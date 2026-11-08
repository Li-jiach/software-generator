const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const backendOrigin = window.location.port === '8080' ? '' : 'http://127.0.0.1:8080';
const storage = { get: (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } }, set: (key, value) => localStorage.setItem(key, JSON.stringify(value)) };

const sampleProfile = { name: '医疗影像运维管理系统', shortName: '', version: 'V1.0', acquisition: '原始取得', rights: '全部权利', publication: '未发表', completionDate: '2024-04-10', owner: '上海人工智能创新中心', category: '应用软件', development: '单独开发', languages: 'Java、JavaScript', purpose: '为医生和企业提供医疗数据服务，发掘数据价值，提升医疗影像数据管理与运维效率。', industry: '医疗领域', function: '系统负责管理治理后的数据申请审核，对系统进行运维管理，也对平台标注功能进行管理，记录相关规则学习情况。系统管理包括机构、字典、用户、角色、菜单和操作记录的运维管理；标注管理包括标签、标签模板和工具的运维管理。', feature: '大数据软件。提供医疗影像数据从数据申请审核、系统管理、标注管理到学习情况管理的运维管理功能，支持对项目相关学习情况进行记录管理。', devHardware: 'CPU: Intel(R) Xeon(R) Gold 6151；内存: 32GB；硬盘: 120GB', runHardware: 'CPU: Intel(R) Core(TM) i7-7700；内存: 16GB；硬盘: 1T', devOs: 'Windows 10', devTools: 'Java + Spring Cloud、Vue.js + ElementUI、Mybatis', runOs: 'Windows 7、Windows 10', support: 'Chrome、Firefox、兼容浏览器极速模式、MySQL', sourceLines: '约 31000 行' };
const blankProfile = Object.fromEntries(Object.keys(sampleProfile).map(key => [key, '']));
const requiredProfileFields = ['name', 'version', 'owner', 'purpose', 'function', 'feature'];
let profile = storage.get('studioProfileV2', blankProfile), aiConfig = storage.get('studioAiConfigV2', { endpoint: '', mode: 'chat', model: '', apiKey: '' }), nodes = storage.get('studioNodesV2', []), connections = storage.get('studioConnectionsV2', []), copyrights = storage.get('studioCopyrightsV2', []), generated = storage.get('studioGeneratedV2', {}), activeCopyrightId = storage.get('studioActiveCopyrightV2', '');
let workspaceTimer = null, aiConfigTimer = null, globalAiConfigLoaded = false, projectCreationPromise = null, dragState = null, panState = null, connectionState = null, pendingDropPosition = null, canvasZoom = 1, undoStack = [], generationState = { running: false, paused: false, queue: [], index: 0, currentNodeId: '' };
let restructureProgressTimer = null, restructureProgressStartedAt = 0;
nodes = nodes.map((node, index) => node.layoutVersion ? node : { ...node, x: 70 + (index % 3) * 290, y: 60 + Math.floor(index / 3) * 250, layoutVersion: 2 });

function toast(message, type = 'success') { const el = document.createElement('div'); el.className = `toast ${type}`; el.textContent = message; $('#toastStack').appendChild(el); setTimeout(() => el.remove(), 3200); }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c])); }
function uid(prefix = 'id') { return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`; }
function profileComplete(value = profile) { return requiredProfileFields.every(key => String(value[key] || '').trim()); }
function localPersist() { storage.set('studioProfileV2', profile); storage.set('studioAiConfigV2', aiConfig); storage.set('studioNodesV2', nodes); storage.set('studioConnectionsV2', connections); storage.set('studioCopyrightsV2', copyrights); storage.set('studioGeneratedV2', generated); storage.set('studioActiveCopyrightV2', activeCopyrightId); }
function pushUndoState() { undoStack.push({ nodes: JSON.parse(JSON.stringify(nodes)), connections: JSON.parse(JSON.stringify(connections)), generated: JSON.parse(JSON.stringify(generated)) }); if (undoStack.length > 30) undoStack.shift(); }
function undoLastOperation() { const previous = undoStack.pop(); if (!previous) { toast('没有可撤回的操作', 'error'); return; } nodes = previous.nodes; connections = previous.connections; generated = previous.generated; saveWorkspace(); renderCanvas(); toast('已撤回上一步操作'); }
function api(path, options = {}) { return fetch(`${backendOrigin}/api${path}`, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options }).then(async response => { const text = await response.text(); let data = null; try { data = text ? JSON.parse(text) : null; } catch { data = text; } if (!response.ok) throw new Error(data?.message || data?.detail || `请求失败（${response.status}）`); return data; }); }
function configuredAi() { return Boolean(aiConfig.endpoint.trim() && aiConfig.model.trim()); }
function saveAiConfig() { localPersist(); clearTimeout(aiConfigTimer); aiConfigTimer = setTimeout(async () => { try { await api('/ai-config', { method: 'PUT', body: JSON.stringify(aiConfig) }); globalAiConfigLoaded = true; } catch (error) { toast(`模型设置未保存到数据库：${error.message}`, 'error'); } }, 500); }
function saveWorkspace() { localPersist(); clearTimeout(workspaceTimer); workspaceTimer = setTimeout(async () => { if (!activeCopyrightId || !/^[0-9]+$/.test(String(activeCopyrightId))) return; try { const item = copyrights.find(value => String(value.id) === String(activeCopyrightId)), metadata = copyrightPayloadFromProfile(); await api(`/copyrights/${activeCopyrightId}`, { method: 'PUT', body: JSON.stringify({ ...metadata, status: item?.status || '草稿', assetPath: item?.assetPath || '' }) }); await api(`/copyrights/${activeCopyrightId}/workspace`, { method: 'PUT', body: JSON.stringify({ profile, aiConfig, nodes, connections, generated }) }); if (item) Object.assign(item, metadata); localPersist(); renderLibrary(); } catch {} }, 500); const state = $('#saveState'); if (state) { state.textContent = '● 已自动保存'; setTimeout(() => { state.textContent = '● 已保存'; }, 1100); } }

function switchView(view) { $$('.nav-item[data-view]').forEach(button => button.classList.toggle('active', button.dataset.view === view)); $$('.view').forEach(section => section.classList.toggle('active', section.id === `view-${view}`)); $('#breadcrumbTitle').textContent = ({ foundation: '基础信息', manual: '操作手册', library: '软著库', settings: '模型设置', test: '测试用例' })[view]; if (view === 'foundation') refreshFoundationProjects(); if (view === 'manual') refreshManualProjects(); if (view === 'library') renderLibrary(); }
$$('.nav-item[data-view]').forEach(button => button.addEventListener('click', () => switchView(button.dataset.view))); $$('[data-view-target]').forEach(button => button.addEventListener('click', () => switchView(button.dataset.viewTarget)));

function renderProfile() { $$('[data-field]').forEach(input => { input.value = profile[input.dataset.field] ?? ''; }); ['purpose', 'industry', 'function', 'feature'].forEach(updateCounter); updateCompletion(); }
function updateCounter(field) { const input = $(`[data-field="${field}"]`), counter = $(`[data-counter="${field}"]`); if (input && counter) counter.textContent = `${input.value.length} / ${input.maxLength}`; }
function updateCompletion() { const complete = requiredProfileFields.filter(key => String(profile[key] || '').trim()).length, percent = Math.round(complete / requiredProfileFields.length * 100); $('#formProgress').style.width = `${percent}%`; $('#completionBar').style.width = `${percent}%`; $('#completionPercent').textContent = `${percent}%`; $('#completionHint').textContent = percent === 100 ? '基础信息已完整，可以进入下一步' : `还需完善 ${requiredProfileFields.length - complete} 项必填信息`; [['checkIdentity', ['name', 'version']], ['checkDev', ['owner']], ['checkFeature', ['purpose', 'function', 'feature']]].forEach(([id, keys]) => { const el = $(`#${id}`), done = keys.every(key => String(profile[key] || '').trim()); el.classList.toggle('done', done); el.textContent = `${done ? '●' : '○'} ${el.textContent.slice(2)}`; }); }
$$('[data-field]').forEach(input => input.addEventListener('input', () => { profile[input.dataset.field] = input.value; updateCounter(input.dataset.field); updateCompletion(); if (String(profile.name || '').trim()) ensureManualProject().then(saved => saved && saveWorkspace()); else saveWorkspace(); }));
function copyrightPayloadFromProfile() { return { name: String(profile.name || '').trim(), shortName: String(profile.shortName || '').trim(), version: String(profile.version || '').trim(), owner: String(profile.owner || '').trim(), industry: String(profile.industry || '').trim(), completionDate: profile.completionDate || null }; }
async function ensureManualProject() {
  if (activeCopyrightId && /^[0-9]+$/.test(String(activeCopyrightId))) return true;
  if (projectCreationPromise) return projectCreationPromise;
  const payload = { ...copyrightPayloadFromProfile(), status: '草稿', assetPath: '' };
  projectCreationPromise = (async () => { try {
    const server = await api('/copyrights', { method: 'POST', body: JSON.stringify(payload) });
    if (!server?.id) throw new Error('软著项目创建失败');
    activeCopyrightId = String(server.id);
    copyrights.unshift({ ...payload, id: server.id });
    localPersist();
    await api(`/copyrights/${server.id}/workspace`, { method: 'PUT', body: JSON.stringify({ profile, aiConfig, nodes, connections, generated }) });
    return true;
  } catch (error) {
    toast(`自动入库失败：${error.message || '请求失败'}`, 'error');
    return false;
  } finally { projectCreationPromise = null; } })();
  return projectCreationPromise;
}
$('#toManualBtn').addEventListener('click', async () => { if (!profileComplete()) { toast('请先完成基础信息中的必填字段', 'error'); return; } const saved = await ensureManualProject(); if (saved) switchView('manual'); });

async function optimize(field) { if (!configuredAi()) { toast('请先在模型设置中配置 API 地址和模型名称', 'error'); return; } const input = $(`[data-field="${field}"]`), button = $(`[data-optimize="${field}"]`), original = button.textContent; button.disabled = true; button.textContent = '生成中…'; try { const result = await api('/ai/optimize', { method: 'POST', body: JSON.stringify({ text: input.value, field, settings: { endpoint: aiConfig.endpoint, mode: aiConfig.mode, model: aiConfig.model, api_key: aiConfig.apiKey } }) }); if (result?.error) throw new Error(result.detail || result.message || 'AI 服务调用失败'); if (!result?.text) throw new Error('AI 服务没有返回优化文本'); input.value = result.text; profile[field] = result.text; updateCounter(field); updateCompletion(); saveWorkspace(); toast('AI 已完成优化'); } catch (error) { toast(error.message || 'AI 优化失败', 'error'); } finally { button.disabled = false; button.textContent = original; } }
$$('[data-optimize]').forEach(button => button.addEventListener('click', () => optimize(button.dataset.optimize)));

function configureManualShell() { $('#view-manual .manual-aside')?.remove(); $('#view-manual .manual-reader')?.remove(); const intro = $('#view-manual .manual-heading > div'); if (intro && !$('#manualCopyrightSelect')) intro.insertAdjacentHTML('afterbegin', '<div class="manual-project-menu"><span>操作软著</span><select id="manualCopyrightSelect"><option value="">暂无可用软著</option></select></div>'); const actions = $('#view-manual .heading-actions'); if (actions && !$('#pauseGenerationBtn')) actions.insertAdjacentHTML('afterbegin', '<button class="btn ghost" id="pauseGenerationBtn" hidden>暂停生成</button>'); $('#generateManualBtn').innerHTML = '<span>✦</span> 完整生成'; $('#view-manual .manual-workspace').classList.add('canvas-only'); }
configureManualShell();
$('#view-manual .manual-heading > div').insertAdjacentHTML('beforeend', '<div class="manual-generation-status" id="generationText" role="status" aria-live="polite">等待开始完整生成</div>');
// The workflow is intentionally explicit: generate component text, restructure it,
// then export the template-based package. Screenshot grouping is no longer used.
const manualActions = $('#view-manual .heading-actions');
if (manualActions && !$('#restructureManualBtn')) manualActions.insertAdjacentHTML('beforeend', '<button class="btn ghost" id="restructureManualBtn" disabled>全量重构</button><button class="btn ghost" id="exportManualBtn" disabled>完整导出</button><div class="restructure-progress-wrap" id="restructureProgressWrap" hidden><div class="restructure-progress-head"><span>全量重构</span><strong id="restructureProgressText">0%</strong></div><div class="restructure-progress"><i id="restructureProgressFill"></i></div><small id="restructureProgressDetail">准备开始</small></div>');
$('#generateManualBtn').innerHTML = '<span>✦</span> 完整生成';
$('#resetCanvasBtn').textContent = '↶ 撤回操作';
// These actions operate on selected manual components, so they belong to the
// 操作手册 toolbar rather than the first heading-actions block (基础信息).
$('#view-manual .heading-actions').insertAdjacentHTML('afterbegin', '<button class="btn ghost" id="regenerateBtn" hidden>重新生成</button>');
$('#fallbackToggle')?.closest('.preference-row')?.remove();
$('.api-card-top small').textContent = '配置保存到数据库'; $('.api-card p').textContent = '基础信息中的“AI 优化”和完整手册生成共用此配置。未配置或调用失败时直接提示错误。'; $('.endpoint-card code:last-of-type').textContent = 'POST /generate-full';
$('.footer-tip').textContent = '从组件右侧拖到目标组件即可连线，截图可串联';

function nodeSize(node) {
  if (node.type === 'screenshot') return { width: 260, height: 285 };
  return { width: 220, height: 168 };
}
function getNode(id) { return nodes.find(node => node.id === id); } function getConnection(id) { return connections.find(connection => connection.id === id); } function pointRight(node) { const size = nodeSize(node); return { x: node.x + size.width, y: node.y + size.height / 2 }; } function pointLeft(node) { const size = nodeSize(node); return { x: node.x, y: node.y + size.height / 2 }; }
function validConnection(from, to) { const valid = { system: ['system', 'module', 'screenshot'], module: ['module', 'page', 'screenshot'], page: ['page', 'screenshot'], screenshot: ['screenshot'] }; if (!from || !to || from.id === to.id || !valid[from.type]?.includes(to.type)) return false; if (from.type === 'screenshot' && to.type === 'screenshot' && connections.some(item => item.fromId === from.id)) return false; if (to.type === 'screenshot' && connections.some(item => item.toId === to.id)) return false; if (to.type === 'screenshot' && from.type !== 'screenshot' && connections.some(item => item.fromId === from.id && getNode(item.toId)?.type === 'screenshot')) return false; return true; }
function connectionExists(fromId, toId) { return connections.some(connection => connection.fromId === fromId && connection.toId === toId); } function directTargets(id) { return connections.filter(connection => connection.fromId === id).map(connection => getNode(connection.toId)).filter(Boolean); }
function addNode(type, extra = {}) { pushUndoState(); const count = nodes.filter(node => node.type === type).length, position = nodes.length, size = nodeSize({ type }); const node = { id: uid('node'), type, name: extra.name || (type === 'screenshot' ? `截图 ${count + 1}` : `${type === 'system' ? '系统' : type === 'module' ? '模块' : '页面'} ${count + 1}`), x: extra.x ?? 70 + (position % 3) * 290, y: extra.y ?? 60 + Math.floor(position / 3) * 250, width: size.width, height: size.height, selected: false, layoutVersion: 2, ...extra }; nodes.push(node); saveWorkspace(); renderCanvas(); if (type !== 'screenshot') setTimeout(() => editNodeTitle(node, $(`.manual-node[data-id="${node.id}"]`)), 0); return node; }
function ensureCanvasStage() { const canvas = $('#canvas'); let stage = $('.canvas-stage', canvas); if (!stage) { stage = document.createElement('div'); stage.className = 'canvas-stage'; const grid = $('.canvas-grid', canvas), empty = $('#canvasEmpty'); if (grid) stage.appendChild(grid); if (empty) stage.appendChild(empty); canvas.prepend(stage); } let spacer = $('.canvas-scroll-size', canvas); if (!spacer) { spacer = document.createElement('div'); spacer.className = 'canvas-scroll-size'; canvas.appendChild(spacer); } return { canvas, stage, spacer }; }
function canvasBounds() { return nodes.reduce((result, node) => ({ width: Math.max(result.width, node.x + nodeSize(node).width + 180), height: Math.max(result.height, node.y + nodeSize(node).height + 180) }), { width: 1200, height: 760 }); }
function resizeCanvasToNodes() { const { stage, spacer } = ensureCanvasStage(), bounds = canvasBounds(); stage.style.width = `${bounds.width}px`; stage.style.height = `${bounds.height}px`; spacer.style.width = `${bounds.width * canvasZoom}px`; spacer.style.height = `${bounds.height * canvasZoom}px`; const svg = $('.connections-layer', stage); if (svg) { svg.setAttribute('width', bounds.width); svg.setAttribute('height', bounds.height); } }
function renderCanvas() { const { canvas, stage } = ensureCanvasStage(); $$('.manual-node', stage).forEach(element => element.remove()); $$('.connections-layer', stage).forEach(element => element.remove()); $('#canvasEmpty').style.display = nodes.length ? 'none' : 'flex'; $('#nodeCount').textContent = `${nodes.length} 个组件`; const bounds = canvasBounds(); stage.style.width = `${bounds.width}px`; stage.style.height = `${bounds.height}px`; stage.style.transform = `scale(${canvasZoom})`; resizeCanvasToNodes(); const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.classList.add('connections-layer'); svg.setAttribute('width', bounds.width); svg.setAttribute('height', bounds.height); stage.appendChild(svg); nodes.forEach(node => stage.appendChild(renderNode(node))); connections.forEach(renderConnection); renderDropDeleteZone(); updateManualStatus(); }
function screenshotChainIndex(node) { let current = node, index = 1, seen = new Set([node.id]); while (true) { const previous = connections.find(item => item.toId === current.id), parent = previous && getNode(previous.fromId); if (!parent || parent.type !== 'screenshot' || seen.has(parent.id)) return index; seen.add(parent.id); current = parent; index += 1; } }
function screenshotChain(node) {
  const chain = [], seen = new Set();
  while (node?.type === 'screenshot' && !seen.has(node.id)) {
    seen.add(node.id);
    chain.push(node);
    node = directTargets(node.id).find(child => child.type === 'screenshot');
  }
  return chain;
}
function screenshotChainHead(node) {
  let current = node, seen = new Set();
  while (current?.type === 'screenshot' && !seen.has(current.id)) {
    seen.add(current.id);
    const parentLink = connections.find(item => item.toId === current.id);
    const parent = parentLink && getNode(parentLink.fromId);
    if (!parent || parent.type !== 'screenshot') return current;
    current = parent;
  }
  return current || node;
}
function generatedScreenshot(node) {
  const head = screenshotChainHead(node);
  const bucket = generated.screenshots || {};
  const data = bucket[node?.id] || bucket[head?.id] || Object.entries(bucket).find(([id]) => String(id) === String(head?.id))?.[1] || {};
  return { ...data, operation: screenshotOperation(data.operation) };
}
function screenshotOperation(value) { const result = String(value || '').replace(/^截图内容\s*[:：]\s*/u, '').trim(); return result.startsWith('【') && result.endsWith('】') ? result.slice(1, -1).trim() : result; }
function generationNode(node) { return node; }
function renderNode(node) {
  const el = document.createElement('div');
  el.className = `manual-node type-${node.type}${node.selected ? ' selected' : ''}`;
  el.dataset.id = node.id; el.style.left = `${node.x}px`; el.style.top = `${node.y}px`;
  el.style.width = `${nodeSize(node).width}px`; el.style.height = `${nodeSize(node).height}px`;
  const isShot = node.type === 'screenshot';
  const data = isShot ? (node.type === 'screenshot' ? generatedScreenshot(node) : generated.screenshots?.[node.id]) : generated.nodes?.[node.id];
  const imageHtml = node.type === 'screenshot' && node.image ? `<img class="manual-node-image" src="${escapeHtml(node.image)}" alt="截图" />` : '';
  const screenshotNumber = node.type === 'screenshot' ? screenshotChainIndex(node) : '';
  const screenshotText = node.type === 'screenshot' ? `<div class="screenshot-generated"><div class="screenshot-operation">${escapeHtml(data?.operation || '生成后将在此显示操作说明')}</div><button class="node-edit-text">编辑操作说明</button></div>` : '';
  el.innerHTML = `<button class="node-delete" title="删除">×</button><span class="connector-dot target-dot" data-role="target"></span><span class="connector-dot source-dot" data-role="source"></span>${imageHtml}${node.type === 'screenshot' ? `<span class="screenshot-number">${screenshotNumber}</span>${screenshotText}` : `<div class="manual-node-title">${escapeHtml(node.name)}</div><div class="manual-node-summary">${escapeHtml(data?.contentSummary || '等待生成组件介绍')}</div><div class="manual-node-detail"><p>${escapeHtml(data?.contentSummary || '等待生成组件介绍')}</p><button class="node-edit-text">编辑介绍</button></div>`}`;
  $('.node-delete', el).addEventListener('mousedown', e => { e.stopPropagation(); e.preventDefault(); deleteNode(node.id); });
  const editTextButton = $('.node-edit-text', el);
  if (editTextButton) editTextButton.addEventListener('click', e => { e.stopPropagation(); pauseForEditing(); editGeneratedText(node); });
  $('.target-dot', el).addEventListener('mousedown', e => { e.stopPropagation(); e.preventDefault(); });
  $('.target-dot', el).addEventListener('mouseup', e => { if (connectionState) { e.stopPropagation(); e.preventDefault(); finishConnection(node.id); } });
  $('.target-dot', el).addEventListener('mouseenter', () => { if (connectionState) $('.target-dot', el).classList.add('highlight'); });
  $('.target-dot', el).addEventListener('mouseleave', () => $('.target-dot', el).classList.remove('highlight'));
  $('.source-dot', el).addEventListener('mousedown', e => { e.stopPropagation(); e.preventDefault(); startConnection(node.id); });
  el.addEventListener('mouseup', e => { if (connectionState && !e.target.closest('.connector-dot,.node-delete')) { e.stopPropagation(); e.preventDefault(); finishConnection(node.id); } });
  if (node.type === 'screenshot' && node.image) el.addEventListener('dblclick', e => { if (!e.target.closest('.node-delete,.connector-dot,.node-edit-text')) openScreenshotDetail(node); });
  el.addEventListener('mousedown', e => { if (e.target.closest('.connector-dot,.node-delete,.node-expand,.node-edit-text,.title-editor-input')) return; e.preventDefault(); if (node.type==='screenshot'&&!e.shiftKey) { node.selected=true; nodes.filter(item=>item.type!=='screenshot').forEach(item=>item.selected=false); } else if(e.shiftKey) node.selected=!node.selected; else { nodes.forEach(item=>item.selected=false); node.selected=true; } updateSelectionActions(); startElementDrag(node,e); });
  el.addEventListener('click', e => { if (e.target.closest('.connector-dot,.node-delete,.node-expand,.node-edit-text,.title-editor-input')) return; if (data) el.classList.add('detail-open'); });
  const titleElement = $('.manual-node-title', el);
  if (titleElement) titleElement.addEventListener('dblclick', e => { e.stopPropagation(); editNodeTitle(node, el); });
  el.addEventListener('dblclick', e => { if(node.type!=='screenshot'&&!e.target.closest('.manual-node-title')) el.classList.toggle('detail-open'); });
  return el;
}
function renderConnection(connection) { const svg = $('.connections-layer'), from = getNode(connection.fromId), to = getNode(connection.toId); if (!from || !to || !svg) return; const line = document.createElementNS('http://www.w3.org/2000/svg', 'line'), start = pointRight(from), end = pointLeft(to); line.setAttribute('x1', start.x); line.setAttribute('y1', start.y); line.setAttribute('x2', end.x); line.setAttribute('y2', end.y); line.dataset.connectionId = connection.id; line.style.pointerEvents = 'stroke'; line.addEventListener('click', event => { event.stopPropagation(); removeConnection(connection.id); }); svg.appendChild(line); }
function startConnection(sourceId) { connectionState = { sourceId }; const line = document.createElementNS('http://www.w3.org/2000/svg', 'line'); line.classList.add('temp-line'); $('.connections-layer').appendChild(line); connectionState.line = line; }
function finishConnection(targetId) { const from = getNode(connectionState?.sourceId), to = getNode(targetId); if (!validConnection(from, to)) { toast('该连接不符合层级关系或截图串联规则', 'error'); cancelConnection(); return; } if (connectionExists(from.id, to.id)) { toast('连接已存在', 'error'); cancelConnection(); return; } pushUndoState(); connections.push({ id: uid('connection'), fromId: from.id, toId: to.id }); cancelConnection(); saveWorkspace(); renderCanvas(); }
function cancelConnection() { connectionState?.line?.remove(); connectionState = null; $$('.target-dot.highlight').forEach(dot => dot.classList.remove('highlight')); } function removeConnection(id) { pushUndoState(); connections = connections.filter(connection => connection.id !== id); saveWorkspace(); renderCanvas(); toast('连线已删除'); } function deleteNode(id) { pushUndoState(); connections = connections.filter(connection => connection.fromId !== id && connection.toId !== id); nodes = nodes.filter(node => node.id !== id); saveWorkspace(); renderCanvas(); toast('已删除组件'); }
function updateConnectionLines() { $$('.connections-layer line:not(.temp-line)').forEach(line => { const connection = getConnection(line.dataset.connectionId), from = connection && getNode(connection.fromId), to = connection && getNode(connection.toId); if (!from || !to) return; const start = pointRight(from), end = pointLeft(to); line.setAttribute('x1', start.x); line.setAttribute('y1', start.y); line.setAttribute('x2', end.x); line.setAttribute('y2', end.y); }); }
function canvasPoint(event) { const canvas = $('#canvas'), rect = canvas.getBoundingClientRect(); return { x: (event.clientX - rect.left + canvas.scrollLeft) / canvasZoom, y: (event.clientY - rect.top + canvas.scrollTop) / canvasZoom }; }
function startElementDrag(node, event) { const point = canvasPoint(event); pushUndoState(); dragState = { node, offsetX: point.x - node.x, offsetY: point.y - node.y }; $(`.manual-node[data-id="${node.id}"]`)?.classList.add('dragging'); $('#dragDeleteZone')?.classList.add('visible'); }
function renderDropDeleteZone() { let zone = $('#dragDeleteZone'); if (!zone) { zone = document.createElement('div'); zone.id = 'dragDeleteZone'; zone.className = 'drag-delete-zone'; zone.textContent = '拖到这里删除'; $('#canvas').appendChild(zone); } }
function editNodeTitle(node, element) { const title = $('.manual-node-title', element), input = document.createElement('input'); pushUndoState(); input.className = 'title-editor-input'; input.value = node.name; title.replaceChildren(input); input.focus(); input.select(); input.addEventListener('blur', () => { node.name = input.value.trim() || node.name; saveWorkspace(); renderCanvas(); }, { once: true }); input.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === 'Escape') input.blur(); }); }
function editGeneratedText(node) {
  const isScreenshot = node.type === 'screenshot', target = isScreenshot && !generated.screenshots?.[node.id] ? screenshotChainHead(node) : node;
  const data = isScreenshot ? generatedScreenshot(node) : generated.nodes?.[node.id] || {};
  $('#modal').innerHTML = `<h2>编辑组件文本</h2><p>${escapeHtml(target.name || node.name)}</p>${isScreenshot ? `<label class="field"><span>功能与操作说明</span><textarea id="editOperation" rows="8">${escapeHtml(data.operation || '')}</textarea></label>` : `<label class="field"><span>组件介绍</span><textarea id="editSummary" rows="8">${escapeHtml(data.contentSummary || '')}</textarea></label>`}<div class="modal-actions"><button class="btn ghost" data-close>取消</button><button class="btn primary" id="saveGeneratedText">保存</button></div>`;
  $('#modalBackdrop').classList.add('open');
  $('#saveGeneratedText').addEventListener('click', () => {
    const next = { ...data };
    if (isScreenshot) {
      next.operation = screenshotOperation($('#editOperation').value);
      delete next.contentSummary;
      generated.screenshots ||= {}; generated.screenshots[target.id] = next;
    } else {
      next.contentSummary = $('#editSummary').value.trim();
      delete next.operation;
      generated.nodes ||= {}; generated.nodes[node.id] = next;
    }
    saveWorkspace(); closeModal(); renderCanvas();
  });
  bindClose();
}
function bindClose() { $$('#modal [data-close]').forEach(button => button.addEventListener('click', closeModal)); } function closeModal() { $('#modalBackdrop').classList.remove('open'); $('#modal').className='modal'; $('#modal').innerHTML = ''; } $('#modalBackdrop').addEventListener('click', event => { if (event.target === $('#modalBackdrop')) closeModal(); });
function openImagePreview(image, name='截图') { $('#modal').innerHTML = `<button class="image-preview-close" data-close>×</button><img class="image-preview" src="${escapeHtml(image)}" alt="${escapeHtml(name)}" />`; $('#modalBackdrop').classList.add('open'); $('#modal').classList.add('image-preview-modal'); bindClose(); }
function openScreenshotDetail(node) {
  const head = screenshotChainHead(node), chain = screenshotChain(head), data = generatedScreenshot(node);
  const gallery = chain.map((item, index) => `<button class="screenshot-detail-thumb${item.id === node.id ? ' active' : ''}" data-image="${escapeHtml(item.image || '')}" data-label="截图 ${index + 1}"><img src="${escapeHtml(item.image || '')}" alt="截图 ${index + 1}" /><span>${index + 1}</span></button>`).join('');
  $('#modal').innerHTML = `<div class="screenshot-detail-head"><div><span class="modal-eyebrow">截图链 · ${chain.length} 张</span><h2>${escapeHtml(head.name || '截图')}</h2></div><button class="image-preview-close" data-close aria-label="关闭">×</button></div><div class="screenshot-detail-layout"><div class="screenshot-detail-visual"><img id="screenshotDetailImage" class="screenshot-detail-image" src="${escapeHtml(node.image || head.image || '')}" alt="${escapeHtml(node.name || head.name || '截图')}" /><div class="screenshot-detail-gallery">${gallery}</div></div><div class="screenshot-detail-copy"><section><span>操作说明</span><p>${escapeHtml(data.operation || '暂无生成内容')}</p></section></div></div>`;
  $('#modalBackdrop').classList.add('open'); $('#modal').classList.add('screenshot-detail-modal');
  $$('.screenshot-detail-thumb', $('#modal')).forEach(button => button.addEventListener('click', () => { $('#screenshotDetailImage').src = button.dataset.image; $$('.screenshot-detail-thumb', $('#modal')).forEach(item => item.classList.toggle('active', item === button)); }));
  bindClose();
}
function updateSelectionActions() { const selectedGenerated = nodes.filter(node => node.selected && (generated.nodes?.[node.id] || generated.screenshots?.[node.id])); const regen = $('#regenerateBtn'); if (regen) regen.hidden = selectedGenerated.length !== 1; }
function openRegenerateModal(node) { $('#modal').innerHTML = `<h2>重新生成组件内容</h2><p>${escapeHtml(node.name)}：请输入本次修改方向。</p><textarea id="regenerateDirection" rows="5" placeholder="例如：突出用户操作步骤和结果反馈"></textarea><div class="modal-actions"><button class="btn ghost" data-close>取消</button><button class="btn primary" id="confirmRegenerate">重新生成</button></div>`; $('#modalBackdrop').classList.add('open'); $('#confirmRegenerate').addEventListener('click', () => { const direction = $('#regenerateDirection').value.trim(); if (!direction) { toast('请输入修改方向', 'error'); return; } closeModal(); regenerateNode(node, direction); }); bindClose(); }
async function regenerateNode(node, direction) { const result = configuredAi() ? await api('/manual/generate-component', { method: 'POST', body: JSON.stringify({ profile, node: generationNode(node), children: componentChildren(node), direction, settings: { endpoint: aiConfig.endpoint, mode: aiConfig.mode, model: aiConfig.model, api_key: aiConfig.apiKey } }) }) : { ...localGenerateComponent(node), operation: `${localGenerateComponent(node).operation} 修改方向：${direction}` }; const next = normalizeGeneratedResult(node, result); if (node.type === 'screenshot') { generated.screenshots ||= {}; generated.screenshots[node.id] = next; } else { generated.nodes ||= {}; generated.nodes[node.id] = next; } saveWorkspace(); renderCanvas(); toast('组件内容已重新生成'); }
document.addEventListener('mousemove', event => { if (panState) { const canvas = $('#canvas'); canvas.scrollLeft = panState.scrollLeft - (event.clientX - panState.clientX); canvas.scrollTop = panState.scrollTop - (event.clientY - panState.clientY); return; } if (connectionState) { const from = getNode(connectionState.sourceId), point = pointRight(from), cursor = canvasPoint(event); connectionState.line.setAttribute('x1', point.x); connectionState.line.setAttribute('y1', point.y); connectionState.line.setAttribute('x2', cursor.x); connectionState.line.setAttribute('y2', cursor.y); } if (dragState) { const point = canvasPoint(event), dx = point.x - dragState.offsetX, dy = point.y - dragState.offsetY; dragState.node.x = Math.max(0, dx); dragState.node.y = Math.max(0, dy); const element = $(`.manual-node[data-id="${dragState.node.id}"]`); if (element) { element.style.left = `${dragState.node.x}px`; element.style.top = `${dragState.node.y}px`; } resizeCanvasToNodes(); updateConnectionLines(); const zone = $('#dragDeleteZone'); zone?.classList.toggle('hover', event.clientY > window.innerHeight - 130); } });
$('#canvas').addEventListener('wheel', event => { event.preventDefault(); const canvas = $('#canvas'), rect = canvas.getBoundingClientRect(), before = { x: (event.clientX - rect.left + canvas.scrollLeft) / canvasZoom, y: (event.clientY - rect.top + canvas.scrollTop) / canvasZoom }, next = Math.min(2.5, Math.max(.5, canvasZoom * (event.deltaY < 0 ? 1.1 : .9))); if (next === canvasZoom) return; canvasZoom = next; renderCanvas(); canvas.scrollLeft = Math.max(0, before.x * canvasZoom - (event.clientX - rect.left)); canvas.scrollTop = Math.max(0, before.y * canvasZoom - (event.clientY - rect.top)); }, { passive: false });
$('#canvas').addEventListener('mousedown', event => { if (event.button !== 0 || event.target.closest('.manual-node,.canvas-toolbar,.drag-delete-zone')) return; const canvas = $('#canvas'); panState = { clientX: event.clientX, clientY: event.clientY, scrollLeft: canvas.scrollLeft, scrollTop: canvas.scrollTop }; canvas.classList.add('panning'); });
document.addEventListener('mouseup', event => { if (connectionState) { const target = event.target.closest?.('.target-dot'); if (!target) cancelConnection(); } if (dragState) { const zone = $('#dragDeleteZone'); if (zone?.classList.contains('hover')) deleteNode(dragState.node.id); else { $('.manual-node.dragging')?.classList.remove('dragging'); saveWorkspace(); } dragState = null; zone?.classList.remove('visible', 'hover'); } if (panState) { panState = null; $('#canvas')?.classList.remove('panning'); } });

function updateGenerationStatus() {
  updateManualStatus();
  const current = generationState.running ? generationState.queue[generationState.index] : null;
  if (current && $('#generationText')) $('#generationText').textContent = `${generationState.paused ? '已暂停' : '正在生成'}（${generationState.index}/${generationState.queue.length}）：${current.name}`;
  $$('.manual-node.generating').forEach(element => element.classList.remove('generating'));
  if (current) $(`.manual-node[data-id="${current.id}"]`)?.classList.add('generating');
}
setInterval(updateGenerationStatus, 100);

$$('[data-add]').forEach(button => { button.draggable = true; button.addEventListener('click', () => addNode(button.dataset.add)); button.addEventListener('dragstart', event => { event.dataTransfer.effectAllowed = 'copy'; event.dataTransfer.setData('application/x-manual-component', button.dataset.add); button.classList.add('dragging-tool'); }); button.addEventListener('dragend', () => button.classList.remove('dragging-tool')); }); $('#selectAllBtn').addEventListener('click', () => { const select = nodes.some(node => !node.selected); nodes.forEach(node => node.selected = select); renderCanvas(); }); $('#resetCanvasBtn').addEventListener('click', undoLastOperation);
function isImageFile(file) { return file && (file.type.startsWith('image/') || /\.(png|jpe?g|gif|webp|bmp)$/i.test(file.name || '')); }
async function addImageFiles(files, origin, source = '拖入') {
  const images = [...files].filter(isImageFile);
  if (!images.length) return false;
  const canvas = $('#canvas');
  const start = origin || {
    x: Math.max(20, (canvas.scrollLeft + canvas.clientWidth / 2) / canvasZoom - 130),
    y: Math.max(20, (canvas.scrollTop + canvas.clientHeight / 2) / canvasZoom - 122)
  };
  let loaded;
  try {
    loaded = await Promise.all(images.map(async file => ({ file, image: await fileToDataUrl(file) })));
  } catch (error) {
    toast(error.message || '图片读取失败', 'error');
    return false;
  }
  pushUndoState();
  const existingCount = nodes.filter(node => node.type === 'screenshot').length;
  for (const [index, item] of loaded.entries()) {
    const { file, image } = item;
    const size = nodeSize({ type: 'screenshot' });
    const baseName = (file.name || '').replace(/\.[^.]+$/, '').trim();
    nodes.push({
      id: uid('node'), type: 'screenshot',
      name: baseName || `${source}图片 ${existingCount + index + 1}`,
      x: start.x + (index % 3) * (size.width + 24),
      y: start.y + Math.floor(index / 3) * (size.height + 24),
      width: size.width, height: size.height, selected: false, layoutVersion: 2,
      image, fileName: file.name || `${source}图片.png`
    });
  }
  saveWorkspace();
  renderCanvas();
  toast(`已${source} ${images.length} 张图片`);
  return true;
}
$('#canvas').addEventListener('dragover', event => { if (event.dataTransfer.types.includes('application/x-manual-component') || [...event.dataTransfer.items].some(item => item.kind === 'file' && item.type.startsWith('image/'))) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; $('#canvas').classList.add('drop-ready'); } });
$('#canvas').addEventListener('dragleave', event => { if (!event.relatedTarget || !$('#canvas').contains(event.relatedTarget)) $('#canvas').classList.remove('drop-ready'); });
$('#canvas').addEventListener('drop', async event => { event.preventDefault(); const type = event.dataTransfer.getData('application/x-manual-component'); $('#canvas').classList.remove('drop-ready'); const point = canvasPoint(event); if (!type) { await addImageFiles(event.dataTransfer.files, { x: Math.max(20, point.x - 130), y: Math.max(20, point.y - 122) }, '拖入'); return; } const size = nodeSize({ type }); pendingDropPosition = { x: Math.max(20, point.x - size.width / 2), y: Math.max(20, point.y - size.height / 2) }; if (type === 'screenshot') openScreenshotModal(); else addNode(type, pendingDropPosition); pendingDropPosition = null; });
document.addEventListener('paste', async event => {
  if (!$('#view-manual').classList.contains('active') || event.target.closest('input,textarea,[contenteditable="true"]')) return;
  const images = [...(event.clipboardData?.items || [])].filter(item => item.kind === 'file' && item.type.startsWith('image/')).map(item => item.getAsFile()).filter(Boolean);
  if (!images.length) return;
  event.preventDefault();
  await addImageFiles(images, null, '粘贴');
});
function openScreenshotModal() { const dropPosition = pendingDropPosition; $('#modal').innerHTML = `<h2>添加产品截图</h2><p>上传截图后，通过右侧源点连接到页面、模块或系统。</p><div class="field"><span>截图名称</span><input id="shotName" placeholder="如：管理人员看板" /></div><div class="file-drop"><label for="shotFile">▣ 选择图片文件<input id="shotFile" type="file" accept="image/*" multiple /></label><small id="shotFileName">支持 PNG、JPG，浏览器本地预览</small></div><div class="modal-actions"><button class="btn ghost" data-close>取消</button><button class="btn primary" id="confirmShot">添加截图</button></div>`; $('#modalBackdrop').classList.add('open'); $('#shotFile').addEventListener('change', () => { $('#shotFileName').textContent = `${$('#shotFile').files.length} 个文件已选择`; }); $('#confirmShot').addEventListener('click', async () => { const files = [...$('#shotFile').files]; if (!files.length) { toast('请选择截图文件', 'error'); return; } for (const [index, file] of files.entries()) addNode('screenshot', { ...(files.length === 1 && dropPosition ? dropPosition : {}), name: files.length === 1 ? ($('#shotName').value.trim() || file.name.replace(/\.[^.]+$/, '')) : `${$('#shotName').value.trim() || '截图'} ${index + 1}`, image: await fileToDataUrl(file), fileName: file.name }); closeModal(); toast(`已添加 ${files.length} 个截图`); }); bindClose(); }
function fileToDataUrl(file) { return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error(`无法读取图片：${file.name || '剪贴板图片'}`)); reader.readAsDataURL(file); }); } $('#addScreenshotBtn').draggable = true; $('#addScreenshotBtn').addEventListener('dragstart', event => { event.dataTransfer.effectAllowed = 'copy'; event.dataTransfer.setData('application/x-manual-component', 'screenshot'); event.currentTarget.classList.add('dragging-tool'); }); $('#addScreenshotBtn').addEventListener('dragend', event => event.currentTarget.classList.remove('dragging-tool')); $('#addScreenshotBtn').addEventListener('click', openScreenshotModal);

function makeComponentQueue() {
  const queue = [], visited = new Set();
  const sort = list => [...list].sort((a, b) => (Number(a.y) || 0) - (Number(b.y) || 0) || (Number(a.x) || 0) - (Number(b.x) || 0));
  const visit = node => {
    if (visited.has(node.id)) return;
    visited.add(node.id);
    sort(directTargets(node.id)).forEach(visit);
    queue.push(node);
  };
  sort(nodes).forEach(visit);
  return queue;
}
function componentChildren(node) { return directTargets(node.id).map(child => ({ name: child.name, generated: { contentSummary: (child.type === 'screenshot' ? generated.screenshots : generated.nodes)?.[child.id]?.contentSummary || '' } })); }
function manualTreePayload() { const byId = new Map(nodes.map(node => [node.id, node])); const children = new Map(nodes.map(node => [node.id, []])); connections.forEach(link => { const list = children.get(link.fromId); if (list && byId.has(link.toId)) list.push(byId.get(link.toId)); }); const sort = list => list.sort((a, b) => (Number(a.y) || 0) - (Number(b.y) || 0) || (Number(a.x) || 0) - (Number(b.x) || 0)); const visit = node => ({ id: node.id, type: node.type, name: node.name, title: node.title || '', x: node.x, y: node.y, children: sort(children.get(node.id) || []).map(visit) }); return sort(nodes.filter(node => !connections.some(link => link.toId === node.id))).map(visit); }
function localGenerateComponent(node) { const typeLabel = ({ system: '系统', module: '模块', page: '页面', screenshot: '截图' })[node.type] || '组件'; if (node.type === 'screenshot') return { id: node.id, title: /^截图\s*\d+$/u.test(node.name || '') ? '功能操作界面' : node.name, contentSummary: '操作界面展示相关业务信息。', operation: '查看界面信息，按照页面提示完成操作并检查结果。' }; const children = directTargets(node.id); const childNames = children.map(child => child.name).filter(Boolean); const summary = `${node.name}是${typeLabel}功能单元${childNames.length ? `，包含${childNames.join('、')}` : ''}。`; return { id: node.id, title: node.name, contentSummary: summary }; }
function normalizeGeneratedResult(node, result) { if (!result) return result; const clean = value => String(value || '').replace(/^(该组件|此组件|该页面|此页面)[，,:：\s]*/u, '').trim(); const contentSummary = clean(result.contentSummary), operation = clean(result.operation); const title = clean(result.title) || (/截图\s*\d+/u.test(node.name || '') ? '功能操作界面' : node.name); if (node.type === 'screenshot') return { ...result, title, contentSummary, operation: screenshotOperation(operation) }; const next = { ...result, title, contentSummary: contentSummary.startsWith(node.name) ? contentSummary : `${node.name}${contentSummary ? `：${contentSummary}` : ''}` }; delete next.operation; return next; }
function ensurePauseButton() { const button = $('#pauseGenerationBtn'); if (button) { button.hidden = !generationState.running; button.textContent = generationState.paused ? '继续生成' : '暂停生成'; } } function pauseForEditing() { if (generationState.running) { generationState.paused = true; ensurePauseButton(); } }
async function downloadGeneratedManual() { if (!activeCopyrightId || !/^[0-9]+$/.test(String(activeCopyrightId))) { toast('请先保存软著项目', 'error'); return; } const response = await fetch(`${backendOrigin}/api/copyrights/${activeCopyrightId}/export`); if (!response.ok) throw new Error(`文档导出失败（${response.status}）`); const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `${profile.name || '软著操作手册'}.docx`; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000); }
async function generateNext() {
  if (generationState.running) return;
  if (!nodes.length) { toast('请先拖入至少一个组件', 'error'); return; }
  const fallback = !configuredAi(), projectId = activeCopyrightId;
  const run = { running: true, paused: false, queue: makeComponentQueue(), index: 0 };
  generationState = run;
  const active = () => generationState === run && activeCopyrightId === projectId;
  generated = { nodes: {}, screenshots: {}, status: 'generating', restructured: false };
  $('#generateManualBtn').disabled = true;
  ensurePauseButton(); saveWorkspace(); renderCanvas(); updateGenerationStatus();
  try {
    while (run.index < run.queue.length) {
      while (run.paused && active()) await new Promise(resolve => setTimeout(resolve, 100));
      if (!active()) return;
      const node = run.queue[run.index];
      if (!getNode(node.id)) { run.index += 1; continue; }
      updateGenerationStatus();
      const result = fallback ? localGenerateComponent(node) : await api('/manual/generate-component', {
        method: 'POST', body: JSON.stringify({ profile, node, children: componentChildren(node), settings: { endpoint: aiConfig.endpoint, mode: aiConfig.mode, model: aiConfig.model, api_key: aiConfig.apiKey } })
      });
      if (!active()) return;
      if (result?.error) throw new Error(result.detail || result.message || 'AI 服务调用失败');
      if (!result?.contentSummary || (node.type === 'screenshot' && !result?.operation)) throw new Error(`${node.name}未返回完整内容`);
      if (getNode(node.id)) generated[node.type === 'screenshot' ? 'screenshots' : 'nodes'][node.id] = normalizeGeneratedResult(node, result);
      run.index += 1;
      saveWorkspace(); renderCanvas(); updateGenerationStatus();
      await new Promise(resolve => requestAnimationFrame(resolve));
    }
    generated.status = 'generated';
    saveWorkspace(); toast('完整生成已完成，请继续全量重构');
  } catch (error) {
    if (!active()) return;
    generated.status = 'partial';
    saveWorkspace(); toast(`${error.message || '完整生成失败'}；已保留 ${run.index}/${run.queue.length} 个组件的结果`, 'error');
  } finally {
    if (active()) {
      run.running = false; run.paused = false;
      $('#generateManualBtn').disabled = false;
      ensurePauseButton(); renderCanvas(); updateGenerationStatus();
    }
  }
}
function restructureProgressValue(elapsedMs) {
  const minute = elapsedMs / 60000;
  if (minute <= 1) return 60 * minute;
  if (minute <= 2) return 60 + 30 * (minute - 1);
  if (minute <= 3) return 90 + 6 * (minute - 2);
  return 100 - 4 / Math.pow(2, minute - 3);
}
function updateRestructureProgress(value = restructureProgressValue(Date.now() - restructureProgressStartedAt)) {
  const percent = value >= 100 ? 100 : Math.min(99, Math.max(0, value));
  const fill = $('#restructureProgressFill'), text = $('#restructureProgressText'), detail = $('#restructureProgressDetail');
  if (fill) fill.style.width = `${percent}%`;
  if (text) text.textContent = `${Math.floor(percent)}%`;
  if (detail) detail.textContent = `已用时 ${Math.floor((Date.now() - restructureProgressStartedAt) / 60000)} 分钟`;
}
function startRestructureProgress() {
  const wrap = $('#restructureProgressWrap');
  if (wrap) wrap.hidden = false;
  restructureProgressStartedAt = Date.now();
  updateRestructureProgress(0);
  clearInterval(restructureProgressTimer);
  restructureProgressTimer = setInterval(() => updateRestructureProgress(), 1000);
}
function finishRestructureProgress(success) {
  clearInterval(restructureProgressTimer);
  restructureProgressTimer = null;
  if (success) {
    updateRestructureProgress(100);
    const detail = $('#restructureProgressDetail');
    if (detail) detail.textContent = '全量重构已完成';
  } else {
    const wrap = $('#restructureProgressWrap');
    if (wrap) wrap.hidden = true;
  }
}
async function restructureManual() {
  const generatedCount = Object.keys(generated.nodes || {}).length + Object.keys(generated.screenshots || {}).length;
  if (!nodes.length || generatedCount < nodes.length || ['generating', 'partial'].includes(generated.status)) {
    toast('请先完成完整生成', 'error');
    return;
  }
  const button = $('#restructureManualBtn');
  button.disabled = true;
  startRestructureProgress();
  try {
    const result = await api('/manual/generate-restructured', {
      method: 'POST',
      body: JSON.stringify({ profile, nodes, tree: manualTreePayload(), generated, settings: { endpoint: aiConfig.endpoint, mode: aiConfig.mode, model: aiConfig.model, api_key: aiConfig.apiKey } })
    });
    if (!result || result.error) throw new Error(result?.detail || result?.message || '全量重构失败');
    if (!result.nodes || !result.screenshots) throw new Error('全量重构未返回完整手册结构');
    generated.nodes = result.nodes;
    generated.screenshots = result.screenshots;
    generated.status = 'restructured';
    generated.restructured = true;
    saveWorkspace();
    renderCanvas();
    updateManualStatus();
    finishRestructureProgress(true);
    $('#exportManualBtn')?.classList.add('success');
    toast('全量重构已完成，可以完整导出');
  } catch (error) {
    finishRestructureProgress(false);
    toast(error.message || '全量重构失败', 'error');
    button.disabled = false;
  }
}
async function exportManualPackage() { if (!generated.restructured) { toast('请先完成全量重构', 'error'); return; } if (!activeCopyrightId || !/^[0-9]+$/.test(String(activeCopyrightId))) { toast('请先保存软著项目', 'error'); return; } const response = await fetch(`${backendOrigin}/api/copyrights/${activeCopyrightId}/export`); if (!response.ok) throw new Error(`文档导出失败（${response.status}）`); const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = '软著材料.zip'; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000); toast('已导出基础信息.txt和操作手册.docx'); }
$('#generateManualBtn').addEventListener('click', generateNext); $('#restructureManualBtn')?.addEventListener('click', restructureManual); $('#exportManualBtn')?.addEventListener('click', () => exportManualPackage().catch(error => toast(error.message || '导出失败', 'error'))); $('#pauseGenerationBtn').addEventListener('click', () => { generationState.paused = !generationState.paused; ensurePauseButton(); updateGenerationStatus(); });
function updateManualStatus() {
  const hasGenerated = !generationState.running && !['generating', 'partial'].includes(generated.status) && Boolean(generated.status === 'generated' || generated.restructured || Object.keys(generated.nodes || {}).length || Object.keys(generated.screenshots || {}).length);
  if ($('#generateManualBtn')) $('#generateManualBtn').disabled = generationState.running;
  if ($('#restructureManualBtn')) $('#restructureManualBtn').disabled = !hasGenerated;
  if ($('#exportManualBtn')) { $('#exportManualBtn').disabled = generationState.running || !generated.restructured; $('#exportManualBtn').classList.toggle('success', Boolean(generated.restructured)); }
  if ($('#generationText') && !generationState.running) $('#generationText').textContent = generated.restructured ? '已完成全量重构' : generated.status === 'generated' ? '已完成完整生成' : ['generating', 'partial'].includes(generated.status) ? `生成未完成，已保留 ${Object.keys(generated.nodes || {}).length + Object.keys(generated.screenshots || {}).length}/${nodes.length} 个组件` : nodes.length ? '等待开始完整生成' : '等待添加组件';
}
$('#regenerateBtn').addEventListener('click', () => { const node = nodes.find(item => item.selected && (generated.nodes?.[item.id] || generated.screenshots?.[item.id])); if (node) openRegenerateModal(node); });

function renderLibrary() { const query = ($('#librarySearch')?.value || '').toLowerCase(), rows = copyrights.filter(item => `${item.name}${item.owner}`.toLowerCase().includes(query)); $('#totalCopyrights').textContent = copyrights.length; $('#doneCopyrights').textContent = copyrights.filter(item => item.status === '已完成').length; $('#assetCopyrights').textContent = copyrights.filter(item => item.assetPath).length; $('#libraryBadge').textContent = copyrights.length; $('#libraryBody').innerHTML = rows.map(item => `<tr><td><div class="project-cell"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.shortName || '未设置简称')}</small></div></td><td>${escapeHtml(item.version || '-')}</td><td>${escapeHtml(item.owner || '-')}</td><td>${escapeHtml(item.completionDate || '-')}</td><td><span class="status-tag ${(item.status || '草稿') === '已完成' ? 'done' : (item.status || '草稿') === '生成中' ? 'generating' : 'draft'}">${escapeHtml(item.status || '草稿')}</span></td><td>${item.assetPath ? '<a class="asset-link" href="/api/copyrights/' + encodeURIComponent(item.id) + '/materials/download" download>⇩ 已上传</a>' : '<span style="color:#b0b0a8">未上传</span>'}</td><td><div class="row-actions"><button data-edit-copyright="${item.id}">编辑</button><button data-upload-copyright="${item.id}">材料</button><button data-open-copyright="${item.id}">打开</button><button data-delete-copyright="${item.id}">删除</button></div></td></tr>`).join(''); $('#libraryEmpty').classList.toggle('visible', !rows.length); $$('[data-edit-copyright]').forEach(button => button.addEventListener('click', () => openCopyrightModal(copyrights.find(item => String(item.id) === button.dataset.editCopyright)))); $$('[data-upload-copyright]').forEach(button => button.addEventListener('click', () => uploadMaterials(copyrights.find(item => String(item.id) === button.dataset.uploadCopyright)))); $$('[data-open-copyright]').forEach(button => button.addEventListener('click', () => loadWorkspace(button.dataset.openCopyright).then(() => switchView('foundation')))); $$('[data-delete-copyright]').forEach(button => button.addEventListener('click', () => deleteCopyright(button.dataset.deleteCopyright))); }
$('#librarySearch').addEventListener('input', renderLibrary);
async function openCopyrightModal(item = null) { const value = item || { name: '', shortName: '', version: '', owner: '', industry: '', completionDate: '', status: '草稿', assetPath: '' }; $('#modal').innerHTML = `<h2>${item ? '编辑软著项目' : '新建软著项目'}</h2><p>维护软著库中的常用字段，基础信息和操作手册会按项目保存。</p><div class="modal-grid"><label class="field"><span>软件全称</span><input id="copyrightName" value="${escapeHtml(value.name)}" /></label><label class="field"><span>软件简称</span><input id="copyrightShort" value="${escapeHtml(value.shortName)}" /></label><label class="field"><span>版本号</span><input id="copyrightVersion" value="${escapeHtml(value.version)}" /></label><label class="field"><span>著作权人</span><input id="copyrightOwner" value="${escapeHtml(value.owner)}" /></label><label class="field"><span>行业领域</span><input id="copyrightIndustry" value="${escapeHtml(value.industry)}" /></label><label class="field"><span>完成日期</span><input id="copyrightDate" type="date" value="${escapeHtml(value.completionDate)}" /></label><label class="field"><span>状态</span><select id="copyrightStatus"><option ${value.status === '草稿' ? 'selected' : ''}>草稿</option><option ${value.status === '生成中' ? 'selected' : ''}>生成中</option><option ${value.status === '已完成' ? 'selected' : ''}>已完成</option></select></label></div><div class="modal-actions"><button class="btn ghost" data-close>取消</button><button class="btn primary" id="saveCopyright">保存项目</button></div>`; $('#modalBackdrop').classList.add('open'); $('#saveCopyright').addEventListener('click', async () => { const isNew = !item, next = { id: item?.id || uid('copyright'), name: $('#copyrightName').value.trim(), shortName: $('#copyrightShort').value.trim(), version: $('#copyrightVersion').value.trim(), owner: $('#copyrightOwner').value.trim(), industry: $('#copyrightIndustry').value.trim(), completionDate: $('#copyrightDate').value, status: $('#copyrightStatus').value, assetPath: item?.assetPath || '' }; if (!next.name) { toast('软件全称不能为空', 'error'); return; } try { const server = await api(item ? `/copyrights/${item.id}` : '/copyrights', { method: item ? 'PUT' : 'POST', body: JSON.stringify(next) }); if (server?.id) next.id = server.id; } catch {} if (item) Object.assign(item, next); else copyrights.unshift(next); activeCopyrightId = next.id; closeModal(); renderLibrary(); refreshFoundationProjects(); if (isNew && /^[0-9]+$/.test(String(next.id))) { await loadWorkspace(next.id); saveWorkspace(); switchView('foundation'); } else { saveWorkspace(); toast('软著项目已保存'); } }); bindClose(); }
$('#addCopyrightBtn').addEventListener('click', () => openCopyrightModal()); $('#emptyAddBtn').addEventListener('click', () => openCopyrightModal()); async function deleteCopyright(id) { if (!confirm('确定删除这个软著项目吗？')) return; try { await api(`/copyrights/${id}`, { method: 'DELETE' }); } catch {} copyrights = copyrights.filter(item => String(item.id) !== String(id)); if (String(activeCopyrightId) === String(id)) activeCopyrightId = ''; saveWorkspace(); renderLibrary(); toast('项目已删除'); }
function uploadMaterials(item) { $('#modal').innerHTML = `<h2>上传完整材料</h2><p>选择完整材料文件夹后，系统会保存到当前软著资产目录。</p><div class="file-drop"><label for="materialFiles">▤ 选择材料文件夹<input id="materialFiles" type="file" webkitdirectory directory multiple /></label><small id="materialNames">可包含申请表、源程序、操作手册等全部材料</small></div><div class="modal-actions"><button class="btn ghost" data-close>取消</button><button class="btn primary" id="confirmMaterials">上传材料</button></div>`; $('#modalBackdrop').classList.add('open'); $('#materialFiles').addEventListener('change', () => { $('#materialNames').textContent = `${$('#materialFiles').files.length} 个文件已选择`; }); $('#confirmMaterials').addEventListener('click', async () => { const files = [...$('#materialFiles').files]; if (!files.length) { toast('请选择材料文件夹', 'error'); return; } try { const form = new FormData(); files.forEach(file => form.append('files', file, file.webkitRelativePath || file.name)); const response = await fetch(`${backendOrigin}/api/copyrights/${item.id}/materials`, { method: 'POST', body: form }); if (!response.ok) throw new Error('材料上传失败'); item.assetPath = (await response.json()).assetPath; } catch (error) { item.assetPath = files[0].webkitRelativePath?.split('/')[0] || files[0].name; toast(error.message, 'error'); } activeCopyrightId = item.id; saveWorkspace(); closeModal(); renderLibrary(); refreshManualProjects(); toast(`已记录 ${files.length} 个材料文件`); }); bindClose(); }
$('#exportLibraryBtn').addEventListener('click', () => { const blob = new Blob([JSON.stringify(copyrights, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = '软著库项目.json'; link.click(); URL.revokeObjectURL(link.href); toast('软著库列表已导出'); });

function renderSettings() { $('#aiEndpoint').value = aiConfig.endpoint; $('#aiMode').value = aiConfig.mode; $('#aiModel').value = aiConfig.model; $('#aiKey').value = aiConfig.apiKey; } function handleAiConfigChange() { aiConfig = { ...aiConfig, endpoint: $('#aiEndpoint').value, mode: $('#aiMode').value, model: $('#aiModel').value, apiKey: $('#aiKey').value }; saveAiConfig(); saveWorkspace(); } ['aiEndpoint', 'aiMode', 'aiModel', 'aiKey'].forEach(id => { $(`#${id}`).addEventListener('input', handleAiConfigChange); $(`#${id}`).addEventListener('change', handleAiConfigChange); }); $('#toggleKey').addEventListener('click', () => { $('#aiKey').type = $('#aiKey').type === 'password' ? 'text' : 'password'; });
$('#testConnectionBtn').addEventListener('click', async () => { const button = $('#testConnectionBtn'); button.disabled = true; button.textContent = '测试中…'; try { if (!configuredAi()) throw new Error('请先填写 API 地址和模型名称'); const result = await api('/ai/test', { method: 'POST', body: JSON.stringify({ settings: { endpoint: aiConfig.endpoint, mode: aiConfig.mode, model: aiConfig.model, api_key: aiConfig.apiKey } }) }); if (result?.error) throw new Error(result.detail || result.message || 'AI 服务调用失败'); $('#connectionDot').parentElement.classList.add('connected'); $('#connectionText').textContent = '服务配置可用'; $('#apiCardText').textContent = '已检测到服务配置'; toast('模型接口连接成功'); } catch (error) { $('#connectionText').textContent = '连接失败'; $('#apiCardText').textContent = error.message; toast(error.message, 'error'); } finally { button.disabled = false; button.textContent = '测试连接'; } });
async function loadWorkspace(id) {
  let workspace;
  try {
    workspace = await api(`/copyrights/${id}/workspace`);
  } catch (error) {
    console.error('加载软著工作区接口失败', error);
    toast(`无法载入软著工作区：${error.message}`, 'error');
    return;
  }
  try {
    const project = copyrights.find(item => String(item.id) === String(id));
    profile = { ...blankProfile, name: project?.name || '', shortName: project?.shortName || '', version: project?.version || '', owner: project?.owner || '', industry: project?.industry || '', completionDate: project?.completionDate || '', ...(workspace.profile || {}) };
    if (!globalAiConfigLoaded && Object.keys(workspace.aiConfig || {}).length) aiConfig = { endpoint: '', mode: 'chat', model: '', apiKey: '', ...workspace.aiConfig };
    nodes = Array.isArray(workspace.nodes) ? workspace.nodes : [];
    connections = Array.isArray(workspace.connections) ? workspace.connections : [];
    generated = workspace.generated && typeof workspace.generated === 'object' ? workspace.generated : {};
    activeCopyrightId = id;
    undoStack = [];
    generationState = { running: false, paused: false, queue: [], index: 0 };
    ensurePauseButton();
    localPersist();
    renderProfile();
    renderSettings();
    renderCanvas();
    refreshFoundationProjects();
    refreshManualProjects();
    toast('已载入该软著工作区');
  } catch (error) {
    console.error('软著工作区已载入，但页面渲染失败', error);
    toast(`工作区数据已载入，但页面渲染失败：${error.message}`, 'error');
  }
}
async function refreshFoundationProjects() { const select = $('#foundationCopyrightSelect'); if (!select) return; let list = []; try { list = await api('/copyrights'); } catch {} list = Array.isArray(list) ? list : copyrights; select.innerHTML = list.length ? list.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name || item.shortName || '未命名软著')} ${escapeHtml(item.version || '')}</option>`).join('') : '<option value="">暂无软著项目</option>'; select.disabled = !list.length; const selected = list.find(item => String(item.id) === String(activeCopyrightId)) || list[0]; if (selected) { select.value = selected.id; } select.onchange = () => select.value && loadWorkspace(select.value); }
async function refreshManualProjects() { const select = $('#manualCopyrightSelect'); if (!select) return; let list = []; try { list = await api('/copyrights'); } catch {} list = (Array.isArray(list) ? list : copyrights).filter(item => String(item.name || '').trim()); select.innerHTML = list.length ? list.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} ${escapeHtml(item.version || '')}</option>`).join('') : '<option value="">暂无可用软著</option>'; select.disabled = !list.length; const selected = list.find(item => String(item.id) === String(activeCopyrightId)) || list[0]; if (selected) { select.value = selected.id; if (!activeCopyrightId) { activeCopyrightId = selected.id; await loadWorkspace(selected.id); return; } } select.onchange = () => loadWorkspace(select.value); }
async function hydrate() { try { const savedAiConfig = await api('/ai-config'); if (savedAiConfig && Object.keys(savedAiConfig).length) { aiConfig = { ...aiConfig, ...savedAiConfig }; globalAiConfigLoaded = true; } else if (aiConfig.endpoint || aiConfig.model || aiConfig.apiKey) saveAiConfig(); } catch {} try { const serverList = await api('/copyrights'); if (Array.isArray(serverList)) { copyrights = serverList.map(item => ({ ...item, shortName: item.shortName ?? item.short_name ?? '', completionDate: item.completionDate ?? item.completion_date ?? '', assetPath: item.assetPath ?? item.asset_path ?? '' })); localPersist(); renderLibrary(); } } catch {} if (activeCopyrightId && /^[0-9]+$/.test(String(activeCopyrightId))) await loadWorkspace(activeCopyrightId); else { renderProfile(); renderSettings(); renderCanvas(); } refreshFoundationProjects(); refreshManualProjects(); }
renderProfile(); renderSettings(); renderCanvas(); renderLibrary(); hydrate();
