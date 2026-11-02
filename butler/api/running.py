"""总览 / 运行：各游戏概况、现在在跑什么、停止、继续、暂停、让出电脑。"""
from __future__ import annotations

import threading
import time
from datetime import timedelta

from .. import games as G
from .. import report
from ..runstate import is_admin, kill_image, kill_tree, now_bj
from ..store import DONE, NEED_ATTENTION, item_key
from ..timeutil import game_day, sched_day
from . import route


def game_card(api, gid: str, cur: dict | None) -> dict:
    """主页卡片。"""
    from .. import gacha as GC, readings as RD, rounds as R
    from ..scheduler import is_pc_game
    cfg, store = api.cfg, api.store
    g = cfg["games"][gid]
    ok, why = G.available(g)
    today = game_day(g)
    base = {"id": gid, "name": g["name"], "today": today.isoformat(), "tomorrow": (today + timedelta(days=1)).isoformat(),
            "kind": G.kind(g), "pc": is_pc_game(g), "windows": g.get("windows") or {},
            "available": ok, "message": why, "has_notice": bool(g.get("notice_reader")),
            "has_gacha": bool(g.get("gacha_reader") or g.get("pc_gacha")),
            "read_notice": bool(g.get("notice_reader")) and g.get("read_notice", True) is not False,
            "read_gacha": bool(g.get("gacha_reader") or g.get("pc_gacha")) and g.get("read_gacha", True) is not False, "emulator": g.get("emulator", ""), "refresh": g["refresh"],
            "notice": g.get("notice", ""), "recovery_task": g.get("recovery_task", ""),
            "running": bool(cur and cur.get("current") and cur["current"].get("game") == gid),
            "gacha": RD.brief(cfg, gid), "pity": GC.brief(cfg, gid)}
    if not ok:
        return {**base, "routines": [], "done": 0, "total": 0, "attention": 0, "alerts": []}
    ad = G.adapter(cfg, gid)
    store.ensure_routines(gid, ad.seed())
    doc = store.routines(gid)
    st = store.status(gid, today)
    from ..schedule import Schedule
    rec = g.get("recovery_task", "")
    keys = [item_key(t) for t in Schedule(cfg).game_tasks(gid) if ad.usable(t["task"]) and t["task"] != rec]
    keys += [r["key"] for r in R.for_game(cfg, gid, store, today)[0] if ad.usable(r["task"])]
    runs = report.list_runs(cfg, gid, today)
    last = runs[-1] if runs else None
    try:
        labels, problem = ad.labels(), ""
    except (OSError, ValueError, RuntimeError, KeyError) as e:  # 工具的任务列表读不出来：卡片上写原因，别的游戏照常显示
        labels, problem = {}, f"任务列表读不出来：{e}"
    return {**base, "routines": list(doc["routines"]), "labels": labels, "problem": problem,
            "done": sum(1 for k in keys if st.get(k, {}).get("result") in DONE), "total": len(keys),
            "attention": sum(1 for k in keys if st.get(k, {}).get("result") in NEED_ATTENTION),
            "alerts": [{"task": k, "text": st[k]["alert"]} for k in keys if st.get(k, {}).get("alert")],
            "att": [{"task": k, "result": st[k]["result"]} for k in keys if st.get(k, {}).get("result") in NEED_ATTENTION],
            "last_run": {k: last[k] for k in ("started", "ok", "finished", "stopped")} if last else None,
            "changed_outside": ad.changed_outside(), "can_open": ad.has_gui(), "can_import": ad.can_import, "can_launch": ad.can_launch()}


def do_yield(cfg: dict, rs):
    """停止运行 → 等它停下（最多 90 秒）→ 关闭所有用到的模拟器实例和电脑游戏 / 工具。"""
    rs.request_stop("让出电脑")
    rs.pause("让出电脑")
    rs.clear_continue()  # 你明确不想继续
    close_all(cfg, rs)


def close_all(cfg: dict, rs):
    """等运行停下（最多 90 秒，停不下强制结束）→ 关闭所有用到的模拟器实例和电脑游戏 / 工具。"""
    t0 = time.time()
    while rs.current() and time.time() - t0 < 90:
        time.sleep(2)
    cur = rs.current()
    if cur:  # 还没停下：强制结束
        kill_tree(int(cur.get("runner_pid") or 0))
        kill_tree(int(cur.get("pid") or 0))
    games = cfg["games"]
    emus = {G.emulator_of(g) for g in games.values()} - {""}
    if emus:
        from ..mumu import MuMu
        mumu = MuMu.of(cfg)
        for e in emus:
            mumu.shutdown(e)
    for gid in games:
        for exe in G.adapter(cfg, gid).processes():
            kill_image(exe)


def _current_game(api) -> tuple[dict | None, str]:
    cur = api.rs.current()
    return cur, ((cur or {}).get("current") or {}).get("game", "")


HALT = "中止队列"  # rs.pause 的原因：和「让出电脑」区分

@route("GET", "/api/state")
def _(api, m, q, b):
    cur = api.rs.current()
    return {"games": [game_card(api, gid, cur) for gid in api.cfg["games"]], "now": now_bj(),
            "paused": api.rs.paused(), "game_day": sched_day().isoformat(), "admin": is_admin(),
            "appearance": api.appearance()}


@route("GET", "/api/running")
def _(api, m, q, b):
    cur, cg = _current_game(api)
    rs = api.rs
    return {"running": bool(cur), "paused": rs.paused(), "suspended": rs.suspended() if cur else None,
            "can_suspend": bool(cg) and api.adapter(cg).can_suspend,
            "stop_requested": rs.stop_requested() and bool(cur),
            "resume": None if cur else rs.get_continue(api.cfg), "prompt": api.sched.prompt,
            **({"started": cur["started"], "games": cur["games"], "done_games": cur["done_games"],
                "current": cur["current"]} if cur else {})}


@route("POST", "/api/stop")
def _(api, m, q, b):
    cur = api.rs.current()
    api.rs.request_stop("界面停止")  # 没在跑也写：刚开出来、还没拿到运行锁的进程要认（下次开跑前调度会清掉）
    queued = api.sched.cancel_queued()  # 排着还没开始的也停：一起记进「继续」
    # 「中止队列」（11-02）：整个序列都停，定时到点的也不开始，直到你点「继续」「不继续了」或手动开始
    api.rs.pause(HALT)
    from .. import settings as S
    close = bool(S.get(api.cfg, "scheduler").get("halt_close"))
    if close:  # 设置里勾了「中止队列时，关闭模拟器和游戏」：等它停下再关（原来的「让出电脑」）
        threading.Thread(target=close_all, args=(api.cfg, api.rs), daemon=True, name="halt-close").start()
    return {"ok": True, "running": bool(cur), "cancelled": queued, "closing": close}


@route("POST", "/api/running/skip")
def _(api, m, q, b):
    """运行条：「跳过当前任务」{scope: task}（停下它、记成今天跳过，接着跑这个游戏剩下的）；
    右键「跳过当前序列」{scope: game}（这个游戏这次剩下的都不跑；定时生成的那一条今天跳过）。"""
    from ..schedule import Schedule
    cur, gid = _current_game(api)
    if not gid:
        raise ValueError("现在没有在跑的任务")
    task = cur["current"].get("task", "")
    scope = "game" if b.get("scope") == "game" else "task"
    sch, day = Schedule(api.cfg), sched_day()
    if scope == "task":
        keys = {item_key(t): t for t in sch.game_tasks(gid, with_skipped=True)}
        key = task if task in keys else next((k for k, t in keys.items() if t["task"] == task), task)
        sch.set_skip_task(day, gid, key, True)
    else:
        bat = next((x for x in sch.day(day)["batches"] if x["id"] == cur.get("batch")), None)
        if bat and bat["kind"] == "rule":
            sch.set_skip(day, bat["id"], True)
    api.rs.request_skip(scope, gid, task)
    return {"ok": True, "scope": scope, "task": task}


@route("POST", "/api/continue")
def _(api, m, q, b):
    doc = api.rs.get_continue(api.cfg)
    if not doc:
        raise ValueError("没有可以继续的记录")
    out, skipped = [], []
    for x in doc["games"].values():
        try:
            out.append(api.enqueue(sched_day(), {"game": x["game"], "tasks": x["keys"], "routine": x.get("routine", ""),
                                                 "rerun": bool(x.get("rerun"))}))
        except ValueError as e:  # 这一批现在已经没有要跑的：说明原因，其余照样排
            skipped.append(str(e))
    api.rs.clear_continue()
    return {"ok": True, "batches": out, "skipped": skipped}


@route("DELETE", "/api/continue")
def _(api, m, q, b):
    api.rs.clear_continue()
    if (api.rs.paused() or {}).get("reason") == HALT:  # 不继续了 = 放弃剩下的，之后照常调度
        api.rs.resume()
        api.sched.wake()
    return {"ok": True}


@route("POST", r"/api/running/(pause|resume)")
def _(api, m, q, b):
    cur, cg = _current_game(api)
    if not cg:
        raise ValueError("现在没有正在运行的任务")
    ad, rs = api.adapter(cg), api.rs
    if not ad.can_suspend:
        raise ValueError(f"{api.game(cg)['name']} 不能暂停；请用「停止」，之后可以「继续」")
    want = m.group(1) == "pause"
    if bool(rs.suspended()) == want:
        return {"ok": True, "suspended": rs.suspended()}
    key = ad.press("suspend")  # 工具自己的暂停键：按一次暂停，再按一次继续
    rs.set_suspended({"since": now_bj(), "game": cg, "task": cur["current"]["task"], "hotkey": key} if want else None)
    return {"ok": True, "suspended": rs.suspended(), "hotkey": key,
            **({} if is_admin() else {"warning": "管家不是管理员身份，按键可能传不到游戏（游戏在前台时）。请用 GameButler.exe 启动管家。"})}


@route("POST", "/api/yield")
def _(api, m, q, b):
    threading.Thread(target=do_yield, args=(api.cfg, api.rs), daemon=True).start()
    return {"ok": True}


@route("POST", "/api/resume")
def _(api, m, q, b):
    api.rs.resume()
    api.sched.wake()
    return {"ok": True}
