"""自动重复：同一个任务在同一个游戏日里多跑几轮。设在任务预设上，只对点名的单个任务生效：
routines[名]["again"] = {任务键: 设置}，设置是下面两种之一（游戏页「任务预设」→「自动重复」里设）。

  {"every_hours": 6, "max_rounds": 4}
      接力：上一轮做完（成功）后隔 N 小时自动再跑一轮，当天最多 max_rounds 轮（含第一轮）。
      · 间隔跨天也算：新游戏日的第一轮要等前一天最后一轮做完满 N 小时（例如案例解析还没解析完就不去）。
      · 算下来过了下一次刷新的轮次，当天不排，也不会挤到第二天。
      · 某一轮失败或「无可做」（次数用完等），后面的轮次不再排（失败的那轮按正常规则重试）。

  {"at": ["14:00", "20:30"]}
      到点再跑：到这些时间（北京时间，按游戏日算；早于刷新时刻的算第二天凌晨）各再跑一次，每个时间只跑一次，
      不管前面做没做完。

轮次是「虚拟条目」：任务和选项同原条目，key 为「原 key · 第2轮」/「原 key · 14:00」，结果分别记在当天状态里。
完成时间用状态里的 at（完整北京时间）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .store import DONE, Store, item_key
from .timeutil import BJ, day_start, game_day, on_game_day


def check(g: dict, again) -> dict | None:
    """检查一个任务的自动重复设置；不对直接报错。空 = 不重复。"""
    if not again:
        return None
    if not isinstance(again, dict) or not (again.get("every_hours") or again.get("at")):
        raise ValueError("自动重复要写 every_hours（接力）或 at（到点再跑）")
    out = {}
    if again.get("every_hours"):
        out = {"every_hours": float(again["every_hours"]), "max_rounds": int(again.get("max_rounds") or 2)}
    if again.get("at"):
        for hm in again["at"]:
            on_game_day(g, game_day(g), str(hm))  # 时间格式检查
        out["at"] = [str(x) for x in again["at"]]
    return out


def check_preset(g: dict, again, keys: set[str]) -> dict:
    """任务预设上的「自动重复」：{任务键: {every_hours, max_rounds} | {at: [...]}}。"""
    if not again:
        return {}
    if not isinstance(again, dict):
        raise ValueError("自动重复要写成 {任务: 设置}")
    out = {}
    for k, a in again.items():
        if k not in keys:
            raise ValueError(f"自动重复里的「{k}」不在这套任务预设里")
        c = check(g, a)
        if c:
            out[k] = c
    return out


def preset_again(store: Store, gid: str, routine: str) -> dict:
    if not routine:
        return {}
    r = store.routines(gid)["routines"].get(routine) or {}
    return r.get("again") or {}


def _done_at(entry: dict) -> datetime | None:
    if not entry.get("at"):
        return None
    return datetime.strptime(entry["at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ)


def relay_key(base: str, n: int) -> str:
    return f"{base} · 第{n}轮"


def expand(g: dict, tasks: list[dict], a: dict, status: dict, prev_status: dict, day: date,
           rec_task: str = "") -> tuple[list[dict], dict]:
    """a = {任务键: 自动重复设置}（任务预设上的）。返回当天的轮次条目（每个带 _not_before、_base），
    以及原条目的最早开始时间 {原 key: datetime}（接力跨天间隔）。"""
    next_refresh = day_start(g, day + timedelta(days=1))
    rounds, gates = [], {}
    if not a:
        return rounds, gates
    for it in tasks:
        if it["task"] == rec_task:
            continue
        base = item_key(it)
        ai = a.get(base)
        if not ai:
            continue
        hours = float(ai.get("every_hours") or 0)
        if hours > 0:
            gap = timedelta(hours=hours)
            maxn = int(ai.get("max_rounds") or 2)
            # 跨天：前一天最后一个成功轮次做完满 N 小时，今天的第一轮才开始
            last = None
            for n in range(1, maxn + 1):
                e = prev_status.get(base if n == 1 else relay_key(base, n), {})
                if e.get("result") == "succeeded":
                    last = _done_at(e) or last
            if last and last + gap > day_start(g, day):
                gates[base] = last + gap
            prev_key = base
            for n in range(2, maxn + 1):
                e = status.get(prev_key, {})
                if e.get("result") != "succeeded":
                    break  # 上一轮没做成（或无可做）：后面不排
                t = _done_at(e)
                if not t:
                    break
                nb = t + gap
                if nb >= next_refresh:
                    break  # 来不及在今天做：不排，也不挤到第二天
                key = relay_key(base, n)
                rounds.append({**{k: v for k, v in it.items() if k not in ("key", "again")},
                               "key": key, "_base": base, "_not_before": nb, "_kind": "relay"})
                prev_key = key
        for hm in ai.get("at") or []:
            nb = on_game_day(g, day, str(hm))
            rounds.append({**{k: v for k, v in it.items() if k not in ("key", "again")},
                           "key": f"{base} · {hm}", "_base": base, "_not_before": nb, "_kind": "at"})
    return rounds, gates


def for_batch(cfg: dict, gid: str, store: Store, b: dict, day: date | None = None) -> tuple[list[dict], dict]:
    """一个批次的轮次和跨天间隔（它用的任务预设没设自动重复就是空的）。"""
    a = preset_again(store, gid, b.get("routine", ""))
    if not a:
        return [], {}
    from .planner import source
    g = cfg["games"][gid]
    day = day or game_day(g)
    tasks = source(cfg, store, gid, day, b.get("routine", ""), b.get("tasks") or None)
    if b.get("tasks"):
        tasks = [t for t in tasks if item_key(t) in b["tasks"]]
    return expand(g, tasks, a, store.status(gid, day), store.status(gid, day - timedelta(days=1)), day,
                  g.get("recovery_task", ""))


def for_game(cfg: dict, gid: str, store: Store, day: date | None = None) -> tuple[list[dict], dict, dict]:
    """这个游戏当天所有批次的轮次（同一轮次只算一次）、原条目最早开始时间、当天状态。"""
    from .schedule import Schedule
    g = cfg["games"][gid]
    day = day or game_day(g)
    rounds, gates, seen = [], {}, set()
    for b in Schedule(cfg).day(day)["batches"]:
        if b["game"] != gid or not b["enabled"] or not preset_again(store, gid, b.get("routine", "")):
            continue
        rs, gs = for_batch(cfg, gid, store, b, day)
        rounds += [r for r in rs if r["key"] not in seen and not seen.add(r["key"])]
        gates.update(gs)
    return rounds, gates, store.status(gid, day)


def strip(items: list[dict]) -> list[dict]:
    """去掉内部字段，交给执行器。"""
    return [{k: v for k, v in t.items() if not k.startswith("_")} for t in items]


def waiting(cfg: dict, gid: str, store: Store, now: datetime) -> list[tuple[str, datetime]]:
    """还没到点的轮次 / 被跨天间隔挡住的原条目：[(key, 开始时间)]，按时间排。"""
    rounds, gates, status = for_game(cfg, gid, store)
    out = [(r["key"], r["_not_before"]) for r in rounds
           if r["_not_before"] > now and status.get(r["key"], {}).get("result") not in DONE]
    out += [(k, t) for k, t in gates.items() if t > now and status.get(k, {}).get("result") not in DONE]
    return sorted(out, key=lambda x: x[1])
