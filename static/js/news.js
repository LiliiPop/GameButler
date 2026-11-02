// 日常管家界面 · 活动日历。和其它 static/js/*.js 共用全局（不打包，按 index.html 里的顺序加载）。

'use strict';

// ------------------------------------------------------------------ 活动日历
// 时间：后台给北京时间 "YYYY-MM-DD HH:MM"；界面同时写北京时间和电脑本地时间
const localMdhm = ms => { const d = new Date(ms); return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const bothTimes = bj => { const ms = bjMs(bj); return isNaN(ms) ? '' : `${mdhm(bj)}（北京时间）· 本地 ${localMdhm(ms)}`; };
// 开始时间：「10月22日更新后」照原话显示（不写 00:00）；开始时间不知道的（代号鸢活动页）写「不晚于 第一次读到的时间」
const newsStart = it => it.forecast ? `预计 ${mdhm(it.start).slice(0, 5)}（${it.start_note || '预告'}，以正式公告为准）` : it.start_note === '最早读到' ? `不晚于 ${bothTimes(it.start)}`
  : it.start_note ? `${mdhm(it.start).slice(0, 5)} ${it.start_note}（北京时间）` : bothTimes(it.start);
const leftText = bj => {
  const ms = bjMs(bj) - nowBjMs(); if (isNaN(ms)) return '';
  if (ms <= 0) return '已结束';
  const h = ms / 3600e3; return h < 24 ? `剩 ${Math.max(1, Math.round(h))} 小时` : `剩 ${Math.floor(h / 24)} 天`;
};
const gameName = gid => game(gid)?.name || gid;
const shortName = gid => splitName(gameName(gid))[0];
function newsColor(gid) { const g = game(gid) || { id: gid }; return tint(g, (S.state?.games || []).indexOf(game(gid))); }

async function renderNews() {
  const keepY = S.route.view === 'news' ? window.scrollY : 0, keepG = S.route.view === 'news' ? ($('.gscroll')?.scrollTop || 0) : 0;
  let d;
  try { d = await api('GET', '/api/news'); } catch (e) { $('#app').innerHTML = `<div class="glass skeleton">${esc(e.message)}</div>`; return; }
  if (S.route.view !== 'news') return;
  S.news = d;
  syncNewsOff(d);
  const N = S.newsUi || (S.newsUi = { month: null, off: new Set(), slide: 0, view: (() => { try { return localStorage.getItem('gb-news-view') || 'week'; } catch (e) { return 'week'; } })() });
  const today = reportDay() === 'today' ? new Date(nowBjMs() + 8 * 3600e3).toISOString().slice(0, 10) : reportDay();
  if (!N.month) N.month = today.slice(0, 7);
  // 持续超过 60 天的是常驻说明（防沉迷、公平运营声明之类），不进日历和轮播
  const longTerm = it => it.start && it.end && bjMs(it.end) - bjMs(it.start) > 60 * 864e5;
  const items = (d.items || []).filter(it => !N.off.has(it.game) && !longTerm(it) && !it.hidden);
  const gids = [...new Set((d.items || []).map(it => it.game))].sort((a, b) => (S.state.games.findIndex(g => g.id === a)) - (S.state.games.findIndex(g => g.id === b)));
  const banners = newsBanners(d, N.focus);  // 点了上面某个游戏：轮播和日历都只看它的
  N.banners = banners; if (N.slide >= banners.length) N.slide = 0;
  const lastFetch = (d.sources || []).map(s => s.fetched).sort().pop() || '';
  const bad = (d.sources || []).filter(s => !s.ok);
  $('#app').innerHTML = `<div style="display:flex;flex-direction:column;gap:20px">
    <section class="hero">
      <div><div class="eyebrow num">${esc(dayEyebrow())}</div><h1 style="font-size:30px">活动</h1></div>
      <div class="side">
        <div class="chips">${gids.filter(g => !N.off.has(g)).map(g => `<button type="button" class="gchip${N.focus === g ? ' on' : ''}" data-act="news-focus" data-gid="${esc(g)}" aria-pressed="${N.focus === g}" title="${N.focus === g ? '再点一下看全部游戏' : '轮播只看这个游戏的活动'}"><i style="background:${newsColor(g)}"></i>${esc(shortName(g))}</button>`).join('')}</div>
        <button class="btn sm" data-act="news-filter">筛选与关注</button>
        <div class="news-q${N.qOpen || N.q ? ' open' : ''}"><button class="btn icon sm" data-act="news-search" aria-label="搜索活动">${ICON.search}</button><input type="search" id="news-q" value="${esc(N.q || '')}" aria-label="搜索活动"></div>
      </div>
    </section>
    <div id="news-res">${N.q ? newsSearchHtml(d.items || [], N.q) : ''}</div>
    ${trackPromptHtml(d)}
    ${banners.length ? bannerHtml(banners, N.slide) : `<section class="glass empty">${(d.items || []).length ? '现在没有带题图的进行中活动' : '还没有读到活动。管家启动后会自动读一次，也可以点右上角「刷新」。'}</section>`}
    ${ganttHtml(N.focus ? items.filter(it => it.game === N.focus) : items, N.month, today)}
    <section class="glass panel">
      <div class="ph"><h3>来源</h3><span class="small faint">${d.fetching ? `<b style="color:var(--blue-ink)">正在读取${d.fetching_now ? `：${esc(d.fetching_now)}` : '…'}</b> · ` : ''}${lastFetch ? `上次读取 ${esc(mdhm(lastFetch))}（北京时间）` : '还没读取过'}${bad.length ? ` · <span style="color:var(--orange-ink)">${bad.length} 个来源没读到</span>` : ''}</span></div>
      <div class="src-list">${(d.sources || []).map(s => `<div class="src"><i style="background:${newsColor(s.game)}"></i><b>${esc(shortName(s.game))}</b><span class="faint xsmall">${esc(SRC_TYPE[s.type] || s.type)}</span>${s.ok ? `<span class="badge ok">${s.count} 条</span>` : `<span class="badge bad" title="${esc(s.error)}">没读到</span><span class="xsmall faint err-t">${esc(s.error)}</span>`}
        ${s.ok && s.incomplete ? `<span class="badge warn" title="${esc((s.incomplete_why || []).join('\n'))}">${s.incomplete} 条没读全</span><span class="xsmall faint err-t">${esc((s.incomplete_why || []).join('；'))}</span>` : ''}
        ${!s.ok || s.incomplete ? `<button type="button" class="btn xs" data-act="news-refresh" data-src="${esc(s.id)}">重读</button>` : ''}</div>`).join('') || '<div class="small faint">—</div>'}</div>
    </section>
  </div>`;
  if (keepG && $('.gscroll')) $('.gscroll').scrollTop = keepG;
  if (keepY) window.scrollTo(0, keepY);
  startBannerTimer();
}
const SRC_TYPE = { mihoyo_ann: '游戏内公告', mys_news: '米游社官方', html_list: '官网新闻', papegames: '官网新闻', ingame: '游戏内（截图识别）', bili_dyn: 'B 站官方号' };

// 轮播：带题图、还没结束的活动 / 外观；没写结束时间的（外观上新新闻等）只放最近 14 天发布的。活动页和总览共用
function newsBanners(d, focus = null) {
  const N = newsUiInit(); const nowMs = nowBjMs();
  const longTerm = it => it.start && it.end && bjMs(it.end) - bjMs(it.start) > 60 * 864e5;
  const live = it => !it.end || bjMs(it.end) >= nowMs;
  const fresh = it => it.end || (it.start && nowMs - bjMs(it.start) < 14 * 864e5);
  const list = (d.items || []).filter(it => !N.off.has(it.game) && !longTerm(it) && !it.hidden && it.img && live(it) && fresh(it) && it.kind !== '常驻' && (it.kind !== '公告' || it.end) && (!focus || it.game === focus))
    .sort((a, b) => (bjMs(a.end) || 9e15) - (bjMs(b.end) || 9e15))
    .reduce((by, it) => { (by[it.game] = by[it.game] || []).push(it); return by; }, {})
    , out = [];
  // 11-02：各游戏轮流取（以前按结束时间取前 12 张，原神一个游戏就占满了）；每轮每个游戏一张，最多 16 张
  const queues = Object.values(list);
  for (let k = 0; out.length < 16 && queues.some(q => q.length > k); k++) queues.forEach(q => { if (q[k] && out.length < 16) out.push(q[k]); });
  return out;
}
function bannerHtml(list, i, home = false) {
  const it = list[i];
  const c = newsColor(it.game);
  return `<section class="banner glass${home ? ' home' : ''}" data-act="${home ? 'news-home' : 'news-open'}" data-id="${esc(it.id)}" tabindex="0" aria-label="${esc(tn(it.title))}${home ? '（点开去活动页）' : ''}">
    <div class="bblur" style="background-image:url('/news-img/${encodeURIComponent(it.img)}')"></div>
    <img class="bimg" src="/news-img/${encodeURIComponent(it.img)}" alt="" onload="bannerFit(this)">
    <div class="bshade"></div>
    <div class="btext">
      <span class="gtag" style="background:${c};color:${onColor(c)}">${esc(shortName(it.game))}</span>
      <h2>${it.starred ? '<span class="star-on" title="已关注">★</span> ' : ''}${esc(tn(it.title))}</h2>
      <div class="small">${it.end ? `${esc(leftText(it.end))} · 结束 ${esc(bothTimes(it.end))}` : it.start ? `${it.kind === '外观' ? '上新' : '发布'} ${esc(bothTimes(it.start))}` : ''}</div>
    </div>
    ${list.length > 1 ? `<button class="bnav prev" data-act="news-slide" data-d="-1" aria-label="上一张">${ICON.back}</button><button class="bnav next" data-act="news-slide" data-d="1" aria-label="下一张">${ICON.right}</button>
    <div class="bdots">${list.map((x, k) => `<button class="${k === i ? 'on' : ''}" data-act="news-dot" data-k="${k}" aria-label="第 ${k + 1} 张"></button>`).join('')}</div>` : ''}
  </section>`;
}
// 题图按原始大小处理：竖图用竖版排法；小图（游戏内截下来的缩略图，例如时绘只有 342×142）最多放大 1.6 倍，不硬拉满变糊
function bannerFit(img) {
  const b = img.closest('.banner'); if (!b) return;
  // 竖版长图（官方号的活动说明长图，高是宽的 3 倍以上）：只露最上面的标题部分；卡面这类竖图（1.4–1.8 倍）照竖图排（11-02）
  if (img.naturalHeight > img.naturalWidth * 2.2) b.classList.add('tall');
  else if (img.naturalHeight > img.naturalWidth) b.classList.add('portrait');
  else if (img.naturalWidth < 900) {  // 小图：最多放大到屏幕上 1.25 倍（按 Windows 的缩放算），再大就糊了（11-02）
    const k = 1.25 / (window.devicePixelRatio || 1);
    b.classList.add('small'); img.style.maxWidth = Math.round(img.naturalWidth * k) + 'px'; img.style.maxHeight = Math.round(img.naturalHeight * k) + 'px';
  }
}
// 换一张（10-31 加动效）：旧的那张向一边滑出、淡掉，新的从另一边滑进来；dir = 1 往后，-1 往前
function setSlide(k, dir) {
  const N = S.newsUi; if (!N?.banners?.length) return;
  const n = N.banners.length, was = N.slide;
  N.slide = (k + n) % n;
  if (dir === undefined) dir = k > was ? 1 : -1;
  S.bannerElapsed = 0;
  const box = $('.banner'); if (!box) return;
  const tmp = document.createElement('div'); tmp.innerHTML = bannerHtml(N.banners, N.slide, box.classList.contains('home'));
  const nb = tmp.firstElementChild;
  if (N.slide === was || matchMedia('(prefers-reduced-motion: reduce)').matches) { box.replaceWith(nb); return; }
  const ghost = document.createElement('div'); ghost.className = 'bghost';
  [...box.children].filter(c => !c.matches('.bnav,.bdots')).forEach(c => ghost.appendChild(c));
  box.replaceWith(nb);
  nb.insertBefore(ghost, nb.querySelector('.bnav'));
  const ease = 'cubic-bezier(.2,.7,.3,1)';
  ghost.animate([{ opacity: 1, translate: '0 0' }, { opacity: 0, translate: `${-dir * 48}px 0` }], { duration: 420, easing: ease, fill: 'forwards' }).finished.catch(() => {}).then(() => ghost.remove());
  nb.querySelectorAll(':scope > .bimg, :scope > .btext').forEach(x => x.animate([{ opacity: 0, translate: `${dir * 48}px 0` }, { opacity: 1, translate: '0 0' }], { duration: 480, easing: ease }));
  nb.querySelectorAll(':scope > .bblur').forEach(x => x.animate([{ opacity: 0 }, { opacity: .85 }], { duration: 480 }));
}
// 自动播放：每张停 5 秒，鼠标放在轮播上 / 窗口在后台时暂停计时；当前那个点里有一条进度
function startBannerTimer() {
  clearInterval(S.bannerTimer);
  S.bannerElapsed = 0;
  S.bannerTimer = setInterval(() => {
    if (!['news', 'home'].includes(S.route.view)) { clearInterval(S.bannerTimer); return; }
    if (document.hidden || $('.banner:hover') || (S.newsUi?.banners?.length || 0) < 2) return;
    S.bannerElapsed += 100;
    $('.bdots button.on')?.style.setProperty('--p', Math.min(1, S.bannerElapsed / 5000));
    if (S.bannerElapsed >= 5000) setSlide(S.newsUi.slide + 1, 1);
  }, 100);
}

const mondayOf = day => { const [y, m, d] = day.split('-').map(Number); const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay(); return addDays(day, -((wd + 6) % 7)); };
function ganttHtml(items, month, today) {
  const N = S.newsUi; const view = N.view === 'week' ? 'week' : 'month';
  let t0, t1, dates, title, prevA, nextA, resetA;
  if (view === 'week') {
    const a = N.week || mondayOf(today);
    const [y, m, d] = a.split('-').map(Number);
    t0 = Date.UTC(y, m - 1, d, -8); t1 = t0 + 7 * 864e5;
    dates = Array.from({ length: 7 }, (_, i) => addDays(a, i));
    title = `${+dates[0].slice(5, 7)} 月 ${+dates[0].slice(8)} 日 – ${+dates[6].slice(5, 7)} 月 ${+dates[6].slice(8)} 日`;
    prevA = addDays(a, -7); nextA = addDays(a, 7); resetA = mondayOf(today);
  } else {
    const [y, m] = month.split('-').map(Number);
    const n = new Date(Date.UTC(y, m, 0)).getUTCDate();
    t0 = Date.UTC(y, m - 1, 1, -8); t1 = Date.UTC(y, m, 1, -8); // 北京时间本月 1 日 0 点 ~ 下月 1 日 0 点
    dates = Array.from({ length: n }, (_, i) => `${month}-${pad(i + 1)}`);
    title = `${y} 年 ${m} 月`;
    prevA = `${m === 1 ? y - 1 : y}-${pad(m === 1 ? 12 : m - 1)}`; nextA = `${m === 12 ? y + 1 : y}-${pad(m === 12 ? 1 : m + 1)}`; resetA = today.slice(0, 7);
  }
  const days = dates.length;
  const span = t1 - t0;
  const rows = items.filter(it => it.start && it.end && it.kind !== '常驻' && bjMs(it.end) > t0 && bjMs(it.start) < t1)
    .sort((a, b) => (S.state.games.findIndex(g => g.id === a.game) - S.state.games.findIndex(g => g.id === b.game)) || (bjMs(a.start) - bjMs(b.start)));
  const nowMs = nowBjMs();
  const pct = ms => Math.min(100, Math.max(0, (ms - t0) / span * 100));
  const hc = palName() === '高对比';
  const head = dates.map(ds => {
    const [y, m, d] = ds.split('-').map(Number);
    const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
    return `<div class="gd${wd === 0 || wd === 6 ? ' we' : ''}${ds === today ? ' td' : ''}"><b class="num">${view === 'week' ? `${m}/${d}` : d}</b><span>${view === 'week' ? '周' : ''}${'日一二三四五六'[wd]}</span></div>`;
  }).join('');
  const nowIn = nowMs >= t0 && nowMs < t1;
  const rowHtml = it => {
    const s = bjMs(it.start), e = bjMs(it.end); const c = newsColor(it.game); const fc = onColor(c);
    const l = pct(s), w = Math.max(pct(e) - l, 1.2);
    return `<div class="grow"><div class="glabel">${it.starred ? '<span class="star-on">★</span>' : ''}<span class="cat-dot" title="${esc(it.cat_label || '')}${it.tag && it.tag !== it.cat_label ? ' · ' + esc(it.tag) : ''}">${esc(it.tag || (it.cat_label || '').slice(0, 2))}</span></div>
      <div class="gtrack"><button type="button" class="gbar${it.forecast ? ' forecast' : s > nowMs ? ' upcoming' : ''}${s < t0 ? ' cut-l' : ''}${e > t1 ? ' cut-r' : ''}${e < nowMs ? ' past' : ''}${it.starred ? ' starred' : ''}" style="left:${l}%;width:${w}%;background:${c};color:${fc};--gc:${c}" aria-label="${esc(tn(it.title))}" data-act="news-open" data-id="${esc(it.id)}">
        ${hc ? `<em>${esc(markOf(gameName(it.game)))}</em>` : ''}${it.starred ? '★ ' : ''}<span>${esc(tn(it.title))}</span><small class="num">${it.forecast ? esc(it.start_note || '预告') : `${esc(mdhm(it.end).slice(0, 5))} ${esc(hm(it.end))} 止`}</small></button></div></div>`;
  };
  // 按游戏分组：最左一列写游戏全称（合并单元格）
  const groups = [];
  rows.forEach(it => { const g = groups[groups.length - 1]; if (g && g.id === it.game) g.rows.push(it); else groups.push({ id: it.game, rows: [it] }); });
  const body = groups.map(g => `<div class="ggroup"><div class="ggame" style="--gc:${newsColor(g.id)}"><b>${esc(shortName(g.id))}</b></div><div class="grows">${g.rows.map(rowHtml).join('')}</div></div>`).join('');
  const noTime = items.filter(it => (!it.start || !it.end) && it.kind !== '公告' && it.kind !== '常驻');
  const nav = view === 'week' ? 'news-week' : 'news-month';
  return `<section class="glass gantt">
    <div class="ph"><h3>${esc(title)}</h3>
      <div class="side"><span class="small faint">按北京时间；鼠标移到色块上看题图和本地时间</span>
        <div class="seg" role="group" aria-label="视图"><button type="button" class="${view === 'week' ? 'on' : ''}" data-act="news-view" data-v="week">本周</button><button type="button" class="${view === 'month' ? 'on' : ''}" data-act="news-view" data-v="month">本月</button></div>
        <button class="btn icon xs" data-act="${nav}" data-m="${prevA}" aria-label="${view === 'week' ? '上一周' : '上个月'}">${ICON.back}</button>
        <button class="btn xs" data-act="${nav}" data-m="${resetA}">${view === 'week' ? '回到本周' : '回到本月'}</button>
        <button class="btn icon xs" data-act="${nav}" data-m="${nextA}" aria-label="${view === 'week' ? '下一周' : '下个月'}">${ICON.right}</button></div></div>
    <div class="gscroll"><div class="ggrid${view === 'week' ? ' week' : ''}" style="--days:${days}">
      <div class="ghead"><div class="ggame h"></div><div class="glabel h"></div><div class="gdays">${head}</div></div>
      <div class="gbody">${body || `<div class="empty small">这${view === 'week' ? '周' : '个月'}没有带起止时间的活动</div>`}</div>
      ${nowIn ? `<div class="gnow" style="left:calc(var(--gcol) + var(--lab) + (100% - var(--gcol) - var(--lab)) * ${pct(nowMs) / 100})"><span>今天 · 游戏日 ${esc(dayLabel(today))}</span></div>` : ''}
    </div></div>
    ${noTime.length ? `<details class="notime"><summary class="small muted">还有 ${noTime.length} 条没写清起止时间的活动</summary>${noTime.map(it => `<div class="small"><i style="background:${newsColor(it.game)}"></i>${esc(shortName(it.game))} · <button type="button" class="linkbtn" data-act="news-open" data-id="${esc(it.id)}">${esc(tn(it.title))}</button></div>`).join('')}</details>` : ''}
  </section>`;
}
// 鼠标移到甘特色块上：浮出题图 + 完整标题 + 起止时间（北京 / 本地）
function newsPop(btn) {
  let pop = $('#gpop');
  if (!btn) { if (pop) pop.hidden = true; return; }
  const it = (S.news?.items || []).find(x => x.id === btn.dataset.id); if (!it) return;
  if (!pop) { pop = document.createElement('div'); pop.id = 'gpop'; pop.className = 'gpop glass'; document.body.appendChild(pop); }
  pop.innerHTML = `${it.img ? `<div class="gpop-img"><img src="/news-img/${encodeURIComponent(it.img)}" alt="" onload="if(this.naturalHeight>this.naturalWidth*2.2)this.classList.add('tall')"></div>` : ''}
    <div class="gpop-t"><span class="gtag" style="background:${newsColor(it.game)};color:${onColor(newsColor(it.game))}">${esc(shortName(it.game))}</span><b>${esc(tn(it.title))}</b></div>
    ${it.subtitle2 ? `<div class="xsmall muted pre">${esc(tn(it.subtitle2))}</div>` : ''}
    <div class="xsmall faint">${esc(it.cat_label || '')}${it.chars?.length ? ' · ' + esc(it.chars.join('、')) : ''}</div>
    <div class="small"><b>${esc(it.end ? leftText(it.end) : '')}</b></div>`;
  pop.hidden = false;
  const r = btn.getBoundingClientRect(); const w = Math.min(340, window.innerWidth - 24);
  pop.style.width = w + 'px';
  let x = Math.min(Math.max(12, r.left), window.innerWidth - w - 12);
  const h = pop.offsetHeight; let y = r.bottom + 8; if (y + h > window.innerHeight - 8) y = Math.max(8, r.top - h - 8);
  pop.style.left = x + 'px'; pop.style.top = y + 'px';
}
document.addEventListener('mouseover', e => { const b = e.target.closest?.('.gbar'); if (b && !$('#news-ctx')) newsPop(b); else if (!e.target.closest?.('#gpop')) newsPop(null); });
window.addEventListener('scroll', () => newsPop(null), { passive: true });

async function openNews(id) {
  const it = (S.news?.items || []).find(x => x.id === id); if (!it) return;
  let content = '';
  if (it.detail) { try { content = (await api('GET', `/api/news/item/${encodeURIComponent(id)}`)).content || ''; } catch (e) { content = unreadHtml('活动正文', e); } }
  S.newsContent = content;
  modal({ title: it.title, wide: true, ok: '关闭', cancel: '', body: `<div id="nd-body">${newsDetailHtml(it, content)}</div>`,
    onMount: m => { const f = $('.mf', m); f.classList.add('nd-foot'); f.insertAdjacentHTML('afterbegin', `<div class="nd-acts" id="nd-acts">${newsActsHtml(it)}</div>`); } });
}
function newsDetailHtml(it, content) {
  const doc = `<!doctype html><meta charset="utf-8"><base target="_blank"><style>body{font:14px/1.75 "Microsoft YaHei UI","PingFang SC",sans-serif;color:#1B1A2E;margin:0;padding:4px 6px}img{max-width:100%;height:auto;border-radius:10px}a{color:#3550D6}table{border-collapse:collapse;max-width:100%}td,th{border:1px solid #ddd;padding:4px 6px}</style>${content}`;
  const cats = S.news?.cats || [];
  return `<div class="nd">
    ${it.img ? `<div class="nd-img"><img src="/news-img/${encodeURIComponent(it.img)}" alt=""></div>` : ''}
    <div class="nd-meta small"><span class="gtag" style="background:${newsColor(it.game)};color:${onColor(newsColor(it.game))}">${esc(shortName(it.game))}</span>
      ${it.end ? `<b>${esc(leftText(it.end))}</b>` : ''}
      <span class="muted">${it.start ? `开始 ${esc(newsStart(it))}` : ''}${it.end && !it.forecast ? `　结束 ${esc(bothTimes(it.end))}` : ''}</span></div>
    ${it.subtitle2 ? `<div class="nd-sub pre">${esc(tn(it.subtitle2))}</div>` : ''}
    ${it.url || (it.source_title && it.source_title !== it.title) ? `<div class="xsmall faint">原文：${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.source_title || it.title)} ↗</a>` : esc(it.source_title)}</div>` : ''}
    ${it.chars?.length ? `<div class="chips">${it.chars.map(c => `<span class="chip">${esc(c)}</span>`).join('')}</div>` : ''}
    <div class="nd-cls small"><label>类别 <select class="sel" data-ndcat="${esc(it.id)}">${cats.filter(c => c.default || c.id === it.cat).map(c => `<option value="${esc(c.id)}" ${c.id === it.cat ? 'selected' : ''}>${esc(c.label)}</option>`).join('')}<option value="__new">＋ 新建类别…</option><option value="">（自动分类）</option></select></label>
      <label>标签 <input class="inp xs" maxlength="6" style="width:90px" value="${esc(it.tag || '')}" data-ndtag="${esc(it.id)}" placeholder="自动"></label>
      <span class="xsmall faint">标签是日历左边那一小格；清空 = 自动</span></div>
    <div class="nd-cls small"><label>开始 <input class="inp xs num" style="width:150px" data-nddate="start" value="${esc(it.start || '')}" placeholder="2026-11-01 05:00"></label>
      <label>结束 <input class="inp xs num" style="width:150px" data-nddate="end" value="${esc(it.end || '')}" placeholder="不填 = 没写"></label>
      <button type="button" class="btn xs" data-nddates="${esc(it.id)}">改起止时间</button>${it.dates_fixed ? `<button type="button" class="linkbtn" data-nddates-reset="${esc(it.id)}">恢复识别的（${esc(it.start_auto || '—')} ～ ${esc(it.end_auto || '—')}）</button>` : ''}
      <span class="xsmall faint">北京时间；识别错了在这里改</span></div>
    ${content ? `<iframe class="news-frame" sandbox="allow-popups allow-popups-to-escape-sandbox" srcdoc="${esc(doc)}"></iframe>` : ''}
  </div>`;
}
// 右键菜单：日历色块、轮播、搜索结果、追踪提醒上都能直接操作
function newsCtx(e) {
  const el = e.target.closest('[data-act="news-open"],[data-act="news-home"]'); if (!el) return;  // 总览上的轮播也能右键（11-02）
  const it = (S.news?.items || []).find(x => x.id === el.dataset.id); if (!it) return;
  e.preventDefault(); closeCtx(); newsPop(null);
  const m = document.createElement('div'); m.className = 'ctx glass'; m.id = 'news-ctx';
  const b = (a, label, extra = '') => `<button type="button" data-act="nd" data-a="${a}" data-id="${esc(it.id)}" ${extra}>${label}</button>`;
  m.innerHTML = `<div class="ctx-t">${esc(tn(it.title))}</div>
    ${b(it.starred ? 'unfollow' : 'follow', it.starred ? '<i>★</i>取消关注' : '<i>☆</i>关注这个活动')}
    ${it.hidden ? b('unhide', '<i>◎</i>恢复显示') : b('hide', '<i>⊘</i>隐藏这个活动')}
    ${b('hide_cat', `<i>⊖</i>${esc(catHideText(it))}`, `data-game="${esc(it.game)}" data-cat="${esc(it.cat)}"`)}
    <button type="button" data-act="news-regame" data-gid="${esc(it.game)}" title="把这个游戏的所有消息来源（官方号、官网、wiki…）重新读一遍，不进游戏"><i>⟳</i>重新读取该游戏活动</button>`;
  document.body.appendChild(m);
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(e.clientX, innerWidth - r.width - 8) + 'px';
  m.style.top = Math.min(e.clientY, innerHeight - r.height - 8) + 'px';
}
function closeCtx() { $('#news-ctx')?.remove(); }
document.addEventListener('contextmenu', newsCtx);
document.addEventListener('click', () => setTimeout(closeCtx, 0), true);
window.addEventListener('scroll', closeCtx, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeCtx(); });
const catHideText = it => `不再显示${shortName(it.game)}的${it.cat_label || '这类'}`;
// 详情里改类别 / 标签（自己建的类别也在这里建）
document.addEventListener('change', async e => {
  const c = e.target.closest?.('[data-ndcat]'), t = e.target.closest?.('[data-ndtag]');
  if (c) {
    if (c.value === '__new') {  // 在旁边出一个输入框，写好名字点「建」
      if (!c.parentElement.querySelector('.nd-newcat')) c.parentElement.insertAdjacentHTML('afterend', `<span class="nd-newcat"><input class="inp xs" maxlength="12" style="width:120px" placeholder="新类别的名字"><button type="button" class="btn xs" data-newcat="${esc(c.dataset.ndcat)}">建</button></span>`);
      c.closest('.nd-cls').querySelector('.nd-newcat input')?.focus();
      return;
    }
    return newsAct({ act: 'set_cat', id: c.dataset.ndcat, cat: c.value }, c.dataset.ndcat);
  }
  if (t) newsAct({ act: 'set_tag', id: t.dataset.ndtag, value: t.value.trim() }, t.dataset.ndtag);
});
document.addEventListener('click', e => {
  const d = e.target.closest?.('[data-nddates]'), r = e.target.closest?.('[data-nddates-reset]');
  if (d) { const box = d.closest('.nd-cls'); return newsAct({ act: 'set_dates', id: d.dataset.nddates, start: box.querySelector('[data-nddate=start]').value.trim(), end: box.querySelector('[data-nddate=end]').value.trim() }, d.dataset.nddates); }
  if (r) return newsAct({ act: 'set_dates', id: r.dataset.nddatesReset, start: '', end: '' }, r.dataset.nddatesReset);
});
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-newcat]'); if (!b) return;
  const name = b.previousElementSibling.value.trim(); if (!name) return toast('写一下类别的名字', true);
  newsAct({ act: 'add_cat', id: b.dataset.newcat, name }, b.dataset.newcat);
});
function newsActsHtml(it) {
  return `<button class="btn sm ${it.starred ? '' : 'dark'}" data-act="nd" data-a="${it.starred ? 'unfollow' : 'follow'}" data-id="${esc(it.id)}">${it.starred ? '★ 取消关注' : '☆ 关注这个活动'}</button>
      ${it.hidden ? `<button class="btn sm" data-act="nd" data-a="unhide" data-id="${esc(it.id)}">◎ 恢复显示</button>`
        : `<button class="btn sm" data-act="nd" data-a="hide" data-id="${esc(it.id)}">⊘ 隐藏这个活动</button>`}
      <button class="btn sm" data-act="nd" data-a="hide_cat" data-id="${esc(it.id)}" data-game="${esc(it.game)}" data-cat="${esc(it.cat)}">⊖ ${esc(catHideText(it))}</button>`;
}
async function newsAct(body, refreshId) {
  try { await api('POST', '/api/news/act', body); } catch (e) { fail(e); return; }
  try { S.news = await api('GET', '/api/news'); } catch (e) { failRead('活动')(e); return; }
  if (refreshId) { const it = S.news.items.find(x => x.id === refreshId); const box = $('#nd-body'); if (it && box) { box.innerHTML = newsDetailHtml(it, S.newsContent || ''); const ab = $('#nd-acts'); if (ab) ab.innerHTML = newsActsHtml(it); } }
  if (S.route.view === 'news') renderNews(); else if (S.route.view === 'home') renderHome();
  if ($('#nf-body')) $('#nf-body').innerHTML = newsFilterHtml();
}
// 搜索：标题、副标题、原文标题、角色；范围 = 进行中 + 前后 30 天
function newsSearchHtml(all, q) {
  const k = q.trim().toLowerCase(); if (!k) return '';
  const now = nowBjMs(), lo = now - 30 * 864e5, hi = now + 30 * 864e5;
  const hit = all.filter(it => {
    const e = it.end ? bjMs(it.end) : (it.start ? bjMs(it.start) : now), st = it.start ? bjMs(it.start) : e;
    if (e < lo || st > hi) return false;
    return [it.title, it.subtitle, it.subtitle2, it.source_title, (it.chars || []).join(' '), shortName(it.game), it.cat_label].join(' ').toLowerCase().includes(k);
  }).sort((a, b) => (bjMs(b.end) || 0) - (bjMs(a.end) || 0));
  return `<section class="glass panel news-res"><div class="ph"><h3>搜索「${esc(q)}」</h3><span class="small faint">${hit.length} 条</span></div>
    ${hit.map(it => { const past = it.end && bjMs(it.end) < now; return `<button type="button" class="nr${past ? ' past' : ''}" data-act="news-open" data-id="${esc(it.id)}">
      <i style="background:${newsColor(it.game)}"></i><span class="nr-g">${esc(shortName(it.game))}</span><b>${it.starred ? '★ ' : ''}${esc(tn(it.title))}</b>
      <span class="xsmall faint">${esc(it.cat_label || '')}${it.hidden ? ' · 已屏蔽' : ''}${past ? ' · 已结束' : it.end ? ' · ' + esc(leftText(it.end)) : ''}</span></button>`; }).join('') || '<div class="small faint">没有找到</div>'}
  </section>`;
}
// 追踪的角色出现在新活动里：直接问要不要关注这个活动
function trackPrompts(d) {
  const asked = new Set(d?.prefs?.asked || []); const now = nowBjMs();
  return (d?.items || []).filter(it => it.tracked?.length && !it.starred && !it.hidden && !asked.has(it.id) && (!it.end || bjMs(it.end) >= now));
}
function trackPromptHtml(d) {
  const list = trackPrompts(d); if (!list.length) return '';
  return `<section class="glass panel track-p"><div class="ph"><h3>追踪的角色有新活动</h3><span class="small faint">要关注吗？关注后加星标${d.prefs?.push_followed ? '，并随每日汇总推送' : ''}</span></div>
    ${list.slice(0, 6).map(it => `<div class="tp-row"><i style="background:${newsColor(it.game)}"></i><span class="nr-g">${esc(shortName(it.game))}</span>
      <button type="button" class="linkbtn" data-act="news-open" data-id="${esc(it.id)}"><b>${esc(tn(it.title))}</b></button>
      <span class="xsmall muted">${esc(it.tracked.join('、'))}${it.start ? ' · ' + esc(it.start_note ? mdhm(it.start).slice(0, 5) + ' ' + it.start_note.replace('最早读到', '前') : mdhm(it.start)) + ' 开始' : ''}</span><span style="flex:1"></span>
      <button class="btn xs dark" data-act="nd" data-a="follow" data-id="${esc(it.id)}">☆ 关注</button><button class="btn xs ghost" data-act="nd" data-a="asked" data-id="${esc(it.id)}">不了</button></div>`).join('')}
  </section>`;
}
async function injectTrackPrompts() {
  let d; try { d = await api('GET', '/api/news'); } catch (e) { const b = $('#home-track'); if (b) b.innerHTML = unreadHtml('活动', e); return; }
  S.news = d;
  const box = $('#home-track'); if (box) box.innerHTML = trackPromptHtml(d);
}
// 筛选与关注：按游戏 / 类别显示、已屏蔽的活动、追踪的角色
function openNewsFilter() {
  modal({ title: '筛选与关注', wide: true, ok: '完成', cancel: '', body: `<div id="nf-body">${newsFilterHtml()}</div>` });
}
function newsFilterHtml() {
  const d = S.news || {}; const p = d.prefs || {}; const cats = (d.cats || []);
  const gids = (S.state?.games || []).map(g => g.id).filter(g => (d.items || []).some(it => it.game === g));
  const hc = p.hidden_cats || {};
  const catRow = g => `<div class="nf-cats">${cats.filter(c => c.default && (c.id !== 'qxqy' || g === '*' || g === 'genshin')).map(c => {
    const off = (hc[g] || []).includes(c.id) || (g !== '*' && (hc['*'] || []).includes(c.id));
    return `<button type="button" class="nf-cat${off ? ' off' : ''}" data-act="nf-cat" data-game="${esc(g)}" data-cat="${c.id}" data-on="${off ? '1' : '0'}">${esc(c.label)}</button>`; }).join('')}</div>`;
  const hiddenItems = (d.items || []).filter(it => (p.hidden_items || []).includes(it.id));
  return `<div class="nf">
    <h4>显示哪些游戏</h4><div class="small faint">点一下切换；灰色 = 活动页和总览上都不显示这个游戏的活动。</div>
    <div class="nf-cats">${gids.map(g => { const off = newsUiInit().off.has(g); return `<button type="button" class="nf-cat${off ? ' off' : ''}" data-act="news-game" data-gid="${esc(g)}">${esc(shortName(g))}</button>`; }).join('')}</div>
    <h4>按类别显示</h4><div class="small faint">点一下切换；灰色 = 不显示。「全部游戏」一行对所有游戏生效。</div>
    <div class="nf-g"><b>全部游戏</b>${catRow('*')}</div>
    ${gids.map(g => `<div class="nf-g"><b><i style="background:${newsColor(g)}"></i>${esc(shortName(g))}</b>${catRow(g)}</div>`).join('')}
    ${cats.some(c => c.user) ? `<h4>自己建的类别</h4><div class="small faint">在活动详情里「类别」选「＋ 新建类别…」建；删掉后放进去的活动回到自动分类。</div>
      <div class="nf-cats">${cats.filter(c => c.user).map(c => `<span class="chip">${esc(c.label)} <button type="button" class="linkbtn" data-act="nd" data-a="del_cat" data-cat="${esc(c.id)}">删除</button></span>`).join('')}</div>` : ''}
    <h4>追踪的角色</h4><div class="small faint">新读到的活动里出现这些角色时，在总览和活动页顶部问你要不要关注。</div>
    ${gids.map(g => { const names = (d.chars || {})[g] || []; const tr = (p.track || {})[g] || []; return `<div class="nf-g"><b><i style="background:${newsColor(g)}"></i>${esc(shortName(g))}</b><div class="nf-cats">
      ${names.map(n => `<button type="button" class="nf-cat chr${tr.includes(n) ? ' on' : ''}" data-act="nf-track" data-game="${esc(g)}" data-name="${esc(n)}" data-on="${tr.includes(n) ? '1' : '0'}">${tr.includes(n) ? '★ ' : ''}${esc(n)}</button>`).join('')}
      <input class="inp xs" placeholder="添加角色名" data-act="nf-addchar" data-game="${esc(g)}" style="width:110px"></div></div>`; }).join('')}
    <h4>不再关注的活动（${hiddenItems.length}）</h4>
    ${hiddenItems.map(it => `<div class="tp-row"><span class="nr-g">${esc(shortName(it.game))}</span><span>${esc(tn(it.title))}</span><span style="flex:1"></span><button class="btn xs" data-act="nd" data-a="unhide" data-id="${esc(it.id)}">恢复</button></div>`).join('') || '<div class="small faint">没有</div>'}
  </div>`;
}

// 轮播右键「重新获取题图」（11-01）：模拟器临时调高分辨率，只重读游戏内公告，读完改回原来的
async function refetchBanners(gid) {
  const g = game(gid);
  if (!(await confirmBox('重新获取题图？', `会先关掉${esc(shortName(gid))}用的模拟器，临时调高分辨率（在游戏页「高级」里选）后重开，只读一遍游戏内公告，读完把分辨率改回来并关掉模拟器。大约要几分钟，期间这台模拟器上的别的游戏要等。`, '开始'))) return;
  try {
    const r = await api('POST', `/api/games/${encodeURIComponent(gid)}/refetch-banners`);
    toast(`已排进队列：${shortName(gid)}按 ${r.resolution.replace('x', '×')} 重新读公告，读完活动页会更新`);
    S.fastUntil = Date.now() + 40000; pollRunning();
  } catch (e) { fail(e); }
  void g;
}
