"""TapTap 官方号帖子（11-02，先给恋与深空用）。不用登录：
  1. 读游戏论坛的「官方」列表页（服务器直接出的网页），找出帖子链接 /moment/<id>；
  2. 逐帖读（最多 count 帖、只看 days 天内）：标题（og:title）、发布时间、正文里的活动时间段、主图（og:image，原图）。

{"type": "taptap", "app": "201633", "count": 12, "days": 45}
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from ..common import BJ, _fmt, _get, _now, _parse_dt, _text, extract_activities, extract_period, guess_name, strip_html

_META = lambda p, k: (re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(k) + r'["\'][^>]+content=["\']([^"\']*)', p)
                      or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']' + re.escape(k) + r'["\']', p))


def _meta(page: str, *keys: str) -> str:
    for k in keys:
        m = _META(page, k)
        if m and m.group(1).strip():
            return html.unescape(m.group(1)).strip()
    return ""


def _when(page: str) -> datetime | None:
    s = _meta(page, "article:published_time", "og:release_date", "datePublished")
    if not s:
        m = re.search(r'"(?:datePublished|published_time|created_time)"\s*:\s*"?([0-9T:\-+.Z ]{10,30})', page)
        s = m.group(1) if m else ""
    if not s:
        m = re.search(r'"(?:created_time|publish_time)"\s*:\s*(\d{10})', page)
        if m:
            return datetime.fromtimestamp(int(m.group(1)), BJ)
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(BJ)
    except ValueError:
        return _parse_dt(s[:16].replace("T", " "))


def _same_day(u: str, main: str) -> bool:
    """帖子页上还有「相关帖子」的缩略图：只要和主图同一天上传的（文件名里的 _20261026161417）。"""
    d = lambda x: (re.search(r"_(\d{8})\d{6}\.", x) or [None, ""])[1]
    return bool(d(main)) and d(u) == d(main)


def read(src: dict, data_dir: Path, miss) -> list[dict]:
    app = str(src["app"])
    lst = f"https://www.taptap.cn/app/{app}/topic?os=android&type=official"
    page = _text(_get(lst, data_dir, f"{src['id']}_list", timeout=20, raw_cap=800_000))
    ids = list(dict.fromkeys(re.findall(r"/moment/(\d{12,22})", page)))
    if not ids:
        raise RuntimeError("官方帖子列表里没找到帖子链接（TapTap 页面格式可能变了，或要求验证）")
    now, out = _now(), []
    for k, mid in enumerate(ids[:int(src.get("count", 12))]):
        url = f"https://www.taptap.cn/moment/{mid}"
        try:
            p = _text(_get(url, data_dir, f"{src['id']}_m{k}" if k < 2 else "", referer=lst, timeout=20, raw_cap=600_000))
        except Exception as e:
            miss.add("帖子读不到", e)
            continue
        when = _when(p)
        if when and now - when > timedelta(days=int(src.get("days", 45))):
            continue
        title = re.sub(r"\s*-\s*[^-]*(讨论|论坛|TapTap).*$", "", _meta(p, "og:title") or "").strip()
        desc = _meta(p, "og:description", "description")
        body = strip_html(re.sub(r"(?is)<head.*?</head>", "", p))
        i = body.find(title[:12]) if title else -1
        seg = body[i:i + 3000] if i >= 0 else ""
        # 11-03：帖子正文后面是「猜你想搜」「前往论坛」和别人的帖子、评论——不能算进正文（恋与深空「庆生日历」帖子本身没写时间，
        # 却从后面别人的帖子里认出了 11/21~11/30）。截到第一个这样的标记为止
        cut = [k for k in (seg.find(mk) for mk in ("猜你想搜", "前往论坛", "去论坛查看", "热门评论", "全部评论")) if k > 0]
        seg = seg[:min(cut)] if cut else seg
        text = (desc + "\n" + seg).strip()
        img = _meta(p, "og:image", "twitter:image")
        img = img if "tapimg.com" in img else ""
        more = list(dict.fromkeys(re.findall(r'https://img\d*-tc\.tapimg\.com/moment/[^"\'\s)<>\\]+', p)))  # 帖子里的其他图（11-02）
        base = {"game": src["game"], "source": src["id"], "url": url, "content": "",
                "banner_urls": [img] + [u for u in more if u != img and _same_day(u, img)] if img else [],
                "img_rank": float(src.get("img_rank", 3.3)), "source_title": f"TapTap 官方号 · {title[:40]}"}
        acts = extract_activities(text)
        if len(acts) > 1:
            for j, (name, st, en, sub, seg) in enumerate(acts):
                out.append({**base, "id": f"{src['id']}:{mid}:{j}", "kind": "活动", "title": name, "start": _fmt(st),
                            "end": _fmt(en), "banner_url": img if j == 0 else "", "subtitle": sub, "text": seg})
            continue
        st, en = extract_period(text, when or now)
        name = guess_name(title) or guess_name(text)
        if not name:
            continue
        if st:
            out.append({**base, "id": f"{src['id']}:{mid}", "kind": "活动", "title": name, "start": _fmt(st), "end": _fmt(en),
                        "banner_url": img, "subtitle": title if title != name else desc[:90], "text": text[:900]})
        elif img:  # PV、宣传帖：图只当题图，按名字配
            out.append({**base, "id": f"{src['id']}:{mid}", "kind": "活动", "title": name, "start": "", "end": "",
                        "banner_url": img, "subtitle": "", "text": "", "img_only": True})
        time.sleep(0.4)
    return out
