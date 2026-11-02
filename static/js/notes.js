// 日常管家界面 · 界面批注（调优期间用，定稿后整个文件连同 app.css 里「界面批注」一段、butler/uinotes.py 一起删掉）。
// 和其它 static/js/*.js 共用全局（不打包，按 index.html 里的顺序加载）。

'use strict';

// ------------------------------------------------------------------ 界面批注（10-28 第二版）
// 左下角「批注」→ 点界面上任意东西 → 选一种：改文字 / 改层级 / 挪位置 / 其他。
// 改文字会当场替换成新文字给你看（刷新后恢复，等开发照批注改）；挪位置可以再点一下「挪到哪儿」的参照物。
// 存在 data/ui_notes.json：comment 是给人看的一句话，kind / change 是给开发读的结构。
const UN = { on: false, notes: [], picking: null };
const UN_KINDS = [['text', '改文字'], ['layer', '改层级'], ['move', '挪位置'], ['other', '其他']];
const UN_LAYER = [
  ['up', '更醒目一点'], ['down', '更不显眼一点'], ['primary', '改成实心主按钮（一屏只能一个）'], ['outline', '改成描边按钮（改状态的操作）'],
  ['link', '改成文字链接（只是看 / 去别处）'], ['l1', '升成区块标题（20px + 黑线）'], ['l2', '降成普通行'], ['hide', '收起来（放进二级 / 更多）'], ['remove', '删掉'],
];
const UN_REL = [['before', '前面'], ['after', '后面'], ['left', '左边'], ['right', '右边'], ['inside', '里面'], ['page', '换到别的页（写在说明里）']];
const unTextOf = el => (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || el.value || '').trim().replace(/\s+/g, ' ').slice(0, 200);
function unDesc(el) {  // 给开发者看的位置描述：页面里的路径 + 文字
  const parts = []; let x = el;
  for (let i = 0; x && x !== document.body && i < 6; i++, x = x.parentElement) {
    let s = x.tagName.toLowerCase();
    if (x.id) s += '#' + x.id;
    const cls = [...x.classList].filter(c => !/^(on|live|over|drag|un-)/.test(c)).slice(0, 2);
    if (cls.length) s += '.' + cls.join('.');
    if (x.dataset?.act) s += `[act=${x.dataset.act}]`;
    parts.unshift(s);
  }
  return parts.join(' > ');
}
const unShort = t => t ? `「${t.length > 24 ? t.slice(0, 24) + '…' : t}」` : '这里';
// 批注自己的弹窗：单独一层（#un-dlg），盖在界面弹窗上面，不会把正在批注的界面弹窗关掉
function unDialog({ title, body = '', ok = '确定', cancel = '取消', wide = false, onMount = null }) {
  return new Promise(resolve => {
    let root = $('#un-dlg');
    if (!root) { root = document.createElement('div'); root.id = 'un-dlg'; document.body.appendChild(root); }
    root.innerHTML = `<div class="modal-bg un-dlg-bg"><div class="modal glass${wide ? ' wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="mh"><h3>${esc(title)}</h3><button class="btn icon xs ghost" data-m="x" aria-label="关闭">${ICON.x}</button></div>
      <div class="mb">${body}</div>
      <div class="mf">${cancel ? `<button class="btn sm" data-m="no">${esc(cancel)}</button>` : ''}${ok ? `<button class="btn sm dark" data-m="ok">${esc(ok)}</button>` : ''}</div></div></div>`;
    let getVal = null;
    const done = v => { root.innerHTML = ''; document.removeEventListener('keydown', key, true); resolve(v); };
    const key = e => { if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); done(false); } };  // 只关批注弹窗，不关下面的界面弹窗
    document.addEventListener('keydown', key, true);
    root.firstElementChild.addEventListener('click', e => {
      if (e.target === root.firstElementChild) return done(false);
      const b = e.target.closest('[data-m]'); if (!b) return;
      if (b.dataset.m === 'ok') done(getVal ? getVal() : true); else done(false);
    });
    if (onMount) onMount($('.modal', root), fn => { getVal = fn; });
  });
}
// 批注的位置：页面地址，界面弹窗开着时再加上弹窗标题（这样弹窗里的批注只在同一个弹窗里显示编号）
const unModalTitle = () => {  // 记住弹窗打开时的标题：标题被「改文字」预览换掉后也认得出是同一个弹窗
  const h = $('#modal .modal .mh h3'); if (!h) return '';
  if (!h.dataset.unT) h.dataset.unT = h.textContent.trim();
  return h.dataset.unT;
};
const unCtx = () => (location.hash || '#/') + (unModalTitle() ? ` · 弹窗「${unModalTitle()}」` : '');
async function unLoad() { try { UN.notes = (await api('GET', '/api/ui-notes')).notes || []; } catch (e) { UN.notes = []; fail(e); } unPins(); unBtn(); }
function unBtn() {
  if (!S.state?.appearance?.ui_notes && !UN.on) { $('#un-btn')?.remove(); return; }  // 设置 → 外观里打开才显示
  let b = $('#un-btn');
  if (!b) { b = document.createElement('div'); b.id = 'un-btn'; document.body.appendChild(b); }
  const open = UN.notes.filter(n => n.status !== 'done').length;
  b.innerHTML = `<button type="button" class="btn sm${UN.on ? ' un-on' : ''}" data-un="toggle" title="批注模式：点界面上任意东西，写改文字 / 改层级 / 挪位置">${UN.on ? '退出批注' : '批注'}</button>${open ? `<button type="button" class="btn sm" data-un="list">${open} 条未处理</button>` : ''}`
    + (UN.picking ? '<span class="un-tip">点一下要挪到的参照物（按 Esc 取消）</span>' : UN.on ? '<span class="un-tip">点任意按钮、文字、区块；Alt + 点 = 选它外面一层</span>' : '');
}
function unPins() {
  $$('.un-pin').forEach(p => p.remove());
  if (!UN.on) return;
  const page = unCtx();
  UN.notes.filter(n => n.page === page && n.status !== 'done' && n.rect).forEach(n => {
    const p = document.createElement('div'); p.className = 'un-pin' + (n.rect.fixed ? ' fixed' : ''); p.textContent = n.no; p.title = n.comment;
    const y = n.rect.y;  // 弹窗里的按窗口坐标（fixed），页面上的按整页坐标
    p.style.left = (n.rect.x + n.rect.w - 6) + 'px'; p.style.top = (y - 8) + 'px';
    p.dataset.un = 'pin'; p.dataset.id = n.id; document.body.appendChild(p);
  });
}
const unSkip = t => t.closest('#un-btn,#un-dlg,.un-pin');
document.addEventListener('mouseover', e => {
  if (!UN.on || unSkip(e.target)) return;
  $$('.un-hover').forEach(x => x.classList.remove('un-hover'));
  (e.altKey ? e.target.parentElement || e.target : e.target).classList.add('un-hover');
}, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape' && UN.picking) { const p = UN.picking; UN.picking = null; unBtn(); p(null); } }, true);
document.addEventListener('click', async e => {
  const u = e.target.closest('[data-un]');
  if (u) {
    e.preventDefault(); e.stopPropagation();
    if (u.dataset.un === 'toggle') {
      UN.on = !UN.on; UN.picking = null; document.body.classList.toggle('un-mode', UN.on);
      $$('.un-hover').forEach(x => x.classList.remove('un-hover')); unBtn(); unPins();
    } else if (u.dataset.un === 'list' || u.dataset.un === 'pin') unList(u.dataset.id);
    return;
  }
  if (!UN.on || unSkip(e.target)) return;
  e.preventDefault(); e.stopPropagation();
  const el = e.altKey ? e.target.parentElement || e.target : e.target;
  if (UN.picking) { const p = UN.picking; UN.picking = null; unBtn(); p(el); return; }
  unEdit(el);
}, true);

// 写一条批注；draft 在「去点参照物」时保住已经填的内容
async function unEdit(el, draft) {
  const d = draft || { el, kind: 'text', from: unTextOf(el), to: unTextOf(el), layer: '', rel: 'after', ref: null, note: '' };
  $$('.un-sel').forEach(x => x.classList.remove('un-sel'));
  d.el.classList.add('un-sel');
  if (d.ref) d.ref.el.classList.add('un-sel', 'un-ref');
  const body = `<div class="un-form">
    <div class="xsmall faint">选中：${esc(unShort(d.from))} <button type="button" class="linkbtn" data-unf="parent">选外面一层</button></div>
    <div class="seg" role="group" aria-label="改什么">${UN_KINDS.map(([k, t]) => `<button type="button" data-unk="${k}" class="${d.kind === k ? 'on' : ''}">${t}</button>`).join('')}</div>
    <div data-unp="text"${d.kind === 'text' ? '' : ' hidden'}><label class="small un-l">改成<textarea class="inp un-ta" id="un-to" rows="3">${esc(d.to)}</textarea></label>
      <div class="xsmall faint">保存后界面上会先换成新文字给你看，刷新就恢复。</div></div>
    <div data-unp="layer"${d.kind === 'layer' ? '' : ' hidden'}><div class="un-opts">${UN_LAYER.map(([k, t]) => `<label class="rad"><input type="radio" name="un-layer" value="${k}" ${d.layer === k ? 'checked' : ''}>${t}</label>`).join('')}</div></div>
    <div data-unp="move"${d.kind === 'move' ? '' : ' hidden'}><div class="un-move">挪到 <button type="button" class="btn sm" data-unf="ref">${d.ref ? esc(unShort(d.ref.text)) : '点这里，再去页面上点参照物'}</button> 的
      <select class="sel" id="un-rel" style="width:auto">${UN_REL.map(([k, t]) => `<option value="${k}" ${d.rel === k ? 'selected' : ''}>${t}</option>`).join('')}</select></div></div>
    <label class="small un-l">说明${d.kind === 'other' ? '' : '（可不写）'}<textarea class="inp un-ta" id="un-note" rows="2" placeholder="为什么这么改、别的要求">${esc(d.note)}</textarea></label>
  </div>`;
  let jump = null;  // 'parent' | 'ref'
  const read = () => {
    d.to = $('#un-to')?.value ?? d.to; d.note = $('#un-note')?.value.trim() ?? d.note;
    d.layer = document.querySelector('input[name="un-layer"]:checked')?.value || d.layer; d.rel = $('#un-rel')?.value || d.rel;
  };
  const ans = await unDialog({ title: '写批注', ok: '保存', body, onMount: (m, setOk) => {
    setOk(() => { read(); return d; });
    m.addEventListener('click', ev => {
      const k = ev.target.closest('[data-unk]');
      if (k) { read(); d.kind = k.dataset.unk; $$('[data-unk]', m).forEach(b => b.classList.toggle('on', b === k)); $$('[data-unp]', m).forEach(p => { p.hidden = p.dataset.unp !== d.kind; }); return; }
      const f = ev.target.closest('[data-unf]');
      if (f) { read(); jump = f.dataset.unf; m.querySelector('[data-m="no"]')?.click(); }
    });
  } });
  $$('.un-sel').forEach(x => x.classList.remove('un-sel', 'un-ref'));
  if (jump === 'parent') { const p = d.el.parentElement; if (p && p !== document.body) { d.el = p; d.from = unTextOf(p); if (d.kind !== 'text' || !d.to) d.to = d.from; } return unEdit(d.el, d); }
  if (jump === 'ref') {
    UN.picking = ref => { if (ref) d.ref = { el: ref, text: unTextOf(ref), target: unDesc(ref) }; unEdit(d.el, d); };
    unBtn(); return;
  }
  if (!ans || ans === true) return;
  unSave(d);
}
async function unSave(d) {
  const lab = Object.fromEntries(UN_KINDS);
  let change, line;
  if (d.kind === 'text') {
    if (d.to.trim() === d.from) return toast('文字没改，没有保存', true);
    change = { from: d.from, to: d.to.trim() }; line = `${unShort(d.from)} → 「${d.to.trim()}」`;
  } else if (d.kind === 'layer') {
    if (!d.layer) return toast('选一下要怎么改层级', true);
    change = { layer: d.layer }; line = `${unShort(d.from)}：${Object.fromEntries(UN_LAYER)[d.layer]}`;
  } else if (d.kind === 'move') {
    if (!d.ref && d.rel !== 'page') return toast('先点一下要挪到哪个东西旁边', true);
    change = { rel: d.rel, ref: d.ref ? { text: d.ref.text, target: d.ref.target } : null };
    line = `${unShort(d.from)} 挪到 ${d.ref ? unShort(d.ref.text) : ''}的${Object.fromEntries(UN_REL)[d.rel]}`;
  } else {
    if (!d.note) return toast('写一下想怎么改', true);
    change = {}; line = unShort(d.from);
  }
  const comment = `【${lab[d.kind]}】${line}${d.note ? ` · ${d.note}` : ''}`;
  const r = d.el.getBoundingClientRect();
  const inModal = !!d.el.closest('#modal');
  try {
    await api('POST', '/api/ui-notes', { page: unCtx(), target: unDesc(d.el), text: d.from, comment, kind: d.kind, change: { ...change, note: d.note },
      rect: inModal ? { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height), fixed: true }
        : { x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY), w: Math.round(r.width), h: Math.round(r.height), doc: true },
      viewport: [innerWidth, innerHeight], theme: S.themeApplied || '' });
    if (d.kind === 'text' && d.el.children.length === 0) d.el.textContent = d.to.trim();  // 先换给你看
    toast('批注已保存'); unLoad();
  } catch (err) { fail(err); }
}
async function unList(focusId) {
  await unLoad();
  const page = unCtx();
  const rows = UN.notes.slice().reverse().map(n => `<div class="un-row${n.status === 'done' ? ' done' : ''}${n.id === focusId ? ' focus' : ''}"><b>#${n.no}</b>
    <div><div>${esc(n.comment)}</div><div class="xsmall faint">${n.page === page ? '本页' : esc(n.page)} · ${esc(n.time)}${n.status === 'done' ? ' · 已处理' : ''}</div></div>
    <span class="un-acts"><button class="linkbtn" data-unx="${n.status === 'done' ? 'open' : 'done'}" data-id="${esc(n.id)}">${n.status === 'done' ? '重新打开' : '标为已处理'}</button><button class="linkbtn" data-unx="del" data-id="${esc(n.id)}">删除</button></span></div>`).join('');
  const open = UN.notes.filter(n => n.status !== 'done');
  const ans = await unDialog({ title: '界面批注', wide: true, ok: open.length ? '复制未处理的' : '', cancel: '关闭',
    body: `<div class="xsmall faint">都存在管家的 data/ui_notes.json，开发直接读这个文件；也可以复制下来贴给开发。</div><div class="un-list">${rows || '<div class="small faint">还没有批注</div>'}</div>`,
    onMount: m => m.addEventListener('click', async e => {
      const b = e.target.closest('[data-unx]'); if (!b) return;
      if (b.dataset.unx === 'del') await api('POST', `/api/ui-notes/${b.dataset.id}/delete`);
      else await api('POST', `/api/ui-notes/${b.dataset.id}`, { status: b.dataset.unx });
      m.querySelector('[data-m="no"]')?.click(); unList();
    }) });
  if (ans === true) {
    const txt = open.map(n => `#${n.no} ${n.page} ${n.comment}\n   位置：${n.target}`).join('\n');
    try { await navigator.clipboard.writeText(txt); toast(`已复制 ${open.length} 条`); } catch (x) { toast('复制不了，直接读 data/ui_notes.json 也行', true); }
  }
}
window.addEventListener('hashchange', () => setTimeout(unPins, 400));
new MutationObserver(() => { unModalTitle(); if (UN.on) setTimeout(unPins, 50); }).observe(document.getElementById('modal'), { childList: true });  // 界面弹窗开关时换一套编号
window.addEventListener('resize', () => unPins());
setTimeout(() => { if (S.state?.appearance?.ui_notes) unLoad(); }, 1200);
