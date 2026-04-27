"""
Nervus 开发用静态服务器
- 托管所有 App HTML 页面
- /api/* 请求代理到 Arbor (http://localhost:8090)
- 内置 App 导航首页
用法: python dev-server.py [--port 8080] [--arbor http://localhost:8090]
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

try:
    from aiohttp import web, ClientSession, ClientTimeout
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

# ── 首页 HTML（App 导航页）──────────────────────────────────────
APPS_DIR = Path(__file__).parent / "apps"

APP_META = {
    "model-manager":    {"name": "模型管理",   "icon": "🤖", "desc": "本地/云端模型管理与测试"},
    "knowledge-base":   {"name": "知识库",     "icon": "📚", "desc": "知识写入与语义搜索"},
    "file-manager":     {"name": "文件管理",   "icon": "📁", "desc": "文件浏览与管理"},
    "life-memory":      {"name": "生活记忆",   "icon": "💭", "desc": "生活事件记录与回溯"},
    "meeting-notes":    {"name": "会议记录",   "icon": "📝", "desc": "会议记录与 AI 摘要"},
    "photo-scanner":    {"name": "照片扫描",   "icon": "📷", "desc": "照片 OCR 与分析"},
    "pdf-extractor":    {"name": "PDF 提取",   "icon": "📄", "desc": "PDF 内容提取与分析"},
    "rss-reader":       {"name": "RSS 阅读",   "icon": "📰", "desc": "RSS 订阅与阅读"},
    "reminder":         {"name": "提醒",       "icon": "⏰", "desc": "智能提醒管理"},
    "calendar":         {"name": "日历",       "icon": "📅", "desc": "日程管理"},
    "calorie-tracker":  {"name": "卡路里",     "icon": "🥗", "desc": "饮食与卡路里追踪"},
    "personal-notes":   {"name": "个人笔记",   "icon": "✏️", "desc": "笔记与备忘"},
    "video-transcriber":{"name": "视频转文字", "icon": "🎬", "desc": "视频音频转写"},
    "workflow-viewer":  {"name": "工作流",     "icon": "⚙️", "desc": "Flow 编排查看"},
    "sense":            {"name": "Sense",      "icon": "🧠", "desc": "感知与数据分析"},
    "status-sense":     {"name": "系统状态",   "icon": "📊", "desc": "平台运行状态"},
}

def build_index_html(arbor_url: str) -> str:
    cards = []
    for app_id, meta in APP_META.items():
        app_path = APPS_DIR / app_id
        has_html = (app_path / "index.html").exists()
        if not has_html:
            # try frontend/index.html
            has_html = (app_path / "frontend" / "index.html").exists()
        disabled = "" if has_html else 'style="opacity:.4;cursor:not-allowed;"'
        href = f"/apps/{app_id}/" if has_html else "#"
        cards.append(f"""
        <a class="card" href="{href}" {disabled}>
          <div class="icon">{meta["icon"]}</div>
          <div class="info">
            <div class="app-name">{meta["name"]}</div>
            <div class="app-desc">{meta["desc"]}</div>
          </div>
        </a>""")

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nervus 平台</title>
<style>
  :root {{ --bg:#f5f5f7; --card:#fff; --border:#e0e0e0; --text:#1d1d1f;
           --sub:#6e6e73; --accent:#0071e3; --radius:14px; --shadow:0 2px 12px rgba(0,0,0,.08); }}
  @media (prefers-color-scheme:dark) {{
    :root {{ --bg:#1c1c1e; --card:#2c2c2e; --border:#3a3a3c; --text:#f5f5f7; --sub:#98989d; }}
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,sans-serif; background:var(--bg); color:var(--text);
          min-height:100vh; padding:32px 20px; }}
  header {{ margin-bottom:32px; }}
  h1 {{ font-size:28px; font-weight:700; }}
  .meta {{ color:var(--sub); font-size:14px; margin-top:6px; }}
  .status {{ display:inline-flex; align-items:center; gap:6px; font-size:13px;
             padding:4px 12px; border-radius:20px; margin-top:12px; }}
  .status.online {{ background:rgba(52,199,89,.15); color:#34c759; }}
  .status.offline {{ background:rgba(255,59,48,.12); color:#ff3b30; }}
  .dot {{ width:7px; height:7px; border-radius:50%; background:currentColor; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:14px; }}
  .card {{ display:flex; gap:14px; align-items:center; background:var(--card);
           border-radius:var(--radius); box-shadow:var(--shadow); padding:18px;
           text-decoration:none; color:var(--text); transition:transform .12s,box-shadow .12s; }}
  .card:hover {{ transform:translateY(-2px); box-shadow:0 6px 20px rgba(0,0,0,.12); }}
  .icon {{ font-size:32px; flex-shrink:0; }}
  .app-name {{ font-weight:600; font-size:15px; }}
  .app-desc {{ color:var(--sub); font-size:12px; margin-top:3px; }}
  footer {{ margin-top:40px; color:var(--sub); font-size:12px; text-align:center; }}
</style>
</head>
<body>
<header>
  <h1>🧠 Nervus 平台</h1>
  <p class="meta">AI 增强的个人操作系统</p>
  <div class="status offline" id="arbor-status">
    <span class="dot"></span><span id="arbor-text">检测 Arbor 状态...</span>
  </div>
</header>
<div class="grid">{"".join(cards)}</div>
<footer>Nervus v1 &nbsp;·&nbsp; Arbor: {arbor_url}</footer>

<script>
async function checkArbor() {{
  try {{
    const r = await fetch('/healthz', {{ signal: AbortSignal.timeout(3000) }});
    const ok = r.ok;
    const el = document.getElementById('arbor-status');
    const txt = document.getElementById('arbor-text');
    el.className = 'status ' + (ok ? 'online' : 'offline');
    txt.textContent = ok ? 'Arbor 在线' : 'Arbor 离线 (docker compose up)';
  }} catch(e) {{
    document.getElementById('arbor-text').textContent = 'Arbor 离线 (docker compose up)';
  }}
}}
checkArbor();
setInterval(checkArbor, 10000);
</script>
</body>
</html>"""


def build_simple_server(port: int, arbor_url: str):
    """纯标准库版本（无 aiohttp）"""
    import http.server
    import urllib.request
    import urllib.error

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # 静默日志

        def do_GET(self):
            # 首页
            if self.path in ('/', ''):
                html = build_index_html(arbor_url).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return

            # /healthz → 代理到 Arbor
            if self.path.startswith('/healthz') or self.path.startswith('/api/'):
                self._proxy(arbor_url + self.path)
                return

            # /apps/{id}/ 或 /apps/{id}/frontend/
            if self.path.startswith('/apps/'):
                parts = self.path.lstrip('/').split('/', 2)
                if len(parts) >= 2:
                    app_id = parts[1]
                    # 找 index.html
                    candidates = [
                        APPS_DIR / app_id / "index.html",
                        APPS_DIR / app_id / "frontend" / "index.html",
                        APPS_DIR / app_id / "dist" / "index.html",
                    ]
                    for p in candidates:
                        if p.exists():
                            content = p.read_bytes()
                            self.send_response(200)
                            self.send_header('Content-Type', 'text/html; charset=utf-8')
                            self.send_header('Content-Length', str(len(content)))
                            self.end_headers()
                            self.wfile.write(content)
                            return

            # 其他静态文件（图片、CSS 等）
            super().do_GET()

        def do_POST(self):
            if self.path.startswith('/api/') or self.path.startswith('/healthz'):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length) if length else b''
                self._proxy(arbor_url + self.path, method='POST', body=body)
            else:
                self.send_error(404)

        def do_PUT(self):
            if self.path.startswith('/api/'):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length) if length else b''
                self._proxy(arbor_url + self.path, method='PUT', body=body)
            else:
                self.send_error(404)

        def _proxy(self, url: str, method: str = 'GET', body: bytes = b''):
            try:
                req = urllib.request.Request(url, data=body or None, method=method)
                req.add_header('Content-Type', self.headers.get('Content-Type', 'application/json'))
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    self.send_response(resp.status)
                    self.send_header('Content-Type', resp.headers.get('Content-Type', 'application/json'))
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(data)
            except urllib.error.HTTPError as e:
                data = e.read()
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:
                msg = json.dumps({"error": "Arbor 未运行，请 docker compose up", "detail": str(exc)}).encode()
                self.send_response(503)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

    Handler.directory = str(APPS_DIR)
    server = http.server.HTTPServer(('0.0.0.0', port), Handler)
    print(f"Nervus Dev Server 已启动: http://0.0.0.0:{port}")
    print(f"Arbor 代理: {arbor_url}")
    print(f"按 Ctrl+C 停止")
    server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--arbor', default=os.getenv('ARBOR_URL', 'http://localhost:8090'))
    args = parser.parse_args()
    build_simple_server(args.port, args.arbor)
