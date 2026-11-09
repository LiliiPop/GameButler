/* 游戏日常管家 · 前台
 * 只通过 HTTP API 与后台交互（见《管家前台-后台接口交接（第二版）》）。原生 JS，无依赖，离线可用。
 * 路由：#/            总览
 *       #/report      推送报告
 *       #/news        活动日历（官方公告的题图轮播 + 本月甘特图）
 *       #/schedule    日程（播放列表式的批次：什么时候跑哪个游戏的哪些任务）
 *       #/settings    设置（自动调度、开机自动启动、日志、外观）
 *       #/g/<gid>/<tab>   tab = today | routine | runs | advanced（tomorrow 是旧链接，转到 routine）
 */
'use strict';

// ------------------------------------------------------------------ 工具
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clone = o => JSON.parse(JSON.stringify(o));
const stripTags = s => String(s ?? '').replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').trim();
const keyOf = t => t.key || t.task;
// 任务名、提示里的 emoji 只在显示时去掉（数据和接口里保留原名）
const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}\u{200D}\u{20E3}\u{E0020}-\u{E007F}]/gu;
// 任务显示名：interface.json 里有 label（多语言）的项目，按 /api/labels 换成中文名
const tn = s => String((S.labels && S.labels[s]) || (s ?? '')).replace(EMOJI_RE, '').replace(/ {2,}/g, ' ').trim();
// 任务说明的第一行：去掉 HTML、[color:x] 标记和 Markdown 链接，只留文字
const plain = s => tn(stripTags(s).split('\n')[0].replace(/\[\/?color(:\w+)?\]/gi, '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[【】*]/g, ''));
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function api(method, url, body) {
  const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  let j = {};
  try { j = await r.json(); } catch (e) { /* 非 JSON */ }
  if (!r.ok) { const err = new Error(j.error || `请求失败（${r.status}）`); err.status = r.status; throw err; }
  return j;
}

const ICON = {
  edit: '<svg width="14" height="14" viewBox="0 0 20 20" aria-hidden="true"><path d="M4 16l1-4 8.5-8.5 3 3L8 15z M12 5l3 3" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linejoin="round"/></svg>',
  check: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  play: '<svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true"><path d="M3.5 2.2v9.6L11.5 7z" fill="currentColor"/></svg>',
  stop: '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect x="2" y="2" width="8" height="8" rx="1.5" fill="currentColor"/></svg>',
  power: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5v6M4.2 4a5.5 5.5 0 1 0 7.6 0" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/></svg>',
  back: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="1.7" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  chev: '<svg class="chev" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3.5 5.5L7 9l3.5-3.5" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  right: '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M4.5 3l3 3-3 3" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  plus: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M7 2.5v9M2.5 7h9" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  search: '<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.6" style="stroke:var(--faint)" stroke-width="1.5" fill="none"/><path d="M10.5 10.5L14 14" style="stroke:var(--faint)" stroke-width="1.5" stroke-linecap="round"/></svg>',
  grip: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="5" cy="3.5" r="1.1" fill="currentColor"/><circle cx="9" cy="3.5" r="1.1" fill="currentColor"/><circle cx="5" cy="7" r="1.1" fill="currentColor"/><circle cx="9" cy="7" r="1.1" fill="currentColor"/><circle cx="5" cy="10.5" r="1.1" fill="currentColor"/><circle cx="9" cy="10.5" r="1.1" fill="currentColor"/></svg>',
  warn: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.8l6.4 11.2H1.6z" style="stroke:var(--orange)" stroke-width="1.5" fill="none" stroke-linejoin="round"/><path d="M8 6.5v3M8 11.3v.2" style="stroke:var(--orange)" stroke-width="1.6" stroke-linecap="round"/></svg>',
  x: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  clock: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="5.6" stroke="currentColor" stroke-width="1.5" fill="none"/><path d="M7 4v3.2l2.2 1.4" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg>',
  star: '<svg width="10" height="10" viewBox="0 0 12 12" aria-hidden="true" style="vertical-align:-1px"><path d="M6 1.6l1.35 2.8 3.05.42-2.22 2.12.54 3.02L6 8.5 3.28 9.96l.54-3.02L1.6 4.82l3.05-.42z" stroke="currentColor" stroke-width="1.3" fill="none" stroke-linejoin="round"/></svg>',
  logo: '<svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true"><rect x="1" y="1" width="28" height="28" rx="9" style="fill:var(--ink)"/><path d="M9 15.5l4 4 8-9" style="stroke:var(--on-dark)" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

// 结果码
const RES = {
  succeeded: ['已完成', 'ok'], exhausted: ['已完成', 'ok'], failed: ['失败', 'bad'], timeout: ['失败', 'bad'],
  stalled: ['失败', 'bad'], missed: ['错过时段', 'bad'], stopped: ['已停止', 'off'], pending: ['未运行', 'off'], running: ['运行中', 'run'],
};
const DONE = new Set(['succeeded', 'exhausted']);
const BAD = new Set(['failed', 'timeout', 'stalled', 'missed']);
const badge = result => { // 只写结果，不带时间（时间只在运行记录里）
  const [t, c] = RES[result] || [result || '未运行', 'off'];
  return `<span class="badge ${c}">${esc(t)}</span>`;
};
const why = d => d ? `提示原因：${tn(d)}` : '';

// 北京时间 / 日期
const WEEK = '日一二三四五六';
const wd = day => { const [y, m, d] = day.split('-').map(Number); return '周' + WEEK[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]; };
const md = day => (day || '').slice(5);
const dayLabel = day => day ? `${md(day)} ${wd(day)}` : '';
const addDays = (day, n) => { const [y, m, d] = day.split('-').map(Number); const t = new Date(Date.UTC(y, m - 1, d + n)); return t.toISOString().slice(0, 10); };
const bjMs = s => { // "YYYY-MM-DD HH:MM[:SS]"（北京时间）→ 时间戳
  const m = String(s || '').match(/(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)(?::(\d\d))?/);
  return m ? Date.UTC(+m[1], m[2] - 1, +m[3], m[4] - 8, +m[5], +(m[6] || 0)) : NaN;
};
const pad = n => String(n).padStart(2, '0');
const hm = s => { const m = String(s || '').match(/(\d\d:\d\d)/); return m ? m[1] : ''; };
const mdhm = s => { const m = String(s || '').match(/\d{4}-(\d\d-\d\d)[ T](\d\d:\d\d)/); return m ? `${m[1]} ${m[2]}` : (s || ''); };
const dur = ms => { if (!(ms >= 0)) return ''; const s = Math.floor(ms / 1000); return s < 60 ? `${s} 秒` : s < 3600 ? `${Math.floor(s / 60)} 分 ${s % 60} 秒` : `${Math.floor(s / 3600)} 小时 ${Math.floor(s % 3600 / 60)} 分`; };
const mins = m => (m || m === 0) ? (m < 1 ? `${Math.round(m * 60)} 秒` : `${(+m).toFixed(1).replace(/\.0$/, '')} 分钟`) : '';

// 游戏配色：4 套主题，设置「外观」里切换（存在后台 data/ui.json，/api/state.appearance 带回来）
//   雾光 = 「日常管家」设计系统的游戏色（默认）；晴空 = 更亮更饱和；暮色 = 低饱和偏暖；高对比 = 照顾色弱，颜色差异最大
const PALETTES = {
  '雾光': { yuan: '#8F7BE0', tot: '#D98A9C', lysk: '#6F8FE0', sh: '#E0A070', genshin: '#6FB7A8', starrail: '#9AA6C8', jx3: '#B79A6A' },
  '晴空': { yuan: '#9B6BF2', tot: '#F06E96', lysk: '#3E8BF5', sh: '#FF9D4D', genshin: '#1FB89A', starrail: '#7C8CF8', jx3: '#E0A73A' },
  '暮色': { yuan: '#6E5A8A', tot: '#9A5E6E', lysk: '#4F6F9A', sh: '#9A6A44', genshin: '#4F7A70', starrail: '#6A7290', jx3: '#7D6A45' },
  '高对比': { yuan: '#7A2E9E', tot: '#C2185B', lysk: '#0055A4', sh: '#B04A00', genshin: '#2E7D32', starrail: '#00777A', jx3: '#8F6000' },
};
const PALETTE_DESC = { '雾光': '设计系统默认，柔和', '晴空': '更亮、更饱和', '暮色': '低饱和、偏暖', '高对比': '更鲜明' };
const SPARE = ['#8FA0D8', '#C99AC4', '#7FB09C', '#D7A27C', '#9C93D6'];
const palName = () => PALETTES[S.state?.appearance?.palette] ? S.state.appearance.palette : '雾光';
const tint = (g, i = 0) => S.state?.appearance?.game_colors?.[g.id] || PALETTES[palName()][g.id] || SPARE[i % SPARE.length];  // 自己定的颜色优先
// 色块上的字用白色还是深色：按 WCAG 对比度选
const onColor = hex => {
  const c = hex.replace('#', ''); const L = [0, 2, 4].map(i => { const v = parseInt(c.substr(i, 2), 16) / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  const l = 0.2126 * L[0] + 0.7152 * L[1] + 0.0722 * L[2];
  return (1.05 / (l + 0.05)) >= 4.5 ? '#fff' : '#1B1A2E';
};
const splitName = name => { const m = String(name || '').match(/^(.*?)[（(](.*)[）)]\s*$/); return m ? [m[1].trim(), m[2].trim()] : [name || '', '']; };
const markOf = name => { const ch = [...splitName(name)[0]].find(c => /[\u4e00-\u9fffA-Za-z0-9]/.test(c)); return ch || '·'; };
const KIND = { maa: 'MAA', bettergi: 'BetterGI', m7a: '三月七', command: '命令行' };
const isPC = g => g && ('pc' in g ? !!g.pc : (g.kind && g.kind !== 'maa'));
const canPick = g => g && (g.kind === 'maa' || g.can_import);
const isBgi = gid => !!(S.schemas[gid]?.bettergi || game(gid)?.can_import);
const toolName = g => g?.kind === 'bettergi' ? 'BetterGI' : (KIND[g?.kind] || 'MAA');

// ------------------------------------------------------------------ 状态
const S = {
  state: null,          // /api/state
  running: null,        // /api/running
  report: null,         // /api/report/<day>（总览用）
  schemas: {}, switches: {},
  route: { view: 'home' },
  ed: null,             // 当前编辑中的计划 / 任务预设
  dirty: false,
  bjOffset: 0,          // 服务器北京时间 − 本机时间
  runsCache: {},        // gid → /api/runs（运行面板用）
  wasRunning: false,
};
// 11-02：仅关注（没挂脚本）的游戏在 S.state.watch；活动、总览、颜色都按「挂着的 + 仅关注的」算
const allGames = () => [...(S.state?.games || []), ...(S.state?.watch || [])];
const game = gid => allGames().find(g => g.id === gid);
const nowBjMs = () => Date.now() + S.bjOffset;

// ------------------------------------------------------------------ 提示与弹窗
function toast(text, err = false, act = null) {  // act = {label, fn}：提示里带一个按钮（例如「撤销」，11-05）
  const box = $('#toast'); const d = document.createElement('div');
  d.textContent = text; if (err) d.className = 'err';
  if (act) {
    const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'toast-act'; btn.textContent = act.label;
    btn.onclick = () => { d.remove(); act.fn(); }; d.appendChild(btn);
  }
  box.appendChild(d); setTimeout(() => d.remove(), err ? 6000 : act ? 8000 : 3200);
}
const fail = e => toast(e.message || String(e), true);
const failRead = what => e => toast(`读不到${what}：${e.message || e}`, true); // 界面读数据失败：说出来，不当成没有数据
const unreadHtml = (what, e) => `<div class="small bwarn">读不到${esc(what)}：${esc(e.message || String(e))}</div>`;

function modal({ title, body = '', ok = '确定', cancel = '取消', alt = '', danger = false, wide = false, input = null, onMount = null, okDisabled = false }) {
  return new Promise(resolve => {
    const root = $('#modal');
    root.innerHTML = `<div class="modal-bg"><div class="modal glass${wide ? ' wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="mh"><h3>${esc(title)}</h3><button class="btn icon xs ghost" data-m="x" aria-label="关闭">${ICON.x}</button></div>
      <div class="mb">${body}${input ? `<label class="small" style="display:flex;flex-direction:column;gap:6px">${esc(input.label || '')}<input class="inp" style="max-width:none" id="m-input" value="${esc(input.value || '')}" placeholder="${esc(input.placeholder || '')}"></label>` : ''}</div>
      <div class="mf">${cancel ? `<button class="btn sm" data-m="no">${esc(cancel)}</button>` : ''}${alt ? `<button class="btn sm" data-m="alt">${esc(alt)}</button>` : ''}${ok ? `<button class="btn sm ${danger ? 'warn' : 'dark'}" data-m="ok" ${okDisabled ? 'disabled' : ''}>${esc(ok)}</button>` : ''}</div>
    </div></div>`;
    const bg = $('.modal-bg', root);
    const done = v => {
      // 关掉时淡出（10-31）：拿一份副本放在原处做动画，原来的位置马上空出来（接着开下一个弹窗不受影响）
      const bg = root.querySelector('.modal-bg');
      if (bg && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        const g = bg.cloneNode(true); g.classList.add('closing'); g.style.pointerEvents = 'none'; document.body.appendChild(g);
        g.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, easing: 'ease-in' }).finished.catch(() => {}).then(() => g.remove());
        g.querySelector('.modal')?.animate([{ transform: 'none' }, { transform: 'translateY(8px) scale(.985)' }], { duration: 160, easing: 'ease-in' });
      }
      root.innerHTML = ''; document.removeEventListener('keydown', key); resolve(v);
    };
    const okv = () => input ? $('#m-input').value.trim() : true;
    const key = e => { if (e.key === 'Escape') done(false); if (e.key === 'Enter' && input && document.activeElement?.id === 'm-input') done(okv()); };
    document.addEventListener('keydown', key);
    bg.addEventListener('click', e => {
      if (e.target === bg) return done(false);
      const b = e.target.closest('[data-m]'); if (!b) return;
      if (b.dataset.m === 'ok') {
        // 批注 #193（11-03）：定时选了「每周」却没勾哪几天：不能保存，弹窗留着
        const bd = root.querySelector('.be-days');
        if (bd && bd.querySelector('input[name="wd"][value="week"]')?.checked && ![...bd.querySelectorAll('[data-wd]')].some(x => x.checked)) { toast('选了「每周」，还要勾上哪几天', true); return; }
        const ctl = root._okValue; done(ctl ? ctl() : okv());
      }
      else if (b.dataset.m === 'alt') { const ctl = root._okValue; done({ alt: true, value: ctl ? ctl() : okv() }); }
      else done(false);
    });
    root._okValue = null;
    if (onMount) onMount($('.modal', root), fn => { root._okValue = fn; });
    setTimeout(() => (input ? $('#m-input') : $('[data-m="ok"]', root))?.focus(), 30);
  });
}
const confirmBox = (title, html, ok = '确定', danger = false) => modal({ title, body: html, ok, danger });

function lightbox(src) {
  const d = document.createElement('div'); d.className = 'lightbox';
  d.innerHTML = `<img src="${esc(src)}" alt="截图">`; d.onclick = () => d.remove();
  document.body.appendChild(d);
}

// ------------------------------------------------------------------ 数据加载
async function loadState() {
  const st = await api('GET', '/api/state');
  S.state = st;
  S.labels = Object.assign({}, ...st.games.map(g => g.labels || {})); // 任务显示名：随游戏卡片一起来
  const t = bjMs(st.now); if (!isNaN(t)) S.bjOffset = t - Date.now();
  await applyTheme(st.appearance || {});
  return st;
}
// 界面主题（评测 #8）：自带主题是 static/themes/<id>.css；自建主题「user:<id>」= 基于的自带主题 + 改过的几个变量
async function applyTheme(ap) {
  const want = ap.theme || 'minimal';
  if (S.themeApplied === want) return;
  if (!S.themes || (want.startsWith('user:') && !S.themes.user.some(t => t.id === want))) S.themes = await api('GET', '/api/themes');
  const u = S.themes.user.find(t => t.id === want);
  $('#theme-css').href = `/static/themes/${encodeURIComponent(u ? u.base : want)}.css`;
  $('#theme-vars').textContent = u ? `:root{${Object.entries(u.vars).map(([k, v]) => `${k}:${v}`).join(';')}}` : '';
  S.themeApplied = want;
  unBtn();
}
// 各页标题上方那一行统一写法：「游戏日 10-28 周三 · 最早刷新04:00」（各游戏刷新时间不同，只写最早的）
function dayEyebrow(day) {
  const rf = (S.state?.games || []).filter(g => g.available && g.refresh).map(g => g.refresh).sort()[0];
  return `游戏日 ${dayLabel(day || reportDay())}${rf ? ` · 最早刷新${rf}` : ''}`;
}
function reportDay() { return S.state?.game_day || 'today'; }  // 总览用的游戏日：后台给的 game_day
async function loadReport(day) { S.report = await api('GET', `/api/report/${day || reportDay()}`); return S.report; }
async function schema(gid, force = false) {
  if (force || !S.schemas[gid]) S.schemas[gid] = await api('GET', `/api/schema/${encodeURIComponent(gid)}`);
  return S.schemas[gid];
}
async function switches(gid, force = false) { // 任务开关：从 schema 里取（和计划编辑看到的是同一份）
  if (force || !S.switches[gid]) {
    await schema(gid, force);
    S.switches[gid] = (S.schemas[gid].tasks || []).filter(t => !t.placeholder).map(t => ({ task: t.name, disabled: !!t.disabled,
      reason: t.disabled_reason || '', source: t.switch_source || '', config_reason: t.config_reason || '', untested: !!t.untested, notice: t.notice || '' }));
  }
  return S.switches[gid];
}

// ------------------------------------------------------------------ 顶栏、运行条
function renderTop() {
  const r = S.route;
  // 游戏页按分页对应顶栏：任务预设 → 任务预设，运行记录 → 运行记录，其它 → 总览
  const nav = r.view === 'game' ? ({ routine: 'presets', runs: 'report' }[r.tab] || 'home') : r.view;
  $('#top').innerHTML = `
    <div class="brand">
      <a class="logo" href="#/">${ICON.logo}<b>日常管家</b></a>
      <nav class="nav"><a href="#/" class="${nav === 'home' ? 'on' : ''}">总览</a><a href="#/schedule" class="${nav === 'schedule' ? 'on' : ''}">日程</a><a href="#/news" class="${nav === 'news' ? 'on' : ''}">活动</a><a href="#/presets" class="${nav === 'presets' ? 'on' : ''}">任务预设</a><a href="#/report" class="${nav === 'report' ? 'on' : ''}">运行记录</a><a href="#/settings" class="${nav === 'settings' ? 'on' : ''}">设置</a></nav>
    </div>
    <div class="tools">
      <span class="clock num" id="clock"></span>

      ${WV ? `<div class="winctl"><button type="button" data-win="min" title="最小化（收到右下角托盘，后台照常跑）" aria-label="最小化"><svg viewBox="0 0 10 10"><path d="M0 5h10"/></svg></button><button type="button" data-win="max" title="${WIN_MAX ? '还原' : '最大化'}" aria-label="${WIN_MAX ? '还原' : '最大化'}"><svg viewBox="0 0 10 10">${WIN_MAX ? '<path d="M2.5 .5h7v7M.5 2.5h7v7h-7z"/>' : '<path d="M.5 .5h9v9h-9z"/>'}</svg></button><button type="button" class="x" data-win="close" title="关闭（收到托盘，后台和自动调度继续跑）" aria-label="关闭"><svg viewBox="0 0 10 10"><path d="M0 0l10 10M10 0L0 10"/></svg></button></div>` : ''}
    </div>`;
  tickClock();
}
// 无边框窗口（GameButler.exe 里）：顶栏当标题栏。拖空白处移动、双击最大化 / 还原，右上角 — □ ✕
const WV = window.chrome?.webview;
let WIN_MAX = false, WV_PICK = false;
const PICKS = new Map();
// 选文件夹（11-02）：在 GameButler.exe 的窗口里由启动器自己弹（挂在管家窗口上，不会被挡住）；在浏览器里打开时由后台弹
async function pickFolder(title) {
  if (WV && WV_PICK) {
    const id = String(Date.now()) + Math.random().toString(36).slice(2, 6);
    return new Promise(res => { PICKS.set(id, res); WV.postMessage(`pick:${id}\n${title}`); });
  }
  toast('在电脑上弹出了文件夹选择窗口；也可以在下一步直接粘贴路径');
  return (await api('POST', '/api/browse', { title })).path || '';
}
if (WV) {
  document.documentElement.classList.add('frameless');
  WV.addEventListener('message', e => {
    const d = String(e.data || '');
    if (d === 'cap:pick') { WV_PICK = true; return; }  // 11-02：启动器能自己弹选文件夹窗口
    if (d.startsWith('pick:')) { const nl = d.indexOf('\n'); const id = d.slice(5, nl < 0 ? undefined : nl); const cb = PICKS.get(id); if (cb) { PICKS.delete(id); cb(nl < 0 ? '' : d.slice(nl + 1)); } return; }
    if (d !== 'max' && d !== 'normal') return;
    const m = d === 'max';
    if (m === WIN_MAX) return;
    WIN_MAX = m; document.documentElement.classList.toggle('win-max', m);
    if ($('#top')?.innerHTML) renderTop();
  });
  WV.postMessage('hello');
  // 窗口上边框：系统的边框只留了左右下，上边是页面顶上这一条（左上、右上两个角也能拉）
  const edge = document.createElement('div'); edge.id = 'win-edge';
  edge.innerHTML = '<i data-size="13"></i><i data-size="12"></i><i data-size="14"></i>';
  document.body.appendChild(edge);
  edge.addEventListener('mousedown', e => { const h = e.target.dataset?.size; if (h && e.button === 0) { e.preventDefault(); WV.postMessage('size:' + h); } });
  let last = 0, lx = 0, ly = 0;
  document.addEventListener('mousedown', e => {
    if (e.button !== 0 || e.clientY > 64 || document.querySelector('.modal-bg') || e.target.closest('#win-edge')) return;
    if (e.target.closest('a,button,input,select,textarea,label,[data-act],[data-win],#un-btn,.un-pin,.ctx')) return;
    e.preventDefault();
    const t = Date.now(), dbl = t - last < 450 && Math.abs(e.clientX - lx) < 6 && Math.abs(e.clientY - ly) < 6;
    last = dbl ? 0 : t; lx = e.clientX; ly = e.clientY;
    WV.postMessage(dbl ? 'max' : 'drag');
  });
  document.addEventListener('click', e => { const b = e.target.closest('[data-win]'); if (b) WV.postMessage(b.dataset.win); });
}
function tickClock() {
  const el = $('#clock'); if (!el) return;
  const b = new Date(nowBjMs() + 8 * 3600e3), l = new Date();
  el.innerHTML = `北京 <b>${pad(b.getUTCHours())}:${pad(b.getUTCMinutes())}</b>　本机 <b>${pad(l.getHours())}:${pad(l.getMinutes())}</b>`;
  el.title = `北京时间 ${pad(b.getUTCMonth() + 1)}-${pad(b.getUTCDate())}，电脑时间 ${pad(l.getMonth() + 1)}-${pad(l.getDate())}`;
}

// 运行行（B 极简 L3）：放在当前页标题下面（没有标题的页放在顶栏下面）；#bars 这个节点一直留着，页面重画时挪回去
const BARS = document.getElementById('bars');
function placeBars() {
  const slot = document.querySelector('#app .sch-bars-slot');  // 批注 #205：日程页放进「今天」里，「接下来」之前
  if (slot) { if (BARS.parentElement !== slot) slot.appendChild(BARS); return; }
  const h = document.querySelector('#app .hero, #app .ghero');
  if (h) { if (h.nextElementSibling !== BARS) h.after(BARS); }
  else if (BARS.previousElementSibling !== $('#top')) $('#top').after(BARS);
}
new MutationObserver(placeBars).observe(document.getElementById('app'), { childList: true, subtree: true });
const triLine = (cls, title, detail, acts, sub = '') => `<section class="runline ${cls}"><div class="rl-top"><div class="rl-l"><i class="tri"></i><b>${title}</b>${detail ? `<span class="rl-d">${detail}</span>` : ''}</div>${acts ? `<div class="rl-r">${acts}</div>` : ''}</div>${sub ? `<div class="rl-sub">${sub}</div>` : ''}</section>`;
function renderBars() {
  const R = S.running, P = R?.paused || S.state?.paused;
  let h = '';
  if (S.offline) h += triLine('warm', '连不上管家后台', esc(S.offline), '', '确认托盘里的管家还开着，或重新打开 GameButler.exe。');
  if (R?.running) {
    const c = R.current || {}; const g = game(c.game);
    const since = bjMs(c.since), started = bjMs(R.started);
    const left = (R.games || []).filter(x => !(R.done_games || []).includes(x) && x !== c.game).map(x => game(x)?.name || x);
    const n = g?.total ? Math.min(g.total, (g.done || 0) + 1) : 0;
    const pct = g?.total ? Math.round((g.done || 0) / g.total * 100) : 0;
    const state = R.stop_requested ? '正在中止 · ' : R.suspended ? '已原地暂停 · ' : '';
    const sub = [Array.isArray(c.focus) && c.focus.length ? focusHtml(c.focus[c.focus.length - 1]) : '',
      R.started ? `本次 ${esc(hm(R.started))} 开始，已 ${dur(nowBjMs() - started)}` : '', left.length ? `之后 ${esc(left.map(x => splitName(x)[0]).join('、'))}` : ''].filter(Boolean).join(' · ');
    h += `<section class="runline"${g ? ` style="--gc:${newsColor(g.id)}"` : ''}>
      <div class="rl-top"><div class="rl-l"><span class="dot live"></span>
        <b>${g ? `<a href="#/g/${esc(g.id)}/today" style="color:inherit;text-decoration:none">${esc(splitName(g.name)[0])}</a> · ` : ''}${esc(tn(c.task) || '准备中')}${c.attempt > 1 ? `（第 ${c.attempt} 次）` : ''}</b>
        <span class="rl-d">${state}${n ? `第 ${n} / ${g.total} 项` : ''}${c.since ? `${n ? ' · ' : ''}已 ${dur(nowBjMs() - since)}` : ''}</span></div>
      <div class="rl-r">${R.stop_requested ? '' : `<button class="btn ghost" data-act="skip-cur" data-scope="task" title="停下这个任务，接着跑这个游戏后面的（今天不再自动跑它）">跳过当前任务</button><button class="btn ghost" data-act="skip-cur" data-scope="game" title="这个游戏这次剩下的都不跑，接着下一个游戏">跳过当前序列</button>`}${R.can_suspend && !R.stop_requested ? `<button class="btn ghost" data-act="suspend" data-on="${R.suspended ? '0' : '1'}" title="按 BetterGI 的暂停键，停在原地；期间不算超时">${R.suspended ? '继续' : '原地暂停'}</button>` : ''}
        <button class="btn warn" data-act="stop" title="停下当前任务，整个队列（排着的、定时的）都先不跑" ${R.stop_requested ? 'disabled' : ''}>${R.stop_requested ? '正在中止' : '中止队列'}</button></div></div>
      ${sub ? `<div class="rl-sub">${sub}</div>` : ''}
      <div class="rl-bar" aria-hidden="true"><i style="width:${pct}%"></i></div>
    </section>`;
  }
  const HALT = P?.reason === '中止队列';
  if (HALT && !R?.running) { // 中止队列：和「还没跑完」合成一条（11-02）
    const r = S.resume?.games?.length ? S.resume : null;
    h += triLine('warm', r ? `队列已中止 · 还没跑完：${esc(namesOf(r.games))}${r.only ? `（选中的 ${r.only.length} 个任务）` : ''}` : '队列已中止',
      `${P.since ? `${esc(mdhm(P.since))} 起` : ''}${r?.task ? ` · 停在「${esc(tn(r.task))}」` : ''}`,
      r ? `<button class="btn ghost" data-act="resume-drop">不继续了</button><button class="btn warn" data-act="resume-run">继续</button>`
        : '<button class="btn warn" data-act="resume">恢复调度</button>',
      r ? '什么都不会自动开始（定时的也等着）。「继续」：已完成的跳过，停下的那个从头再跑。「不继续了」：放弃剩下的，回到平常调度。'
        : '什么都不会自动开始（定时的也等着）；点「开始」「立即开始」也会恢复；「加入队列」的只排着，等恢复后再跑。');
  } else if (!R?.running && S.resume?.games?.length && !P) {
    const r = S.resume;
    h += triLine('warm', `还没跑完：${esc(namesOf(r.games))}${r.only ? `（选中的 ${r.only.length} 个任务）` : ''}`,
      `已停止${r.source ? `（${esc(r.source)}${r.stopped_at ? ' ' + esc(mdhm(r.stopped_at)) : ''}）` : ''}${r.task ? ` · 停在「${esc(tn(r.task))}」` : ''}`,
      `<button class="btn ghost" data-act="resume-drop">不继续了</button><button class="btn warn" data-act="resume-run">继续</button>`,
      '「继续」：已完成的任务跳过，停下的那个从头再跑。「不继续了」：放弃剩下的，之后照常调度。');
  }
  const Q = R?.prompt; // 电脑端游戏开跑前的提醒：启动器卡片和这里都能回答
  if (Q && !R?.running) {
    h += triLine('warm', `准备运行 ${esc(Q.name)}：你在用电脑，现在开始吗？`, '',
      Object.entries(Q.choices).map(([k, v]) => `<button class="btn ${k === 'now' ? 'warn' : 'ghost'}" data-act="answer" data-choice="${k}">${esc(v)}</button>`).join(''),
      `<span style="white-space:pre-line">${esc(Q.text)}</span>`);
  }
  const hideAdmin = (() => { try { return localStorage.getItem('gb-admin-hint') === '1'; } catch (e) { return false; } })();
  if (S.state && S.state.admin === false && !hideAdmin && S.state.games.some(g => g.available && g.kind === 'bettergi')) {
    h += `<section class="runline thin"><div class="rl-top"><div class="rl-l">管家现在不是以管理员身份运行，启动 BetterGI 时可能会弹确认窗口。用 GameButler.exe 启动管家就不会弹。</div>
      <div class="rl-r"><button class="btn ghost" data-act="admin-hide">不再提示</button></div></div></section>`;
  }
  // 工具有新版本（11-01）：只在总览上提示一行；同一个版本点过「不再提示」就不再出现
  if (S.route?.view === 'home') {
    if (S.updates === undefined) { S.updates = null; api('GET', '/api/updates').then(r => { S.updates = r; renderBars(); }).catch(() => {}); }
    const seen = (() => { try { return JSON.parse(localStorage.getItem('gb-upd-seen') || '{}'); } catch (e) { return {}; } })();
    const nw = (S.updates?.tools || []).filter(t => t.newer && seen[t.name] !== t.latest);
    if (nw.length) h += `<section class="runline thin"><div class="rl-top"><div class="rl-l">有新版本：${nw.map(t => `${esc(t.name)} ${esc(t.version)} → <b>${esc(t.latest)}</b>`).join('；')}</div>
      <div class="rl-r">${nw.map(t => `<button class="btn ghost" data-act="open-tool" data-updater="1" data-gid="${esc(t.games[0])}" title="打开 ${esc(t.name)}，用它自带的更新器更新">打开 ${esc(t.name)} 更新</button>`).join('')}<button class="btn ghost" data-act="upd-hide" data-v="${esc(JSON.stringify(Object.fromEntries(nw.map(t => [t.name, t.latest]))))}">不再提示</button></div></div></section>`;
  }
  // 11-09：MAA 工具更新后的新功能（新任务、任务预设里用到的选项多了哪些值）：点「看看」去任务预设里选
  for (const u of (S.state?.tool_updates || [])) {
    const parts = [];
    if (u.new_tasks?.length) parts.push(`新任务：${u.new_tasks.map(x => `「${esc(tn(x))}」`).join('、')}`);
    for (const c of (u.changes || []).slice(0, 4)) parts.push(`${esc(tn(c.task))} ·「${esc(c.option)}」${c.new ? '是新选项' : '新增'}：${esc(c.cases.slice(0, 4).join('、'))}${c.cases.length > 4 ? ' 等' : ''}`);
    if ((u.changes || []).length > 4) parts.push(`还有 ${u.changes.length - 4} 处`);
    if (u.gone_tasks?.length) parts.push(`去掉了：${u.gone_tasks.map(x => `「${esc(x)}」`).join('、')}`);
    h += triLine('warm', `${esc(splitName(u.name)[0])} 的脚本更新了${u.to ? `（${u.from ? esc(u.from) + ' → ' : ''}${esc(u.to)}）` : ''}${parts.length ? '，有新功能' : ''}`, '',
      `<button class="btn ghost" data-act="tool-upd-ok" data-gid="${esc(u.game)}">知道了</button><button class="btn warn" data-act="tool-upd-go" data-gid="${esc(u.game)}">去任务预设看看</button>`,
      parts.length ? parts.join('<br>') : '没有影响你任务预设的变化。');
  }
  if (P && !HALT) {
    h += triLine('warm', '已让出电脑，调度暂停', `${esc(P.reason || '让出电脑')}${P.since ? `（${esc(mdhm(P.since))} 起）` : ''}`,
      '<button class="btn warn" data-act="resume">恢复调度</button>', '什么都不会开始，你手动排的也等恢复后再跑。');
  }
  // 运行行每 1–2 秒刷新一次（用时在变）：按着按钮的时候先不换，不然这次点击会落空，要点两次（11-02）
  if (BARS.innerHTML === h) return;
  if (BARS_PRESSED) { BARS_PENDING = true; return; }
  BARS.innerHTML = h;
  placeBars();
}

// ------------------------------------------------------------------ 拖动排序（10-28）：用鼠标按下 / 移动 / 松开自己做，
// 不用浏览器自带的拖放（管家窗口里的拖放不可靠：日程、右栏卡片拖了不生效）。
// box：容器选择器；item：可拖的行；handle：按住哪里开始拖；onDrop(拖的行, 放到哪一行, 是不是放在它前面)
function pointerSort({ box, item, handle, can = () => true, onDrop }) {
  // 拖动排序（10-31 加动效）：拖着的那一项跟着鼠标走，别的项实时让位（FLIP 动画），松手后滑进空位，再交给 onDrop
  document.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const h = e.target.closest?.(handle); if (!h) return;
    const el = h.closest(item); const root = h.closest(box);
    if (!el || !root || !can(el)) return;
    e.preventDefault();
    const sibs = () => [...el.parentElement.children].filter(x => x !== el && x.matches(item) && can(x));
    const origNext = el.nextElementSibling;
    const grab = e.clientY - el.getBoundingClientRect().top;
    let started = false, lastY = e.clientY;
    const natTop = () => { const t = el.style.transform; el.style.transform = ''; const r = el.getBoundingClientRect().top; el.style.transform = t; return r; };
    const flip = fn => {
      const list = sibs(); const first = new Map(list.map(x => [x, x.getBoundingClientRect().top]));
      fn();
      list.forEach(x => { const d = first.get(x) - x.getBoundingClientRect().top; if (d) x.animate([{ transform: `translateY(${d}px)` }, { transform: 'none' }], { duration: 200, easing: 'cubic-bezier(.2,.7,.3,1)' }); });
    };
    const move = ev => {
      if (!started && Math.abs(ev.clientY - e.clientY) < 4) return;
      if (!started) { started = true; el.classList.add('dragging'); document.body.classList.add('sorting'); }
      lastY = ev.clientY;
      const top = ev.clientY - grab;
      const list = sibs();  // 不含拖着的这一项，按页面上的先后
      // 按鼠标位置算插到哪（11-02 批注 #156）：以前按拖着那一项的中心算，高矮不同的行会在两个位置之间来回跳
      const want = list.find(x => { const r = x.getBoundingClientRect(); return r.top + r.height / 2 > ev.clientY; }) || null;
      const kids = [...el.parentElement.children];
      const curNext = kids.slice(kids.indexOf(el) + 1).find(x => list.includes(x)) || null;
      if (want !== curNext) flip(() => { if (want) want.before(el); else list[list.length - 1]?.after(el); });
      el.style.transform = `translateY(${top - natTop()}px)`;
    };
    const up = () => {
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up);
      document.body.classList.remove('sorting');
      if (!started) return;
      const off = lastY - grab - natTop();
      el.style.transform = '';
      el.animate([{ transform: `translateY(${off}px)` }, { transform: 'none' }], { duration: 180, easing: 'cubic-bezier(.2,.7,.3,1)' })
        .finished.catch(() => {}).then(() => el.classList.remove('dragging'));
      const eat = ev => { ev.stopPropagation(); ev.preventDefault(); };  // 拖完松手不算点击
      document.addEventListener('click', eat, { capture: true, once: true });
      setTimeout(() => document.removeEventListener('click', eat, { capture: true }), 80);
      if (el.nextElementSibling === origNext) return;  // 没挪位置
      const next = [...el.parentElement.children].slice([...el.parentElement.children].indexOf(el) + 1).find(x => x.matches(item) && can(x));
      const prev = [...el.parentElement.children].slice(0, [...el.parentElement.children].indexOf(el)).reverse().find(x => x.matches(item) && can(x));
      setTimeout(() => { if (next) onDrop(el, next, true); else if (prev) onDrop(el, prev, false); }, 190);  // 等滑进空位的动画走完再重画
    };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
  });
}

// 滚动条：平时藏起来，滚动时、鼠标靠近右边时才出来（浅色半透明，样式在 app.css 末尾）
(() => {
  const root = document.documentElement; let t = 0;
  const show = () => { root.classList.add('sb-on'); clearTimeout(t); t = setTimeout(() => root.classList.remove('sb-on'), 1200); };
  window.addEventListener('scroll', show, { passive: true });
  document.addEventListener('mousemove', e => { if (e.clientX > root.clientWidth - 24 && root.scrollHeight > root.clientHeight) show(); }, { passive: true });
})();

document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="upd-hide"]'); if (!b) return;
  try { const seen = JSON.parse(localStorage.getItem('gb-upd-seen') || '{}'); localStorage.setItem('gb-upd-seen', JSON.stringify({ ...seen, ...JSON.parse(b.dataset.v) })); } catch (x) { /* 记不住就算了 */ }
  renderBars();
});

let BARS_PRESSED = false, BARS_PENDING = false;
BARS.addEventListener('pointerdown', () => { BARS_PRESSED = true; });
document.addEventListener('pointerup', () => { if (!BARS_PRESSED) return; BARS_PRESSED = false; if (BARS_PENDING) { BARS_PENDING = false; setTimeout(renderBars, 0); } }, true);
document.addEventListener('pointercancel', () => { BARS_PRESSED = false; }, true);
