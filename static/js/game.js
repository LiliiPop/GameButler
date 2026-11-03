// 日常管家界面 · 游戏页：今天的进度、任务预设编辑（和它的定时）、运行记录、任务库、高级、编辑操作。和其它 static/js/*.js 共用全局（不打包，按 index.html 里的顺序加载）。

'use strict';

// ------------------------------------------------------------------ 游戏页
const TABS = [['today', '今日任务'], ['routine', '任务预设'], ['runs', '运行记录'], ['advanced', '高级']];  // 11-01：去掉「任务库」（任务默认都能用，跑哪些由任务预设定）

async function openGame(gid, tab) {
  const g = game(gid);
  if (!g) { $('#app').innerHTML = `<div class="glass skeleton">没有这个游戏：${esc(gid)}</div>`; return; }
  if (!g.available) { $('#app').innerHTML = `<div class="glass skeleton">${esc(g.name)}：${esc(g.message || '待接入')}</div>`; return; }
  const same = S.ed && S.ed.gid === gid && S.ed.tab === tab;
  if (!same) {
    $('#app').innerHTML = `<div class="gpage">${gameShell(g, tab)}<div class="glass skeleton">加载中…</div></div>`;
    try {
      await switches(gid);
      if (tab === 'today' || tab === 'routine') await loadEditor(gid, tab);
      else { S.ed = { gid, tab }; S.ed.routines = await api('GET', `/api/routines/${encodeURIComponent(gid)}`).catch(e => { failRead('任务预设')(e); return null; }); }
      prefetchNav(gid);
    } catch (e) { $('#app').innerHTML = gameShell(g, tab) + `<div class="glass skeleton">${esc(e.message)}</div>`; return; }
  }
  renderGame();
}

async function prefetchNav(gid) {
  try {
    S.runsCache[gid] = S.runsCache[gid] || await api('GET', `/api/runs/${encodeURIComponent(gid)}`);
    if (S.ed?.gid === gid) { const a = $('#aside'); if (a) a.innerHTML = asideHtml(game(gid)); }
  } catch (e) { failRead('运行记录')(e); }
}

function gameShell(g, tab) {
  const i = S.state.games.indexOf(g);
  const [main, sub] = splitName(g.name);
  const running = S.running?.running;
  return `<section class="ghero">
    <div class="id">
      <button type="button" class="btn icon sm ghost" data-act="go-back" aria-label="后退" title="回到上一页">${ICON.back}</button>
      <div class="avatar lg" style="background:${tint(g, i)};box-shadow:0 10px 24px -10px ${tint(g, i)},0 1px 0 rgba(var(--paper-rgb),.45) inset">${esc(markOf(g.name))}</div>
      <div><h1>${esc(main)}</h1><div class="small muted">${esc([sub, isPC(g) ? ((KIND[g.kind] || g.kind) !== sub ? (KIND[g.kind] || g.kind) + ' · ' : '') + '电脑端' : '', g.emulator ? `模拟器「${g.emulator}」` : '', `每日 ${g.refresh} 刷新`].filter(Boolean).join(' · '))}</div></div>
    </div>
    <div class="acts">
      ${g.running ? `${S.running?.can_suspend ? `<button class="btn" data-act="suspend" data-on="${S.running.suspended ? '0' : '1'}" title="按 BetterGI 自己的暂停键，停在原地；队列不动">${S.running.suspended ? '继续' : '原地暂停'}</button>` : ''}<button class="btn warn" data-act="stop" title="停下当前任务，整个队列（排着的、定时的）都先不跑">${ICON.stop}中止队列</button>` : tab === 'runs' ? `
        ${g.can_open ? `<button class="btn" data-act="open-tool" data-gid="${esc(g.id)}" title="打开这个游戏用的脚本工具（${esc(toolName(g))}）">打开 ${esc(toolName(g))}</button>` : ''}
        ${g.can_launch ? `<button class="btn" data-act="launch-game" data-gid="${esc(g.id)}" title="只开模拟器和游戏，不跑任务：方便手动改游戏设置或 MAA 设置">用模拟器启动游戏</button>` : ''}
        <button class="btn dark" data-act="run" data-gid="${esc(g.id)}" title="${running ? '正在运行别的游戏：排在队列最后' : '排进今天的队列，马上开始'}">${ICON.play}开始</button>` : `
        ${g.can_open ? `<button class="btn" data-act="open-tool" data-gid="${esc(g.id)}" title="打开这个游戏用的脚本工具（${esc(toolName(g))}）">打开 ${esc(toolName(g))}</button>` : ''}
        ${canPick(g) ? `<button class="btn" data-act="today-add" data-gid="${esc(g.id)}" title="从这个游戏能做的任务里挑几项：加入队列或立即开始">单项任务</button>` : ''}
        <button class="btn dark" data-act="run" data-gid="${esc(g.id)}" title="${running ? '正在运行别的游戏：排在队列最后' : '排进今天的队列，马上开始'}">${ICON.play}开始</button>`}
    </div>
  </section>${(S.schemas?.[g.id]?.warnings || []).map(w => `<div class="notice-line">${ICON.warn}<span>${esc(w)}</span></div>`).join('')}`;
}

async function loadEditor(gid, tab) {
  const g = game(gid);
  const routines = await api('GET', `/api/routines/${encodeURIComponent(gid)}`);
  const ed = { gid, tab, routines, filter: '', open: new Set() };
  if (tab === 'routine') {
    const prev = S.ed?.gid === gid ? S.ed.routineName : null;
    ed.routineName = prev && routines.routines[prev] ? prev : (Object.keys(routines.routines)[0] || '');
    ed.tasks = clone(routines.routines[ed.routineName]?.tasks || []);
    ed.again = clone(routines.routines[ed.routineName]?.again || {});
    ed.status = {};
  } else {  // 今天：只看——今天各条里的任务和状态（改跑什么去任务预设，改什么时候去日程）
    ed.day = g.today;
    const r = await api('GET', `/api/today/${encodeURIComponent(gid)}`);
    ed.tasks = r.tasks || []; ed.status = r.status || {}; ed.items = r.items || []; ed.todayChoices = r.today_choices || {}; ed.skipTasks = new Set(r.skip_tasks || []);
  }
  ed.saved = JSON.stringify(ed.tasks);
  S.ed = ed; setDirty(false);
}

// 每个分页在主栏顶上写清楚这一页是什么（和「高级」一样：标题 + 一句灰色说明）
const TAB_HINT = { today: '今天要跑的任务和结果；改跑哪些在「任务预设」，改什么时候在日程页', routine: '一套预设 = 一次跑哪些任务、按什么顺序、选项怎么设',
  runs: '每次运行的结果、用时和截图；时间为北京时间', library: '脚本工具自带任务，停用的不会出现在配置里', advanced: '保存时检查格式，不对会直接提示' };
const tabName = tab => (TABS.find(t => t[0] === tab) || [tab, tab])[1];
const tabHead = (tab, extra = '') => `<div class="b-h tab-h"><h2>${esc(tabName(tab))}${extra}</h2><span>${esc(TAB_HINT[tab] || '')}</span></div>`;
function renderGame() {
  const ed = S.ed; const g = game(ed.gid);
  const page = main => `<div class="gpage">${gameShell(g, ed.tab)}<div id="page-alerts">${pageAlerts(g)}</div><div class="cols"><div class="main gmain">${tabHead(ed.tab, ed.tab === 'routine' && ed.routineName ? `<span class="tab-sub">「${esc(ed.routineName)}」</span>` : '')}${main}</div><aside class="aside" id="aside">${asideHtml(g)}</aside></div></div>`;
  if (ed.tab === 'runs') { $('#app').innerHTML = page('<div id="runs-box"><div class="glass skeleton">加载中…</div></div>'); renderRuns(); return; }
  if (ed.tab === 'advanced') { $('#app').innerHTML = page('<div id="adv-box"><div class="glass skeleton">加载中…</div></div>'); renderAdvanced(); return; }
  const y0 = window.scrollY;
  $('#app').innerHTML = page(`${ed.tab === 'routine' ? routineExtrasHtml(g) : ''}<section class="tlist glass" id="tlist">${ed.tab === 'today' ? todayInner() : taskListInner()}</section>`);
  window.scrollTo(0, y0); bindDrag();
}

// 游戏页顶部的 Alert：今天有失败的任务；外部工具（BetterGI）的设置被改过
function badTasks() {
  const ed = S.ed; if (!ed || ed.tab !== 'today') return [];
  return ed.tasks.filter(t => BAD.has(ed.status[keyOf(t)]?.result));
}
function pageAlerts(g) {
  const ed = S.ed; let h = '';
  const bad = badTasks();
  if (bad.length) {
    h += `<div class="alert big">${ICON.warn}<div class="a-body"><div class="a-t">今天有 ${bad.length} 项需要处理</div>
      ${bad.map(t => { const st = ed.status[keyOf(t)]; return `<div class="a-d">${esc(tn(keyOf(t)))} · ${esc(RES[st.result]?.[0] || st.result)}${st.detail ? ` · ${esc(why(st.detail))}` : ''}</div>`; }).join('')}
      <div class="a-acts"><button class="btn xs" data-act="goto-tab" data-tab="runs">看运行记录</button><button class="btn xs" data-act="rerun-bad">重跑这 ${bad.length} 项</button></div></div></div>`;
  }
  if (g?.can_import && g.changed_outside) {
    const name = toolName(g);
    h += `<div class="alert big">${ICON.warn}<div class="a-body"><div class="a-t">${esc(name)} 里的设置有改动</div><div class="a-d">在管家上次写入或同步之后，${esc(name)} 的一条龙配置又被改过。点「从 ${esc(name)} 同步」导入到一套任务预设。</div></div></div>`;
  }
  return h;
}
function rerunBad() {
  const ed = S.ed; const keys = badTasks().map(keyOf); if (!keys.length) return;
  startGame(ed.gid, keys);
}

// 导入工具自带的预设（11-02：挂上以后也能导入；MaaFramework 项目的 preset、MFA 的实例、工具默认勾选；BetterGI 的一条龙）
// 批注 #177（11-03）：入口挪到「设置 → 工具与游戏」每个脚本那一行
async function importToolRoutines(gid) {
  let r; try { r = await api('GET', `/api/games/${encodeURIComponent(gid)}/tool-routines`); } catch (e) { return fail(e); }
  const list = r.routines || [];
  if (!list.length) return toast('这个工具里没有自带的预设', true);
  const v = await modal({ title: '导入工具自带的预设', ok: '导入',
    body: `<div class="small muted" style="margin-bottom:10px">勾上的做成任务预设（和已有的同名时，名字后面加「（导入）」）。</div>
      ${list.map((x, i) => `<label class="rad"><input type="checkbox" data-i="${i}" ${x.exists ? '' : 'checked'}> ${esc(x.name)} <span class="xsmall faint">${x.count} 项${x.exists ? ' · 已有同名的任务预设' : ''}</span></label>`).join('')}`,
    onMount: (m, setVal) => setVal(() => [...m.querySelectorAll('input[data-i]:checked')].map(c => list[+c.dataset.i].name)) });
  if (!Array.isArray(v) || !v.length) return;
  try {
    const res = await api('POST', `/api/games/${encodeURIComponent(gid)}/import-routines`, { names: v });
    toast(res.imported.length ? `已导入：${res.imported.join('、')}（在游戏页「任务预设」里）` : '没有导入');
    await loadState();
    if (S.ed?.gid === gid) { if (res.imported[0]) S.ed.routineName = res.imported[0]; await loadEditor(gid, S.ed.tab); renderGame(); }
  } catch (e) { fail(e); }
}
// 右侧任务预设卡片：任务预设列表，每套下面写着它的定时（点定时改，「＋ 定时」加）
const ruleText = u => typeof ruleChip === 'function' ? ruleChip(u) : u.text;
function routineCard(g) {
  const ed = S.ed; const sc = S.schemas[ed.gid] || {};
  const doc = ed.routines || { routines: {}, rules: [] };
  const names = Object.keys(doc.routines || {});
  const rules = doc.rules || [];
  const presets = sc.presets || [];
  const onRoutine = ed.tab === 'routine';
  const cur = onRoutine ? ed.routineName : '';
  let top = '', acts = '';
  if (onRoutine && cur) {
    acts = `      <div class="rc-btns"><button class="btn xs" data-act="pk-new" data-gid="${esc(g.id)}" title="新建一套任务预设：从头开始，或从工具自带的预设新建">新建预设</button><button class="btn xs" data-act="routine-new">另存为新预设</button><button class="btn xs" data-act="routine-rename">重命名</button><button class="btn xs" data-act="routine-del">删除</button></div>`;
  } else if (onRoutine) {
    acts = `<div class="rc-btns"><button class="btn xs" data-act="pk-new" data-gid="${esc(g.id)}">新建预设</button></div>`;
  }
  const list = names.map(n => {
    const on = n === cur;
    const act = onRoutine ? `data-act="routine-pick"` : `data-act="routine-goto"`;
    return `<a href="#/g/${esc(g.id)}/routine" ${act} data-name="${esc(n)}" class="${on ? 'on' : ''}" ${on ? 'aria-current="page"' : ''}><span>${esc(n)}</span><span class="xsmall faint num">${(doc.routines[n].tasks || []).length} 项</span></a>`;
  }).join('') || '<div class="xsmall faint">还没有任务预设：点「新建预设」，或到「设置 → 工具与游戏」导入工具自带的预设</div>';
  return `<section data-card="routine" class="panel glass navcard ${onRoutine ? 'on' : 'thin'}" ${onRoutine ? 'aria-current="page"' : `data-act="goto-tab" data-tab="routine" role="link" tabindex="0" aria-label="任务预设"`}><div class="ph"><h3>任务预设</h3>${onRoutine ? '<span class="xsmall faint">正在管理</span>' : ICON.right}</div>
    ${top}<div class="rlist">${list}</div>${acts ? `<div class="rc-acts">${acts}</div>` : ''}</section>`;
}

// 任务预设页主栏顶上：这套预设的定时（改时间、加定时都在这里），和跑日常时顺带做的「读公告 / 读抽卡资源」
function routineExtrasHtml(g) {
  const ed = S.ed; const cur = ed.routineName; if (!cur) return '';
  const rules = (ed.routines?.rules || []).filter(u => u.routine === cur);
  const chip = u => `<button type="button" class="chip" data-act="rule-edit" data-id="${esc(u.id)}" title="点开改时间、哪些天">${esc(ruleText(u))}</button>`;
  const ag = Object.entries(ed.again || {});
  return `<section class="rx">
    <div class="rx-row"><b>定时</b><div class="rx-c">${rules.length ? rules.map(chip).join('') : `<button type="button" class="linkbtn pr-norule" data-act="rule-add" data-gid="${esc(ed.gid)}" data-name="${esc(cur)}" title="点这里加定时">没有定时：手动跑</button>`}</div></div>
    <div class="rx-row"><b>自动重复</b><div class="rx-c">${(ed.again || {})['*'] ? `<button type="button" class="chip" data-act="again-edit" data-key="*" title="点开改">整套：${esc(againText(ed.again['*']))}</button>`
        : `<button type="button" class="btn ghost" data-act="again-edit" data-key="*">＋ 设置自动重复</button><span class="xsmall faint">这一整套预设做完后隔几小时再跑一轮，或到点再跑</span>`}
      ${ag.filter(([k]) => k !== '*').map(([k, a]) => `<button type="button" class="chip" data-act="again-edit" data-key="${esc(k)}" title="以前给单个任务设的，点开改或取消">${esc(tn(k))}：${esc(againText(a))}</button>`).join('')}</div></div>
  </section>`;  // 11-02：「资源记录」（读公告 / 读资源）挪到设置 → 游戏内读取
}
document.addEventListener('change', async e => {
  const c = e.target.closest?.('[data-read]'); const gid = c?.dataset.gid || S.ed?.gid; if (!c || !gid) return;
  try { await api('PUT', `/api/games/${encodeURIComponent(gid)}`, { [c.dataset.read]: c.checked }); await loadState(); toast(c.checked ? '已勾上：跑日常时一起做' : '已取消：跑日常时不再做'); }
  catch (err) { c.checked = !c.checked; fail(err); }
});

// 今天：只看。今天各条（定时生成的、临时加的）里的任务和状态
function todayInner() {
  const ed = S.ed; const g = game(ed.gid);
  const R = S.running;
  const counted = ed.tasks.filter(t => !disabledReason(t.task));
  const done = counted.filter(t => DONE.has(ed.status[keyOf(t)]?.result)).length;
  const src = (ed.items || []).map(x => `${x.routine ? `「${x.routine}」` : x.tasks?.length ? `临时：${x.tasks.slice(0, 3).map(tn).join('、')}` : '今天的任务'}${x.kind === 'once' ? '（只这一次）' : ''}${x.skipped ? '（今天跳过）' : ''}`);
  const rows = ed.tasks.map((t, i) => {
    const k = keyOf(t); const st = ed.status[k]; const off = disabledReason(t.task); const win = winOf(g, t);
    const live = R?.running && R.current?.game === ed.gid && (R.current.task === k || R.current.task === t.task);
    const sk = ed.skipTasks?.has(k);
    const b = live ? `<span class="badge run"><span class="dot live" style="width:6px;height:6px"></span>运行中</span>` : sk && !DONE.has(st?.result) ? '<span class="badge off">今天跳过</span>' : st ? badge(st.result) : off ? '<span class="badge off">停用</span>' : win && !inWindow(win) ? '<span class="badge off">等时段</span>' : '<span class="badge off">未运行</span>';
    const td = taskDef(t.task); const open = ed.open.has(i); const can = td && td.options.length;  // 11-03：原神（BetterGI）也能在今日任务里改选项
    return `<div class="trow${off || sk ? ' off' : ''}${live ? ' cur' : ''}${open ? ' open' : ''}"${can ? ` data-i="${i}"` : ''} data-tkey="${esc(k)}"><div class="thead"${can ? ` data-act="toggle" data-i="${i}"` : ''}><span class="tname"><b>${esc(tn(k))}</b>${ed.todayChoices?.[k] ? '<span class="chip">仅今日</span>' : ''}${st?.detail && BAD.has(st.result) ? `<span class="sum">${esc(why(st.detail))}</span>` : st?.time ? `<span class="sum num">${esc(st.time)}</span>` : ''}</span>
      <span class="tright">${win ? `<span class="chip" title="北京时间（游戏里的时间）；${esc(winLocalNote(win) || '和电脑本地时间一样')}">${ICON.clock}只在 ${esc(win.replace(/-/g, '–'))}</span>` : ''}${b}${moreBtn('跳过此次 / 再跑一次 / 标为已完成')}${can ? `<button class="btn icon xs ghost" data-act="toggle" data-i="${i}" aria-label="${open ? '收起' : '展开'}选项" aria-expanded="${open}">${ICON.chev}</button>` : '<span class="btn icon xs ghost slot-ph" aria-hidden="true"></span>'}</span></div>
      ${open ? todayBody(t, i, td) : ''}</div>`;
  }).join('');
  // 11-03：BetterGI 这类外部工具：今日任务里也能从工具同步 / 同步到工具，都只管今天（不改任务预设）
  const tools = g?.can_import ? `<div class="tl-tools">
      <span class="small muted">只改今天，明天恢复任务预设里的</span><span style="flex:1"></span>
      ${g.can_open ? `<button class="btn" data-act="open-tool" data-gid="${esc(g.id)}">去 ${esc(toolName(g))} 布置</button>` : ''}
      <button class="btn ${g.changed_outside ? 'warn' : ''}" data-act="today-import" title="今天按 ${esc(toolName(g))} 一条龙现在的设置跑：选项用它的，它没启用的今天跳过">从 ${esc(toolName(g))} 同步（仅今日）</button>
      <button class="btn" data-act="today-export" title="把今天要跑的（含今天单独改的选项、跳过的不算）写进 ${esc(toolName(g))} 的一条龙">同步到 ${esc(toolName(g))}</button>
    </div>` : '';
  return `${tools}<div class="rows" id="rows">${rows || `<div class="empty">今天没有任务：给一套任务预设加上定时，或点下面的「添加任务」</div>`}</div>
    <button type="button" class="add-line" data-act="today-add" title="挑几项任务，加进今天的队列">${ICON.plus}添加任务</button>`;
}

// 今日任务里展开改选项：保存时问「仅今日」（默认）还是「写进任务预设」
function todayBody(t, i, td) {
  const k = keyOf(t);
  return `<div class="tbody">
    ${td.description ? `<div class="desc">${esc(stripTags(td.description))}</div>` : ''}
    <div class="opts">${optionsHtml(td, t, i, td.options, 0)}</div>
    <div class="tacts">${S.ed.todayChoices?.[k] ? `<span class="xsmall faint" style="align-self:center">今天用的是单独改过的选项</span><button class="btn xs ghost" data-act="today-reset" data-key="${esc(k)}">恢复成任务预设里的</button>` : ''}
      <span style="flex:1"></span><button class="btn xs" data-act="save" data-save-slot ${S.dirty ? '' : 'hidden'}>保存</button></div></div>`;
}
async function todaySave() {
  const ed = S.ed; const before = JSON.parse(ed.saved || '[]');
  const changed = ed.tasks.filter((t, i) => JSON.stringify(t.choices || {}) !== JSON.stringify(before[i]?.choices || {}));
  if (!changed.length) { setDirty(false); return true; }
  const rs = ed.routines?.routines || {};
  const names = [...new Set((ed.items || []).map(x => x.routine).filter(Boolean))];
  const where = t => names.find(n => (rs[n]?.tasks || []).some(x => keyOf(x) === keyOf(t)));
  // 11-03：今日任务里改的默认只管今天（主按钮「仅今日」），要以后都这样再选「写进任务预设」
  const pick = await modal({ title: '保存修改', ok: '仅今日', alt: '写进任务预设', cancel: '取消',
    body: `<div>改了这些任务的选项：</div><ul style="margin:0;padding-left:18px;line-height:1.8">${changed.map(t => `<li>${esc(tn(keyOf(t)))}${where(t) ? ` <span class="muted">→ 任务预设「${esc(where(t))}」</span>` : ' <span class="muted">（不在今天用的任务预设里，只能仅今日）</span>'}</li>`).join('')}</ul>
      <div class="small muted">仅今日：只今天这样跑，明天恢复任务预设里的。写进任务预设：以后每天都这样跑。</div>` });
  if (!pick) return false;
  const ans = pick?.alt ? true : 'today';  // true = 写进任务预设
  try {
    const today = {};
    if (ans === true) {
      const touched = new Set();
      changed.forEach(t => {
        const n = where(t); if (!n) { today[keyOf(t)] = t.choices || {}; return; }
        rs[n].tasks = rs[n].tasks.map(x => keyOf(x) === keyOf(t) ? { ...x, choices: clone(t.choices || {}) } : x); touched.add(n);
        if (ed.todayChoices?.[keyOf(t)]) today[keyOf(t)] = null;  // 以前「仅今日」改过的：去掉，回到刚写进预设的
      });
      if (touched.size) await api('PUT', `/api/routines/${encodeURIComponent(ed.gid)}`, { routines: rs });
    } else changed.forEach(t => { today[keyOf(t)] = t.choices || {}; });
    if (Object.keys(today).length) await api('PUT', `/api/today/${encodeURIComponent(ed.gid)}/choices`, { choices: today });
    toast(ans === true ? '已写进任务预设' : '只今天这样跑，明天恢复');
    setDirty(false); const open = ed.open; await loadEditor(ed.gid, 'today'); S.ed.open = open; await loadState(); renderGame();
    return true;
  } catch (e) { fail(e); return false; }
}
// 11-03：从工具同步（仅今日）/ 同步到工具
async function todayImport() {
  const ed = S.ed; const g = game(ed.gid); const name = toolName(g);
  if (!(await confirmBox(`从 ${esc(name)} 同步（仅今日）？`, `今天按 ${esc(name)} 一条龙现在的设置跑：选项用它的；它没启用的任务今天跳过。任务预设不变，明天恢复。${S.dirty ? '<br><b>页面上还没保存的修改会丢掉。</b>' : ''}`, '同步'))) return;
  try {
    const r = await api('POST', `/api/today/${encodeURIComponent(ed.gid)}/import-tool`);
    toast(r.msg || '今天按工具的设置跑');
    setDirty(false); const open = ed.open; await schema(ed.gid, true); await loadState(); await loadEditor(ed.gid, 'today'); S.ed.open = open; renderGame();
  } catch (e) { fail(e); }
}
async function todayExport() {
  const ed = S.ed; const g = game(ed.gid); const name = toolName(g);
  if (S.dirty && !(await todaySave())) return;
  if (!(await confirmBox(`同步到 ${esc(name)}？`, `把今天要跑的任务（含今天单独改过的选项，跳过的不算）写进 ${esc(name)} 的一条龙配置（写之前备份）。${esc(name)} 开着时，等它关掉后再写。`, '写进去'))) return;
  try {
    const r = await api('POST', `/api/bettergi/${encodeURIComponent(ed.gid)}/sync`, { today: true });
    toast(r.msg || `已写进 ${name}`);
    await loadState(); renderGame();
  } catch (e) { fail(e); }
}
async function todayReset(key) {
  try { await api('PUT', `/api/today/${encodeURIComponent(S.ed.gid)}/choices`, { choices: { [key]: null } }); toast('已恢复成任务预设里的'); const open = S.ed.open; setDirty(false); await loadEditor(S.ed.gid, 'today'); S.ed.open = open; renderGame(); } catch (e) { fail(e); }
}

// 任务预设页：单个任务的「自动重复」（做完隔几小时再跑一轮，或到点再跑）。改完和任务列表一起保存
async function againEdit(key) {
  const ed = S.ed; const rec = game(ed.gid)?.recovery_task;
  const keys = ed.tasks.map(keyOf).filter(k => k !== rec && !(ed.tasks.find(t => keyOf(t) === k) && taskDef(ed.tasks.find(t => keyOf(t) === k).task)?.kind === 'finish'));
  const all = key === '*';  // 批注 #179：整套预设自动重复
  const a = (key && ed.again?.[key]) || {};
  const v = await modal({ title: all ? `自动重复 · 整套「${ed.routineName}」` : key ? `自动重复 · ${tn(key)}` : '自动重复：选一个任务', ok: '确定', alt: key && ed.again?.[key] ? '不再自动重复' : '', body: `<div class="bedit">
    ${all ? '<input type="hidden" id="ag-k" value="*">' : `<label class="field-row"><b>任务</b><select class="sel" id="ag-k" ${key ? 'disabled' : ''}>${keys.map(k => `<option value="${esc(k)}" ${k === key ? 'selected' : ''}>${esc(tn(k))}</option>`).join('')}</select></label>`}
    <div class="field-row"><b>怎么重复</b><div class="be-start">
      <label class="rad"><input type="radio" name="ag-m" value="relay" ${!a.at?.length ? 'checked' : ''}> 做完后每隔 <input class="inp xs num" type="number" min="1" max="23" id="ag-h" value="${a.every_hours || 6}" style="width:64px"> 小时再跑，当天最多 <input class="inp xs num" type="number" min="2" max="8" id="ag-n" value="${a.max_rounds || 3}" style="width:64px"> 轮</label>
      <label class="rad"><input type="radio" name="ag-m" value="at" ${a.at?.length ? 'checked' : ''}> 到点再跑：<input class="inp xs" id="ag-t" value="${esc((a.at || []).map(bjToLocal).join(', ') || '14:00, 20:30')}" style="width:150px"> <span class="xsmall faint">本地时间，逗号隔开</span></label>
    </div></div>
    <div class="xsmall faint">${all ? '整套预设里的每一项都这样重复（启动游戏除外）。' : '只对这一个任务生效。'}上一轮没做成（失败或无可做）后面的轮次不再排；来不及在今天刷新前做的也不排。</div></div>`,
    onMount: (m, setVal) => setVal(() => {
      const k = $('#ag-k', m).value; const mode = (m.querySelector('input[name="ag-m"]:checked') || {}).value;
      return { k, a: mode === 'at' ? { at: $('#ag-t', m).value.split(/[,，\s]+/).filter(x => /^\d{1,2}:\d{2}$/.test(x)).map(localToBj) } : { every_hours: +$('#ag-h', m).value || 6, max_rounds: +$('#ag-n', m).value || 3 } };
    }) });
  if (!v) return;
  ed.again = ed.again || {};
  if (v.alt) delete ed.again[key]; else if (v !== true) ed.again[v.k] = v.a;
  ed.forceDirty = true; touch(false); renderGame(); toast('记得点「保存任务预设」');
}

// 任务列表
function taskListInner() {
  const ed = S.ed; const sc = S.schemas[ed.gid];
  const f = ed.filter.trim().toLowerCase();
  const isToday = false;
  const done = 0;
  const rows = ed.tasks.map((t, i) => (!f || (keyOf(t) + ' ' + t.task).toLowerCase().includes(f)) ? taskRow(t, i) : '').join('');
  return `<div class="tl-tools">
      <label class="field">${ICON.search}<input type="search" placeholder="搜索任务名" aria-label="搜索任务名" data-act="filter" value="${esc(ed.filter)}"></label>
      <span class="small muted num">${ed.tasks.length} 项${isToday ? ` · 已完成 ${done}` : ''}</span>
      ${toolButtons(game(ed.gid))}
      <button class="btn" data-act="add">${ICON.edit}修改预设</button>
    </div>
    <div class="rows" id="rows">${rows || `<div class="empty">${ed.tasks.length ? '没有匹配的任务' : '还没有任务，点「修改预设」加进来'}</div>`}</div>
    <div class="tl-foot"><span id="tl-save2" style="display:contents">${saveBtns()}</span></div>
    ${sc.tasks.length ? (isBgi(ed.gid)
      ? `<div class="legend"><i></i>在管家里改过的选项，运行时会写进 BetterGI；没改过的跟随 BetterGI 里的设置。启用哪些项和顺序以这里为准。</div>`
      : `<div class="legend"><i></i>与 MAA 里原来的设置不同的选项</div>`) : ''}`;
}

function disabledReason(task) {
  const sw = (S.switches[S.ed.gid] || []).find(x => x.task === task);
  if (sw) return sw.disabled ? (sw.reason || '已停用') : '';
  const td = S.schemas[S.ed.gid].tasks.find(x => x.name === task);
  if (td && td.disabled) return td.disabled_reason || '已停用';
  return '';
}
const taskDef = name => S.schemas[S.ed.gid].tasks.find(x => x.name === name);

// 任务的运行时段写在游戏设置里（按任务键或任务名），不在任务项上；编辑页改了先记在 ed.winEdits，保存时一起写回。
// 存的是北京时间（调度按北京时间判）；界面上显示和填写都用电脑本地时间（评测 #4，和批次时间同一口径）。
const winLocal = w => !w ? '' : w.split(/[,，]/).map(seg => seg.split('-').map(x => bjToLocal(x.trim())).join('-')).join(',');
// 批注 #194（11-03）：运行时段按北京时间（游戏里的时间）填，下面写出换算成电脑本地时间是几点（本地就是北京时间时不写）
const winLocalNote = w => { const x = (w || '').replace(/，/g, ','); if (!x || !WIN_RE.test(x)) return ''; const l = winLocal(x); return l.replace(/\s/g, '') === x.replace(/\s/g, '') ? '' : `本地时间 ${l}`; };
const winBj = w => !w || !WIN_RE.test(w.replace(/，/g, ',')) ? w : w.replace(/，/g, ',').split(',').map(seg => seg.split('-').map(x => localToBj(x.trim())).join('-')).join(',');
function winOf(g, t) {
  const k = keyOf(t); const ed = S.ed;
  if (ed?.gid === g?.id && ed.winEdits && k in ed.winEdits) return ed.winEdits[k];
  const w = g?.windows || {}; return w[k] || w[t.task] || '';
}
function inWindow(win) { // 北京时间现在是否在时段内
  if (!win) return true;
  const b = new Date(nowBjMs() + 8 * 3600e3); const now = b.getUTCHours() * 60 + b.getUTCMinutes();
  return win.split(/[,，]/).some(seg => {
    const m = seg.trim().match(/^(\d{1,2}):(\d\d)\s*-\s*(\d{1,2}):(\d\d)$/); if (!m) return false;
    const a = +m[1] * 60 + +m[2], z = +m[3] * 60 + +m[4];
    return z >= a ? now >= a && now <= z : now >= a || now <= z;
  });
}

function taskSummary(t, td) {
  if (!td) return '';
  const bits = [];
  walkOptions(td, t, (name, od, val, depth) => {
    if (depth > 0 || bits.length >= 3) return;
    if (od.type === 'input') { const v = Object.values(val || {})[0]; if (v !== undefined && v !== '') bits.push(`${od.label || name}：${v}`); return; }
    if (od.type === 'checkbox') { bits.push(`${od.label || name}：${(val || []).length} 项`); return; }
    const c = (od.cases || []).find(c => c.name === val);
    bits.push(`${od.label || name}：${caseLabel(c, val)}`);
  });
  return bits.join(' · ');
}

// 「未实测」标签、任务提醒（会切换账号、消耗体力 / 货币 / 树脂等）
const untestedTag = () => '';  // 10-28：「未实测」标签不再显示
const noticeIcon = td => td?.notice ? `<span class="badge warn" title="${esc(td.notice)}">${ICON.warn}注意</span>` : '';
function taskRow(t, i) {
  const ed = S.ed; const td = taskDef(t.task); const k = keyOf(t);
  const st = ed.status[k];
  const off = disabledReason(t.task);
  const open = ed.open.has(i);
  const R = S.running; const isCur = R?.running && R.current?.game === ed.gid && (R.current.task === k || R.current.task === t.task) && ed.tab === 'today';
  let right = '';
  if (!td) right += `<span class="badge bad">MAA 里找不到</span>`;
  if (off) right += `<span class="badge off">停用</span>`;
  right += untestedTag(td) + noticeIcon(td);
  const win = winOf(game(ed.gid), t);
  if (win) right += `<span class="chip" title="北京时间（游戏里的时间）；${esc(winLocalNote(win) || '和电脑本地时间一样')}">${ICON.clock}只在 ${esc(win.replace(/-/g, '–'))}</span>`;
  if (ed.tab === 'today') {
    if (isCur) right += `<span class="badge run"><span class="dot live" style="width:6px;height:6px"></span>运行中</span>`;
    else if (st) right += badge(st.result);
    else if (!off) right += win && !inWindow(win) ? `<span class="badge off">等时段</span>` : `<span class="badge off">未运行</span>`;
  }
  return `<div class="trow${open ? ' open' : ''}${off ? ' off' : ''}${isCur ? ' cur' : ''}" data-i="${i}">
    <div class="thead" data-act="toggle" data-i="${i}">
      <span class="grip" title="${td?.kind === 'finish' ? '固定在最后' : '拖动调整顺序'}" aria-hidden="true" ${td?.kind === 'finish' ? 'style="visibility:hidden"' : ''}>${ICON.grip}</span>
      <span class="tno num">${pad(i + 1)}</span>
      <span class="tname"><b>${esc(tn(k))}</b>${!open ? `<span class="sum">${esc(taskSummary(t, td))}</span>` : ''}</span>
      <span class="tright">${right}<button class="btn icon xs ghost" data-act="toggle" data-i="${i}" aria-label="${open ? '收起' : '展开'}选项" aria-expanded="${open}">${ICON.chev}</button></span>
    </div>
    ${open ? taskBody(t, i, td, off, st) : ''}
  </div>`;
}

function taskBody(t, i, td, off, st) {
  const ed = S.ed;
  const n = ed.tasks.length;
  const dup = ed.tasks.filter(x => x.task === t.task).length > 1;
  let h = '<div class="tbody">';
  const bgi = isBgi(ed.gid); const g = game(ed.gid);
  if (td?.notice) h += `<div class="notice-line">${ICON.warn}<span>${esc(td.notice)}</span></div>`;
  if (td?.description) h += `<div class="desc">${esc(stripTags(td.description))}</div>`;
  if (td?.kind === 'group') {
    const items = td.group_items || [];
    h += `<div class="grp-items"><div class="gi-h"><b>配置组里的内容</b><span class="xsmall faint">启用 ${items.filter(x => x.enabled).length} / ${items.length}</span><span style="flex:1"></span>${items.length ? `<button class="btn xs" data-act="edit-group" data-task="${esc(t.task)}">在管家里改</button>` : ''}${g?.can_open ? `<button class="btn xs" data-act="open-tool" data-gid="${esc(ed.gid)}">去 ${esc(toolName(g))} 修改</button>` : ''}</div>
      <div class="gi-list">${items.map(x => `<div class="gi${x.enabled ? '' : ' off'}"><span class="gi-n">${esc(x.name)}</span><span class="xsmall faint">${esc([x.folder, x.type, x.schedule && x.schedule !== 'Daily' ? x.schedule : ''].filter(Boolean).join(' · '))}</span>${x.enabled ? '' : '<span class="badge off">未启用</span>'}</div>`).join('') || '<div class="xsmall faint">空的配置组</div>'}</div></div>`;
  }
  if (st && st.result !== 'pending') h += `<div class="st-detail num">${badge(st.result)}${st.attempts > 1 ? `<span>尝试 ${st.attempts} 次</span>` : ''}${st.detail ? `<span>${esc(why(st.detail))}</span>` : ''}<a href="#/g/${esc(ed.gid)}/runs">看运行记录</a></div>`;
  if (!bgi) h += `<div class="metaf">
    <label>显示名（同一任务加多次时用来区分）<input class="inp" data-act="key" data-i="${i}" value="${esc(t.key || '')}" placeholder="${esc(dup ? '保存时自动命名为「' + tn(t.task) + ' #2」' : tn(t.task))}"></label>
    <label>运行时段（北京时间，和游戏里一样；不填 = 不限；这个游戏所有日子都按它）<input class="inp num" data-act="window" data-i="${i}" value="${esc(winOf(g, t))}" placeholder="例如 12:00-15:00"><span class="xsmall faint" data-winlocal="${i}">${winLocalNote(winOf(g, t))}</span><span class="err" data-err="window-${i}"></span></label>
  </div>`;
  if (td) {
    if (td.options.length) h += `<div class="opts">${optionsHtml(td, t, i, td.options, 0)}</div>`;
    else if (td.kind !== 'group') h += `<div class="small faint">这个任务没有选项。</div>`;
  }
  h += `<div class="tacts">
    ${td?.kind === 'finish' ? '<span class="xsmall faint" style="align-self:center">固定在最后</span>' : `<button class="btn xs" data-act="up" data-i="${i}" ${i === 0 ? 'disabled' : ''}>上移</button>
    <button class="btn xs" data-act="down" data-i="${i}" ${i === n - 1 || taskDef(ed.tasks[i + 1]?.task)?.kind === 'finish' ? 'disabled' : ''}>下移</button>`}
    ${bgi ? '' : `<button class="btn xs" data-act="dup" data-i="${i}" ${off ? 'disabled' : ''}>再加一次</button>`}
    ${td && Object.keys(t.choices || {}).length ? `<button class="btn xs" data-act="reset-opts" data-i="${i}">${bgi ? '恢复为 BetterGI 设置' : '选项恢复为 MAA 设置'}</button>` : ''}
    <span style="flex:1"></span>
    <button class="btn xs warn" data-act="remove" data-i="${i}">移除</button>
    <button class="btn xs" data-act="save-one" data-i="${i}" data-save-slot title="只保存这一项的修改；下面的「保存任务预设」保存整套" ${S.dirty ? '' : 'hidden'}>保存此项</button></div>`;
  return h + '</div>';
}

// 选项
function optValue(td, t, name) {
  const od = S.schemas[S.ed.gid].options[name];
  let v = t.choices?.[name];
  if (v === undefined) v = td.mfa_choices?.[name];
  if (v === undefined) v = od?.default;
  if (od?.type === 'checkbox') v = Array.isArray(v) ? v : (v ? [v] : []);
  if (od?.type === 'input') { const o = {}; (od.inputs || []).forEach(x => o[x.name] = x.default ?? ''); v = Object.assign(o, typeof v === 'object' && v ? v : {}); }
  if (od && (od.type === 'select' || od.type === 'switch') && !(od.cases || []).some(c => c.name === v)) v = od.cases?.[0]?.name;
  return v;
}
function subsOf(od, val) {
  if (!od || od.type === 'input') return [];
  if (od.type === 'checkbox') return (od.cases || []).filter(c => (val || []).includes(c.name)).flatMap(c => c.sub || []);
  return ((od.cases || []).find(c => c.name === val)?.sub) || [];
}
function walkOptions(td, t, cb, names = td.options, depth = 0, seen = new Set()) {
  const ops = S.schemas[S.ed.gid].options;
  for (const name of names) {
    if (seen.has(name)) continue; seen.add(name);
    const od = ops[name]; if (!od) continue;
    const val = optValue(td, t, name);
    cb(name, od, val, depth);
    walkOptions(td, t, cb, subsOf(od, val), depth + 1, seen);
  }
}
const caseLabel = (c, v) => { const l = c?.label || c?.name || v || ''; return l === 'Yes' ? '开启' : l === 'No' ? '关闭' : l; };
const changed = (td, t, name) => isBgi(S.ed.gid) ? !!(t.choices && name in t.choices) : t.choices && name in t.choices && td.mfa_choices && name in td.mfa_choices && JSON.stringify(t.choices[name]) !== JSON.stringify(td.mfa_choices[name]);

function optionsHtml(td, t, i, names, depth, seen = new Set()) {
  const ops = S.schemas[S.ed.gid].options;
  let h = '';
  for (const name of names) {
    if (seen.has(name)) continue; seen.add(name);
    const od = ops[name]; if (!od) continue;
    const val = optValue(td, t, name);
    const label = od.label || name; const hint = stripTags(od.description || '');
    const A = `data-i="${i}" data-opt="${esc(name)}"`;
    let ctl = '';
    if (od.type === 'input') {
      ctl = (od.inputs || []).map(inp => {
        const bad = !inputOk(inp, val[inp.name]);
        return `<label class="xsmall faint" style="display:flex;flex-direction:column;gap:3px">${(od.inputs.length > 1 || (inp.label && inp.label !== label)) ? esc(inp.label || inp.name) : ''}
          <input class="inp${bad ? ' invalid' : ''}" ${A} data-act="opt-input" data-inp="${esc(inp.name)}" value="${esc(val[inp.name])}" ${inp.pipeline_type === 'int' ? 'inputmode="numeric"' : ''} title="${esc(stripTags(inp.description || ''))}">
          ${bad ? `<span class="err">${inp.pipeline_type === 'int' ? '只能填数字' : '格式不对'}</span>` : ''}${badRule(inp) ? '<span class="hint">工具给的格式规则有误，这一项没检查</span>' : ''}${inp.description && od.inputs.length > 1 ? `<span class="hint">${esc(stripTags(inp.description))}</span>` : ''}</label>`;
      }).join('');
    } else if (od.type === 'checkbox') {
      ctl = `<div class="checks">${(od.cases || []).map(c => `<button type="button" class="${val.includes(c.name) ? 'on' : ''}" ${A} data-act="opt-check" data-case="${esc(c.name)}" aria-pressed="${val.includes(c.name)}">${ICON.check}${esc(caseLabel(c))}</button>`).join('')}</div>`;
    } else {
      const cs = od.cases || [];
      const short = cs.length <= 4 && cs.reduce((n, c) => n + [...caseLabel(c)].length, 0) <= 18;
      ctl = short
        ? `<div class="seg">${cs.map(c => `<button type="button" class="${c.name === val ? 'on' : ''}" ${A} data-act="opt-seg" data-case="${esc(c.name)}" aria-pressed="${c.name === val}">${esc(caseLabel(c))}</button>`).join('')}</div>`
        : `<select class="sel" ${A} data-act="opt-select" aria-label="${esc(label)}">${cs.map(c => `<option value="${esc(c.name)}" ${c.name === val ? 'selected' : ''}>${esc(caseLabel(c))}</option>`).join('')}</select>`;
    }
    if (hint) ctl += `<span class="hint" title="${esc(hint)}">${esc(hint)}</span>`;
    h += `<div class="opt"><div class="lab">${changed(td, t, name) ? '<i class="chg" title="与 MAA 里的设置不同"></i>' : ''}<span>${esc(label)}</span></div><div class="ctl">${ctl}</div></div>`;
    const subs = subsOf(od, val).filter(s => ops[s] && !seen.has(s));
    if (subs.length) h += `<div class="subs"><div class="subs-h">${esc(label)} · 子选项</div>${optionsHtml(td, t, i, subs, depth + 1, seen)}</div>`;
  }
  return h;
}
function badRule(inp) { if (!inp.verify) return false; try { new RegExp(inp.verify); return false; } catch (e) { return true; } }
function inputOk(inp, v) {
  v = String(v ?? '');
  if (inp.pipeline_type === 'int' && !/^-?\d+$/.test(v.trim())) return false;
  if (inp.verify && !badRule(inp) && !new RegExp(inp.verify).test(v)) return false; // 工具给的规则写错了：这一项不检查（输入框下面写明）
  return true;
}
const WIN_RE = /^\s*\d{1,2}:\d\d\s*-\s*\d{1,2}:\d\d\s*(,\s*\d{1,2}:\d\d\s*-\s*\d{1,2}:\d\d\s*)*$/;
function validate() {
  const ed = S.ed; const probs = [];
  Object.entries(ed.winEdits || {}).forEach(([k, w]) => { if (w && !WIN_RE.test(w.replace(/，/g, ','))) probs.push(`${k}：运行时段格式不对`); });
  ed.tasks.forEach((t, i) => {
    const td = taskDef(t.task); if (!td) return;
    walkOptions(td, t, (name, od, val) => {
      if (od.type === 'input') (od.inputs || []).forEach(inp => { if (!inputOk(inp, val[inp.name])) probs.push(`${keyOf(t)}：${od.label || name} 填写不对`); });
    });
  });
  const keys = ed.tasks.filter(t => t.key).map(t => t.key);
  const dupKey = keys.find((k, i) => keys.indexOf(k) !== i);
  if (dupKey) probs.push(`显示名「${dupKey}」重复了`);
  return probs;
}

// 右栏
function asideHtml(g) {
  const ed = S.ed; let h = '';
  const R = S.running;
  if (R?.running && R.current?.game === g.id) {
    const c = R.current; const runs = S.runsCache[g.id]; const last = runs?.runs?.[runs.runs.length - 1];
    const lt = [...(last?.tasks || [])].reverse().find(t => t.task === c.task); const la = lt?.attempts?.[lt.attempts.length - 1];
    const src = Array.isArray(c.focus) ? c.focus : (la?.focus || []);
    const lines = src.map(f => ({ t: '', html: focusHtml(f) })).slice(-6).reverse();
    h += `<section class="panel glass blue" data-card="run">
      <div class="ph"><h3>运行中</h3><span class="xsmall" style="color:var(--blue-ink);display:flex;align-items:center;gap:6px"><span class="dot live"></span>每 3 秒刷新</span></div>
      <div><div class="small" style="color:var(--blue-ink)">当前任务</div><div class="cur-task">${esc(tn(c.task) || '准备中')}</div>
        <div class="small muted num">第 ${c.attempt || 1} 次尝试${c.since ? ` · 已 ${dur(nowBjMs() - bjMs(c.since))}` : ''}</div></div>
      ${lines.length ? `<div class="feed">${lines.map(l => `<div><span>${l.html}</span></div>`).join('')}</div>` : ''}
      <div style="display:flex;gap:8px"><a class="btn sm" style="flex:1;text-decoration:none" href="#/g/${esc(g.id)}/runs">运行记录</a><button class="btn sm warn" style="flex:1" data-act="stop" ${R.stop_requested ? 'disabled' : ''}>${ICON.stop}${R.stop_requested ? '正在中止' : '中止队列'}</button></div>
    </section>`;
  }
  // 今天的进度
  h += `<section class="panel glass navcard ${ed.tab === 'today' ? 'on' : 'thin'}" data-card="plan" data-act="goto-tab" data-tab="today" role="link" tabindex="0" aria-label="今日任务" ${ed.tab === 'today' ? 'aria-current="page"' : ''}>
    <div class="ph"><h3>今日任务</h3>${ed.tab === 'today' ? '<span class="xsmall faint">正在查看</span>' : ICON.right}</div>
    <div class="xsmall faint num">${g.total ? `完成 ${g.done} / ${g.total}` : '今天没有任务'}</div></section>`;
  if (ed.tab === 'today') {
    const c = { ok: 0, bad: 0, wait: 0 };
    ed.tasks.forEach(t => { if (disabledReason(t.task)) return; const r = ed.status[keyOf(t)]?.result; if (DONE.has(r)) c.ok++; else if (BAD.has(r)) c.bad++; else c.wait++; });
    h += `<section class="panel glass" data-card="results"><div class="ph"><h3>今日结果</h3></div>
      <div class="tiles num"><div class="tile ${c.ok ? 'ok' : ''}"><b>${c.ok}</b><span>已完成</span></div>
      <div class="tile ${c.bad ? 'bad' : ''}"><b>${c.bad}</b><span>失败</span></div><div class="tile"><b>${c.wait}</b><span class="muted">未运行</span></div></div></section>`;
  }
  h += routineCard(g);
  h += resCardHtml(g);  // 抽卡资源（11-02）
  // 运行记录：和任务预设一样是卡片，点卡片切换到对应视图
  const sw = S.switches[g.id] || [];
  const navCard = (tab, title, body) => `<section data-card="${tab}" class="panel glass navcard ${ed.tab === tab ? 'on' : 'thin'}" data-act="goto-tab" data-tab="${tab}" role="link" tabindex="0" aria-label="${esc(title)}" ${ed.tab === tab ? 'aria-current="page"' : ''}>
    <div class="ph"><h3>${esc(title)}</h3>${ed.tab === tab ? '<span class="xsmall faint">正在查看</span>' : ICON.right}</div>${body}</section>`;
  h += navCard('runs', '运行记录', `<div class="nc-stats num"><span class="nc-ok"><b>${g.done || 0}</b> 条完成</span><span class="${g.attention ? 'nc-bad' : 'nc-zero'}"><b>${g.attention || 0}</b> 条要处理</span></div>`);
  h += navCard('advanced', '高级', '<div class="xsmall faint">启动任务、顺序、成败判定、超时</div>');
  return orderCards(h);
}

// 游戏页「高级」（评测 #6）：原来只能改 data/games/<游戏>.json 的设置，列出说明和现在的值，保存时后台检查格式
const ADV_HIDE = ['before_startup', 'run_order', 'timeouts', 'task_retries', 'retry_on_fail', 'restart_on_fail', 'back_presses'];  // 11-02：超时、重试改成全局（调度设置）  // 10-28：读公告改成「任务预设」里的勾选；「固定先后」不在界面上改了（游戏记录里有的照旧生效）
async function renderAdvanced() {
  const gid = S.ed.gid; const box = $('#adv-box'); if (!box) return;
  let d; try { d = await api('GET', `/api/games/${encodeURIComponent(gid)}/advanced`); } catch (e) { box.innerHTML = unreadHtml('高级设置', e); return; }
  const fields = d.fields.filter(f => !ADV_HIDE.includes(f.key));
  const J = v => v == null ? '' : JSON.stringify(v, null, 1);
  const cur = {};  // 界面上的值（null = 用默认）
  fields.forEach(f => { cur[f.key] = f.value ?? null; });
  const input = f => {
    const v = cur[f.key], id = `adv-${f.key}`;
    if (f.kind === 'int' && f.max - f.min <= 20) {  // 小范围：只能点 − / +，不能乱填
      const n = v ?? f.default ?? f.min;
      return `<div class="stepper" id="${id}"><button type="button" class="btn icon xs" data-step="-1" data-k="${f.key}" ${n <= f.min ? 'disabled' : ''} aria-label="减一">−</button><b class="num">${n}</b><button type="button" class="btn icon xs" data-step="1" data-k="${f.key}" ${n >= f.max ? 'disabled' : ''} aria-label="加一">+</button>
        <span class="xsmall faint">${f.min}–${f.max}${f.default != null ? ` · 默认 ${f.default}` : ''}</span>${v != null && v !== f.default ? `<button type="button" class="linkbtn" data-reset="${f.key}">恢复默认</button>` : ''}</div>`;
    }
    if (f.kind === 'int') return `<input class="inp xs num" type="number" min="${f.min}" max="${f.max}" id="${id}" value="${v ?? ''}" placeholder="默认">`;
    if (f.kind === 'bool') {
      const on = v ?? f.default;
      return `<div class="adv-bool" id="${id}"><div class="seg" role="group"><button type="button" class="${on ? 'on' : ''}" data-bool="${f.key}" data-v="1">开</button><button type="button" class="${on ? '' : 'on'}" data-bool="${f.key}" data-v="0">关</button></div>
        <span class="xsmall faint">默认${f.default ? '开' : '关'}</span>${v != null && v !== f.default ? `<button type="button" class="linkbtn" data-reset="${f.key}">恢复默认</button>` : ''}</div>`;
    }
    if (f.kind === 'choice') return `<select class="sel" id="${id}" style="width:auto">${f.choices.map(([k, l]) => `<option value="${esc(k)}" ${k === (v ?? f.default) ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
    if (f.kind === 'task') return `<select class="sel" id="${id}"><option value="">（没有）</option>${d.tasks.map(t => `<option ${t === v ? 'selected' : ''} value="${esc(t)}">${esc(tn(t))}</option>`).join('')}</select>`;
    if (f.kind === 'tasks') {  // 任务名列表：从下拉里选，已选的可以去掉
      const list = v || [];
      return `<div class="adv-tasks" id="${id}">${list.map((t, i) => `<span class="chip">${esc(tn(t))}<button type="button" class="linkbtn" data-tdel="${f.key}" data-i="${i}" aria-label="去掉 ${esc(tn(t))}">×</button></span>`).join('') || '<span class="xsmall faint">没有</span>'}
        <select class="sel" data-tadd="${f.key}" style="width:auto"><option value="">＋ 加一个任务…</option>${d.tasks.filter(t => !list.includes(t)).map(t => `<option value="${esc(t)}">${esc(tn(t))}</option>`).join('')}</select></div>`;
    }
    return `<textarea class="inp mono" rows="${f.kind === 'judge' ? 8 : 4}" id="${id}" placeholder="JSON；留空 = 用默认">${esc(J(v))}</textarea>`;
  };
  const readText = f => {  // 文本框里的值（int / task / JSON）
    const el = $(`#adv-${f.key}`); if (!el || !('value' in el)) return cur[f.key];
    const x = el.value.trim();
    if (!x) return null;
    if (f.kind === 'int') return Number(x);
    if (f.kind === 'task' || f.kind === 'choice') return x;
    try { return JSON.parse(x); } catch (e) { throw new Error(`「${f.label}」不是正确的 JSON：${e.message}`); }
  };
  const textKinds = f => !(f.kind === 'bool' || f.kind === 'tasks' || (f.kind === 'int' && f.max - f.min <= 20));
  const draw = () => {
    box.innerHTML = `<section class="glass panel adv">
      ${fields.map(f => `<div class="adv-row"><label for="adv-${f.key}"><b>${esc(f.label)}</b><span class="xsmall muted">${esc(f.help)}</span></label>${input(f)}</div>`).join('') || '<div class="small faint">这个工具没有可调的高级设置</div>'}
      <div class="adv-foot"><span class="xsmall faint">写脚本、做预设的人看：管家文件夹里的 docs\\给脚本作者.md（预设格式、成败判定、[GB_*] 信号）</span><button class="btn dark" id="adv-save">保存</button></div></section>`;
  };
  const keepText = () => { fields.filter(textKinds).forEach(f => { try { cur[f.key] = readText(f); } catch (e) { /* 保存时再报 */ } }); };
  draw();
  box.onclick = async e => {
    const st = e.target.closest('[data-step]'), bo = e.target.closest('[data-bool]'), rs = e.target.closest('[data-reset]'), td = e.target.closest('[data-tdel]');
    if (st) { const f = fields.find(x => x.key === st.dataset.k); keepText(); cur[f.key] = Math.min(f.max, Math.max(f.min, (cur[f.key] ?? f.default ?? f.min) + +st.dataset.step)); return draw(); }
    if (bo) { keepText(); cur[bo.dataset.bool] = bo.dataset.v === '1'; return draw(); }
    if (rs) { keepText(); cur[rs.dataset.reset] = null; return draw(); }
    if (td) { keepText(); const l = (cur[td.dataset.tdel] || []).slice(); l.splice(+td.dataset.i, 1); cur[td.dataset.tdel] = l.length ? l : null; return draw(); }
    if (e.target.id !== 'adv-save') return;
    const patch = {};
    try { fields.forEach(f => { const nv = textKinds(f) ? readText(f) : cur[f.key]; if (JSON.stringify(nv) !== JSON.stringify(f.value ?? null)) patch[f.key] = nv; }); } catch (err) { return fail(err); }
    if (!Object.keys(patch).length) return toast('没有改动');
    try { await api('PUT', `/api/games/${encodeURIComponent(gid)}/advanced`, patch); toast('高级设置已保存'); renderAdvanced(); } catch (err) { fail(err); }
  };
  box.onchange = e => {
    const a = e.target.closest('[data-tadd]'); if (!a || !a.value) return;
    keepText(); cur[a.dataset.tadd] = [...(cur[a.dataset.tadd] || []), a.value]; draw();
  };
}

// 右栏卡片可以拖动调整顺序（拖卡片标题栏），顺序存在本机浏览器里，所有游戏共用
const CARD_KEY = 'gb-aside-order';
// 顺序存在管家设置里（界面窗口里的浏览器存储不一定留得住）；本机浏览器存储只做备份
function cardOrder() {
  if (S.asideOrder) return S.asideOrder.slice();
  const saved = S.state?.appearance?.aside_order; if (saved?.length) return saved.slice();
  try { return JSON.parse(localStorage.getItem(CARD_KEY) || '[]'); } catch (e) { return []; }
}
function orderCards(html) {
  const t = document.createElement('template'); t.innerHTML = html;
  const cards = [...t.content.children];
  const order = cardOrder();
  const rank = el => { const i = order.indexOf(el.dataset.card); return i < 0 ? 100 + cards.indexOf(el) : i; };
  cards.sort((a, b) => rank(a) - rank(b));
  cards.forEach(c => { const ph = c.querySelector(':scope > .ph'); if (ph) { ph.classList.add('drag-h'); ph.title = '拖动标题栏可以调整卡片顺序'; } });
  return cards.map(c => c.outerHTML).join('');
}
// 拖卡片标题栏改顺序（pointerSort，见 core.js）
pointerSort({ box: '#aside', item: '[data-card]', handle: '[data-card] > .ph.drag-h', onDrop: (el, to, before) => {
  const full = cardOrder();
  $$('#aside [data-card]').forEach(x => { if (!full.includes(x.dataset.card)) full.push(x.dataset.card); });
  const c = el.dataset.card; full.splice(full.indexOf(c), 1);
  full.splice(full.indexOf(to.dataset.card) + (before ? 0 : 1), 0, c);
  S.asideOrder = full;
  try { localStorage.setItem(CARD_KEY, JSON.stringify(full)); } catch (x) { /* 忽略 */ }
  api('PUT', '/api/settings/appearance', { aside_order: full }).then(r => { if (S.state) S.state.appearance = r.appearance; }).catch(fail);
  const a = $('#aside'); if (a && S.ed) a.innerHTML = asideHtml(game(S.ed.gid));
} });
// 任务列表：按住 ⠿ 拖（搜索时不能拖）
pointerSort({ box: '#rows', item: '.trow[data-i]', handle: '.grip', can: () => S.ed?.tab === 'routine' && !S.ed.filter, onDrop: (el, to, before) => {
  const f = +el.dataset.i; let t = +to.dataset.i + (before ? 0 : 1); if (t > f) t--; if (t !== f) moveTask(f, t);
} });

// 脚本提示文字（可能是 JSON 字符串、含 [color:x] 或 <span>）
function focusHtml(f) {
  let s = String(f ?? '');
  if (s.startsWith('{')) { try { const o = JSON.parse(s); s = Object.values(o).join(' '); } catch (e) { /* 原样 */ } }
  s = stripTags(s);
  let out = '', re = /\[color:(\w+)\]([\s\S]*?)\[\/color\]/gi, last = 0, m;
  while ((m = re.exec(s))) { out += esc(s.slice(last, m.index)) + `<span class="c-${esc(m[1][0].toUpperCase() + m[1].slice(1).toLowerCase())}">${esc(m[2])}</span>`; last = re.lastIndex; }
  return out + esc(s.slice(last));
}

// ------------------------------------------------------------------ 运行记录
async function renderRuns(day) {
  const ed = S.ed; const g = game(ed.gid);
  day = day || ed.runsDay || g.today; ed.runsDay = day;
  let r;
  try { r = await api('GET', `/api/runs/${encodeURIComponent(g.id)}?day=${day}`); } catch (e) { $('#runs-box').innerHTML = `<div class="glass skeleton">${esc(e.message)}</div>`; return; }
  if (S.ed !== ed || ed.tab !== 'runs') return;
  S.runsCache[g.id] = day === g.today ? r : S.runsCache[g.id];
  const days = [0, 1, 2, 3, 4, 5, 6].map(n => addDays(g.today, -n));
  const runs = [...(r.runs || [])].reverse();
  ed.openRuns = ed.openRuns || new Set();
  const R = S.running;
  $('#runs-box').innerHTML = `<div style="display:flex;flex-direction:column;gap:16px">
    <section class="strip glass thin"><div class="l"><span>游戏日</span><select class="sel" style="width:auto" data-act="runs-day" aria-label="选择游戏日">${days.map(d => `<option value="${d}" ${d === day ? 'selected' : ''}>${d === g.today ? '今天 · ' : ''}${dayLabel(d)}</option>`).join('')}</select>
      <span class="small muted">共 ${runs.length} 次运行，最新的在上面</span></div>
      <div class="r"><button class="btn sm" data-act="runs-refresh">刷新</button></div></section>
    ${runs.length ? runs.map((run, idx) => runCard(run, idx === 0 && R?.running && R.current?.game === g.id)).join('') : '<div class="glass empty">这一天没有运行记录</div>'}
  </div>`;
}
function runCard(run, live) {
  const ed = S.ed; const g = game(ed.gid);
  const canMark = (ed.runsDay || g?.today) === g?.today;  // 11-03：今天的失败行可以右键标为已完成（标记只对今天有效）
  const st = live ? ['运行中', 'run'] : run.aborted ? ['熔断停止', 'bad'] : run.stopped ? ['手动停止', 'off'] : !run.finished ? ['中途结束', 'bad'] : run.ok ? ['顺利结束', 'ok'] : ['有任务没完成', 'bad', 1];
  const t0 = bjMs(run.started), t1 = bjMs(run.last_event);
  const nOk = run.tasks.filter(t => DONE.has(t.result)).length;
  const warns = (run.messages || []).filter(m => m.level !== 'info');
  return `<section class="runc glass">
    <div class="run-h"><div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap"><b class="num">${esc(mdhm(run.started))}</b>${st[2] ? `<span class="badge ${st[1]} icon-only" title="${st[0]}" aria-label="${st[0]}"></span>` : `<span class="badge ${st[1]}">${st[0]}</span>`}
      <span class="small muted num">${run.tasks.length} 个任务 · 完成 ${nOk}${t1 > t0 ? ` · 用时 ${dur(t1 - t0)}` : ''}</span></div>
</div>
    ${warns.length ? `<div class="msgs">${warns.map(m => `<div class="${esc(m.level)}"><span class="faint num">${esc(hm(m.time))}</span> ${esc(m.text)}</div>`).join('')}</div>` : ''}
    <table class="rtab"><colgroup><col style="width:28%"><col style="width:92px"><col style="width:112px"><col style="width:104px"><col></colgroup>
      <thead><tr><th>任务</th><th>结果</th><th>时间</th><th>用时</th><th>提示原因</th></tr></thead><tbody>
      ${run.tasks.map((t, j) => {
        const id = run.id + '|' + j; const open = ed.openRuns.has(id);
        const a0 = (t.attempts || [])[0], a1 = (t.attempts || [])[(t.attempts || []).length - 1];
        const span = a0?.start ? `${hm(a0.start)}${a1?.end ? '–' + hm(a1.end) : ''}` : '';
        return `<tr class="x" data-act="run-task" data-id="${esc(id)}"${canMark && RES[t.result]?.[1] === 'bad' && (g.att || []).some(a => a.task === t.task) ? ` data-gid="${esc(g.id)}" data-key="${esc(t.task)}" title="右键：立刻重跑 / 标为已完成 / 跳过任务"` : ''}><td><b>${esc(tn(t.task))}</b></td><td>${badge(t.result === 'running' ? (live ? 'running' : 'stopped') : t.result)}</td>
          <td class="num small">${esc(span)}</td><td class="num small">${t.tries > 1 ? `${t.tries} 次 · ` : ''}${esc(mins(t.minutes))}</td><td class="det">${esc(tn(t.detail || ''))}${t.shots?.length || t.evidence?.length ? ` <span class="chip">截图 ${(t.shots?.length || 0) + (t.evidence?.length || 0)}</span>` : ''}</td></tr>
          ${open ? `<tr><td colspan="5" style="background:transparent;padding:0"><div class="attempts">${t.attempts.map(a => `<div class="att">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap"><b class="small">第 ${a.attempt || 1} 次</b>${badge(a.result === 'running' ? (live ? 'running' : 'stopped') : a.result)}<span class="small faint num">${esc(hm(a.start))}${a.end ? ' – ' + esc(hm(a.end)) : ''}${a.minutes ? ` · ${esc(mins(a.minutes))}` : ''}</span>${a.detail ? `<span class="small muted">${esc(why(a.detail))}</span>` : ''}</div>
            ${a.focus?.length ? `<div class="feed">${a.focus.map(f => `<div>${focusHtml(f)}</div>`).join('')}</div>` : ''}
            ${a.flags?.length ? `<div class="xsmall faint">命中标志：${esc(a.flags.join('、'))}</div>` : ''}
            ${a.shots?.length || a.evidence?.length ? `<div class="shots">${[...(a.shots || []).map(s => [s, '卡住 / 失败时']), ...(a.evidence || []).map(s => [s, '留证'])].map(([s, k]) => `<button type="button" data-act="shot" data-src="${esc(s)}" aria-label="查看截图（${k}）" title="${k}截的"><img src="${esc(s)}" alt="" loading="lazy"></button>`).join('')}</div>` : ''}
          </div>`).join('')}</div></td></tr>` : ''}`;
      }).join('')}
    </tbody></table>
    ${(run.messages || []).length ? `<details><summary class="small muted" style="cursor:pointer">运行日志（${run.messages.length} 条）</summary><div class="msgs" style="margin-top:8px">${run.messages.map(m => `<div class="${esc(m.level)}"><span class="faint num">${esc(hm(m.time))}</span> ${esc(m.text)}</div>`).join('')}</div></details>` : ''}
  </section>`;
}

// ------------------------------------------------------------------ 任务库
const PINYIN = new Intl.Collator('zh-Hans-CN-u-co-pinyin');
const PY_KEYS = 'ABCDEFGHJKLMNOPQRSTWXYZ'.split('');
const PY_EDGE = '阿八嚓咑妸发旮哈丌咔垃妈拏噢妑七呥仨他屲夕丫帀'.split('');
function pyInitial(name) {
  const c = [...tn(name)][0] || '';
  if (/[0-9]/.test(c)) return '#';
  if (/[A-Za-z]/.test(c)) return c.toUpperCase();
  if (!/[\u4e00-\u9fff]/.test(c)) return '#';
  let r = 'A'; PY_EDGE.forEach((e, i) => { if (PINYIN.compare(c, e) >= 0) r = PY_KEYS[i]; });
  return r;
}
async function renderLibrary() {
  const ed = S.ed; const gid = ed.gid;
  let sw;
  try { sw = await switches(gid, true); } catch (e) { $('#lib-box').innerHTML = `<div class="glass skeleton">${esc(e.message)}</div>`; return; }
  if (S.ed !== ed) return;
  const sc = S.schemas[gid];
  const desc = n => { const td = sc.tasks.find(t => t.name === n); return td ? plain(td.description) : ''; };
  const list = [...sw].sort((a, b) => PINYIN.compare(tn(a.task), tn(b.task)));
  const nOff = list.filter(x => x.disabled).length;
  let cur = '', rows = '';
  list.forEach(x => {
    const L = pyInitial(x.task);
    if (L !== cur) { cur = L; rows += `<div class="lib-l num">${esc(L)}</div>`; }
    const d = desc(x.task);
    rows += `<div class="lrow${x.disabled ? ' off' : ''}"><div class="nm"><b>${esc(tn(x.task))}</b>${x.notice ? `<span class="badge warn" title="${esc(x.notice)}">${ICON.warn}注意</span>` : ''}${d ? `<div>${esc(d)}</div>` : ''}${x.notice ? `<div class="notice-line sm">${esc(x.notice)}</div>` : ''}</div>
      <div class="seg" role="group" aria-label="${esc(tn(x.task))}"><button type="button" class="${x.disabled ? '' : 'on'}" aria-pressed="${!x.disabled}" data-act="lib-enable" data-task="${esc(x.task)}">启用</button><button type="button" class="${x.disabled ? 'on' : ''}" aria-pressed="${!!x.disabled}" data-act="lib-disable" data-task="${esc(x.task)}">停用</button></div></div>`;
  });
  $('#lib-box').innerHTML = `<section class="lib glass">
    <div class="small muted num lib-sum">共 ${list.length} 个 · 启用 ${list.length - nOff} · 停用 ${nOff} · 按拼音排序</div>
    ${rows || '<div class="empty">没有任务</div>'}
  </section>`;
}

// ------------------------------------------------------------------ 编辑操作
function setDirty(v) {
  const was = S.dirty; S.dirty = v;
  $$('[data-save-slot]').forEach(b => { b.hidden = !v; }); // 展开的任务里，改过就出现「保存」
  if (was !== v) { $$('#tl-save2').forEach(t => { t.innerHTML = saveBtns(); }); const a = $('#aside'); if (a && S.ed?.routines) a.innerHTML = asideHtml(game(S.ed.gid)); }
}
// 有未保存的修改时，任务栏里出现「保存 / 放弃」（不再弹底部保存条；运行、布置/定时会自动先保存）
// 任务预设页：列表上面和下面都有「放弃修改 / 保存任务预设」，没改动时是灰的
function saveBtns() {
  if (!S.ed || S.ed.tab !== 'routine') return '';
  const off = S.dirty ? '' : 'disabled';
  const at = S.ed.savedAt; // 刚保存过：按钮变灰的同时写明已经存好了
  return `${!S.dirty && at ? `<span class="xsmall faint saved-at">已保存 ${pad(at.getHours())}:${pad(at.getMinutes())}</span>` : ''}<button class="btn" data-act="discard" ${off}>放弃修改</button><button class="btn" data-act="save" title="Ctrl+S" ${off}>保存任务预设</button>`;
}
function touch(rerender = true) {
  const ed = S.ed;
  setDirty(JSON.stringify(ed.tasks) !== ed.saved || !!ed.forceDirty);
  if (rerender) refreshList();
}
function refreshList() {
  const box = $('#tlist'); if (!box) return;
  const active = document.activeElement; const sel = active?.dataset?.act === 'filter';
  box.innerHTML = S.ed.tab === 'today' ? todayInner() : taskListInner();
  if (sel) { const f = $('[data-act="filter"]', box); f.focus(); f.setSelectionRange(f.value.length, f.value.length); }
  const a = $('#aside'); if (a) a.innerHTML = asideHtml(game(S.ed.gid));
  const pa = $('#page-alerts'); if (pa) pa.innerHTML = pageAlerts(game(S.ed.gid));
  bindDrag();
}
function cleanTasks(tasks) {
  return tasks.map(t => { const o = { task: t.task, choices: t.choices || {} }; if (t.key) o.key = t.key; return o; });
}

// 批注 #176（11-03）：任务里的「保存此项」只保存这一项（其他任务的改动留着、还算没保存）；下面的「保存任务预设」保存整套
async function saveOne(i) {
  const ed = S.ed; if (!ed || ed.tab !== 'routine') return save();
  const a = document.activeElement;
  if (a && a.matches?.('#tlist input, #tlist select, #tlist textarea')) { a.dispatchEvent(new Event('change', { bubbles: true })); a.blur(); }
  const cur = ed.tasks[i]; if (!cur) return;
  const before = JSON.parse(ed.saved || '[]'); const k = keyOf(cur);
  const next = before.slice(); const j = before.findIndex(t => keyOf(t) === k);
  if (j >= 0) next[j] = clone(cur); else next.splice(Math.min(i, next.length), 0, clone(cur));
  if (JSON.stringify(next) === JSON.stringify(ed.tasks)) return save();  // 只改了这一项：和保存整套一样
  try {
    const old = ed.routines.routines[ed.routineName] || {};
    ed.routines.routines[ed.routineName] = { ...old, tasks: cleanTasks(next) };
    await api('PUT', `/api/routines/${encodeURIComponent(ed.gid)}`, { routines: ed.routines.routines });
    ed.saved = JSON.stringify(next); ed.savedAt = new Date();
    toast(`已保存「${tn(cur.task)}」；其他任务的修改还没保存`);
    touch(true);
  } catch (e) { fail(e); }
}
async function save(quiet = false) {
  // 正在输入的框先把值交上来（不然点「保存」时它失焦触发的修改会在保存之后才到，保存完又变成「有未保存的修改」）
  const a = document.activeElement;
  if (a && a.matches?.('#tlist input, #tlist select, #tlist textarea')) { a.dispatchEvent(new Event('change', { bubbles: true })); a.blur(); }
  const ed = S.ed; if (!ed) return;
  const probs = validate();
  if (probs.length) { await modal({ title: '还有内容需要改', body: `<ul style="margin:0;padding-left:18px">${probs.map(p => `<li>${esc(p)}</li>`).join('')}</ul>`, ok: '知道了', cancel: '' }); return false; }
  try {
    if (ed.tab === 'today') return todaySave();  // 今日任务：问「覆盖预设」还是「仅今日」
    if (ed.tab !== 'routine') return true;
    const keys = new Set(ed.tasks.map(keyOf));
    const again = Object.fromEntries(Object.entries(ed.again || {}).filter(([k]) => k === '*' || keys.has(k)));  // 任务删掉了，它的自动重复也不要了；「*」= 整套
    ed.routines.routines[ed.routineName] = { tasks: cleanTasks(ed.tasks), ...(Object.keys(again).length ? { again } : {}) };
    await api('PUT', `/api/routines/${encodeURIComponent(ed.gid)}`, { routines: ed.routines.routines });
    toast(`已保存任务预设「${ed.routineName}」`);
    if (ed.winEdits && Object.keys(ed.winEdits).length) {  // 运行时段改在游戏设置里
      const w = { ...(game(ed.gid).windows || {}) };
      Object.entries(ed.winEdits).forEach(([k, v]) => { const x = v.replace(/，/g, ',').replace(/\s+/g, ''); if (x) w[k] = x; else delete w[k]; });
      await api('PUT', `/api/games/${encodeURIComponent(ed.gid)}`, { windows: w });
    }
    const open = ed.open;
    await loadEditor(ed.gid, ed.tab); S.ed.open = open; S.ed.savedAt = new Date();
    setDirty(false); await loadState(); renderGame();
    return true;
  } catch (e) { fail(e); return false; }
}
// 原神：保存时不写回 BetterGI，开跑前才写这次要跑的（用户 10-26 定）；两边对不上时选一边为准
async function bgiConflict(gid, b) {
  const col = (t, list) => `<div class="cmp-col"><b>${t}</b><ol>${list.map(x => `<li>${esc(tn(x))}</li>`).join('') || '<li class="faint">（空）</li>'}</ol></div>`;
  const ans = await modal({ title: 'BetterGI 里也改过', wide: true, ok: '以管家为准', alt: '以 BetterGI 为准', cancel: '先不管',
    body: `<div class="small">上次同步之后，BetterGI 里的一条龙「${esc(game(gid)?.bettergi?.config || '默认配置')}」被改过，和管家这边不一样。选一边为准：</div>
      <div class="cmp">${col('管家（今天要跑的）', b.butler || [])}${col('BetterGI 一条龙（启用的）', b.bettergi || [])}</div>
      <div class="xsmall faint">以管家为准：把管家今天要跑的写进 BetterGI（写之前备份）。以 BetterGI 为准：用 BetterGI 现在的设置覆盖管家正在看的那套任务预设。</div>` });
  try {
    if (ans === true) { const x = await api('POST', `/api/bettergi/${encodeURIComponent(gid)}/sync`); toast(x.msg || '已写回 BetterGI'); }
    else if (ans?.alt) { await api('POST', `/api/import/${encodeURIComponent(gid)}`, { routine: S.ed?.routineName || '' }); toast('已按 BetterGI 的设置更新管家'); await loadEditor(gid, S.ed?.tab || 'routine'); await loadState(); renderGame(); }
  } catch (e) { fail(e); }
}
async function editGroup(gid, task) {
  const td = taskDef(task); const items = JSON.parse(JSON.stringify(td?.group_items || []));
  const html = () => `<div class="small muted">勾选 = 启用；用上移 / 下移调整顺序。保存后直接写回 BetterGI 的配置组文件（写之前备份）。BetterGI 开着时不能改。</div>
    <div class="grp-edit">${items.map((x, i) => `<div class="ge-row"><label class="chk"><input type="checkbox" data-gi="${i}" ${x.enabled ? 'checked' : ''}> ${esc(x.name)}</label>
      <span class="xsmall faint">${esc([x.folder, x.type].filter(Boolean).join(' · '))}</span><span style="flex:1"></span>
      <button class="btn icon xs ghost" data-gmove="${i}" data-d="-1" ${i === 0 ? 'disabled' : ''} aria-label="上移">↑</button><button class="btn icon xs ghost" data-gmove="${i}" data-d="1" ${i === items.length - 1 ? 'disabled' : ''} aria-label="下移">↓</button></div>`).join('')}</div>`;
  const ok = await modal({ title: `编辑配置组 · ${task}`, wide: true, ok: '保存到 BetterGI', body: `<div id="ge">${html()}</div>`, onMount: (m, setVal) => {
    m.addEventListener('change', e => { const k = e.target.dataset.gi; if (k !== undefined) items[+k].enabled = e.target.checked; });
    m.addEventListener('click', e => { const b = e.target.closest('[data-gmove]'); if (!b) return; const i = +b.dataset.gmove, j = i + (+b.dataset.d); [items[i], items[j]] = [items[j], items[i]]; $('#ge', m).innerHTML = html(); });
    setVal(() => true);
  } });
  if (ok !== true) return;
  try {
    const r = await api('PUT', `/api/bettergi/${encodeURIComponent(gid)}/group`, { group: task, projects: items.map(x => ({ name: x.name, folderName: x.folder, enabled: x.enabled })) });
    toast(`已写回配置组：启用 ${r.enabled} / ${r.total}`);
    await loadEditor(gid, S.ed?.tab || 'routine'); renderGame();
  } catch (e) { fail(e); }
}
async function discard() {
  if (!(await confirmBox('放弃修改？', '没保存的修改会丢掉。', '放弃修改', true))) return;
  const ed = S.ed; await loadEditor(ed.gid, ed.tab); renderGame();
}

function moveTask(from, to) {
  const ed = S.ed; if (to < 0 || to >= ed.tasks.length || from === to) return;
  const fin = i => taskDef(ed.tasks[i]?.task)?.kind === 'finish';
  if (fin(from) || fin(to)) return toast('「结束后操作」固定在最后', true);
  const [t] = ed.tasks.splice(from, 1); ed.tasks.splice(to, 0, t);
  const open = new Set([...ed.open].map(i => i === from ? to : (from < to && i > from && i <= to) ? i - 1 : (from > to && i >= to && i < from) ? i + 1 : i));
  ed.open = open; touch();
}

// 「修改预设」（11-02，原「添加任务」）：每个任务前面 ✓ / ✕ 表示在不在这套预设里，点一下切换；
// 后面的 − 数量 + 调同一项要跑几次（BetterGI 一条龙里同一项只能有一次，没有加减）。「取消」全部还原
async function addTasks() {
  const ed = S.ed; const sc = S.schemas[ed.gid];
  const usable = sc.tasks.filter(t => !t.placeholder && !disabledReason(t.name)); // 只有任务库里启用的任务能加进来
  const count = n => ed.tasks.filter(t => t.task === n).length;
  const once = isBgi(ed.gid);
  let changed = 0;
  const snap = clone(ed.tasks);
  const confirming = new Set(); // 有提醒的任务：第一次点先显示提醒，再点一次才加
  const add = td => {
    const item = { task: td.name, choices: once ? {} : clone(td.mfa_choices || {}) }; // BetterGI：留空 = 跟随 BetterGI
    const fin = ed.tasks.findIndex(t => taskDef(t.task)?.kind === 'finish');
    if (td.kind !== 'finish' && fin >= 0) ed.tasks.splice(fin, 0, item); else ed.tasks.push(item);
  };
  const removeOne = n => { for (let i = ed.tasks.length - 1; i >= 0; i--) if (ed.tasks[i].task === n) { ed.tasks.splice(i, 1); return; } };
  const html = q => {
    q = (q || '').toLowerCase();
    const f = t => !q || tn(t.name).toLowerCase().includes(q) || t.name.toLowerCase().includes(q);
    const item = t => { const c = count(t.name), warn = t.notice && confirming.has(t.name);
      return `<div class="it pr-it${c ? ' on' : ''}">
      <button type="button" class="pr-tog" data-tog="${esc(t.name)}" aria-pressed="${!!c}" aria-label="${c ? '从预设里去掉' : '加进预设'}" title="${c ? '已选：点一下从预设里去掉' : '没选：点一下加进预设'}">${c ? ICON.check : ''}</button>
      <span class="nm" data-tog="${esc(t.name)}"><b>${esc(tn(t.name))}</b>${untestedTag(t)}<div>${esc(plain(t.description))}</div>${warn ? `<div class="notice-line">${ICON.warn}<span>${esc(t.notice)}</span></div><span class="btn xs dark" data-tog="${esc(t.name)}">知道了，加进去</span>` : ''}</span>
      ${once ? '' : `<span class="pr-step" role="group" aria-label="次数"><button type="button" class="btn icon xs" data-step="${esc(t.name)}" data-d="-1" ${c ? '' : 'disabled'} aria-label="少跑一次">−</button><b class="num">${c}</b><button type="button" class="btn icon xs" data-step="${esc(t.name)}" data-d="1" aria-label="多跑一次">+</button></span>`}</div>`; };
    return `<div class="pick">${usable.filter(f).map(item).join('') || '<div class="empty">没有匹配的任务</div>'}</div>`;
  };
  const ok = await modal({
    title: '修改预设', wide: true, ok: '保存', cancel: '取消',
    body: `<label class="field">${ICON.search}<input type="search" id="add-q" placeholder="搜索任务名" aria-label="搜索任务名"></label><div id="add-list">${html('')}</div>`,
    onMount: (m) => {
      const q = $('#add-q', m); setTimeout(() => q.focus(), 40);
      const redraw = () => { $('#add-list', m).innerHTML = html(q.value); };
      q.addEventListener('input', redraw);
      m.addEventListener('click', e => {
        const st = e.target.closest('[data-step]'), tg = e.target.closest('[data-tog]');
        const n = st?.dataset.step || tg?.dataset.tog; if (!n) return;
        const td = sc.tasks.find(t => t.name === n); if (!td) return;
        const c = count(n);
        const want = st ? c + (+st.dataset.d) : (c ? 0 : 1);
        if (want < 0 || (once && want > 1)) return;
        if (want > c && c === 0 && td.notice && !confirming.has(n)) { confirming.add(n); return redraw(); }
        confirming.delete(n);
        for (let k = c; k < want; k++) add(td);
        for (let k = c; k > want; k--) removeOne(n);
        changed++; ed.open = new Set();
        redraw();
      });
    },
  });
  if (!ok) { if (changed) { ed.tasks = snap; touch(); renderGame(); } return; }
  if (changed) { touch(); await save(); }  // 「保存」：直接存进这套任务预设
}

async function applySource(el) {
  const ed = S.ed; const v = el?.value; if (!v) return;
  const name = v.slice(2);
  let tasks, label;
  if (v.startsWith('r:')) { tasks = ed.routines.routines[name]?.tasks || []; label = `任务预设「${name}」`; }
  else { tasks = (S.schemas[ed.gid].presets || []).find(p => p.name === name)?.tasks || []; label = `MAA 预设「${name}」`; }
  if (!(await confirmBox('换成' + label + '？', `会用它的 ${tasks.length} 个任务替换现在的列表（保存后才生效）。`, '替换'))) { el.value = ''; return; }
  ed.tasks = clone(tasks); ed.open = new Set();
  touch(); renderGame(); toast(`已换成${label}，记得保存`);
}

async function routineOp(op, name) {
  const ed = S.ed; const doc = ed.routines;
  const commit = async (msg, sel, renamed) => {
    const r = await api('PUT', `/api/routines/${encodeURIComponent(ed.gid)}`, { routines: doc.routines, ...(renamed ? { renamed } : {}) });
    if (r.removed_rules) msg += `（它的 ${r.removed_rules} 个定时也删了）`;
    toast(msg); await loadState();
    S.ed.routineName = sel; await loadEditor(ed.gid, ed.tab); renderGame();
  };
  try {
    if (op === 'pick' || op === 'goto') {
      if (name === ed.routineName && ed.tab === 'routine') return;
      if (S.dirty && !(await confirmBox('切换任务预设？', '当前修改还没保存，切换后会丢掉。', '切换', true))) return;
      if (ed.tab !== 'routine') { setDirty(false); S.pendingRoutine = name; location.hash = `#/g/${ed.gid}/routine`; return; }
      ed.routineName = name; ed.tasks = clone(doc.routines[name]?.tasks || []); ed.again = clone(doc.routines[name]?.again || {}); ed.forceDirty = false; ed.saved = JSON.stringify(ed.tasks); ed.open = new Set(); setDirty(false); renderGame(); return;
    }
    if (op === 'new' || op === 'saveas') {
      const n = await modal({ title: op === 'new' ? '另存为新任务预设' : '另存为任务预设', input: { label: '名称', placeholder: '例如：周一（含电影院）' }, ok: '保存' });
      if (!n) return;
      if (doc.routines[n] && !(await confirmBox('覆盖已有的任务预设？', `「${esc(n)}」已经存在，会被现在的任务列表覆盖。`, '覆盖', true))) return;
      if (validate().length) return save();
      doc.routines[n] = { tasks: cleanTasks(ed.tasks) };
      if (op === 'saveas') { await api('PUT', `/api/routines/${encodeURIComponent(ed.gid)}`, { routines: doc.routines }); toast(`已另存为任务预设「${n}」`); ed.routines = await api('GET', `/api/routines/${encodeURIComponent(ed.gid)}`); await loadState(); refreshList(); renderGame(); return; }
      setDirty(false); return commit(`已另存为「${n}」`, n);
    }
    if (op === 'rename') {
      const n = await modal({ title: '重命名任务预设', input: { label: '新名称', value: ed.routineName }, ok: '重命名' });
      if (!n || n === ed.routineName) return;
      if (doc.routines[n]) return toast('这个名称已经有了', true);
      const r = {}; Object.keys(doc.routines).forEach(k => r[k === ed.routineName ? n : k] = k === ed.routineName ? { tasks: cleanTasks(ed.tasks) } : doc.routines[k]);
      doc.routines = r;
      setDirty(false); return commit(`已重命名为「${n}」`, n, { [ed.routineName]: n });
    }
    if (op === 'del') {
      const n = (doc.rules || []).filter(u => u.routine === ed.routineName).length;
      if (!(await confirmBox(`删除任务预设「${esc(ed.routineName)}」？`, `删除后不能恢复。${n ? `挂在它上面的 ${n} 个定时也会一起删掉。` : ''}`, '删除', true))) return;
      delete doc.routines[ed.routineName];
      setDirty(false); return commit('已删除', Object.keys(doc.routines)[0] || '');
    }
  } catch (e) { fail(e); }
}

// 原神等外部工具：去工具里布置 / 从工具同步（放在任务列表工具栏，「添加任务」旁边）
function toolButtons(g) {
  if (!g?.can_import) return '';
  const name = toolName(g);
  return `${g.can_open ? `<button class="btn" data-act="open-tool" data-gid="${esc(g.id)}" title="配置组里的路线、脚本等在 ${esc(name)} 里布置">去 ${esc(name)} 布置</button>` : ''}
    <button class="btn ${g.changed_outside ? 'warn' : ''}" data-act="import" title="用 ${esc(name)} 当前一条龙里启用的项和顺序覆盖这套任务预设">从 ${esc(name)} 同步</button>`;
}
async function openTool(gid, updater = false) {
  const g = game(gid);
  try { const r = await api('POST', `/api/open/${encodeURIComponent(gid)}`, updater ? { updater: true } : {}); toast(r.updater ? `正在打开 ${toolName(g)} 的更新程序…` : `正在打开 ${toolName(g)}…`); } catch (e) { fail(e); }
}
async function importFromTool() {
  const ed = S.ed; const g = game(ed.gid); const name = toolName(g);
  const def = ed.routineName || Object.keys(ed.routines?.routines || {})[0] || '日常';
  if (!(await confirmBox(`从 ${esc(name)} 同步？`, `用 ${esc(name)} 当前一条龙里启用的项（按它的顺序）和结束后操作，覆盖任务预设「${esc(def)}」。${S.dirty ? '<br><b>页面上还没保存的修改会丢掉。</b>' : ''}`, '同步'))) return;
  try {
    const r = await api('POST', `/api/import/${encodeURIComponent(ed.gid)}`, { routine: def });
    toast(`已从 ${name} 同步到任务预设「${r.routine || def}」`);
    setDirty(false); await schema(ed.gid, true); await loadState(); await loadEditor(ed.gid, ed.tab); renderGame();
  } catch (e) { fail(e); }
}

// 今日任务：右键一个任务 →「跳过此次」（今天不再跑它；正在跑的就是它：马上停下，接着跑后面的）/ 再跑一次 / 标为已完成
document.addEventListener('contextmenu', e => {
  const row = e.target.closest?.('#rows .trow[data-tkey]'); if (!row || S.ed?.tab !== 'today') return;
  const k = row.dataset.tkey; const on = !S.ed.skipTasks?.has(k); const bad = BAD.has(S.ed.status?.[k]?.result);
  e.preventDefault(); closeCtx();
  const m = document.createElement('div'); m.className = 'ctx glass'; m.id = 'news-ctx';
  // 11-03：跳过了的任务不再给「不跳过了」（要跑就点「再跑一次」）；换成「标为已完成」——跳过的在日常一览里还算没做完
  m.innerHTML = `<div class="ctx-t">${esc(tn(k))}</div>${on ? `<button type="button" data-act="task-skip" data-key="${esc(k)}" data-on="1"><i>⏭</i>跳过此次</button>` : ''}<button type="button" data-act="run-again" data-key="${esc(k)}" data-kind="now"><i>▶</i>再跑一次 · 立即开始</button><button type="button" data-act="run-again" data-key="${esc(k)}" data-kind="queue"><i>⤓</i>再跑一次 · 加入队列</button>${bad || !on ? `<button type="button" data-act="mark-done" data-key="${esc(k)}"><i>✓</i>标为已完成</button>` : ''}`;
  document.body.appendChild(m);
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(e.clientX, innerWidth - r.width - 8) + 'px'; m.style.top = Math.min(e.clientY, innerHeight - r.height - 8) + 'px';
});
async function taskSkip(key, on) {
  const gid = S.ed?.gid; if (!gid) return;
  try {
    const r = await api('POST', `/api/today/${encodeURIComponent(gid)}/skip`, { key, on });
    S.ed.skipTasks = new Set(r.skip_tasks || []);
    const R = S.running; const live = R?.running && R.current?.game === gid && (R.current.task === key || keyOf({ task: R.current.task }) === key);
    toast(on ? (live ? `正在停下「${tn(key)}」，接着跑后面的` : `今天跳过「${tn(key)}」`) : `「${tn(key)}」今天照常跑`);
    refreshList(); if (live) { S.fastUntil = Date.now() + 20000; pollRunning(); }
  } catch (e) { fail(e); }
}

// 单项任务（11-02）：今日任务的「添加任务」和右上角「单项任务」都用这个弹窗。列出这个游戏能做的所有任务，点选几项，
// 「加入队列」= 排在今天的队尾，前面的轮完才开始；「立即开始」= 现在就跑（正在跑别的就排在它后面）
async function addTodayTasks(gid) {
  gid = gid || S.ed?.gid; if (!gid) return;
  let sc; try { sc = await schema(gid); } catch (e) { return fail(e); }
  const list = (sc.tasks || []).filter(t => !t.placeholder && t.name !== game(gid)?.recovery_task);
  const st = S.ed?.gid === gid ? (S.ed.status || {}) : {};
  const sel = new Set();
  const html = q => {
    q = (q || '').toLowerCase();
    const f = t => !q || tn(t.name).toLowerCase().includes(q) || t.name.toLowerCase().includes(q);
    return `<div class="pick">${list.filter(f).map(t => `<button type="button" class="it${sel.has(t.name) ? ' on' : ''}" data-ta="${esc(t.name)}" aria-pressed="${sel.has(t.name)}">
      <span class="cbx">${ICON.check.replace('currentColor', '#fff')}</span><span class="nm"><b>${esc(tn(t.name))}</b><div>${esc(plain(t.description))}</div>${t.notice ? `<div class="notice-line">${ICON.warn}<span>${esc(t.notice)}</span></div>` : ''}</span>
      ${st[t.name] ? badge(st[t.name].result) : ''}</button>`).join('') || '<div class="empty">没有匹配的任务</div>'}</div>`;
  };
  const v = await modal({
    title: `单项任务 · ${shortName(gid)}`, wide: true, ok: '立即开始', alt: '加入队列',
    body: `<label class="field">${ICON.search}<input type="search" id="ta-q" placeholder="搜索任务名" aria-label="搜索任务名"></label><div id="ta-list">${html('')}</div>
      <div class="xsmall faint">选项按任务预设里的设置（没有就用工具默认）。今天做过的也会再跑一次。加入队列：排在今天的队尾，前面的轮完才开始。</div>`,
    onMount: (m, setVal) => {
      const q = $('#ta-q', m); setTimeout(() => q.focus(), 40);
      const upd = () => { const n = sel.size; m.querySelectorAll('[data-m="ok"],[data-m="alt"]').forEach(b => { b.disabled = !n; }); const o = $('[data-m="ok"]', m); if (o) o.textContent = n ? `立即开始（${n} 项）` : '先选任务'; };
      q.addEventListener('input', () => { $('#ta-list', m).innerHTML = html(q.value); });
      m.addEventListener('click', e => { const b = e.target.closest('[data-ta]'); if (!b) return; const n = b.dataset.ta; sel.has(n) ? sel.delete(n) : sel.add(n); $('#ta-list', m).innerHTML = html(q.value); upd(); });
      setVal(() => [...sel]); upd();
    },
  });
  if (!v) return;
  const keys = v.alt ? v.value : v;
  if (!keys || keys === true || !keys.length) return;
  return runTasks(gid, keys, v.alt ? 'queue' : 'now');
}
// 跑这几项：kind = queue（加入队列）/ now（立即开始）；今天做过的也再跑
async function runTasks(gid, keys, kind) {
  try {
    const r = await api('POST', '/api/schedule/today/items', { game: gid, tasks: keys, when: { kind }, rerun: true });
    toast(kind === 'queue' ? (r.batch?.merged ? '同类的已经排着：并进去了' : `已加进今天的队尾：${keys.map(tn).join('、')}`)
      : `${shortName(gid)}：${keys.map(tn).join('、')} ${r.batch?.paused ? '已排进队列，恢复调度后开始' : S.running?.running ? '已排进队列，前面的跑完接着跑' : '马上开始'}`);
    S.fastUntil = Date.now() + 40000; pollRunning();
    if (S.ed?.gid === gid) { const open = S.ed.open, tab = S.ed.tab; await loadEditor(gid, tab); S.ed.open = open; await loadState(); renderGame(); }
  } catch (e) { fail(e); }
}
