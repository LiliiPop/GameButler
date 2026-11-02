"""仅关注的游戏（11-02）：不挂脚本，只看活动（站外官方来源）+ 在总览「日常一览」里手动标记今天做完没有。

存在 data/watch.json：
  {"games": {"lysk": {"added": "2026-11-02", "order": 1}}, "done": {"lysk": "2026-11-02"}}
  done 记的是「标为已完成」的那个游戏日；到下一个游戏日（按这个游戏的刷新时间换天）自动变回没完成。

同一个游戏挂上脚本以后，以挂着的为准（这里的记录留着，取消挂载后又回到仅关注）。
可以关注的游戏 = 有站外官方来源的游戏（CATALOG）；以后加新游戏：在 news/sources 的 DEFAULT_SOURCES 加来源，这里加一行。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import jsonio
from .timeutil import BJ, game_day

# 名字、每天刷新时间（北京时间，和挂脚本时的预设一致）
CATALOG = {
    "genshin": {"name": "原神", "refresh": "04:00"},
    "starrail": {"name": "崩坏：星穹铁道", "refresh": "04:00"},
    "tot": {"name": "未定事件簿", "refresh": "04:00"},
    "lysk": {"name": "恋与深空", "refresh": "05:00"},
    "sh": {"name": "时空中的绘旅人", "refresh": "05:00"},
    "yuan": {"name": "代号鸢", "refresh": "05:00"},
    "jx3": {"name": "剑网三无界", "refresh": "06:30"},
}


def _p(cfg) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "watch.json"


def _read(cfg) -> dict:
    d = jsonio.read(_p(cfg), {}) or {}
    d.setdefault("games", {})
    d.setdefault("done", {})
    return d


def records(cfg) -> dict:
    """关注着的（包括已经挂了脚本的），按添加顺序。"""
    gs = _read(cfg)["games"]
    return {gid: {**CATALOG[gid], **r} for gid, r in sorted(gs.items(), key=lambda x: x[1].get("order", 0)) if gid in CATALOG}


def active(cfg) -> dict:
    """现在算「仅关注」的：关注着、又没挂脚本的。"""
    return {gid: r for gid, r in records(cfg).items() if gid not in cfg.get("games", {})}


def news_games(cfg) -> set:
    """活动日历要读的游戏：挂着的 + 仅关注的。"""
    return set(cfg.get("games", {})) | set(active(cfg))


def catalog(cfg) -> list[dict]:
    """「添加游戏」弹窗：每个能关注的游戏和它现在的状态（mounted = 已挂脚本；watched = 已关注）。"""
    rec = records(cfg)
    return [{"id": gid, "name": c["name"], "refresh": c["refresh"], "mounted": gid in cfg.get("games", {}),
             "watched": gid in rec} for gid, c in CATALOG.items()]


def add(cfg, gid: str):
    if gid not in CATALOG:
        raise ValueError(f"现在还不支持这个游戏：{gid}")

    def fn(d):
        d.setdefault("games", {})
        d.setdefault("done", {})
        if gid not in d["games"]:
            d["games"][gid] = {"added": datetime.now(BJ).strftime("%Y-%m-%d"),
                               "order": max([r.get("order", 0) for r in d["games"].values()] + [0]) + 1}
    jsonio.update(_p(cfg), {}, fn)


def remove(cfg, gid: str):
    def fn(d):
        (d.get("games") or {}).pop(gid, None)
        (d.get("done") or {}).pop(gid, None)
    jsonio.update(_p(cfg), {}, fn)


def set_done(cfg, gid: str, on: bool):
    r = active(cfg).get(gid)
    if not r:
        raise ValueError("这个游戏不是仅关注的游戏")
    day = game_day(r).isoformat()

    def fn(d):
        d.setdefault("done", {})
        if on:
            d["done"][gid] = day
        else:
            d["done"].pop(gid, None)
    jsonio.update(_p(cfg), {}, fn)


def cards(cfg) -> list[dict]:
    """总览「日常一览」的行（和挂着的游戏同样的字段，watch = True）。"""
    done = _read(cfg)["done"]
    out = []
    for gid, r in active(cfg).items():
        today = game_day(r).isoformat()
        ok = done.get(gid) == today
        out.append({"id": gid, "name": r["name"], "watch": True, "available": True, "refresh": r["refresh"],
                    "today": today, "done": 1 if ok else 0, "total": 1, "attention": 0, "running": False,
                    "alerts": [], "att": []})
    return out
