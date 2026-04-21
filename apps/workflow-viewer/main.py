"""
Workflow Viewer App — Arbor Flow 可视化
通过 Arbor Core API 拉取 Flow 配置和执行日志，
提供一个静态 HTML 页面（/ui）展示节点图和实时事件流。
"""

import os
import httpx
from datetime import datetime
from fastapi.responses import HTMLResponse

import sys
sys.path.insert(0, "/app/nervus-sdk")
from nervus_sdk import NervusApp

nervus = NervusApp("workflow-viewer")

ARBOR_URL = os.getenv("ARBOR_URL", "http://arbor-core:8090")

# ── Actions ───────────────────────────────────────────

@nervus.action("get_flows")
async def action_get_flows(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{ARBOR_URL}/flows")
        return resp.json()

@nervus.action("get_logs")
async def action_get_logs(payload: dict) -> dict:
    limit   = int(payload.get("limit", 50))
    flow_id = payload.get("flow_id", "")
    url = f"{ARBOR_URL}/logs?limit={limit}"
    if flow_id:
        url += f"&flow_id={flow_id}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        return resp.json()

# ── REST API ──────────────────────────────────────────

@nervus._api.get("/flows")
async def proxy_flows():
    return await action_get_flows({})

@nervus._api.get("/logs")
async def proxy_logs(limit: int = 50, flow_id: str = ""):
    return await action_get_logs({"limit": limit, "flow_id": flow_id})

@nervus._api.get("/apps")
async def proxy_apps():
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{ARBOR_URL}/apps/list")
        return resp.json()

@nervus._api.get("/status")
async def proxy_status():
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{ARBOR_URL}/status")
        return resp.json()

# ── 可视化前端 ────────────────────────────────────────

@nervus._api.get("/ui", response_class=HTMLResponse)
async def viewer_ui():
    """Flow 可视化仪表盘"""
    return HTMLResponse(content=_HTML)

@nervus.state
async def get_state():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ARBOR_URL}/status")
            data = resp.json()
            return {"arbor_status": data.get("status", "unknown")}
    except Exception:
        return {"arbor_status": "unreachable"}


_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nervus Workflow Viewer</title>
<style>
  :root {
    --bg:#0d0d0d; --surface:#161616; --surface2:#1e1e1e;
    --border:rgba(255,255,255,0.07); --accent:#00D4AA;
    --warn:#FF6B35; --text:#e8e8e8; --text2:#888; --radius:10px;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--text); font-family:-apple-system,sans-serif; padding:24px; }
  h1 { font-size:22px; font-weight:700; margin-bottom:4px; }
  h1 span { color:var(--accent); }
  .subtitle { font-size:13px; color:var(--text2); margin-bottom:24px; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media(max-width:900px) { .grid { grid-template-columns:1fr; } }
  .panel { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:18px; }
  .panel-title { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.6px; color:var(--text2); margin-bottom:14px; }
  .flow-card { background:var(--surface2); border-radius:8px; padding:12px 14px; margin-bottom:8px; cursor:pointer; border:1px solid transparent; transition:.15s; }
  .flow-card:hover, .flow-card.active { border-color:var(--accent); }
  .flow-id { font-size:13px; font-weight:600; color:var(--accent); }
  .flow-desc { font-size:12px; color:var(--text2); margin-top:2px; }
  .flow-trigger { font-size:11px; color:var(--text2); margin-top:6px; }
  .flow-trigger span { background:rgba(0,212,170,.12); color:var(--accent); padding:1px 6px; border-radius:4px; }
  .steps { margin-top:10px; }
  .step { display:flex; align-items:flex-start; gap:10px; padding:8px 0; border-top:1px solid var(--border); }
  .step-num { background:var(--accent); color:#000; font-size:10px; font-weight:700; width:18px; height:18px; border-radius:50%; display:flex; align-items:center; justify-content:center; flex-shrink:0; margin-top:1px; }
  .step-type { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.4px; color:var(--text2); }
  .step-detail { font-size:12px; color:var(--text); margin-top:2px; }
  .log-item { display:flex; gap:10px; padding:8px 0; border-bottom:1px solid var(--border); font-size:12px; }
  .log-dot { width:6px; height:6px; border-radius:50%; background:var(--accent); flex-shrink:0; margin-top:4px; }
  .log-dot.error { background:var(--warn); }
  .log-flow { font-weight:600; color:var(--text); }
  .log-time { color:var(--text2); font-size:11px; }
  .stat-row { display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--border); }
  .stat-label { font-size:13px; color:var(--text2); }
  .stat-value { font-size:13px; font-weight:600; color:var(--text); }
  #refresh-btn { background:var(--accent); color:#000; border:none; border-radius:6px; padding:6px 14px; font-size:12px; font-weight:600; cursor:pointer; float:right; margin-top:-4px; }
  .badge { display:inline-block; border-radius:4px; padding:1px 6px; font-size:10px; font-weight:600; }
  .badge-green { background:rgba(0,212,170,.15); color:var(--accent); }
  .badge-warn  { background:rgba(255,107,53,.15); color:var(--warn); }
  .empty { color:var(--text2); font-size:13px; text-align:center; padding:20px 0; }
</style>
</head>
<body>
<h1>Nerv<span>us</span> Workflow Viewer</h1>
<p class="subtitle">Arbor Core Flow 可视化 · 实时执行日志</p>

<div class="grid">
  <!-- 左：Flow 列表 -->
  <div class="panel">
    <div class="panel-title">Flow 配置 <button id="refresh-btn" onclick="loadAll()">刷新</button></div>
    <div id="flows-list"><div class="empty">加载中...</div></div>
  </div>

  <!-- 右：详情 + 日志 -->
  <div>
    <div class="panel" style="margin-bottom:16px">
      <div class="panel-title">系统状态</div>
      <div id="status-panel"><div class="empty">加载中...</div></div>
    </div>
    <div class="panel">
      <div class="panel-title">执行日志（最近 30 条）</div>
      <div id="logs-list"><div class="empty">加载中...</div></div>
    </div>
  </div>
</div>

<script>
let flows = [];
let activeFlow = null;

async function loadAll() {
  await Promise.all([loadFlows(), loadLogs(), loadStatus()]);
}

async function loadFlows() {
  try {
    const data = await (await fetch('/flows')).json();
    flows = data.flows || [];
    renderFlows();
  } catch(e) {
    document.getElementById('flows-list').innerHTML = '<div class="empty">无法连接 Arbor Core</div>';
  }
}

function renderFlows() {
  const el = document.getElementById('flows-list');
  if (!flows.length) { el.innerHTML = '<div class="empty">暂无 Flow</div>'; return; }
  el.innerHTML = flows.map((f,i) => `
    <div class="flow-card ${activeFlow===f.id?'active':''}" onclick="selectFlow('${f.id}')">
      <div class="flow-id">${f.id}</div>
      <div class="flow-desc">${f.description || ''}</div>
      <div class="flow-trigger">触发: <span>${f.trigger || ''}</span></div>
      ${activeFlow === f.id ? renderSteps(f.steps || []) : ''}
    </div>
  `).join('');
}

function renderSteps(steps) {
  if (!steps.length) return '';
  return '<div class="steps">' + steps.map((s,i) => {
    let type = s.app ? 'action' : s.emit ? 'emit' : s.notify ? 'notify' : s.context ? 'context' : '?';
    let detail = s.app ? `${s.app} → ${s.action}` : s.emit || s.notify || JSON.stringify(s).slice(0,60);
    return `<div class="step"><div class="step-num">${i+1}</div><div><div class="step-type">${type}</div><div class="step-detail">${detail}</div></div></div>`;
  }).join('') + '</div>';
}

function selectFlow(id) {
  activeFlow = activeFlow === id ? null : id;
  renderFlows();
}

async function loadLogs() {
  try {
    const data = await (await fetch('/logs?limit=30')).json();
    const logs = data.logs || [];
    const el = document.getElementById('logs-list');
    if (!logs.length) { el.innerHTML = '<div class="empty">暂无执行记录</div>'; return; }
    el.innerHTML = logs.reverse().map(l => `
      <div class="log-item">
        <div class="log-dot ${l.status==='error'?'error':''}"></div>
        <div>
          <div class="log-flow">${l.flow_id || l.subject || '—'} <span class="badge ${l.status==='error'?'badge-warn':'badge-green'}">${l.status||'ok'}</span></div>
          <div class="log-time">${formatTime(l.created_at)}</div>
        </div>
      </div>
    `).join('');
  } catch(e) {}
}

async function loadStatus() {
  try {
    const data = await (await fetch('/status')).json();
    const apps = await (await fetch('/apps')).json();
    const el = document.getElementById('status-panel');
    const appList = apps.apps || [];
    el.innerHTML = `
      <div class="stat-row"><span class="stat-label">Arbor Core 状态</span><span class="stat-value"><span class="badge badge-green">${data.status||'ok'}</span></span></div>
      <div class="stat-row"><span class="stat-label">已注册 App</span><span class="stat-value">${appList.length}</span></div>
      <div class="stat-row"><span class="stat-label">已加载 Flow</span><span class="stat-value">${flows.length}</span></div>
      <div class="stat-row" style="border:none"><span class="stat-label">Embedding 队列</span><span class="stat-value">${data.embedding?.queue_size ?? '—'}</span></div>
    `;
  } catch(e) {
    document.getElementById('status-panel').innerHTML = '<div class="empty">无法获取状态</div>';
  }
}

function formatTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso), now = new Date(), diff = now - d;
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return Math.floor(diff/60000) + ' 分钟前';
    return (d.getMonth()+1) + '/' + d.getDate() + ' ' + String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
  } catch { return iso; }
}

loadAll();
setInterval(loadAll, 15000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    nervus.run(port=int(os.getenv("APP_PORT", "8014")))
