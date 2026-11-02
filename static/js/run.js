// 日常管家界面 · 开始 / 继续 / 停止 / 让出电脑、轮询、拖动排序。和其它 static/js/*.js 共用全局（不打包，按 index.html 里的顺序加载）。

'use strict';

// ------------------------------------------------------------------ 开始 / 继续 / 停止 / 让出电脑
// 「开始」只有一种：排进今天日程的队尾（立即）。前面没有在跑就马上开始，正在跑就排在后面，由后台日程按顺序跑。
// 当天已经做完的任务会跳过；有运行时段的任务在时段外跳过。
const namesOf = ids => ids.map(x => splitName(game(x)?.name || x)[0]).join('、');
function syncResume(r) { // 停止后「继续」的记录在后台（/api/running 的 resume）
  const x = r?.resume;
  S.resume = x ? { games: [...new Set(Object.values(x.games).map(v => v.game))], task: x.current?.task || '', source: x.source || '', stopped_at: x.stopped_at || '' } : null;
}
async function dropResume() { // 「不继续了」：放弃剩下的任务
  try { await api('DELETE', '/api/continue'); } catch (e) { return fail(e); }
  S.resume = null; toast('已放弃剩下的任务，之后照常调度');
  await pollRunning(); await loadState(); renderTop(); renderBars(); refreshAfterResume();
}
async function resumeRun() {
  try {
    const r = await api('POST', '/api/continue');
    S.resume = null;
    if (r.batches.length) toast(`继续 ${namesOf(r.batches.map(b => b.game))}：已排进今天的队列（已完成的任务会跳过）`);
    (r.skipped || []).forEach(x => toast(x, true));
    askNotify(); S.fastUntil = Date.now() + 40000; await pollRunning(); await loadState(); renderTop();
  } catch (e) { fail(e); }
  renderBars(); refreshAfterResume();
}
function refreshAfterResume() { if (S.route.view === 'home') renderHome(); else if (S.route.view === 'game' && S.ed) { const box = $('.ghero'); if (box) box.outerHTML = gameShell(game(S.ed.gid), S.ed.tab); } }

async function startGame(gid, tasks, rerun = false, quiet = false, routine = '') {
  const g = game(gid);
  if (!quiet && !tasks && isPC(g) && !(await confirmBox(`开始 ${esc(g.name)}？`, '这是电脑端游戏，运行时会占用电脑前台，期间不能用电脑。', '开始'))) return false;
  try {
    const r = await api('POST', '/api/schedule/today/items', { game: gid, tasks: tasks || [], rerun, routine });
    if (!quiet) toast(`${splitName(g.name)[0]} · ${tasks ? `选中的 ${tasks.length} 个任务` : routine ? `任务预设「${routine}」` : '今天的任务'}：${r.batch.paused ? '已排进今天的队列，让出电脑中，恢复调度后开始' : S.running?.running ? '已排进今天的队列，前面的跑完接着跑' : '马上开始'}`);
    askNotify(); S.fastUntil = Date.now() + 40000; pollRunning();
    return true;
  } catch (e) { fail(e); return false; }
}

// 「开始全部游戏」：今天还没做完的游戏都排进队列（含电脑端游戏）。
async function runAll() {
  const R = S.running;
  const gs = (S.state?.games || []).filter(g => g.available && g.total > 0 && g.done < g.total && !g.running && g.id !== R?.current?.game);
  if (!gs.length) return toast('今天所有游戏的任务都已完成');
  const pcs = gs.filter(isPC);
  const ok = await confirmBox(`开始全部游戏（${gs.length}）？`, `<div>今天还没做完的游戏按顺序排进队列，已完成的任务会跳过：</div>
    <ol style="margin:0;padding-left:20px;line-height:1.9">${gs.map(g => `<li>${esc(g.name)} <span class="faint num">${g.done}/${g.total}</span>${isPC(g) ? ' <span class="chip gray">电脑端</span>' : ''}</li>`).join('')}</ol>
    ${pcs.length ? `<div class="small" style="display:flex;align-items:center;gap:6px;color:var(--orange-ink)">${ICON.warn.replace(/var\(--orange\)/g, 'currentColor')}跑到${esc(namesOf(pcs.map(g => g.id)))}时会占用电脑前台，期间不能用电脑。</div>` : ''}`, '开始');
  if (!ok) return;
  const ok2 = [];
  for (const g of gs) if (await startGame(g.id, null, false, true)) ok2.push(g.id); // 没有要跑的会单独提示原因
  if (ok2.length) toast(`已排进今天的队列：${namesOf(ok2)}`);
}

async function pickRun(gid) {
  const g = game(gid);
  try { await switches(gid); } catch (e) { return fail(e); }
  let plan, status;
  try { const r = await api('GET', `/api/today/${encodeURIComponent(gid)}`); plan = r; status = r.status || {}; } catch (e) { return fail(e); }
  const tasks = plan.tasks;
  const reason = t => { const sw = (S.switches[gid] || []).find(x => x.task === t); return sw && sw.disabled ? (sw.reason || '已停用') : ''; };
  const sel = new Set(tasks.filter(t => !reason(t.task) && !DONE.has(status[keyOf(t)]?.result)).map(keyOf));
  let rerun = false;
  const html = () => `<div class="small">按今天各条里的任务列出，默认勾选了还没完成的任务；启动游戏的任务会自动加在最前。</div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center"><button class="btn xs" data-pk="all">全选</button><button class="btn xs" data-pk="none">全不选</button><button class="btn xs" data-pk="todo">只选未完成</button>
      <label class="small" style="margin-left:auto"><input type="checkbox" id="pk-rerun" ${rerun ? 'checked' : ''}> 今天做过的也再跑一次</label></div>
    <div class="pick">${tasks.map(t => { const k = keyOf(t), off = reason(t.task), st = status[k], w = winOf(g, t); return `<button type="button" class="it${sel.has(k) ? ' on' : ''}" data-pk-key="${esc(k)}" aria-pressed="${sel.has(k)}" ${off ? 'disabled' : ''}>
      <span class="cbx">${ICON.check.replace('currentColor', '#fff')}</span><span class="nm"><b>${esc(tn(k))}</b>${w ? `<div>只在 ${esc(winLocal(w))}</div>` : ''}</span>${off ? '<span class="badge off">停用</span>' : ''}${st ? badge(st.result) : '<span class="badge off">未运行</span>'}</button>`; }).join('')}</div>`;
  const res = await modal({
    title: `选择要跑的任务 · ${g.name}`, wide: true, ok: '开始', body: `<div id="pk">${html()}</div>${S.running?.running ? '<div class="small" style="color:var(--blue-ink)">现在正在运行：会排进今天的队列，前面的跑完接着跑。</div>' : ''}`,
    onMount: (m, setOk) => {
      const upd = () => {
        $('#pk', m).innerHTML = html(); const b = $('[data-m="ok"]', m);
        b.disabled = !sel.size; b.textContent = sel.size ? `开始（${sel.size} 个任务）` : '先选任务';
      };
      m.addEventListener('click', e => {
        const k = e.target.closest('[data-pk-key]'); const a = e.target.closest('[data-pk]');
        if (k && !k.disabled) { const v = k.dataset.pkKey; sel.has(v) ? sel.delete(v) : sel.add(v); upd(); }
        if (a) { sel.clear(); if (a.dataset.pk === 'all') tasks.filter(t => !reason(t.task)).forEach(t => sel.add(keyOf(t))); if (a.dataset.pk === 'todo') tasks.filter(t => !reason(t.task) && !DONE.has(status[keyOf(t)]?.result)).forEach(t => sel.add(keyOf(t))); upd(); }
      });
      m.addEventListener('change', e => { if (e.target.id === 'pk-rerun') rerun = e.target.checked; });
      setOk(() => [...sel]); upd();
    },
  });
  if (!res || !res.length) return;
  startGame(gid, tasks.map(keyOf).filter(k => res.includes(k)), rerun);
}

async function stopRun() {
  let close = false; // 设置里「中止队列时，关闭模拟器和游戏」（11-02）
  try { close = !!(await api('GET', '/api/settings')).scheduler?.halt_close; } catch (e) { /* 读不到就按没勾 */ }
  if (!(await confirmBox('中止队列？', `当前任务会在 2 秒内停下，整个队列（排着的、定时到点的）都先不开始。${close ? '<br><b>按你的设置，停下后会关闭所有模拟器和电脑游戏 / 工具。</b>' : ''}<br>之后点「继续」接着跑：已完成的任务跳过，停下的那个从头再跑；点「不继续了」放弃剩下的，回到平常调度。<br><span class="muted">只想让 BetterGI 停在原地：用「原地暂停」。只想跳过这一项：用「跳过当前任务」。${close ? '' : '想顺便关掉模拟器和游戏：设置 → 运行。'}</span>`, '中止队列', true))) return;
  try { const r = await api('POST', '/api/stop'); toast(r.closing ? '已中止队列，正在关闭模拟器和游戏' : '已中止队列'); S.fastUntil = Date.now() + 20000; pollRunning(); } catch (e) { fail(e); }
}
async function yieldPc() {
  if (!(await confirmBox('一键让出电脑？', `<ul style="margin:0;padding-left:18px;line-height:1.8"><li>停止正在进行的运行</li><li>暂停调度：什么都不开始，排着的和你手动点「开始」的都等恢复后再跑</li><li>关闭所有模拟器实例和电脑游戏 / 工具</li></ul><p style="margin:6px 0 0">大约 1 分钟内完成。之后点「恢复调度」就回到平常。</p>`, '让出电脑', true))) return;
  try { await api('POST', '/api/yield'); toast('正在让出电脑：停止运行并关闭游戏…'); S.fastUntil = Date.now() + 30000; await pollRunning(); await loadState(); renderTop(); renderBars(); } catch (e) { fail(e); }
}
async function resume() {
  try { await api('POST', '/api/resume'); toast('已恢复自动调度'); await pollRunning(); await loadState(); renderTop(); renderBars(); if (S.route.view === 'home') renderHome(); } catch (e) { fail(e); }
}
async function setTaskEnabled(task, on) { // 任务库的「启用 | 停用」：点了立即生效
  const ed = S.ed; const cur = (S.switches[ed.gid] || []).find(x => x.task === task);
  if (cur && !cur.disabled === on) return;
  try {
    await api('POST', `/api/tasks/${encodeURIComponent(ed.gid)}/${on ? 'enable' : 'disable'}`, on ? { task } : { task, reason: '' });
    await switches(ed.gid, true);
    toast(`已${on ? '启用' : '停用'}「${tn(task)}」`); renderLibrary();
    const a = $('#aside'); if (a) a.innerHTML = asideHtml(game(ed.gid));
  } catch (e) { fail(e); }
}

// 浏览器通知（运行结束时）
function askNotify() { try { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); } catch (e) { /* 忽略 */ } }
function notify(title, body) { try { if ('Notification' in window && Notification.permission === 'granted' && document.hidden) new Notification(title, { body }); } catch (e) { /* 忽略 */ } }

const reGantt = () => renderNews();

// ------------------------------------------------------------------ 轮询
let pollTimer = null, polling = false;
async function pollRunning() {
  if (polling) return; polling = true;
  clearTimeout(pollTimer);
  try {
    const r = await api('GET', '/api/running');
    const was = S.running?.running, prevGame = S.running?.current?.game, prevTask = S.running?.current?.task;
    S.running = r; S.offline = null; syncResume(r);
    const changed = was !== r.running || prevGame !== r.current?.game || prevTask !== r.current?.task;
    renderBars();
    if (was && !r.running) { toast('运行结束'); notify('日常管家', '运行结束，点开看看结果'); }
    if (r.running || changed) await refreshLive(changed);
  } catch (e) { S.offline = e.message; renderBars(); }
  polling = false;
  const fast = S.running?.running || Date.now() < (S.fastUntil || 0);
  pollTimer = setTimeout(pollRunning, fast ? 3000 : 10000);
}
async function refreshLive(changed) {
  const r = S.route;
  try {
    // 运行开始 / 结束时不在总览、游戏页（例如在活动日历、设置页）：也要更新游戏状态，不然回到总览时卡片还停在「运行中」
    if (changed && r.view === 'schedule') { await loadState(); renderTop(); renderSchedule(); return; }
    if (changed && r.view !== 'home' && r.view !== 'game') { await loadState(); renderTop(); return; }
    if (r.view === 'home') { await loadState(); if (changed) await loadReport().catch(() => {}); renderHome(); renderTop(); return; }
    if (r.view === 'game' && S.ed) {
      const gid = S.ed.gid; await loadState();
      if (S.running?.running && S.running.current?.game === gid && !Array.isArray(S.running.current.focus)) S.runsCache[gid] = await api('GET', `/api/runs/${encodeURIComponent(gid)}`).catch(() => S.runsCache[gid]);
      if (S.ed.tab === 'today') {
        const st = await api('GET', `/api/today/${encodeURIComponent(gid)}`);
        S.ed.status = st.status || {}; S.ed.items = st.items || [];
        if (changed) S.ed.tasks = st.tasks || [];
      }
      if (changed) { const box = $('.ghero'); if (box) box.outerHTML = gameShell(game(gid), S.ed.tab); }
      if (S.ed.tab === 'runs') { if (changed || S.running?.running) renderRuns(); }
      else if (S.ed.tab !== 'library') refreshListKeepFocus();
    }
  } catch (e) { /* 忽略 */ }
}
function refreshListKeepFocus() {
  const a = document.activeElement;
  if (a && /INPUT|SELECT|TEXTAREA/.test(a.tagName) && a.closest('#tlist') && a.dataset.act !== 'filter') { const as = $('#aside'); if (as) as.innerHTML = asideHtml(game(S.ed.gid)); return; }
  refreshList();
}
setInterval(() => { tickClock(); if (S.running?.running) { renderBars(); } }, 1000);
setInterval(async () => { if (S.route.view === 'home' && !S.running?.running && !document.hidden) { try { await loadState(); await loadReport(); renderHome(); } catch (e) { /* 忽略 */ } } }, 30000);

// ------------------------------------------------------------------ 拖动排序
function bindDrag() {
  const rows = $('#rows'); if (!rows) return;
  let from = null;
  $$('.thead[draggable]', rows).forEach(h => {
    h.addEventListener('dragstart', e => {
      if (S.ed.filter) { e.preventDefault(); return; }
      from = +h.dataset.i; h.parentElement.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', String(from)); } catch (x) { /* 忽略 */ }
    });
    h.addEventListener('dragend', () => { $$('.trow', rows).forEach(r => r.classList.remove('dragging', 'drop-before', 'drop-after')); from = null; });
  });
  rows.addEventListener('dragover', e => {
    if (from === null) return; e.preventDefault();
    const r = e.target.closest('.trow'); $$('.trow', rows).forEach(x => x.classList.remove('drop-before', 'drop-after'));
    if (!r) return; const b = r.getBoundingClientRect(); r.classList.add(e.clientY < b.top + b.height / 2 ? 'drop-before' : 'drop-after');
  });
  rows.addEventListener('drop', e => {
    if (from === null) return; e.preventDefault();
    const r = e.target.closest('.trow'); if (!r) return;
    const b = r.getBoundingClientRect(); let to = +r.dataset.i + (e.clientY < b.top + b.height / 2 ? 0 : 1);
    if (to > from) to--; const f = from; from = null; moveTask(f, to);
  });
}

// 运行行「跳过当前任务」；右键它 →「跳过当前序列」（这个游戏这次剩下的都不跑）
async function skipCurrent(scope) {
  const R = S.running; const c = R?.current || {}; const g = game(c.game);
  const ok = scope === 'game'
    ? await confirmBox('跳过当前序列？', `${esc(g ? splitName(g.name)[0] : '这个游戏')}这次剩下的任务都不跑，接着下一个游戏。定时生成的这一条今天不再自动跑。`, '跳过序列', true)
    : await confirmBox('跳过当前任务？', `「${esc(tn(c.task) || '当前任务')}」马上停下，接着跑这个游戏后面的任务。今天不再自动跑它（游戏页「今日任务」里右键可以取消跳过）。`, '跳过', true);
  if (!ok) return;
  try { await api('POST', '/api/running/skip', { scope }); toast(scope === 'game' ? '正在跳过这个序列…' : '正在跳过这个任务…'); S.fastUntil = Date.now() + 20000; pollRunning(); } catch (e) { fail(e); }
}
document.addEventListener('contextmenu', e => {
  const b = e.target.closest?.('[data-act="skip-cur"]'); if (!b) return;
  e.preventDefault(); closeCtx();
  const m = document.createElement('div'); m.className = 'ctx glass'; m.id = 'news-ctx';
  m.innerHTML = `<button type="button" data-act="skip-cur" data-scope="task"><i>⏭</i>跳过当前任务</button><button type="button" data-act="skip-cur" data-scope="game"><i>⏩</i>跳过当前序列</button>`;
  document.body.appendChild(m);
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(e.clientX, innerWidth - r.width - 8) + 'px'; m.style.top = Math.min(e.clientY, innerHeight - r.height - 8) + 'px';
});

// 没做成的任务手动标成已完成（10-31）：今天不再算失败，也不再自动重跑
async function markDone(gid, keys) {
  if (!keys?.length) return;
  if (!(await confirmBox('标记为已完成？', `${esc(shortName(gid))}：${esc(keys.map(tn).join('、'))}。今天不再算失败，也不再自动重跑；明天照常。`, '标记为已完成'))) return;
  try {
    await api('POST', `/api/today/${encodeURIComponent(gid)}/mark-done`, { keys });
    toast('已标记为已完成');
    await loadState();
    if (S.route.view === 'schedule') renderSchedule();
    else if (S.route.view === 'report') renderReport();
    else if (S.route.view === 'home') renderHome();
    else if (S.ed?.gid === gid) { const open = S.ed.open, tab = S.ed.tab; await loadEditor(gid, tab); S.ed.open = open; renderGame(); }
  } catch (e) { fail(e); }
}

// 打开自动调度（10-31）：第一次打开时问要不要一起开「卡死处理」（多半是没人看着的时候跑）
const STUCK_TEXT = 'MAA 类游戏的画面 10 分钟没有变化，就算卡住（之后怎么办看下面「卡住以后」）。开着时不用每项的最长时间，只留 90 分钟兜底；关着时按下面的「每项最长时间」。';
async function schedulerOn() {
  let st = S.sch?.settings;
  try { if (!st) st = (await api('GET', '/api/settings')).scheduler; } catch (e) { st = {}; }
  if (!st.stuck_asked && !st.stuck_restart) {
    const ans = await modal({ title: '同时开启卡死处理？', ok: '开启卡死处理', alt: '先不开', cancel: '',
      body: `<div class="small">自动调度多半在没人看着的时候跑。${STUCK_TEXT}</div><div class="xsmall faint">之后可以在日程页「调度设置」里随时改。</div>` });
    try { await api('PUT', '/api/settings/scheduler', { stuck_asked: true, ...(ans === true ? { stuck_restart: true } : {}) }); } catch (e) { fail(e); }
    if (S.sch?.settings) Object.assign(S.sch.settings, { stuck_asked: true, ...(ans === true ? { stuck_restart: true } : {}) });
  }
  await api('POST', '/api/scheduler/on');
}

// 没做成的任务的右键菜单（总览「日常一览」、运行记录、游戏页今日任务共用，11-01）：立刻重跑 / 标为已完成 / 跳过任务
function showCtx(e, title, buttons) {
  e.preventDefault(); closeCtx();
  const m = document.createElement('div'); m.className = 'ctx glass'; m.id = 'news-ctx';
  m.innerHTML = `${title ? `<div class="ctx-t">${esc(title)}</div>` : ''}${buttons.join('')}`;
  document.body.appendChild(m);
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(e.clientX, innerWidth - r.width - 8) + 'px'; m.style.top = Math.min(e.clientY, innerHeight - r.height - 8) + 'px';
}
function badTaskButtons(gid, keys) {
  const k = esc(keys.join('\n'));
  return [`<button type="button" data-act="task-rerun" data-gid="${esc(gid)}" data-keys="${k}"><i>▶</i>立刻重跑</button>`,
    `<button type="button" data-act="mark-done" data-gid="${esc(gid)}" data-keys="${k}"><i>✓</i>标为已完成</button>`,
    `<button type="button" data-act="task-skip-many" data-gid="${esc(gid)}" data-keys="${k}"><i>⏭</i>跳过任务（今天不再跑）</button>`];
}
async function taskRerun(gid, keys) {
  if (!keys.length) return;
  try {
    const r = await api('POST', '/api/schedule/today/items', { game: gid, tasks: keys, when: { kind: 'now' } });
    toast(`${shortName(gid)}：${keys.length === 1 ? `「${tn(keys[0])}」` : `${keys.length} 项`}${r.batch?.paused ? '已排进队列，恢复调度后开始' : S.running?.running ? '已排进队列，前面的跑完接着跑' : '马上重跑'}`);
    S.fastUntil = Date.now() + 40000; pollRunning();
  } catch (e) { fail(e); }
}
async function taskSkipMany(gid, keys) {
  try {
    for (const key of keys) await api('POST', `/api/today/${encodeURIComponent(gid)}/skip`, { key, on: true });
    toast(`今天跳过：${keys.map(tn).join('、')}`);
    await loadState();
    if (S.route.view === 'home') renderHome(); else if (S.route.view === 'report') renderReport();
    else if (S.ed?.gid === gid) { const open = S.ed.open; await loadEditor(gid, S.ed.tab); S.ed.open = open; renderGame(); }
  } catch (e) { fail(e); }
}
document.addEventListener('contextmenu', e => {
  const row = e.target.closest?.('.b-row[data-gid]');  // 总览：这个游戏没做成的
  if (row) {
    const g = game(row.dataset.gid); const keys = ((repMap()[row.dataset.gid]?.attention) || g?.att || []).map(a => a.task);
    if (!keys.length) return;
    return showCtx(e, `${shortName(row.dataset.gid)} · 没做成的 ${keys.length} 项`, badTaskButtons(row.dataset.gid, keys));
  }
  const li = e.target.closest?.('.rg-list li[data-key]');  // 运行记录：单项
  if (li) return showCtx(e, tn(li.dataset.key), badTaskButtons(li.dataset.gid, [li.dataset.key]));
});

// 「⋯」按钮（11-02）：右键菜单不好找，行上放一个小按钮，点了打开同一个菜单
const MORE_SVG = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="3" cy="8" r="1.4"/><circle cx="8" cy="8" r="1.4"/><circle cx="13" cy="8" r="1.4"/></svg>';
const moreBtn = (title, target = '') => `<button type="button" class="more-btn" data-more="${esc(target)}" title="${esc(title)}" aria-label="${esc(title)}">${MORE_SVG}</button>`;
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-more]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const host = b.dataset.more ? (b.closest('section,div')?.querySelector(b.dataset.more) || document.querySelector(b.dataset.more)) : b;
  const r = b.getBoundingClientRect();
  // 晚一点再打开：这次点击本身会触发「点别处就关菜单」
  setTimeout(() => (host || b).dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: r.left, clientY: r.bottom + 4 })), 30);
}, true);
