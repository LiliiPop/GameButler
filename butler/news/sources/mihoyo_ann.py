"""米哈游游戏内公告（getAnnList + getAnnContent）：有题图、开始和结束时间。"""
from __future__ import annotations

import json
from pathlib import Path

from ..common import _ACT, _fmt, _get, _parse_dt, _text, strip_html

_ANN = "https://{host}/common/{biz}/announcement/api/{api}?game={game}&game_biz={biz}&lang=zh-cn&bundle_id={biz}" \
       "&platform=pc&region={region}&level=60&uid=100000000&channel_id=1&sdk_presentation_style=fullscreen" \
       "&sdk_screen_transparent=true&auth_appid=announcement&authkey_ver=1&sign_type=2"


def read(src: dict, data_dir: Path, miss) -> list[dict]:
    fmt = dict(host=src["host"], biz=src["biz"], game=src["gamecode"], region=src["region"])
    lst = json.loads(_text(_get(_ANN.format(api="getAnnList", **fmt), data_dir, src["id"])))
    if lst.get("retcode") != 0:
        raise RuntimeError(f"getAnnList 返回 {lst.get('retcode')}：{lst.get('message')}")
    contents = {}
    try:
        con = json.loads(_text(_get(_ANN.format(api="getAnnContent", **fmt), data_dir, src["id"] + "_content")))
        for c in (con.get("data") or {}).get("list", []):
            contents[c.get("ann_id")] = c
    except Exception as e:  # 列表有了、正文没有：条目照样有标题和起止时间，正文和题图缺
        n = sum(len(g.get("list", [])) for g in (lst.get("data") or {}).get("list", []))
        miss.add("公告正文读不到", e, n)
    out = []
    for grp in (lst.get("data") or {}).get("list", []):
        glabel = str(grp.get("type_label", ""))
        for a in grp.get("list", []):
            title = strip_html(a.get("title") or a.get("subtitle") or "")
            c = contents.get(a.get("ann_id"), {})
            banner = a.get("banner") or c.get("banner") or ""
            kind = "活动" if ("活动" in glabel or "活动" in str(a.get("tag_label", "")) or
                            (_ACT.search(title) and "更新说明" not in title and "维护" not in title)) else "公告"
            sub = strip_html(a.get("subtitle") or "")
            out.append({"id": f"{src['id']}:{a.get('ann_id')}", "game": src["game"], "source": src["id"], "kind": kind,
                        "title": title, "start": _fmt(_parse_dt(a.get("start_time"))),
                        "end": _fmt(_parse_dt(a.get("end_time"))), "banner_url": banner,
                        "url": "", "content": c.get("content", ""), "subtitle": sub if sub != title else "",
                        "source_title": title, "text": strip_html(c.get("content", ""))[:900]})
    return out
