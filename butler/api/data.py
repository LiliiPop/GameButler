"""读数、抽卡记录、活动日历。"""
from __future__ import annotations

import re
from pathlib import Path

from .. import news
from ..launch import background_running, spawn_background
from . import route


@route("GET", r"/api/readings/(\w+)")
def _(api, m, q, b):
    from .. import gacha as GC, readings as RD
    api.game(m.group(1))
    return {**RD.summary(api.cfg, m.group(1)), "gacha": GC.stats(api.cfg, m.group(1))}


@route("GET", "/api/resources")
def _(api, m, q, b):  # 总览「资源一览」（11-02）
    from .. import readings as RD
    return {"games": RD.overview(api.cfg)}


@route("POST", r"/api/readings/(\w+)")
def _(api, m, q, b):
    from .. import readings as RD
    api.game(m.group(1))
    return RD.add_points(api.cfg, m.group(1), b.get("values") or {}, "manual")


@route("PUT", r"/api/readings/(\w+)/defs")
def _(api, m, q, b):
    from .. import readings as RD
    api.game(m.group(1))
    return RD.set_defs(api.cfg, m.group(1), b.get("defs") or [])


@route("POST", r"/api/gacha/(\w+)/import")
def _(api, m, q, b):
    from .. import gacha as GC
    api.game(m.group(1))
    r = GC.import_doc(api.cfg, m.group(1), b.get("doc"), bool(b.get("dry")))
    return {**r, "stats": GC.stats(api.cfg, m.group(1))}


@route("GET", "/api/gacha/template")
def _(api, m, q, b):
    from .. import gacha as GC
    return GC.TEMPLATE


@route("GET", "/api/news")
def _(api, m, q, b):
    run = news_running()
    return {**news.load(api.cfg), "tz": api.cfg["machine"]["timezone"], "fetching": bool(run),
            "fetching_now": news_now(api.data_dir, run) if run else ""}


@route("GET", r"/api/news/item/(.+)")
def _(api, m, q, b):
    return {"id": m.group(1), "content": news.content_of(api.cfg, m.group(1))}


@route("POST", "/api/news/act")
def _(api, m, q, b):
    return {"ok": True, "prefs": news.act(api.cfg, b)}


@route("POST", "/api/news/refresh")
def _(api, m, q, b):
    only = [str(x) for x in (b.get("only") or [])]
    # 11-02：只读某个游戏 / 来源时用单独的后台任务名，不用等「全部读取」结束；同一个来源由读取进程里的锁排开
    name = "news" if not only else "news-" + "-".join(re.sub(r"\W", "", x) for x in only)[:40]
    started = spawn_background(name, ["news", "fetch", "--from-butler", *only], api.data_dir)
    return {"ok": True, "started": started, **({} if started else {"running": news_now(api.data_dir, [name])})}


def news_running() -> list[str]:
    """正在进行的活动读取（后台任务名：news = 全部；news-xxx = 只读某个游戏 / 来源）。"""
    from .. import launch
    return [n for n in list(launch._bg) if n.startswith("news") and background_running(n)]


def news_now(data_dir, names) -> str:
    """正在进行的读取里还没读完的来源（看 data/logs/<任务名>.log 最后一段：「· 读取 xxx …」之后没有「· xxx 读完」的）。"""
    out = []
    for n in names:
        try:
            tail = (Path(data_dir) / "logs" / f"{n}.log").read_text(encoding="utf-8", errors="replace")[-4000:]
        except OSError:
            continue
        cur = tail.split("=====")[-1]
        done = set(re.findall(r"· (\S+) 读完", cur))
        out += [x for x in re.findall(r"· 读取 (\S+)", cur) if x not in done and x not in out]
    return "、".join(out[:6])
