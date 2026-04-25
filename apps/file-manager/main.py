import os
import sys

sys.path.insert(0, "/app/nervus-sdk")

from nervus_sdk import NervusApp
from fastapi.responses import Response
import httpx

from routers.files import router as files_router

nervus = NervusApp("file-manager")
nervus._api.include_router(files_router)

_WX_IMG_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.43 NetType/WIFI Language/zh_CN"
)


@nervus._api.get("/image-proxy")
async def image_proxy(url: str):
    """微信 CDN 图片代理，绕过防盗链。"""
    is_wechat = any(k in url for k in ("qpic.cn", "mmbiz", "weixin"))
    headers = {"Referer": "https://mp.weixin.qq.com/"}
    if is_wechat:
        headers["User-Agent"] = _WX_IMG_UA
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
        return Response(content=r.content, media_type=r.headers.get("content-type", "image/jpeg"))
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(502, f"图片代理失败: {e}")


@nervus.state
async def get_state():
    from services.storage import get_all_files
    files = get_all_files()
    by_type: dict = {}
    for f in files:
        by_type[f.type.value] = by_type.get(f.type.value, 0) + 1
    return {"total": len(files), "by_type": by_type}


if __name__ == "__main__":
    nervus.run(port=int(os.getenv("APP_PORT", "8015")))
