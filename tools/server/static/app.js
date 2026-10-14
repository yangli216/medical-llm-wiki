        let graphData = null;
        let currentPageId = "index";
        let currentView = "doc";
        let activeNavTab = "doc";

        function escapeHtml(value) {
            const node = document.createElement('span');
            node.textContent = String(value ?? '');
            return node.innerHTML;
        }

        async function refreshInventory() {
            const [statsResponse, qualityResponse] = await Promise.all([fetch('/api/inventory'), fetch('/api/quality')]);
            const stats = await statsResponse.json();
            const quality = await qualityResponse.json();
            const types = stats.type_counts;
            document.getElementById('topbarStats').innerHTML = [
                `🏛️ ${stats.registered_sources} 来源`, `🫀 ${types.disease || 0} 疾病`,
                `📋 ${types.protocol || 0} 协议`, `📖 ${types.drug_insert || 0} 说明书整理页`,
                `🛡️ ${stats.rules_by_file.clinical_safety_rules || 0} 临床规则`
            ].map(label => `<span class="stat-badge">${escapeHtml(label)}</span>`).join('');
            document.getElementById('qualityBanner').textContent =
                `原始文件归档 ${quality.originalsArchived}/${quality.sources}；来源核验 ${quality.provenanceVerified}/${quality.sources}；临床审核 ${quality.clinicallyReviewedPages}/${quality.clinicalPages} 内容页、${quality.clinicallyReviewedRules}/${quality.rules} 规则。` +
                (quality.clinicalReady ? '审核记录完整。' : '待审核内容需由医师或药师核对后采用。');
        }

        async function init() {
            try {
                const resp = await fetch('/api/graph');
                graphData = await resp.json();
                renderNavTree();
                await refreshInventory();
                await loadPage(new URLSearchParams(location.search).get('page') || 'index');
                setupCanvas();
                setupPdfDropzone();
            } catch (err) {
                console.error('Initialization error:', err);
                document.getElementById('docBody').innerHTML = `
                    <div style="background:rgba(239,68,68,0.15);border:1px solid #ef4444;border-radius:8px;padding:24px;margin-top:20px;">
                        <h3 style="color:#f87171;margin-bottom:8px;">⚠️ 加载本地知识库遇到问题</h3>
                        <p style="color:#cbd5e1;font-size:0.9rem;">错误详情: ${escapeHtml(err.message)}</p>
                        <button onclick="location.reload()" style="margin-top:12px;padding:8px 16px;background:#0284c7;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600;">🔄 重新加载</button>
                    </div>`;
            }
        }

        document.addEventListener('click', (event) => {
            const link = event.target.closest('a.wikilink[data-page]');
            if (link) { event.preventDefault(); loadPage(link.dataset.page); }
        });

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
                catEl.innerHTML = `<div class="cat-title">登记资料来源 (${srcNodes.length})</div>`;
                srcNodes.forEach(n => {
                    const item = document.createElement('div');
                    item.className = `tree-item ${n.id === currentPageId ? 'active' : ''}`;
                    item.innerHTML = `<span>🏛️ ${escapeHtml(n.title)}</span><span class="badge">来源</span>`;
                    item.onclick = () => loadPage(n.id);
                    catEl.appendChild(item);
                });
                container.appendChild(catEl);
                return;
            }

            const groups = {
                'protocol': { title: '📋 门诊临床推荐方案', items: [] },
                'synthesis': { title: '💡 综合与共病专题', items: [] },
                'disease': { title: '🫀 疾病实体库', items: [] },
                'drug': { title: '💊 药物与核心疗法', items: [] },
                'drug_insert': { title: '📖 药品说明书整理页', items: [] },
                'concept': { title: '📐 诊断标准与临床量表', items: [] },
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
                    item.innerHTML = `<span>${escapeHtml(n.title)}</span><span class="badge">${n.in_degree} 引用</span>`;
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
                    <div><strong>类别:</strong> <code>${escapeHtml(data.frontmatter.type || '未分类')}</code></div>
                    <div><strong>最后更新:</strong> ${escapeHtml(data.frontmatter.last_updated || '未记录')}</div>
                    <div><strong>临床审核:</strong> ${data.clinicalReview?.status === 'approved' ? '已审核（记录有效）' : '待审核'}</div>
                    ${data.frontmatter.tags ? `<div><strong>标签:</strong> ${data.frontmatter.tags.map(t=>`<span class="meta-tag">${escapeHtml(t)}</span>`).join(' ')}</div>` : ''}
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
                item.innerHTML = `<div><div style="font-weight:600;">${escapeHtml(h.title)}</div><div style="font-size:0.75rem;color:#94a3b8;">${escapeHtml(h.snippet.slice(0, 40))}...</div></div>`;
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


                let uploadedPdfBase64 = null;

        function setupPdfDropzone() {
            const dropzone = document.getElementById('pdfDropzone');
            if (!dropzone) return;
            ['dragenter', 'dragover'].forEach(eventName => {
                dropzone.addEventListener(eventName, (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    dropzone.classList.add('dragover');
                }, false);
            });
            ['dragleave', 'drop'].forEach(eventName => {
                dropzone.addEventListener(eventName, (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    dropzone.classList.remove('dragover');
                }, false);
            });
            dropzone.addEventListener('drop', (e) => {
                const dt = e.dataTransfer;
                const files = dt.files;
                if (files && files.length > 0) {
                    handlePdfFileSelected(files);
                }
            }, false);
        }

        async function handlePdfFileSelected(files) {
            if (!files || files.length === 0) return;
            const file = files[0];
            if (!file.name.toLowerCase().endsWith('.pdf')) {
                alert('请上传标准 PDF 格式文件！');
                return;
            }

            const statusEl = document.getElementById('pdfParseStatus');
            statusEl.style.display = 'block';
            statusEl.style.background = 'rgba(2, 132, 199, 0.15)';
            statusEl.style.border = '1px solid #0284c7';
            statusEl.style.color = '#38bdf8';
            statusEl.innerHTML = `⏳ 正在深度解析 <strong>${escapeHtml(file.name)}</strong> (${(file.size / 1024).toFixed(1)} KB)...`;

            const reader = new FileReader();
            reader.onload = async function(e) {
                const dataUrl = e.target.result;
                uploadedPdfBase64 = dataUrl;

                try {
                    const resp = await fetch('/api/knowledge/parse-pdf', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            filename: file.name,
                            pdf_base64: dataUrl
                        })
                    });
                    const res = await resp.json();
                    if (res.success) {
                        statusEl.style.background = 'rgba(16, 185, 129, 0.15)';
                        statusEl.style.border = '1px solid #10b981';
                        statusEl.style.color = '#34d399';
                        statusEl.innerHTML = `✅ PDF 解析成功！共 ${res.total_pages} 页，已自动为您回填下方元数据、摘要与正文，您可按需微调后提交。`;

                        if (res.title) document.getElementById('inpTitle').value = res.title;
                        if (res.authority) document.getElementById('inpAuthority').value = res.authority;
                        if (res.category) document.getElementById('inpCategory').value = res.category;
                        if (res.year) document.getElementById('inpYear').value = res.year;
                        if (res.summary) document.getElementById('inpSummary').value = res.summary;
                        if (res.related_diseases) document.getElementById('inpRelated').value = res.related_diseases;
                        if (res.content) document.getElementById('inpContent').value = res.content;
                    } else {
                        statusEl.style.background = 'rgba(239, 68, 68, 0.15)';
                        statusEl.style.border = '1px solid #ef4444';
                        statusEl.style.color = '#f87171';
                        statusEl.innerHTML = `❌ PDF 解析失败: ${escapeHtml(res.error || '未知错误')}`;
                    }
                } catch (err) {
                    statusEl.style.background = 'rgba(239, 68, 68, 0.15)';
                    statusEl.style.border = '1px solid #ef4444';
                    statusEl.style.color = '#f87171';
                    statusEl.innerHTML = `❌ 解析请求异常: ${escapeHtml(err.message)}`;
                }
            };
            reader.readAsDataURL(file);
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
            document.getElementById('inpSourceId').value = '';
            document.getElementById('inpYear').value = 2024;
            document.getElementById('inpSummary').value = `1. 诊断切点：成人 BMI ≥ 24 kg/m² 为超重，≥ 28 kg/m² 为肥胖；男性腰围 ≥ 90cm、女性 ≥ 85cm 为中心型肥胖。
2. 饮食干预：控制总能量摄入，推荐每日能量摄入减少 500～1000 kcal；优质蛋白质占比达 50% 以上。
3. 减重靶标：以 6 个月内体重减轻 5%～10% 为适宜目标，严禁剧烈极低能量禁食。`;
            document.getElementById('inpRelated').value = '2型糖尿病, 原发性高血压, 动脉粥样硬化性心血管疾病';
            document.getElementById('inpContent').value = `# 《成人肥胖食养指南（2024年版）》核心条款归档

## 一、 流行病学与危害
我国成人超重肥胖率已达 50.7%，肥胖是高血压、2型糖尿病、心血管疾病与部分恶性肿瘤的独立高危危险因素。

## 二、 食养原则与建议
1. 控制总能量摄入，循序渐进减重；
2. 宏量营养素配比合理，多全谷物、少精制糖；
3. 充足微量营养素与膳食纤维摄入；
4. 戒烟限酒，规律睡眠与抗阻有氧运动结合。`;
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
                content: document.getElementById('inpContent').value.trim(),
                pdf_base64: uploadedPdfBase64,
                official_url: document.getElementById('inpOfficialUrl').value.trim(),
                doi: document.getElementById('inpDoi').value.trim()
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
                    await refreshInventory();
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
