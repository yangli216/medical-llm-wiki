"""
Local Interactive Web Explorer for Medical LLM Wiki.
Powered by Python standard library http.server and embedded Single Page Application (SPA).
Features interactive knowledge graph visualization, real-time search, and markdown reader.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.compiler.compiler import WikiGraph
from tools.search.searcher import WikiSearcher
from tools.collector.collector import SourceCollector
from tools.cdss.engine import CdssEngine


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>中国医学权威指南与标准 LLM Wiki 知识库</title>
    <style>
        :root {
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-cyan: #06b6d4;
            --accent-emerald: #10b981;
            --accent-indigo: #6366f1;
            --accent-amber: #f59e0b;
            --accent-rose: #f43f5e;
            --border: #475569;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background: var(--bg-primary);
            color: var(--text-main);
            display: flex;
            height: 100vh;
            overflow: hidden;
        }
        /* Sidebar */
        #sidebar {
            width: 320px;
            background: var(--bg-secondary);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
        }
        .header {
            padding: 20px;
            border-bottom: 1px solid var(--border);
            background: rgba(15, 23, 42, 0.6);
        }
        .header h1 {
            font-size: 1.15rem;
            font-weight: 700;
            color: #38bdf8;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .header p {
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 4px;
        }
        .search-box {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
        }
        .search-box input {
            width: 100%;
            padding: 10px 14px;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            color: #fff;
            font-size: 0.9rem;
            outline: none;
            transition: border-color 0.2s;
        }
        .search-box input:focus {
            border-color: var(--accent-cyan);
            box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.2);
        }
        .nav-tabs {
            display: flex;
            border-bottom: 1px solid var(--border);
            background: rgba(15, 23, 42, 0.3);
        }
        .nav-tab {
            flex: 1;
            padding: 10px;
            text-align: center;
            font-size: 0.85rem;
            cursor: pointer;
            color: var(--text-muted);
            border-bottom: 2px solid transparent;
        }
        .nav-tab.active {
            color: var(--accent-cyan);
            border-bottom-color: var(--accent-cyan);
            font-weight: 600;
            background: rgba(30, 41, 59, 0.8);
        }
        .tree-list {
            flex: 1;
            overflow-y: auto;
            padding: 12px;
        }
        .tree-category {
            margin-bottom: 14px;
        }
        .cat-title {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 6px;
            padding-left: 6px;
            font-weight: 600;
        }
        .tree-item {
            padding: 8px 10px;
            border-radius: 6px;
            font-size: 0.88rem;
            cursor: pointer;
            color: #cbd5e1;
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 3px;
            transition: all 0.15s;
        }
        .tree-item:hover {
            background: var(--bg-card);
            color: #fff;
        }
        .tree-item.active {
            background: rgba(6, 182, 212, 0.2);
            color: #38bdf8;
            font-weight: 600;
        }
        .badge {
            font-size: 0.7rem;
            padding: 2px 6px;
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.1);
        }

        /* Main View */
        #main {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            position: relative;
        }
        .topbar {
            height: 52px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 24px;
            background: var(--bg-secondary);
        }
        .topbar-left {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 0.95rem;
            font-weight: 600;
            color: #e2e8f0;
        }
        .topbar-actions button {
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: #e2e8f0;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8rem;
            transition: all 0.2s;
        }
        .topbar-actions button:hover {
            background: #475569;
            border-color: #64748b;
        }
        .content-area {
            flex: 1;
            overflow-y: auto;
            padding: 32px 48px;
            max-width: 960px;
            margin: 0 auto;
            width: 100%;
        }
        /* Markdown Styling */
        .markdown-body {
            line-height: 1.7;
            font-size: 1rem;
            color: #e2e8f0;
        }
        .markdown-body h1 { font-size: 1.8rem; margin-bottom: 16px; color: #38bdf8; border-bottom: 1px solid var(--border); padding-bottom: 10px; }
        .markdown-body h2 { font-size: 1.35rem; margin-top: 28px; margin-bottom: 12px; color: #f1f5f9; }
        .markdown-body h3 { font-size: 1.1rem; margin-top: 20px; margin-bottom: 8px; color: #cbd5e1; }
        .markdown-body p { margin-bottom: 14px; }
        .markdown-body ul, .markdown-body ol { margin-left: 24px; margin-bottom: 16px; }
        .markdown-body li { margin-bottom: 6px; }
        .markdown-body table { width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 0.9rem; }
        .markdown-body th, .markdown-body td { border: 1px solid var(--border); padding: 10px 14px; text-align: left; }
        .markdown-body th { background: var(--bg-card); color: #38bdf8; }
        .markdown-body blockquote { border-left: 4px solid var(--accent-cyan); padding-left: 16px; color: #94a3b8; margin: 16px 0; }
        .markdown-body code { background: rgba(255, 255, 255, 0.1); padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 0.9em; }
        .markdown-body pre { background: var(--bg-card); padding: 14px; border-radius: 8px; overflow-x: auto; margin: 16px 0; }
        .wikilink {
            color: #38bdf8;
            text-decoration: none;
            background: rgba(56, 189, 248, 0.12);
            padding: 1px 6px;
            border-radius: 4px;
            cursor: pointer;
            border-bottom: 1px dashed #38bdf8;
            transition: all 0.15s;
        }
        .wikilink:hover {
            background: rgba(56, 189, 248, 0.25);
            color: #7dd3fc;
        }
        .meta-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 24px;
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            font-size: 0.85rem;
        }
        .meta-tag {
            background: rgba(99, 102, 241, 0.2);
            color: #a5b4fc;
            padding: 2px 8px;
            border-radius: 6px;
            font-size: 0.75rem;
        }
        /* Graph View Mode */
        #graph-container {
            display: none;
            position: absolute;
            top: 52px;
            bottom: 0;
            left: 0;
            right: 0;
            background: #090d16;
        }
        #graph-canvas {
            width: 100%;
            height: 100%;
        }
        .graph-legend {
            position: absolute;
            bottom: 20px;
            right: 20px;
            background: rgba(30, 41, 59, 0.85);
            backdrop-filter: blur(8px);
            padding: 12px 16px;
            border-radius: 8px;
            border: 1px solid var(--border);
            font-size: 0.8rem;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .legend-dot {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 6px;
        }
    </style>
</head>
<body>
    <div id="sidebar">
        <div class="header">
            <h1><span>🩺</span> Medical LLM Wiki</h1>
            <p>中国医学权威指南与标准知识库</p>
        </div>
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="搜索临床指南、疾病、药物、分期..." oninput="onSearchInput(this.value)">
        </div>
        <div class="nav-tabs">
            <div class="nav-tab active" id="tabDoc" onclick="switchNavTab('doc')">📑 目录导航</div>
            <div class="nav-tab" id="tabSrc" onclick="switchNavTab('src')">🏛️ 权威来源</div>
        </div>
        <div class="tree-list" id="treeList">
            <!-- Populated via JS -->
        </div>
    </div>

    <div id="main">
        <div class="topbar">
            <div class="topbar-left" id="topbarTitle">
                <span>📚</span> <span id="currentTitleText">主索引目录</span>
            </div>
            <div class="topbar-actions">
                <button onclick="toggleView('doc')" id="btnDocView" style="background:#0284c7;color:#fff;">📄 阅读文档</button>
                <button onclick="toggleView('graph')" id="btnGraphView">🕸️ 知识图谱</button>
            </div>
        </div>

        <div class="content-area" id="docContainer">
            <div class="markdown-body" id="docBody">
                <p>正在加载本地知识库...</p>
            </div>
        </div>

        <div id="graph-container">
            <canvas id="graph-canvas"></canvas>
            <div class="graph-legend">
                <div><span class="legend-dot" style="background:#ef4444;"></span> 疾病实体 (Disease)</div>
                <div><span class="legend-dot" style="background:#10b981;"></span> 药物与疗法 (Drug)</div>
                <div><span class="legend-dot" style="background:#f59e0b;"></span> 概念与分期 (Concept)</div>
                <div><span class="legend-dot" style="background:#8b5cf6;"></span> 综合专题 (Synthesis)</div>
                <div><span class="legend-dot" style="background:#38bdf8;"></span> 权威来源 (Source)</div>
            </div>
        </div>
    </div>

    <script>
        let graphData = null;
        let currentPageId = "index";
        let currentView = "doc";
        let activeNavTab = "doc";

        async function init() {
            const resp = await fetch('/api/graph');
            graphData = await resp.json();
            renderNavTree();
            loadPage('index');
            setupCanvas();
        }

        function switchNavTab(tab) {
            activeNavTab = tab;
            document.getElementById('tabDoc').classList.toggle('active', tab === 'doc');
            document.getElementById('tabSrc').classList.toggle('active', tab === 'src');
            renderNavTree();
        }

        function renderNavTree() {
            const container = document.getElementById('treeList');
            container.innerHTML = '';

            if (activeNavTab === 'src') {
                const srcNodes = graphData.nodes.filter(n => n.type === 'source');
                const catEl = document.createElement('div');
                catEl.className = 'tree-category';
                catEl.innerHTML = `<div class="cat-title">国家权威指南来源 (${srcNodes.length})</div>`;
                srcNodes.forEach(n => {
                    const item = document.createElement('div');
                    item.className = `tree-item ${n.id === currentPageId ? 'active' : ''}`;
                    item.innerHTML = `<span>🏛️ ${n.title}</span><span class="badge">来源</span>`;
                    item.onclick = () => loadPage(n.id);
                    catEl.appendChild(item);
                });
                container.appendChild(catEl);
                return;
            }

            const groups = {
                'synthesis': { title: '💡 综合与共病专题', items: [] },
                'disease': { title: '🫀 疾病实体库', items: [] },
                'drug': { title: '💊 药物与核心疗法', items: [] },
                'concept': { title: '📐 诊断标准与量表', items: [] },
                'organization': { title: '🏢 权威发布机构', items: [] }
            };

            graphData.nodes.forEach(n => {
                if (groups[n.type]) groups[n.type].items.push(n);
            });

            // Master index
            const topEl = document.createElement('div');
            topEl.className = `tree-item ${currentPageId === 'index' ? 'active' : ''}`;
            topEl.innerHTML = `<span>🏠 知识库主索引 (Index)</span><span class="badge">主页</span>`;
            topEl.onclick = () => loadPage('index');
            container.appendChild(topEl);

            for (const key in groups) {
                const g = groups[key];
                if (g.items.length === 0) continue;
                const catEl = document.createElement('div');
                catEl.className = 'tree-category';
                catEl.innerHTML = `<div class="cat-title">${g.title} (${g.items.length})</div>`;
                g.items.forEach(n => {
                    const item = document.createElement('div');
                    item.className = `tree-item ${n.id === currentPageId ? 'active' : ''}`;
                    item.innerHTML = `<span>${n.title}</span><span class="badge">${n.in_degree} 引用</span>`;
                    item.onclick = () => loadPage(n.id);
                    catEl.appendChild(item);
                });
                container.appendChild(catEl);
            }
        }

        async function loadPage(pageId) {
            currentPageId = pageId;
            renderNavTree();
            const resp = await fetch(`/api/page?id=${encodeURIComponent(pageId)}`);
            const data = await resp.json();
            
            document.getElementById('currentTitleText').innerText = data.title;
            let metaHtml = '';
            if (data.frontmatter && pageId !== 'index') {
                metaHtml = `<div class="meta-card">
                    <div><strong>类别:</strong> <code>${data.frontmatter.type || '未分类'}</code></div>
                    <div><strong>最后更新:</strong> ${data.frontmatter.last_updated || '2026-10-06'}</div>
                    ${data.frontmatter.tags ? `<div><strong>标签:</strong> ${data.frontmatter.tags.map(t=>`<span class="meta-tag">${t}</span>`).join(' ')}</div>` : ''}
                </div>`;
            }

            document.getElementById('docBody').innerHTML = metaHtml + data.html;
            toggleView('doc');
        }

        function toggleView(view) {
            currentView = view;
            const docContainer = document.getElementById('docContainer');
            const graphContainer = document.getElementById('graph-container');
            const btnDoc = document.getElementById('btnDocView');
            const btnGraph = document.getElementById('btnGraphView');

            if (view === 'graph') {
                docContainer.style.display = 'none';
                graphContainer.style.display = 'block';
                btnGraph.style.background = '#0284c7';
                btnGraph.style.color = '#fff';
                btnDoc.style.background = 'var(--bg-card)';
                drawGraph();
            } else {
                docContainer.style.display = 'block';
                graphContainer.style.display = 'none';
                btnDoc.style.background = '#0284c7';
                btnDoc.style.color = '#fff';
                btnGraph.style.background = 'var(--bg-card)';
            }
        }

        async function onSearchInput(val) {
            if (!val.trim()) {
                renderNavTree();
                return;
            }
            const resp = await fetch(`/api/search?q=${encodeURIComponent(val)}`);
            const hits = await resp.json();
            const container = document.getElementById('treeList');
            container.innerHTML = `<div class="cat-title">搜索结果 (${hits.length})</div>`;
            hits.forEach(h => {
                const item = document.createElement('div');
                item.className = 'tree-item';
                item.innerHTML = `<div><div style="font-weight:600;">${h.title}</div><div style="font-size:0.75rem;color:#94a3b8;">${h.snippet.slice(0, 40)}...</div></div>`;
                item.onclick = () => loadPage(h.id);
                container.appendChild(item);
            });
        }

        // Lightweight Force-Directed Canvas Graph
        let canvas, ctx;
        let simNodes = [], simLinks = [];

        function setupCanvas() {
            canvas = document.getElementById('graph-canvas');
            ctx = canvas.getContext('2d');
            window.addEventListener('resize', resizeCanvas);
            resizeCanvas();
        }

        function resizeCanvas() {
            if (!canvas) return;
            canvas.width = canvas.parentElement.clientWidth;
            canvas.height = canvas.parentElement.clientHeight;
        }

        function drawGraph() {
            if (!graphData) return;
            resizeCanvas();
            const width = canvas.width;
            const height = canvas.height;

            // Setup simulation nodes
            simNodes = graphData.nodes.map((n, i) => {
                const angle = (i / graphData.nodes.length) * Math.PI * 2;
                const r = Math.min(width, height) * 0.35;
                return {
                    id: n.id,
                    title: n.title,
                    type: n.type,
                    x: width / 2 + Math.cos(angle) * r + (Math.random() - 0.5) * 40,
                    y: height / 2 + Math.sin(angle) * r + (Math.random() - 0.5) * 40,
                    vx: 0,
                    vy: 0,
                    r: n.id === currentPageId ? 14 : Math.min(12, 6 + (n.in_degree || 0) * 0.8)
                };
            });

            const nodeMap = {};
            simNodes.forEach(n => nodeMap[n.id] = n);

            simLinks = [];
            graphData.links.forEach(l => {
                if (nodeMap[l.source] && nodeMap[l.target]) {
                    simLinks.push({ source: nodeMap[l.source], target: nodeMap[l.target] });
                }
            });

            // Run simple simulation steps
            for (let step = 0; step < 60; step++) {
                // Link spring attraction
                simLinks.forEach(link => {
                    const dx = link.target.x - link.source.x;
                    const dy = link.target.y - link.source.y;
                    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    const force = (dist - 120) * 0.03;
                    link.source.x += (dx / dist) * force;
                    link.source.y += (dy / dist) * force;
                    link.target.x -= (dx / dist) * force;
                    link.target.y -= (dy / dist) * force;
                });
                // Repulsion
                for (let i = 0; i < simNodes.length; i++) {
                    for (let j = i + 1; j < simNodes.length; j++) {
                        const a = simNodes[i], b = simNodes[j];
                        const dx = b.x - a.x;
                        const dy = b.y - a.y;
                        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                        if (dist < 200) {
                            const rep = (200 - dist) / dist * 1.5;
                            a.x -= dx * rep * 0.05;
                            a.y -= dy * rep * 0.05;
                            b.x += dx * rep * 0.05;
                            b.y += dy * rep * 0.05;
                        }
                    }
                }
            }

            renderCanvas();
        }

        function getColor(type) {
            switch(type) {
                case 'disease': return '#ef4444';
                case 'drug': return '#10b981';
                case 'concept': return '#f59e0b';
                case 'synthesis': return '#8b5cf6';
                case 'source': return '#38bdf8';
                default: return '#94a3b8';
            }
        }

        function renderCanvas() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Draw links
            ctx.strokeStyle = 'rgba(100, 116, 139, 0.25)';
            ctx.lineWidth = 1;
            simLinks.forEach(l => {
                ctx.beginPath();
                ctx.moveTo(l.source.x, l.source.y);
                ctx.lineTo(l.target.x, l.target.y);
                ctx.stroke();
            });

            // Draw nodes
            simNodes.forEach(n => {
                ctx.beginPath();
                ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
                ctx.fillStyle = getColor(n.type);
                ctx.fill();
                if (n.id === currentPageId) {
                    ctx.strokeStyle = '#fff';
                    ctx.lineWidth = 3;
                    ctx.stroke();
                }

                // Label
                ctx.fillStyle = '#f8fafc';
                ctx.font = '10px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(n.title.slice(0, 10), n.x, n.y + n.r + 12);
            });
        }

        window.onload = init;
    </script>
</body>
</html>
"""


class WikiHTTPHandler(BaseHTTPRequestHandler):
    """Custom HTTP Handler for serving the Medical LLM Wiki application and API."""

    root_dir: Path = Path(__file__).resolve().parent.parent.parent
    graph: WikiGraph = WikiGraph(root_dir)
    searcher: WikiSearcher = WikiSearcher(root_dir)
    collector: SourceCollector = SourceCollector(root_dir)
    cdss: CdssEngine = CdssEngine(root_dir)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-RHN-Prompt-Version")
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)

        if path == "/" or path == "/index.html":
            self._send_html(HTML_TEMPLATE)
        elif path == "/api/health":
            self._send_json({
                "status": "UP",
                "version": "1.9.0",
                "service": "Medical LLM Wiki & CDSS Intelligence Gateway",
                "protocols": len(self.cdss.repo.list_all()),
                "rules": 35,
                "guidelines": len(self.collector.list_sources()),
                "articles": len(self.graph.pages),
            })
        elif path in ("/v1/models", "/models"):
            self._send_json({
                "object": "list",
                "data": [
                    {
                        "id": "medical-cdss-wiki",
                        "object": "model",
                        "created": 1728300000,
                        "owned_by": "medical-llm-wiki",
                        "permission": [],
                        "root": "medical-cdss-wiki",
                        "parent": None,
                    }
                ]
            })
        elif path == "/api/graph":
            self.graph.load_graph()
            data = self.graph.to_json_graph()
            self._send_json(data)
        elif path == "/api/search":
            q = query_params.get("q", [""])[0]
            hits = self.searcher.search(q, limit=12)
            self._send_json(hits)
        elif path == "/api/page":
            pid = query_params.get("id", ["index"])[0]
            resolved = self.graph.resolve_link(pid) or pid
            page = self.graph.pages.get(resolved)
            if not page and resolved == "index":
                idx_path = self.root_dir / "wiki" / "index.md"
                if idx_path.exists():
                    from tools.compiler.compiler import WikiPage
                    page = WikiPage(idx_path, self.root_dir / "wiki")

            if page:
                html_body = self._markdown_to_html(page.raw_text)
                self._send_json({
                    "id": resolved,
                    "title": page.title,
                    "frontmatter": page.frontmatter,
                    "html": html_body,
                })
            else:
                self._send_json({"error": "Page not found", "id": pid}, status=404)
        elif path == "/api/sources":
            sources = self.collector.list_sources()
            self._send_json(sources)
        elif path == "/api/cdss/protocols":
            protocols = self.cdss.repo.list_all()
            data = [{
                "protocolId": p.protocol_id,
                "title": p.title,
                "icd10": p.icd10,
                "category": p.category,
                "summary": p.summary,
            } for p in protocols]
            self._send_json(data)
        elif path.startswith("/api/cdss/protocols/"):
            pid = path[len("/api/cdss/protocols/"):]
            prot = self.cdss.repo.get(pid)
            if prot:
                self._send_json({
                    "protocolId": prot.protocol_id,
                    "title": prot.title,
                    "icd10": prot.icd10,
                    "category": prot.category,
                    "summary": prot.summary,
                    "planIntent": prot.to_rhn_plan_intent(),
                    "candidate": prot.to_rhn_plan_candidate(1),
                    "treatmentRecommendations": prot.to_rhn_treatment_recommendations(),
                    "rules": prot.rules,
                })
            else:
                self._send_json({"error": "Protocol not found", "id": pid}, status=404)
        elif path == "/api/cdss/recommend":
            q = query_params.get("q", [""])[0]
            matches = self.cdss.search_protocols(q, limit=5)
            self._send_json(matches)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON body"}, status=400)
            return

        if path in ("/v1/chat/completions", "/chat/completions"):
            self._handle_chat_completions(payload)
        elif path in ("/api/knowledge/search", "/v1/knowledge/pmphai/search"):
            self._handle_knowledge_search(payload)
        elif path == "/api/cdss/compile-rhn-plan":
            query = payload.get("input") or payload.get("naturalInput") or payload.get("protocolId") or ""
            res = self.cdss.compile_rhn_plan(query)
            status_code = 200 if res.get("success") else 404
            self._send_json(res, status=status_code)
        elif path == "/api/cdss/recommend":
            query = payload.get("query") or payload.get("input") or ""
            limit = int(payload.get("limit", 5))
            matches = self.cdss.search_protocols(query, limit=limit)
            self._send_json(matches)
        elif path == "/api/cdss/audit":
            meds = payload.get("medications", [])
            patient = payload.get("patient", {})
            audit_res = self.cdss.audit_prescription(meds, patient)
            self._send_json(audit_res)
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_knowledge_search(self, payload: Dict[str, Any]) -> None:
        """Adapts to RHN PmphaiClinicalKnowledgeGateway ProviderResult[] protocol."""
        query = payload.get("query") or ""
        limit = int(payload.get("limit", 5))
        hits = self.searcher.search(query, limit=limit)
        results = []
        for h in hits:
            sources = h.get("sources", [])
            lib_name = sources[0] if sources else "国家卫生健康委员会临床诊疗指南与规范"
            results.append({
                "id": h["id"],
                "name": h["title"],
                "content": h.get("snippet", ""),
                "score": round(float(h.get("score", 1.0)) / 100.0, 4),
                "resourcePos": h.get("rel_path", ""),
                "sourceInfo": {
                    "knowledgeLibName": lib_name,
                    "knowledgeLibId": f"LIB-{h['id'].upper()}",
                    "publishYear": "2024",
                },
                "aiAbstract": h.get("snippet", ""),
            })
        self._send_json(results)

    def _handle_chat_completions(self, payload: Dict[str, Any]) -> None:
        """Adapts to OpenAI ChatCompletion protocol consumed by RHN OpenAiCompatibleClinicalAiModelGateway."""
        messages = payload.get("messages", [])
        model = payload.get("model", "medical-cdss-wiki")
        stream = bool(payload.get("stream", False))

        system_content = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        user_messages = [m.get("content", "") for m in messages if m.get("role") == "user"]
        last_user_content = user_messages[-1] if user_messages else ""

        u_obj = None
        for u_msg in reversed(user_messages):
            if isinstance(u_msg, str) and u_msg.strip().startswith("{"):
                try:
                    cand = json.loads(u_msg)
                    if isinstance(cand, dict) and ("text" in cand or "mode" in cand or "draft" in cand or "generationStage" in cand):
                        u_obj = cand
                        break
                except Exception:
                    pass

        is_plan_compile = (
            "PLAN_PROMPT" in system_content
            or "门诊临床诊疗方案编译器" in system_content
            or "noteTemplateContent" in system_content
            or (u_obj is not None and "text" in u_obj and "mode" in u_obj)
        )
        is_plan_match = "PLAN_MATCH" in system_content or "匹配院内已有的整体诊疗方案" in system_content
        is_clinical_suggest = (
            "SYSTEM_PROMPT" in system_content
            or "医疗卫生领域辅助临床医生" in system_content
            or (u_obj is not None and ("generationStage" in u_obj or "draft" in u_obj))
        )

        assistant_content = ""

        if is_plan_match:
            available_plans = (u_obj.get("availablePlans") if u_obj else []) or []
            recommended = []
            for p in available_plans[:3]:
                p_id = p.get("templateId") or p.get("id")
                p_name = p.get("name", "已有方案")
                recommended.append({
                    "templateId": p_id,
                    "rationale": f"基于就诊主诉与临床表现推荐核对已有标准化方案【{p_name}】",
                })
            assistant_content = json.dumps({"recommendedPlans": recommended}, ensure_ascii=False)

        elif is_plan_compile:
            query = ""
            available_plans = []
            if u_obj:
                query = u_obj.get("text", "")
                available_plans = u_obj.get("availablePlans", [])
            else:
                query = last_user_content

            res = self.cdss.compile_rhn_plan(query)
            if res.get("success"):
                plan_intent = res["planIntent"]
                matched_ref_id = None
                for ap in available_plans:
                    ap_name = ap.get("name", "")
                    if ap_name and (ap_name in plan_intent["name"] or plan_intent["name"] in ap_name):
                        matched_ref_id = ap.get("id") or ap.get("templateId")
                        break
                plan_intent["referenceTemplateId"] = matched_ref_id
                assistant_content = json.dumps(plan_intent, ensure_ascii=False)
            else:
                assistant_content = json.dumps({
                    "name": query.strip()[:20] if query else "未特指临床方案",
                    "description": "",
                    "noteTemplateContent": {
                        "chiefComplaint": "",
                        "presentIllness": "",
                        "medicalHistory": "",
                        "physicalExam": "",
                        "healthEducation": "",
                        "followUp": "",
                    },
                    "items": [],
                    "referenceTemplateId": None,
                }, ensure_ascii=False)

        elif is_clinical_suggest:
            ctx = u_obj or {}
            draft = ctx.get("draft") or {}
            question = ctx.get("question") or ""
            voice = ctx.get("voiceTranscript") or ""
            patient = ctx.get("patient") or {}
            allergies = ctx.get("allergies") or []

            medications_to_audit = []
            if draft.get("medications") and isinstance(draft["medications"], list):
                for m in draft["medications"]:
                    if isinstance(m, dict) and m.get("name"):
                        medications_to_audit.append(m["name"])
                    elif isinstance(m, str):
                        medications_to_audit.append(m)

            kw = draft.get("chiefComplaint") or question or voice or ""
            if not kw and draft.get("diagnoses") and isinstance(draft["diagnoses"], list):
                first_diag = draft["diagnoses"][0]
                kw = first_diag.get("display") or first_diag.get("code") or ""

            res = self.cdss.compile_rhn_plan(kw) if kw else None
            prot = self.cdss.repo.get(res["protocolId"]) if (res and res.get("success")) else None

            patient_profile = dict(patient)
            if allergies:
                patient_profile["allergies"] = " ".join([
                    a.get("substanceDisplay", "") for a in allergies if isinstance(a, dict)
                ])
            audit_res = self.cdss.audit_prescription(medications_to_audit, patient_profile)
            safety_alerts = []
            for a in audit_res.get("alerts", []):
                safety_alerts.append({
                    "level": "CRITICAL" if a["severity"] == "RED" else "WARNING",
                    "title": a["title"],
                    "detail": a["message"],
                })

            if prot:
                rec_draft = {
                    "chiefComplaint": draft.get("chiefComplaint") or prot.note_template.get("chiefComplaint", ""),
                    "presentIllness": draft.get("presentIllness") or prot.note_template.get("presentIllness", ""),
                    "medicalHistory": draft.get("medicalHistory") or prot.note_template.get("medicalHistory", ""),
                    "physicalExam": draft.get("physicalExam") or prot.note_template.get("physicalExam", ""),
                    "treatmentPlan": None,
                    "healthEducation": draft.get("healthEducation") or prot.note_template.get("healthEducation", ""),
                    "followUp": draft.get("followUp") or prot.note_template.get("followUp", ""),
                    "systolic": draft.get("systolic"),
                    "diastolic": draft.get("diastolic"),
                    "temperature": draft.get("temperature"),
                    "pulseRate": draft.get("pulseRate"),
                    "respiratoryRate": draft.get("respiratoryRate"),
                    "oxygenSaturation": draft.get("oxygenSaturation"),
                    "heightCm": draft.get("heightCm"),
                    "weightKg": draft.get("weightKg"),
                }
                diag_candidates = [{
                    "code": prot.icd10,
                    "display": prot.title,
                    "type": "PRIMARY",
                    "confidence": 0.95,
                    "rationale": f"符合《{prot.sources[0] if prot.sources else '国家权威临床指南'}》规范诊断标准与临床路径",
                }]
                recs = prot.to_rhn_treatment_recommendations()
                suggestion = {
                    "summary": f"针对【{prot.title}】（ICD-10: {prot.icd10}）提供权威门诊临床路径、6段规范病历范文及用药安全核对建议。",
                    "recordDraft": rec_draft,
                    "diagnosisCandidates": diag_candidates,
                    "differentialDiagnoses": [],
                    "missingInformation": [],
                    "safetyAlerts": safety_alerts,
                    "recommendedPlans": [{
                        "templateId": 1,
                        "name": prot.title,
                        "description": prot.summary,
                        "rationale": "基于国家权威临床指南建立的标准方案",
                    }],
                    "treatmentRecommendations": recs,
                    "disclaimer": "本临床建议基于国家卫健委及中华医学会权威指南生成，仅供注册医师参考核验。",
                }
                assistant_content = json.dumps(suggestion, ensure_ascii=False)
            else:
                assistant_content = json.dumps({
                    "summary": "未识别到明确的主诉或疾病主题，建议补充问诊资料。",
                    "recordDraft": None,
                    "diagnosisCandidates": [],
                    "differentialDiagnoses": [],
                    "missingInformation": ["请补充患者主要就诊不适症状及持续时间"],
                    "safetyAlerts": safety_alerts,
                    "recommendedPlans": [],
                    "treatmentRecommendations": [],
                    "disclaimer": "本临床建议仅供注册医师参考核验。",
                }, ensure_ascii=False)
        else:
            hits = self.searcher.search(last_user_content, limit=3)
            if hits:
                evidence_text = "\n\n".join([f"### 来源《{h.get('title')}》\n{h.get('snippet', '')}" for h in hits])
                assistant_content = f"根据中国医学权威指南与标准知识库检索结果：\n\n{evidence_text}"
            else:
                assistant_content = "知识库中暂未检索到直接匹配的指南条目，建议核对疾病或药物名称。"

        now_ts = int(time.time())
        completion_id = f"chatcmpl-cdss-{now_ts}"

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            chunk_size = 120
            for i in range(0, len(assistant_content), chunk_size):
                sub = assistant_content[i:i + chunk_size]
                chunk_data = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": now_ts,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": sub},
                        "finish_reason": None,
                    }],
                }
                self.wfile.write(f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()

            final_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": now_ts,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
            }
            self.wfile.write(f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            response_obj = {
                "id": completion_id,
                "object": "chat.completion",
                "created": now_ts,
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": assistant_content,
                    },
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": len(last_user_content),
                    "completion_tokens": len(assistant_content),
                    "total_tokens": len(last_user_content) + len(assistant_content),
                },
            }
            self._send_json(response_obj)

    def _markdown_to_html(self, md_text: str) -> str:
        """Lightweight markdown to HTML converter with [[WikiLink]] resolution."""
        # Strip frontmatter if present
        if md_text.startswith("---"):
            parts = md_text.split("---", 2)
            if len(parts) >= 3:
                md_text = parts[2].strip()

        # Convert [[WikiLink|Alias]] or [[WikiLink]]
        def link_sub(match):
            raw = match.group(1)
            if "|" in raw:
                target, label = raw.split("|", 1)
            else:
                target, label = raw, raw
            return f'<a class="wikilink" onclick="loadPage(\'{target.strip()}\')">{label.strip()}</a>'

        md_text = re.sub(r"\[\[([^\]]+)\]\]", link_sub, md_text)

        # Basic markdown transforms
        lines = []
        in_table = False
        in_code = False

        for line in md_text.splitlines():
            if line.startswith("```"):
                if in_code:
                    lines.append("</pre>")
                    in_code = False
                else:
                    lines.append("<pre><code>")
                    in_code = True
                continue

            if in_code:
                lines.append(html.escape(line))
                continue

            # Tables
            if line.startswith("|") and line.endswith("|"):
                if not in_table:
                    lines.append("<table>")
                    in_table = True
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if all(c.startswith("-") or c.startswith(":-") for c in cells if c):
                    continue  # Table separator
                row_tag = "th" if "<table>" in lines[-1] else "td"
                cells_html = "".join(f"<{row_tag}>{c}</{row_tag}>" for c in cells)
                lines.append(f"<tr>{cells_html}</tr>")
                continue
            else:
                if in_table:
                    lines.append("</table>")
                    in_table = False

            # Headers
            if line.startswith("### "):
                lines.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith("## "):
                lines.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("# "):
                lines.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("- "):
                lines.append(f"<li>{line[2:]}</li>")
            elif line.strip() == "---":
                lines.append("<hr>")
            elif line.strip():
                # Bold
                l = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", line)
                lines.append(f"<p>{l}</p>")

        if in_table:
            lines.append("</table>")
        if in_code:
            lines.append("</code></pre>")

        return "\n".join(lines)

    def _send_html(self, html_content: str) -> None:
        encoded = html_content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, data: Any, status: int = 200) -> None:
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)


def run_server(port: int = 8080) -> None:
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, WikiHTTPHandler)
    print(f"🚀 Medical LLM Wiki Web Server is running on http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server.")
        httpd.server_close()
