const $ = (selector) => document.querySelector(selector);
const state = { library: [], results: [], format: 'bibtex', dragged: null, expanded: new Set() };
const fields = [['authors', '作者（用分号分隔）', 'wide'], ['year', '年份', ''], ['venue', '期刊/会议', 'wide'], ['volume', '卷', ''], ['issue', '期', ''], ['pages', '页码', ''], ['doi', 'DOI', 'wide'], ['url', '正式主页', 'wide']];

function message(text, type = '') { const node = $('#message'); node.textContent = text; node.className = `message ${type}`; }
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char])); }
function authors(value) { return Array.isArray(value) ? value.join('; ') : value || ''; }
function paperMeta(item) { return [authors(item.authors), item.venue, item.year, item.doi].filter(Boolean).join(' · '); }
function sourceBadges(item) { return (item.sources || []).map(source => `<span class="badge">${esc(source)}</span>`).join(''); }
function safeUrl(value) { try { const url = new URL(String(value || '')); return ['http:', 'https:'].includes(url.protocol) ? url.href : ''; } catch { return ''; } }
function paperLink(item) { const url = safeUrl(item.url); return url ? `<a class="paper-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="打开正式主页">主页 ↗</a>` : ''; }
function exactMatches(items = []) { return items.filter(item => item.confidence === 1); }

function renderResults() {
  const node = $('#results');
  if (!state.results.length) { node.innerHTML = '<div class="empty">没有找到候选结果，请尝试更完整的标题或 DOI。</div>'; return; }
  node.innerHTML = state.results.map((item, index) => `<article class="result"><h3>${esc(item.title)}</h3><p class="meta">${esc(paperMeta(item))}</p><div class="result-foot"><div class="badges">${sourceBadges(item)}<span class="confidence">匹配度 ${Math.round((item.confidence || 0) * 100)}%</span></div><button type="button" data-add="${index}">${state.library.some(saved => saved.id === item.id) ? '已在文献库' : '加入文献库'}</button></div></article>`).join('');
  node.querySelectorAll('[data-add]').forEach(button => button.addEventListener('click', () => addPaper(state.results[Number(button.dataset.add)])));
}
function renderLibrary() {
  $('#count').textContent = state.library.length;
  const node = $('#library');
  if (!state.library.length) { node.innerHTML = '<div class="empty">文献库为空。将左侧候选加入后即可编辑和格式化。</div>'; updatePreview(); return; }
  node.innerHTML = state.library.map((item, index) => { const expanded = state.expanded.has(item.id); return `<article class="library-item${expanded ? ' expanded' : ''}" draggable="true" data-index="${index}"><div class="item-top"><span class="handle" aria-hidden="true">⠿</span><input class="item-title" aria-label="论文标题" data-field="title" value="${esc(item.title)}"><div class="item-actions"><button class="icon-btn expand-btn" type="button" title="${expanded ? '收起详细信息' : '展开详细信息'}" aria-expanded="${expanded}" data-expand>${expanded ? '▾' : '▸'}</button><button class="icon-btn" title="上移" data-move="up">↑</button><button class="icon-btn" title="下移" data-move="down">↓</button><button class="icon-btn delete" title="删除" data-delete>×</button></div></div><p class="item-summary">${esc(paperMeta(item) || '暂无作者、期刊或年份信息')} ${paperLink(item)}</p><div class="fields"${expanded ? '' : ' hidden style="display:none"'}>${fields.map(([key, label, className]) => `<label class="${className}">${label}${key === 'url' ? paperLink(item) : ''}<input data-field="${key}" value="${esc(key === 'authors' ? authors(item[key]) : item[key] || '')}"></label>`).join('')}</div></article>`; }).join('');
  node.querySelectorAll('.library-item').forEach(card => {
    const index = Number(card.dataset.index);
    card.addEventListener('dragstart', () => { state.dragged = index; card.classList.add('dragging'); });
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
    card.addEventListener('dragover', event => event.preventDefault());
    card.addEventListener('drop', event => { event.preventDefault(); movePaper(state.dragged, index); });
    card.querySelectorAll('[data-field]').forEach(input => input.addEventListener('input', () => { const key = input.dataset.field; state.library[index][key] = key === 'authors' ? input.value.split(';').map(value => value.trim()).filter(Boolean) : input.value; updatePreview(); }));
    card.querySelector('[data-expand]').addEventListener('click', () => { const id = state.library[index].id; if (state.expanded.has(id)) state.expanded.delete(id); else state.expanded.add(id); renderLibrary(); });
    card.querySelector('[data-delete]').addEventListener('click', () => { state.expanded.delete(state.library[index].id); state.library.splice(index, 1); renderLibrary(); });
    card.querySelector('[data-move="up"]').addEventListener('click', () => movePaper(index, index - 1));
    card.querySelector('[data-move="down"]').addEventListener('click', () => movePaper(index, index + 1));
  });
  updatePreview();
}
function addPaper(item) { if (!state.library.some(saved => saved.id === item.id)) { const copy = structuredClone(item); state.expanded.delete(copy.id); state.library.push(copy); renderLibrary(); renderResults(); } }
function movePaper(from, to) { if (from == null || to < 0 || to >= state.library.length || from === to) return; const [item] = state.library.splice(from, 1); state.library.splice(to, 0, item); renderLibrary(); }
async function search(query) {
  message('正在并发查询 Crossref、OpenAlex、Semantic Scholar、arXiv 和 PubMed…', 'info'); $('#results').innerHTML = '<div class="empty">正在查询…</div>'; $('#source-status').textContent = '';
  try { const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '检索失败'); state.results = exactMatches(data.results); renderResults(); renderStatus(data.source_status); message(`找到 ${state.results.length} 条 100% 匹配的候选结果。`, 'info'); } catch (error) { message(error.message); $('#results').innerHTML = '<div class="empty">暂时无法获取结果，请检查网络后重试。</div>'; }
}
function renderStatus(status = {}) { $('#source-status').innerHTML = Object.entries(status).map(([name, value]) => `<span class="${value.startsWith('失败') ? 'error' : ''}">${esc(name)}：${esc(value)}</span>`).join(''); }
function batchResults(items) {
  const merged = new Map();
  items.flatMap(item => item.results || []).forEach(item => {
    const key = item.doi || item.id || item.title.toLowerCase();
    if (!merged.has(key)) merged.set(key, item);
    else merged.get(key).sources = [...new Set([...(merged.get(key).sources || []), ...(item.sources || [])])];
  });
  return exactMatches([...merged.values()]).sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
}
function renderBatchStatus(items) {
  $('#source-status').innerHTML = items.map(item => `<span class="${item.status === 'failed' ? 'error' : ''}">${esc(item.filename)}：${item.status === 'completed' ? '完成' : item.status === 'failed' ? esc(item.error || '失败') : item.status === 'processing' ? '处理中' : '等待中'}</span>`).join('');
}
async function upload(files) {
  const selected = [...(files || [])];
  if (!selected.length) { message('请选择 PDF 文件。'); return; }
  if (selected.length > 50) { message('一次最多上传 50 个 PDF。'); return; }
  if (selected.some(file => file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf'))) { message('请选择 PDF 文件。'); return; }
  const data = new FormData(); selected.forEach(file => data.append('files', file));
  message(`正在上传 ${selected.length} 个 PDF…`, 'info');
  try {
    let response = await fetch('/api/pdf-batches', { method: 'POST', body: data });
    let payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || '批量上传失败');
    while (true) {
      renderBatchStatus(payload.items);
      state.results = batchResults(payload.items);
      renderResults();
      message(`正在处理 ${payload.completed + payload.failed}/${payload.total}，成功 ${payload.completed}，失败 ${payload.failed}。`, 'info');
      if (payload.status === 'completed') break;
      await new Promise(resolve => setTimeout(resolve, 1000));
      response = await fetch(`/api/pdf-batches/${encodeURIComponent(payload.batch_id)}`);
      payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || '无法获取批量任务状态');
    }
    const firstQuery = payload.items.find(item => item.query)?.query;
    if (firstQuery) $('#query').value = firstQuery;
    message(`批量处理完成：成功 ${payload.completed}，失败 ${payload.failed}，找到 ${state.results.length} 条去重候选。`, payload.completed ? 'info' : '');
  } catch (error) { message(error.message); }
}
async function updatePreview() {
  if (!state.library.length) { $('#preview').textContent = '添加文献后显示引用格式。'; return; }
  try { const response = await fetch('/api/format', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items: state.library, format: state.format }) }); const data = await response.json(); $('#preview').textContent = data.text || ''; } catch { $('#preview').textContent = '预览暂时不可用。'; }
}
$('#search-form').addEventListener('submit', event => { event.preventDefault(); search($('#query').value.trim()); });
$('#browse').addEventListener('click', () => $('#pdf-input').click()); $('#pdf-input').addEventListener('change', event => { const files = event.target.files; if (files.length) message(`已选择 ${files.length} 个 PDF，正在准备上传…`, 'info'); upload(files); event.target.value = ''; });
const drop = $('#drop-zone'); ['dragenter', 'dragover'].forEach(type => drop.addEventListener(type, event => { event.preventDefault(); drop.classList.add('dragover'); })); ['dragleave', 'drop'].forEach(type => drop.addEventListener(type, event => { event.preventDefault(); drop.classList.remove('dragover'); })); drop.addEventListener('drop', event => upload(event.dataTransfer.files)); drop.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') $('#pdf-input').click(); });
$('#format').addEventListener('change', event => { state.format = event.target.value; updatePreview(); });
$('#clear-library').addEventListener('click', () => { state.library = []; state.expanded.clear(); renderLibrary(); });
$('#copy').addEventListener('click', async () => { if (!state.library.length) return; await navigator.clipboard.writeText($('#preview').textContent); message('引用已复制到剪贴板。', 'info'); });
$('#export').addEventListener('click', async () => { if (!state.library.length) return; const response = await fetch('/api/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items: state.library, format: state.format }) }); const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `paper-citations.${state.format === 'bibtex' ? 'bib' : state.format === 'ris' ? 'ris' : 'txt'}`; link.click(); URL.revokeObjectURL(link.href); });
renderLibrary();
