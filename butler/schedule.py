"""日程：今天要跑什么、什么时候跑。

两样东西：
  定时（rules.json）  挂在任务预设上：一个游戏的一套任务预设 + 什么时候 + 哪些天。一套任务预设可以有好几个定时。
                      界面上叫「定时」，写在各自的任务预设上；每天按它们生成「今天」的条目。
  一次性（days/）     只在今天：「开始」「选任务运行」「继续」和「添加」里选「只这一次」的。用完就没了；
                      要常驻就存成任务预设再加定时。

定时：{"id": "r-…", "game": "yuan", "routine": "日常",
       "when": {"kind": "at", "at": "06:00", "until": ""}        到点（北京时间，until 空 = 到这个游戏当天刷新）
             | {"kind": "idle", "at": "", "until": ""}           闲时（at = 最早几点，空 = 刷新后；见 idle.py）
             | {"kind": "after_refresh"}                         任意时段（11-06 改名，原「刷新后马上」）：刷新就能跑，到下次刷新
       "days": "daily" | [1–7]（星期一 = 1）}
一次性：{"id": "o-…", "game", "routine": "" | 名, "tasks": [任务键…], "when": {"kind": "now"} | 同上的 at / idle,
        "rerun"?: true, "added": 时间}
  routine 空、tasks 也空：这个游戏今天各条里还没做完的任务（游戏页的「开始」）。
  routine 空、tasks 有：临时勾的任务，选项取这个游戏第一套含有它的任务预设里的设置，没有就用工具默认。

存储（data/schedule/）：
  rules.json       {"rules": [定时…]}（数组顺序 = 同一时间到点时的先后）
  days/<日期>.json {"once": [一次性…], "order": [今天拖动后的顺序], "skip": [id…], "moved": [点了「现在跑」的定时 id…], "ran": {id: 时间}, "ran_why": {id: 原因},
                    "choices": {游戏: {任务键: 选项}}（游戏页「今日任务」里改了选在「仅今日」的）,
                    "skip_tasks": {游戏: [任务键…]}（「今日任务」右键「跳过此次」的）}
日程日按北京时间、04:00 换日（timeutil.sched_day）。

调度（scheduler.py）看的是「批次」：每个定时 / 一次性条目换算成
  {"id", "kind": "rule"|"once", "game", "routine", "tasks", "start": {"mode": "now"} | {"mode": "window", "from", "to", "idle"},
   "repeat": "daily"|"once", "enabled", "rerun"?}
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from . import jsonio
from . import settings as S
from .store import DONE, Store, item_key
from .timeutil import BJ, game_day, on_game_day, parse_hm, window_instances

WHEN_RULE = ("at", "idle", "after_refresh", "queue")  # queue = 每天排进队列：前面的轮完就跑（11-02）
WHEN_ONCE = ("now", "queue", "at", "idle")  # queue = 加入队列：排在队尾，前面的轮完才开始
WEEK = "一二三四五六日"


def local_tz():
    return datetime.now().astimezone().tzinfo


def new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:8]


def window_bounds(g: dict, b: dict, day: date) -> tuple[datetime, datetime]:
    """时段批次在游戏日 day 里的开始和结束（北京时间）。"""
    st = on_game_day(g, day, b["start"]["from"])
    if b["start"].get("to"):
        en = on_game_day(g, day, b["start"]["to"])
        if en <= st:
            en += timedelta(days=1)
    else:
        en = on_game_day(g, day + timedelta(days=1), g["refresh"])
    return st, en


def when_text(w: dict, g: dict | None = None) -> str:
    """「什么时候」的说明（北京时间后附电脑本地时间）。"""
    def hm(x):
        t = parse_hm(x)
        loc = datetime.now(BJ).replace(hour=t.hour, minute=t.minute).astimezone(local_tz())
        return f"{loc:%H:%M}（北京 {x}）" if loc.utcoffset() != BJ.utcoffset(None) else x
    k = w.get("kind")
    if k == "now":
        return "现在"
    if k == "queue":
        return "轮到时"  # 11-06：原「加入队列」——和「闲时」「到点」一样说的是什么时候跑：前面的轮完就轮到它
    if k == "after_refresh":
        return "任意时段"
    if k == "at":
        return f"{hm(w['at'])}" + (f" 到 {hm(w['until'])}" if w.get("until") else "")
    if k == "idle":
        return "闲时" + (f"，{hm(w['at'])} 以后" if w.get("at") else "") + (f"，到 {hm(w['until'])} 为止" if w.get("until") else "")
    return ""


def days_text(days) -> str:
    if days == "daily" or not days:
        return "每天"
    return "每周" + "、".join(WEEK[d - 1] for d in sorted(days))


class Schedule:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.dir = Path(cfg["machine"]["data_dir"]) / "schedule"
        self.store = Store(cfg["machine"]["data_dir"])

    @property
    def rpath(self) -> Path:
        return self.dir / "rules.json"

    # ---------- 检查 ----------
    def _game(self, gid: str):
        from .gamesdb import all_records
        if gid not in self.cfg["games"] and gid not in all_records(self.cfg):
            raise ValueError(f"没有这个游戏：{gid}")

    def _when(self, w: dict, kinds: tuple) -> dict:
        w = dict(w or {})
        k = w.get("kind")
        if k not in kinds:
            raise ValueError("「什么时候」只能是：" + "、".join({"now": "现在", "queue": "轮到时", "at": "到点", "idle": "闲时",
                                                             "after_refresh": "任意时段"}[x] for x in kinds))
        out = {"kind": k}
        if k == "at":
            parse_hm(str(w.get("at") or ""))
            out["at"] = w["at"]
        if k == "idle":
            from .idle import configured
            if not configured(self.cfg):
                raise ValueError("还没设置什么算闲时：先在「什么算闲时」里加一组条件")
            if w.get("at"):
                parse_hm(str(w["at"]))
            out["at"] = w.get("at") or ""
        if k in ("at", "idle"):
            if w.get("until"):
                parse_hm(str(w["until"]))
            out["until"] = w.get("until") or ""
        return out

    def clean_rule(self, r: dict) -> dict:
        gid = r.get("game", "")
        self._game(gid)
        routine = str(r.get("routine") or "")
        if not routine:
            raise ValueError("定时要挂在一套任务预设上")
        if gid in self.cfg["games"] and routine not in self.store.routines(gid)["routines"]:
            raise ValueError(f"这个游戏没有叫「{routine}」的任务预设")
        days = r.get("days") or "daily"
        if days != "daily":
            try:
                days = sorted({int(x) for x in days})
            except (TypeError, ValueError):
                raise ValueError("「哪些天」只能是每天或星期几")
            if not days or any(not 1 <= d <= 7 for d in days):
                raise ValueError("「哪些天」至少选一天")
            if len(days) == 7:
                days = "daily"
        out = {"id": r.get("id") or new_id("r"), "game": gid, "routine": routine,
               "when": self._when(r.get("when"), WHEN_RULE), "days": days}
        return out  # 10-30：定时上不再有「启用」（不跑就删掉定时）和「重跑」（要隔几小时再跑用任务预设上的「自动重复」）

    def clean_once(self, b: dict) -> dict:
        gid = b.get("game", "")
        self._game(gid)
        routine = str(b.get("routine") or "")
        if routine and gid in self.cfg["games"] and routine not in self.store.routines(gid)["routines"]:
            raise ValueError(f"这个游戏没有叫「{routine}」的任务预设")
        w = b.get("when")
        out = {"id": b.get("id") or new_id("o"), "game": gid, "routine": routine,
               "tasks": [str(x) for x in (b.get("tasks") or [])], "when": self._when(w or {"kind": "now"}, WHEN_ONCE)}
        if b.get("rerun"):
            out["rerun"] = True
        if b.get("added"):
            out["added"] = b["added"]
        if b.get("label"):
            out["label"] = str(b["label"])
        if b.get("hires"):  # 「重新获取题图」：跑的时候模拟器临时调高到这个分辨率（如 1920x1080）
            out["hires"] = str(b["hires"])
        return out

    # ---------- 定时 ----------
    def rules(self, all_games: bool = False) -> list[dict]:
        rs = jsonio.read(self.rpath, {"rules": []}).get("rules", [])
        if any(r.get("enabled") is False or "enabled" in r or r.get("rerun") for r in rs):
            # 以前关掉的定时直接删掉；「启用」「重跑」两个字段不再有（10-30）
            self._write_rules(lambda xs: [{k: v for k, v in x.items() if k not in ("enabled", "rerun")}
                                          for x in xs if x.get("enabled") is not False])
            rs = jsonio.read(self.rpath, {"rules": []}).get("rules", [])
        return rs if all_games else [r for r in rs if r["game"] in self.cfg["games"]]

    def _write_rules(self, fn):
        def upd(doc):
            doc["rules"] = fn(list(doc.get("rules", [])))
        jsonio.update(self.rpath, {"rules": []}, upd)

    def save_rule(self, r: dict) -> dict:
        r = self.clean_rule(r)

        def fn(rs):
            for i, x in enumerate(rs):
                if x["id"] == r["id"]:
                    rs[i] = r
                    return rs
            return rs + [r]
        self._write_rules(fn)
        return r

    def delete_rule(self, rid: str):
        if not any(r["id"] == rid for r in self.rules(True)):
            raise ValueError("没有这个定时")
        self._write_rules(lambda rs: [r for r in rs if r["id"] != rid])

    def set_rules_order(self, ids: list[str]):
        def fn(rs):
            pos = {i: n for n, i in enumerate(ids)}
            return sorted(rs, key=lambda r: pos.get(r["id"], len(ids) + rs.index(r)))
        self._write_rules(fn)

    def routine_renamed(self, gid: str, old: str, new: str):
        def fn(rs):
            for r in rs:
                if r["game"] == gid and r["routine"] == old:
                    r["routine"] = new
            return rs
        self._write_rules(fn)

    def routines_kept(self, gid: str, names) -> list[dict]:
        """任务预设删掉后，它的定时一起删；返回删掉的定时。"""
        gone = [r for r in self.rules(True) if r["game"] == gid and r["routine"] not in names]
        if gone:
            ids = {r["id"] for r in gone}
            self._write_rules(lambda rs: [r for r in rs if r["id"] not in ids])
        return gone

    def applies(self, r: dict, day: date) -> bool:
        return r["days"] == "daily" or day.isoweekday() in r["days"]

    # ---------- 换算成批次 ----------
    def _start(self, w: dict, g: dict, kind: str = "once") -> dict:
        k = w["kind"]
        if k == "queue" and kind == "rule":  # 每天排进队列：一整天都可以跑（自动调度），但要等排在前面的都轮完
            return {"mode": "window", "from": g["refresh"], "to": "", "idle": False, "queue": True}
        if k == "now":
            return {"mode": "now"}
        if k == "queue":  # 和「现在」一样只跑一次，但要等排在它前面的都轮完（scheduler.tick）
            return {"mode": "now", "queue": True}
        if k == "after_refresh":
            return {"mode": "window", "from": g["refresh"], "to": "", "idle": False}  # 11-06：不再等刷新后几分钟
        return {"mode": "window", "from": w.get("at") or g["refresh"], "to": w.get("until") or "", "idle": k == "idle"}

    def as_batch(self, x: dict, kind: str) -> dict:
        g = self.cfg["games"][x["game"]]
        b = {"id": x["id"], "kind": kind, "game": x["game"], "routine": x.get("routine", ""),
             "tasks": list(x.get("tasks") or []), "when": x["when"], "start": self._start(x["when"], g, kind),
             "repeat": "daily" if kind == "rule" else "once", "enabled": x.get("enabled", True)}
        for k in ("rerun", "added", "days", "label", "hires"):
            if x.get(k):
                b[k] = x[k]
        return b

    # ---------- 某一天 ----------
    def day_path(self, day: date) -> Path:
        return self.dir / "days" / f"{day.isoformat()}.json"

    def day(self, day: date) -> dict:
        """今天的条目：今天生效的定时 + 一次性的，按今天的顺序（没拖过：定时的顺序在前，一次性按加入先后）。"""
        d = jsonio.read(self.day_path(day), {})
        moved = set(d.get("moved", []))  # 今天点了「现在跑」的定时：换成了一条「现在」的一次性条目
        rules = [self.as_batch(r, "rule") for r in self.rules() if self.applies(r, day) and r["id"] not in moved]
        once = []
        for b in d.get("once", []):
            if b.get("game") not in self.cfg["games"]:
                continue
            try:
                once.append(self.as_batch(self.clean_once(b), "once"))
            except ValueError:  # 用的任务预设已经删了：这一条不再显示
                continue
        # 11-06：日程里展开改过「今天这一条跑哪些、什么顺序」的（days 里 edit {id: [任务键…]}）：只改今天，不改任务预设
        for b in rules + once:
            ed = (d.get("edit") or {}).get(b["id"])
            if ed:
                b.update(edit=list(ed), tasks=list(ed))
        # 「重跑失败项」：原条目回到「接下来」，只跑没做成的那几项（days 里 requeue {id: [任务键…]}）
        for b in rules + once:
            keys = (d.get("requeue") or {}).get(b["id"])
            if keys:
                b.update(start={"mode": "now", **({"queue": True} if b["id"] in (d.get("requeue_q") or []) else {})},
                         tasks=list(keys), requeue=True)
                if b["id"] in (d.get("requeue_rerun") or []):
                    b["rerun"] = True
        allb = {b["id"]: b for b in rules + once}
        order = [i for i in d.get("order", []) if i in allb]
        order += [b["id"] for b in rules + once if b["id"] not in order]
        return {"day": day.isoformat(), "batches": [allb[i] for i in order],
                "skip": [i for i in d.get("skip", []) if i in allb],
                "ran": {k: v for k, v in d.get("ran", {}).items() if k not in (d.get("requeue") or {})},
                "ran_why": d.get("ran_why", {})}

    def day_choices(self, day: date, gid: str) -> dict:
        """「仅今日」改过的选项 {任务键: choices}（只在这一天）。"""
        return (jsonio.read(self.day_path(day), {}).get("choices") or {}).get(gid) or {}

    def set_day_choices(self, day: date, gid: str, patch: dict):
        """patch = {任务键: choices | None}；None = 去掉今天单独的，回到任务预设里的。"""
        def fn(d):
            c = d.setdefault("choices", {}).setdefault(gid, {})
            for k, v in patch.items():
                if v is None:
                    c.pop(k, None)
                else:
                    c[k] = v
        jsonio.update(self.day_path(day), {}, fn)

    def skip_tasks(self, day: date, gid: str) -> list[str]:
        """游戏页「今日任务」右键「跳过此次」的任务键（只在这一天；右键「不跳过了」去掉）。"""
        return (jsonio.read(self.day_path(day), {}).get("skip_tasks") or {}).get(gid) or []

    def set_skip_task(self, day: date, gid: str, key: str, on: bool):
        def fn(d):
            c = d.setdefault("skip_tasks", {})
            c[gid] = [k for k in c.get(gid, []) if k != key] + ([key] if on else [])
        jsonio.update(self.day_path(day), {}, fn)

    def set_order(self, day: date, ids: list[str]):
        """今天拖动后的顺序（只改今天）。"""
        known = {b["id"] for b in self.day(day)["batches"]}
        bad = [i for i in ids if i not in known]
        if bad:
            raise ValueError("今天没有这些条目：" + "、".join(bad))
        jsonio.update(self.day_path(day), {}, lambda d: d.update(order=list(ids)))

    def add_once(self, day: date, b: dict) -> dict:
        """加一条一次性的（「开始」「继续」都走这里）。现在跑的排在今天的最后。"""
        b = self.clean_once(b)
        b["added"] = datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")

        def fn(d):
            d.setdefault("once", []).append(b)
            if d.get("order"):
                d["order"].append(b["id"])
        jsonio.update(self.day_path(day), {}, fn)
        return self.as_batch(b, "once") if b["game"] in self.cfg["games"] else b

    def remove_once(self, day: date, bid: str):
        d = jsonio.read(self.day_path(day), {})
        if not any(b["id"] == bid for b in d.get("once", [])):
            raise ValueError("这一条不是今天临时加的（定时生成的请用「今天跳过」）")

        def fn(d):
            d["once"] = [b for b in d.get("once", []) if b["id"] != bid]
            d["order"] = [i for i in d.get("order", []) if i != bid]
            d["skip"] = [i for i in d.get("skip", []) if i != bid]
        jsonio.update(self.day_path(day), {}, fn)

    def move_now(self, day: date, rid: str):
        """定时生成的条目点了「现在跑」：今天不再按它的时段等，由刚加的「现在」那条代替。"""
        jsonio.update(self.day_path(day), {}, lambda d: d.update(moved=list(dict.fromkeys(d.get("moved", []) + [rid]))))

    def once_item(self, day: date, bid: str) -> dict | None:
        return next((b for b in jsonio.read(self.day_path(day), {}).get("once", []) if b["id"] == bid), None)

    def set_skip(self, day: date, bid: str, on: bool):
        def fn(d):
            d["skip"] = [i for i in d.get("skip", []) if i != bid] + ([bid] if on else [])
            if on:  # 11-04：跳过了的条目，之前「挪到现在」排着的那一轮也作废（不然下次挪回来会把旧的整套任务并进去）
                (d.get("requeue") or {}).pop(bid, None)
                d["requeue_q"] = [i for i in d.get("requeue_q", []) if i != bid]
                d["requeue_rerun"] = [i for i in d.get("requeue_rerun", []) if i != bid]
        jsonio.update(self.day_path(day), {}, fn)

    def requeue(self, day: date, bid: str, keys: list[str], queue: bool = False, rerun: bool = False):
        """原条目回到「接下来」，只跑这几项；跑一次后恢复原样（mark_ran 时去掉）。
        「重跑失败项」「现在跑」「继续」、加一条同一套预设的，都走这里，不再另加一条（11-01）。
        queue = 按「加入队列」排（前面的轮完才开始），否则马上跑。"""
        def fn(d):
            d.setdefault("requeue", {})[bid] = list(dict.fromkeys(keys))
            q = [i for i in d.get("requeue_q", []) if i != bid]
            d["requeue_q"] = q + ([bid] if queue else [])
            rr = [i for i in d.get("requeue_rerun", []) if i != bid]  # 11-03：「再跑一次」挪过来的：今天做过的也再跑
            d["requeue_rerun"] = rr + ([bid] if rerun else [])
            d["skip"] = [i for i in d.get("skip", []) if i != bid]
            d.get("ran_why", {}).pop(bid, None)
        jsonio.update(self.day_path(day), {}, fn)

    def add_tasks(self, day: date, bid: str, keys: list[str]):
        """把任务并进一条还没跑的一次性条目（或重跑中的条目）。"""
        def fn(d):
            if bid in (d.get("requeue") or {}):
                d["requeue"][bid] = list(dict.fromkeys(d["requeue"][bid] + keys))
                return
            for b in d.get("once", []):
                if b["id"] == bid and b.get("tasks"):
                    b["tasks"] = list(dict.fromkeys(b["tasks"] + keys))
        jsonio.update(self.day_path(day), {}, fn)

    def mark_ran(self, day: date, bid: str, why: str = ""):
        """「现在」的条目只跑一次（要再跑就再加一次）。why = 到开始时没有要跑的，原因。"""
        def fn(d):
            if bid in (d.get("requeue") or {}):  # 重跑失败项的那一轮开始了：条目恢复原样
                d["requeue"].pop(bid)
                d["requeue_q"] = [i for i in d.get("requeue_q", []) if i != bid]
                d["requeue_rerun"] = [i for i in d.get("requeue_rerun", []) if i != bid]
                d.setdefault("ran_why", {}).pop(bid, None)
                if not any(b["id"] == bid for b in d.get("once", [])):
                    return  # 定时生成的：不记「跑过」（它本来就按时段管）
            d.setdefault("ran", {})[bid] = datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")
            if why:
                d.setdefault("ran_why", {})[bid] = why
        jsonio.update(self.day_path(day), {}, fn)

    def forget(self, gid: str):
        """彻底删除：定时和每一天的日程里这个游戏的条目。"""
        self._write_rules(lambda rs: [r for r in rs if r["game"] != gid])
        for p in (self.dir / "days").glob("*.json"):
            def dfn(d):
                ids = {b["id"] for b in d.get("once", []) if b["game"] == gid}
                d["once"] = [b for b in d.get("once", []) if b["game"] != gid]
                d["order"] = [i for i in d.get("order", []) if i not in ids]
                d["skip"] = [i for i in d.get("skip", []) if i not in ids]
                d["ran"] = {k: v for k, v in d.get("ran", {}).items() if k not in ids}
                d["ran_why"] = {k: v for k, v in d.get("ran_why", {}).items() if k not in ids}
            jsonio.update(p, {}, dfn)

    # ---------- 今天各条里的任务 ----------
    def batch_items(self, b: dict) -> list[dict]:
        """这一条要跑的任务项（不含启动任务以外的过滤；按它用的那套）。
        今天改过清单的（edit）：按改过的顺序，选项用它那套预设里的，预设里没有的用工具默认。"""
        from .planner import source
        g = self.cfg["games"][b["game"]]
        if b.get("edit") and not b.get("requeue"):
            base = source(self.cfg, self.store, b["game"], game_day(g), b.get("routine", ""), None) if b.get("routine") else []
            out = []
            for k in b["edit"]:
                hit = next((t for t in base if item_key(t) == k or t.get("_base") == k), None) or \
                      next((t for t in base if t["task"] == k), None)
                if hit is None:
                    from .planner import resolve_named
                    hit = resolve_named(self.store, b["game"], [k])[0]
                if hit not in out:
                    out.append(hit)
            return out
        return source(self.cfg, self.store, b["game"], game_day(g), b.get("routine", ""), b.get("tasks") or None)

    def set_edit(self, day: date, bid: str, keys: list[str] | None):
        """今天这一条跑哪些任务、什么顺序（只改今天）。None / 空 = 回到任务预设里的。"""
        def fn(d):
            e = d.setdefault("edit", {})
            if keys:
                e[bid] = list(dict.fromkeys(keys))
            else:
                e.pop(bid, None)
        jsonio.update(self.day_path(day), {}, fn)

    def batch_keys(self, b: dict) -> list[str]:
        """条目包含的任务键（不含启动任务）。"""
        rec = self.cfg["games"][b["game"]].get("recovery_task")
        return [item_key(t) for t in self.batch_items(b) if t["task"] != rec]

    def game_tasks(self, gid: str, day: date | None = None, with_skipped: bool = False) -> list[dict]:
        """这个游戏今天各条里的任务（去重，按出现的先后）。主页卡片、报告、错过时段、BetterGI 同步都看这里。"""
        from .timeutil import sched_day
        doc = self.day(day or sched_day())
        seen, out = set(), []
        for b in doc["batches"]:
            if b["game"] != gid or not b["enabled"] or (b["id"] in doc["skip"] and not with_skipped):
                continue
            if not b.get("routine") and not b.get("tasks"):
                continue  # 「开始」：跑的就是别的条目里的任务
            if b.get("routine"):
                items = self.batch_items(b)
            else:  # 临时勾的任务：选项先看前面各条里的，再看任务预设（不能再回头算今天，会绕圈）
                from .planner import resolve_named
                items = resolve_named(self.store, gid, b["tasks"], out)
            for t in items:
                k = item_key(t)
                if k not in seen:
                    seen.add(k)
                    out.append(t)
        return out

    # ---------- 估算 / 检查 ----------
    def estimate_minutes(self, gid: str, keys: list[str]) -> float:
        """按最近 7 个游戏日的实际用时估算（每个任务取最近一次成功的用时；没有记录按 3 分钟）。"""
        g = self.cfg["games"][gid]
        today = game_day(g)
        last: dict[str, float] = {}
        for i in range(1, 8):
            for k, e in self.store.status(gid, today - timedelta(days=i)).items():
                if k not in last and e.get("result") in DONE and e.get("minutes"):
                    last[k] = float(e["minutes"])
        return round(sum(last.get(k, 3.0) for k in keys), 1)

    def conflicts(self, batches: list[dict]) -> dict[str, list[str]]:
        """一个游戏当天第一个「闲时」条目，如果只能靠闲时里的时段成立、而那时某个有时段的任务已经过了 →
        橙色警告（只警告，不拦）。"""
        from .idle import groups
        from .planner import window_of
        starts = []
        for grp in groups(self.cfg):
            if any(c["kind"] == "time" for c in grp) and all(c["kind"] == "time" for c in grp):
                starts.append(next(c for c in grp if c["kind"] == "time")["from"])
        has_idle_only = any(not any(c["kind"] == "time" for c in grp) for grp in groups(self.cfg))
        out: dict[str, list[str]] = {}
        if not starts or has_idle_only:
            return out
        seen = set()
        tz = local_tz()
        for b in batches:
            gid = b["game"]
            if gid in seen or not b["enabled"]:
                continue
            seen.add(gid)
            if b["start"]["mode"] != "window" or not b["start"]["idle"]:
                continue
            g = self.cfg["games"][gid]
            day = game_day(g)
            base, _ = window_bounds(g, b, day)
            cands = []
            for hm in starts:
                t = parse_hm(hm)
                c = base.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
                if c < base:
                    c += timedelta(days=1)
                cands.append(c)
            start = min(cands)
            msgs = []
            for t in self.batch_items(b):
                k = item_key(t)
                spec = window_of(g, t)
                if not spec:
                    continue
                ends = window_instances(g, day, spec)
                if all(start >= en for _, en in ends):
                    w = "、".join(f"{a:%H:%M}–{e:%H:%M}" for a, e in ends)
                    wl = "、".join(f"{a.astimezone(tz):%H:%M}–{e.astimezone(tz):%H:%M}" for a, e in ends)
                    msgs.append(f"{g['name'].split('（')[0]}「{k}」只能在北京时间 {w}（本地 {wl}）做，"
                                f"闲时要到本地 {start.astimezone(tz):%H:%M} 才开始，今天会错过")
            if msgs:
                out[b["id"]] = msgs
        return out
