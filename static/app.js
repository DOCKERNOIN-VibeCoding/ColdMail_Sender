// ---------- 공통 ----------
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const enc = encodeURIComponent;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtSize = n => n > 1048576 ? (n / 1048576).toFixed(1) + 'MB' : Math.ceil(n / 1024) + 'KB';

async function api(url, { method, body } = {}) {
  const opt = { method: method || (body === undefined ? 'GET' : 'POST'), headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  let res;
  try { res = await fetch(url, opt); }
  catch { throw new Error('프로그램 서버에 연결할 수 없습니다. 이 창을 닫고 바탕화면의 ColdMail Sender 아이콘으로 다시 실행하세요.'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

let toastTimer;
function toast(msg, isError = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'show' + (isError ? ' error' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = ''), isError ? 7000 : 3000);
}

// 이벤트 핸들러: 오류는 토스트로, 버튼은 처리 중 비활성화(중복 클릭 방지)
function on(target, ev, fn) {
  const el = typeof target === 'string' ? $(target) : target;
  el.addEventListener(ev, async e => {
    const btn = el.tagName === 'BUTTON' ? el : null;
    if (btn) btn.disabled = true;
    try { await fn(e); } catch (err) { toast(err.message, true); } finally { if (btn) btn.disabled = false; }
  });
}

function fillSelect(sel, items, keep) {
  const el = $(sel);
  const prev = keep ?? el.value;
  el.innerHTML = items.map(n => `<option>${esc(n)}</option>`).join('');
  if (items.includes(prev)) el.value = prev;
}

function pickFile(input) { const f = input.files[0]; input.value = ''; return f; }

// ---------- 탭 ----------
const tabInit = { send: initSend, lists: initLists, templates: initTemplates, log: loadLog, settings: loadSettings };
async function showTab(name) {
  $$('nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  $$('.tab').forEach(s => s.classList.toggle('active', s.id === 'tab-' + name));
  await tabInit[name]();
}
$$('nav button').forEach(b => on(b, 'click', () => showTab(b.dataset.tab)));
window.addEventListener('beforeunload', e => { if (L.dirty || T.dirty) e.preventDefault(); });

// ---------- 발송 ----------
const S = { recipients: [], current: null, settings: null, queue: [], queueId: null, only: null };
const campaignBody = () => ({ template: $('#s-template').value, list: $('#s-list').value, subject: $('#s-subject').value });

async function initSend() {
  const [t, l, a, s] = await Promise.all([api('/api/templates'), api('/api/lists'), api('/api/attachments'), api('/api/settings')]);
  fillSelect('#s-template', t);
  fillSelect('#s-list', l);
  S.settings = s;
  renderAttach(a);
  await updateFields();
  await loadQueue();
}

async function loadQueue() {
  S.queue = await api('/api/queue');
  $('#queue-card').hidden = !S.queue.length;
  $('#queue-items').innerHTML = S.queue.map(i => `<div class="queue-item">
      <div><b>${esc(i.subject)}</b><br><small class="muted">${esc(i.created)} · 템플릿 ${esc(i.template)} · 리스트 ${esc(i.list)}
        · ${i.indices ? i.indices.length + '명 지정' : '리스트 전체'}${i.attachments.length ? ' · 첨부 ' + esc(i.attachments.join(', ')) : ''}</small>
        ${i.note ? `<div class="hint">${esc(i.note)}</div>` : ''}</div>
      <div class="actions"><button class="primary" data-load="${esc(i.id)}">불러오기</button><button class="danger" data-del="${esc(i.id)}">삭제</button></div>
    </div>`).join('');
}

on('#queue-items', 'click', async e => {
  const { load, del } = e.target.dataset;
  if (del) {
    if (!confirm('이 발송 대기 항목을 삭제할까요?')) return;
    await api('/api/queue/' + enc(del), { method: 'DELETE' });
    return loadQueue();
  }
  if (!load) return;
  const item = S.queue.find(i => i.id === load);
  $('#s-template').value = item.template;
  $('#s-list').value = item.list;
  if ($('#s-template').value !== item.template || $('#s-list').value !== item.list) throw new Error('템플릿 또는 리스트를 찾을 수 없습니다');
  $('#s-subject').value = item.subject;
  await updateFields();
  $$('#s-attach input').forEach(c => (c.checked = item.attachments.includes(c.value)));
  await prepareRecipients(item.indices);
  S.queueId = item.id;
  toast('불러왔습니다. 미리보기와 수신자를 확인한 뒤 발송하세요');
});

async function updateFields() {
  const name = $('#s-list').value;
  const cols = name ? (await api('/api/lists/' + enc(name))).columns : [];
  $('#s-fields').innerHTML = cols.map(c => `<button class="chip" data-f="${esc(c)}">{{${esc(c)}}}</button>`).join(' ')
    || '<small class="muted">리스트를 선택하세요</small>';
}

on('#s-fields', 'click', e => {
  const f = e.target.dataset.f;
  if (f === undefined) return;
  const inp = $('#s-subject');
  const pos = inp.selectionStart ?? inp.value.length;
  inp.value = inp.value.slice(0, pos) + `{{${f}}}` + inp.value.slice(inp.selectionEnd ?? pos);
  inp.focus();
  resetRecipients();
});

function resetRecipients() {
  $('#s-recipients-card').hidden = true;
  Object.assign(S, { recipients: [], current: null, queueId: null, only: null });
}
on('#s-template', 'change', resetRecipients);
on('#s-list', 'change', async () => { resetRecipients(); await updateFields(); });
on('#s-subject', 'input', resetRecipients);

const selectedAttach = () => $$('#s-attach input:checked').map(i => i.value);
function renderAttach(items) {
  const checked = new Set(selectedAttach());
  $('#s-attach').innerHTML = items.length
    ? items.map(a => `<label class="check"><input type="checkbox" value="${esc(a.name)}" ${checked.has(a.name) ? 'checked' : ''}>
        ${esc(a.name)} <small class="muted">(${fmtSize(a.size)})</small>
        <button class="x" data-del="${esc(a.name)}" title="삭제">×</button></label>`).join('')
    : '<small class="muted">없음</small>';
}
on('#s-attach-upload', 'change', async e => {
  const fd = new FormData();
  [...e.target.files].forEach(f => fd.append('files', f));
  e.target.value = '';
  renderAttach(await api('/api/attachments', { body: fd }));
});
on('#s-attach', 'click', async e => {
  const name = e.target.dataset.del;
  if (name === undefined) return;
  e.preventDefault();
  if (!confirm(`첨부파일 '${name}'을(를) 삭제할까요?`)) return;
  renderAttach(await api('/api/attachments/' + enc(name), { method: 'DELETE' }));
});

// only: 발송 대기 항목이 지정한 행들(없으면 전체)
async function prepareRecipients(only = null) {
  const r = await api('/api/prepare', { body: campaignBody() });
  if (r.unknown.length) toast(`리스트에 없는 치환 필드: ${r.unknown.map(u => `{{${u}}}`).join(', ')} → 빈칸으로 들어갑니다`, true);
  S.recipients = r.recipients;
  S.only = only;
  renderRecipients();
  $('#s-recipients-card').hidden = false;
  if (r.recipients.length) await previewRow((r.recipients.find(x => !only || only.includes(x.idx)) || r.recipients[0]).idx);
}
on('#s-prepare', 'click', () => prepareRecipients());

function renderRecipients() {
  const skipSent = $('#s-skip-sent').checked;
  const rows = S.recipients.map(r => {
    const badges = [];
    if (r.invalid) badges.push('<span class="badge bad">주소 오류</span>');
    if (r.duplicate) badges.push('<span class="badge warn">중복</span>');
    if (r.already_sent) badges.push('<span class="badge info">발송 이력 있음</span>');
    if (r.missing.length) badges.push(`<span class="badge warn">빈 값: ${esc(r.missing.join(', '))}</span>`);
    if (r.omitted.length) badges.push(`<span class="badge muted-badge" title="비어 있는 맞춤문단은 그 문단을 빼고 보냅니다">생략: ${esc(r.omitted.join(', '))}</span>`);
    const ok = !r.invalid && !r.duplicate && !r.missing.length && !(skipSent && r.already_sent)
      && (!S.only || S.only.includes(r.idx));
    return `<tr data-idx="${r.idx}"><td><input type="checkbox" ${ok ? 'checked' : ''} ${r.invalid ? 'disabled' : ''}></td>
      <td>${r.idx + 1}</td><td>${esc(r.email)}</td><td>${esc(r.label)}</td><td>${badges.join(' ')}</td></tr>`;
  });
  $('#s-table').innerHTML = '<thead><tr><th></th><th>#</th><th>이메일</th><th>수신자</th><th>확인 사항</th></tr></thead><tbody>'
    + rows.join('') + '</tbody>';
  updateCount();
}
const checkedIndices = () => $$('#s-table tbody input:checked').map(i => +i.closest('tr').dataset.idx);
function updateCount() { $('#s-count').textContent = `${checkedIndices().length} / ${S.recipients.length}명 선택`; }

on('#s-skip-sent', 'change', () => { if (S.recipients.length) renderRecipients(); });
on('#s-all', 'click', () => { $$('#s-table tbody input:not(:disabled)').forEach(c => (c.checked = true)); updateCount(); });
on('#s-none', 'click', () => { $$('#s-table tbody input').forEach(c => (c.checked = false)); updateCount(); });
on('#s-table', 'click', async e => {
  const tr = e.target.closest('tbody tr');
  if (!tr) return;
  if (e.target.type === 'checkbox') { updateCount(); return; }
  await previewRow(+tr.dataset.idx);
});

async function previewRow(idx) {
  const r = await api('/api/render', { body: { ...campaignBody(), idx } });
  S.current = idx;
  $('#pv-subject').textContent = r.subject;
  $('#pv-frame').srcdoc = r.html;
  const rec = S.recipients.find(x => x.idx === idx);
  $('#pv-who').textContent = rec ? `→ ${rec.email}` : '';
  $$('#s-table tbody tr').forEach(tr => tr.classList.toggle('current', +tr.dataset.idx === idx));
}

on('#s-test', 'click', async () => {
  if (S.current == null) throw new Error('미리볼 수신자를 먼저 선택하세요');
  const r = await api('/api/test-send', { body: { ...campaignBody(), idx: S.current, attachments: selectedAttach() } });
  toast(`테스트 메일을 ${r.to} 로 보냈습니다`);
});

on('#s-start', 'click', async () => {
  const indices = checkedIndices();
  if (!indices.length) throw new Error('선택된 수신자가 없습니다');
  const s = S.settings;
  // 받는 서버는 발송 때 확인하므로 범위로만 안내: 전부 기타 주소일 때 ~ 전부 한 회사(Google 등)일 때
  const base = (s.base_delay_min + s.base_delay_max) / 2;
  const fast = Math.ceil((indices.length - 1) * base / 60);
  const slow = Math.ceil((indices.length - 1) * Math.max(base, (s.delay_min + s.delay_max) / 2) / 60);
  const att = selectedAttach();
  if (!confirm(`${indices.length}명에게 발송합니다.\n\n제목: ${$('#s-subject').value}\n첨부: ${att.length ? att.join(', ') : '없음'}\n`
    + `메일 간격 ${s.base_delay_min}~${s.base_delay_max}초, Google·Microsoft 주소끼리는 ${s.delay_min}~${s.delay_max}초\n`
    + `(예상 소요 약 ${fast === slow ? fast : `${fast}~${slow}`}분, Google·Microsoft 주소가 많을수록 오래 걸림)\n\n진행할까요?`)) return;
  await api('/api/send', { body: { ...campaignBody(), indices, attachments: att } });
  if (S.queueId) {
    await api('/api/queue/' + enc(S.queueId), { method: 'DELETE' });
    S.queueId = null;
    await loadQueue();
  }
  pollJob();
});

on('#job-stop', 'click', async () => { await api('/api/job/stop', { body: {} }); pollJob(); });

let jobTimer;
const JOB_LABELS = { running: '진행 중', stopping: '중지 중…', done: '완료', stopped: '중지됨', aborted: '중단됨' };
async function pollJob() {
  clearTimeout(jobTimer);
  const j = await api('/api/job');
  if (j.status === 'idle') return;
  const active = j.status === 'running' || j.status === 'stopping';
  $('#job-card').hidden = false;
  $('#job-status').textContent = JOB_LABELS[j.status] || j.status;
  $('#job-progress').max = j.total;
  $('#job-progress').value = j.sent + j.failed;
  let text = `${j.sent + j.failed} / ${j.total} · 성공 ${j.sent} · 실패 ${j.failed}`;
  if (j.current) text += ` · 발송 중: ${j.current}`;
  else if (j.next_at && active) text += ` · 다음 발송까지 ${Math.max(0, Math.round(j.next_at - Date.now() / 1000))}초`;
  if (j.message) text += ` · ${j.message}`;
  $('#job-text').textContent = text;
  $('#job-items').innerHTML = j.items.map(i =>
    `<li>${i.ok ? '<span class="badge ok">성공</span>' : '<span class="badge bad">실패</span>'} ${esc(i.email)}
     <span class="muted">${esc(i.label)}</span> ${i.note ? `<small class="muted">— ${esc(i.note)}</small>` : ''}</li>`).join('');
  $('#job-stop').hidden = !active;
  if (active) jobTimer = setTimeout(() => pollJob().catch(e => toast(e.message, true)), 1000);
}

// ---------- 수신자 리스트 ----------
const L = { data: null, dirty: false };
const DEFAULT_COLUMNS = ['이름', '채널명', '이메일', '플랫폼', '메모'];
const DEFAULT_EMPTY_ROWS = 5;

function setListDirty(v) { L.dirty = v; $('#l-save').classList.toggle('dirty', v); }

async function initLists() {
  const names = await api('/api/lists');
  fillSelect('#l-select', names, L.data?.name);
  if (L.data && names.includes(L.data.name)) return;
  if (names.length) await openList(names[0], true);
  else { L.data = null; setListDirty(false); renderListTable(); }
}

async function openList(name, force = false) {
  if (!force && L.dirty && !confirm('저장하지 않은 변경 내용이 있습니다. 버리고 이동할까요?')) {
    $('#l-select').value = L.data.name;
    return;
  }
  L.data = { name, ...(await api('/api/lists/' + enc(name))) };
  setListDirty(false);
  $('#l-select').value = name;
  renderListTable();
}

function renderListTable() {
  const t = $('#l-table');
  $('#l-resync').hidden = !L.data?.source;
  if (!L.data) {
    t.innerHTML = '<tr><td class="muted" style="padding:12px">리스트가 없습니다. \'새 리스트\' 또는 \'엑셀/CSV 가져오기\'로 시작하세요.</td></tr>';
    $('#l-count').textContent = '';
    return;
  }
  const { columns, rows } = L.data;
  t.innerHTML = '<thead><tr><th class="sel"><input type="checkbox" id="l-selall"></th>'
    + columns.map((c, i) => `<th><input data-col="${i}" value="${esc(c)}"><button class="x" data-delcol="${i}" title="열 삭제">×</button></th>`).join('')
    + '</tr></thead><tbody>'
    + rows.map((r, ri) => `<tr><td class="sel"><input type="checkbox" data-sel="${ri}"></td>`
      + columns.map((_, ci) => cellInput(r[ci] ?? '', ri, ci)).join('') + '</tr>').join('')
    + '</tbody>';
  $('#l-count').textContent = `${rows.length}명`;
}

// 한 줄 입력칸은 줄바꿈을 지워버리므로, 여러 줄인 칸은 읽기 전용으로 보여주고 편집창에서만 고친다
function cellInput(v, r, c) {
  const multi = v.includes('\n');
  return `<td><input data-r="${r}" data-c="${c}" value="${esc(multi ? v.replace(/\n/g, ' ⏎ ') : v)}"`
    + (multi ? ' readonly class="multi" title="클릭하면 편집창이 열립니다"' : '') + '></td>';
}

let cellTarget = null;
function openCellEditor(r, c) {
  cellTarget = { r, c };
  $('#cell-title').textContent = `${L.data.columns[c]} · ${r + 1}행`;
  $('#cell-text').value = L.data.rows[r][c] ?? '';
  $('#cell-dialog').showModal();
  $('#cell-text').focus();
}
function applyCellEditor() {
  L.data.rows[cellTarget.r][cellTarget.c] = $('#cell-text').value.replace(/\r\n/g, '\n').trim();
  setListDirty(true);
  renderListTable();
  $('#cell-dialog').close();
}
on('#l-table', 'dblclick', e => { const d = e.target.dataset; if (d.r !== undefined) openCellEditor(+d.r, +d.c); });
on('#cell-ok', 'click', applyCellEditor);
on('#cell-cancel', 'click', () => $('#cell-dialog').close());
on('#cell-text', 'keydown', e => { if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); applyCellEditor(); } });

async function saveList() {
  const { columns, rows, source } = L.data;
  await api('/api/lists/' + enc(L.data.name), { method: 'PUT', body: { columns, rows, source } });
  setListDirty(false);
}

// 엑셀에서 복사한 내용(탭/줄바꿈 구분, 줄바꿈이 든 칸은 "..."로 감싸짐)을 2차원 배열로
function parseClipboard(text) {
  const rows = [[]];
  let cell = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch !== '"') cell += ch;
      else if (text[i + 1] === '"') { cell += '"'; i++; }
      else quoted = false;
    } else if (ch === '"' && cell === '') quoted = true;
    else if (ch === '\t') { rows.at(-1).push(cell); cell = ''; }
    else if (ch === '\r' || ch === '\n') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      rows.at(-1).push(cell); cell = ''; rows.push([]);
    } else cell += ch;
  }
  rows.at(-1).push(cell);
  if (rows.length > 1 && rows.at(-1).join('') === '') rows.pop();  // 엑셀은 끝에 줄바꿈을 붙인다
  return rows.map(r => r.map(c => c.replace(/\r\n/g, '\n').trim()));
}
function ensureColumn(c) {
  while (L.data.columns.length <= c) {
    L.data.columns.push(`열${L.data.columns.length + 1}`);
    L.data.rows.forEach(r => r.push(''));
  }
}
function setCell(r, c, v) {
  ensureColumn(c);
  while (L.data.rows.length <= r) L.data.rows.push(L.data.columns.map(() => ''));
  L.data.rows[r][c] = v;
}

on('#l-table', 'paste', e => {
  const text = e.clipboardData.getData('text/plain');
  if (!/[\t\r\n]/.test(text.replace(/\r?\n$/, ''))) return;  // 한 칸짜리는 기본 붙여넣기
  e.preventDefault();
  const d = e.target.dataset;
  const grid = parseClipboard(text);
  const c0 = +(d.c ?? d.col ?? 0);
  let r0 = +(d.r ?? 0);
  if (d.col !== undefined) {  // 머리글에 붙여넣으면 첫 줄은 열 이름
    grid.shift().forEach((name, j) => { ensureColumn(c0 + j); if (name) L.data.columns[c0 + j] = name; });
    r0 = 0;
  }
  grid.forEach((vals, i) => vals.forEach((v, j) => setCell(r0 + i, c0 + j, v)));
  setListDirty(true);
  renderListTable();
  toast(`${grid.length}행을 붙여넣었습니다. 확인 후 저장하세요`);
});

on('#l-select', 'change', e => openList(e.target.value));
on('#l-table', 'input', e => {
  const d = e.target.dataset;
  if (d.col !== undefined) L.data.columns[d.col] = e.target.value;
  else if (d.r !== undefined) L.data.rows[d.r][d.c] = e.target.value;
  else return;
  setListDirty(true);
});
on('#l-table', 'click', e => {
  if (e.target.id === 'l-selall') { $$('#l-table [data-sel]').forEach(c => (c.checked = e.target.checked)); return; }
  if (e.target.classList.contains('multi')) { openCellEditor(+e.target.dataset.r, +e.target.dataset.c); return; }
  const c = e.target.dataset.delcol;
  if (c === undefined) return;
  if (!confirm(`'${L.data.columns[c]}' 열을 삭제할까요?`)) return;
  L.data.columns.splice(c, 1);
  L.data.rows.forEach(r => r.splice(c, 1));
  setListDirty(true);
  renderListTable();
});
on('#l-addrow', 'click', () => {
  if (!L.data) throw new Error('리스트를 먼저 만드세요');
  L.data.rows.push(L.data.columns.map(() => ''));
  setListDirty(true);
  renderListTable();
  const last = $('#l-table tbody tr:last-child input[data-c="0"]');
  last.scrollIntoView({ block: 'nearest' });
  last.focus();
});
on('#l-addcol', 'click', () => {
  if (!L.data) throw new Error('리스트를 먼저 만드세요');
  const name = prompt('새 열 이름 (본문에서 {{열이름}} 으로 사용)');
  if (!name) return;
  L.data.columns.push(name.trim());
  L.data.rows.forEach(r => r.push(''));
  setListDirty(true);
  renderListTable();
});
on('#l-delrows', 'click', () => {
  const sel = $$('#l-table [data-sel]:checked').map(c => +c.dataset.sel);
  if (!sel.length) throw new Error('삭제할 행을 체크하세요');
  if (!confirm(`${sel.length}개 행을 삭제할까요?`)) return;
  sel.sort((a, b) => b - a).forEach(i => L.data.rows.splice(i, 1));
  setListDirty(true);
  renderListTable();
});
on('#l-save', 'click', async () => {
  if (!L.data) return;
  await saveList();
  toast('저장했습니다');
});
on('#l-new', 'click', async () => {
  if (L.dirty && !confirm('저장하지 않은 변경 내용이 있습니다. 버릴까요?')) return;
  const name = prompt('새 리스트 이름');
  if (!name) return;
  if ((await api('/api/lists')).includes(name.trim())) throw new Error('같은 이름의 리스트가 있습니다');
  L.data = { name: name.trim(), columns: [...DEFAULT_COLUMNS], rows: Array.from({ length: DEFAULT_EMPTY_ROWS }, () => DEFAULT_COLUMNS.map(() => '')) };
  await saveList();
  await initLists();
  renderListTable();
});
on('#l-import', 'change', async e => {
  const f = pickFile(e.target);
  if (!f) return;
  if (L.dirty && !confirm('저장하지 않은 변경 내용이 있습니다. 버릴까요?')) return;
  const name = prompt('리스트 이름', f.name.replace(/\.(xlsx|csv)$/i, ''));
  if (!name) return;
  if ((await api('/api/lists')).includes(name.trim()) && !confirm('같은 이름의 리스트를 덮어쓸까요?')) return;
  const fd = new FormData();
  fd.append('file', f);
  fd.append('name', name.trim());
  const r = await api('/api/lists/import', { body: fd });
  setListDirty(false);
  L.data = null;
  await initLists();
  await openList(r.name, true);
  toast(`${L.data.rows.length}명을 가져왔습니다`);
});
async function importGoogleSheet(name, url) {
  await api('/api/lists/import-gsheet', { body: { name, url } });
  setListDirty(false);
  L.data = null;
  await initLists();
  await openList(name, true);
  toast(`구글시트에서 ${L.data.rows.length}명을 가져왔습니다`);
}
on('#l-gsheet', 'click', async () => {
  if (L.dirty && !confirm('저장하지 않은 변경 내용이 있습니다. 버릴까요?')) return;
  const url = prompt('구글시트 주소를 붙여넣으세요.\n(시트 공유 설정: 링크가 있는 모든 사용자 - 뷰어. 여러 탭이면 가져올 탭을 열어둔 상태의 주소)');
  if (!url) return;
  const name = prompt('리스트 이름', '구글시트');
  if (!name) return;
  if ((await api('/api/lists')).includes(name.trim()) && !confirm('같은 이름의 리스트를 덮어쓸까요?')) return;
  await importGoogleSheet(name.trim(), url.trim());
});
on('#l-resync', 'click', async () => {
  if (!confirm('구글시트의 현재 내용으로 다시 불러옵니다. 이 앱에서 고친 내용은 시트 내용으로 바뀝니다. 진행할까요?')) return;
  await importGoogleSheet(L.data.name, L.data.source);
});

on('#l-delete', 'click', async () => {
  if (!L.data || !confirm(`리스트 '${L.data.name}'을(를) 삭제할까요? 되돌릴 수 없습니다.`)) return;
  await api('/api/lists/' + enc(L.data.name), { method: 'DELETE' });
  L.data = null;
  setListDirty(false);
  await initLists();
});

// ---------- 메일 템플릿 ----------
const T = { name: null, kind: null, dirty: false };
const SAMPLE_TEMPLATE = `안녕하세요, {{채널명}} {{이름}} 님.

저는 ○○○의 홍길동입니다. {{채널명}} 채널의 콘텐츠를 인상 깊게 보고 협업을 제안드리고자 연락드립니다.
저희 브랜드가 {{채널명}}과 함께한다면 좋은 시너지를 낼 수 있으리라 생각합니다.

**제안 내용**
- 협업 형태:
- 일정:
- 조건:

자세한 내용은 회신 주시면 안내드리겠습니다.

감사합니다.
홍길동 드림
`;

function setTplDirty(v) { T.dirty = v; $('#t-save').classList.toggle('dirty', v); }

async function initTemplates() {
  const names = await api('/api/templates');
  fillSelect('#t-select', names, T.name);
  if (T.dirty && names.includes(T.name)) return;
  if (names.length) await openTemplate(names.includes(T.name) ? T.name : names[0], true);
  else { T.name = null; $('#t-source').value = ''; $('#t-frame').srcdoc = ''; }
}

async function openTemplate(name, force = false) {
  if (!force && T.dirty && !confirm('저장하지 않은 변경 내용이 있습니다. 버리고 이동할까요?')) {
    $('#t-select').value = T.name;
    return;
  }
  const t = await api('/api/templates/' + enc(name));
  Object.assign(T, { name: t.name, kind: t.kind });
  setTplDirty(false);
  $('#t-select').value = t.name;
  const isMd = t.kind === 'md';
  $('#t-source').hidden = !isMd;
  $('#t-save').hidden = !isMd;
  $('#t-docx-note').hidden = isMd;
  $('#t-source').value = t.source ?? '';
  $('#t-frame').srcdoc = t.html;
}

let renderTimer;
on('#t-source', 'input', () => {
  setTplDirty(true);
  clearTimeout(renderTimer);
  renderTimer = setTimeout(async () => {
    try { $('#t-frame').srcdoc = (await api('/api/templates/render', { body: { source: $('#t-source').value } })).html; }
    catch (err) { toast(err.message, true); }
  }, 400);
});
on('#t-select', 'change', e => openTemplate(e.target.value));
on('#t-save', 'click', async () => {
  if (!T.name) return;
  await api('/api/templates/' + enc(T.name), { method: 'PUT', body: { source: $('#t-source').value } });
  setTplDirty(false);
  toast('저장했습니다');
});
on('#t-new', 'click', async () => {
  if (T.dirty && !confirm('저장하지 않은 변경 내용이 있습니다. 버릴까요?')) return;
  let name = prompt('새 템플릿 이름 (예: 협업제안_기본)');
  if (!name) return;
  name = name.trim().replace(/\.md$/i, '') + '.md';
  if ((await api('/api/templates')).includes(name)) throw new Error('같은 이름의 템플릿이 있습니다');
  await api('/api/templates/' + enc(name), { method: 'PUT', body: { source: SAMPLE_TEMPLATE } });
  T.name = name;
  setTplDirty(false);
  await initTemplates();
});
on('#t-upload', 'change', async e => {
  const f = pickFile(e.target);
  if (!f) return;
  if ((await api('/api/templates')).includes(f.name) && !confirm(`'${f.name}'을(를) 덮어쓸까요?`)) return;
  const fd = new FormData();
  fd.append('file', f);
  const r = await api('/api/templates/upload', { body: fd });
  T.name = r.name;
  setTplDirty(false);
  await initTemplates();
});
on('#t-folder', 'click', () => api('/api/open-folder/templates', { body: {} }));
on('#t-delete', 'click', async () => {
  if (!T.name || !confirm(`템플릿 '${T.name}'을(를) 삭제할까요?`)) return;
  await api('/api/templates/' + enc(T.name), { method: 'DELETE' });
  T.name = null;
  setTplDirty(false);
  await initTemplates();
});

// ---------- 발송 기록 ----------
let LOG = [];
async function loadLog() { LOG = await api('/api/log'); renderLog(); }
function renderLog() {
  const q = $('#g-filter').value.trim().toLowerCase();
  const rows = LOG.filter(r => !q || Object.values(r).join(' ').toLowerCase().includes(q));
  $('#g-count').textContent = `${rows.length}건`;
  $('#g-table').innerHTML = '<thead><tr><th>시각</th><th>결과</th><th>이메일</th><th>수신자</th><th>제목</th><th>템플릿</th><th>리스트</th><th>비고</th></tr></thead><tbody>'
    + rows.map(r => `<tr><td>${esc(r.ts)}</td>
      <td>${r.status === 'sent' ? '<span class="badge ok">성공</span>' : '<span class="badge bad">실패</span>'}</td>
      <td>${esc(r.email)}</td><td>${esc(r.label)}</td><td>${esc(r.subject)}</td>
      <td>${esc(r.template)}</td><td>${esc(r.list)}</td><td><small>${esc(r.error)}</small></td></tr>`).join('')
    + '</tbody>';
}
on('#g-filter', 'input', renderLog);
on('#g-refresh', 'click', loadLog);

// ---------- 설정 ----------
const SET_KEYS = ['smtp_host', 'smtp_port', 'smtp_security', 'username', 'from_name', 'from_email',
  'imap_enabled', 'imap_host', 'imap_port', 'imap_sent_folder', 'base_delay_min', 'base_delay_max', 'delay_min', 'delay_max'];

function applySettings(s) {
  SET_KEYS.forEach(k => {
    const el = $('#set-' + k);
    if (el.type === 'checkbox') el.checked = !!s[k]; else el.value = s[k] ?? '';
  });
  $('#set-password').value = '';
  $('#set-password').placeholder = s.has_password ? '저장됨 (변경할 때만 입력)' : '';
}
async function loadSettings() { applySettings(await api('/api/settings')); }

async function saveSettings() {
  const d = {};
  SET_KEYS.forEach(k => {
    const el = $('#set-' + k);
    d[k] = el.type === 'checkbox' ? el.checked : el.value.trim();
  });
  if (!d.from_email) d.from_email = d.username;
  const pw = $('#set-password').value;
  if (pw) d.password = pw;
  applySettings(await api('/api/settings', { body: d }));
}

on('#set-save', 'click', async () => { await saveSettings(); toast('설정을 저장했습니다'); });
on('#set-test', 'click', async () => {
  await saveSettings();
  $('#set-result').textContent = '연결 확인 중…';
  const r = await api('/api/settings/test', { body: {} });
  const parts = [`SMTP: ${r.smtp === 'ok' ? '✔ 정상' : '✖ ' + r.smtp}`];
  if (r.imap) parts.push(`IMAP: ${r.imap === 'ok' ? '✔ 정상' : '✖ ' + r.imap}`);
  if (r.folders) {
    $('#imap-folders').innerHTML = r.folders.map(f => `<option value="${esc(f)}">`).join('');
    const cur = $('#set-imap_sent_folder');
    if (!r.folders.includes(cur.value) && r.sent_guess) {
      cur.value = r.sent_guess;
      await saveSettings();
      parts.push(`보낸편지함 폴더를 '${r.sent_guess}'(으)로 지정했습니다`);
    } else if (!r.folders.includes(cur.value)) {
      parts.push(`'${cur.value}' 폴더가 없습니다. 목록에서 선택하세요`);
    }
  }
  $('#set-result').textContent = parts.join('  ·  ');
});
on('#preset-gmail', 'click', () => {
  Object.entries({ smtp_host: 'smtp.gmail.com', smtp_port: 587, smtp_security: 'starttls', imap_host: 'imap.gmail.com', imap_port: 993 })
    .forEach(([k, v]) => ($('#set-' + k).value = v));
  $('#set-imap_enabled').checked = false;
  toast('Gmail 설정을 채웠습니다. 계정·앱 비밀번호를 입력하고 저장하세요');
});

// ---------- 시작 ----------
initSend().catch(e => toast(e.message, true));
pollJob().catch(() => {});
// 창이 열려 있는 동안 서버 유지(닫히면 3분 뒤 자동 종료) + Claude 가 올린 발송 대기 반영
setInterval(() => loadQueue().catch(() => {}), 30000);
