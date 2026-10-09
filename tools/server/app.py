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
from datetime import datetime
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.compiler.compiler import WikiGraph
from tools.search.searcher import WikiSearcher
from tools.collector.collector import SourceCollector
from tools.cdss.engine import CdssEngine
from tools.cdss.drug_checker import DrugInsertRepository, DrugContraindicationAuditor
from tools.cdss.evidence_chain import EvidenceChainEngine
from tools.cdss.calculators import ClinicalCalculatorRegistry


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
            overflow: hidden;
        }
        #graph-canvas {
            width: 100%;
            height: 100%;
            cursor: pointer;
        }
        .graph-controls {
            position: absolute;
            top: 16px;
            left: 20px;
            display: flex;
            align-items: center;
            gap: 8px;
            z-index: 10;
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(8px);
            padding: 6px 12px;
            border-radius: 20px;
            border: 1px solid var(--border);
        }
        .filter-pill {
            background: rgba(30, 41, 59, 0.8);
            border: 1px solid var(--border);
            color: var(--text-dim);
            padding: 4px 10px;
            border-radius: 14px;
            font-size: 0.75rem;
            cursor: pointer;
            transition: all 0.2s;
        }
        .filter-pill:hover, .filter-pill.active {
            background: #0284c7;
            color: #fff;
            border-color: #38bdf8;
        }
        .graph-tooltip {
            position: absolute;
            display: none;
            background: rgba(15, 23, 42, 0.95);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 8px 12px;
            color: #fff;
            font-size: 0.8rem;
            pointer-events: none;
            z-index: 20;
            box-shadow: 0 4px 16px rgba(0,0,0,0.5);
            line-height: 1.4;
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

        /* Source Import Modal & Topbar Badges */
        .btn-import-source {
            width: 100%;
            padding: 9px 12px;
            margin-top: 10px;
            background: linear-gradient(135deg, #059669, #0284c7);
            color: #fff;
            border: none;
            border-radius: 6px;
            font-size: 0.82rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            transition: all 0.2s;
            box-shadow: 0 2px 6px rgba(0,0,0,0.25);
        }
        .btn-import-source:hover {
            background: linear-gradient(135deg, #10b981, #0ea5e9);
            transform: translateY(-1px);
            box-shadow: 0 4px 10px rgba(6, 182, 212, 0.35);
        }
        .topbar-stats {
            display: flex;
            align-items: center;
            gap: 6px;
            flex-wrap: wrap;
            margin-left: 12px;
        }
        .stat-badge {
            background: rgba(30, 41, 59, 0.9);
            border: 1px solid var(--border);
            color: #cbd5e1;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 0.72rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s;
        }
        .stat-badge:hover {
            border-color: #38bdf8;
            color: #38bdf8;
        }
        .modal-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(15, 23, 42, 0.8);
            backdrop-filter: blur(4px);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        .modal-overlay.active {
            display: flex;
        }
        .modal-box {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 12px;
            width: 90%;
            max-width: 680px;
            max-height: 88vh;
            overflow-y: auto;
            padding: 24px;
            box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5), 0 8px 10px -6px rgba(0,0,0,0.5);
        }
        .modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
        }
        .modal-header h2 {
            font-size: 1.15rem;
            color: #38bdf8;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .modal-close {
            background: transparent;
            border: none;
            color: #94a3b8;
            font-size: 1.4rem;
            cursor: pointer;
        }
        .modal-close:hover { color: #f1f5f9; }
        .form-group {
            margin-bottom: 14px;
        }
        .form-group label {
            display: block;
            font-size: 0.82rem;
            font-weight: 600;
            color: #cbd5e1;
            margin-bottom: 6px;
        }
        .form-group input, .form-group textarea, .form-group select {
            width: 100%;
            padding: 8px 12px;
            background: var(--bg-primary);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: #f8fafc;
            font-size: 0.85rem;
            outline: none;
            box-sizing: border-box;
            font-family: inherit;
        }
        .form-group input:focus, .form-group textarea:focus {
            border-color: #38bdf8;
        }
        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }
        .modal-actions {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            margin-top: 18px;
            border-top: 1px solid var(--border);
            padding-top: 14px;
        }
        .btn-cancel {
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: #cbd5e1;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85rem;
        }
        .btn-submit {
            background: linear-gradient(135deg, #059669, #0284c7);
            border: none;
            color: #fff;
            padding: 8px 18px;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            font-size: 0.85rem;
            transition: all 0.2s;
        }
        .btn-submit:hover {
            background: linear-gradient(135deg, #10b981, #0ea5e9);
        }
        .btn-demo {
            background: rgba(245, 158, 11, 0.2);
            border: 1px solid #f59e0b;
            color: #fbbf24;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.75rem;
            cursor: pointer;
        }
        .btn-demo:hover {
            background: rgba(245, 158, 11, 0.35);
        }
    </style>
</head>
<body>
    <div id="sidebar">
        <div class="header">
            <h1><span>🩺</span> Medical LLM Wiki</h1>
            <p>中国医学权威指南与标准知识库</p>
            <button class="btn-import-source" onclick="openImportModal()">➕ 录入新标准 / 指南</button>
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
            <div class="topbar-left" id="topbarTitle" style="display:flex;align-items:center;">
                <span>📚</span> <span id="currentTitleText">主索引目录</span>
                <div class="topbar-stats" id="topbarStats">
                    <span class="stat-badge" onclick="switchNavTab('src')" title="点击查看所有国家权威指南">🏛️ 51 指南</span>
                    <span class="stat-badge" onclick="loadPage('index')" title="点击查看高发疾病实体">🫀 48 疾病</span>
                    <span class="stat-badge" onclick="loadPage('index')" title="点击查看门诊方案协议">📋 42 门诊协议</span>
                    <span class="stat-badge" onclick="loadPage('index')" title="点击查看国家法定说明书">📖 140 说明书</span>
                    <span class="stat-badge" onclick="loadPage('index')" title="点击查看临床安全规则">🛡️ 45 CDSS规则</span>
                </div>
            </div>
            <div class="topbar-actions">
                <button onclick="openImportModal()" style="background:rgba(5,150,105,0.25);border:1px solid #059669;color:#34d399;">➕ 导入标准</button>
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
            <div class="graph-controls">
                <span style="font-size:0.75rem; color:#94a3b8; margin-right:4px;">分类筛选:</span>
                <button class="filter-pill active" id="btnFilterAll" onclick="setGraphFilter('all')">全部</button>
                <button class="filter-pill" id="btnFilterDisease" onclick="setGraphFilter('disease')">🔴 疾病</button>
                <button class="filter-pill" id="btnFilterDrug" onclick="setGraphFilter('drug')">🟢 药物与说明书</button>
                <button class="filter-pill" id="btnFilterSynthesis" onclick="setGraphFilter('synthesis')">🟣 方案协议</button>
                <button class="filter-pill" id="btnFilterConcept" onclick="setGraphFilter('concept')">🟡 概念分期</button>
                <button class="filter-pill" id="btnFilterSource" onclick="setGraphFilter('source')">🔵 来源</button>
                <button class="filter-pill" onclick="resetEgoNetwork()" style="margin-left:8px; border-color:#ef4444; color:#fca5a5;">重置邻域</button>
            </div>
            <canvas id="graph-canvas"></canvas>
            <div id="graph-tooltip" class="graph-tooltip"></div>
            <div class="graph-legend">
                <div><span class="legend-dot" style="background:#ef4444;"></span> 疾病实体 (Disease)</div>
                <div><span class="legend-dot" style="background:#10b981;"></span> 药物与说明书 (Drug)</div>
                <div><span class="legend-dot" style="background:#8b5cf6;"></span> 门诊方案 (Synthesis)</div>
                <div><span class="legend-dot" style="background:#f59e0b;"></span> 概念与分期 (Concept)</div>
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

        // Enhanced Force-Directed Canvas Graph with 1-Hop Ego Network & Filtering
        let canvas, ctx;
        let simNodes = [], simLinks = [];
        let graphFilter = 'all';
        let egoCenterNodeId = null;
        let egoNeighbors = null;
        let hoveredNode = null;

        function setGraphFilter(type) {
            graphFilter = type;
            document.querySelectorAll('.filter-pill').forEach(btn => btn.classList.remove('active'));
            const activeBtn = document.getElementById(
                type === 'all' ? 'btnFilterAll' :
                type === 'disease' ? 'btnFilterDisease' :
                type === 'drug' ? 'btnFilterDrug' :
                type === 'synthesis' ? 'btnFilterSynthesis' :
                type === 'concept' ? 'btnFilterConcept' : 'btnFilterSource'
            );
            if (activeBtn) activeBtn.classList.add('active');
            egoCenterNodeId = null;
            egoNeighbors = null;
            drawGraph();
        }

        function resetEgoNetwork() {
            egoCenterNodeId = null;
            egoNeighbors = null;
            renderCanvas();
        }

        function setupCanvas() {
            canvas = document.getElementById('graph-canvas');
            ctx = canvas.getContext('2d');
            window.addEventListener('resize', resizeCanvas);
            canvas.addEventListener('mousemove', onCanvasMouseMove);
            canvas.addEventListener('click', onCanvasClick);
            canvas.addEventListener('dblclick', onCanvasDblClick);
            canvas.addEventListener('mouseleave', () => {
                document.getElementById('graph-tooltip').style.display = 'none';
                hoveredNode = null;
            });
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

            // Filter nodes by category if selected
            let filteredNodes = graphData.nodes;
            if (graphFilter !== 'all') {
                filteredNodes = graphData.nodes.filter(n => {
                    if (graphFilter === 'drug') return n.type === 'drug' || n.type === 'drug_insert';
                    return n.type === graphFilter;
                });
            }
            const allowedIds = new Set(filteredNodes.map(n => n.id));

            // Setup simulation nodes
            simNodes = filteredNodes.map((n, i) => {
                const angle = (i / filteredNodes.length) * Math.PI * 2;
                const r = Math.min(width, height) * 0.36;
                return {
                    id: n.id,
                    title: n.title,
                    type: n.type,
                    in_degree: n.in_degree || 0,
                    x: width / 2 + Math.cos(angle) * r + (Math.random() - 0.5) * 60,
                    y: height / 2 + Math.sin(angle) * r + (Math.random() - 0.5) * 60,
                    vx: 0,
                    vy: 0,
                    r: n.id === currentPageId ? 14 : Math.min(13, 6 + (n.in_degree || 0) * 0.7)
                };
            });

            const nodeMap = {};
            simNodes.forEach(n => nodeMap[n.id] = n);

            simLinks = [];
            graphData.links.forEach(l => {
                if (allowedIds.has(l.source) && allowedIds.has(l.target) && nodeMap[l.source] && nodeMap[l.target]) {
                    simLinks.push({
                        source: nodeMap[l.source],
                        target: nodeMap[l.target],
                        sourceId: l.source,
                        targetId: l.target
                    });
                }
            });

            // Run force simulation relaxation
            for (let step = 0; step < 70; step++) {
                // Spring attraction
                simLinks.forEach(link => {
                    const dx = link.target.x - link.source.x;
                    const dy = link.target.y - link.source.y;
                    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    const force = (dist - 110) * 0.035;
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
                        if (dist < 180) {
                            const rep = (180 - dist) / dist * 1.6;
                            a.x -= dx * rep * 0.04;
                            a.y -= dy * rep * 0.04;
                            b.x += dx * rep * 0.04;
                            b.y += dy * rep * 0.04;
                        }
                    }
                }
            }

            renderCanvas();
        }

        function getColor(type) {
            switch(type) {
                case 'disease': return '#ef4444';
                case 'drug':
                case 'drug_insert': return '#10b981';
                case 'concept': return '#f59e0b';
                case 'synthesis': return '#8b5cf6';
                case 'source': return '#38bdf8';
                default: return '#94a3b8';
            }
        }

        function findNodeAt(x, y) {
            for (let i = simNodes.length - 1; i >= 0; i--) {
                const n = simNodes[i];
                const dx = x - n.x;
                const dy = y - n.y;
                if (dx * dx + dy * dy <= (n.r + 5) * (n.r + 5)) {
                    return n;
                }
            }
            return null;
        }

        function onCanvasMouseMove(e) {
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;
            const node = findNodeAt(mouseX, mouseY);
            const tooltip = document.getElementById('graph-tooltip');

            if (node) {
                hoveredNode = node;
                canvas.style.cursor = 'pointer';
                tooltip.style.display = 'block';
                tooltip.style.left = (e.clientX - rect.left + 15) + 'px';
                tooltip.style.top = (e.clientY - rect.top - 20) + 'px';
                tooltip.innerHTML = `
                    <div style="font-weight:600;color:#f8fafc;font-size:0.85rem;">${node.title}</div>
                    <div style="color:#94a3b8;font-size:0.75rem;margin-top:2px;">
                        分类: <span>${node.type}</span> | 核心入度: <span style="color:#38bdf8;">${node.in_degree}</span>
                    </div>
                    <div style="color:#38bdf8;font-size:0.7rem;margin-top:4px;">
                        💡 单击展开 1-Hop 邻域 | 双击打开词条
                    </div>
                `;
            } else {
                hoveredNode = null;
                canvas.style.cursor = 'default';
                tooltip.style.display = 'none';
            }
        }

        function onCanvasClick(e) {
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;
            const node = findNodeAt(mouseX, mouseY);

            if (node) {
                if (egoCenterNodeId === node.id) {
                    resetEgoNetwork();
                } else {
                    egoCenterNodeId = node.id;
                    const neighbors = new Set([node.id]);
                    graphData.links.forEach(l => {
                        if (l.source === node.id) neighbors.add(l.target);
                        if (l.target === node.id) neighbors.add(l.source);
                    });
                    egoNeighbors = neighbors;
                    renderCanvas();
                }
            } else {
                if (egoCenterNodeId) {
                    resetEgoNetwork();
                }
            }
        }

        function onCanvasDblClick(e) {
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;
            const node = findNodeAt(mouseX, mouseY);
            if (node) {
                loadPage(node.id);
                toggleView('doc');
            }
        }

        function renderCanvas() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Draw links
            simLinks.forEach(l => {
                const isEgoActive = egoNeighbors !== null;
                const inEgo = isEgoActive && (egoNeighbors.has(l.sourceId) && egoNeighbors.has(l.targetId));
                const connectsToCenter = isEgoActive && (l.sourceId === egoCenterNodeId || l.targetId === egoCenterNodeId);

                ctx.save();
                if (isEgoActive) {
                    if (connectsToCenter) {
                        ctx.strokeStyle = '#38bdf8';
                        ctx.lineWidth = 2.2;
                        ctx.globalAlpha = 0.95;
                    } else if (inEgo) {
                        ctx.strokeStyle = 'rgba(148, 163, 184, 0.6)';
                        ctx.lineWidth = 1.2;
                        ctx.globalAlpha = 0.6;
                    } else {
                        ctx.strokeStyle = 'rgba(100, 116, 139, 0.15)';
                        ctx.lineWidth = 0.5;
                        ctx.globalAlpha = 0.1;
                    }
                } else {
                    ctx.strokeStyle = 'rgba(100, 116, 139, 0.28)';
                    ctx.lineWidth = 1;
                    ctx.globalAlpha = 0.7;
                }

                ctx.beginPath();
                ctx.moveTo(l.source.x, l.source.y);
                ctx.lineTo(l.target.x, l.target.y);
                ctx.stroke();
                ctx.restore();
            });

            // Draw nodes
            simNodes.forEach(n => {
                const isEgoActive = egoNeighbors !== null;
                const inEgo = !isEgoActive || egoNeighbors.has(n.id);
                const isCenter = isEgoActive && (n.id === egoCenterNodeId);

                ctx.save();
                ctx.globalAlpha = inEgo ? 1.0 : 0.12;

                // Node circle
                ctx.beginPath();
                ctx.arc(n.x, n.y, isCenter ? n.r + 4 : n.r, 0, Math.PI * 2);
                ctx.fillStyle = getColor(n.type);
                ctx.fill();

                if (isCenter) {
                    // Center pulsating ring
                    ctx.strokeStyle = '#ffffff';
                    ctx.lineWidth = 3.5;
                    ctx.stroke();
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, n.r + 9, 0, Math.PI * 2);
                    ctx.strokeStyle = '#38bdf8';
                    ctx.lineWidth = 2;
                    ctx.stroke();
                } else if (n.id === currentPageId) {
                    ctx.strokeStyle = '#fff';
                    ctx.lineWidth = 2.5;
                    ctx.stroke();
                }

                // Label
                if (inEgo || n.in_degree > 15) {
                    ctx.fillStyle = isCenter ? '#38bdf8' : (inEgo ? '#f8fafc' : '#64748b');
                    ctx.font = isCenter ? 'bold 12px sans-serif' : '10px sans-serif';
                    ctx.textAlign = 'center';
                    ctx.fillText(n.title.slice(0, 12), n.x, n.y + n.r + (isCenter ? 16 : 13));
                }
                ctx.restore();
            });
        }


        function openImportModal() {
            document.getElementById('importModal').classList.add('active');
        }

        function closeImportModal() {
            document.getElementById('importModal').classList.remove('active');
        }

        function fillExampleImportData() {
            document.getElementById('inpTitle').value = '成人肥胖食养指南（2024年版）';
            document.getElementById('inpAuthority').value = '国家卫生健康委食品司 / 中华医学会内分泌学分会';
            document.getElementById('inpCategory').value = '内分泌代谢与医学营养';
            document.getElementById('inpSourceId').value = 'SRC-NHC-NUT-2024-01';
            document.getElementById('inpYear').value = 2024;
            document.getElementById('inpSummary').value = '1. 诊断切点：成人 BMI ≥ 24 kg/m² 为超重，≥ 28 kg/m² 为肥胖；男性腰围 ≥ 90cm、女性 ≥ 85cm 为中心型肥胖。\n2. 饮食干预：控制总能量摄入，推荐每日能量摄入减少 500～1000 kcal；优质蛋白质占比达 50% 以上。\n3. 减重靶标：以 6 个月内体重减轻 5%～10% 为适宜目标，严禁剧烈极低能量禁食。';
            document.getElementById('inpRelated').value = '2型糖尿病, 原发性高血压, 动脉粥样硬化性心血管疾病';
            document.getElementById('inpContent').value = '# 《成人肥胖食养指南（2024年版）》核心条款归档\n\n## 一、 流行病学与危害\n我国成人超重肥胖率已达 50.7%，肥胖是高血压、2型糖尿病、心血管疾病与部分恶性肿瘤的独立高危危险因素。\n\n## 二、 食养原则与建议\n1. 控制总能量摄入，循序渐进减重；\n2. 宏量营养素配比合理，多全谷物、少精制糖；\n3. 充足微量营养素与膳食纤维摄入；\n4. 戒烟限酒，规律睡眠与抗阻有氧运动结合。';
        }

        async function submitImportSource(e) {
            e.preventDefault();
            const btn = document.getElementById('btnSubmitImport');
            btn.disabled = true;
            btn.innerText = '⏳ 正在编译并建立索引...';

            const payload = {
                title: document.getElementById('inpTitle').value.trim(),
                authority: document.getElementById('inpAuthority').value.trim(),
                category: document.getElementById('inpCategory').value.trim(),
                source_id: document.getElementById('inpSourceId').value.trim(),
                year: parseInt(document.getElementById('inpYear').value) || 2024,
                summary: document.getElementById('inpSummary').value.trim(),
                related_diseases: document.getElementById('inpRelated').value.trim(),
                content: document.getElementById('inpContent').value.trim()
            };

            try {
                const resp = await fetch('/api/knowledge/import-source', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const res = await resp.json();
                if (res.success) {
                    alert('🎉 ' + res.message);
                    closeImportModal();
                    // Reload graph & re-render tree
                    const graphResp = await fetch('/api/graph');
                    graphData = await graphResp.json();
                    renderNavTree();
                    // Load the newly imported page directly
                    loadPage(res.source_id);
                } else {
                    alert('❌ 导入失败: ' + (res.error || '未知错误'));
                }
            } catch (err) {
                alert('❌ 请求异常: ' + err.message);
            } finally {
                btn.disabled = false;
                btn.innerText = '🚀 编译并导入本知识库';
            }
        }

        window.onload = init;
    </script>

    <!-- Modal for importing new clinical guidelines / standards -->
    <div class="modal-overlay" id="importModal">
        <div class="modal-box">
            <div class="modal-header">
                <h2><span>🏛️</span> 录入新临床诊疗指南与国家标准</h2>
                <button class="modal-close" onclick="closeImportModal()">&times;</button>
            </div>
            <div style="font-size:0.78rem;color:#94a3b8;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;">
                <span>向知识库追加尚未收录的行业权威标准，系统将自动编译知识图谱与全文索引。</span>
                <button type="button" class="btn-demo" onclick="fillExampleImportData()">✨ 填入示例数据</button>
            </div>
            <form id="importSourceForm" onsubmit="submitImportSource(event)">
                <div class="form-group">
                    <label>标准 / 指南官方全称 *</label>
                    <input type="text" id="inpTitle" placeholder="例如：《成人肥胖食养指南（2024年版）》" required>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>制定 / 发布权威机构 *</label>
                        <input type="text" id="inpAuthority" placeholder="国家卫生健康委食品司 / 中华医学会" required>
                    </div>
                    <div class="form-group">
                        <label>专科领域分类 *</label>
                        <input type="text" id="inpCategory" placeholder="例如：内分泌代谢、心血管、儿科、全科医学" required>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>文献来源标识代码 (ID)</label>
                        <input type="text" id="inpSourceId" placeholder="例如：SRC-NHC-NUT-2024-01 (选填，自动建议)">
                    </div>
                    <div class="form-group">
                        <label>发布年份 *</label>
                        <input type="number" id="inpYear" value="2024" min="2000" max="2030" required>
                    </div>
                </div>
                <div class="form-group">
                    <label>核心临床导读与要点提炼 (支持多行) *</label>
                    <textarea id="inpSummary" rows="3" placeholder="提炼 2～4 条核心诊疗要点、控制靶标或推荐意见..." required></textarea>
                </div>
                <div class="form-group">
                    <label>关联高发疾病实体 / 规范概念 (逗号分隔)</label>
                    <input type="text" id="inpRelated" placeholder="例如：2型糖尿病, 原发性高血压, 骨质疏松症">
                </div>
                <div class="form-group">
                    <label>原始文献正文 / 核心章节 Markdown (可选，支持长文粘贴)</label>
                    <textarea id="inpContent" rows="4" placeholder="在此粘贴文献官方原文、章节条款或诊断标准..."></textarea>
                </div>
                <div class="modal-actions">
                    <button type="button" class="btn-cancel" onclick="closeImportModal()">取消</button>
                    <button type="submit" class="btn-submit" id="btnSubmitImport">🚀 编译并导入本知识库</button>
                </div>
            </form>
        </div>
    </div>

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
    drug_repo: DrugInsertRepository = DrugInsertRepository(root_dir)
    drug_auditor: DrugContraindicationAuditor = DrugContraindicationAuditor(drug_repo)
    evidence_engine: EvidenceChainEngine = EvidenceChainEngine(root_dir)

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
                "drug_inserts": len(self.drug_repo.list_all()),
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
        elif path == "/api/cdss/calculators":
            self._send_json({
                "calculators": [
                    {"name": "cha2ds2_vasc", "title": "CHA2DS2-VASc 房颤卒中风险评估与抗凝决策", "params": ["age", "gender", "chf", "htn", "dm", "stroke", "vascular"]},
                    {"name": "has_bled", "title": "HAS-BLED 房颤抗凝出血风险评估", "params": ["age", "sbp_gt_160", "renal_disease", "liver_disease", "stroke_history", "bleeding_history", "labile_inr", "antiplatelet", "alcohol_abuse"]},
                    {"name": "curb_65", "title": "CURB-65 社区获得性肺炎严重度与收治场所", "params": ["age", "confusion", "bun", "rr", "sbp", "dbp"]},
                    {"name": "centor", "title": "Centor-McIsaac 急性咽扁桃体炎链球菌概率与抗菌决策", "params": ["age", "tonsil_exudate", "tender_cervical_nodes", "temp", "no_cough"]},
                    {"name": "renal_clearance", "title": "eGFR (2021 CKD-EPI) 与 Cockcroft-Gault 肾清除率", "params": ["age", "gender", "scr", "weight"]},
                    {"name": "child_pugh", "title": "Child-Pugh 肝硬化肝功能储备评分与分级", "params": ["bili", "alb", "inr", "ascites", "encephalopathy"]},
                    {"name": "pediatric_fluid", "title": "儿童急性腹泻脱水补液量估算 (Holliday-Segar + ORS-III)", "params": ["weight_kg", "dehydration"]},
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
        elif path in ("/api/sources", "/api/knowledge/sources"):
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
        elif path == "/api/drugs":
            category = query_params.get("category", [""])[0]
            q = query_params.get("q", [""])[0]
            if q:
                drugs = self.drug_repo.search(q, limit=20)
                data = [{
                    "id": d["id"],
                    "genericName": d["generic_name"],
                    "englishName": d["english_name"],
                    "category": d["category"],
                    "atcCode": d["atc_code"],
                    "approvalCategory": d["approval_category"],
                    "tradeNames": d["trade_names"],
                    "standardDosage": d["standard_maintenance_dose"],
                    "maxDailyDose": d["max_daily_dose"],
                    "keyContraindications": d["key_contraindications"],
                    "relPath": d["rel_path"],
                } for d in drugs]
            else:
                all_drugs = self.drug_repo.list_all()
                if category:
                    all_drugs = [d for d in all_drugs if category in d["category"]]
                data = [{
                    "id": d["id"],
                    "genericName": d["generic_name"],
                    "englishName": d["english_name"],
                    "category": d["category"],
                    "atcCode": d["atc_code"],
                    "approvalCategory": d["approval_category"],
                    "tradeNames": d["trade_names"],
                    "standardDosage": d["standard_maintenance_dose"],
                    "maxDailyDose": d["max_daily_dose"],
                    "keyContraindications": d["key_contraindications"],
                    "relPath": d["rel_path"],
                } for d in all_drugs]
            self._send_json(data)
        elif path.startswith("/api/drugs/"):
            raw_id = path[len("/api/drugs/"):]
            drug_name = urllib.parse.unquote(raw_id)
            d = self.drug_repo.get(drug_name)
            if d:
                html_body = self._markdown_to_html(d["raw_body"])
                self._send_json({
                    "id": d["id"],
                    "genericName": d["generic_name"],
                    "englishName": d["english_name"],
                    "category": d["category"],
                    "atcCode": d["atc_code"],
                    "approvalCategory": d["approval_category"],
                    "tradeNames": d["trade_names"],
                    "formsAndSpecs": d["forms_and_specs"],
                    "maxDailyDose": d["max_daily_dose"],
                    "standardMaintenanceDose": d["standard_maintenance_dose"],
                    "keyContraindications": d["key_contraindications"],
                    "specialPopulations": d["special_populations"],
                    "storage": d["storage"],
                    "sources": d["sources"],
                    "tags": d["tags"],
                    "title": d["title"],
                    "relPath": d["rel_path"],
                    "html": html_body,
                })
            else:
                self._send_json({"error": "Drug monograph not found", "query": drug_name}, status=404)
        elif path in ("/api/wiki/doc", "/api/knowledge/doc"):
            self._handle_wiki_doc(query_params)
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
        elif path in ("/api/cdss/evidence-chain", "/api/knowledge/evidence-chain"):
            self._handle_evidence_chain(payload)
        elif path in ("/api/cdss/calculate", "/api/calculator"):
            calc_name = payload.get("calculator") or payload.get("name") or ""
            params = payload.get("params") or payload.get("parameters") or payload
            try:
                res = ClinicalCalculatorRegistry.calculate(calc_name, params)
                self._send_json({"success": True, "data": res})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, status=400)
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
        elif path in ("/api/cdss/preflight-safety", "/api/cdss/preflight", "/api/preflight-safety", "/api/knowledge/preflight-safety"):
            meds = payload.get("medications") or payload.get("meds") or payload.get("items") or []
            patient = payload.get("patient") or payload.get("patientContext") or payload.get("profile") or {}
            res = self.cdss.audit_preflight_safety(meds, patient)
            self._send_json(res)
        elif path in ("/api/knowledge/import-source", "/api/sources/import"):
            self._handle_import_source(payload)
        elif path == "/api/drugs/check-contraindications":
            meds = payload.get("medications") or []
            if isinstance(meds, str):
                meds = [meds]
            single_drug = payload.get("drug")
            if single_drug and not meds:
                meds = [single_drug]
            patient = payload.get("patient", {})
            if len(meds) == 1:
                res = self.drug_auditor.audit(meds[0], patient)
            else:
                res = self.drug_auditor.audit_prescription(meds, patient)
            self._send_json(res)
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_import_source(self, payload: Dict[str, Any]) -> None:
        """
        Imports and compiles a newly discovered clinical guideline or medical standard:
        1. Validates and generates metadata in raw/metadata.json
        2. Archives raw document markdown in raw/docs/{source_id}.md
        3. Compiles structured wiki study guide in wiki/sources/{source_id}.md
        4. Updates master index wiki/index.md and audit log wiki/log.md
        5. Updates SQLite FTS5 search index and in-memory WikiGraph
        """
        title = (payload.get("title") or "").strip()
        if not title:
            self._send_json({"success": False, "error": "指南/标准官方全称 (title) 不能为空"}, status=400)
            return

        authority = (payload.get("authority") or "国家卫生健康委员会 / 中华医学会").strip()
        category = (payload.get("category") or "临床医学综合").strip()
        year = int(payload.get("year") or 2024)
        summary = (payload.get("summary") or f"收录《{title}》，规范临床诊疗路径与合理用药。").strip()
        content = (payload.get("content") or "").strip()
        source_id = (payload.get("source_id") or "").strip().upper()
        raw_related = payload.get("related_diseases") or []
        if isinstance(raw_related, str):
            related_items = [d.strip() for d in re.split(r"[,，、;；]", raw_related) if d.strip()]
        else:
            related_items = list(raw_related)

        # Generate source_id if not given
        if not source_id:
            abbr = re.sub(r"[^A-Za-z0-9]", "", category)[:4].upper() or "CLIN"
            existing_ids = {s["id"] for s in self.collector.list_sources()}
            counter = 1
            source_id = f"SRC-USER-{abbr}-{year}-{counter:02d}"
            while source_id in existing_ids:
                counter += 1
                source_id = f"SRC-USER-{abbr}-{year}-{counter:02d}"

        # 1. Register in raw/metadata.json
        file_rel = f"raw/docs/{source_id}.md"
        self.collector.register_source(
            source_id=source_id,
            title=title,
            authority=authority,
            year=year,
            category=category,
            file_path=file_rel,
            key_scope=summary,
            level="国家级临床诊疗指南与行业标准",
        )

        # 2. Write raw document in raw/docs/{source_id}.md
        raw_doc_path = self.root_dir / file_rel
        raw_doc_path.parent.mkdir(parents=True, exist_ok=True)
        if not content:
            content = f"# 《{title}》原始文献归档\n\n- **制定机构**: {authority}\n- **发布年份**: {year}年\n- **专科分类**: {category}\n\n## 核心内容与指引摘要\n{summary}\n"
        raw_doc_path.write_text(content.strip().replace("~", "～") + "\n", encoding="utf-8")

        # 3. Resolve related disease links safely (only [[link]] if page exists)
        related_links_list = []
        for item in related_items:
            resolved = self.graph.resolve_link(item)
            if resolved and resolved in self.graph.pages:
                related_links_list.append(f"- [[{item}]]")
            else:
                related_links_list.append(f"- {item}")

        if not related_links_list:
            related_links_list = ["- [[index]] (医学知识库主索引)"]
        else:
            related_links_list.append("- [[index]] (医学知识库主索引)")

        related_links_text = "\n".join(related_links_list)

        core_points_lines = [p.strip() for p in summary.split("\n") if p.strip()]
        core_points_text = "\n".join([f"- {p}" for p in core_points_lines]) if core_points_lines else f"- {summary}"

        clean_title = title.replace("《", "").replace("》", "")
        today_str = datetime.now().strftime("%Y-%m-%d")

        wiki_source_content = f"""---
title: 《{clean_title}》研读导读
type: source
tags:
  - 医学指南/{category}
  - 权威指南/动态录入
aliases:
  - 《{clean_title}》
  - {clean_title}
sources:
  - {source_id}
last_updated: "{today_str}"
status: verified
---

# 《{clean_title}》研读导读

> [!NOTE] 权威来源元数据
> - **来源标识代码 (ID)**: `{source_id}`
> - **制定发布机构**: {authority}
> - **发布年份**: {year} 年
> - **专科分类**: {category}
> - **原始文献归档**: [`{file_rel}`](file:///{file_rel})

---

## 一、 指南/规范核心要点提炼
{core_points_text}

---

## 二、 临床诊疗路径指引
1. **诊断与风险分层**：严格参照本规范推荐的诊断切点与分层评估流程。
2. **规范化干预方案**：优先选择一线推荐治疗与药物方案，注意禁忌证与特殊人群监护。
3. **随访与健康宣教**：实施连续性健康管理，指导患者规律复诊与危险因素干预。

---

## 三、 知识网络关联与适用疾病
{related_links_text}
"""
        wiki_source_content = wiki_source_content.replace("~", "～")
        wiki_source_path = self.root_dir / "wiki" / "sources" / f"{source_id}.md"
        wiki_source_path.parent.mkdir(parents=True, exist_ok=True)
        wiki_source_path.write_text(wiki_source_content.strip() + "\n", encoding="utf-8")

        # 4. Update wiki/index.md (add to sources table)
        index_path = self.root_dir / "wiki" / "index.md"
        if index_path.exists():
            idx_text = index_path.read_text(encoding="utf-8")
            clean_summary = summary.replace("\n", " ")[:60].replace("~", "～")
            new_row = f"| [[{source_id}]] | 《{clean_title}》 | {authority} | {category} | {clean_summary}... |\n"

            section_marker = "### J. 临床在线动态录入权威标准 (动态扩充)"
            if section_marker in idx_text:
                header = section_marker + "\n| 来源 ID | 官方指南全称 | 发布机构 | 专科领域 | 核心导读 |\n| :--- | :--- | :--- | :--- | :--- |\n"
                idx_text = idx_text.replace(header, header + new_row)
            else:
                table_block = f"{section_marker}\n| 来源 ID | 官方指南全称 | 发布机构 | 专科领域 | 核心导读 |\n| :--- | :--- | :--- | :--- | :--- |\n{new_row}\n---\n\n"
                insert_target = "## 2. 疾病与健康主诉实体库 (Diseases & Conditions)"
                if insert_target in idx_text:
                    idx_text = idx_text.replace(insert_target, table_block + insert_target)
                else:
                    idx_text = idx_text.replace("## 2. 疾病与健康主诉实体库", table_block + "## 2. 疾病与健康主诉实体库")

            # Bump count in overview block if present
            current_count = len(self.collector.list_sources())
            idx_text = re.sub(r"├── 1\. 权威来源层 \(wiki/sources/\)\s+->\s+\d+\s+部",
                              f"├── 1. 权威来源层 (wiki/sources/)           -> {current_count} 部", idx_text)
            index_path.write_text(idx_text, encoding="utf-8")

        # 5. Append to wiki/log.md
        log_path = self.root_dir / "wiki" / "log.md"
        if log_path.exists():
            log_text = log_path.read_text(encoding="utf-8")
            log_entry = f"\n- **[Web在线录入]**: 新增收录权威标准《{clean_title}》（`{source_id}`，{authority}，{year}年）。\n"
            log_path.write_text(log_text.rstrip() + log_entry, encoding="utf-8")

        # 6. Re-index SQLite FTS5 incrementally
        try:
            self.searcher.index_wiki(incremental=True)
        except Exception as e:
            print(f"Index update warning: {e}")

        # 7. Reload in-memory graph
        self.graph.load_graph()

        self._send_json({
            "success": True,
            "source_id": source_id,
            "page_id": source_id,
            "title": f"《{clean_title}》",
            "message": f"权威标准《{clean_title}》已成功收录至知识库！已自动生成导读、挂接主索引并完成全文检索索引建立。"
        })

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

    def _handle_wiki_doc(self, query_params: Dict[str, List[str]]) -> None:
        """
        Universal document retrieval endpoint for drug inserts, clinical guidelines,
        disease entities, and decision protocols.
        """
        raw_name = query_params.get("name", [""])[0].strip()
        raw_id = query_params.get("id", [""])[0].strip()
        raw_path = query_params.get("path", [""])[0].strip()
        doc_type = query_params.get("type", [""])[0].strip().lower()

        target = raw_id or raw_name or raw_path
        if not target:
            self._send_json({"error": "Missing query parameter 'id', 'name', or 'path'"}, status=400)
            return

        # 1. Try drug monograph if type is medication/drug/insert or not specified
        if doc_type in ("", "drug", "insert", "medication"):
            candidates = [target]
            token0 = target.split()[0].strip() if " " in target else ""
            if token0 and token0 not in candidates:
                candidates.append(token0)
            token_paren = re.split(r'[（\(]', target)[0].strip()
            if token_paren and token_paren not in candidates:
                candidates.append(token_paren)
            token_cleaned = re.sub(r'[\s0-9\.\*gmg片粒盒袋/]+$', '', target).strip()
            if token_cleaned and token_cleaned not in candidates:
                candidates.append(token_cleaned)

            d = None
            for cand in candidates:
                d = self.drug_repo.get(cand)
                if d:
                    break

            if not d:
                for cand in candidates:
                    drug_matches = self.drug_repo.search(cand, limit=1)
                    if drug_matches:
                        d = drug_matches[0]
                        break

            if d:
                html_body = self._markdown_to_html(d["raw_body"])
                self._send_json({
                    "id": d["id"],
                    "title": d["title"],
                    "type": "MEDICATION",
                    "category": d["category"],
                    "genericName": d["generic_name"],
                    "englishName": d["english_name"],
                    "atcCode": d["atc_code"],
                    "approvalCategory": d["approval_category"],
                    "tradeNames": d["trade_names"],
                    "formsAndSpecs": d["forms_and_specs"],
                    "maxDailyDose": d["max_daily_dose"],
                    "standardMaintenanceDose": d["standard_maintenance_dose"],
                    "keyContraindications": d["key_contraindications"],
                    "specialPopulations": d["special_populations"],
                    "storage": d["storage"],
                    "sources": d["sources"],
                    "tags": d["tags"],
                    "relPath": d["rel_path"],
                    "markdown": d["raw_body"],
                    "html": html_body,
                })
                return
            elif doc_type in ("drug", "insert", "medication"):
                # If explicitly querying a drug monograph, do not fallback to unrelated wiki documents
                self._send_json({"error": "Drug monograph not found", "query": target}, status=404)
                return

        # 2. Try protocol repository if type is protocol or not specified
        if doc_type in ("", "protocol"):
            prot = self.cdss.repo.get(target)
            if not prot and raw_name:
                matches = self.cdss.search_protocols(raw_name, limit=1)
                if matches:
                    prot = self.cdss.repo.get(matches[0]["protocolId"])
            if prot:
                html_body = self._markdown_to_html(prot.raw_text)
                self._send_json({
                    "id": prot.protocol_id,
                    "title": prot.title,
                    "type": "protocol",
                    "category": prot.category,
                    "icd10": prot.icd10,
                    "aliases": prot.aliases,
                    "sources": prot.sources,
                    "summary": prot.summary,
                    "relPath": f"protocols/{prot.file_path.name}",
                    "markdown": prot.raw_text,
                    "html": html_body,
                    "items": [it.to_rhn_intent_item() for it in prot.items],
                })
                return
            elif doc_type == "protocol":
                self._send_json({"error": "Clinical protocol not found", "query": target}, status=404)
                return

        # 3. Try WikiGraph (concepts, entities, sources)
        resolved_link = self.graph.resolve_link(target) or target
        clean_id = re.sub(r"\.md$", "", resolved_link).split("/")[-1]
        resolved = self.graph.resolve_link(clean_id) or clean_id
        page = self.graph.pages.get(resolved) or self.graph.pages.get(target)
        if not page:
            for sub in ("sources", "concepts", "entities/diseases", "entities"):
                p_cand = self.root_dir / "wiki" / sub / f"{clean_id}.md"
                if p_cand.exists():
                    from tools.compiler.compiler import WikiPage
                    page = WikiPage(p_cand, self.root_dir / "wiki")
                    break

        if page:
            html_body = self._markdown_to_html(page.raw_text)
            self._send_json({
                "id": page.file_path.stem,
                "title": page.title,
                "type": page.frontmatter.get("type", "wiki_page"),
                "category": page.frontmatter.get("category", ""),
                "frontmatter": page.frontmatter,
                "relPath": str(page.rel_path),
                "markdown": page.raw_text,
                "html": html_body,
            })
            return

        # 4. Search fallback: find closest matching article (only if type is not strictly restricted)
        if doc_type in ("", "wiki", "concept", "source", "guideline"):
            search_hits = self.searcher.search(target, limit=1)
            if search_hits:
                hit = search_hits[0]
                hit_page = self.graph.pages.get(hit["id"])
                if hit_page:
                    html_body = self._markdown_to_html(hit_page.raw_text)
                    self._send_json({
                        "id": hit_page.file_path.stem,
                        "title": hit_page.title,
                        "type": hit_page.frontmatter.get("type", "wiki_page"),
                        "frontmatter": hit_page.frontmatter,
                        "relPath": str(hit_page.rel_path),
                        "markdown": hit_page.raw_text,
                        "html": html_body,
                    })
                    return

        self._send_json({"error": "Document not found", "query": target}, status=404)

    def _handle_evidence_chain(self, payload: Dict[str, Any]) -> None:
        """
        Derives clinical evidence reasoning checklist, gap orders, and guideline citations.
        """
        diag_name = payload.get("diagnosis") or payload.get("diagnosisName") or payload.get("query") or ""
        diag_code = payload.get("diagnosisCode") or payload.get("code") or ""
        patient = payload.get("patient") or {}

        if not patient and ("vitals" in payload or "chiefComplaint" in payload):
            patient = {
                "age": payload.get("age"),
                "gender": payload.get("gender"),
                "chiefComplaint": payload.get("chiefComplaint"),
                "presentIllness": payload.get("presentIllness"),
                "physicalExam": payload.get("physicalExam"),
                "medicalHistory": payload.get("medicalHistory"),
                "vitals": payload.get("vitals", {}),
            }

        res = self.evidence_engine.evaluate(diag_name, diag_code, patient)
        self._send_json(res)

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
            # 1. Protocol-level prescription audit
            audit_res = self.cdss.audit_prescription(medications_to_audit, patient_profile)
            safety_alerts = []
            seen_alert_titles = set()
            for a in audit_res.get("alerts", []):
                safety_alerts.append({
                    "level": "CRITICAL" if a.get("severity") == "RED" else "WARNING",
                    "title": a.get("title", "处方安全预警"),
                    "detail": a.get("message", ""),
                })
                seen_alert_titles.add(a.get("title"))

            # 2. Monograph-level CDSS contraindication & DDI audit (covering 100 essential drugs)
            if medications_to_audit:
                drug_audit = self.drug_auditor.audit_prescription(medications_to_audit, patient_profile)
                for da in drug_audit.get("alerts", []):
                    title = da.get("title", "药品说明书安全阻断")
                    if title not in seen_alert_titles:
                        safety_alerts.append({
                            "level": "CRITICAL" if da.get("level") == "BLOCK" else "WARNING",
                            "title": title,
                            "detail": f"{da.get('reason', '')} (依据：{da.get('evidence', '')})",
                        })
                        seen_alert_titles.add(title)

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
                # Bold & standard GFM strikethrough (double-tilde)
                l = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", line)
                l = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", l)
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
    httpd = ThreadingHTTPServer(server_address, WikiHTTPHandler)
    print(f"🚀 Medical LLM Wiki Web Server is running on http://127.0.0.1:{port} (Multi-threaded)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server.")
        httpd.server_close()
