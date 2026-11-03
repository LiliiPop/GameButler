// 日常管家界面 · 日程：今天（正在跑 / 接下来 / 跑过的）+ 各游戏的任务预设和它的定时 + 什么算闲时 + 睡眠和锁屏提醒。
// 和其它 static/js/*.js 共用全局（不打包，按 index.html 里的顺序加载）。
//
// 用户看到的只有两样：任务预设（跑什么）和它上面的定时（什么时候跑）；临时要跑的用「添加 · 只这一次」或「开始」。
// 后台：GET /api/schedule/today、PUT …/order、POST …/items（/{id}/skip|unskip|run-now|delete|save-as-routine）、
//       POST|PUT|DELETE /api/schedule/rules、GET /api/idle、PUT /api/settings/scheduler（idle_groups / wake_from_sleep）。

'use strict';

const SCH_STATE = { running: ['运行中', 'run'], done: ['完成', 'ok'], attention: ['要处理', 'bad'], ready: ['就绪', 'run'], waiting: ['等待', 'off'], skipped: ['今天跳过', 'off'], ran: ['已跑过', 'off'] };
const tzMin = () => -new Date().getTimezoneOffset();               // 电脑本地时区（分钟）
const hmToMin = hm => { const [h, m] = String(hm).split(':').map(Number); return h * 60 + m; };
const minToHm = v => { v = ((v % 1440) + 1440) % 1440; return `${String(Math.floor(v / 60)).padStart(2, '0')}:${String(v % 60).padStart(2, '0')}`; };
const localToBj = hm => minToHm(hmToMin(hm) + 480 - tzMin());
const bjToLocal = hm => minToHm(hmToMin(hm) - 480 + tzMin());
const sameTz = () => tzMin() === 480;
const hmBoth = bj => sameTz() ? bj : `${bjToLocal(bj)}（北京 ${bj}）`;   // 界面上：电脑时间在前，北京时间在后
const WEEK_MON = '一二三四五六日';  // 星期一 = 1（定时的「哪些天」）
function againText(a) {  // 任务预设上单个任务的「自动重复」
  if (!a) return '';
  if (a.every_hours) return `做完隔 ${a.every_hours} 小时再跑，最多 ${a.max_rounds || 2} 轮`;
  if (a.at?.length) return `到点再跑：${a.at.map(x => '本地 ' + bjToLocal(x)).join('、')}`;
  return '';
}
async function loadSchedule() {  // 日程 + 调度设置（设置都在 /api/settings）
  const [d, set] = await Promise.all([api('GET', '/api/schedule/today'), api('GET', '/api/settings')]);
  d.settings = set.scheduler;
  return d;
}

// ------------------------------------------------------------------ 页面
async function renderSchedule() {
  let d;
  try { d = await loadSchedule(); } catch (e) { $('#app').innerHTML = `<div class="glass skeleton">${esc(e.message)}</div>`; return; }
  if (S.route.view !== 'schedule') return;
  S.sch = d;
  const items = d.items || [];
  const left = items.filter(b => b.section !== 'done').length;
  const bad = items.filter(b => b.state === 'attention').length;
  const sec = k => items.map((b, i) => [b, i]).filter(([b]) => b.section === k);
  const run = sec('running'), next = sec('next'), done = sec('done');
  $('#app').innerHTML = `<div class="sch">
    <section class="hero">
      <div><span class="eyebrow num">${esc(dayEyebrow(d.day))}</span>
        <h1>日程</h1>
        <div class="small muted">已设置定时的任务序列会自动加入每日日程，也可手动添加任务到日程安排。</div></div>
      <div class="hero-side">
        <button class="btn" data-act="sch-settings">调度设置</button>
        ${S.running?.running ? '' : '<button class="btn dark" data-act="run-all">开始全部</button>'}
      </div>
    </section>
    ${d.scheduler === false ? `<div class="panel glass warnbar small">自动调度关着：只有「加入队列」的会跑，定时不会自己开始。<button class="btn xs" data-act="sch-on">开启自动调度</button></div>` : ''}
    ${powerWarnHtml(d.power || {}, d.routines || [])}
    ${dayTimelineHtml(d)}
    <div class="sch-wrap2">
      <section class="glass panel sch-today" aria-label="今天">
        <div class="ph"><h3>今天</h3><span class="xsmall faint num">${run.length ? `${run.length} 正在跑 · ` : ''}${next.length} 接下来 · ${done.length} 跑过</span></div>
        <div class="sch-th" aria-hidden="true"><span></span><span>任务序列</span><span>什么时候</span><span>状态</span><span></span></div>
        <h4 class="sch-seg">接下来${next.length > 1 ? ' <span>按住左边的 ⠿ 拖动改顺序：定时的以后每天也这样，临时加的只改今天</span>' : ''}</h4>
        <div class="sch-list" id="sch-next">${next.length ? withHours(next) : '<div class="xsmall faint sch-empty">今天没有要等的了</div>'}</div>
        <h4 class="sch-seg">跑过的</h4>
        <div class="sch-list">${done.length ? done.map(([b, i]) => itemRow(b, i)).join('') : '<div class="xsmall faint sch-empty">还没有</div>'}</div>
        <button type="button" class="add-line" data-act="sch-add">${ICON.plus}添加任务序列</button>
      </section>
    </div>
  </div>`;
  bindNextDrag();
  if (S.drawer) openDrawer(S.drawer, true);
}

function itemTitle(b) {
  const name = shortName(b.game);
  if (b.routine) return `${name} · ${b.routine}`;
  if (b.tasks?.length) return `${name} · 临时：${b.tasks.slice(0, 3).map(x => tn(x)).join('、')}${b.tasks.length > 3 ? ' 等' : ''}`;
  return `${name} · 今天的任务`;
}
// 「接下来」按预计开始的整点分段（批注 #168）：整点标题放在两个序列之间，不打断任务块；每项上不再写「预计几点开始」
function withHours(next) {
  let last = '';
  return next.map(([b, i]) => {
    const t = b.eta ? bjToLocal(b.eta) : '';
    const h = t ? t.slice(0, 2) + ':00' : '';
    const sep = h && h !== last ? `<div class="sch-hr" aria-hidden="true"><span class="num">${h}</span></div>` : '';
    if (h) last = h;
    return sep + itemRow(b, i, true);
  }).join('');
}
function itemRow(b, i, draggable = false) {
  const c = newsColor(b.game);
  const [label, cls] = SCH_STATE[b.state] || ['等待', 'off'];
  const live = b.section === 'running' && S.running?.running && S.running.current?.game === b.game;
  const src = b.kind === 'rule' ? `定时：${b.when_text}` : ['now', 'queue'].includes(b.when?.kind) ? '只跑这一次' : `只跑这一次 · ${b.when_text}`;
  const why = (b.section === 'next' || b.final) && b.why && !(S.sch?.scheduler === false && b.why.startsWith('自动调度关着')) ? b.why : '';
  const acts = [];
  if (live) acts.push(`<button class="btn xs warn" data-act="stop">${ICON.stop}停止</button>`);
  if (b.section === 'next') {
    acts.push(`<button class="btn xs" data-act="sch-now" data-id="${esc(b.id)}" title="不等条件，挪到接下来的第一个">${ICON.play}现在跑</button>`);
    acts.push(`<button class="btn xs ghost" data-act="sch-skip" data-id="${esc(b.id)}" data-on="1">今天跳过</button>`);
  }
  if (b.state === 'skipped') acts.push(`<button class="btn xs ghost" data-act="sch-skip" data-id="${esc(b.id)}" data-on="0">恢复</button>`);
  if (b.section === 'done' && b.bad?.length) acts.push(`<button class="btn xs" data-act="sch-rerun-bad" data-id="${esc(b.id)}">重跑失败项</button>`, `<button class="btn xs ghost" data-act="mark-done" data-gid="${esc(b.game)}" data-keys="${esc(b.bad.join('\n'))}" title="今天不再算失败，也不再自动重跑">标为已完成</button>`, `<a class="btn xs ghost" href="#/g/${esc(b.game)}/runs">看运行记录</a>`);
  if (b.kind === 'once' && b.tasks?.length && !b.routine) acts.push(`<button class="btn xs ghost" data-act="sch-save-routine" data-id="${esc(b.id)}">存为任务预设</button>`);
  if (b.kind === 'once' && b.section === 'next') acts.push(`<button class="btn xs ghost" data-act="sch-del" data-id="${esc(b.id)}" aria-label="删掉这一条">删掉</button>`);
  const R = S.running;
  const pct = live && b.keys?.length ? Math.round(b.done / b.keys.length * 100) : 0;
  const stText = live ? `运行中 · ${esc(tn(R.current.task) || '准备中')}${b.keys?.length ? ` · ${b.done + 1} / ${b.keys.length}` : ''}${R.current.since ? ` · 已 ${dur(nowBjMs() - bjMs(R.current.since))}` : ''}`
    : `${label}${b.state !== 'done' && b.keys?.length ? ` · ${b.done} / ${b.keys.length}` : ''}${b.last && b.section === 'done' ? ` · ${esc(bjToLocal(b.last))}` : ''}`;
  const when = b.kind === 'rule' ? whenShort(b) : b.when?.kind === 'now' ? '现在' : b.when?.kind === 'queue' ? '排队' : whenShort(b);
  const notes = [b.kind === 'once' ? '只跑这一次' : '', b.pc ? '电脑端' : '', b.est_minutes && b.section === 'next' ? `预计约 ${Math.round(b.est_minutes)} 分钟` : '',
    b.rerun ? '今天做过的也再跑' : ''].filter(Boolean).join(' · ');
  const row = `<div class="bcard sch-item${b.state === 'attention' ? ' warm' : ''}${live ? ' live' : ''}${b.state === 'skipped' ? ' off' : ''}${draggable ? ' sortable' : ''}" data-i="${i}" data-id="${esc(b.id)}" style="--gc:${c}">
    <span class="bc-no"><span class="bgrip" aria-hidden="true">${draggable ? ICON.grip : ''}</span></span>
    <span class="bc-name"><i class="b-bar"></i><a href="#/g/${esc(b.game)}/today" draggable="false" title="去改今天的任务：选项、跳过、再跑一次都只管今天（要以后都这样，去「任务预设」）">${esc(itemTitle(b))}</a></span>
    <span class="bc-when" title="${esc(src)}">${b.kind === 'rule' ? `<button type="button" class="linkbtn" data-act="rule-edit" data-id="${esc(b.id)}" title="改启动时间">${esc(when)}</button>` : esc(when)}</span>
    <div class="bc-st"><span class="pill ${cls}">${stText}</span>
      ${b.section === 'next' && b.eta_late ? '<div class="xsmall bwarn" title="按顺序和预计时长估的；赶时段的任务可能插队">可能赶不上它的时段</div>' : ''}${b.section === 'next' && !b.eta && b.eta_note ? `<div class="xsmall faint">${esc(b.eta_note)}</div>` : ''}
      ${notes ? `<div class="xsmall faint">${esc(notes)}</div>` : ''}
      ${!live && why ? (why.startsWith('工具没接好') ? `<a class="xsmall bwarn tool-fix" href="#/settings" title="去「设置 → 工具与游戏」改这个游戏的工具路径">${esc(why)} · 去改路径</a>`
        : `<div class="xsmall faint" title="${esc(why)}">${esc(why.startsWith('等闲时') ? '等闲时' : why)}</div>`) : ''}
      ${b.section === 'done' && b.bad?.length ? `<div class="xsmall bwarn">没做成：${esc(b.bad.map(tn).join('、'))}</div>` : ''}
      ${b.error ? `<div class="xsmall bwarn">${esc(b.error)}</div>` : ''}
      ${(b.warnings || []).map(w => `<div class="xsmall bwarn">${esc(w)}</div>`).join('')}
    </div>
    <div class="bacts">${acts.join('')}</div></div>`;
  return live ? `<div class="bc-live">${row}<div class="bc-prog" aria-hidden="true"><i style="width:${pct}%"></i></div></div>` : row;
}

function routinesHtml(list) {
  const games = list.filter(x => game(x.game)?.available !== false);
  if (!games.length) return '<div class="small faint">还没有挂游戏</div>';
  return games.map((x, gi) => `<div class="rt-game"><div class="rt-gh"><span class="avatar xs" style="background:${tint(game(x.game) || {}, gi)}">${esc(markOf(x.name))}</span><b>${esc(shortName(x.game))}</b></div>
    ${x.routines.length ? x.routines.map(r => `<div class="rt-row"><a href="#/g/${esc(x.game)}/routine" data-act="routine-open" data-gid="${esc(x.game)}" data-name="${esc(r.name)}" class="rt-name">${esc(r.name)}<span class="xsmall faint num"> · ${r.tasks} 项</span></a>
      <span class="rt-rules">${r.rules.map(u => `<button type="button" class="chip" data-act="rule-edit" data-id="${esc(u.id)}" title="点开改时间、哪些天">${esc(ruleChip(u))}</button>`).join('') || '<span class="xsmall faint">手动</span>'}
        <button type="button" class="linkbtn xsmall" data-act="rule-add" data-gid="${esc(x.game)}" data-name="${esc(r.name)}">＋ 定时</button></span></div>`).join('')
      : `<div class="xsmall faint rt-row">还没有任务预设：<a href="#/g/${esc(x.game)}/routine">去游戏页建一套</a></div>`}</div>`).join('');
}
// 定时的时间同时写本机和北京时间（同一时区时只写一个）
function bothHm(bj, bj2) {
  const loc = bjToLocal(bj) + (bj2 ? '–' + bjToLocal(bj2) : ''), b = bj + (bj2 ? '–' + bj2 : '');
  return sameTz() ? b : `本机 ${loc}（北京 ${b}）`;
}
function ruleChip(u) {
  const d = u.days === 'daily' ? '每天' : '每周' + u.days.map(n => WEEK_MON[n - 1]).join('');
  const w = u.when || {};
  const t = w.kind === 'queue' ? '加入队列' : w.kind === 'after_refresh' ? '刷新后马上' : w.kind === 'idle' ? `闲时${w.at ? ' · ' + bothHm(w.at) + ' 以后' : ''}` : bothHm(w.at, w.until);
  return `${d} ${t}`;
}

// ------------------------------------------------------------------ 睡眠和锁屏提醒
function powerWarns(p, routines) {
  const pcGames = routines.filter(x => x.pc && x.routines.some(r => r.rules.length)).map(x => shortName(x.game));
  const warn = [];
  if (p.wake_from_sleep && p.wake_timers === false) warn.push('Windows 没有允许唤醒定时器，管家叫不醒睡着的电脑。打开：控制面板 → 电源选项 → 更改计划设置 → 更改高级电源设置 → 睡眠 → 允许使用唤醒定时器 → 启用。');
  if (p.wake_error) warn.push(`设叫醒电脑失败：${p.wake_error}`);
  if (p.locked && pcGames.length) warn.push(`现在屏幕锁着：${pcGames.join('、')}要解锁后才会跑。`);
  return warn;
}
// 日程页上只留一行「要注意」，详细的在「调度设置」里
function powerWarnHtml(p, routines) {
  const w = p.supported ? powerWarns(p, routines) : [];
  return w.length ? `<section class="runline warm"><div class="rl-top"><div class="rl-l"><i class="tri"></i><b>睡眠和锁屏：${w.length} 项要注意</b><span class="rl-d">${esc(w[0].slice(0, 40))}${w[0].length > 40 ? '…' : ''}</span></div>
    <div class="rl-r"><button class="btn ghost" data-act="sch-settings">看调度设置</button></div></div></section>` : '';
}
function powerHtml(p, routines) {
  if (!p.supported) return '<div class="small faint">只在 Windows 上有</div>';
  const pcGames = routines.filter(x => x.pc && x.routines.some(r => r.rules.length)).map(x => shortName(x.game));
  const warn = [];
  if (p.wake_from_sleep && p.wake_timers === false) warn.push('Windows 没有允许唤醒定时器，管家叫不醒睡着的电脑。打开：控制面板 → 电源选项 → 更改计划设置 → 更改高级电源设置 → 睡眠 → 允许使用唤醒定时器 → 启用。');
  if (p.wake_error) warn.push(`设叫醒电脑失败：${p.wake_error}`);
  if (p.locked && pcGames.length) warn.push(`现在屏幕锁着：${pcGames.join('、')}要解锁后才会跑。`);
  const lines = [
    `电脑<b>睡着时什么都不会跑</b>（屏幕关掉没关系）。${p.wake_from_sleep ? `管家会在下一个定时前把电脑叫醒${p.next_wake ? `：下次 <span class="num">${esc(p.next_wake.slice(5))}</span>（北京时间）` : '（现在没有要叫醒的）'}。` : '「叫醒电脑」关着（调度设置里可以打开）。'}`,
    `能不能叫醒看 Windows：电源选项里要允许唤醒定时器${p.wake_timers === true ? '（现在：已允许）' : p.wake_timers === false ? '（现在：<b>没允许</b>）' : '（读不到这一项）'}；不少笔记本（现代待机）不理会唤醒定时器，最稳的是把「睡眠」设成「从不」，只让屏幕关掉${p.sleep_after_min ? `（现在 ${p.sleep_after_min} 分钟不用就睡眠）` : p.sleep_after_min === 0 ? '（现在：从不睡眠）' : ''}。`,
    `<b>锁着屏时电脑游戏跑不了</b>（脚本看不到窗口），会等解锁；模拟器上的游戏照跑。叫醒后通常是锁屏的${p.password_on_wake ? '：这台电脑唤醒时要密码，能接受的话可以在「设置 → 账户 → 登录选项」里关掉' : ''}。`,
  ];
  return `${warn.map(w => `<div class="small bwarn">${ICON.warn} ${esc(w)}</div>`).join('')}
    <ul class="small muted sch-power-l">${lines.map(l => `<li>${l}</li>`).join('')}</ul>`;
}

// ------------------------------------------------------------------ 什么算闲时
function condText(c) {
  return c.kind === 'input_idle' ? `键鼠不动 ≥ ${c.minutes} 分钟` : `${bjToLocal(c.from)}–${bjToLocal(c.to)}${sameTz() ? '' : `（北京 ${c.from}–${c.to}）`}`;
}
// 「什么算闲时」的编辑器：放进一个盒子里（调度设置弹窗、加定时弹窗里直接改，不再嵌一层弹窗）
function mountIdleEditor(box, groups) {
  const gs = JSON.parse(JSON.stringify(groups || []));
  const condRow = (c, gi, ci) => c.kind === 'input_idle'
    ? `<div class="cond"><b>键鼠不动</b> 至少 <input class="inp xs num" type="number" min="1" max="600" data-g="${gi}" data-c="${ci}" data-f="minutes" value="${c.minutes}" style="width:72px"> 分钟
        <button type="button" class="btn icon xs ghost" data-del="${gi}:${ci}" aria-label="删掉这个条件">${ICON.x}</button></div>`
    : `<div class="cond"><b>时段</b> <input class="inp xs num" type="time" data-g="${gi}" data-c="${ci}" data-f="from" value="${bjToLocal(c.from)}"> 到 <input class="inp xs num" type="time" data-g="${gi}" data-c="${ci}" data-f="to" value="${bjToLocal(c.to)}">
        <span class="xsmall faint">本地时间${sameTz() ? '' : `（北京 ${c.from}–${c.to}）`}，可跨零点</span>
        <button type="button" class="btn icon xs ghost" data-del="${gi}:${ci}" aria-label="删掉这个条件">${ICON.x}</button></div>`;
  const html = () => `<div class="small muted">用「键鼠不动」和「时段」自己搭：一组里的要<b>同时满足</b>；有好几组时<b>满足任意一组</b>就算闲时。所有定时里的「闲时」共用这一份。</div>
    ${gs.map((g, gi) => `${gi ? '<div class="idle-or">或</div>' : ''}<div class="idle-edit-g"><div class="small"><b>第 ${gi + 1} 组</b></div>
      ${g.map((c, ci) => (ci ? '<div class="xsmall muted" style="padding-left:10px">且</div>' : '') + condRow(c, gi, ci)).join('')}
      ${g.length < 2 ? `<button type="button" class="btn xs ghost" data-addc="${gi}">＋ 叠加「${g[0]?.kind === 'time' ? '键鼠不动' : '时段'}」</button>` : ''}</div>`).join('') || '<div class="small faint">一组都没有。</div>'}
    <div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" class="btn sm ghost" data-addg="input_idle">＋ 加一组：键鼠不动</button><button type="button" class="btn sm ghost" data-addg="time">＋ 加一组：时段</button></div>`;
  const fresh = k => k === 'time' ? { kind: 'time', from: localToBj('01:00'), to: localToBj('07:00') } : { kind: 'input_idle', minutes: 30 };
  box.classList.add('idle-ed'); box.innerHTML = html();
  let dirty = false;
  box.addEventListener('input', e => { const t = e.target; if (t.dataset.f === undefined) return; const c = gs[+t.dataset.g][+t.dataset.c]; dirty = true;
    if (t.dataset.f === 'minutes') c.minutes = +t.value; else if (t.value) c[t.dataset.f] = localToBj(t.value); });
  box.addEventListener('click', e => {
    const d = e.target.closest('[data-del]'), a = e.target.closest('[data-addc]'), g = e.target.closest('[data-addg]');
    if (d) { const [gi, ci] = d.dataset.del.split(':').map(Number); gs[gi].splice(ci, 1); if (!gs[gi].length) gs.splice(gi, 1); }
    else if (a) { const gi = +a.dataset.addc; gs[gi].push(fresh(gs[gi][0]?.kind === 'time' ? 'input_idle' : 'time')); }
    else if (g) gs.push([fresh(g.dataset.addg)]);
    else return;
    dirty = true; box.innerHTML = html();
  });
  return { get: () => gs, dirty: () => dirty };
}
// ------------------------------------------------------------------ 调度设置（补跑、叫醒电脑）
async function openSchSettings() {
  const st = S.sch?.settings || (await api('GET', '/api/settings')).scheduler;
  const d = S.sch || {};
  const on = d.scheduler !== false;
  const v = await modal({ title: '调度设置', wide: true, ok: '保存', body: `<div class="sch-idle">
    <div class="lrow"><div class="nm"><b>自动调度</b><div>管家开着时，按各任务预设上的定时自动跑日常。电脑游戏到点时你在用电脑会先问你；锁屏时等解锁。</div></div>
      <label class="small nowrap"><input type="checkbox" id="sch-on" ${on ? 'checked' : ''}> 打开</label></div>
    <div class="lrow"><div class="nm"><b>卡死处理</b><div>${STUCK_TEXT}</div></div>
      <label class="small nowrap"><input type="checkbox" id="sch-stuck" ${st.stuck_restart ? 'checked' : ''}> 打开</label></div>
    <div class="lrow"><div class="nm"><b>卡住以后</b><div>画面 10 分钟没变化算卡住（卡死处理开着时）；超过每项最长时间也算</div></div>
      <span class="set-ctl"><select class="sel" id="sch-stuck-act"><option value="restart" ${st.stuck_action !== 'skip' ? 'selected' : ''}>重启游戏，再试这一项</option><option value="skip" ${st.stuck_action === 'skip' ? 'selected' : ''}>不再试，直接跑下一项</option></select></span></div>
    <div class="lrow"><div class="nm"><b>失败后当场再试</b><div>一项没做成，马上再试几次</div></div>
      <span class="set-ctl"><select class="sel" id="sch-try">${[0, 1, 2, 3].map(n => `<option value="${n}" ${(st.task_retries ?? 1) === n ? 'selected' : ''}>${n ? `再试 ${n} 次` : '不再试'}</option>`).join('')}</select></span></div>
    <div class="lrow"><div class="nm"><b>每项最长时间</b><div>卡死处理关着时用：一项跑超过这么久就停下（开着时看画面，只留 90 分钟兜底）</div></div>
      <span class="set-ctl"><input class="inp num" type="number" min="5" max="180" id="sch-max" value="${st.task_max_minutes ?? 20}" style="width:80px"> 分钟</span></div>
    <div class="lrow"><div class="nm"><b>之后自动补跑</b><div>当场没做成的，隔一段时间再自动跑一轮</div></div>
      <span class="nowrap set-ctl"><select class="sel" id="sch-retries">${[0, 1, 2, 3].map(n => `<option value="${n}" ${st.fail_retries === n ? 'selected' : ''}>${n ? `补跑 ${n} 次` : '不补跑'}</option>`).join('')}</select>
      间隔 <input class="inp num" type="number" min="10" max="600" id="sch-gap" value="${st.retry_gap_minutes}" style="width:80px"> 分钟</span></div>
    <div class="lrow"><div class="nm"><b>叫醒电脑</b><div>电脑睡着时，在下一个定时前把它叫醒：模拟器游戏照跑，电脑游戏等解锁。</div></div>
      <label class="small"><input type="checkbox" id="sch-wake" ${st.wake_from_sleep ? 'checked' : ''}> 打开</label></div>
    <div class="lrow"><div class="nm"><b>刷新后马上</b><div>定时选「刷新后马上」时，刷新后过多少分钟开始</div></div>
      <span><input class="inp num" type="number" min="0" max="240" id="sch-delay" value="${st.start_delay_minutes}" style="width:80px"> 分钟</span></div>
    <section class="sch-set-sec" aria-label="什么算闲时"><div class="ph"><h3>什么算闲时</h3>${(d.idle || {}).why || (d.idle || {}).ok ? `<span class="xsmall ${d.idle.ok ? '' : 'faint'}"><span class="dot ${d.idle.ok ? 'live' : ''}"></span> 现在：${d.idle.ok ? '是闲时' : esc(d.idle.why || '不是闲时')}</span>` : ''}</div>
      <div id="set-idle"></div></section>
    <section class="sch-set-sec" aria-label="睡眠和锁屏"><div class="ph"><h3>睡眠和锁屏</h3><span class="xsmall faint">电脑睡着、锁屏时会怎样</span></div>${powerHtml(d.power || {}, d.routines || [])}</section>
  </div>`, onMount: (m, setVal) => {
    const ed = mountIdleEditor($('#set-idle', m), st.idle_groups);  // 闲时直接在这里改（10-30 #136），和别的设置一起保存
    setVal(() => ({ fail_retries: +$('#sch-retries', m).value, retry_gap_minutes: +$('#sch-gap', m).value, wake_from_sleep: $('#sch-wake', m).checked, stuck_restart: $('#sch-stuck', m).checked, stuck_asked: true, start_delay_minutes: +$('#sch-delay', m).value,
      stuck_action: $('#sch-stuck-act', m).value, task_retries: +$('#sch-try', m).value, task_max_minutes: +$('#sch-max', m).value, _on: $('#sch-on', m).checked,
      ...(ed.dirty() ? { idle_groups: ed.get() } : {}) }));
  } });
  if (!v || v === true) return;
  const wantOn = v._on; delete v._on;
  try {
    await api('PUT', '/api/settings/scheduler', v);
    if (wantOn !== on) await api('POST', `/api/scheduler/${wantOn ? 'on' : 'off'}`);
    if (S.sch?.settings && v.idle_groups) S.sch.settings.idle_groups = v.idle_groups; toast('调度设置已保存'); if (S.route.view === 'schedule') renderSchedule();
  } catch (e) { fail(e); }
}

// ------------------------------------------------------------------ 定时（挂在任务预设上）
function whenEditor(w, opts = {}) {  // 什么时候：时间段 / 闲时 / 刷新后马上开始（加一条一次性的时还有「现在」）
  const gs = S.sch?.settings?.idle_groups || [];
  const k = w.kind || (opts.now ? 'queue' : 'at');
  const t = x => x ? bjToLocal(x) : '';
  return `<div class="be-start">
    ${opts.now || opts.queue ? `<label class="rad"><input type="radio" name="we-kind" value="queue" ${k === 'queue' || k === 'now' ? 'checked' : ''}> <b>加入队列</b> <span class="xsmall faint">${opts.now ? '排在今天的队尾，前面的轮完才开始；里面只在某个时段跑的任务到了时段先跑，不等前面的。选「以后也这样」= 每天都排进队列' : '每天排进队列：前面的都轮完就跑；里面只在某个时段跑的任务（例如领体力 · 午间）到了时段先跑，不等前面的'}</span></label>` : ''}
    <label class="rad nowrap"><input type="radio" name="we-kind" value="at" ${k === 'at' ? 'checked' : ''}> <b>定时</b> <input class="inp xs num t-short" type="time" id="we-at" value="${t(w.at) || '06:00'}"> 到 <input class="inp xs num t-short" type="time" id="we-until" value="${t(w.until)}"> <span class="xsmall faint">本地时间；默认截止到日常刷新时间</span></label>
    <label class="rad"><input type="radio" name="we-kind" value="idle" ${k === 'idle' ? 'checked' : ''}> <b>闲时</b>
      <span class="xsmall faint">满足「什么算闲时」就跑 · 最早 <input class="inp xs num t-short" type="time" id="we-iat" value="${k === 'idle' ? t(w.at) : ''}"> 起</span></label>
    ${opts.idleEdit ? `<div class="we-idle xsmall faint">什么算闲时：${gs.length ? esc(gs.map(g => g.map(condText).join(' 且 ')).join('；或 ')) : '还没设，在日程页「调度设置」里设'}</div>` : ''}
    ${opts.now ? '' : `<label class="rad"><input type="radio" name="we-kind" value="after_refresh" ${k === 'after_refresh' ? 'checked' : ''}> <b>刷新后马上开始</b> <span class="xsmall faint">日常刷新后立即启动</span></label>`}
  </div>`;
}
function readWhen(m) {
  const k = (m.querySelector('input[name="we-kind"]:checked') || {}).value || 'at';
  if (k === 'now' || k === 'queue' || k === 'after_refresh') return { kind: k };
  if (k === 'idle') { const a = $('#we-iat', m)?.value; return { kind: 'idle', at: a ? localToBj(a) : '' }; }
  const u = $('#we-until', m).value;
  return { kind: 'at', at: localToBj($('#we-at', m).value || '06:00'), until: u ? localToBj(u) : '' };
}
function daysEditor(days) {
  const daily = days === 'daily' || !days;
  const set = new Set(daily ? [] : days);
  return `<div class="be-days"><label class="rad"><input type="radio" name="wd" value="daily" ${daily ? 'checked' : ''}> 每天</label>
    <label class="rad"><input type="radio" name="wd" value="week" ${daily ? '' : 'checked'}> 每周 ${[1, 2, 3, 4, 5, 6, 7].map(n => `<label class="chk"><input type="checkbox" data-wd="${n}" ${set.has(n) ? 'checked' : ''}> ${WEEK_MON[n - 1]}</label>`).join('')}</label></div>`;
}
// 批注 #180 / #193（11-03）：「每天」和「每周几」不能同时选：勾了星期几自动换成「每周」；选「每天」清掉星期几。
// 可以先点「每周」再勾哪几天；「每周」一天都没勾时不能保存（弹窗的「确定」里拦）
document.addEventListener('change', e => {
  const box = e.target.closest?.('.be-days'); if (!box) return;
  const daily = box.querySelector('input[name="wd"][value="daily"]'), week = box.querySelector('input[name="wd"][value="week"]');
  const days = [...box.querySelectorAll('[data-wd]')];
  if (e.target.matches('[data-wd]')) { if (days.some(x => x.checked)) week.checked = true; }
  else if (e.target === daily && daily.checked) days.forEach(x => { x.checked = false; });
});
function readDays(m) {
  if ((m.querySelector('input[name="wd"]:checked') || {}).value !== 'week') return 'daily';
  return $$('[data-wd]', m).filter(x => x.checked).map(x => +x.dataset.wd);
}
async function editRule(id, gid, routine) {
  if (id || !S.sch?.settings) { try { S.sch = await loadSchedule(); } catch (e) { return fail(e); } }  // 游戏页、任务预设页上点开时日程数据可能是旧的
  const all = (S.sch?.routines || []).flatMap(x => x.routines.flatMap(r => r.rules));
  let old = id ? all.find(r => r.id === id) : null;
  if (id && !old) {  // 列表里没有（例如那个游戏暂时没接好）：从今天的条目里拿
    const it = (S.sch?.items || []).find(x => x.id === id && x.kind === 'rule');
    if (it) old = { id, game: it.game, routine: it.routine, when: it.when, days: it.days };
  }
  const r = old ? JSON.parse(JSON.stringify(old)) : { game: gid, routine, when: { kind: 'at', at: localToBj('06:00') }, days: 'daily' };
  const v = await modal({ title: `${old ? '改定时' : '加定时'} · ${shortName(r.game)} · ${r.routine}`, wide: true, ok: '保存', alt: old ? '删除这个定时' : '', body: `<div class="bedit">
    <div class="field-row"><b>什么时候</b>${whenEditor(r.when, { idleEdit: true, queue: true })}</div>
    <div class="field-row"><b>哪些天</b>${daysEditor(r.days)}</div>
    </div>`,
    onMount: (m, setVal) => { setVal(() => ({ when: readWhen(m), days: readDays(m) })); } });
  try {
    if (v?.alt && old) {
      if (!(await confirmBox('删除这个定时？', `${esc(r.routine)} · ${esc(ruleChip(r))}。任务预设不受影响。`, '删除', true))) return;
      await api('DELETE', `/api/schedule/rules/${encodeURIComponent(old.id)}`); toast('已删除定时');
    } else if (v && v !== true) {
      if (old) await api('PUT', `/api/schedule/rules/${encodeURIComponent(old.id)}`, v);
      else await api('POST', '/api/schedule/rules', { game: r.game, routine: r.routine, ...v });
      toast(old ? '定时已保存' : `已给「${r.routine}」加上定时`);
    } else return;
  } catch (e) { return fail(e); }
  if (S.route.view === 'schedule') renderSchedule(); else if (S.route.view === 'presets') renderPresets(); else if (S.ed?.gid) { await loadEditor(S.ed.gid, S.ed.tab); renderGame(); }
}

// ------------------------------------------------------------------ 添加：四步
async function addFlow(gid0) {
  if (!S.sch) { try { S.sch = await loadSchedule(); } catch (e) { return fail(e); } }
  const games = (S.state?.games || []).filter(g => g.available);
  if (!games.length) return toast('还没有挂游戏', true);
  const st = { game: gid0 || games[0].id, what: 'routine', routine: '', tasks: new Set(), when: { kind: 'queue' }, repeat: 'once', name: '', days: 'daily' };
  let routines = [], lib = [];
  const load = async () => {
    try {
      const [r, sc] = await Promise.all([api('GET', `/api/routines/${encodeURIComponent(st.game)}`), schema(st.game)]);
      routines = Object.keys(r.routines || {});
      lib = (sc.tasks || []).filter(t => !t.placeholder && !t.disabled).map(t => t.name);
    } catch (e) { routines = []; lib = []; failRead('任务预设')(e); }
    if (!routines.includes(st.routine)) st.routine = routines[0] || '';
    if (!routines.length) st.what = 'tasks';
  };
  await load();
  // 四步像一叠卡片：正在填的那张在最前面，后面几张只露出右边一条，填好的露出左边一条；点露出来的边切换（10-28 批注 #99）
  // 在游戏页里加（gid0）：只针对这个游戏，没有「选择游戏」这一步
  const fixed = !!gid0;
  const keys = fixed ? ['what', 'when', 'rep'] : ['game', 'what', 'when', 'rep'];
  let focus = 0;
  const tmpOf = () => st.what === 'tasks';
  const nowOf = () => st.when.kind === 'now' || st.when.kind === 'queue';
  const short = {
    game: () => shortName(st.game),
    what: () => tmpOf() ? (st.tasks.size ? `单项任务 ${st.tasks.size} 项` : '单项任务') : (st.routine || '—'),
    when: () => nowOf() ? '加入队列' : st.when.kind === 'idle' ? '闲时' : st.when.kind === 'after_refresh' ? '刷新后' : (st.when.at ? bjToLocal(st.when.at) : ''),
    rep: () => st.repeat === 'daily' && st.when.kind !== 'now' ? '以后也这样' : '只这一次',
  };
  const title = { game: '选择游戏', what: '跑什么', when: '什么时候', rep: '只这一次？' };
  const body = {
    game: () => `<div class="as-list">${games.map((g, i) => `<label class="as-opt${g.id === st.game ? ' on' : ''}"><input type="radio" name="af-game" value="${esc(g.id)}" ${g.id === st.game ? 'checked' : ''}><span class="avatar xs" style="background:${tint(g, i)}">${esc(markOf(g.name))}</span>${esc(splitName(g.name)[0])}</label>`).join('')}</div>`,
    what: () => { const tmp = tmpOf(); return `<div class="seg" role="group"><button type="button" class="${tmp ? '' : 'on'}" data-af-what="routine" ${routines.length ? '' : 'disabled'}>任务预设</button><button type="button" class="${tmp ? 'on' : ''}" data-af-what="tasks">单项任务</button></div>
      <div class="as-list">${tmp ? (lib.map(n => `<label class="as-opt${st.tasks.has(n) ? ' on' : ''}"><input type="checkbox" data-af-task="${esc(n)}" ${st.tasks.has(n) ? 'checked' : ''}> ${esc(tn(n))}</label>`).join('') || '<span class="xsmall faint">这个游戏没有可选的任务</span>')
        : routines.map(n => `<label class="as-opt${n === st.routine ? ' on' : ''}"><input type="radio" name="af-rt" value="${esc(n)}" ${n === st.routine ? 'checked' : ''}> ${esc(n)}</label>`).join('')}</div>
      <div class="xsmall faint">${tmp ? '选项用这个任务在任务预设里的设置，没有就用工具默认。挑好了点「下一步」。' : routines.length ? '' : '这个游戏还没有任务预设。'}</div>`; },
    when: () => whenEditor(st.when, { now: true }) + (isPC(game(st.game)) ? '<div class="xsmall faint">电脑游戏选「加入队列」会先问你能不能让出电脑；锁屏时要等解锁。</div>' : ''),
    rep: () => { const now = st.when.kind === 'now', tmp = tmpOf(); return `<label class="as-opt${st.repeat === 'once' ? ' on' : ''}"><input type="radio" name="af-rep" value="once" ${st.repeat === 'once' ? 'checked' : ''}> <span><b>只这一次</b><div class="xsmall faint">今天跑完就没了</div></span></label>
      <label class="as-opt${st.repeat === 'daily' ? ' on' : ''}${now ? ' off' : ''}"><input type="radio" name="af-rep" value="daily" ${st.repeat === 'daily' ? 'checked' : ''} ${now ? 'disabled' : ''}> <span><b>以后也这样</b><div class="xsmall faint">${now ? '选「现在」只能只这一次' : tmp ? '存成新任务预设，并把这个时间设成它的定时' : '加入日常列表'}</div></span></label>
      ${st.repeat === 'daily' && !now ? `${tmp ? `<label class="fld xsmall">任务预设名字 <input class="inp" id="af-name" value="${esc(st.name || [...st.tasks].map(tn).slice(0, 2).join(' + '))}"></label>` : ''}${daysEditor(st.days)}` : ''}`; },
  };
  const html = () => `<div class="af-deck" style="--n:${keys.length}">${keys.map((k, i) => {
    const pos = i < focus ? 'before' : i === focus ? 'focus' : 'after';
    return `<section class="add-step af-card ${pos}" data-af-card="${i}" style="--i:${i};z-index:${10 - Math.abs(i - focus)}">
      <button type="button" class="af-tab" data-af-focus="${i}" tabindex="${pos === 'focus' ? -1 : 0}" aria-label="第 ${i + 1} 步：${title[k]}"><span class="as-n">${i < focus ? '✓' : i + 1}</span><span class="af-tt">${title[k]}</span><span class="af-ts">${esc(short[k]())}</span></button>
      <div class="af-in"><div class="as-h"><span class="as-n">${i + 1}</span><b>${title[k]}</b></div>${body[k]()}
        ${i > 0 || i < keys.length - 1 ? `<div class="af-next">${i > 0 ? '<button type="button" class="btn sm ghost" data-af-prev>上一步</button>' : ''}${i < keys.length - 1 ? '<button type="button" class="btn sm" data-af-next>下一步</button>' : ''}</div>` : ''}</div></section>`;
  }).join('')}</div>`;
  const v = await modal({ title: fixed ? `添加任务 · ${shortName(gid0)}` : '添加任务序列', wide: true, ok: '保存', body: `<div id="af">${html()}</div>`, onMount: (m, setVal) => {
    const box = $('#af', m);
    // 弹窗大小按第一张卡片定下来，之后每一步都一样大（10-30 #124）；内容多的那张在卡片里滚动
    let deckH = 0;
    const fit = () => requestAnimationFrame(() => { const d = $('.af-deck', box), c = $('.af-card.focus .af-in', box); if (!d || !c) return; if (!deckH) deckH = c.scrollHeight + 2; d.style.height = deckH + 'px'; });
    // 换卡片时有动效（10-31）：每张卡从原来的位置滑到新位置，新的那张内容淡入
    const re = () => {
      const was = new Map($$('.af-card', box).map(c => [c.dataset.afCard, c.getBoundingClientRect().left]));
      const wasFocus = $('.af-card.focus', box)?.dataset.afCard;
      box.innerHTML = html(); fit();
      $$('.af-card', box).forEach(c => {
        const d = (was.get(c.dataset.afCard) ?? c.getBoundingClientRect().left) - c.getBoundingClientRect().left;
        if (d) c.animate([{ transform: `translateX(${d}px)` }, { transform: 'none' }], { duration: 260, easing: 'cubic-bezier(.2,.7,.3,1)' });
      });
      const f = $('.af-card.focus .af-in', box);
      if (f && wasFocus !== $('.af-card.focus', box)?.dataset.afCard) f.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 220, delay: 60, fill: 'backwards' });
    };
    const go = i => { focus = Math.max(0, Math.min(keys.length - 1, i)); re(); };
    const next = () => go(focus + 1);
    fit();
    m.addEventListener('change', async e => {
      const t = e.target;
      if (t.name === 'af-game') { st.game = t.value; st.tasks = new Set(); st.routine = ''; st.what = 'routine'; await load(); return next(); }  // 单选：选好就到下一张
      if (t.name === 'af-rt') { st.routine = t.value; return next(); }
      if (t.dataset.afTask) { if (t.checked) st.tasks.add(t.dataset.afTask); else st.tasks.delete(t.dataset.afTask); return re(); }  // 多选：点「下一步」再走
      if (t.name === 'we-kind' || t.id?.startsWith('we-')) { st.when = readWhen(m); if (st.when.kind === 'now') { st.repeat = 'once'; return next(); } if (nowOf()) return next(); return re(); }
      if (t.name === 'af-rep') { st.repeat = t.value; return re(); }
      if (t.name === 'wd' || t.dataset.wd) { st.days = readDays(m); return; }
    });
    m.addEventListener('input', e => { if (e.target.id === 'af-name') st.name = e.target.value; });
    let again = false;  // 点的是已经选中的那一项：不会触发 change，也要到下一张
    m.addEventListener('pointerdown', e => { const i = e.target.closest('label.as-opt')?.querySelector('input[name="af-game"],input[name="af-rt"]'); again = !!i?.checked; });
    m.addEventListener('click', e => {
      if (again && e.target.closest('label.as-opt')) { again = false; return next(); }
      const w = e.target.closest('[data-af-what]'); if (w && !w.disabled) { st.what = w.dataset.afWhat; return re(); }
      if (e.target.closest('[data-af-next]')) return next();
      if (e.target.closest('[data-af-prev]')) return go(focus - 1);
      const f = e.target.closest('[data-af-focus]'); if (f) return go(+f.dataset.afFocus);
      const c = e.target.closest('.af-card:not(.focus)'); if (c) return go(+c.dataset.afCard);
    });
    setVal(() => ({ ...st, tasks: [...st.tasks], when: $('input[name="we-kind"]', m) ? readWhen(m) : st.when, days: $('input[name="wd"]', m) ? readDays(m) : st.days, name: ($('#af-name', m)?.value || st.name || '').trim() }));
  } });
  if (!v || v === true) return;
  const tmp = v.what === 'tasks';
  if (tmp && !v.tasks.length) return toast('还没选任务', true);
  if (!tmp && !v.routine) return toast('还没选任务预设', true);
  try {
    if (v.repeat === 'daily' && v.when.kind !== 'now') {
      if (tmp) {  // 存成新任务预设并加定时：先加一条一次性的，再存为任务预设（选项按任务预设的规则取好），然后删掉那条一次性的
        if (!v.name) return toast('要给新的任务预设起个名字', true);
        const b = (await api('POST', '/api/schedule/today/items', { game: v.game, tasks: v.tasks, when: v.when })).batch;
        await api('POST', `/api/schedule/today/items/${encodeURIComponent(b.id)}/save-as-routine`, { name: v.name, when: v.when, days: v.days });
        await api('POST', `/api/schedule/today/items/${encodeURIComponent(b.id)}/delete`);
        toast(`已存成任务预设「${v.name}」并加上定时`);
      } else {
        await api('POST', '/api/schedule/rules', { game: v.game, routine: v.routine, when: v.when, days: v.days });
        toast(`已给「${v.routine}」加上定时`);
      }
    } else if (v.when.kind === 'queue') {  // 加入队列：排在队尾，前面的轮完才开始（10-31）
      const r = await api('POST', '/api/schedule/today/items', { game: v.game, routine: tmp ? '' : v.routine, tasks: tmp ? v.tasks : [], when: { kind: 'queue' } });
      toast(r.batch?.merged ? '同一套已经排着：并进去了' : '已加到今天的队尾：前面的轮完就开始');
    } else {
      await api('POST', '/api/schedule/today/items', { game: v.game, routine: tmp ? '' : v.routine, tasks: tmp ? v.tasks : [], when: v.when });
      toast('已加到今天：只跑这一次');
    }
  } catch (e) { return fail(e); }
  await loadState();
  if (S.route.view === 'schedule') renderSchedule();
}

// ------------------------------------------------------------------ 今天：拖动顺序和各个操作
function bindNextDrag() {}  // 拖动改顺序：见下面的 pointerSort（按住行首的编号 / ⠿ 拖）
pointerSort({ box: '#sch-next', item: '.bcard.sortable', handle: '.bcard.sortable .bc-no', onDrop: async (el, to, before) => {
  const from = el.dataset.id, tid = to.dataset.id; if (!from || from === tid) return;
  const ids = S.sch.items.map(b => b.id); ids.splice(ids.indexOf(from), 1); ids.splice(ids.indexOf(tid) + (before ? 0 : 1), 0, from);
  try {
    await api('PUT', '/api/schedule/today/order', { ids });
    // 11-02：定时生成的条目，拖完的先后以后每天也这样（存进定时的顺序）；临时加的只改今天
    const kind = Object.fromEntries(S.sch.items.map(b => [b.id, b.kind]));
    const ruleIds = ids.filter(i => kind[i] === 'rule');
    const allRules = (S.sch.routines || []).flatMap(x => x.routines.flatMap(r => r.rules.map(u => u.id)));
    const moved = kind[from] === 'rule';
    if (moved) await api('PUT', '/api/schedule/rules-order', { ids: [...ruleIds, ...allRules.filter(i => !ruleIds.includes(i))] });
    toast(moved ? '顺序已改：以后每天也按这个先后' : '今天的顺序已改（临时加的只在今天）'); renderSchedule();
  } catch (x) { fail(x); }
} });
async function scheduleAct(act, el) {
  const d = S.sch; if (!d) return;
  const b = el?.dataset?.id ? d.items.find(x => x.id === el.dataset.id) : null;
  const op = async (what, body, msg) => { try { await api('POST', `/api/schedule/today/items/${encodeURIComponent(el.dataset.id)}/${what}`, body); if (msg) toast(msg); await loadState(); renderSchedule(); pollRunning(); } catch (e) { fail(e); } };
  if (act === 'sch-add') return addFlow();
  if (act === 'sch-now') return op('run-now', {}, '已挪到接下来的第一个');
  if (act === 'sch-skip') return op(el.dataset.on === '1' ? 'skip' : 'unskip', {}, el.dataset.on === '1' ? '今天跳过' : '已恢复');
  if (act === 'sch-del') { if (await confirmBox('删掉这一条？', esc(itemTitle(b)), '删掉', true)) op('delete', {}, '已删掉'); return; }
  if (act === 'sch-rerun-bad') return op('rerun-bad', { keys: b.bad }, '已放回「接下来」最前面：只重跑没做成的');
  if (act === 'sch-save-routine') {
    const v = await modal({ title: '存为任务预设', wide: true, ok: '保存', body: `<div class="bedit"><label class="field-row"><b>名字</b><input class="inp" id="sr-name" value="${esc(b.tasks.map(tn).slice(0, 2).join(' + '))}"></label>
      <div class="field-row"><b>以后也跑</b><div><label class="chk"><input type="checkbox" id="sr-rule"> 加上定时</label>${whenEditor({ kind: 'at', at: localToBj('06:00') })}${daysEditor('daily')}</div></div></div>`,
      onMount: (m, setVal) => setVal(() => ({ name: $('#sr-name', m).value.trim(), ...($('#sr-rule', m).checked ? { when: readWhen(m), days: readDays(m) } : {}) })) });
    if (v && v !== true) op('save-as-routine', v, `已存为任务预设「${v.name}」`);
    return;
  }
  if (act === 'sch-on') { try { await schedulerOn(); toast('自动调度已开启'); renderSchedule(); } catch (e) { fail(e); } }
}

// 右侧抽屉：这个游戏今天的计划和状态；改任务预设 / 任务选项等去完整设置页
async function openDrawer(gid, keep) {
  const g = game(gid); if (!g) return;
  S.drawer = gid;
  let box = $('#drawer');
  if (!box) { box = document.createElement('aside'); box.id = 'drawer'; box.className = 'drawer glass'; document.body.appendChild(box); }
  if (!keep) box.innerHTML = '<div class="small faint" style="padding:20px">读取中…</div>';
  box.hidden = false;
  $$('.sg').forEach(x => x.classList.toggle('on', x.dataset.gid === gid));
  let p = { tasks: [], status: {} };
  try { p = await api('GET', `/api/today/${encodeURIComponent(gid)}`); } catch (e) { failRead('今天的任务')(e); return; }
  if (S.drawer !== gid) return;
  const tasks = p.tasks || [];
  const cur = S.running?.running && S.running.current?.game === gid ? S.running.current.task : '';
  const rows = tasks.map(t => {
    const key = t.key || t.task; const r = p.status?.[key];
    const res = key === cur ? ['运行中', 'run'] : r ? (RES[r.result] || [r.result, 'off']) : ['未运行', 'off'];
    return `<li class="${key === cur ? 'live' : ''}"><span class="pill ${res[1]}">${res[0]}</span><b>${esc(tn(key))}</b>${r?.time ? `<span class="xsmall faint num">${esc(r.time)}</span>` : ''}
      ${r?.detail && res[1] === 'bad' ? `<div class="xsmall bwarn">${esc(why(r.detail))}</div>` : ''}</li>`;
  }).join('');
  box.innerHTML = `<div class="dr-h" style="--gc:${tint(g, (S.state.games || []).indexOf(g))}">
      <div><div class="xsmall faint">游戏日 ${esc(dayLabel(g.today))} · ${esc(toolName(g))}</div><h3>${esc(splitName(g.name)[0])}</h3></div>
      <button class="btn icon xs ghost" data-act="drawer-close" aria-label="关闭">${ICON.x}</button></div>
    <div class="dr-acts">
      ${g.running ? `<button class="btn sm warn" data-act="stop">${ICON.stop}中止队列</button>` : `<button class="btn sm dark" data-act="run" data-gid="${esc(gid)}">${ICON.play}开始今天的任务</button>`}
      ${canPick(g) && !g.running ? `<button class="btn sm" data-act="today-add" data-gid="${esc(gid)}">单项任务</button>` : ''}
      <button class="btn sm" data-act="sch-add-game" data-gid="${esc(gid)}">添加…</button>
      <a class="btn sm ghost" href="#/g/${esc(gid)}/routine">完整设置 →</a></div>
    <div class="dr-sec"><div class="small muted">今天的任务 · ${g.done || 0}/${g.total || 0}</div>
      <ol class="dr-tasks">${rows || '<li class="small faint">今天没有任务：给一套任务预设加上定时，或点「添加」</li>'}</ol></div>
    <div class="dr-sec" id="dr-res"></div>
    <div class="dr-sec xsmall faint">任务预设和它的定时、任务选项、运行记录、任务库都在「完整设置」里。${' · <button class="linkbtn" data-act="mount-edit-open" data-gid="' + esc(gid) + '">名字和刷新时间</button>'} · <button class="linkbtn" data-act="mount-remove" data-gid="${esc(gid)}">卸掉这个游戏</button></div>`;
  loadDrawerRes(gid);
}
// 抽卡资源（读数）+ 抽卡记录：抽屉里的一块
async function loadDrawerRes(gid) {
  const box = $('#dr-res'); if (!box) return;
  let d; try { d = await api('GET', `/api/readings/${encodeURIComponent(gid)}`); } catch (e) { box.innerHTML = unreadHtml('资源读数', e); return; }
  if (S.drawer !== gid) return;
  S.res = { gid, d };
  const vals = Object.entries(d.values || {});
  const pools = d.gacha?.pools || [];
  box.innerHTML = `<div class="small muted dr-rh"><span>抽卡资源${d.at ? ` · ${esc(d.at.slice(5))} 读到${d.stale ? '（数据较旧）' : ''}` : ''}</span>
      <span><button class="linkbtn" data-act="res-add" data-gid="${esc(gid)}">记一笔</button> · <button class="linkbtn" data-act="res-defs" data-gid="${esc(gid)}">资源项</button></span></div>
    ${vals.length ? `<div class="res-nums">${d.pulls != null ? `<div class="res-big"><b class="num">${Math.floor(d.pulls)}</b><span>折合抽数</span></div>` : ''}
      ${d.standard_pulls != null ? `<div><b class="num">${Math.floor(d.standard_pulls)}</b><span>常驻池折合</span></div>` : ''}
      ${vals.map(([k, v]) => `<div><b class="num">${v.toLocaleString()}</b><span>${esc(k)}</span></div>`).join('')}</div>
      ${resChart(d.series || [])}` : `<div class="xsmall faint">还没有读数：点「记一笔」手动填${(d.defs || []).length ? '' : '（先在「资源项」里写上这个游戏的抽卡货币和单抽价格）'}。</div>`}
    <div class="small muted dr-rh" style="margin-top:6px"><span>抽卡记录${d.gacha?.total ? ` · ${d.gacha.total} 抽${d.gacha.uid ? ' · UID ' + esc(d.gacha.uid) : ''}` : ''}</span>
      <span><button class="linkbtn" data-act="gacha-import" data-gid="${esc(gid)}">导入 JSON</button></span></div>
    ${pools.map(p => `<div class="pity"><b>${esc(p.pool)}</b><span class="num">${p.hard ? `距保底 <b>${Math.max(0, p.hard - p.since)}</b>（已垫 ${p.since}/${p.hard}）` : `已垫 ${p.since}`}</span>
      <span class="xsmall faint">共 ${p.total} 抽${p.avg ? ` · 平均 ${p.avg} 抽出 ${p.top_rank} 星` : ''}</span>
      ${p.stars.length ? `<div class="xsmall muted pity-s">${p.stars.slice(0, 6).map(x => `${esc(x.name)}<span class="faint">（${x.pulls}）</span>`).join('、')}</div>` : ''}</div>`).join('') || '<div class="xsmall faint">还没导入。原神 / 星铁用抽卡记录工具导出的 UIGF / SRGF 文件；其他游戏用管家的格式（导入时可以下载模板）。</div>'}`;
}
function resChart(series) {
  const pts = series.filter(x => x.pulls != null || Object.keys(x.values || {}).length);
  if (pts.length < 2) return '';
  const val = x => x.pulls != null ? x.pulls : Object.values(x.values)[0];
  const ys = pts.map(val); const lo = Math.min(...ys), hi = Math.max(...ys); const span = hi - lo || 1;
  const W = 380, H = 70;
  const xy = pts.map((p, i) => [Math.round(i / (pts.length - 1) * (W - 8) + 4), Math.round(H - 6 - (val(p) - lo) / span * (H - 16))]);
  return `<svg class="res-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="抽卡资源增长曲线"><polyline points="${xy.map(p => p.join(',')).join(' ')}" fill="none" stroke="var(--blue)" stroke-width="2" stroke-linejoin="round"/>
    ${xy.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="2.5" fill="var(--blue)"><title>${esc(pts[i].day)}：${Math.round(val(pts[i]))}</title></circle>`).join('')}
    <text x="4" y="10" font-size="10" fill="var(--faint)">${Math.round(hi)}</text><text x="4" y="${H - 1}" font-size="10" fill="var(--faint)">${esc(pts[0].day.slice(5))}</text><text x="${W - 4}" y="${H - 1}" font-size="10" fill="var(--faint)" text-anchor="end">${esc(pts[pts.length - 1].day.slice(5))}</text></svg>`;
}
async function resAdd(gid) {
  const d = S.res?.gid === gid ? S.res.d : await api('GET', `/api/readings/${encodeURIComponent(gid)}`);
  const keys = (d.defs || []).map(x => x.key);
  const row = (k, v) => `<label class="fld">${esc(k)} <input class="inp num" data-k="${esc(k)}" inputmode="numeric" value="${v ?? ''}"></label>`;
  const v = await modal({ title: '记一笔：现在有多少', ok: '保存', body: `<div class="add-form">${keys.map(k => row(k, d.values?.[k])).join('') || ''}
      <label class="fld">其他资源（可空） <span style="display:flex;gap:6px"><input class="inp" id="ra-k" placeholder="名字"><input class="inp num" id="ra-v" placeholder="数量"></span></label></div>`,
    onMount: (m, setVal) => setVal(() => { const o = {}; m.querySelectorAll('[data-k]').forEach(i => { if (i.value.trim()) o[i.dataset.k] = i.value.trim(); }); const k = $('#ra-k', m).value.trim(); if (k && $('#ra-v', m).value.trim()) o[k] = $('#ra-v', m).value.trim(); return o; }) });
  if (!v || v === true || !Object.keys(v).length) return;
  try { await api('POST', `/api/readings/${encodeURIComponent(gid)}`, { values: v }); toast('已记下'); await loadState(); loadDrawerRes(gid); } catch (e) { fail(e); }
}
async function resDefs(gid) {
  const d = S.res?.gid === gid ? S.res.d : await api('GET', `/api/readings/${encodeURIComponent(gid)}`);
  const row = (x = {}) => `<div class="def-row"><input class="inp" data-f="key" placeholder="资源名（如 原石）" value="${esc(x.key || '')}"><input class="inp num" data-f="per_pull" placeholder="多少个 = 1 抽" value="${x.per_pull ?? ''}">
    <label class="xsmall"><input type="checkbox" data-f="standard" ${x.standard ? 'checked' : ''}> 常驻池用</label></div>`;
  const v = await modal({ title: '这个游戏记哪些抽卡资源', ok: '保存', wide: true, body: `<div class="add-form"><div class="xsmall faint">「多少个 = 1 抽」：货币填单抽价格（原神原石 160），抽卡券填 1；空着的只记数量、不算进折合抽数。勾「常驻池用」的单独算。</div>
      <div id="defs">${(d.defs || []).map(row).join('') || row()}</div><button type="button" class="btn xs ghost" id="def-add">＋ 再加一项</button></div>`,
    onMount: (m, setVal) => { $('#def-add', m).onclick = () => $('#defs', m).insertAdjacentHTML('beforeend', row()); setVal(() => [...m.querySelectorAll('.def-row')].map(r => ({ key: r.querySelector('[data-f=key]').value.trim(), per_pull: r.querySelector('[data-f=per_pull]').value.trim(), standard: r.querySelector('[data-f=standard]').checked }))); } });
  if (!v || v === true) return;
  try { await api('PUT', `/api/readings/${encodeURIComponent(gid)}/defs`, { defs: v }); toast('已保存'); await loadState(); loadDrawerRes(gid); } catch (e) { fail(e); }
}
async function gachaImport(gid) {
  const inp = document.createElement('input'); inp.type = 'file'; inp.accept = '.json,application/json';
  inp.onchange = async () => {
    const f = inp.files[0]; if (!f) return;
    let doc; try { doc = JSON.parse(await f.text()); } catch (e) { return toast('文件不是有效的 JSON', true); }
    try {
      const pre = await api('POST', `/api/gacha/${encodeURIComponent(gid)}/import`, { doc, dry: true });
      if (!pre.new) return toast(`文件里的 ${pre.file_records} 条都已经导入过了`);
      if (!await confirmBox('导入抽卡记录', `<div class="small">${esc(f.name)}：${pre.file_records} 条，其中 <b>${pre.new}</b> 条是新的${pre.uid ? `（UID ${esc(pre.uid)}）` : ''}。</div>`, '导入')) return;
      const r = await api('POST', `/api/gacha/${encodeURIComponent(gid)}/import`, { doc });
      toast(`已导入 ${r.new} 条`); await loadState(); loadDrawerRes(gid);
    } catch (e) {
      if (/认不出格式/.test(e.message) && await confirmBox('认不出这个文件', `<div class="small">${esc(e.message)}</div><div class="small" style="margin-top:6px">要下载管家格式的模板吗？</div>`, '下载模板')) {
        const t = await api('GET', '/api/gacha/template'); t.game = gid;
        const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(t, null, 1)], { type: 'application/json' })); a.download = `抽卡记录模板-${gid}.json`; a.click();
      } else fail(e);
    }
  };
  inp.click();
}
function closeDrawer() { S.drawer = null; const b = $('#drawer'); if (b) b.hidden = true; $$('.sg').forEach(x => x.classList.remove('on')); }

// ------------------------------------------------------------------ 任务预设（顶栏，10-28）：所有游戏的任务预设和它们的定时
// 任务预设页（11-01 改成看板）：每个游戏一列、每套预设一张卡片。从上到下按时间排：闲时的在最上，定时的按时间，没有定时的最后。
// 卡片上只露出前 5 个任务，鼠标放在卡片上可以用滚轮看完；图标按钮：加入队列 / 编辑预设 / 复制预设；每列最后是「新建预设」
const PR_ICON = {
  queue: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 5h10M3 10h10M3 15h6M14 12.5l3.5 2.5-3.5 2.5z"/></svg>',
  edit: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 16l1-4 8.5-8.5 3 3L8 15z M12 5l3 3"/></svg>',
  copy: '<svg viewBox="0 0 20 20" aria-hidden="true"><rect x="7" y="7" width="9" height="10" rx="1.5"/><path d="M4 13V4.5A1.5 1.5 0 0 1 5.5 3H12"/></svg>',
  plus: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 4v12M4 10h12"/></svg>',
  del: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10M9 9v5M11 9v5"/></svg>',
};
function presetSortKey(rules, gid) {  // 闲时 0；定时按本地时刻（刷新后马上 = 刷新时刻）；没有定时排最后
  if (!rules.length) return [2, 0];
  const ks = rules.map(u => { const w = u.when || {};
    if (w.kind === 'idle') return [0, w.at ? hmMin(bjToLocal(w.at)) : 0];
    return [1, hmMin(bjToLocal(['after_refresh', 'queue'].includes(w.kind) ? (game(gid)?.refresh || '04:00') : (w.at || '00:00')))]; });
  ks.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  return ks[0];
}
const hmMin = t => { const [h, m] = String(t || '0:0').split(':').map(Number); return (h || 0) * 60 + (m || 0); };
async function renderPresets() {
  let d;
  try { d = await loadSchedule(); } catch (e) { $('#app').innerHTML = `<div class="glass skeleton">${esc(e.message)}</div>`; return; }
  if (S.route.view !== 'presets') return;
  S.sch = d;
  const games = (d.routines || []).filter(x => game(x.game)?.available !== false);
  const docs = {};
  await Promise.all(games.map(async x => { try { docs[x.game] = (await api('GET', `/api/routines/${encodeURIComponent(x.game)}`)).routines || {}; } catch (e) { docs[x.game] = {}; } }));
  if (S.route.view !== 'presets') return;
  S.presetDocs = docs;
  const card = (x, r) => {
    const tasks = (docs[x.game][r.name]?.tasks || []).map(t => t.key || t.task).filter(k => k !== game(x.game)?.recovery_task);
    const gw = game(x.game)?.windows || {};  // 批注 #195（11-03）：有运行时段的任务也要这套有定时才会进每天的日程
    const hasWin = (docs[x.game][r.name]?.tasks || []).some(t => gw[t.key || t.task] || gw[t.task]);
    const when = r.rules.length ? r.rules.map(u => `<button type="button" class="pk-when" data-act="rule-edit" data-id="${esc(u.id)}" title="点开改定时">${esc(ruleChip(u))}</button>`).join('')
      : `<button type="button" class="pk-when none" data-act="rule-add" data-gid="${esc(x.game)}" data-name="${esc(r.name)}" title="点这里加定时">没有定时：手动跑</button>`;
    return `<article class="pk-card" data-gid="${esc(x.game)}" data-name="${esc(r.name)}">
      <div class="pk-h"><b>${esc(r.name)}</b><span class="num faint xsmall">${tasks.length} 项</span></div>
      <div class="pk-whens">${when}</div>
      ${!r.rules.length && hasWin ? '<div class="pk-hint xsmall">里面有只在某个时段跑的任务，但这套没有定时，不会自动跑：加一个「每天」的定时（时间随意，例如加入队列），这些任务会等到自己的时段再跑</div>' : ''}
      <ol class="pk-tasks" tabindex="0" aria-label="任务（滚轮看全部）">${tasks.map(k => `<li>${esc(tn(k))}</li>`).join('') || '<li class="faint">还没有任务</li>'}</ol>
      ${tasks.length > 5 ? `<div class="pk-more xsmall faint">还有 ${tasks.length - 5} 项</div>` : ''}
      <div class="pk-acts">
        <button type="button" class="pk-ic" data-act="pk-queue" data-gid="${esc(x.game)}" data-name="${esc(r.name)}" data-tip="加入队列：排在今天的队尾" aria-label="加入队列">${PR_ICON.queue}</button>
        <button type="button" class="pk-ic" data-act="routine-open" data-gid="${esc(x.game)}" data-name="${esc(r.name)}" data-tip="编辑预设：改任务和选项" aria-label="编辑预设">${PR_ICON.edit}</button>
        <button type="button" class="pk-ic" data-act="pk-copy" data-gid="${esc(x.game)}" data-name="${esc(r.name)}" data-tip="复制预设：另存一份再改" aria-label="复制预设">${PR_ICON.copy}</button>
        <button type="button" class="pk-ic pk-del" data-act="pk-del" data-gid="${esc(x.game)}" data-name="${esc(r.name)}" data-tip="删除预设（挂在它上面的定时一起删）" aria-label="删除预设">${PR_ICON.del}</button>
      </div></article>`;
  };
  $('#app').innerHTML = `<div class="sch">
    <section class="hero">
      <div><span class="eyebrow num">${esc(dayEyebrow(d.day))}</span><h1>任务预设</h1>
        <div class="small muted">一套预设 = 一次跑哪些任务。每列从上到下：闲时跑的、按时间定时的、没有定时的</div></div>
    </section>
    <div class="pk-board">${games.map((x, gi) => {
      const rs = [...x.routines].sort((a, b) => { const ka = presetSortKey(a.rules, x.game), kb = presetSortKey(b.rules, x.game); return ka[0] - kb[0] || ka[1] - kb[1]; });
      return `<section class="pk-col" data-gid="${esc(x.game)}" style="--gc:${tint(game(x.game) || {}, gi)}" aria-label="${esc(shortName(x.game))}">
        <div class="pk-gh"><i class="b-bar"></i><b>${esc(shortName(x.game))}</b><span class="num faint xsmall">${rs.length} 套</span></div>
        ${rs.map(r => card(x, r)).join('')}
        <button type="button" class="pk-card pk-new" data-act="pk-new" data-gid="${esc(x.game)}">${PR_ICON.plus}<span>新建预设</span></button>
      </section>`;
    }).join('') || '<div class="b-empty">还没有挂游戏</div>'}</div>
  </div>`;
  // 批注 #196（11-03）：重画 / 新建预设回来后不弹回最左边：接着上次的位置；刚新建过预设的那个游戏那一列一定露出来
  const bd = $('.pk-board');
  if (bd) {
    bd.scrollLeft = S.pkScroll || 0;
    const col = S.pkFocus && bd.querySelector(`.pk-col[data-gid="${CSS.escape(S.pkFocus)}"]`);
    if (col) {
      const l = col.getBoundingClientRect().left - bd.getBoundingClientRect().left + bd.scrollLeft, r = l + col.offsetWidth;
      if (l < bd.scrollLeft || r > bd.scrollLeft + bd.clientWidth) bd.scrollLeft = Math.max(0, l - 24);
    }
    S.pkFocus = '';
    bd.addEventListener('scroll', () => { S.pkScroll = bd.scrollLeft; }, { passive: true });
  }
}
// 批注 #173（11-03）：看板在空白处（列与列之间、卡片下面）按住左右拖动，鼠标是小手
(() => {
  let pan = null;
  document.addEventListener('pointerdown', e => {
    const b = e.target.closest?.('.pk-board');
    if (!b || e.button !== 0 || e.target.closest('.pk-card,button,a,input,select,textarea')) return;
    pan = { b, x0: e.clientX, s0: b.scrollLeft }; b.classList.add('panning'); e.preventDefault();
  });
  document.addEventListener('pointermove', e => { if (pan) pan.b.scrollLeft = pan.s0 - (e.clientX - pan.x0); });
  const end = () => { if (pan) { pan.b.classList.remove('panning'); pan = null; } };
  document.addEventListener('pointerup', end); document.addEventListener('pointercancel', end); window.addEventListener('blur', end);
})();
async function presetAct(act, el) {
  const gid = el.dataset.gid, name = el.dataset.name;
  try {
    if (act === 'pk-queue') {
      const r = await api('POST', '/api/schedule/today/items', { game: gid, routine: name, tasks: [], when: { kind: 'queue' } });
      toast(r.batch?.merged ? `「${name}」今天已经排着：并在一起了` : `「${name}」已加进今天的队尾`);
      return;
    }
    const doc = (await api('GET', `/api/routines/${encodeURIComponent(gid)}`)).routines || {};
    if (act === 'pk-copy') {
      let n = `${name} 副本`; let i = 2; while (doc[n]) n = `${name} 副本 ${i++}`;
      n = await modal({ title: `复制「${name}」`, input: { label: '新预设的名字', value: n }, ok: '复制' });
      if (!n) return;
      if (doc[n]) return toast('这个名字已经有了', true);
      doc[n] = { tasks: clone(doc[name]?.tasks || []), ...(doc[name]?.again ? { again: clone(doc[name].again) } : {}) };
      await api('PUT', `/api/routines/${encodeURIComponent(gid)}`, { routines: doc });
      toast(`已复制为「${n}」（定时没有一起复制）`); return renderPresets();
    }
    if (act === 'pk-del') {
      const n = (S.sch?.routines || []).find(x => x.game === gid)?.routines.find(r => r.name === name)?.rules.length || 0;
      if (!(await confirmBox(`删除任务预设「${esc(name)}」？`, `删除后不能恢复。${n ? `挂在它上面的 ${n} 个定时也会一起删掉。` : ''}`, '删除', true))) return;
      delete doc[name];
      const r = await api('PUT', `/api/routines/${encodeURIComponent(gid)}`, { routines: doc });
      toast(`已删除「${name}」${r.removed_rules ? `（它的 ${r.removed_rules} 个定时也删了）` : ''}`); await loadState(); return renderPresets();
    }
    if (act === 'pk-new') {
      // 批注 #191（11-03）：从头开始（只有启动游戏），或从工具自带的预设新建（MAA 的预设 / MFA 实例 / 工具默认勾选；BetterGI 一条龙）
      let tr = []; try { tr = (await api('GET', `/api/games/${encodeURIComponent(gid)}/tool-routines`)).routines || []; } catch (e) { tr = []; }
      const tool = game(gid)?.kind === 'bettergi' ? 'BetterGI' : 'MAA';
      const v = await modal({ title: `新建预设 · ${shortName(gid)}`, ok: '建好去加任务', body: `<div class="bedit">
        ${tr.length ? `<div class="field-row"><b>从哪开始</b><div class="be-start">
          <label class="rad"><input type="radio" name="pn-src" value="" checked> 从头开始 <span class="xsmall faint">只有启动游戏，自己加任务</span></label>
          <label class="rad"><input type="radio" name="pn-src" value="tool"> 从 ${tool} 预设新建 <select class="sel" id="pn-tool" style="width:auto;max-width:260px">${tr.map((x, i) => `<option value="${i}">${esc(x.name)}（${x.count} 项）</option>`).join('')}</select></label>
        </div></div>` : ''}
        <label class="field-row"><b>名字</b><input class="inp" id="pn-name" placeholder="例如：周末" style="max-width:none"></label></div>`,
        onMount: (m, setVal) => {
          const nameEl = $('#pn-name', m), sel = $('#pn-tool', m); let auto = '';
          const pickTool = () => { const r = m.querySelector('input[name="pn-src"][value="tool"]'); if (r) r.checked = true; const nm = tr[+sel.value]?.name || ''; if (!nameEl.value.trim() || nameEl.value === auto) { nameEl.value = auto = nm; } };
          if (sel) { sel.addEventListener('change', pickTool); sel.addEventListener('focus', pickTool); }
          m.querySelectorAll('input[name="pn-src"]').forEach(r => r.addEventListener('change', () => { if (r.value === 'tool' && r.checked) pickTool(); else if (nameEl.value === auto) { nameEl.value = auto = ''; } }));
          setTimeout(() => nameEl.focus(), 50);
          setVal(() => ({ name: nameEl.value.trim(), src: (m.querySelector('input[name="pn-src"]:checked') || {}).value === 'tool' ? tr[+sel.value]?.name : '' }));
        } });
      if (!v || v === true) return;
      const n = v.name; if (!n) return toast('要写个名字', true);
      if (doc[n]) return toast('这个名字已经有了', true);
      S.pkFocus = gid;
      if (v.src) {
        await api('POST', `/api/games/${encodeURIComponent(gid)}/import-routines`, { names: [v.src], as: n });
      } else {
        const rec = game(gid)?.recovery_task;
        doc[n] = { tasks: rec ? [{ task: rec, choices: {} }] : [] };
        await api('PUT', `/api/routines/${encodeURIComponent(gid)}`, { routines: doc });
      }
      if (S.route?.view === 'game' && S.ed?.gid === gid && location.hash === `#/g/${gid}/routine`) {  // 已经在这个游戏的任务预设页（批注 #178）
        S.ed.routineName = n; await loadState(); await loadEditor(gid, 'routine'); renderGame(); toast(`已新建「${n}」：点「修改预设」加任务`);
      } else { S.pendingRoutine = n; location.hash = `#/g/${gid}/routine`; }
    }
  } catch (e) { fail(e); }
}

// ------------------------------------------------------------------ 定时一览（11-01）：今天的时间轴，在「今天」列表上面，可以收起
// 横轴是今天的日程日（北京 04:00 → 次日 04:00），刻度写电脑本地时间；每个游戏一行：
// 实心块 = 定时的时段，虚线块 = 闲时等着的时段，细条 = 只在某个时段跑的任务，圆点 = 今天开跑的时间，竖线 = 现在
const tlOpen = () => { try { return localStorage.getItem('gb-tl') !== '0'; } catch (e) { return true; } };
function dayTimelineHtml(d) {
  const pos = hm => { const m = hmToMin(hm); return ((m - 240 + 1440) % 1440) / 14.4; };
  const span = (a, b) => { const x = pos(a); let y = b ? pos(b) : 100; if (y <= x) y = 100; return [x, y - x]; };
  // 钟点时段（闲时、任务的运行时段）跨过日程日的起点（北京 04:00）时拆成两段
  const spans = (a, b) => { const x = pos(a), y = pos(b); return y > x ? [[x, y - x]] : [[x, 100 - x], [0, y]].filter(v => v[1] > 0); };
  const items = (d.items || []).filter(b => b.game);
  const gids = [...new Set(items.map(b => b.game))];
  const now = new Date(nowBjMs() + 8 * 3600e3); const nowHm = `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}`;
  const ticks = Array.from({ length: 13 }, (_, i) => minToHm(240 + i * 120));
  const idleGroups = S.sch?.settings?.idle_groups || d.settings?.idle_groups || [];
  const idleBands = idleGroups.map(g => g.find(c => c.kind === 'time')).filter(Boolean);
  const row = gid => {
    const g = game(gid) || {}; const c = newsColor(gid);
    const blocks = items.filter(b => b.game === gid).map(b => {
      const st = b.start || {};
      const label = `${itemTitle(b)} · ${b.when_text || ''}`;
      if (st.mode === 'window') {
        const [x, w] = span(st.from || g.refresh || '04:00', st.to || g.refresh);
        const cls = `tl-blk${st.idle ? ' idle' : ''}${b.section === 'done' ? ' done' : ''}`;
        // 等闲时的：只画在「什么算闲时」的时段里（有一组只看键鼠不动、不限时段的，就是整段）（11-02）
        const segs = st.idle && idleGroups.length && idleGroups.every(gr => gr.some(c => c.kind === 'time'))
          ? idleBands.flatMap(c => spans(c.from, c.to).flatMap(([bx, bw]) => { const a = Math.max(x, bx), e = Math.min(x + w, bx + bw); return e > a ? [[a, e - a]] : []; }))
          : [[x, w]];
        return segs.map(([a, l]) => `<i class="${cls}" style="left:${a}%;width:${l}%" title="${esc(label)}"></i>`).join('');
      }
      return '';
    }).join('');
    const wins = Object.entries(g.windows || {}).flatMap(([k, v]) => String(v).split(/[,，]/).map(seg => { const [a, b] = seg.split('-').map(s => s.trim()); if (!a || !b) return '';
      return spans(a, b).map(([x, w]) => `<i class="tl-win" style="left:${x}%;width:${w}%" title="${esc(tn(k))}：只在 ${esc(bjToLocal(a))}–${esc(bjToLocal(b))}"></i>`).join(''); })).join('');
    const dots = items.filter(b => b.game === gid && (b.last || b.ran)).map(b => { const t = b.last || (b.ran || '').slice(11, 16); return t ? `<i class="tl-dot${b.state === 'attention' ? ' bad' : ''}" style="left:${pos(t)}%" title="${esc(itemTitle(b))} · ${esc(bjToLocal(t))} 跑过"></i>` : ''; }).join('');
    return `<div class="tl-row" style="--gc:${c}"><span class="tl-name">${esc(shortName(gid))}</span><div class="tl-track">${blocks}${wins}${dots}</div></div>`;
  };
  const open = tlOpen();
  return `<section class="tl-day${open ? ' open' : ''}" aria-label="定时一览">
    <button type="button" class="tl-head" data-act="tl-toggle" aria-expanded="${open}"><h3>定时一览</h3><span class="xsmall faint">今天什么时候会自动跑 · 时间为电脑本地时间</span>${ICON.chev}</button>
    ${open ? `<div class="tl-body">
      <div class="tl-row tl-axis"><span class="tl-name"></span><div class="tl-track">${ticks.map((t, i) => `<span style="left:${i * 100 / 12}%">${esc(bjToLocal(t))}</span>`).join('')}</div></div>
      ${idleBands.length ? `<div class="tl-row tl-idle"><span class="tl-name">闲时</span><div class="tl-track">${idleBands.flatMap(c => spans(c.from, c.to).map(([x, w]) => `<i style="left:${x}%;width:${w}%" title="闲时时段 ${esc(bjToLocal(c.from))}–${esc(bjToLocal(c.to))}（还要键鼠不动够久）"></i>`)).join('')}</div></div>` : ''}
      ${gids.map(row).join('') || '<div class="xsmall faint">今天没有定时</div>'}
      <div class="tl-now" style="left:calc(var(--tl-name) + (100% - var(--tl-name)) * ${pos(nowHm) / 100})" title="现在 ${esc(bjToLocal(nowHm))}"></div>
      <div class="tl-legend xsmall faint"><span><i class="tl-blk"></i>定时时段</span><span><i class="tl-blk idle"></i>等闲时</span><span><i class="tl-win"></i>只在这个时段跑的任务</span><span><i class="tl-dot"></i>开跑</span></div>
    </div>` : ''}
  </section>`;
}
document.addEventListener('click', e => {
  if (!e.target.closest?.('[data-act="tl-toggle"]')) return;
  try { localStorage.setItem('gb-tl', tlOpen() ? '0' : '1'); } catch (x) { /* 不记也行 */ }
  if (S.route.view === 'schedule') renderSchedule();
});
