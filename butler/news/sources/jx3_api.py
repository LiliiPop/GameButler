"""剑网3 官网新闻接口。"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

from ...timeutil import BJ
from ..common import _ACT, _IMG, _OG_IMG, _fmt, _get, _parse_dt, _text, extract_period, strip_html

_JX3_LOOK = re.compile(r"外观|外装|套装|校服|上新|礼盒|盒子|商城|新品|时装|发型|坐骑|挂件|披风|成衣|发售")
_JX3_SKIP = re.compile(r"处罚|维护公告|版本更新公告|武学调整|安全提醒|沉寂|代开|发奖|赛季结算")


def read(src: dict, data_dir: Path, miss) -> list[dict]:
    """剑网3 官网新闻（前端渲染，数据接口见官网 page-latest 脚本：api.php?op=search_api&action=get_customer_article_list）。
    外观上新类的标为「外观」，进文章页取题图和时间。"""
    # 2458 = 新闻、2461 = 活动（官网「最新」页用的就是这两个栏目）
    url = "https://jx3.xoyo.com/api.php?op=search_api&action=get_customer_article_mix_list&game=jx3&num=30&page=1" \
          "&mixcatid=2458,2461"
    txt = _text(_get(url, data_dir, src["id"], referer="https://jx3.xoyo.com/index/")).strip()
    m = re.match(r"^[\w$.]+\((.*)\)\s*;?\s*$", txt, re.S)  # JSONP
    d = json.loads(m.group(1) if m else txt)
    lst = (d.get("data") or {}).get("list") if isinstance(d.get("data"), dict) else d.get("list")
    if isinstance(lst, dict):  # mix_list 返回的是 {序号: 文章}
        lst = list(lst.values())
    if not isinstance(lst, list):
        raise RuntimeError("接口返回里没有文章列表（可能改版了）")
    out, t0 = [], time.time()
    for a in lst:
        title = strip_html(str(a.get("title", "")))
        if _JX3_SKIP.search(title):  # 维护、处罚之类的公告不进活动日历
            continue
        link = str(a.get("url") or a.get("link") or "")
        if not link.startswith("http"):  # 只给了编号：官网文章页是 show-<栏目>-<编号>-1.html
            link = f"https://jx3.xoyo.com/show-{a.get('catid') or 2458}-{a.get('id')}-1.html"
        thumb = next((str(a[k]) for k in ("thumb", "image", "cover", "pic", "img") if a.get(k)), "")
        look = bool(_JX3_LOOK.search(title))
        kind = "外观" if look else ("活动" if _ACT.search(title) else "公告")
        st = en = None
        if (look or kind == "活动") and link.startswith("http") and time.time() - t0 < 120 and len(out) < 40:
            try:
                art = _text(_get(link, data_dir, timeout=15))
                st, en = extract_period(strip_html(art))
                if not thumb:
                    mm = _OG_IMG.search(art) or _IMG.search(art)
                    thumb = urllib.parse.urljoin(link, mm.group(1)) if mm else ""
            except Exception as e:
                miss.add("文章页读不到（没有时间和题图）", e)
        if not st and a.get("inputtime"):
            v = str(a["inputtime"])
            st = datetime.fromtimestamp(int(v), BJ) if v.isdigit() else _parse_dt(v)  # 接口给时间戳或日期文字
            if not st:
                miss.add("发布时间看不懂", v)
            en = None if kind == "公告" else en
        out.append({"id": f"{src['id']}:{a.get('id') or hashlib.sha1(link.encode()).hexdigest()[:12]}", "game": src["game"],
                    "source": src["id"], "kind": kind, "title": title, "start": _fmt(st), "end": _fmt(en),
                    "banner_url": urllib.parse.urljoin(link or "https://jx3.xoyo.com/", thumb) if thumb else "",
                    "url": link, "content": ""})
    return out
