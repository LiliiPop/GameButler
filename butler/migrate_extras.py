"""10-28：「读公告 · 读资源」从单独的一套任务预设（会再启动一次游戏）改成跑日常时顺带做。

以前：每个游戏有一套叫「读公告 · 读资源」的任务预设（启动游戏 + 📰读游戏内公告 + 💎读抽卡资源），挂着自己的定时。
现在：游戏记录里 read_notice / read_gacha（默认开），planner 在这个游戏每次整套运行时把这两个任务加进去（当天做过就不再做）。

这里只做一次：找到只含这几个任务的那套预设 → 按它有的任务把开关设成开 → 删掉这套预设和挂在它上面的定时。
"""
from __future__ import annotations

from pathlib import Path

from . import gamesdb as GD
from . import jsonio
from .games import GACHA_TASK, NOTICE_TASK

NAME = "读公告 · 读资源"


def _files(cfg: dict) -> list[Path]:
    d = Path(cfg["machine"]["data_dir"]) / "routines"
    return sorted(d.glob("*.json")) if d.exists() else []


def needed(cfg: dict) -> bool:
    return any(NAME in (jsonio.read(p, {}).get("routines") or {}) for p in _files(cfg))


def migrate(cfg: dict) -> str:
    done = []
    rules_p = Path(cfg["machine"]["data_dir"]) / "schedule" / "rules.json"
    for p in _files(cfg):
        gid = p.stem
        doc = jsonio.read(p, {})
        r = (doc.get("routines") or {}).get(NAME)
        if r is None:
            continue
        g = GD.record(cfg, gid) if gid in GD.all_records(cfg) else None
        rec = (g or {}).get("recovery_task", "")
        names = {t.get("task") for t in r.get("tasks", [])}
        if not names <= {rec, NOTICE_TASK, GACHA_TASK, ""}:
            done.append(f"{gid}：「{NAME}」里还有别的任务，没动")
            continue
        if g is not None:
            g["read_notice"] = NOTICE_TASK in names or bool(g.get("read_notice"))
            g["read_gacha"] = GACHA_TASK in names or bool(g.get("read_gacha"))
            GD.save(cfg, gid, g)

        def drop(d):
            d.get("routines", {}).pop(NAME, None)
        jsonio.update(p, {}, drop)

        def drop_rules(d):
            d["rules"] = [x for x in d.get("rules", []) if not (x.get("game") == gid and x.get("routine") == NAME)]
        if rules_p.exists():
            jsonio.update(rules_p, {"rules": []}, drop_rules)
        done.append(f"{gid}：读公告 {'开' if NOTICE_TASK in names else '—'}、读资源 {'开' if GACHA_TASK in names else '—'}，已删掉单独的那套和它的定时")
    return "读公告 · 读资源 并进日常：\n  " + "\n  ".join(done or ["没有要改的"])
