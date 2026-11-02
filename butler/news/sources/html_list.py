"""官网新闻列表页：找出新闻链接，再进文章页读标题、题图和正文里的时间。"""
from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.parse
from pathlib import Path

from ..common import (_A, _IMG, _OG_IMG, pick_img, _OG_TITLE, _TITLE, _article_body, _clean_title, _fmt, _get, _list_summary,
                      _text, extract_activities, extract_period, strip_html)

_SCRIPT = re.compile(r'(?is)<script[^>]+src=["\']([^"\']+\.js[^"\']*)')

def read(src: dict, data_dir: Path, miss) -> list[dict]:
    """官网新闻列表：先找新闻链接，再逐篇读（最多 12 篇）。
    probe=True：把页面引用的脚本也存进 raw/（网站是前端渲染时，从脚本里找它的数据接口用）。"""
    page, base = "", ""
    errs = []
    for u in src.get("urls", []):
        try:
            page = _text(_get(u, data_dir, src["id"]))
            base = u
            break
        except Exception as e:
            errs.append(f"{u}：{e}")
    if not page:
        raise RuntimeError("；".join(errs) or "没有可用的网址")
    for e in errs:  # 前面的网址读不到、用了后面的：照样记下
        miss.add("列表页换了备用网址", e, 0)
    bm = re.search(r'(?is)<base[^>]+href=["\']([^"\']+)', page)
    if bm:  # 页面声明了 <base href>：相对链接按它算
        base = urllib.parse.urljoin(base, bm.group(1))
    if src.get("probe"):
        apps = [js for js in _SCRIPT.findall(page) if "xassets" not in js and "/lib/" not in js
                and not re.search(r"jquery|react|polyfill|shim|promise|sdk|tracker|footer|navibar", js, re.I)]
        apps += [h for h in re.findall(r'(?is)<link[^>]+href=["\']([^"\']+\.js)["\'][^>]*rel=["\']prefetch', page)
                 if re.search(r"latest|news|announce|activit", h)]
        for k, js in enumerate(apps[:8]):
            try:
                _get(urllib.parse.urljoin(base, js), data_dir, f"{src['id']}_js{k}", timeout=30, raw_cap=6_000_000)
            except Exception as e:
                miss.add("排查用的页面脚本没存下", e, 0)
    pat = re.compile(src.get("match", r"/news/"))
    links, seen = [], set()
    for href, inner in _A.findall(page):
        full = urllib.parse.urljoin(base, html.unescape(href))
        if not full.startswith("http") or full in seen or not pat.search(full):
            continue
        if full.rstrip("/") in (u.rstrip("/") for u in src.get("urls", [])):
            continue
        seen.add(full)
        links.append((full, strip_html(inner)))
    # 前端渲染的页面：链接不在 <a> 里，而在页面内嵌的数据（JSON）里
    for m in re.finditer(r'["\'](/[^"\'\s<>]*?' + src.get("match", r"/news/").lstrip("/") + r'[^"\'\s<>]*)["\']', page):
        full = urllib.parse.urljoin(base, m.group(1))
        if full not in seen:
            seen.add(full)
            links.append((full, ""))
    kws = src.get("keywords")
    out, t0 = [], time.time()
    for full, text in links[:40]:
        if len(out) >= 24 or len({o["url"] for o in out}) >= 12 or time.time() - t0 > 120:
            break
        if kws and text and not any(k in text for k in kws):
            continue
        try:
            art = _text(_get(full, data_dir, f"{src['id']}_art{len(out)}" if len(out) < 2 else "", timeout=15))  # 前两篇存下来排查
        except Exception as e:
            miss.add("文章页读不到", e)
            continue
        t = _OG_TITLE.search(art) or _TITLE.search(art)
        title = _clean_title(t.group(1)) if t else text
        if kws and not any(k in title for k in kws):
            continue
        body = _article_body(strip_html(art))
        img = pick_img(art)  # 11-02：不再拿网站顶栏的图（以前时绘每条都是 nie.topBar 那张 3k 小图）
        banner = urllib.parse.urljoin(full, html.unescape(img)) if img else ""
        uid = hashlib.sha1(full.encode()).hexdigest()[:12]
        acts = extract_activities(body) if src.get("multi") else []
        if acts:  # 一篇公告里有好几个活动：每个活动一条
            for k, (name, st, en, sub, seg) in enumerate(acts):
                out.append({"id": f"{src['id']}:{uid}:{k}", "game": src["game"], "source": src["id"], "kind": "活动",
                            "title": name, "start": _fmt(st), "end": _fmt(en), "banner_url": banner if k == 0 else "",
                            "url": full, "content": "", "subtitle": sub, "source_title": title, "text": seg})
            continue
        start, end = extract_period(body)
        first = next((x for x in body.split("\n") if len(x.strip()) >= 8 and x.strip() not in title), "")
        out.append({"id": f"{src['id']}:{uid}", "game": src["game"],
                    "source": src["id"], "kind": src.get("kind", "活动" if start else "公告"), "title": title or text,
                    "start": _fmt(start), "end": _fmt(end), "banner_url": banner, "url": full, "content": "",
                    "subtitle": _list_summary(text, title) or first.strip()[:90], "source_title": title,
                    "text": body[:900]})
    return out
