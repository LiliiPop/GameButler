"""日程与调度：今天的条目（正在跑 / 接下来 / 跑过的）、拖动顺序、加一次性的、跳过、现在跑、
任务预设上的定时、什么算闲时、自动调度开关、电脑游戏开跑前的提醒、叫醒电脑。"""
from __future__ import annotations

from datetime import datetime

from .. import games as G
from ..schedule import Schedule, days_text, when_text
from ..store import DONE, NEED_ATTENTION
from ..timeutil import BJ, game_day
from . import day_of, route


def schedule_view(api, day) -> dict:
    """日程页：今天的条目（带状态、分段）+ 各游戏的任务预设和定时 + 闲时现在的情况 + 睡眠 / 锁屏提醒。"""
    from .. import idle, wake
    from ..scheduler import idle_seconds, is_pc_game
    from ..signals import fused
    cfg, store = api.cfg, api.store
    sch = Schedule(cfg)
    doc = sch.day(day)
    info = {r["id"]: r for r in api.sched.batch_info}
    cur = api.rs.current()
    cur_game = ((cur or {}).get("current") or {}).get("game", "")
    cur_batch = (cur or {}).get("batch", "")
    warns = sch.conflicts(doc["batches"])
    out = []
    for b in doc["batches"]:
        g = cfg["games"][b["game"]]
        try:
            keys = sch.batch_keys(b)
        except ValueError as e:
            keys, err = [], str(e)
        else:
            err = ""
        gday = game_day(g)
        st = store.status(b["game"], gday)
        done = [k for k in keys if st.get(k, {}).get("result") in DONE]
        bad = [k for k in keys if st.get(k, {}).get("result") in NEED_ATTENTION]
        tried = [k for k in keys if k in st]
        skipt = set(sch.skip_tasks(day, b["game"]))  # 「今日任务」右键跳过的：不算还要跑的
        pending = [k for k in keys if k not in done and k not in bad and k not in skipt]  # 还没做、也没出过问题的：这一条还会跑
        r = info.get(b["id"], {})
        if b.get("requeue"):  # 刚放回「接下来」的：调度上次算的结果（这一轮跑完了）不再算数
            r = {**r, "final": False}
        fz = fused(cfg, b["game"], gday)
        ran = doc["ran"].get(b["id"], "")
        running = b["id"] == cur_batch if cur_batch else cur_game == b["game"]
        if running:
            state = "running"
        elif b["id"] in doc["skip"]:
            state = "skipped"
        elif fz or (bad and not pending):  # 还有没跑的：先算等待，跑完再看要不要处理
            state = "attention"
        elif keys and done and not pending and not bad:
            state = "done"
        elif r.get("due"):
            state = "ready"
        else:
            state = "waiting"
        if b.get("requeue") and not running:  # 重跑失败项：回到「接下来」，等着跑
            state = "ready" if r.get("due") else "waiting"
        if state == "waiting" and r.get("final") and not r.get("due"):
            state = "attention" if bad or len(done) < len(keys) else "done"  # 今天不会再自动跑：按结果算
        if state == "waiting" and b["kind"] == "once" and ran:
            state = "ran"  # 用掉的一次性条目：跑过了（结果看各任务的状态）
        # 分段：正在跑 / 接下来（还会跑）/ 跑过的（做完、要处理、跳过、用掉的一次性条目）
        if running:
            section = "running"
        elif state in ("done", "skipped") or (b["kind"] == "once" and ran) or (r.get("final") and not r.get("due")) or \
                (state == "attention" and not pending and not r.get("due") and not r.get("next")):
            section = "done"
        elif not b["enabled"]:
            section = "done"
        else:
            section = "next"
        last = max((st[k].get("at", "") for k in tried), default="")
        out.append({**b, "name": g["name"], "keys": keys, "done": len(done), "bad": bad, "error": err,
                    "est_minutes": sch.estimate_minutes(b["game"], keys) if keys else 0,
                    "state": state, "section": section, "last": last[11:16] if last else (ran[11:16] if ran else ""),
                    "why": "正在跑" if running else (doc["ran_why"].get(b["id"]) or r.get("why", "")),
                    "next": "" if running else r.get("next", ""), "when_text": when_text(b["when"], g),
                    "warnings": warns.get(b["id"], []), "pc": is_pc_game(g), "ran": ran,
                    "final": bool(r.get("final"))})
    now = datetime.now(BJ)
    routines = []
    rules = sch.rules()
    for gid, g in cfg["games"].items():
        rs = store.routines(gid)["routines"] if G.available(g)[0] else {}
        mine = [r for r in rules if r["game"] == gid]
        routines.append({"game": gid, "name": g["name"], "pc": is_pc_game(g),
                         "routines": [{"name": n, "tasks": len(v.get("tasks", [])),
                                       "rules": [{**x, "text": f"{days_text(x['days'])} · {when_text(x['when'], g)}"}
                                                 for x in mine if x["routine"] == n]} for n, v in rs.items()]})
    ist = idle.status(cfg, now, idle_seconds())
    estimate_starts(api, out, now, ist)
    return {"day": doc["day"], "items": out, "routines": routines,
            "idle": ist, "scheduler": api.sched.enabled(),
            "power": wake.status(cfg, api.sched)}


def estimate_starts(api, items: list[dict], now: datetime, ist: dict):
    """「接下来」每一条大约几点开始（11-02）：按日程里的顺序往下排，前一条跑完（按预计时长）才轮到下一条；
    定时的不早于它的开始时刻，等闲时的不早于预计闲下来的时候。只是估算：实际以调度为准（赶时段的会插队）。
    写进每条的 eta（北京时间 HH:MM）、eta_late（估出来已经过了它的时段，可能赶不上）。"""
    from datetime import timedelta
    from ..schedule import window_bounds
    t = now
    for b in items:
        if b["section"] == "running":
            left = b.get("est_minutes") or 0
            if b.get("keys"):
                left *= max(0.2, 1 - (b.get("done") or 0) / len(b["keys"]))
            t = max(t, now + timedelta(minutes=left))
    enabled = api.sched.enabled()
    held = (api.rs.paused() or {}).get("reason")  # 中止队列 / 让出电脑：什么都不会自动开始
    for b in items:
        if held and b["section"] == "next":
            b["eta"], b["eta_note"] = "", f"{held}中"
            continue
        if b["section"] != "next" or b["state"] == "skipped" or b.get("error") or str(b.get("why", "")).startswith("工具没接好"):
            continue
        st = b.get("start") or {}
        start, end = t, None
        if st.get("mode") == "window":
            if not enabled:
                b["eta"], b["eta_note"] = "", "自动调度关着"
                continue
            g = api.cfg["games"][b["game"]]
            try:
                ws, end = window_bounds(g, b, game_day(g, now))
            except Exception:
                ws = None
            if ws and ws > start:
                start = ws
            if st.get("idle") and not ist.get("ok") and ist.get("wait_s"):
                start = max(start, now + timedelta(seconds=float(ist["wait_s"])))
        if b.get("next"):
            try:
                nx = datetime.strptime(b["next"], "%Y-%m-%d %H:%M").replace(tzinfo=BJ)
                start = max(start, nx)
            except ValueError:
                pass
        b["eta"] = start.strftime("%H:%M")
        b["eta_late"] = bool(end and start >= end)
        t = start + timedelta(minutes=b.get("est_minutes") or 5)


@route("GET", r"/api/schedule/([\w-]+)")
def _(api, m, q, b):
    return schedule_view(api, day_of(m.group(1)))


@route("PUT", r"/api/schedule/([\w-]+)/order")
def _(api, m, q, b):  # 今天拖动后的顺序（只改今天）
    day = day_of(m.group(1))
    Schedule(api.cfg).set_order(day, [str(x) for x in b.get("ids") or []])
    api.sched.wake()
    return schedule_view(api, day)


@route("POST", r"/api/schedule/([\w-]+)/(?:items|batch)")
def _(api, m, q, b):  # 加一条一次性的（「开始」「选任务运行」「添加 · 只这一次」）
    api.game(b.get("game", ""))
    return {"ok": True, "batch": api.enqueue(day_of(m.group(1)), b)}


@route("POST", r"/api/schedule/([\w-]+)/(?:items|batch)/([\w-]+)/(skip|unskip|run-now|delete|save-as-routine|rerun-bad)")
def _(api, m, q, b):
    day, bid, op = day_of(m.group(1)), m.group(2), m.group(3)
    sch = Schedule(api.cfg)
    doc = sch.day(day)
    it = next((x for x in doc["batches"] if x["id"] == bid), None)
    if not it:
        raise ValueError("今天没有这一条")
    if op in ("skip", "unskip"):
        sch.set_skip(day, bid, op == "skip")
    elif op == "delete":
        sch.remove_once(day, bid)
    elif op == "run-now":
        from ..signals import clear_fuse
        clear_fuse(api.cfg, it["game"])
        # 不等条件，这一条自己挪到「接下来」的第一个、马上跑（11-01：不再另加一条，跑完「跑过的」里只有它一条）
        keys = it.get("tasks") if it.get("requeue") else sch.batch_keys({**it, "tasks": it.get("tasks") if it["kind"] == "once" else []})
        sch.requeue(day, bid, keys or [])
        ids = [x["id"] for x in sch.day(day)["batches"]]
        sch.set_order(day, [bid] + [i for i in ids if i != bid])
    elif op == "rerun-bad":
        from ..signals import clear_fuse
        clear_fuse(api.cfg, it["game"])
        # 重跑失败项（10-31）：不另加一条。同一游戏有排着还没跑的条目就并进去；没有就让原条目回到「接下来」最前面
        g = api.cfg["games"][it["game"]]
        st = api.store.status(it["game"], game_day(g))
        keys = [str(k) for k in (b.get("keys") or []) if st.get(str(k), {}).get("result") not in DONE] or \
               [k for k in sch.batch_keys(it) if st.get(k, {}).get("result") in NEED_ATTENTION]
        if not keys:
            raise ValueError("这一条没有没做成的任务")
        same = api._pending_same(day, {"game": it["game"], "routine": it.get("routine", ""), "tasks": keys})
        if not same:
            sch.requeue(day, bid, keys)
            ids = [x["id"] for x in sch.day(day)["batches"]]
            sch.set_order(day, [bid] + [i for i in ids if i != bid])
    elif op == "save-as-routine":
        if it["kind"] != "once":
            raise ValueError("定时生成的条目本来就是一套任务预设")
        name = str(b.get("name") or "").strip()
        if not name:
            raise ValueError("要给新的任务预设起个名字")
        rs = api.store.routines(it["game"])
        if name in rs["routines"]:
            raise ValueError(f"已经有叫「{name}」的任务预设了")
        items = sch.batch_items(it)
        rs["routines"][name] = {"tasks": [{k: v for k, v in t.items() if k in ("task", "choices", "key")} for t in items]}
        api.store.save_routines(it["game"], rs)
        if b.get("when"):
            sch.save_rule({"game": it["game"], "routine": name, "when": b["when"], "days": b.get("days") or "daily"})
    api.sched.wake()
    return {"ok": True, **schedule_view(api, day)}


# ---------------------------------------------------------------- 任务预设上的定时
@route("POST", r"/api/schedule/rules")
def _(api, m, q, b):
    api.game(b.get("game", ""))
    r = Schedule(api.cfg).save_rule({k: v for k, v in b.items() if k != "id"})
    api.sched.wake()
    return {"ok": True, "rule": r}


@route("PUT", r"/api/schedule/rules/([\w-]+)")
def _(api, m, q, b):
    sch = Schedule(api.cfg)
    old = next((r for r in sch.rules(True) if r["id"] == m.group(1)), None)
    if not old:
        raise ValueError("没有这个定时")
    r = sch.save_rule({**old, **b, "id": old["id"], "game": old["game"]})
    api.sched.wake()
    return {"ok": True, "rule": r}


@route("DELETE", r"/api/schedule/rules/([\w-]+)")
def _(api, m, q, b):
    Schedule(api.cfg).delete_rule(m.group(1))
    api.sched.wake()
    return {"ok": True}


@route("PUT", r"/api/schedule/rules-order")
def _(api, m, q, b):
    Schedule(api.cfg).set_rules_order([str(x) for x in b.get("ids") or []])
    api.sched.wake()
    return {"ok": True}


# ---------------------------------------------------------------- 什么算闲时、调度
@route("GET", "/api/idle")
def _(api, m, q, b):
    from .. import idle
    from .. import settings as S
    from ..scheduler import idle_seconds
    return {"groups": S.get(api.cfg, "scheduler")["idle_groups"],
            "status": idle.status(api.cfg, datetime.now(BJ), idle_seconds())}


@route("GET", "/api/scheduler")
def _(api, m, q, b):
    return api.sched.status()


@route("POST", r"/api/scheduler/(on|off)")
def _(api, m, q, b):
    api.sched.set_enabled(m.group(1) == "on")
    return {"ok": True, **api.sched.status()}


@route("POST", "/api/scheduler/wake")
def _(api, m, q, b):  # Windows 的「叫醒电脑」计划任务到点时调这里：马上重新看一遍
    api.sched.log("电脑被管家的定时叫醒")
    api.sched.wake()
    return {"ok": True}


@route("POST", "/api/scheduler/answer")
def _(api, m, q, b):
    if b.get("choice") not in ("now", "later", "skip"):
        raise ValueError("choice 只能是 now / later / skip")
    if not api.sched.answer(b["choice"]):
        raise ValueError("现在没有等你回答的提醒")
    return {"ok": True, **api.sched.status()}
