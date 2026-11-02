// 日常管家界面 · 事件分发、路由、启动（最后加载）。和其它 static/js/*.js 共用全局（不打包，按 index.html 里的顺序加载）。

'use strict';

// ------------------------------------------------------------------ 事件
document.addEventListener('click', async e => {
  const el = e.target.closest('[data-act]'); if (!el) return;
  const act = el.dataset.act; const ed = S.ed; const i = +el.dataset.i;
  if (['filter', 'key', 'window', 'opt-input', 'opt-select', 'apply-src', 'runs-day', 'report-day', 'tool-emu'].includes(act)) return;
  if (el.tagName === 'A' && !['routine-goto', 'routine-pick', 'routine-open'].includes(act)) return;
  e.preventDefault();
  switch (act) {
    case 'open': location.hash = `#/g/${el.dataset.gid}/today`; break;
    case 'today-reset': todayReset(el.dataset.key); break;
    case 'again-edit': againEdit(el.dataset.key); break;
    case 'go-back': if ((S.navStack || []).length > 1) history.back(); else location.hash = '#/'; break;  // 回到来的地方；直接打开这一页时回总览
    case 'launch-game': api('POST', `/api/launch/${encodeURIComponent(el.dataset.gid)}`).then(r => toast(r.msg)).catch(fail); break;
    case 'goto-tab': if (S.ed) location.hash = `#/g/${S.ed.gid}/${el.dataset.tab}`; break;
    case 'run': startGame(el.dataset.gid); break;
    case 'run-all': runAll(); break;
    case 'mount-add': openAddScript(); break;
    case 'watch-open': openAddWatch(); break;
    case 'watch-remove': watchToggle(el.dataset.gid, false); break;
    case 'go-news': newsUiInit().focus = el.dataset.gid; location.hash = '#/news'; break;
    case 'watch-done': watchDone(el.dataset.gid, el.dataset.on === '1'); break;
    case 'drawer': openDrawer(el.dataset.gid); break;
    case 'sch-settings': openSchSettings(); break;
    case 'res-add': resAdd(el.dataset.gid); break;
    case 'res-defs': resDefs(el.dataset.gid); break;
    case 'gacha-import': gachaImport(el.dataset.gid); break;
    case 'drawer-close': closeDrawer(); break;
    case 'sch-add-game': addFlow(el.dataset.gid); break;
    case 'today-add': addTodayTasks(el.dataset.gid); break;
    case 'run-again': runTasks(el.dataset.gid || S.ed?.gid, [el.dataset.key], el.dataset.kind); break;
    case 'news-hires': refetchBanners(el.dataset.gid); break;
    case 'news-regame': api('POST', '/api/news/refresh', { only: [el.dataset.gid] }).then(r => { toast(r.started ? `正在重新读取 ${shortName(el.dataset.gid)} 的活动，稍等一会儿` : `上一次读取还没结束${r.running ? `（正在读：${r.running}）` : ''}，等它读完再点`, !r.started); if (r.started) setTimeout(() => { if (S.route.view === 'news') renderNews(); }, 20000); }).catch(fail); break;
    case 'pk-queue': case 'pk-copy': case 'pk-new': case 'pk-del': presetAct(act, el); break;
    case 'rule-edit': editRule(el.dataset.id); break;
    case 'rule-add': editRule(null, el.dataset.gid, el.dataset.name); break;
    case 'routine-open': S.pendingRoutine = el.dataset.name; location.hash = `#/g/${el.dataset.gid}/routine`; break;
    case 'mount-remove': removeGame(el.dataset.gid); break;
    case 'mount-edit': editGame(el.dataset.gid); break;
    case 'mount-delete': deleteGame(el.dataset.gid); break;
    case 'mount-edit-open': loadGames().then(() => editGame(el.dataset.gid)).catch(fail); break;
    case 'mount-follow': api('POST', `/api/games/${el.dataset.gid}/follow`, { on: true }).then(() => { toast('已重新挂载'); return afterMountChange(); }).catch(fail); break;
    case 'pick-run': pickRun(el.dataset.gid); break;
    case 'stop': stopRun(); break;
    case 'skip-cur': skipCurrent(el.dataset.scope); break;
    case 'task-skip': taskSkip(el.dataset.key, el.dataset.on === '1'); break;
    case 'task-rerun': taskRerun(el.dataset.gid, (el.dataset.keys || '').split('\n').filter(Boolean)); break;
    case 'task-skip-many': taskSkipMany(el.dataset.gid, (el.dataset.keys || '').split('\n').filter(Boolean)); break;
    case 'mark-done': markDone(el.dataset.gid || S.ed?.gid, (el.dataset.keys || el.dataset.key || '').split('\n').filter(Boolean)); break;
    case 'suspend': api('POST', `/api/running/${el.dataset.on === '1' ? 'pause' : 'resume'}`).then(r => { toast(r.suspended ? '已原地暂停（BetterGI）' : '已继续'); pollRunning(); }).catch(fail); break;
    case 'answer': api('POST', '/api/scheduler/answer', { choice: el.dataset.choice }).then(() => pollRunning()).catch(fail); break;
    case 'yield': yieldPc(); break;
    case 'resume': resume(); break;
    case 'toggle': if (e.target.closest('.grip')) return; ed.open.has(i) ? ed.open.delete(i) : ed.open.add(i); refreshList(); break;
    case 'up': moveTask(i, i - 1); break;
    case 'down': moveTask(i, i + 1); break;
    case 'remove': {
      const t = ed.tasks[i]; ed.tasks.splice(i, 1);
      ed.open = new Set([...ed.open].filter(x => x !== i).map(x => x > i ? x - 1 : x)); touch(); toast(`已移除「${tn(keyOf(t))}」`); break;
    }
    case 'dup': { const t = clone(ed.tasks[i]); delete t.key; ed.tasks.splice(i + 1, 0, t); ed.open = new Set([...ed.open].map(x => x > i ? x + 1 : x)); ed.open.add(i + 1); touch(); toast('已再加一次，保存时会自动命名为「#2」，也可以自己改显示名'); break; }
    case 'reset-opts': { const td = taskDef(ed.tasks[i].task); ed.tasks[i].choices = isBgi(ed.gid) ? {} : clone(td?.mfa_choices || {}); touch(); break; }
    case 'open-tool': openTool(el.dataset.gid, el.dataset.updater === '1'); break;
    case 'import': importFromTool(); break;
    case 'resume-run': resumeRun(); break;
    case 'resume-drop': dropResume(); break;
    case 'rerun-bad': rerunBad(); break;
    case 'admin-hide': try { localStorage.setItem('gb-admin-hint', '1'); } catch (x) { /* 忽略 */ } renderBars(); break;
    case 'opt-seg': setOpt(i, el.dataset.opt, el.dataset.case); break;
    case 'opt-check': {
      const t = ed.tasks[i]; const td = taskDef(t.task); const cur = optValue(td, t, el.dataset.opt).slice();
      const k = cur.indexOf(el.dataset.case); k >= 0 ? cur.splice(k, 1) : cur.push(el.dataset.case);
      const od = S.schemas[ed.gid].options[el.dataset.opt]; setOpt(i, el.dataset.opt, (od.cases || []).map(c => c.name).filter(n => cur.includes(n))); break;
    }
    case 'add': addTasks(); break;
    case 'routine-pick': routineOp('pick', el.dataset.name); break;
    case 'routine-goto': routineOp('goto', el.dataset.name); break;
    case 'routine-new': routineOp('new'); break;
    case 'routine-import': importToolRoutines(S.ed?.gid); break;
    case 'routine-rename': routineOp('rename'); break;
    case 'routine-del': routineOp('del'); break;
    case 'save': save(); break;
    case 'discard': discard(); break;
    case 'run-task': { const id = el.dataset.id; ed.openRuns.has(id) ? ed.openRuns.delete(id) : ed.openRuns.add(id); renderRuns(); break; }
    case 'runs-refresh': renderRuns(); break;
    case 'shot': lightbox(el.dataset.src); break;
    case 'lib-enable': setTaskEnabled(el.dataset.task, true); break;
    case 'lib-disable': setTaskEnabled(el.dataset.task, false); break;
    case 'news-open': openNews(el.dataset.id); break;
    case 'news-home': location.hash = '#/news'; break;
    case 'set-home-order': setAppearance({ home_order: el.dataset.v }, el.dataset.v === 'news_first' ? '总览上当前活动放在上面' : '总览上日常一览放在上面'); break;
    case 'nd': newsAct({ act: el.dataset.a, id: el.dataset.id, game: el.dataset.game, cat: el.dataset.cat, ...(el.dataset.v !== undefined ? { value: el.dataset.v } : {}) }, $('#nd-body') ? el.dataset.id : null);
      if (el.dataset.a === 'pin_img') { const N = S.newsUi; if (N?.imgIdx) delete N.imgIdx[el.dataset.id]; toast(el.dataset.v ? '已固定为这个活动的题图' : '已恢复自动挑题图'); } break;
    case 'news-filter': openNewsFilter(); break;
    case 'edit-group': if (S.ed) editGroup(S.ed.gid, el.dataset.task); break;
    case 'tool-browse': case 'tool-scan': case 'tool-check': case 'tool-mumu': case 'tool-emu-close': toolAct(act, el); break;
    case 'setup-done': location.hash = '#/'; break;
    case 'pcres-on': api('PUT', `/api/games/${el.dataset.gid}`, { resolution_switch: el.dataset.on === '1' }).then(loadPcres).catch(fail); break;
    case 'pcres-restore': api('POST', `/api/pcres/${el.dataset.gid}/restore`).then(r => { toast(r.msg); loadPcres(); }).catch(fail); break;
    case 'sch-add': case 'sch-now': case 'sch-skip': case 'sch-del': case 'sch-rerun-bad': case 'sch-save-routine': case 'sch-on': scheduleAct(act, el); break;
    case 'set-wake': api('PUT', '/api/settings/scheduler', { wake_from_sleep: el.dataset.on === '1' }).then(() => { toast(el.dataset.on === '1' ? '叫醒电脑已打开' : '叫醒电脑已关闭'); renderSettings(); }).catch(fail); break;
    case 'app-restart': api('POST', '/api/app/restart').catch(() => {}); toast('正在重启管家后台，十来秒后自动连回'); setTimeout(() => location.reload(), 15000); break;
    case 'news-search': { const w = el.closest('.news-q'); const open = !w.classList.contains('open') || !!$('#news-q').value; w.classList.add('open'); S.newsUi.qOpen = true; if (open) $('#news-q').focus(); else { w.classList.remove('open'); S.newsUi.qOpen = false; } break; }
    case 'nf-cat': newsAct({ act: el.dataset.on === '1' ? 'unhide_cat' : 'hide_cat', game: el.dataset.game, cat: el.dataset.cat }); break;
    case 'nf-track': newsAct({ act: el.dataset.on === '1' ? 'untrack' : 'track', game: el.dataset.game, name: el.dataset.name }); break;
    case 'set-news': newsAct({ act: 'set', key: el.dataset.key, value: el.dataset.on === '1' }).then(loadPushNews); break;
    case 'news-slide': setSlide(S.newsUi.slide + (+el.dataset.d), +el.dataset.d); break;
    case 'news-dot': setSlide(+el.dataset.k); break;
    case 'news-month': S.newsUi.month = el.dataset.m; reGantt(); break;
    case 'news-week': S.newsUi.week = el.dataset.m; reGantt(); break;
    case 'news-view': S.newsUi.view = el.dataset.v; try { localStorage.setItem('gb-news-view', el.dataset.v); } catch (e2) { /* 忽略 */ } reGantt(); break;
    case 'news-focus': { const N = S.newsUi; N.focus = N.focus === el.dataset.gid ? null : el.dataset.gid; N.slide = 0; renderNews(); break; }
    case 'news-game': { const o = S.newsUi.off; const g = el.dataset.gid; const off = !o.has(g); off ? o.add(g) : o.delete(g); api('POST', '/api/news/act', { act: 'news_off', game: g, value: off }).catch(e => { off ? o.delete(g) : o.add(g); renderNews(); toast(`没保存上：${e.message}`, true); }); renderNews(); if ($('#nf-body')) $('#nf-body').innerHTML = newsFilterHtml(); break; }
    case 'news-refresh': api('POST', '/api/news/refresh', el.dataset.src ? { only: [el.dataset.src] } : {}).then(r => { if (!r.started) return toast(`上一次读取还没结束${r.running ? `（正在读：${r.running}）` : ''}，等它读完再点`, true); toast(el.dataset.src ? '正在重读这个来源，稍等一会儿' : '正在读取各游戏的官方公告，稍等一会儿'); setTimeout(() => { if (S.route.view === 'news') renderNews(); }, 15000); }).catch(fail); break;
    case 'set-palette': setPalette(el.dataset.p); break;
    case 'set-theme': setAppearance({ theme: el.dataset.t }, `已换成主题「${el.dataset.n}」`); break;
    case 'theme-import': importTheme(); break;
    case 'theme-export': exportTheme(el.dataset.t); break;
    case 'theme-del': deleteTheme(el.dataset.t); break;
    case 'set-ui-notes': setAppearance({ ui_notes: el.dataset.on === '1' }, el.dataset.on === '1' ? '左下角会显示「批注」' : '已隐藏「批注」').then(() => { if (S.state.appearance.ui_notes) unLoad(); }); break;
    case 'push-save': savePush(); break;
    case 'ev-save': saveEvidence(); break;
    case 'ev-clean': cleanEvidence(el.dataset.all === '1', el.dataset.what || 'evidence'); break;
    case 'push-test': testPush(); break;
    case 'push-onp': savePush({ on_problem: el.dataset.on === '1' }); break;
    case 'set-scheduler': setSetting('scheduler', el.dataset.on === '1'); break;
    case 'set-autostart': setSetting('autostart', el.dataset.on === '1'); break;
    case 'open-folder': api('POST', '/api/settings/open', { what: el.dataset.what }).catch(fail); break;
    case 'copy-report': {
      const r = S.reportShown; const txt = `${r.title}\n\n${r.text}`;
      try { await navigator.clipboard.writeText(txt); toast('已复制'); } catch (x) { const sel = window.getSelection(); const rg = document.createRange(); rg.selectNodeContents($('#report-text')); sel.removeAllRanges(); sel.addRange(rg); toast('已选中正文，按 Ctrl+C 复制'); }
      break;
    }
  }
});
document.addEventListener('keydown', e => {
  const el = e.target.closest?.('[data-act="open"],[data-act="goto-tab"],[data-act="toggle"].thead');
  if (el && (e.key === 'Enter' || e.key === ' ') && e.target === el) { e.preventDefault(); el.click(); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && S.dirty) { e.preventDefault(); save(); }
});
document.addEventListener('input', e => {
  if (e.target.id === 'news-q') { S.newsUi.q = e.target.value; const r = $('#news-res'); if (r) r.innerHTML = newsSearchHtml(S.news?.items || [], S.newsUi.q); return; }
  const el = e.target; const act = el.dataset?.act; if (!act || !S.ed) return; const ed = S.ed; const i = +el.dataset.i;
  if (act === 'filter') { ed.filter = el.value; refreshList(); return; }
  if (act === 'key') { const v = el.value.trim(); if (v) ed.tasks[i].key = v; else delete ed.tasks[i].key; touch(false); return; }
  if (act === 'window') {
    const v = el.value.trim(); ed.winEdits = ed.winEdits || {}; ed.winEdits[keyOf(ed.tasks[i])] = winBj(v);
    const err = $(`[data-err="window-${i}"]`); const bad = v && !WIN_RE.test(v.replace(/，/g, ','));
    el.classList.toggle('invalid', !!bad); if (err) err.textContent = bad ? '格式：HH:MM-HH:MM，多段用逗号隔开' : ''; touch(false); return;
  }
  if (act === 'opt-input') {
    const t = ed.tasks[i]; const td = taskDef(t.task); const name = el.dataset.opt;
    const v = optValue(td, t, name); v[el.dataset.inp] = el.value; t.choices = t.choices || {}; t.choices[name] = v;
    const od = S.schemas[ed.gid].options[name]; const inp = od.inputs.find(x => x.name === el.dataset.inp);
    el.classList.toggle('invalid', !inputOk(inp, el.value)); touch(false);
  }
});
document.addEventListener('change', e => {
  const el = e.target; const act = el.dataset?.act; if (!act) return;
  if (act === 'opt-select') setOpt(+el.dataset.i, el.dataset.opt, el.value);
  if (act === 'apply-src') applySource(el);
  if (act === 'runs-day') renderRuns(el.value);
  if (act === 'report-day') renderReport(el.value);
  if (act === 'tool-emu') toolAct(act, el);
  if (act === 'nd-cat') newsAct({ act: 'set_cat', id: el.dataset.id, cat: el.value }, el.dataset.id);
  if (act === 'nf-addchar' && el.value.trim()) { const g = el.dataset.game, n = el.value.trim(); api('POST', '/api/news/act', { act: 'add_char', game: g, name: n }).then(() => newsAct({ act: 'track', game: g, name: n })).catch(fail); }
});
function setOpt(i, name, v) {
  const t = S.ed.tasks[i]; t.choices = t.choices || {}; t.choices[name] = v; touch();
}

// ------------------------------------------------------------------ 路由
function parseHash() {
  const p = location.hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent).filter(Boolean);
  if (p[0] === 'report') return { view: 'report' };
  if (p[0] === 'settings') return { view: 'settings' };
  if (p[0] === 'news') return { view: 'news' };
  if (p[0] === 'schedule') return { view: 'schedule' };
  if (p[0] === 'presets') return { view: 'presets' };
  if (p[0] === 'setup') return { view: 'setup' };
  if (p[0] === 'g' && p[1]) return { view: 'game', gid: p[1], tab: TABS.some(t => t[0] === p[2]) ? p[2] : 'today' };
  return { view: 'home' };
}
let lastHash = location.hash, guard = false;
async function route() {
  if (S.drawer && !location.hash.startsWith('#/schedule')) closeDrawer();
  if (guard) { guard = false; return; }
  const next = parseHash();
  // 只在真有没存的改动时拦（以前「保存」后偶尔还会被拦：标记没清掉，内容其实已经存好了）
  const changed = S.ed && (JSON.stringify(S.ed.tasks) !== S.ed.saved || S.ed.forceDirty || Object.keys(S.ed.winEdits || {}).length);
  if (S.dirty && !changed) setDirty(false);
  const leaving = S.dirty && S.ed && !(next.view === 'game' && next.gid === S.ed.gid && next.tab === S.ed.tab);
  if (leaving) {
    const target = location.hash; guard = true; location.hash = lastHash;
    const ans = await modal({ title: '离开这一页？', body: '有未保存的修改。', ok: '保存并离开', alt: '不保存', cancel: '留在这里' });
    if (!ans) return;
    if (ans === true && !(await save(true))) return;
    setDirty(false); S.ed = null; guard = false; location.hash = target; return;
  }
  lastHash = location.hash;
  const st = S.navStack || (S.navStack = []);  // 自己记走过的页面：后退键回到来的地方
  if (st.length > 1 && st[st.length - 2] === location.hash) st.pop(); else if (st[st.length - 1] !== location.hash) st.push(location.hash);
  const prevR = S.route;
  S.route = next;
  if (prevR && (prevR.view !== next.view || prevR.gid !== next.gid || prevR.tab !== next.tab) && !matchMedia('(prefers-reduced-motion: reduce)').matches)
    $('#app').animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200, easing: 'ease-out' });  // 换页淡入（10-31）
  renderTop(); renderBars();
  if (next.view !== 'game') { S.ed = null; setDirty(false); }
  if (next.view === 'home') { renderHome(); Promise.all([loadState(), loadReport()]).then(() => { if (S.route.view === 'home') { renderHome(); renderTop(); } }).catch(failRead('主页数据')); }
  else if (next.view === 'report') renderReport();
  else if (next.view === 'settings') renderSettings();
  else if (next.view === 'news') renderNews();
  else if (next.view === 'schedule') renderSchedule();
  else if (next.view === 'presets') renderPresets();
  else if (next.view === 'setup') renderSetup();
  else {
    if (S.pendingRoutine && next.tab === 'routine') { S.ed = { gid: next.gid, routineName: S.pendingRoutine }; S.pendingRoutine = null; await openGame(next.gid, 'routine'); window.scrollTo(0, 0); return; }
    if (S.ed && (S.ed.gid !== next.gid || S.ed.tab !== next.tab)) S.ed = null;
    await openGame(next.gid, next.tab);
  }
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', route);
window.addEventListener('beforeunload', e => { if (S.dirty) { e.preventDefault(); e.returnValue = '有未保存的修改'; return e.returnValue; } });

(async function init() {
  try {
    await loadState();
    S.running = await api('GET', '/api/running'); syncResume(S.running);
    renderBars();
    const t = await api('GET', '/api/games'); if (t.needs_setup && !location.hash.startsWith('#/setup')) location.hash = '#/setup';
    await route();
    pollRunning();
  } catch (e) {
    $('#app').innerHTML = `<div class="glass skeleton">连不上管家：${esc(e.message)}<br><span class="small">请确认管家还在运行（任务栏右下角的托盘图标），或重新打开 GameButler.exe。</span></div>`;
  }
})();

// 任务里的「保存」：按下时不让输入框失焦（失焦会先重画列表，按钮被换掉，这次点击就丢了）
document.addEventListener('pointerdown', e => { if (e.target.closest?.('[data-save-slot]')) e.preventDefault(); }, true);
