"""米游社官方资讯：更新公告正文按「活动时间」拆成一条条活动。"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

from ..common import _ACT, _fmt, _get, _now, _text, extract_activities, extract_period, strip_html

# 米游社资讯列表：不同时期的接口地址不同，按顺序试，第一个返回 retcode 0 的为准
MYS_NEWS = [
    "https://bbs-api.miyoushe.com/painter/wapi/getNewsList?client_type=4&gids={gids}&last_id=&page_size=20&type={type}",
    "https://bbs-api-static.miyoushe.com/painter/wapi/getNewsList?client_type=4&gids={gids}&last_id=&page_size=20&type={type}",
    "https://bbs-api.mihoyo.com/post/wapi/getNewsList?gids={gids}&page_size=20&type={type}",
]
MYS_POST = [
    "https://bbs-api.miyoushe.com/post/wapi/getPostFull?gids={gids}&post_id={pid}&read=1",
    "https://bbs-api.mihoyo.com/post/wapi/getPostFull?gids={gids}&post_id={pid}&read=1",
]
# 米游社「活动」栏多是社区活动（盖楼、征集、签到），不是游戏里的活动，不收
_COMMUNITY = re.compile(r"社区活动|米游社|已开奖|盖楼|征集|签到|抽奖|话题|投稿|创作")


def _mys_json(urls: list[str], data_dir: Path, raw: str) -> dict:
    errs = []
    for u in urls:
        try:
            d = json.loads(_text(_get(u, data_dir, raw, referer="https://www.miyoushe.com/")))
            if d.get("retcode") == 0:
                return d
            errs.append(f"retcode {d.get('retcode')} {d.get('message')}")
        except Exception as e:
            errs.append(f"{type(e).__name__}: {e}")
    raise RuntimeError("米游社接口都没读到：" + "；".join(errs))


def read(src: dict, data_dir: Path, miss) -> list[dict]:
    """米游社官方资讯。游戏里的活动大多写在「游戏日常更新公告 / 版本更新公告」正文里：
    取最近 3 周的更新公告，读正文，按「活动时间」拆成一条条活动；资讯栏里标题像活动的也读正文取时间。"""
    out, got = [], set()
    cutoff = (_now() - timedelta(days=21)).timestamp()
    reads = 0
    for typ in (1, 3):
        d = _mys_json([t.format(gids=src["gids"], type=typ) for t in MYS_NEWS], data_dir, f"{src['id']}_{typ}")
        for it in (d.get("data") or {}).get("list", []):
            post = it.get("post") or {}
            pid, title = post.get("post_id"), strip_html(post.get("subject", ""))
            if not pid or pid in got or _COMMUNITY.search(title):
                continue
            got.add(pid)
            if int(post.get("created_at") or 0) < cutoff:
                continue
            is_update = "更新公告" in title or "版本更新" in title
            if not (is_update or _ACT.search(title)) or reads >= 8:
                continue
            reads += 1
            try:
                full = _mys_json([t.format(gids=src["gids"], pid=pid) for t in MYS_POST], data_dir, f"{src['id']}_post")
                content = ((full.get("data") or {}).get("post") or {}).get("post", {}).get("content", "")
            except Exception as e:
                miss.add("正文读不到（没拆出活动和时间）", e)
                content = ""
            body = strip_html(content)
            imgs = post.get("images") if isinstance(post.get("images"), list) else []
            cover = post.get("cover") or (imgs[0] if imgs else "")
            url = f"https://www.miyoushe.com/{src['slug']}/article/{pid}"
            acts = extract_activities(body)
            if acts:
                for k, (name, st, en, sub, seg) in enumerate(acts):
                    out.append({"id": f"{src['id']}:{pid}:{k}", "game": src["game"], "source": src["id"], "kind": "活动",
                                "title": name, "start": _fmt(st), "end": _fmt(en), "banner_url": cover if k == 0 else "",
                                "url": url, "content": "", "subtitle": sub, "source_title": title, "text": seg})
            elif not is_update:
                st, en = extract_period(title + "\n" + body)
                out.append({"id": f"{src['id']}:{pid}", "game": src["game"], "source": src["id"], "kind": "活动",
                            "title": title, "start": _fmt(st), "end": _fmt(en), "banner_url": cover, "url": url,
                            "content": ""})
    return out
