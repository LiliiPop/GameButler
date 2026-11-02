// 日常管家界面 · 总览和运行记录页。和其它 static/js/*.js 共用全局（不打包，按 index.html 里的顺序加载）。

'use strict';

// ------------------------------------------------------------------ 总览：日常一览 + 接下来 + 当前活动（轮播）
function syncNewsOff(d) {  // 按游戏的显示开关存在后台（活动页和主页共用）
  const N = newsUiInit();
  if (!N.offLoaded && d?.prefs) { N.off = new Set(d.prefs.games_off || []); N.offLoaded = true; }
}
function newsUiInit() {
  return S.newsUi || (S.newsUi = { month: null, off: new Set(), slide: 0, view: (() => { try { return localStorage.getItem('gb-news-view') || 'week'; } catch (e) { return 'week'; } })() });
}
const repMap = () => S.report && S.report.games ? Object.fromEntries(S.report.games.map(x => [x.id, x])) : {};
function gstate(g) {
  const allDone = g.total > 0 && g.done >= g.total;
  return g.running ? ['运行中', 'run'] : g.attention ? ['需处理', 'bad'] : allDone ? ['已完成', 'ok'] : !g.total ? ['没有任务', 'off'] : g.done ? ['进行中', 'off'] : ['未开始', 'off'];
}
// 重画页面时保住滚动位置（页面本身和甘特图框里的），不再跳回第一行
function keepScroll(fn) {
  const y = window.scrollY, g = $('.gscroll'), gt = g ? g.scrollTop : 0, gl = g ? g.scrollLeft : 0;
  fn();
  const g2 = $('.gscroll'); if (g2 && (gt || gl)) { g2.scrollTop = gt; g2.scrollLeft = gl; }
  if (Math.abs(window.scrollY - y) > 2) window.scrollTo(0, y);
}
function renderHome() { keepScroll(renderHome0); }
function renderHome0() {  // B 极简：标题 → 运行行 → 日常一览 | 接下来 → 当前活动（设置里可以把当前活动放上面）
  const games = allGames();  // 11-02：仅关注的游戏也在日常一览里（手动标记完成）
  const avail = games.filter(g => g.available);
  const totalGames = avail.filter(g => g.total > 0);
  const doneGames = totalGames.filter(g => g.done >= g.total).length;
  const att = avail.reduce((n, g) => n + (g.attention || 0), 0);
  const left = totalGames.length - doneGames;
  let headline;
  if (!totalGames.length) headline = '还没有可用的游戏';
  else if (!left && !att) headline = S.state.games.length ? '今天的日常都跑完了' : '今天的日常都做完了';
  else headline = (left ? `还剩 ${left} 个游戏没${S.state.games.length ? '跑完' : '做完'}` : '游戏都跑过了') + (att ? `，${att} 项要处理` : '');
  const off = games.filter(g => !g.available);
  const daily = `<div class="b-cols">
      <section aria-label="日常一览">
        <div class="b-h"><h2>日常一览</h2><span>${doneGames} / ${totalGames.length} 完成</span></div>
        <div class="b-list">${avail.map(g => homeRow(g, games.indexOf(g))).join('') || '<div class="b-empty">还没有游戏：去「设置 → 工具与游戏」添加脚本，或「添加游戏」只看活动</div>'}</div>
        ${off.length ? `<div class="b-off">待接入：${off.map(g => `<span title="${esc(g.message || '待接入')}">${esc(splitName(g.name)[0])}</span>`).join('、')}</div>` : ''}
      </section>
      <aside aria-label="接下来">
        <div class="b-h"><h2>接下来</h2></div>
        <div class="b-list" id="home-next">${homeNextHtml()}</div>
        <a class="b-more" href="#/schedule">去日程安排</a>
      </aside>
    </div>`;
  // 资源一览（11-02）：日常一览 | 接下来 下面；左边各游戏存量，点一行右边换成它的曲线和估算
  const res = `<section aria-label="资源一览" class="b-res"><div class="b-h"><h2>资源一览</h2><span>折合抽数 · 估算仅供参考</span></div><div id="home-res">${homeResHtml()}</div></section>`;
  const news = `<section aria-label="当前活动"><div class="b-h"><h2>当前活动</h2></div><div id="home-banner" class="home-banner">${homeBannerHtml()}</div></section>`;
  const newsFirst = S.state.appearance?.home_order === 'news_first';
  $('#app').innerHTML = `
  <div class="home b-home">
    <section class="hero">
      <div><span class="eyebrow num">${esc(dayEyebrow())}</span><h1>${headline}</h1></div>
      <div class="side">${S.running?.running || !S.state.games.some(g => g.available) ? '' : `<button class="btn dark" data-act="run-all">开始全部</button>`}</div>
    </section>
    ${newsFirst ? news + daily + res : daily + res + news}
  </div>`;
  if (!S.homeSchAt || Date.now() - S.homeSchAt > 30e3) {
    S.homeSchAt = Date.now();
    api('GET', '/api/schedule/today').then(d => { S.homeSch = d; const el = $('#home-next'); if (el && S.route.view === 'home') el.innerHTML = homeNextHtml(); }).catch(() => {});
  }
  if (!S.news || !S.newsAt || Date.now() - S.newsAt > 60e3) {
    S.newsAt = Date.now();
    api('GET', '/api/news').then(d => { S.news = d; syncNewsOff(d); const el = $('#home-banner'); if (el && S.route.view === 'home') el.innerHTML = homeBannerHtml(); }).catch(() => {});
  }
  if (!S.resAll || Date.now() - S.resAll.at > 60e3) loadRes().then(() => { const el = $('#home-res'); if (el && S.route.view === 'home') el.innerHTML = homeResHtml(); }).catch(() => {});
  startBannerTimer();
}
function homeBannerHtml() {  // 和活动页同一套轮播；点图去活动页
  if (!S.news) return '<div class="b-empty">正在读取活动…</div>';
  syncNewsOff(S.news);
  const N = newsUiInit(); const list = newsBanners(S.news);
  N.banners = list; if (N.slide >= list.length) N.slide = 0;
  return list.length ? bannerHtml(list, N.slide, true) : '<div class="b-empty">现在没有带题图的进行中活动 · <a href="#/news">去活动页</a></div>';
}
const whenShort = b => b.when?.kind === 'now' ? '接着跑' : b.when?.kind === 'idle' ? '闲时' : (b.when_text || '').replace(/（北京[^）]*）/, '').trim() || '等待';
function homeNextHtml() {
  const d = S.homeSch; if (!d) return '<div class="b-empty">正在读取…</div>';
  const items = (d.items || []).filter(b => b.section === 'next').slice(0, 5);
  return items.map(b => `<div class="b-next"><span>${esc(itemTitle(b))}</span><span>${esc(whenShort(b))}</span></div>`).join('') || '<div class="b-empty">今天没有要等的了</div>';
}
// 要处理的说明：只写第一层原因，按结果分组：「逸梦、地宫助手：失败；每日进膳：错过时段」
function attSummary(list) {
  const by = new Map();
  list.forEach(a => { const k = RES[a.result]?.[0] || a.result || '失败'; by.set(k, [...(by.get(k) || []), tn(a.task)]); });
  return [...by].map(([k, v]) => `${esc(v.join('、'))}：${esc(k)}`).join('；');
}
function homeRow(g, i) {
  if (g.watch) return watchRow(g, i);
  const rep = repMap()[g.id]; const first = (rep?.attention || [])[0];
  const st = gstate(g);
  const label = { run: '运行中', bad: '要处理', ok: '完成' }[st[1]] || (g.total ? '等待' : '没有任务');
  const last = g.last_run !== undefined ? g.last_run : rep?.last_run;
  const prog = g.total ? `日常 ${g.done} / ${g.total}` : '今天没有任务';
  const nx = (S.homeSch?.items || []).find(b => b.game === g.id && b.section === 'next');
  let det;
  if (st[1] === 'bad') det = g.problem ? esc(g.problem) : attSummary(g.att || rep?.attention || []) || `${prog} · 有 ${g.attention} 项要处理`;
  else if (st[1] === 'run') det = `${prog}${S.running?.current?.task ? ` · 正在 ${esc(tn(S.running.current.task))}` : ''}`;
  else if (st[1] === 'ok') det = `${prog}${last?.started ? ` · ${esc(hm(last.started))}` : ''}`;
  else det = nx ? `${esc(whenShort(nx))}${nx.routine ? ` · ${esc(nx.routine)}` : ''}` : prog;
  // 11-02：每个游戏按自己的刷新时刻换天（例如原神北京 04:00、恋与深空 05:00），写出这一行算的是哪个游戏日
  if (g.today) det += ` <span class="faint xsmall" title="这一行算的是 ${esc(g.today)} 这个游戏日：每天北京 ${esc(g.refresh || '')} 刷新后换到下一天">· ${esc(g.today.slice(5))}</span>`;
  return `<a class="b-row${st[1] === 'bad' ? ' att' : ''}" href="#/g/${esc(g.id)}/today" data-gid="${esc(g.id)}" style="--gc:${tint(g, i)}"${st[1] === 'bad' ? ' title="右键：立刻重跑 / 标为已完成 / 跳过任务"' : ''}>
    <span class="b-name"><i></i><b>${esc(splitName(g.name)[0])}</b></span>
    <span class="badge ${st[1] === 'off' ? '' : st[1]}">${label}</span>
    <span class="b-det" title="${det.replace(/<[^>]+>/g, '')}">${det}</span>${st[1] === 'bad' ? moreBtn('立刻重跑 / 标为已完成 / 跳过任务') : ''}</a>`;
}
// 仅关注的游戏（11-02）：没有脚本，右键 / ⋯ 手动标记今天的日常做完没有；到这个游戏的下一个游戏日自动变回没完成
function watchRow(g, i) {
  const ok = g.done >= g.total;
  const det = `${ok ? '今天已标记完成' : '仅关注 · 没挂脚本，做完了右键标记'} <span class="faint xsmall" title="这一行算的是 ${esc(g.today)} 这个游戏日：每天北京 ${esc(g.refresh || '')} 刷新后换到下一天">· ${esc(g.today.slice(5))}</span>`;
  return `<a class="b-row" href="#/news" data-gid="${esc(g.id)}" data-watch="1" style="--gc:${tint(g, i)}" title="右键：${ok ? '取消已完成' : '标记已完成'}">
    <span class="b-name"><i></i><b>${esc(splitName(g.name)[0])}</b></span>
    <span class="badge ${ok ? 'ok' : ''}">${ok ? '完成' : '未完成'}</span>
    <span class="b-det" title="${det.replace(/<[^>]+>/g, '')}">${det}</span>${moreBtn(ok ? '取消已完成' : '标记已完成')}</a>`;
}
async function watchDone(gid, on) {
  try {
    await api('POST', `/api/watch/${encodeURIComponent(gid)}/done`, { on });
    toast(on ? `${shortName(gid)}：今天已标记完成` : `${shortName(gid)}：已取消完成`);
    await loadState(); if (S.route.view === 'home') renderHome();
  } catch (e) { fail(e); }
}
// ------------------------------------------------------------------ 报告
async function renderReport(day) {
  const games = S.state.games.filter(g => g.available);
  const base = reportDay() === 'today' ? null : reportDay();
  day = day || base || 'today';
  let rep;
  try { rep = await api('GET', `/api/report/${day}`); } catch (e) { $('#app').innerHTML = `<div class="glass skeleton">${esc(e.message)}</div>`; return; }
  const days = base ? [0, 1, 2, 3, 4, 5, 6].map(n => addDays(base, -n)) : [];
  const s = rep.summary || {};
  $('#app').innerHTML = `<div style="display:flex;flex-direction:column;gap:20px">
    <section class="hero">
      <div><div class="eyebrow num">${esc(dayEyebrow(rep.day))}</div><h1>运行记录</h1></div>
      <div class="side">${days.length ? `<select class="sel" style="width:auto" data-act="report-day" aria-label="选择日期">${days.map(d => `<option value="${d}" ${d === rep.day ? 'selected' : ''}>${d === base ? '今天 · ' : ''}${dayLabel(d)}</option>`).join('')}</select>` : ''}
</div>
    </section>
    <section class="stats">
      <div class="stat glass"><div class="k">已完成</div><div class="v num"><b>${s.done || 0}</b><span>/ ${s.total || 0} 项任务</span></div><div class="bar"><i style="width:${s.total ? Math.round(s.done / s.total * 100) : 0}%"></i></div></div>
      <div class="stat glass ${s.attention ? 'warm' : ''}"><div class="k">失败</div><div class="v num"><b style="${s.attention ? 'color:var(--orange)' : ''}">${s.attention || 0}</b><span>项</span></div></div>
      <div class="stat glass"><div class="k">生成时间</div><div style="font-size:21px;font-weight:700" class="num">${esc(mdhm(rep.generated))}</div><div class="small faint">北京时间</div></div>
    </section>
    <div style="display:flex;flex-direction:column;gap:16px">
      ${(rep.games || []).map(g => reportGame(g)).join('') || '<div class="glass empty">这一天没有记录</div>'}
    </div>
  </div>`;
  S.reportShown = rep;
}
function reportGame(g) {
  const gg = game(g.id); const i = S.state.games.indexOf(gg);
  const pend = g.pending || [];
  return `<section class="rg glass">
    <div class="ghead"><div class="avatar" style="background:${tint(gg || g, i)}">${esc(markOf(g.name))}</div>
      <div class="gname"><b><a href="#/g/${esc(g.id)}/runs" style="color:inherit;text-decoration:none">${esc(g.name)}</a></b><span class="num">${g.runs ? `运行 ${g.runs} 次` : '没有运行记录'}${g.last_run ? ` · 最近 ${esc(mdhm(g.last_run.started))}` : ''}</span></div>
      <span class="num" style="font-size:17px;font-weight:700">${g.done}<span class="faint" style="font-weight:500"> / ${g.total}</span></span></div>
    ${(() => {  // 11-02：失败、未运行、全部完成、留证截图都排成同一种行（状态 + 任务名 + 说明），字号行距一致
      const rows = (g.attention || []).map(a => `<li data-gid="${esc(g.id)}" data-key="${esc(a.task)}" title="右键：立刻重跑 / 标为已完成 / 跳过任务">${badge(a.result)}<span><b>${esc(tn(a.task))}</b>${a.detail ? `<span class="muted rg-why">${esc(why(a.detail))}</span>` : ''}${a.attempts > 1 ? `<span class="faint rg-why">试了 ${a.attempts} 次</span>` : ''}</span></li>`);
      if (pend.length) rows.push(`<li>${badge('pending')}<span><b>${esc(pend.map(tn).join('、'))}</b></span></li>`);
      if (!g.attention?.length && !pend.length && g.total) rows.push(`<li>${badge('succeeded')}<span><b>全部完成</b></span></li>`);
      (g.tasks || []).filter(t => t.evidence?.length).forEach(t => rows.push(`<li class="rg-ev">${badge(t.result || 'succeeded')}<span><b>${esc(tn(t.task))}</b><span class="faint rg-why">留证截图</span>
        <div class="shots">${t.evidence.map(x => `<button type="button" data-act="shot" data-src="${esc(x)}" aria-label="查看留证截图"><img src="${esc(x)}" alt="" loading="lazy"></button>`).join('')}</div></span></li>`));
      return rows.length ? `<ul class="rg-list">${rows.join('')}</ul>` : '';
    })()}
  </section>`;
}
