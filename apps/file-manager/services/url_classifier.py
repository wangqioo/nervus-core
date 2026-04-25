import re
from urllib.parse import urlparse, urljoin

import httpx

from utils.config import URL_PATTERNS, LINKBOX_API_URL, LINKBOX_API_KEY

_WX_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36 "
    "MicroMessenger/8.0.43.2560(0x28002B37) NetType/WIFI Language/zh_CN"
)
_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def classify_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        for link_type, patterns in URL_PATTERNS.items():
            if any(p in host for p in patterns):
                return link_type
    except Exception:
        pass
    return "generic"


def _meta(html: str, prop: str, attr: str = "property") -> str:
    for pat in [
        rf'<meta[^>]*{attr}=["\'](?:{prop})["\'][^>]*content=["\'](.*?)["\']',
        rf'<meta[^>]*content=["\'](.*?)["\'][^>]*{attr}=["\'](?:{prop})["\']',
    ]:
        m = re.search(pat, html, re.I | re.S)
        if m:
            return m.group(1).strip()
    return ""


def _bs(html: str):
    from bs4 import BeautifulSoup
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


async def fetch_linkbox(url: str) -> dict | None:
    if not LINKBOX_API_URL or not LINKBOX_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                LINKBOX_API_URL,
                json={"url": url},
                headers={"Authorization": f"Bearer {LINKBOX_API_KEY}", "Content-Type": "application/json"},
            )
            if r.status_code != 200:
                return None
            d = r.json()
        title = d.get("title") or d.get("summary") or ""
        description = d.get("description") or ""
        content = d.get("content") or ""
        og_image = d.get("cover") or d.get("image") or d.get("og_image")
        keywords = d.get("keywords") or d.get("tags") or []
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]
        return {
            "summary": title[:50],
            "description": description[:200],
            "keywords": keywords[:5],
            "highlights": [],
            "og_image": og_image,
            "favicon_url": None,
            "_content": content[:2000] if content else "",
        }
    except Exception:
        return None


async def fetch_wechat_summary(url: str) -> dict:
    title = author = pub_time = content = og_image = favicon_url = ""
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True,
            headers={"User-Agent": _WX_UA}
        ) as client:
            r = await client.get(url)
            html = r.text

        soup = _bs(html)
        title_tag = soup.find("h1", id="activity-name") or soup.find("h1", class_="rich_media_title")
        title = title_tag.get_text(strip=True) if title_tag else _meta(html, "og:title") or ""

        author_tag = soup.find(id="js_name") or soup.find(class_="rich_media_meta_nickname")
        author = author_tag.get_text(strip=True) if author_tag else ""

        pub_tag = soup.find(id="publish_time") or soup.find(class_="rich_media_meta_text")
        pub_time = pub_tag.get_text(strip=True) if pub_tag else ""

        content_tag = soup.find(id="js_content") or soup.find(class_="rich_media_content")
        if content_tag:
            content = content_tag.get_text(separator="\n", strip=True)[:2000]

        og_image = _meta(html, "og:image") or ""
        favicon_url = "https://mp.weixin.qq.com/favicon.ico"
    except Exception:
        pass

    desc = f"公众号：{author}  {content[:120]}".strip() if author else content[:150]
    return {
        "summary": title[:50],
        "description": desc[:200],
        "keywords": ["公众号", "微信", author] if author else ["公众号", "微信"],
        "highlights": [],
        "og_image": og_image or None,
        "favicon_url": favicon_url or None,
        "_content": content,  # 供 analyzer 做 AI 摘要
    }


async def fetch_bilibili_summary(url: str) -> dict:
    bvid_m = re.search(r"BV[\w]+", url)
    if bvid_m:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid_m.group()}")
                d = r.json().get("data", {})
            title = d.get("title", "B站视频")
            desc = (d.get("desc") or "")[:200]
            pic = d.get("pic") or None
            owner = d.get("owner", {}).get("name", "")
            return {
                "summary": title[:50],
                "description": f"UP主：{owner}  {desc}".strip(),
                "keywords": ["B站", "视频", owner],
                "highlights": [],
                "og_image": pic,
                "favicon_url": "https://www.bilibili.com/favicon.ico",
                "_content": f"{title}\n{desc}",
            }
        except Exception:
            pass
    return await fetch_generic_summary(url)


async def fetch_generic_summary(url: str) -> dict:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    title = description = og_image = favicon_url = None

    try:
        async with httpx.AsyncClient(
            timeout=12, follow_redirects=True,
            headers={"User-Agent": _DESKTOP_UA}
        ) as client:
            r = await client.get(url)
            html = r.text

        _title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = (
            _meta(html, "og:title")
            or _meta(html, "twitter:title", "name")
            or (_title_m.group(1) if _title_m else None)
            or parsed.netloc
        )
        title = re.sub(r"<[^>]+>", "", title).strip()

        description = (
            _meta(html, "og:description")
            or _meta(html, "description", "name")
            or ""
        )

        og_raw = _meta(html, "og:image") or _meta(html, "twitter:image", "name")
        if og_raw:
            og_image = og_raw if og_raw.startswith("http") else urljoin(base, og_raw)

        fav_raw = ""
        for pat in [
            r'<link[^>]*rel=["\'](?:shortcut icon|icon)["\'][^>]*href=["\'](.*?)["\']',
            r'<link[^>]*href=["\'](.*?)["\'][^>]*rel=["\'](?:shortcut icon|icon)["\']',
        ]:
            m = re.search(pat, html, re.I)
            if m:
                fav_raw = m.group(1)
                break
        favicon_url = (
            (fav_raw if fav_raw.startswith("http") else urljoin(base, fav_raw))
            if fav_raw else f"{base}/favicon.ico"
        )

    except Exception:
        pass

    return {
        "summary": (title or parsed.netloc)[:50],
        "description": (description or f"来自 {parsed.netloc}")[:200],
        "keywords": [parsed.netloc.lstrip("www.")],
        "highlights": [],
        "og_image": og_image,
        "favicon_url": favicon_url,
        "_content": description or "",
    }


async def extract_wechat_markdown(url: str) -> dict:
    """提取微信公众号文章全文，返回 Markdown 格式。"""
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True,
            headers={"User-Agent": _WX_UA}
        ) as client:
            r = await client.get(url)
            html = r.text

        soup = _bs(html)
        title_tag = soup.find("h1", id="activity-name") or soup.find("h1", class_="rich_media_title")
        title = title_tag.get_text(strip=True) if title_tag else "未知标题"

        content_tag = soup.find(id="js_content") or soup.find(class_="rich_media_content")
        if not content_tag:
            return {"error": "未找到正文内容"}

        lines = []
        for el in content_tag.find_all(["p", "h2", "h3", "li", "blockquote"]):
            text = el.get_text(separator=" ", strip=True)
            if text:
                lines.append(text)

        return {"title": title, "markdown": "\n\n".join(lines)}
    except Exception as e:
        return {"error": str(e)}
