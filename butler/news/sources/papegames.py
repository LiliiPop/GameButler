"""叠纸官网（Next.js）：新闻页 /news/<编号>。"""
from __future__ import annotations

import json
import re
import time
import urllib.error
from datetime import datetime
from pathlib import Path

from ...timeutil import BJ
from ..common import _IMG, _clean_title, _fmt, _get, _norm, _text, extract_activities, extract_period, strip_html

_NEXT = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def _next_data(page: str) -> dict:
    m = _NEXT.search(page)
    return json.loads(m.group(1)).get("props", {}).get("pageProps", {}) if m else {}


def _walk_strings(o, out: list):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str):
                out.append((k, v))
            else:
                _walk_strings(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk_strings(v, out)


def read(src: dict, data_dir: Path, miss) -> list[dict]:
    """叠纸官网（Next.js）：新闻页 /news/<编号>，页面内嵌数据里有 title、publish_time、content_html。
    首页轮播只放版本大新闻，所以从轮播里最大的编号往上探到最新一篇（连续 4 个空号为止），再往前读最近 12 篇，
    按「活动时间」拆成一条条活动。"""
    base = src["base"].rstrip("/")
    home = _next_data(_text(_get(base + "/home", data_dir, src["id"])))
    banners = {}
    for b in (home.get("pageData") or {}).get("newsbanner", []) or []:
        try:
            banners[int(b.get("info"))] = b
        except (TypeError, ValueError):
            miss.add("首页轮播里的新闻编号看不懂", repr(b.get("info")))
    if not banners:
        raise RuntimeError("首页数据里没有新闻轮播（网站可能改版了）")
    t0 = time.time()
    pages: dict[int, dict] = {}

    def page_of(nid: int) -> dict | None:
        if nid in pages:
            return pages[nid]
        try:
            raw = _text(_get(f"{base}/news/{nid}", data_dir, timeout=15))
        except urllib.error.HTTPError as e:
            if e.code != 404:  # 404 = 这个编号还没有文章（往上探最新一篇时正常会碰到）
                miss.add(f"新闻页 {nid} 读不到", e)
            pages[nid] = None
            return None
        except Exception as e:
            miss.add(f"新闻页 {nid} 读不到", e)
            pages[nid] = None
            return None
        dd = (_next_data(raw) or {}).get("data") or {}
        pages[nid] = {"raw": raw, **dd} if dd.get("content_html") or dd.get("title") else None
        return pages[nid]

    top, gap, nid = max(banners), 0, max(banners)
    while gap < 4 and time.time() - t0 < 90:  # 往上找最新一篇
        nid += 1
        if page_of(nid):
            top, gap = nid, 0
        else:
            gap += 1
    out = []
    for nid in range(top, max(0, top - 16), -1):
        if time.time() - t0 > 150 or len({o["url"] for o in out}) >= 12:
            break
        pg = page_of(nid)
        if not pg:
            continue
        url = f"{base}/news/{nid}"
        title = _clean_title(pg.get("title") or "")
        body = strip_html(pg.get("content_html") or "")
        pub = None
        try:
            pub = datetime.fromtimestamp(int(pg.get("publish_time")) / 1000, BJ)
        except (TypeError, ValueError):
            miss.add("发布时间看不懂", repr(pg.get("publish_time")))
        m = _IMG.search(pg.get("content_html") or "")
        img = (banners.get(nid) or {}).get("address") or (m.group(1) if m else "")
        acts = extract_activities(body)
        if acts:
            for k, (name, st, en, sub, seg) in enumerate(acts):
                out.append({"id": f"{src['id']}:{nid}:{k}", "game": src["game"], "source": src["id"], "kind": "活动",
                            "title": name, "start": _fmt(st), "end": _fmt(en), "banner_url": img if k == 0 else "",
                            "url": url, "content": "", "subtitle": sub, "source_title": title, "text": seg})
            # 「岁愿萤星｜沈星回生日主题活动即将开启！」：文章标题本身是一个活动（主题活动），卡池是另一个
            m2 = re.match(r"^(.{2,14}?)\s*[｜|]\s*(.+?)(?:即将|现已|正式)?(?:开启|上线)?[!！]?$", title)
            if m2 and _norm(m2.group(1)) not in {_norm(a[0]) for a in acts}:
                out.append({"id": f"{src['id']}:{nid}:main", "game": src["game"], "source": src["id"], "kind": "活动",
                            "title": m2.group(1).strip("「」"), "start": _fmt(min(a[1] for a in acts)),
                            "end": _fmt(max(a[2] for a in acts)), "banner_url": img, "url": url, "content": "",
                            "subtitle": m2.group(2), "source_title": title, "text": body[:900]})
            continue
        st, en = extract_period(title + "\n" + body, pub)
        first = next((x for x in body.split("\n") if len(x.strip()) >= 8 and x.strip() not in title), "")
        out.append({"id": f"{src['id']}:{nid}", "game": src["game"], "source": src["id"],
                    "kind": "活动" if (st and en) else "公告", "title": title,
                    "start": _fmt(st or pub), "end": _fmt(en) if st else "", "banner_url": img, "url": url, "content": "",
                    "subtitle": first.strip()[:90], "source_title": title, "text": body[:900]})
    # 排查用：读过的文章正文各存一份（纯文字）
    for nid, pg in pages.items():
        if pg:
            p = data_dir / "raw" / f"{src['id']}_news_{nid}.txt"
            p.write_text(f"URL: {base}/news/{nid}\n\n" + strip_html(pg.get("content_html") or "")[:200_000], encoding="utf-8")
    return out
