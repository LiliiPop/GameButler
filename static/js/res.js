// 抽卡资源（11-02）：总览「资源一览」+ 游戏页右栏「抽卡资源」卡片。数据：GET /api/resources（butler/readings.py overview）
// 「记一笔」「抽卡保底」这一版不做（见项目文档），只看存量、曲线和到下一个 UP 卡池结束时的估算（仅供参考）。

async function loadRes(force = false) {
  if (!force && S.resAll && Date.now() - S.resAll.at < 60e3) return S.resAll.games;
  if (S.resLoading) return S.resLoading;
  S.resLoading = api('GET', '/api/resources').then(d => { S.resAll = { at: Date.now(), games: d.games || [] }; return S.resAll.games; })
    .finally(() => { S.resLoading = null; });
  return S.resLoading;
}
const resPulls = r => r.pulls != null ? `${Math.floor(r.pulls)}` : '—';
const resMain = r => {  // 没有折合抽数时，显示第一项资源
  if (r.pulls != null) return { n: Math.floor(r.pulls).toLocaleString(), u: '抽' };
  const [k, v] = Object.entries(r.values || {})[0] || ['', 0];
  return { n: Number(v).toLocaleString(), u: k };
};
const resVals = r => Object.entries(r.values || {}).map(([k, v]) => {
  const d = (r.defs || []).find(x => x.key === k) || {};
  return { k, v, per: d.per_pull, std: d.standard };
});

// 曲线：横轴按日期；有 UP 卡池时延长到卡池结束，虚线是按最近的增长估的（仅供参考）
function resChartSvg(r, color, opt = {}) {
  const pts = (r.series || []).filter(x => x.pulls != null);
  if (pts.length < 2) return `<div class="xsmall faint res-nochart">读数还不够画曲线（至少要两天的读数）</div>`;
  const day = s => Date.parse(s.slice(0, 10) + 'T00:00:00+08:00');
  const x0 = day(pts[0].day);
  const pool = r.pool && r.estimate != null ? r.pool : null;
  const xEnd = pool ? Math.max(day(pts[pts.length - 1].day), bjMs(pool.end)) : day(pts[pts.length - 1].day);
  const ys = pts.map(p => p.pulls).concat(pool ? [r.estimate] : []);
  const lo = Math.min(...ys), hi = Math.max(...ys), pad = (hi - lo) * 0.12 || 2;
  const W = opt.w || 560, H = opt.h || 180, L = 40, R = 14, T = 14, B = 24;
  const X = t => L + (t - x0) / Math.max(1, xEnd - x0) * (W - L - R);
  const Y = v => T + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (H - T - B);
  const line = pts.map(p => `${X(day(p.day)).toFixed(1)},${Y(p.pulls).toFixed(1)}`).join(' ');
  const last = pts[pts.length - 1];
  const ticks = [lo - pad, (lo + hi) / 2, hi + pad].map(v => `<text x="${L - 6}" y="${Y(v) + 3}" text-anchor="end">${Math.round(v)}</text><line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" class="grid"/>`).join('');
  const est = pool ? `<polyline points="${X(day(last.day)).toFixed(1)},${Y(last.pulls).toFixed(1)} ${X(bjMs(pool.end)).toFixed(1)},${Y(r.estimate).toFixed(1)}" class="est" style="stroke:${color}"/>
      <line x1="${X(bjMs(pool.end))}" x2="${X(bjMs(pool.end))}" y1="${T}" y2="${H - B}" class="pool"/>
      <circle cx="${X(bjMs(pool.end))}" cy="${Y(r.estimate)}" r="4" fill="var(--paper, #fff)" stroke="${color}" stroke-width="2"><title>估算：${pool.end.slice(5, 10)} 约 ${Math.round(r.estimate)} 抽（仅供参考）</title></circle>
      <text x="${Math.min(W - R - 2, X(bjMs(pool.end)) - 4)}" y="${T + 10}" text-anchor="end" class="pl">${esc(pool.end.slice(5, 10))} 卡池结束</text>` : '';
  return `<svg class="res-chart2" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(splitName(r.name)[0])}折合抽数曲线">
    ${ticks}
    <polyline points="${line}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
    ${pts.map(p => `<circle cx="${X(day(p.day)).toFixed(1)}" cy="${Y(p.pulls).toFixed(1)}" r="3" fill="${color}"><title>${esc(p.day.slice(5))}：${Math.round(p.pulls)} 抽</title></circle>`).join('')}
    ${est}
    <text x="${L}" y="${H - 6}">${esc(pts[0].day.slice(5))}</text><text x="${X(day(last.day))}" y="${H - 6}" text-anchor="${pool ? 'middle' : 'end'}">${esc(last.day.slice(5))}</text>
  </svg>`;
}
function resEstimateHtml(r) {
  const p = r.pool;
  if (!p) return `<div class="res-est xsmall faint">活动日历里暂时没有进行中或将要开始的 UP 卡池。</div>`;
  const left = p.days_left >= 1 ? `${Math.floor(p.days_left)} 天${Math.round((p.days_left % 1) * 24) ? ` ${Math.round((p.days_left % 1) * 24)} 小时` : ''}` : `${Math.max(1, Math.round(p.days_left * 24))} 小时`;
  return `<div class="res-est">
    <div><span class="faint">${p.started ? '当前 UP 卡池' : '下一个 UP 卡池'}</span> <b>${esc(tn(p.title))}</b>${p.chars?.length ? `<span class="faint">（${esc(p.chars.join('、'))}）</span>` : ''}</div>
    <div class="num">${p.started ? '距结束' : '结束于'} <b>${p.started ? left : esc(bothTimes(p.end))}</b>${p.started ? `<span class="faint"> · ${esc(bothTimes(p.end))} 结束</span>` : ''}</div>
    ${r.estimate != null ? `<div>到那时大约 <b class="num">${Math.round(r.estimate)}</b> 抽 <span class="badge">仅供参考</span>
      <div class="xsmall faint">按最近 ${r.rate_days} 天平均每天 +${r.rate} 抽估算（只算攒的，不算抽掉的）；活动奖励、月卡、你抽卡都会让实际数字不一样。</div></div>`
      : `<div class="xsmall faint">读数还不够估算（至少要隔两天的读数）。</div>`}
  </div>`;
}

// ---------------------------------------------------------------- 总览：资源一览
function homeResHtml() {
  const list = S.resAll?.games;
  if (!list) return '<div class="b-empty">正在读取资源…</div>';
  if (!list.length) return '<div class="b-empty">还没有资源读数：在「设置 → 游戏内读取」里勾上「跑日常时读抽卡资源」，跑过一次日常后就有。</div>';
  const games = S.state.games;
  const pick = list.find(x => x.id === S.resPick) || list[0];
  const rows = list.map(r => {
    const g = game(r.id) || r; const m = resMain(r);
    return `<button type="button" class="b-row res-row${r.id === pick.id ? ' on' : ''}" data-res-pick="${esc(r.id)}" style="--gc:${tint(g, games.indexOf(g))}" aria-pressed="${r.id === pick.id}">
      <span class="b-name"><i></i><b>${esc(splitName(r.name)[0])}</b></span>
      <span class="res-n num"><b>${m.n}</b><small>${esc(m.u)}</small></span>
      <span class="b-det">${resVals(r).filter(x => !x.per || x.std).slice(0, 3).map(x => `${esc(x.k)} ${Number(x.v).toLocaleString()}`).join(' · ')}${r.stale ? ' · <span class="bwarn">数据较旧</span>' : ''}</span>
      <span class="xsmall faint num">${esc((r.at || '').slice(5, 10))}</span></button>`;
  }).join('');
  const g = game(pick.id) || pick;
  return `<div class="res-cols">
    <div class="b-list">${rows}</div>
    <div class="res-pane" style="--gc:${tint(g, games.indexOf(g))}">
      <div class="res-ph"><b>${esc(splitName(pick.name)[0])}</b><span class="xsmall faint">折合抽数 · ${pick.at ? `${esc(pick.at.slice(5))} 读到` : ''}</span></div>
      ${resChartSvg(pick, tint(g, games.indexOf(g)))}
      ${resEstimateHtml(pick)}
    </div></div>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-res-pick]'); if (!b) return;
  S.resPick = b.dataset.resPick; const el = $('#home-res'); if (el) el.innerHTML = homeResHtml();
});

// ---------------------------------------------------------------- 游戏页右栏：抽卡资源卡片（数量 | 曲线 | 表格）
function resCardHtml(g) {
  return `<section class="panel glass" data-card="res"><div class="ph"><h3>抽卡资源</h3><span class="xsmall faint" id="res-card-at"></span></div>
    <div id="res-card-body">${resCardBody(g)}</div></section>`;
}
function resCardBody(g) {
  if (!S.resAll) { loadRes().then(() => { const el = $('#res-card-body'); if (el && S.ed?.gid === g.id) el.innerHTML = resCardBody(g); }).catch(() => {}); return '<div class="xsmall faint">读取中…</div>'; }
  const r = S.resAll.games.find(x => x.id === g.id);
  if (!r) return `<div class="xsmall faint">${g.has_gacha ? '还没有读数。在「设置 → 游戏内读取」里勾上这个游戏的「读抽卡资源」，跑过一次日常后就有。' : '这个游戏还不能读抽卡资源。'}</div>`;
  const view = S.resView || 'num';
  const tabs = `<div class="seg res-tabs" role="tablist">${[['num', '数量'], ['chart', '曲线'], ['table', '表格']].map(([k, l]) => `<button type="button" role="tab" class="${view === k ? 'on' : ''}" aria-selected="${view === k}" data-res-view="${k}">${l}</button>`).join('')}</div>`;
  const color = tint(g, (S.state.games || []).indexOf(g));
  let body;
  if (view === 'chart') body = resChartSvg(r, color, { w: 340, h: 150 }) + resEstimateHtml(r);
  else if (view === 'table') {
    const keys = resVals(r).map(x => x.k);
    const rows = (r.series || []).slice().reverse().slice(0, 30);
    body = `<div class="res-tbl-wrap"><table class="res-tbl num"><thead><tr><th>日期</th><th>折合</th>${keys.map(k => `<th>${esc(k)}</th>`).join('')}</tr></thead>
      <tbody>${rows.map((x, i) => { const prev = rows[i + 1]; const dv = prev && x.pulls != null && prev.pulls != null ? x.pulls - prev.pulls : null;
        return `<tr><td>${esc(x.day.slice(5))}</td><td>${x.pulls != null ? Math.floor(x.pulls) : '—'}${dv ? `<small class="${dv > 0 ? 'up' : 'down'}">${dv > 0 ? '+' : ''}${Math.round(dv)}</small>` : ''}</td>${keys.map(k => `<td>${x.values?.[k] != null ? Number(x.values[k]).toLocaleString() : '—'}</td>`).join('')}</tr>`; }).join('')}</tbody></table></div>`;
  } else {
    // 批注 #197（11-03）：各项排成一样的格子（数在上、名字在下，间距行距一致）；换算（多少 = 1 抽）只放在鼠标提示里
    body = `<div class="res-nums">${r.pulls != null ? `<div class="res-big"><b class="num">${Math.floor(r.pulls)}</b><span>折合抽数</span></div>` : ''}
      ${r.standard_pulls != null ? `<div><b class="num">${Math.floor(r.standard_pulls)}</b><span>常驻池折合</span></div>` : ''}
      ${resVals(r).map(x => `<div${x.per ? ` title="${esc(x.per === 1 ? '1 个 = 1 抽' : `${x.per} 个 = 1 抽`)}${x.std ? '，常驻池用' : ''}"` : ''}><b class="num">${Number(x.v).toLocaleString()}</b><span>${esc(x.k)}</span></div>`).join('')}</div>`;
  }
  return `${tabs}${body}<div class="xsmall faint res-at">${r.at ? `${esc(r.at.slice(5))} 读到` : ''}${r.stale ? ' · <span class="bwarn">数据较旧</span>' : ''}</div>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-res-view]'); if (!b || !S.ed) return;
  S.resView = b.dataset.resView; const el = $('#res-card-body'); if (el) el.innerHTML = resCardBody(game(S.ed.gid));
});
