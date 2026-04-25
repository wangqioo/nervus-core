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


def _text(el) -> str:
    if el is None:
        return ""
    return el.get_text(strip=True)


def _favicon_for(url: str) -> str:
    parsed = urlparse(url)
    if "weixin.qq.com" in parsed.netloc:
        return "https://res.wx.qq.com/a/wx_fed/assets/res/NTI4MWU5.ico"
    return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"


def _jsdecode(encoded: str) -> str:
    """解码微信 JsDecode 混淆内容（十六进制转义 + HTML 实体）。"""
    s = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), encoded)
    s = (s.replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#39;", "'")
          .replace("&amp;", "&").replace("&nbsp;", " "))
    return s


def _extract_wechat_content(html: str, soup) -> str:
    """提取微信正文文本，优先 #js_content，降级到 JsDecode 内联脚本。"""
    content_el = soup.select_one("#js_content")
    if content_el:
        for img in content_el.find_all("img", attrs={"data-src": True}):
            img["src"] = img["data-src"]
        text = content_el.get_text("\n", strip=True)
        if text.strip():
            return text.strip()

    for pattern in [
        r'\bcontent_noencode\s*:\s*JsDecode\([\'"]([^\'"]+)[\'"]\)',
        r'\bcontent\s*:\s*JsDecode\([\'"]([^\'"]+)[\'"]\)',
    ]:
        m = re.search(pattern, html)
        if m:
            decoded_html = _jsdecode(m.group(1))
            try:
                inner = _bs(decoded_html)
                text = inner.get_text("\n", strip=True)
                if text.strip():
                    return text.strip()
            except Exception:
                pass

    return _meta(html, "og:description")


def _extract_wechat_cover(html: str, soup) -> str | None:
    """提取微信文章封面图：og:image 优先，其次 #js_content 首图。"""
    og = _meta(html, "og:image")
    if og:
        return og
    content_el = soup.select_one("#js_content")
    if content_el:
        img = content_el.find("img", attrs={"data-src": True})
        if img:
            return img["data-src"]
    return None


def _wechat_fallback(url: str, reason: str = "") -> dict:
    return {
        "summary": "微信公众号文章",
        "description": reason or f"来源：{url}",
        "keywords": ["公众号", "微信"],
        "highlights": [],
        "og_image": None,
        "favicon_url": "https://res.wx.qq.com/a/wx_fed/assets/res/NTI4MWU5.ico",
        "_content": "",
    }


def _html_to_markdown(el) -> str:
    """递归把微信正文 HTML 转成 Markdown，图片经由 /api/files/image-proxy 代理。"""
    from bs4 import NavigableString, Tag

    def walk(node, depth=0) -> str:
        if isinstance(node, NavigableString):
            t = str(node)
            return t if t.strip() else (" " if t else "")
        if not isinstance(node, Tag):
            return ""

        tag = node.name.lower() if node.name else ""
        children = "".join(walk(c, depth) for c in node.children).strip()

        if tag in ("script", "style", "svg"):
            return ""
        if tag in ("p", "div", "section"):
            return f"\n\n{children}\n\n" if children else ""
        if tag == "br":
            return "\n"
        if tag == "h1":
            return f"\n\n# {children}\n\n"
        if tag == "h2":
            return f"\n\n## {children}\n\n"
        if tag == "h3":
            return f"\n\n### {children}\n\n"
        if tag in ("h4", "h5", "h6"):
            return f"\n\n#### {children}\n\n"
        if tag in ("strong", "b"):
            return f"**{children}**" if children else ""
        if tag in ("em", "i"):
            return f"*{children}*" if children else ""
        if tag == "blockquote":
            lines = children.splitlines()
            return "\n" + "\n".join(f"> {l}" for l in lines) + "\n"
        if tag == "ul":
            items = [f"- {walk(li).strip()}" for li in node.find_all("li", recursive=False)]
            return "\n" + "\n".join(items) + "\n"
        if tag == "ol":
            items = [f"{i+1}. {walk(li).strip()}" for i, li in enumerate(node.find_all("li", recursive=False))]
            return "\n" + "\n".join(items) + "\n"
        if tag == "li":
            return children
        if tag == "a":
            href = node.get("href", "")
            return f"[{children}]({href})" if href and children else children
        if tag == "img":
            src = node.get("src") or node.get("data-src") or ""
            alt = node.get("alt") or node.get("data-alt") or ""
            if src:
                proxied = f"/api/files/image-proxy?url={src}"
                return f"\n\n![{alt}]({proxied})\n\n"
            return ""
        if tag == "code":
            return f"`{children}`"
        if tag == "pre":
            return f"\n\n```\n{children}\n```\n\n"
        if tag == "hr":
            return "\n\n---\n\n"
        return children

    result = walk(el)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


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

        title = d.get("title") or d.get("name") or ""
        description = d.get("description") or d.get("summary") or ""
        og_image = d.get("cover") or d.get("image") or d.get("og_image") or d.get("thumbnail")
        author = d.get("author") or d.get("source_name") or ""
        raw_kw = d.get("keywords") or d.get("tags") or []
        keywords = raw_kw if isinstance(raw_kw, list) else [k.strip() for k in str(raw_kw).split(",") if k.strip()]
        content = d.get("content") or d.get("text") or ""

        return {
            "summary": (title or url)[:50],
            "description": (f"{author}  {description}".strip() or f"来自 {urlparse(url).netloc}")[:200],
            "keywords": keywords or [urlparse(url).netloc.lstrip("www.")],
            "highlights": [],
            "og_image": og_image,
            "favicon_url": _favicon_for(url),
            "_content": content[:2000] if content else "",
        }
    except Exception:
        return None


async def fetch_wechat_summary(url: str) -> dict:
    """抓取微信公众号文章，返回结构化摘要字段（含 _content 供 analyzer 做 AI 增强）。"""
    headers = {
        "User-Agent": _WX_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://mp.weixin.qq.com/",
    }

    html = ""
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers) as client:
            r = await client.get(url)
            if "text/html" not in r.headers.get("content-type", ""):
                return _wechat_fallback(url, "非 HTML 页面")
            html = r.text
    except Exception as e:
        return _wechat_fallback(url, f"网络请求失败: {e}")

    if not html:
        return _wechat_fallback(url, "页面内容为空")

    try:
        soup = _bs(html)
    except Exception as e:
        return _wechat_fallback(url, f"HTML 解析失败: {e}")

    for sel in ["script", "style", "svg",
                ".qr_code_pc_outer", ".tips_global", ".weapp_text_link",
                "#js_pc_qr_code", ".rich_media_tool", ".Reward", ".FollowButton"]:
        for el in soup.select(sel):
            el.decompose()

    title = (
        _text(soup.select_one("#activity-name"))
        or _text(soup.select_one(".rich_media_title"))
        or _meta(html, "og:title")
        or _meta(html, "twitter:title", "name")
        or "微信公众号文章"
    )
    author = (
        _text(soup.select_one("#js_name"))
        or _text(soup.select_one(".rich_media_meta_text"))
        or ""
    )
    pub_time = _text(soup.select_one("#publish_time")) or ""
    if not pub_time:
        metas = soup.select(".rich_media_meta_text")
        if metas:
            pub_time = _text(metas[-1])

    og_image = _extract_wechat_cover(html, soup)
    content_text = _extract_wechat_content(html, soup)[:3000].strip()
    favicon_url = "https://res.wx.qq.com/a/wx_fed/assets/res/NTI4MWU5.ico"

    desc = f"公众号：{author}  {pub_time}".strip() or f"来源：{url}"

    return {
        "summary": title[:50],
        "description": desc[:200],
        "keywords": ["公众号", "微信"] + ([author] if author else []),
        "highlights": [],
        "og_image": og_image,
        "favicon_url": favicon_url,
        "_content": content_text,
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
            or _meta(html, "title", "name")
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
    """提取微信公众号文章全文，返回 Markdown 格式（含 JsDecode 降级）。"""
    headers = {
        "User-Agent": _WX_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://mp.weixin.qq.com/",
    }
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers) as client:
            r = await client.get(url)
            html = r.text
    except Exception as e:
        return {"error": f"请求失败: {e}"}

    try:
        soup = _bs(html)
    except Exception as e:
        return {"error": f"解析失败: {e}"}

    for sel in ["script", "style", "svg", ".qr_code_pc_outer", ".tips_global",
                ".weapp_text_link", "#js_pc_qr_code", ".rich_media_tool",
                ".Reward", ".FollowButton"]:
        for el in soup.select(sel):
            el.decompose()

    title = (
        _text(soup.select_one("#activity-name"))
        or _text(soup.select_one(".rich_media_title"))
        or _meta(html, "og:title")
        or "微信文章"
    )
    author = _text(soup.select_one("#js_name")) or ""
    pub_time = _text(soup.select_one("#publish_time")) or ""
    if not pub_time:
        metas = soup.select(".rich_media_meta_text")
        if metas:
            pub_time = _text(metas[-1])

    content_el = soup.select_one("#js_content")

    if not content_el or not content_el.get_text(strip=True):
        for pattern in [
            r'\bcontent_noencode\s*:\s*JsDecode\([\'"]([^\'"]+)[\'"]\)',
            r'\bcontent\s*:\s*JsDecode\([\'"]([^\'"]+)[\'"]\)',
        ]:
            m = re.search(pattern, html)
            if m:
                decoded_html = _jsdecode(m.group(1))
                try:
                    content_el = _bs(f"<div>{decoded_html}</div>")
                except Exception:
                    pass
                break

    if not content_el:
        return {"error": "无法提取文章正文"}

    for img in content_el.find_all("img", attrs={"data-src": True}):
        img["src"] = img["data-src"]
        img.attrs = {"src": img["data-src"]}

    md = _html_to_markdown(content_el)

    return {
        "title": title,
        "author": author,
        "pub_time": pub_time,
        "markdown": md.strip(),
    }
