import os
from pathlib import Path

import httpx
from fastapi import Query as QParam
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from nervus_sdk import NervusApp

from backend.routers import files
from backend.services import storage

nervus = NervusApp("file-manager")
nervus._api.include_router(files.router)

_WX_IMG_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.43 NetType/WIFI Language/zh_CN"
)


@nervus._api.get("/api/image-proxy")
async def image_proxy(url: str = QParam(...)):
    """Proxy WeChat CDN images to bypass hotlink protection."""
    is_wechat = any(k in url for k in ("qpic.cn", "mmbiz", "weixin"))
    headers = {"Referer": "https://mp.weixin.qq.com/"}
    if is_wechat:
        headers["User-Agent"] = _WX_IMG_UA
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
        content_type = r.headers.get("content-type", "image/jpeg")
        return Response(content=r.content, media_type=content_type)
    except Exception:
        raise


@nervus.state
async def get_state():
    all_files = storage.get_all_files()
    by_type: dict = {}
    for f in all_files:
        by_type[f.type.value] = by_type.get(f.type.value, 0) + 1
    return {"total_files": len(all_files), "by_type": by_type}


FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    nervus._api.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="assets",
    )

    @nervus._api.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        return FileResponse(str(FRONTEND_DIST / "index.html"))


if __name__ == "__main__":
    nervus.run(port=int(os.getenv("APP_PORT", "8015")))
