# -*- coding: utf-8 -*-
"""
内存监控看门狗 API 端点

提供内存使用情况的实时监控和报告功能
"""

import asyncio
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from typing import Dict, Any, List

from core.utils.logger import get_logger

logger = get_logger("memory_watchdog.api")

router = APIRouter(prefix="/memory", tags=["memory-watchdog"])


@router.get("/status")
async def get_memory_status() -> Dict[str, Any]:
    """获取当前内存状态"""
    try:
        from core.utils.memory_watchdog import get_memory_status
        return get_memory_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report")
async def get_memory_report() -> Dict[str, Any]:
    """获取内存监控报告"""
    try:
        from core.utils.memory_watchdog import get_memory_watchdog
        watchdog = get_memory_watchdog()
        return watchdog.report()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-objects")
async def get_top_memory_objects(top_n: int = 20) -> List[Dict[str, Any]]:
    """获取占用内存最多的Python对象（按需深度分析，会遍历 gc.get_objects()）

    注意：analyze_top_objects 是同步阻塞函数，必须放到线程池里执行，
    否则会卡死 FastAPI 主事件循环（3GB+ 进程会卡几十秒）
    """
    try:
        from core.utils.memory_watchdog import get_memory_watchdog
        watchdog = get_memory_watchdog()
        # 用 to_thread 把同步阻塞的 gc 遍历放到线程池里
        top_objects = await asyncio.to_thread(watchdog.analyze_top_objects, top_n)

        return [
            {
                "type": type_name,
                "count": count,
                "size_mb": round(size / (1024 * 1024), 2),
            }
            for type_name, count, size in top_objects
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tracemalloc/diff")
async def get_tracemalloc_diff(top_n: int = 25) -> List[Dict[str, Any]]:
    """对比启动基线，返回内存增长最多的分配点（找泄漏源的核心接口）

    tracemalloc 记录每个内存分配的调用栈，对比启动基线，
    就能精确定位"哪些代码分配的内存最多且没释放"。
    开销远小于 /top-objects 和 /leak-analysis（不遍历 gc.get_objects()）。
    """
    try:
        from core.utils.memory_watchdog import get_memory_watchdog
        watchdog = get_memory_watchdog()
        # tracemalloc.take_snapshot() 是同步的，放线程池避免阻塞事件循环
        return await asyncio.to_thread(watchdog.get_tracemalloc_diff, top_n)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tracemalloc/top")
async def get_tracemalloc_top(top_n: int = 25) -> List[Dict[str, Any]]:
    """返回当前内存占用最多的分配点（不对比基线）

    用于看"此刻谁占的内存最多"，和 /tracemalloc/diff 配合使用。
    """
    try:
        from core.utils.memory_watchdog import get_memory_watchdog
        watchdog = get_memory_watchdog()
        return await asyncio.to_thread(watchdog.get_tracemalloc_top, top_n)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sample-lists")
async def sample_large_lists(sample_size: int = 30) -> List[Dict[str, Any]]:
    """采样最大的 list 对象，返回内容和引用者（轻量，定位泄漏源）

    不调 tracemalloc.take_snapshot()，直接遍历 gc 对象找大 list，
    返回 repr(200字符) + 长度 + 引用者。比 /tracemalloc/* 快得多。
    """
    try:
        from core.utils.memory_watchdog import get_memory_watchdog
        watchdog = get_memory_watchdog()
        return await asyncio.to_thread(watchdog.sample_large_lists, sample_size)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/snapshot")
async def take_memory_snapshot() -> Dict[str, Any]:
    """手动拍摄内存快照（按需生成详细快照，会遍历 gc.get_objects()）

    take_detailed_snapshot 是同步阻塞函数，必须放线程池执行。
    """
    try:
        from core.utils.memory_watchdog import get_memory_watchdog
        watchdog = get_memory_watchdog()
        snapshot = await asyncio.to_thread(watchdog.take_detailed_snapshot)

        return {
            "timestamp": snapshot.timestamp,
            "process_rss_mb": round(snapshot.process_rss_mb, 2),
            "process_vms_mb": round(snapshot.process_vms_mb, 2),
            "system_percent": round(snapshot.system_percent, 2),
            "gc_objects": snapshot.gc_objects,
            "loaded_models": snapshot.loaded_models,
            "object_counts": snapshot.object_counts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gc")
async def trigger_garbage_collection() -> Dict[str, Any]:
    """手动触发垃圾回收

    gc.collect() 是同步阻塞，对 3GB+ 进程会卡几秒，放线程池执行。
    """
    try:
        import gc

        def _do_gc():
            before_objects = len(gc.get_objects())
            collected = gc.collect()
            after_objects = len(gc.get_objects())
            return before_objects, collected, after_objects

        before_objects, collected, after_objects = await asyncio.to_thread(_do_gc)

        return {
            "collected_objects": collected,
            "before_objects": before_objects,
            "after_objects": after_objects,
            "freed_objects": before_objects - after_objects,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/leak-analysis")
async def analyze_memory_leak() -> Dict[str, Any]:
    """深度分析内存泄漏源头（按需，会遍历 gc.get_objects()）

    实际逻辑委托给 MemoryWatchdog.analyze_leak_source，
    避免在路由文件里散落 gc 遍历代码。

    注意：analyze_leak_source 是同步阻塞函数，3GB+ 进程会卡 1-5 分钟，
    必须放线程池执行，否则会卡死 FastAPI 主事件循环。
    """
    try:
        from core.utils.memory_watchdog import get_memory_watchdog
        watchdog = get_memory_watchdog()
        return await asyncio.to_thread(watchdog.analyze_leak_source, 10)
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}")


@router.get("/trend")
async def get_memory_trend() -> Dict[str, Any]:
    """获取内存使用趋势"""
    try:
        from core.utils.memory_watchdog import get_memory_watchdog
        watchdog = get_memory_watchdog()
        report = watchdog.report()
        
        return {
            "trend": report.get("trend", {}),
            "summary": report.get("summary", {}),
            "recent_growth": report.get("recent_growth", [])[-10:],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws")
async def websocket_memory_monitor(websocket: WebSocket):
    """WebSocket端点，实时推送内存数据"""
    await websocket.accept()
    
    from core.utils.memory_watchdog import get_memory_watchdog
    watchdog = get_memory_watchdog()
    
    # 订阅更新
    watchdog.subscribe_ws(websocket)
    
    try:
        # 立即发送当前状态（用轻量快照，不调 gc.get_objects()）
        # 详细数据让前端通过 /snapshot、/top-objects 等 API 主动拉取，
        # 避免 WebSocket 首次推送对 3GB+ 进程卡几十秒
        snapshot = watchdog._take_snapshot_fast()
        data: Dict[str, Any] = {
            "type": "memory_snapshot",
            "timestamp": snapshot.timestamp,
            "process_rss_mb": round(snapshot.process_rss_mb, 2),
            "process_vms_mb": round(snapshot.process_vms_mb, 2),
            "system_percent": round(snapshot.system_percent, 2),
        }
        if watchdog._baseline_snapshot:
            data["total_growth_mb"] = round(
                snapshot.process_rss_mb - watchdog._baseline_snapshot.process_rss_mb, 2
            )
        await websocket.send_json(data)
        
        # 保持连接，等待客户端消息
        while True:
            try:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
    finally:
        watchdog.unsubscribe_ws(websocket)


@router.get("/dashboard", response_class=HTMLResponse)
async def memory_dashboard():
    """内存监控面板"""
    html_content = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Memory Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            color: #e6edf3;
            padding: 24px;
        }
        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
        }
        .header h1 {
            font-size: 20px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: 16px;
            font-size: 12px;
            font-weight: 500;
        }
        .status-healthy { background: #1a3a2a; color: #3fb950; }
        .status-warning { background: #3a2a1a; color: #d29922; }
        .status-critical { background: #3a1a1a; color: #f85149; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 20px;
        }
        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 12px;
        }
        .card-title {
            font-size: 12px;
            font-weight: 500;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .card-icon {
            width: 32px;
            height: 32px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
        }
        .card-value {
            font-size: 32px;
            font-weight: 600;
            margin-bottom: 4px;
        }
        .card-unit {
            font-size: 14px;
            color: #8b949e;
        }
        .card-change {
            font-size: 12px;
            margin-top: 8px;
        }
        .change-positive { color: #f85149; }
        .change-negative { color: #3fb950; }
        .chart-container {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 24px;
        }
        .chart-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
        }
        .chart-title {
            font-size: 14px;
            font-weight: 600;
        }
        .chart-canvas {
            width: 100%;
            height: 200px;
            position: relative;
        }
        .chart-bar {
            position: absolute;
            bottom: 0;
            width: 4px;
            background: #58a6ff;
            border-radius: 2px 2px 0 0;
            transition: height 0.3s ease;
        }
        .chart-bar:hover {
            background: #79c0ff;
        }
        .models-list {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 20px;
        }
        .model-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid #21262d;
        }
        .model-item:last-child {
            border-bottom: none;
        }
        .model-name {
            font-size: 14px;
            font-weight: 500;
        }
        .model-status {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
        }
        .model-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }
        .model-loaded .model-dot { background: #3fb950; }
        .model-unloaded .model-dot { background: #484f58; }
        .objects-table {
            width: 100%;
            border-collapse: collapse;
        }
        .objects-table th,
        .objects-table td {
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid #21262d;
        }
        .objects-table th {
            font-size: 12px;
            font-weight: 500;
            color: #8b949e;
            text-transform: uppercase;
        }
        .objects-table td {
            font-size: 13px;
        }
        .progress-bar {
            height: 6px;
            background: #21262d;
            border-radius: 3px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: #58a6ff;
            border-radius: 3px;
            transition: width 0.3s ease;
        }
        .ws-status {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            color: #8b949e;
        }
        .ws-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
        }
        .ws-connected .ws-dot { background: #3fb950; }
        .ws-disconnected .ws-dot { background: #f85149; }
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 Memory Monitor</h1>
        <div class="ws-status" id="wsStatus">
            <span class="ws-dot"></span>
            <span>Connecting...</span>
        </div>
    </div>
    
    <div class="grid">
        <div class="card">
            <div class="card-header">
                <span class="card-title">Process RSS</span>
                <span class="card-icon" style="background: #1a3a5a;">💾</span>
            </div>
            <div class="card-value" id="rssValue">--</div>
            <div class="card-unit">MB</div>
            <div class="card-change" id="rssChange"></div>
        </div>
        
        <div class="card">
            <div class="card-header">
                <span class="card-title">System Usage</span>
                <span class="card-icon" style="background: #1a3a2a;">🖥️</span>
            </div>
            <div class="card-value" id="systemValue">--</div>
            <div class="card-unit">%</div>
            <div class="progress-bar" style="margin-top: 12px;">
                <div class="progress-fill" id="systemProgress" style="width: 0%"></div>
            </div>
        </div>
        
        <div class="card">
            <div class="card-header">
                <span class="card-title">GC Objects</span>
                <span class="card-icon" style="background: #3a2a1a;">♻️</span>
            </div>
            <div class="card-value" id="gcValue">--</div>
            <div class="card-unit">objects</div>
        </div>
        
        <div class="card">
            <div class="card-header">
                <span class="card-title">Total Growth</span>
                <span class="card-icon" style="background: #3a1a1a;">📈</span>
            </div>
            <div class="card-value" id="growthValue">--</div>
            <div class="card-unit">MB</div>
            <div class="card-change" id="growthChange"></div>
        </div>
    </div>
    
    <div class="chart-container">
        <div class="chart-header">
            <span class="chart-title">Memory Timeline</span>
            <span class="status-badge status-healthy" id="statusBadge">Healthy</span>
        </div>
        <div class="chart-canvas" id="chartCanvas"></div>
    </div>
    
    <div class="grid" style="grid-template-columns: 1fr 1fr;">
        <div class="models-list">
            <h3 style="font-size: 14px; margin-bottom: 16px;">Loaded Models</h3>
            <div id="modelsList"></div>
        </div>
        
        <div class="card">
            <h3 style="font-size: 14px; margin-bottom: 16px;">Top Objects</h3>
            <table class="objects-table">
                <thead>
                    <tr>
                        <th>Type</th>
                        <th>Count</th>
                        <th>Size</th>
                    </tr>
                </thead>
                <tbody id="objectsTable"></tbody>
            </table>
        </div>
    </div>
    
    <script>
        const MAX_CHART_POINTS = 60;
        let chartData = [];
        let ws = null;
        let reconnectTimer = null;
        
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/api/v1/admin/memory/ws`;
            
            ws = new WebSocket(wsUrl);
            
            ws.onopen = () => {
                console.log('WebSocket connected');
                updateWsStatus(true);
                if (reconnectTimer) {
                    clearTimeout(reconnectTimer);
                    reconnectTimer = null;
                }
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleData(data);
            };
            
            ws.onclose = () => {
                console.log('WebSocket disconnected');
                updateWsStatus(false);
                reconnectTimer = setTimeout(connectWebSocket, 3000);
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
            
            // 心跳
            setInterval(() => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send('ping');
                }
            }, 30000);
        }
        
        function updateWsStatus(connected) {
            const status = document.getElementById('wsStatus');
            status.className = connected ? 'ws-status ws-connected' : 'ws-status ws-disconnected';
            status.querySelector('span:last-child').textContent = connected ? 'Connected' : 'Disconnected';
        }
        
        function handleData(data) {
            if (data.type === 'memory_snapshot') {
                updateSnapshot(data);
            } else if (data.type === 'memory_growth') {
                showGrowthAlert(data);
            }
        }
        
        function updateSnapshot(data) {
            // 更新卡片
            document.getElementById('rssValue').textContent = data.process_rss_mb.toFixed(1);
            document.getElementById('systemValue').textContent = data.system_percent.toFixed(1);
            // gc_objects 仅在详细快照里提供，轻量快照不带这个字段
            if (data.gc_objects !== undefined) {
                document.getElementById('gcValue').textContent = formatNumber(data.gc_objects);
            }
            
            if (data.total_growth_mb !== undefined) {
                const growthEl = document.getElementById('growthValue');
                growthEl.textContent = (data.total_growth_mb >= 0 ? '+' : '') + data.total_growth_mb.toFixed(1);
                growthEl.style.color = data.total_growth_mb > 0 ? '#f85149' : '#3fb950';
            }
            
            // 更新进度条
            document.getElementById('systemProgress').style.width = data.system_percent + '%';
            
            // 更新图表
            chartData.push({
                time: new Date(data.timestamp * 1000),
                value: data.process_rss_mb
            });
            if (chartData.length > MAX_CHART_POINTS) {
                chartData.shift();
            }
            renderChart();
            
            // 更新模型列表
            updateModels(data.loaded_models || []);
            
            // 更新对象表格
            updateObjects(data.object_counts || {});
            
            // 更新状态
            updateStatus(data);
        }
        
        function renderChart() {
            const canvas = document.getElementById('chartCanvas');
            const width = canvas.clientWidth;
            const height = canvas.clientHeight;
            
            if (chartData.length < 2) return;
            
            const values = chartData.map(d => d.value);
            const min = Math.min(...values) * 0.95;
            const max = Math.max(...values) * 1.05;
            const range = max - min || 1;
            
            const barWidth = Math.max(4, (width - 8) / MAX_CHART_POINTS - 2);
            
            let html = '';
            chartData.forEach((d, i) => {
                const x = (i / MAX_CHART_POINTS) * (width - 8) + 4;
                const h = ((d.value - min) / range) * (height - 20);
                const time = d.time.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                html += `<div class="chart-bar" style="left: ${x}px; height: ${h}px; width: ${barWidth}px;" title="${time}: ${d.value.toFixed(1)} MB"></div>`;
            });
            
            canvas.innerHTML = html;
        }
        
        function updateModels(models) {
            const container = document.getElementById('modelsList');
            const allModels = ['llm_engine', 'image_gen_module', 'vision_module', 'tts_engine', 'stt_engine'];
            
            container.innerHTML = allModels.map(model => {
                const loaded = models.includes(model);
                return `
                    <div class="model-item">
                        <span class="model-name">${model}</span>
                        <span class="model-status ${loaded ? 'model-loaded' : 'model-unloaded'}">
                            <span class="model-dot"></span>
                            ${loaded ? 'Loaded' : 'Unloaded'}
                        </span>
                    </div>
                `;
            }).join('');
        }
        
        function updateObjects(objects) {
            const tbody = document.getElementById('objectsTable');
            const sorted = Object.entries(objects)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 8);
            
            tbody.innerHTML = sorted.map(([type, count]) => `
                <tr>
                    <td>${type}</td>
                    <td>${formatNumber(count)}</td>
                    <td>-</td>
                </tr>
            `).join('');
        }
        
        function updateStatus(data) {
            const badge = document.getElementById('statusBadge');
            const rss = data.process_rss_mb;
            
            if (rss > 4000) {
                badge.className = 'status-badge status-critical';
                badge.textContent = 'Critical';
            } else if (rss > 2000) {
                badge.className = 'status-badge status-warning';
                badge.textContent = 'Warning';
            } else {
                badge.className = 'status-badge status-healthy';
                badge.textContent = 'Healthy';
            }
        }
        
        function showGrowthAlert(data) {
            const changeEl = document.getElementById('rssChange');
            changeEl.textContent = `${data.delta_mb >= 0 ? '+' : ''}${data.delta_mb.toFixed(1)} MB (${data.source})`;
            changeEl.className = `card-change ${data.delta_mb > 0 ? 'change-positive' : 'change-negative'}`;
            
            setTimeout(() => {
                changeEl.textContent = '';
            }, 5000);
        }
        
        function formatNumber(num) {
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
            if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
            return num.toString();
        }
        
        // 初始化
        // 先用 REST 拉一次状态/趋势/最近增长，避免完全依赖 WebSocket
        // （WebSocket 首次推送对 3GB+ 进程会卡顿，REST 更稳定）
        async function loadInitialState() {
            try {
                const [statusRes, reportRes] = await Promise.all([
                    fetch('/api/v1/admin/memory/status').then(r => r.json()),
                    fetch('/api/v1/admin/memory/report').then(r => r.json())
                ]);

                // 用 status 推一次卡片更新
                if (statusRes) {
                    updateSnapshot({
                        timestamp: Date.now() / 1000,
                        process_rss_mb: statusRes.process_rss_mb,
                        system_percent: statusRes.system_percent,
                        total_growth_mb: statusRes.growth_mb,
                    });
                }

                // 用 report 的 trend 把历史曲线画出来
                if (reportRes && reportRes.summary) {
                    document.getElementById('growthValue').textContent =
                        (reportRes.summary.total_growth_mb >= 0 ? '+' : '') +
                        reportRes.summary.total_growth_mb.toFixed(1);
                }
            } catch (e) {
                console.warn('loadInitialState failed:', e);
            }
        }

        loadInitialState();
        connectWebSocket();
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)
