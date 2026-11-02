// 日常管家界面 · 设置、工具与游戏、挂载。和其它 static/js/*.js 共用全局（不打包，按 index.html 里的顺序加载）。

'use strict';

// ------------------------------------------------------------------ 工具与游戏：挂载的游戏、工具路径、模拟器
S.games = null; S.emus = null;
async function loadGames() {
  const [g, e, w] = await Promise.all([api('GET', '/api/games'), api('GET', '/api/emulators'), api('GET', '/api/watch')]);
  S.games = g; S.emus = e; S.watchCat = w.games || [];
  return g;
}
function gameRow(t) {
  const dot = t.available ? ['已连接', 'ok'] : ['没接好', 'bad'];
  const insts = S.emus?.instances || [];
  const emuSel = t.needs_emulator ? `<label class="small muted tr-emu">模拟器实例 <select class="sel" data-act="tool-emu" data-gid="${esc(t.id)}">
      <option value="">选择…</option>${insts.map(i => `<option ${i.name === t.emulator ? 'selected' : ''} value="${esc(i.name)}">${esc(i.name)}${i.resolution ? ` · ${esc(i.resolution)}` : i.resolution_error ? ` · ${esc(i.resolution_error)}` : ''}</option>`).join('')}
      ${t.emulator && !insts.some(i => i.name === t.emulator) ? `<option selected value="${esc(t.emulator)}">${esc(t.emulator)}（没找到）</option>` : ''}</select></label>` : '';
  return `<div class="trow" data-gid="${esc(t.id)}">
    <div class="tr-h"><span class="avatar xs" style="background:${newsColor(t.id)}">${esc(markOf(t.name))}</span><b>${esc(splitName(t.name)[0])}</b>
      <span class="pill ${dot[1]}">${dot[0]}</span><span class="small muted">${esc(t.preset || KIND[t.type] || t.type)}</span><span style="flex:1"></span>
      <button class="btn xs ghost" data-act="mount-edit" data-gid="${esc(t.id)}">设置</button>
      <button class="btn xs ghost" data-act="mount-remove" data-gid="${esc(t.id)}">取消挂载 / 删除</button></div>
    <div class="tr-b">
      <div class="small num tr-path">${esc(t.path)}</div>
      <div class="tr-acts"><button class="btn xs" data-act="tool-browse" data-gid="${esc(t.id)}">换文件夹</button>${t.preset ? `<button class="btn xs" data-act="tool-scan" data-gid="${esc(t.id)}">自动查找</button>` : ''}
        <button class="btn xs ghost" data-act="tool-check" data-gid="${esc(t.id)}" title="查一遍：文件夹和工具文件在不在、模拟器实例对不对、分辨率合不合要求">检查</button>${t.url ? `<a class="btn xs ghost" href="https://github.com/${esc(t.url)}" target="_blank" rel="noopener">去下载</a>` : ''}${emuSel}</div>
      ${t.screen ? `<div class="xsmall faint">要求：${esc(t.screen)}</div>` : ''}
      ${!t.available && t.message ? `<div class="xsmall bwarn">${ICON.warn} ${esc(t.message)}</div>` : ''}
      <div class="tr-check" id="tc-${esc(t.id)}"></div></div>
  </div>`;
}
// MuMu 模拟器：设置页里是单独一块（和「工具与游戏」同级）；第一次使用页里接在脚本列表下面
function mumuHtml() {
  const mumu = S.emus;
  return `<div class="mumu-b">
      <div class="mumu-h"><span class="pill ${mumu?.ok ? 'ok' : 'bad'}">${mumu?.ok ? `找到 ${mumu.instances.length} 个实例` : '没找到'}</span><span class="small num tr-path">${esc(mumu?.mumu_dir || '')}</span><span style="flex:1"></span>
      <button class="btn xs" data-act="tool-mumu">选择 MuMu 文件夹</button></div>
      ${mumu && !mumu.ok ? `<div class="xsmall bwarn">${ICON.warn} ${esc(mumu.error || '')}</div>` : ''}
      <div class="xsmall faint">模拟器游戏在 MuMu 的多开器里各选一个实例；管家按实例名称自动开关模拟器。分辨率不符合工具要求时，在 MuMu 多开器里改该实例的分辨率。</div>
      ${mumu?.ok ? `<div class="lrow"><div class="nm"><b>跑完关模拟器</b><div>每次跑完关：省内存 / 显存，下次跑要多等一两分钟开机。一直开着：同一个模拟器的游戏隔开跑时不用重开，但一直占着内存。</div></div>
        <div class="seg" role="group" aria-label="跑完关模拟器"><button type="button" class="${mumu.close === 'each_run' ? 'on' : ''}" data-act="tool-emu-close" data-v="each_run">每次跑完关</button><button type="button" class="${mumu.close === 'keep_open' ? 'on' : ''}" data-act="tool-emu-close" data-v="keep_open">一直开着</button></div></div>` : ''}</div>`;
}
function drawTools() {
  const host = $('#tools-host'); if (host) host.innerHTML = gamesHtml();
  const mh = $('#mumu-host'); if (mh) mh.innerHTML = mumuHtml();
}
function gamesHtml() {
  const all = S.games?.games || [];
  const on = all.filter(t => t.followed), off = all.filter(t => !t.followed);
  const mumu = S.emus;
  const watched = (S.watchCat || []).filter(x => x.watched && !x.mounted);
  return `<div class="tools"><div class="trow add-row"><button class="btn sm dark" data-act="mount-add">＋ 添加脚本</button><button class="btn sm" data-act="watch-open">＋ 添加游戏</button>
      <span class="xsmall faint">添加脚本：选一个文件夹或程序（MaaFramework 项目、BetterGI、三月七、明日方舟 MAA，或任意命令行脚本），管家按时帮你跑。以前挂过的会恢复原来的设置。<br>添加游戏：不挂脚本，只看它的活动（官方站外来源）、在总览「日常一览」里自己标记今天做完没有。</span></div>
    ${on.map(gameRow).join('')}
    ${watched.length ? `<div class="trow"><div class="tr-h"><b>仅关注的游戏</b><span class="small faint">没挂脚本：看活动、手动标记完成；以后挂上它的脚本就自动按挂着的算</span></div>
      <div class="chips">${watched.map(x => `<span class="chip"><i class="dot" style="background:${newsColor(x.id)}"></i>${esc(x.name)} <button type="button" class="linkbtn" data-act="watch-remove" data-gid="${esc(x.id)}" title="不再关注：日常一览和活动里都不再出现（读过的活动留着，重新关注就接上）">不再关注</button></span>`).join('')}</div></div>` : ''}
    ${off.length ? `<div class="trow"><div class="tr-h"><b>取消挂载的游戏</b><span class="small faint">数据还在，重新挂载就接上</span></div>
      <div class="chips">${off.map(x => `<button class="btn xs" data-act="mount-follow" data-gid="${esc(x.id)}">＋ ${esc(splitName(x.name)[0])}</button><button class="btn xs ghost" data-act="mount-delete" data-gid="${esc(x.id)}" title="彻底删除">删除</button>`).join('')}</div></div>` : ''}

  </div>`;
}
function showCheck(gid, r) {
  const box = $('#tc-' + gid); if (!box) return;
  box.innerHTML = r.items.map(x => `<div class="xsmall ${x.ok ? 'tc-ok' : 'bwarn'}">${x.ok ? ICON.check : ICON.warn} ${esc(x.text)}</div>`).join('');
}
async function toolAct(act, el) {
  const gid = el.dataset.gid;
  const t = (S.games?.games || []).find(x => x.id === gid);
  const redraw = async () => { await loadGames(); drawTools(); };
  const setPath = async path => {
    await api('PUT', `/api/games/${gid}`, { [t.field]: path });
    await afterMountChange(); const c = await api('POST', `/api/games/${gid}/check`); showCheck(gid, c);
    toast(c.ok ? '已接好' : '路径已保存，但检查没通过，看下面的说明', !c.ok);
  };
  try {
    if (act === 'tool-browse') {
      toast('在电脑上弹出了文件夹选择窗口（可能在管家窗口后面）');
      const r = await api('POST', '/api/browse', { title: `选择 ${t.name} 用的工具${t.field === 'exe' ? '程序所在的文件夹' : '文件夹'}` });
      if (r.path) await setPath(r.path);
    } else if (act === 'tool-scan') {
      const r = await api('POST', `/api/games/${gid}/scan`);
      if (!r.found.length) return toast('常见位置没找到，请用「换文件夹」', true);
      let pick = r.found[0];
      if (r.found.length > 1) {
        pick = await modal({ title: '找到了几个', body: r.found.map((p, i) => `<label class="rad"><input type="radio" name="sc" value="${i}" ${i ? '' : 'checked'}> ${esc(p)}</label>`).join(''), ok: '用这个',
          onMount: (m, setVal) => setVal(() => r.found[+(m.querySelector('input[name=sc]:checked')?.value || 0)]) });
        if (!pick || pick === true) return;
      }
      await setPath(pick);
    } else if (act === 'tool-check') {
      showCheck(gid, await api('POST', `/api/games/${gid}/check`));
    } else if (act === 'tool-emu') {
      await api('PUT', `/api/games/${gid}`, { emulator: el.value }); await redraw(); showCheck(gid, await api('POST', `/api/games/${gid}/check`));
    } else if (act === 'tool-emu-close') {
      await api('PUT', '/api/settings/emulator', { close: el.dataset.v }); await redraw();
    } else if (act === 'tool-mumu') {
      toast('在电脑上弹出了文件夹选择窗口');
      const r = await api('POST', '/api/browse', { title: '选择 MuMu 模拟器的安装文件夹（里面有 nx_main）' });
      if (!r.path) return;
      await api('PUT', '/api/settings/emulator', { mumu_dir: r.path }); await redraw();
    }
  } catch (e) { fail(e); }
}
async function loadToolsSection() {
  const host = $('#tools-host'); if (!host) return;
  try { await loadGames(); drawTools(); } catch (e) { host.innerHTML = `<div class="small bwarn">${esc(e.message)}</div>`; }
}

// ------------------------------------------------------------------ 添加游戏（11-02）：仅关注，不挂脚本
function watchListHtml() {
  return `<div class="watch-list">${(S.watchCat || []).map(x => `<div class="wl-row"><i class="dot" style="background:${newsColor(x.id)}"></i><b>${esc(x.name)}</b>
    <span class="xsmall faint">每天北京 ${esc(x.refresh)} 刷新</span><span style="flex:1"></span>
    ${x.mounted ? '<span class="small muted">已挂脚本</span>' : x.watched
      ? `<span class="small muted">已关注</span><button type="button" class="btn xs ghost" data-w="0" data-gid="${esc(x.id)}">不再关注</button>`
      : `<button type="button" class="btn xs dark" data-w="1" data-gid="${esc(x.id)}">关注</button>`}</div>`).join('')}</div>
    <div class="xsmall faint" style="margin-top:10px">现在支持这些游戏（有官方站外来源的）；以后会加更多。</div>`;
}
async function watchToggle(gid, on) {
  try {
    const r = await api('POST', `/api/watch/${on ? 'add' : 'remove'}`, { game: gid });
    S.watchCat = r.games || S.watchCat;
    toast(on ? `已关注 ${(S.watchCat.find(x => x.id === gid) || {}).name || gid}：正在读它的活动` : '已不再关注');
    S.newsAt = 0; await afterMountChange();
  } catch (e) { fail(e); }
}
async function openAddWatch() {
  try { S.watchCat = (await api('GET', '/api/watch')).games || []; } catch (e) { return fail(e); }
  await modal({ title: '添加游戏', ok: '完成', cancel: '', body: `<div class="small muted" style="margin-bottom:12px">不挂脚本，只关注这个游戏：活动日历、轮播只读官方站外来源；总览「日常一览」里有它一行，做完了右键「标记已完成」。</div><div id="wl-host">${watchListHtml()}</div>`,
    onMount: m => m.addEventListener('click', async e => {
      const b = e.target.closest('[data-w]'); if (!b) return;
      b.disabled = true; await watchToggle(b.dataset.gid, b.dataset.w === '1');
      const h = m.querySelector('#wl-host'); if (h) h.innerHTML = watchListHtml();
    }) });
}

// ------------------------------------------------------------------ 挂载：添加脚本、取消挂载 / 重新挂载、彻底删除
async function afterMountChange() {
  S.schemas = {}; S.switches = {};
  await loadState();
  if ($('#tools-host')) await loadToolsSection();
  if (S.route.view === 'schedule') renderSchedule(); else if (S.route.view === 'home') renderHome();
  renderTop();
}
async function openAddScript(preset) {
  let p2 = preset;
  if (!p2) {
    const how = await modal({ title: '添加脚本', ok: '选文件夹', alt: '从常见脚本下载',
      body: '<div class="small">已经装好的脚本：选它所在的文件夹（MaaFramework 项目选有 interface.json 的那层），或命令行脚本的程序。<br>还没装的：从常见脚本列表下载（在你的电脑上从 GitHub 下载最新版）。</div>' });
    if (!how) return;
    if (how.alt) return openCatalog();
    toast('在电脑上弹出了文件夹选择窗口（可能在管家窗口后面）；也可以在下面直接粘贴路径');
    let path = '';
    try { path = (await api('POST', '/api/browse', { title: '选择脚本所在的文件夹（MaaFramework 项目选有 interface.json 的那层）' })).path || ''; } catch (e) { fail(e); }
    p2 = await modal({ title: '添加脚本', body: '<div class="small muted">脚本所在的文件夹，或命令行脚本的程序路径：</div>', input: { label: '', value: path, placeholder: 'F:\\M9A 或 D:\\tools\\run.bat' }, ok: '识别' });
  }
  if (!p2 || p2 === true) return;
  let d; try { d = await api('POST', '/api/games/detect', { path: p2 }); } catch (e) { return fail(e); }
  if (!d.ok) return toast(d.error || '没认出来', true);
  if (d.restore) {  // 以前挂过、取消了：恢复原来那一条（设置、计划、记录都接上）
    if (!(await confirmBox(`重新挂载「${esc(d.restore.name)}」？`, '这个脚本以前挂过。重新挂载会恢复原来的设置、计划和记录；路径变了的话只更新路径。', '重新挂载'))) return;
    try { const r = await api('POST', '/api/games', { ...d }); toast(`已重新挂载「${d.restore.name}」`); await afterMountChange(); location.hash = `#/g/${r.id}/today`; } catch (e) { fail(e); }
    return;
  }
  S.emus = S.emus || await api('GET', '/api/emulators');
  const insts = S.emus?.instances || [];
  const ctrls = d.controllers || [];
  const needsEmu = c => d.type === 'maa_ark' || (d.type === 'maa' && (c?.type || 'adb') === 'adb');
  const cmdRow = (c = {}) => `<div class="cmd-row"><input class="inp xs" data-k="name" placeholder="任务名" value="${esc(c.name || '')}"><input class="inp" data-k="args" placeholder="参数（可空）" value="${esc(c.args || '')}">
      <input class="inp xs num" data-k="timeout" type="number" min="1" value="${esc(c.timeout || 60)}" title="最长运行时间（分钟）"><input class="inp" data-k="done" placeholder="成功标志（日志里出现的字，可空 = 看退出码）" value="${esc(c.done || '')}"></div>`;
  const body = `<div class="add-form">
    <div class="small"><span class="pill ok">${esc(d.kind_label)}</span> <span class="num muted">${esc(d.path)}</span>${d.version ? ` · ${esc(d.version)}` : ''}${d.tasks ? ` · ${d.tasks} 个任务` : ''}</div>
    ${(d.warnings || []).map(w => `<div class="xsmall bwarn">${ICON.warn} ${esc(w)}</div>`).join('')}
    <label class="fld">显示名字 <input class="inp" id="af-name" value="${esc(d.name || '')}"></label>
    ${d.preset ? `<div class="xsmall faint">认出来是「${esc(d.preset.name)}」：会套用调好的运行设置（判定、超时、时段）。</div>` : ''}
    ${(d.tool_routines || []).length ? `<label class="fld chk"><input type="checkbox" id="af-import"> 一同导入工具自带的预设，做成任务预设：${esc(d.tool_routines.join('、'))}</label>
      <div class="xsmall faint">不导入的话任务预设是空的，挂上后在游戏页的任务库里自己勾。</div>` : '<div class="xsmall faint">挂上后任务预设是空的，在游戏页的任务库里自己勾要跑的任务。</div>'}
    <label class="fld">每天几点刷新（北京时间，必填） <input class="inp xs num" type="time" id="af-refresh" value="${esc(d.preset?.refresh || '')}"></label>
    ${ctrls.length > 1 ? `<label class="fld">控制方式 <select class="sel" id="af-ctl">${ctrls.map(c => `<option value="${esc(c.name)}">${esc(c.label)}（${c.type === 'win32' ? '电脑窗口' : '模拟器'}）</option>`).join('')}</select></label>` : ''}
    <label class="fld" id="af-emu-w" ${needsEmu(ctrls[0]) ? '' : 'hidden'}>模拟器实例 <select class="sel" id="af-emu"><option value="">选择…</option>${insts.map(i => `<option value="${esc(i.name)}">${esc(i.name)}${i.resolution ? ` · ${esc(i.resolution)}` : i.resolution_error ? ` · ${esc(i.resolution_error)}` : ''}</option>`).join('')}</select></label>
    ${d.type !== 'command' ? `<label class="fld">游戏包名（卡住时重启游戏用，可空） <input class="inp" id="af-pkg" value="${esc(d.package || '')}"></label>` : ''}
    ${d.type === 'command' ? `<div class="fld">任务（一条命令 = 一个任务）<div id="af-cmds">${cmdRow({ name: '运行' })}</div><button type="button" class="btn xs ghost" id="af-addcmd">＋ 再加一条</button>
      <span class="xsmall faint">成功标志留空时，程序正常退出（返回 0）就算完成。</span></div>
      <label class="fld">日志文件（可空，用来看进度、找成功标志） <input class="inp" id="af-log" placeholder="例如 D:\\tools\\logs\\*.log"></label>` : ''}
    ${d.type === 'maa_ark' ? '<div class="xsmall faint">明日方舟 MAA 通过它自带的命令行运行；任务和选项添加后在游戏页里设置。</div>' : ''}
  </div>`;
  const v = await modal({ title: '添加脚本', wide: true, ok: '添加', body,
    onMount: (m, setVal) => {
      const ctl = $('#af-ctl', m);
      if (ctl) ctl.onchange = () => { $('#af-emu-w', m).hidden = !needsEmu(ctrls.find(c => c.name === ctl.value)); };
      const add = $('#af-addcmd', m); if (add) add.onclick = () => $('#af-cmds', m).insertAdjacentHTML('beforeend', cmdRow());
      setVal(() => ({
        name: $('#af-name', m).value.trim(), refresh: $('#af-refresh', m).value, controller: ctl ? ctl.value : (ctrls[0]?.name || ''),
        emulator: $('#af-emu', m)?.value || '', package: $('#af-pkg', m)?.value.trim() || '', log_glob: $('#af-log', m)?.value.trim() || '',
        import_tool_routines: !!$('#af-import', m)?.checked,
        commands: [...m.querySelectorAll('.cmd-row')].map(r => { const g = k => r.querySelector(`[data-k=${k}]`).value.trim(); return { name: g('name'), args: g('args'), timeout: +g('timeout') || 60, done: g('done') ? [g('done')] : [] }; }),
      }));
    } });
  if (!v || v === true) return;
  try {
    const r = await api('POST', '/api/games', { ...d, ...v });
    toast(`已添加「${v.name || d.name}」`);
    await afterMountChange();
    location.hash = `#/g/${r.id}/today`;
  } catch (e) { fail(e); }
}
async function openCatalog() {
  let d; try { d = await api('GET', '/api/catalog'); } catch (e) { return fail(e); }
  const pick = await modal({ title: '常见脚本', ok: '', cancel: '关闭', wide: true,
    body: `<div class="small muted">点「下载」：选一个放的位置，管家在你的电脑上从 GitHub 下载最新版、解压，然后接着添加。</div>
      <div class="cat-list">${d.items.map(x => `<div class="cat"><div><b>${esc(x.name)}</b> <span class="small muted">${esc(x.game)} · ${esc(x.kind)}</span>
        <div class="xsmall"><a href="https://github.com/${esc(x.repo)}" target="_blank" rel="noopener">github.com/${esc(x.repo)}</a></div></div>
        <button class="btn xs" data-m="ok" data-pick="${esc(x.id)}">下载</button></div>`).join('')}</div>`,
    onMount: (m, setVal) => { m.addEventListener('click', e => { const b = e.target.closest('[data-pick]'); if (b) m._pick = b.dataset.pick; }, true); setVal(() => m._pick); } });
  if (!pick || pick === true) return;
  const it = d.items.find(x => x.id === pick);
  toast('选一个放脚本的文件夹（会在里面新建一个子文件夹）');
  let base = ''; try { base = (await api('POST', '/api/browse', { title: `选择 ${it.name} 放在哪里` })).path || ''; } catch (e) { fail(e); }
  if (!base) return;
  const dest = base.replace(/[\\/]+$/, '') + '\\' + it.name.replace(/[（）() ]+/g, '_').replace(/_+$/, '');
  let job; try { job = (await api('POST', '/api/catalog/download', { id: pick, dest })).job; } catch (e) { return fail(e); }
  for (let i = 0; i < 1200; i++) {
    await sleep(1500);
    let st; try { st = await api('GET', `/api/catalog/job/${encodeURIComponent(job)}`); } catch (e) { continue; }
    if (st.state === 'running') { toast(`${it.name}：${st.msg}${st.total ? `（${Math.round(st.done / st.total * 100)}%）` : ''}`); continue; }
    if (st.state === 'failed') return toast(`${it.name} 下载失败：${st.msg}`, true);
    if (st.state === 'done') { toast(`${it.name} 已下载到 ${st.path}`); return openAddScript(st.path); }
    return;
  }
}
async function removeGame(gid) {
  const g = (S.games?.games || []).find(x => x.id === gid) || game(gid) || { name: gid };
  const v = await modal({ title: `「${splitName(g.name)[0]}」`, ok: '取消挂载', alt: '彻底删除', danger: false,
    body: `<div class="small"><b>取消挂载</b>：不再出现在主页、日程和活动里，也不再自动运行。数据都留着，以后重新挂载（或再添加同一个脚本）就接上。</div>
      <div class="small" style="margin-top:8px"><b>彻底删除</b>：删掉它的设置、任务预设、计划、运行记录、截图、活动、读数和抽卡记录，像没挂过一样。删了不能恢复。</div>` });
  if (!v) return;
  if (v.alt) return deleteGame(gid);
  try { await api('POST', `/api/games/${gid}/follow`, { on: false }); toast('已取消挂载，数据保留'); await afterMountChange(); } catch (e) { fail(e); }
}
async function deleteGame(gid) {
  const g = (S.games?.games || []).find(x => x.id === gid) || { name: gid };
  if (!await confirmBox('确定彻底删除？', `<div class="small">「${esc(g.name)}」的设置和所有数据都会删掉，不能恢复。</div>`, '彻底删除', true)) return;
  try { await api('DELETE', `/api/games/${gid}`); toast('已彻底删除'); await afterMountChange(); } catch (e) { fail(e); }
}
async function editGame(gid) {
  const g = (S.games?.games || []).find(x => x.id === gid); if (!g) return;
  const cmds = g.commands ? Object.entries(g.commands).map(([name, c]) => ({ name, args: (c.args || []).join(' '), timeout: c.timeout, done: (c.done || [])[0] || '' })) : null;
  const cmdRow = (c = {}) => `<div class="cmd-row"><input class="inp xs" data-k="name" placeholder="任务名" value="${esc(c.name || '')}"><input class="inp" data-k="args" placeholder="参数（可空）" value="${esc(c.args || '')}">
      <input class="inp xs num" data-k="timeout" type="number" min="1" value="${esc(c.timeout || 60)}" title="最长运行时间（分钟）"><input class="inp" data-k="done" placeholder="成功标志（可空 = 看退出码）" value="${esc(c.done || '')}"></div>`;
  const v = await modal({ title: `设置「${g.name}」`, ok: '保存', wide: !!cmds, body: `<div class="add-form">
      <label class="fld">显示名字 <input class="inp" id="ce-name" value="${esc(g.name)}"></label>
      <label class="fld">每天几点刷新（北京时间） <input class="inp xs num" type="time" id="ce-refresh" value="${esc(g.refresh)}"></label>
      ${cmds ? `<div class="fld">任务（一条命令 = 一个任务）<div id="ce-cmds">${cmds.map(cmdRow).join('')}</div><button type="button" class="btn xs ghost" id="ce-addcmd">＋ 再加一条</button></div>` : ''}</div>`,
    onMount: (m, setVal) => {
      const add = $('#ce-addcmd', m); if (add) add.onclick = () => $('#ce-cmds', m).insertAdjacentHTML('beforeend', cmdRow());
      setVal(() => ({ name: $('#ce-name', m).value.trim(), refresh: $('#ce-refresh', m).value,
        ...(cmds ? { commands: [...m.querySelectorAll('.cmd-row')].map(r => { const x = k => r.querySelector(`[data-k=${k}]`).value.trim(); return { name: x('name'), args: x('args'), timeout: +x('timeout') || 60, done: x('done') ? [x('done')] : [] }; }) } : {}) }));
    } });
  if (!v || v === true) return;
  try { await api('PUT', `/api/games/${gid}`, v); toast('已保存'); await afterMountChange(); } catch (e) { fail(e); }
}
// 首次引导：还没挂过任何游戏时出现。选 MuMu 文件夹（模拟器游戏要用）→ 添加脚本（或从常见脚本下载）。
async function renderSetup() {
  try { await loadGames(); } catch (e) { $('#app').innerHTML = `<div class="glass skeleton">${esc(e.message)}</div>`; return; }
  if (S.route.view !== 'setup') return;
  const n = S.games.games.length + (S.watchCat || []).filter(x => x.watched).length;
  $('#app').innerHTML = `<div class="setup">
    <section class="hero"><div><div class="eyebrow">第一次使用</div><h1>把你的脚本挂上来</h1></div></section>
    <section class="glass panel"><div class="small muted">管家不自己打游戏，而是按时调用你装好的自动化脚本（MaaYuan、MaaSH、BetterGI、三月七……），再把结果、活动和抽卡资源汇总给你。</div>
      <ol class="setup-steps small">
        <li><b>添加脚本</b>：点下面的「＋ 添加脚本」，选脚本所在的文件夹。还没装脚本的，在弹窗里点「从常见脚本下载」。认得出来的脚本会自动套用调好的设置。</li>
        <li><b>选 MuMu 模拟器</b>（只有手游脚本需要）：一般会自动找到；没找到时点「选择 MuMu 文件夹」。只玩原神、崩铁这类电脑游戏可以跳过。</li>
        <li><b>进入总览</b>：之后在「日程」里排好时间，管家就会按时自动跑。</li>
        <li>还没有脚本、只想看活动？点「＋ 添加游戏」：不挂脚本也能看活动日历和轮播，在总览里自己标记今天做完没有。</li>
      </ol></section>
    <section class="glass panel" id="tools-host">${gamesHtml()}</section>
    <section class="glass panel"><div class="ph"><h3>MuMu 模拟器 <span class="xsmall faint">（只有手游脚本需要）</span></h3></div><div id="mumu-host">${mumuHtml()}</div></section>
    <div class="setup-nav"><span style="flex:1"></span><button class="btn dark" data-act="setup-done" ${n ? '' : 'disabled'}>${n ? '进入总览' : '先添加一个脚本或游戏'}</button></div>
  </div>`;
}

// ------------------------------------------------------------------ 设置
function themeChips() {
  const cur = S.state?.appearance?.theme || 'minimal', T = S.themes || { builtin: [], user: [] };
  const chip = (t, extra = '') => `<span class="chip${cur === t.id ? '' : ' gray'}"><button type="button" class="linkbtn" data-act="set-theme" data-t="${esc(t.id)}" data-n="${esc(t.name)}" aria-pressed="${cur === t.id}">${esc(t.name)}${cur === t.id ? ' · 正在用' : ''}</button>${extra}</span>`;
  return T.builtin.map(t => chip(t)).join('') + T.user.map(t => chip(t, ` <button type="button" class="linkbtn" data-act="theme-export" data-t="${esc(t.id)}">导出</button> <button type="button" class="linkbtn" data-act="theme-del" data-t="${esc(t.id)}">删除</button>`)).join('');
}
// 设置里每一块默认收起，点标题展开；这次打开过的块重画后保持打开
S.setOpen = S.setOpen || new Set();
function foldSettings() {
  $$('#app section.set').forEach(sec => {
    const k = sec.id || sec.querySelector('.section-h h2')?.textContent || '';
    sec.dataset.fold = k; sec.classList.add('fold'); sec.classList.toggle('open', S.setOpen.has(k));
  });
}
document.addEventListener('click', e => {
  const h = e.target.closest?.('#app section.set.fold > .section-h'); if (!h || e.target.closest('button,a,input,select')) return;
  const sec = h.parentElement; const k = sec.dataset.fold;
  sec.classList.toggle('open'); sec.classList.contains('open') ? S.setOpen.add(k) : S.setOpen.delete(k);
});
async function renderSettings() {
  let st;
  try { st = await api('GET', '/api/settings'); } catch (e) { $('#app').innerHTML = `<div class="glass skeleton">${esc(e.message)}</div>`; return; }
  if (S.route.view !== 'settings') return;
  const sch = await api('GET', '/api/scheduler');
  if (!S.themes) { try { S.themes = await api('GET', '/api/themes'); } catch (e) { fail(e); } }
  const seg = (name, on, disabled) => `<div class="seg" role="group" aria-label="${name}">
      <button type="button" class="${on ? 'on' : ''}" aria-pressed="${!!on}" data-act="set-${name}" data-on="1" ${disabled ? 'disabled' : ''}>开启</button><button type="button" class="${on ? '' : 'on'}" aria-pressed="${!on}" data-act="set-${name}" data-on="0" ${disabled ? 'disabled' : ''}>关闭</button></div>`;
  const a = st.autostart || {};
  const schedNote = st.scheduler.enabled ? (S.running?.paused || S.state?.paused ? `已开启，但现在处于「${esc((S.running?.paused || S.state?.paused).reason || '让出电脑')}」，恢复后才会自动跑` : `已开启${sch?.next_check ? ` · 下次检查 ${esc(String(sch.next_check).slice(11, 16))}` : ''}`)
    : '已关闭：只在你点「运行」时才跑';
  const autoNote = !a.available ? '用 GameButler.exe 启动管家后才能设置'
    : a.error ? esc(a.error)
    : a.on ? (a.ok ? '已开启：登录 Windows 后会在托盘里自动启动，不弹确认' : '已开启，但启动的不是这个文件夹里的管家，重新开启一次即可') : '已关闭';
  $('#app').innerHTML = `<div style="display:flex;flex-direction:column;gap:20px">
    <section class="hero"><div><div class="eyebrow">管家设置</div><h1 style="font-size:30px">设置</h1></div></section>
    <section class="lib glass set">
      <div class="section-h" style="padding:0 4px"><h2>工具与游戏</h2><span class="small muted">每个游戏用哪个工具、装在哪、用哪个模拟器实例</span></div>
      <div id="tools-host"><div class="small faint" style="padding:0 6px">读取中…</div></div>
    </section>
    <section class="lib glass set">
      <div class="section-h" style="padding:0 4px"><h2>工具更新</h2><span class="small muted">脚本工具有新版本时提醒；更新用它自己的更新器（按你在工具里设的渠道，GitHub 或 Mirror酱）</span></div>
      <div id="upd-host">${updatesHtml(S.updates)}</div>
    </section>
    <section class="lib glass set">
      <div class="section-h" style="padding:0 4px"><h2>MuMu 模拟器</h2><span class="small muted">模拟器游戏用哪个安装、跑完关不关</span></div>
      <div id="mumu-host"><div class="small faint" style="padding:0 6px">读取中…</div></div>
    </section>
    <section class="lib glass set">
      <div class="section-h" style="padding:0 4px"><h2>运行</h2></div>
      <div class="lrow"><div class="nm"><b>自动调度</b><div>开关、卡死处理、失败重试、闲时都在日程页的「调度设置」里。</div><div class="note">${schedNote}</div></div>
        <a class="btn" href="#/schedule" data-open-sch-settings="1">去调度设置</a></div>
      <div class="lrow"><div class="nm"><b>中止队列时，关闭模拟器和游戏</b><div>点「中止队列」后，等当前任务停下，再关掉所有模拟器实例和电脑游戏 / 工具（原来的「让出电脑」）。不勾就只停下，模拟器和游戏留着。</div></div>
        <label class="chk"><input type="checkbox" id="set-halt-close" ${st.scheduler.halt_close ? 'checked' : ''}><span>关闭</span></label></div>

      <div class="lrow"><div class="nm"><b>开机自动启动</b><div>登录 Windows 后，管家以管理员身份在托盘里启动，自动调度随之生效。</div><div class="note">${autoNote}</div></div>
        ${seg('autostart', a.on && !a.error, !a.available)}</div>
      <div class="lrow"><div class="nm"><b>叫醒电脑</b><div>电脑睡着时什么都不会跑。打开后，管家在下一个定时前用 Windows 的唤醒定时器把电脑叫醒；叫醒后通常是锁屏，模拟器游戏照跑，电脑游戏（原神、崩铁、剑三）要等解锁。最稳的做法：把 Windows 的「睡眠」设成「从不」，只让屏幕关掉。</div>
        <div class="note">${(() => { const p = st.power || {}; if (!p.supported) return '只在 Windows 上有'; const b = [];
          b.push(p.wake_timers === true ? 'Windows 已允许唤醒定时器' : p.wake_timers === false ? '<b>Windows 没有允许唤醒定时器</b>：控制面板 → 电源选项 → 更改计划设置 → 更改高级电源设置 → 睡眠 → 允许使用唤醒定时器 → 启用' : '读不到 Windows 是否允许唤醒定时器');
          b.push(p.sleep_after_min ? `${p.sleep_after_min} 分钟不用会睡眠` : p.sleep_after_min === 0 ? '从不睡眠' : '');
          b.push(p.password_on_wake ? '唤醒时要密码（会锁屏）' : p.password_on_wake === false ? '唤醒时不要密码' : '');
          if (p.next_wake) b.push(`下次叫醒：${esc(p.next_wake.slice(5))}（北京时间）`);
          if (p.wake_error) b.push(`<b>设叫醒失败</b>：${esc(p.wake_error)}`);
          return b.filter(Boolean).join(' · '); })()}</div></div>
        ${seg('wake', st.scheduler.wake_from_sleep)}</div>
    </section>
    ${(() => { // 游戏内读取（11-02）：活动尽量从站外读；只在站外都读不到、又允许时才进游戏读公告
      const ig = st.ingame || []; if (!ig.length) return '';
      const nt = ig.filter(x => x.notice), gc = ig.filter(x => x.gacha);
      return `<section class="lib glass set">
      <div class="section-h" style="padding:0 4px"><h2>游戏内读取</h2><span class="small muted">活动和题图先从站外读（官网、B 站、wiki、TapTap），不进游戏</span></div>
      ${nt.length ? `<div class="lrow"><div class="nm"><b>站外来源都读不到时，进游戏读公告</b><div>默认不进游戏。勾上后，某个游戏的站外来源上一次全都没读到时，它下次跑日常会顺带打开游戏内公告读一遍（多花 1–3 分钟）。会这样做的游戏：</div>
        <ul class="ig-list">${nt.map(x => `<li><b>${esc(splitName(x.name)[0])}</b><span class="xsmall faint">站外：${esc(x.offsite.join('、') || '没有')}</span>${x.down ? '<span class="badge bad">站外都没读到</span>' : x.unread ? '<span class="badge">还没读过</span>' : '<span class="badge ok">站外正常</span>'}</li>`).join('')}</ul></div>
        <label class="chk"><input type="checkbox" id="set-ig-fallback" ${st.news.ingame_fallback ? 'checked' : ''}><span>允许</span></label></div>` : ''}
      ${gc.length ? `<div class="lrow"><div class="nm"><b>跑日常时读抽卡资源</b><div>点进卡池界面读顶栏的抽卡货币和抽卡券（这个只能在游戏里读）。不勾的游戏不读。</div></div>
        <div class="rx-c">${gc.map(x => `<label class="chk"><input type="checkbox" data-read="read_gacha" data-gid="${esc(x.id)}" ${x.read_gacha ? 'checked' : ''}> ${esc(splitName(x.name)[0])}</label>`).join('')}</div></div>` : ''}</section>`;
    })()}
    ${pushSection(st.push)}
    <section class="lib glass set" id="ev-set"><div class="section-h" style="padding:0 4px"><h2>运行记录输出 · 留证截图</h2></div><div class="small faint" style="padding:0 6px">读取中…</div></section>
    <section class="lib glass set">
      <div class="section-h" style="padding:0 4px"><h2>外观</h2></div>
      <div class="lrow"><div class="nm"><b>界面主题</b><div>换主题只换颜色、透明度和阴影，页面的层次不变。自建主题可以导入 / 导出成文件。</div></div>
        <div class="chips">${themeChips()}<button class="btn xs" data-act="theme-import">导入主题文件</button></div></div>
      <div class="lrow"><div class="nm"><b>总览上先放哪块</b><div>「日常一览」和「当前活动」谁在上面。</div></div>
        <div class="seg" role="group" aria-label="总览上先放哪块"><button type="button" class="${S.state?.appearance?.home_order === 'news_first' ? '' : 'on'}" data-act="set-home-order" data-v="daily_first">日常一览在上</button><button type="button" class="${S.state?.appearance?.home_order === 'news_first' ? 'on' : ''}" data-act="set-home-order" data-v="news_first">当前活动在上</button></div></div>
      <div class="small muted" style="padding:6px 6px 0">游戏配色：总览、活动日历、日程里的游戏颜色都跟着变</div>
      <div class="pals">${Object.keys(PALETTES).map(n => { const on = palName() === n; return `<button type="button" class="pal${on ? ' on' : ''}" data-act="set-palette" data-p="${esc(n)}" aria-pressed="${on}">
        <div class="sw">${(S.state?.games || []).map((g, i) => { const c = PALETTES[n][g.id] || SPARE[i % SPARE.length]; return `<i style="background:${c};color:${onColor(c)}">${esc(markOf(g.name))}</i>`; }).join('')}</div>
        <b>${esc(n)}${n === '雾光' ? '<span class="xsmall faint">（默认）</span>' : ''}</b><span class="xsmall muted">${esc(PALETTE_DESC[n])}</span></button>`; }).join('')}</div>
      ${gameColorsHtml()}
    </section>
    <section class="lib glass set">
      <div class="section-h" style="padding:0 4px"><h2>文件</h2></div>
      <div class="lrow"><div class="nm"><b>日志文件夹</b><div>管家自身的日志 butler.log，以及每次运行的输出 run-*.log。出问题时把最新的发过来最有用。</div><div class="note num">${esc(st.logs_dir)}</div></div>
        <button class="btn sm" data-act="open-folder" data-what="logs">打开日志文件夹</button></div>
      <div class="lrow"><div class="nm"><b>管家文件夹</b><div>这台电脑的设置 config\\butler.toml、游戏和其他设置在 data（界面里改）、备用工具 tools。</div><div class="note num">${esc(st.root)}</div></div>
        <button class="btn sm" data-act="open-folder" data-what="root">打开管家文件夹</button></div>
      <div class="lrow"><div class="nm"><b>重启管家后台</b><div>改了 config\\butler.toml、或更新了管家之后用。窗口不关，十来秒后自动连回；正在进行的运行不受影响。</div></div>
        <button class="btn sm" data-act="app-restart">重启管家后台</button></div>
    </section>
    <div class="small faint" style="padding:0 6px">管理员身份：${st.admin ? '是' : '否（BetterGI、三月七启动时可能会弹确认窗口）'}</div>
  </div>`;
  loadEvidenceSection(); loadPushNews(); loadPcres(); loadToolsSection(); foldSettings();
}
async function loadEvidenceSection() {
  const box = $('#ev-set'); if (!box) return;
  let d;
  try { d = await api('GET', '/api/evidence'); } catch (e) { box.querySelector('.small').textContent = e.message; return; }
  S.evidence = d;
  const games = d.games || [];
  const f = d.fail || {};
  box.innerHTML = `<div class="section-h" style="padding:0 4px"><h2>运行记录输出 · 截图</h2><span class="small muted num">留证 ${d.files || 0} 张 · ${d.mb || 0} MB　失败 ${f.files || 0} 张 · ${f.mb || 0} MB</span></div>
    <div class="small muted" style="padding:0 6px">两种截图，都只在电脑上看，不会推送到微信：<br><b>留证截图</b>：勾选的任务做成时截一张游戏画面（地宫选层这类关键步骤也会截），用来核对「到底做没做、做的是哪个」；任务没做成就不留证。目前只支持模拟器上的游戏。<br><b>失败截图</b>：任何任务卡住或失败时自动截的，看停在哪个画面；自动保留 14 天。</div>
    ${games.map(g => { const on = g.tasks.filter(t => t.on).length; return `<details class="ev-game"${on ? ' open' : ''}><summary><i style="background:${newsColor(g.id)}"></i><b>${esc(g.name)}</b><span class="small faint">已选 ${on} 个</span></summary>
      <div class="ev-tasks">${g.tasks.map(t => `<label class="ev-t"><input type="checkbox" data-ev-game="${esc(g.id)}" value="${esc(t.task)}" ${t.on ? 'checked' : ''}><span>${esc(tn(t.task))}</span></label>`).join('')}</div></details>`; }).join('') || '<div class="small faint" style="padding:0 6px">没有可以截图的游戏</div>'}
    <div class="lrow"><div class="nm"><b>保留天数</b><div>超过这个天数的留证截图会自动删除</div></div>
      <input class="inp num" id="ev-keep" type="number" min="1" max="60" value="${esc(d.keep_days)}" style="width:90px"></div>
    <div class="push-acts"><button class="btn sm warn" data-act="ev-clean" data-all="1">删除全部留证截图</button><button class="btn sm" data-act="ev-clean" data-all="0">只删今天以前的</button><span style="flex:1"></span><span class="xsmall faint">改了就自动保存</span></div>
    <div class="lrow"><div class="nm"><b>失败截图</b><div>已存 ${f.files || 0} 张 · ${f.mb || 0} MB。删掉后运行记录里对应的截图就看不到了。</div></div>
      <div class="push-acts"><button class="btn sm warn" data-act="ev-clean" data-what="fail" data-all="1">删除全部失败截图</button><button class="btn sm" data-act="ev-clean" data-what="fail" data-all="0">只删今天以前的</button></div></div>`;
}
async function saveEvidence() {
  const tasks = {};
  (S.evidence?.games || []).forEach(g => { tasks[g.id] = []; });
  $$('#ev-set input[data-ev-game]').forEach(i => { if (i.checked) tasks[i.dataset.evGame].push(i.value); });
  try { await api('PUT', '/api/settings/evidence', { tasks, keep_days: +$('#ev-keep').value }); toast('已保存'); } catch (e) { fail(e); loadEvidenceSection(); }
}
// 留证截图的勾选、保留天数：改了就存（11-02 批注 #162）
document.addEventListener('change', e => { if (e.target.closest?.('#ev-set') && (e.target.matches('input[data-ev-game]') || e.target.id === 'ev-keep')) saveEvidence(); });
async function cleanEvidence(all, what = 'evidence') {
  const today = reportDay() === 'today' ? new Date(nowBjMs() + 8 * 3600e3).toISOString().slice(0, 10) : reportDay();
  const name = what === 'fail' ? '失败截图' : '留证截图';
  const ok = await modal({ title: all ? `删除全部${name}？` : `删除今天以前的${name}？`, body: '删除后不能恢复。', ok: '删除', danger: true });
  if (!ok) return;
  try {
    const r = await api('POST', '/api/evidence/clean', { what, ...(all ? { all: true } : { before: today }) });
    toast(what === 'fail' ? `已删除 ${r.files} 张失败截图` : `已删除 ${r.days} 天的留证截图`); loadEvidenceSection();
  } catch (e) { fail(e); }
}
function pushSection(p) {
  if (!p) return '';
  return `<section class="lib glass set" id="push-set">
    <div class="section-h" style="padding:0 4px"><h2>微信推送</h2><span class="small muted">${p.configured ? `已设置 · ${esc(p.token_masked)}` : '还没设置'}</span></div>
    <div class="push-help small muted">
      用 <b>Server酱</b> 把每天的汇总和新出现的问题推到你的微信（免费额度每天 5 条，管家每天最多推几条）。<br>
      1. 打开 <a href="https://sct.ftqq.com/" target="_blank" rel="noopener">Server酱官网</a>，用微信扫码登录；<br>
      2. 进入 <a href="https://sct.ftqq.com/sendkey" target="_blank" rel="noopener">SendKey 页面</a>，复制以 SCT 开头的 SendKey，粘贴到下面；<br>
      3. 点「发送测试消息」，微信里收到就设置好了。消息通道、更多用法见 <a href="https://github.com/easychen/serverchan-sdk" target="_blank" rel="noopener">Server酱官方说明</a>。<br>
      <span style="color:var(--orange-ink)">SendKey 相当于往你微信发消息的钥匙，不要发给别人；它只存在本机的管家数据里。</span>
    </div>
    <div class="lrow"><div class="nm"><b>SendKey</b><div>${p.configured ? '已保存，界面上只显示前后几位。要换新的直接粘贴覆盖。' : '粘贴 Server酱的 SendKey'}</div></div>
      <input class="inp" id="push-token" type="password" autocomplete="off" placeholder="${p.configured ? esc(p.token_masked) : 'SCT……'}" style="width:min(320px,100%)"></div>
    <div class="lrow"><div class="nm"><b>每天汇总</b><div>北京时间几点推当天的完成情况；留空 = 不推汇总</div></div>
      <input class="inp num" id="push-at" type="time" value="${esc(p.daily_at || '')}" style="width:140px"></div>
    <div class="lrow"><div class="nm"><b>出问题时推送</b><div>每次运行结束，有新的失败或提醒就推一条（同一条当天只推一次）</div></div>
      <div class="seg" role="group" aria-label="出问题时推送"><button type="button" class="${p.on_problem ? 'on' : ''}" data-act="push-onp" data-on="1">开启</button><button type="button" class="${p.on_problem ? '' : 'on'}" data-act="push-onp" data-on="0">关闭</button></div></div>
    <div id="push-news"></div>
    <div class="push-acts"><span class="small faint">${p.last ? '上次推送：' + esc(p.last) : ''}</span><span style="flex:1"></span>
      <button class="btn sm" data-act="push-test" ${p.configured ? '' : 'disabled'}>发送测试消息</button>
      <button class="btn sm dark" data-act="push-save">保存</button></div>
    <details class="push-sample" id="push-sample"><summary class="small">看一眼推送的内容（按今天的记录生成的示例）</summary><div class="small faint">读取中…</div></details>
  </section>`;
}
// 推送内容示例（原来在运行记录页右边的「推送正文」）
document.addEventListener('toggle', async e => {
  const d = e.target; if (d.id !== 'push-sample' || !d.open || d.dataset.loaded) return;
  try {
    const r = await api('GET', '/api/report/today'); d.dataset.loaded = '1'; S.reportShown = r;
    d.querySelector('div').outerHTML = `<pre class="report-text" id="report-text"><b>${esc(r.title)}</b>\n\n${esc(r.text || '（空）')}</pre><div><button class="btn sm" data-act="copy-report">复制</button></div>`;
  } catch (x) { d.querySelector('div').textContent = x.message; }
}, true);
async function loadPcres() {
  let box = $('#pcres-set');
  if (!box) { const anchor = $('#ev-set'); if (!anchor) return; anchor.insertAdjacentHTML('afterend', '<section class="lib glass set" id="pcres-set"></section>'); box = $('#pcres-set'); foldSettings(); }
  let d; try { d = await api('GET', '/api/pcres'); } catch (e) { box.innerHTML = `<div class="section-h" style="padding:0 4px"><h2>电脑游戏分辨率</h2></div>${unreadHtml('分辨率设置', e)}`; return; }
  const scr = d.screen ? `${d.screen[0]}×${d.screen[1]}` : '未知';
  const small = d.screen && (d.screen[0] < 1920 || d.screen[1] < 1080);
  box.innerHTML = `<div class="section-h" style="padding:0 4px"><h2>电脑游戏分辨率</h2><span class="small muted">屏幕 ${esc(scr)}</span></div>
    <div class="small muted" style="padding:0 6px">BetterGI 要求原神为 1920×1080 窗口模式。屏幕分辨率低于 1920×1080 的电脑放不下这个窗口，这时管家会提示并跳过这次运行。只改游戏自己的设置（相当于在游戏设置里改），游戏开着时不改。${small ? '<b style="color:var(--orange-ink)"> 你的屏幕小于 1920×1080。</b>' : ''}</div>
    ${Object.entries(d.games).map(([gid, x]) => `<div class="lrow"><div class="nm"><b>${esc(splitName(x.name)[0])}：运行前调整为 1920×1080 窗口化，跑完恢复</b>
      <div>${x.found ? `游戏现在的设置：${x.width}×${x.height}${x.windowed === true ? ' 窗口' : x.windowed === false ? ' 全屏' : ''}${x.ok ? '（已经是 1920×1080 窗口）' : ''}` : esc(x.error || '没读到')}${x.pending_restore ? ' · <b style="color:var(--orange-ink)">有一次调整还没恢复</b>' : ''}</div></div>
      <div style="display:flex;gap:8px;align-items:center">${x.pending_restore ? `<button class="btn xs" data-act="pcres-restore" data-gid="${gid}">恢复原分辨率</button>` : ''}
      <div class="seg" role="group"><button type="button" class="${x.enabled ? 'on' : ''}" data-act="pcres-on" data-gid="${gid}" data-on="1">开启</button><button type="button" class="${x.enabled ? '' : 'on'}" data-act="pcres-on" data-gid="${gid}" data-on="0">关闭</button></div></div></div>`).join('')}`;
}
async function loadPushNews() {
  const box = $('#push-news'); if (!box) return;
  let d; try { d = await api('GET', '/api/news'); S.news = d; } catch (e) { box.innerHTML = unreadHtml('活动推送设置', e); return; }
  const p = d.prefs || {};
  const sw = (key, on) => `<div class="seg" role="group"><button type="button" class="${on ? 'on' : ''}" data-act="set-news" data-key="${key}" data-on="1">开启</button><button type="button" class="${on ? '' : 'on'}" data-act="set-news" data-key="${key}" data-on="0">关闭</button></div>`;
  box.innerHTML = `<div class="lrow"><div class="nm"><b>推送关注的活动</b><div>加了星标的活动跟每天汇总一起推：名字、结束时间、还剩多久</div></div>${sw('push_followed', p.push_followed)}</div>
    <div class="lrow"><div class="nm"><b>附带活动题图</b><div>在推送里带上题图（Server酱消息里显示为图片；图片从官方地址加载）</div></div>${sw('push_images', p.push_images)}</div>
    <div class="lrow"><div class="nm"><b>抓取版本更新 / 说明类公告</b><div>默认不抓。打开后这些也会读进来，但仍默认不显示，可以在活动页「筛选与关注」里查看</div></div>${sw('fetch_all', p.fetch_all)}</div>`;
}
async function savePush(extra = {}) {
  const tok = ($('#push-token')?.value || '').trim();
  const body = { provider: 'serverchan', daily_at: $('#push-at')?.value || '', ...extra };
  if (tok) body.token = tok;
  try { await api('PUT', '/api/settings/push', body); toast('推送设置已保存'); renderSettings(); return true; } catch (e) { fail(e); return false; }
}
async function testPush() {
  try { const r = await api('POST', '/api/push/test'); toast(r.message || '已推送，去微信看看'); } catch (e) { fail(e); }
  renderSettings();
}
async function setAppearance(patch, msg) {
  try {
    const r = await api('PUT', '/api/settings/appearance', patch);
    S.state.appearance = r.appearance;
    await applyTheme(r.appearance); unBtn();
    if (msg) toast(msg);
    renderSettings();
  } catch (e) { fail(e); }
}
function pickFile(accept) {
  return new Promise(res => { const i = document.createElement('input'); i.type = 'file'; i.accept = accept; i.onchange = () => res(i.files[0] || null); i.click(); });
}
async function importTheme() {  // 自建主题：导入 JSON 文件（格式见 butler/themes.py；设计文档里有编辑器的样子）
  const f = await pickFile('.json,application/json'); if (!f) return;
  let doc; try { doc = JSON.parse(await f.text()); } catch (e) { return fail(new Error(`不是 JSON 文件：${e.message}`)); }
  const id = (f.name.replace(/\.json$/i, '').replace(/[^\w-]+/g, '-').replace(/^-+|-+$/g, '') || 'theme').slice(0, 40);
  try { await api('PUT', `/api/themes/${encodeURIComponent(id)}`, doc); S.themes = null; S.themeApplied = ''; toast(`已导入主题「${doc.name}」`); renderSettings(); } catch (e) { fail(e); }
}
function exportTheme(tid) {
  const u = (S.themes?.user || []).find(t => t.id === tid); if (!u) return;
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify({ name: u.name, base: u.base, vars: u.vars }, null, 1)], { type: 'application/json' }));
  a.download = `${tid.slice(5)}.json`; a.click();
}
async function deleteTheme(tid) {
  if (!await modal({ title: '删除主题', body: '删掉这个自建主题？', ok: '删除' })) return;
  try { await api('DELETE', `/api/themes/${encodeURIComponent(tid.slice(5))}`); S.themes = null; toast('已删除'); renderSettings(); } catch (e) { fail(e); }
}
// 自己定游戏颜色：盖过上面配色方案里的颜色；「恢复」= 跟着配色方案
function gameColorsHtml() {
  const own = S.state?.appearance?.game_colors || {};
  const games = S.state?.games || [];
  const base = (g, i) => PALETTES[palName()][g.id] || SPARE[i % SPARE.length];
  return `<div class="gcolors"><div class="small muted">自己定颜色（只改你选的游戏，其余跟着上面的配色）</div>
    ${games.map((g, i) => `<label class="gcolor"><input type="color" value="${esc(own[g.id] || base(g, i))}" data-gcolor="${esc(g.id)}" aria-label="${esc(splitName(g.name)[0])} 的颜色"><span>${esc(splitName(g.name)[0])}</span>
      ${own[g.id] ? `<button type="button" class="linkbtn" data-gcolor-reset="${esc(g.id)}">恢复</button>` : ''}</label>`).join('')}</div>`;
}
async function setGameColor(gid, color) {
  const cur = { ...(S.state?.appearance?.game_colors || {}) };
  if (color) cur[gid] = color.toUpperCase(); else delete cur[gid];
  await setAppearance({ game_colors: cur }, color ? '颜色已换' : '已恢复成配色方案里的颜色');
}
document.addEventListener('change', e => { const c = e.target.closest?.('[data-gcolor]'); if (c) setGameColor(c.dataset.gcolor, c.value); });
document.addEventListener('click', e => { const c = e.target.closest?.('[data-gcolor-reset]'); if (c) { e.preventDefault(); setGameColor(c.dataset.gcolorReset, ''); } });
async function setPalette(name) {
  try {
    const r = await api('PUT', '/api/settings/appearance', { palette: name });
    S.state.appearance = r.appearance;
    toast(`已换成「${name}」配色`);
    renderSettings();
  } catch (e) { fail(e); }
}
document.addEventListener('change', async e => { // 站外来源都读不到时，进游戏读公告
  if (e.target.id !== 'set-ig-fallback') return;
  try { await api('PUT', '/api/settings/news', { ingame_fallback: e.target.checked }); toast(e.target.checked ? '站外都读不到时，会进游戏读公告' : '不再进游戏读公告'); }
  catch (err) { e.target.checked = !e.target.checked; fail(err); }
});
document.addEventListener('change', async e => { // 「中止队列时，关闭模拟器和游戏」：勾了立即保存
  if (e.target.id !== 'set-halt-close') return;
  try { await api('PUT', '/api/settings/scheduler', { halt_close: e.target.checked }); toast(e.target.checked ? '中止队列时会关闭模拟器和游戏' : '中止队列时只停下，不关模拟器和游戏'); }
  catch (err) { e.target.checked = !e.target.checked; fail(err); }
});
async function setSetting(name, on) {
  try {
    if (name === 'scheduler') { if (on) await schedulerOn(); else await api('POST', '/api/scheduler/off'); }
    else {
      toast(on ? '正在设置开机自动启动…' : '正在取消开机自动启动…');
      await api('POST', '/api/settings/autostart', { on });
    }
    toast(name === 'scheduler' ? (on ? '自动调度已开启' : '自动调度已关闭') : (on ? '开机自动启动已开启' : '开机自动启动已关闭'));
  } catch (e) { fail(e); }
  if (S.route.view === 'settings') renderSettings();
}

// 工具更新（11-01）：/api/updates 是缓存，管家每 12 小时查一次；「现在检查」马上查
function updatesHtml(u) {
  if (!u) { api('GET', '/api/updates').then(r => { S.updates = r; const h = $('#upd-host'); if (h) h.innerHTML = updatesHtml(r); }).catch(() => {}); return '<div class="small faint" style="padding:0 6px">读取中…</div>'; }
  const rows = (u.tools || []).map(t => `<div class="lrow"><div class="nm"><b>${esc(t.name)}</b><div>${esc(t.games.map(shortName).join('、'))} · 本机 ${esc(t.version)}${t.latest ? ` · 最新 ${esc(t.latest)}（${esc(t.source)}）` : ''}${t.errors?.length && !t.latest ? ` · 没查到：${esc(t.errors.join('；'))}` : ''}</div></div>
    ${t.newer ? `<span class="badge bad">有新版本</span><button class="btn sm" data-act="open-tool" data-updater="1" data-gid="${esc(t.games[0])}" title="打开 ${esc(t.name)}，用它自带的更新器更新">打开更新</button>${t.url ? `<a class="btn sm ghost" href="${esc(t.url)}" target="_blank" rel="noopener">看更新说明</a>` : ''}` : t.latest ? '<span class="badge ok">已是最新</span>' : ''}</div>`).join('');
  return `${rows || '<div class="small faint" style="padding:0 6px">没有能查版本的工具（工具的 interface.json 里要有 version 和 github / mirrorchyan_rid）</div>'}
    <div class="lrow"><div class="nm"><div>${u.checked ? `上次检查：${esc(u.checked)}（北京时间）` : '还没检查过'}</div></div><button class="btn sm" data-act="upd-check">现在检查</button></div>`;
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-act="upd-check"]'); if (!b) return;
  b.disabled = true; b.textContent = '检查中…';
  try { S.updates = await api('POST', '/api/updates/check'); const h = $('#upd-host'); if (h) h.innerHTML = updatesHtml(S.updates); toast('已检查'); }
  catch (x) { fail(x); b.disabled = false; b.textContent = '现在检查'; }
});

document.addEventListener('click', e => { if (e.target.closest?.('[data-open-sch-settings]')) setTimeout(() => { if (typeof openSchSettings === 'function') openSchSettings(); }, 600); });
