"""B 站 wiki（wiki.biligame.com，MediaWiki）上玩家整理的官方消息（11-02）。不用登录，直接读页面。

两种读法（来源配置的 mode）：
  fb_index   代号鸢「FB搬运」：索引页列着「FB-2026年11月2日」这样的子页面，每页是当天官方 Facebook 帖子的译文和配图。
             读最近 days 天、最多 pages 页；正文里认活动名和时间段，配图（原图）当题图。
             {"type": "wiki", "mode": "fb_index", "site": "yuan", "page": "FB搬运", "prefix": "FB-"}
  act_table  恋与深空「活动」：一张表，每行 活动（图、名字）| 类型 | 开始 | 结束 | 展示。
             {"type": "wiki", "mode": "act_table", "site": "lysk", "page": "活动"}
"""
from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

from ..common import BJ, _fmt, _get, _now, _text, extract_activities, extract_period, guess_name, strip_html

BASE = "https://wiki.biligame.com/"


def _page(site: str, title: str, data_dir: Path, raw: str = "") -> str:
    url = BASE + site + "/" + urllib.parse.quote(title)
    return _text(_get(url, data_dir, raw, referer=BASE + site + "/", timeout=20, raw_cap=600_000))


def _content(page: str) -> str:
    """正文区域（mw-parser-output），去掉页面四周的导航。"""
    i = page.find('class="mw-parser-output"')
    if i < 0:
        i = page.find('id="mw-content-text"')
    if i < 0:
        return page
    j = min([k for k in (page.find('class="printfooter"', i), page.find("NewPP limit report", i),
                         page.find('id="catlinks"', i)) if k > 0] or [len(page)])
    i = page.find(">", i) + 1  # 从标签后面开始（11-02：之前把 class="mw-parser-output"> 也当成了正文）
    return re.sub(r"(?s)<!--.*?(-->|$)", "", page[i:j])


def _orig(src: str) -> str:
    """缩略图地址 → 原图：…/images/lysk/thumb/3/3f/abc.jpg/335px-名字.jpg → …/images/lysk/3/3f/abc.jpg"""
    src = html.unescape(src)
    if src.startswith("//"):
        src = "https:" + src
    return re.sub(r"/thumb/(.+?\.(?:jpe?g|png|webp|gif))/\d+px-[^/]*$", r"/\1", src, flags=re.I)


_IMG = re.compile(r'<img\b[^>]*>', re.I)


def _imgs(seg: str) -> list[tuple[str, int, int]]:
    """片段里的图：(原图地址, 原图宽, 原图高)；网站图标、表情不要。"""
    out = []
    for tag in _IMG.findall(seg):
        m = re.search(r'\bsrc="([^"]+)"', tag)
        if not m or "patchwiki.biligame.com/images/" not in m.group(1):
            continue
        w = re.search(r'data-file-width="(\d+)"', tag) or re.search(r'\bwidth="(\d+)"', tag)
        h = re.search(r'data-file-height="(\d+)"', tag) or re.search(r'\bheight="(\d+)"', tag)
        out.append((_orig(m.group(1)), int(w.group(1)) if w else 0, int(h.group(1)) if h else 0))
    return out


def _landscape(imgs) -> str:
    """优先横图；没有就用第一张够大的（竖版长图页面上只露最上面）。"""
    big = [x for x in imgs if not (x[1] and x[1] < 300)]
    land = [x for x in big if not (x[1] and x[2] and x[1] < x[2] * 1.2)]
    return (land + big)[0][0] if (land + big) else ""


# ---------------------------------------------------------------- 代号鸢 FB搬运
def _fb_index(src: dict, data_dir: Path, miss) -> list[dict]:
    site, prefix = src["site"], src.get("prefix", "FB-")
    idx = _content(_page(site, src["page"], data_dir, f"{src['id']}_index"))
    names = []
    for m in re.finditer(r'title="(' + re.escape(prefix) + r'(\d{4})年(\d{1,2})月(\d{1,2})日[^"]*)"', idx):
        t = html.unescape(m.group(1))
        if t not in [n for n, _ in names]:
            names.append((t, datetime(int(m.group(2)), int(m.group(3)), int(m.group(4)), tzinfo=BJ)))
    if not names:
        raise RuntimeError(f"索引页「{src['page']}」里没找到「{prefix}日期」的子页面（页面格式可能变了）")
    now = _now()
    want = sorted([x for x in names if now - x[1] <= timedelta(days=int(src.get("days", 21)))], key=lambda x: x[1],
                  reverse=True)[:int(src.get("pages", 14))]
    out = []
    for k, (title, day) in enumerate(want):
        try:
            seg = _content(_page(site, title, data_dir, f"{src['id']}_p{k}" if k < 2 else ""))
        except Exception as e:
            miss.add("子页面读不到", e)
            continue
        text = strip_html(seg)
        # 去掉页面上的小按钮（编 / 刷 / 历）、面包屑（FB搬运 FB-日期）和单独一行的「公告」
        text = "\n".join(x.strip() for x in text.split("\n") if x.strip()
                         and not re.fullmatch(r"(刷|历|编|阅读|编辑|公告|.*FB搬运.*FB-.*)", x.strip()))
        banner = _landscape(_imgs(seg))
        url = BASE + site + "/" + urllib.parse.quote(title)
        base = {"game": src["game"], "source": src["id"], "url": url, "content": "", "img_rank": float(src.get("img_rank", 3.2)),
                "source_title": f"B 站 wiki · {title}"}
        uid = re.sub(r"\D", "", title)[:12] + (re.search(r"补充(\d)", title).group(1) if "补充" in title else "")
        acts = extract_activities(text)
        if len(acts) > 1:  # 一帖写了好几个活动才拆（只有一个时，名字按整帖认更准）
            for j, (name, st, en, sub, seg_) in enumerate(acts):
                out.append({**base, "id": f"{src['id']}:{uid}:{j}", "kind": "活动", "title": name, "start": _fmt(st),
                            "end": _fmt(en), "banner_url": banner if j == 0 else "", "subtitle": sub, "text": seg_})
            continue
        st, en = extract_period(text, day)
        name = guess_name(text)
        if not name:
            continue
        sub = next((x for x in text.split("\n") if len(x) >= 8 and name not in x), "")[:90]
        if st:
            out.append({**base, "id": f"{src['id']}:{uid}", "kind": "活动", "title": name, "start": _fmt(st), "end": _fmt(en),
                        "banner_url": banner, "subtitle": sub, "text": text[:900]})
        elif banner:  # 没写时间的宣传帖：图只当题图，按名字配
            out.append({**base, "id": f"{src['id']}:{uid}", "kind": "活动", "title": name, "start": "", "end": "",
                        "banner_url": banner, "subtitle": "", "text": "", "img_only": True})
        time.sleep(0.5)
    return out


# ---------------------------------------------------------------- 恋与深空 活动表
_TD = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.S | re.I)
_DT = re.compile(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})日?\s*(?:(\d{1,2})\s*[:：]\s*(\d{2}))?\s*(更新后|维护后)?")


def _cell_dt(s: str):
    m = _DT.search(strip_html(s))
    if not m:
        return None, ""
    y, mo, d, h, mi, after = m.groups()
    return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), tzinfo=BJ), after or ""


def _act_table(src: dict, data_dir: Path, miss) -> list[dict]:
    site = src["site"]
    seg = _content(_page(site, src["page"], data_dir, f"{src['id']}_index"))
    now = _now()
    out, rows = [], 0
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", seg, re.S | re.I):
        tds = _TD.findall(tr)
        if len(tds) < 4:
            continue
        st, after = _cell_dt(tds[2])
        en, _ = _cell_dt(tds[3])
        if not st or not en:
            continue
        rows += 1
        if en < now - timedelta(days=45):
            continue
        lines = [re.sub(r"\s*✏️?\s*编辑\s*$|\s*✏️?\s*$", "", x.strip()) for x in strip_html(tds[0]).split("\n")]
        lines = [x for x in lines if x and x not in ("编辑", "[编辑]")]
        title = " ".join(lines)[:60]
        a = re.search(r'<a\b[^>]*title="([^"]+)"', tds[0])
        name = html.unescape(a.group(1)) if a else (lines[0] if lines else "")
        if not title:
            continue
        kind = strip_html(tds[1]).strip()
        banner = next((u for u, _, _ in _imgs(tds[0])), "")
        href = re.search(r'<a\b[^>]*href="(/[^"]+)"', tds[0])
        out.append({"id": f"{src['id']}:{hashlib.sha1((name + _fmt(st)).encode()).hexdigest()[:12]}", "game": src["game"], "source": src["id"],
                    "kind": "活动", "title": title, "start": _fmt(st), "end": _fmt(en), "banner_url": banner,
                    "url": BASE.rstrip("/") + html.unescape(href.group(1)) if href else BASE + site + "/" + urllib.parse.quote(src["page"]),
                    "content": "", "subtitle": kind and f"类型：{kind}", "source_title": f"B 站 wiki · {src['page']}",
                    "text": "", "img_rank": float(src.get("img_rank", 3.2)),
                    **({"start_note": after} if after else {})})
    if not rows:
        raise RuntimeError(f"「{src['page']}」页里没找到活动表（页面格式可能变了）")
    return out


def read(src: dict, data_dir: Path, miss) -> list[dict]:
    if src.get("mode") == "act_table":
        return _act_table(src, data_dir, miss)
    return _fb_index(src, data_dir, miss)
