"""游戏：挂载 / 恢复 / 删除、检查工具、任务与选项、任务开关、任务预设（和它的定时）、今天的进度、运行记录、报告、
高级设置、工具自己的设置（写回 / 同步 / 配置组 / 打开界面）、电脑游戏分辨率。"""
from __future__ import annotations

import re
from datetime import date

from .. import gamesdb as GD
from .. import mount as MT
from .. import report
from ..store import item_key
from ..timeutil import game_day
from . import route


def check_inputs(schema: dict, tasks: list[dict]):
    """保存计划 / 任务预设前检查要填的值：工具给了格式规则（例如只能填数字）的，不合规则就不让存。
    规则本身写错的不检查（界面上已经提示「这个选项的格式规则有误」）。"""
    opts = schema.get("options", {})
    bad = []
    for t in tasks or []:
        for name, v in (t.get("choices") or {}).items():
            od = opts.get(name) or {}
            if od.get("type") != "input" or not isinstance(v, dict):
                continue
            for inp in od.get("inputs", []):
                rule, val = inp.get("verify"), v.get(inp.get("name"))
                if not rule or val is None:
                    continue
                try:
                    ok = re.search(rule, str(val)) is not None
                except re.error:
                    continue
                if not ok:
                    msg = inp.get("pattern_msg") or ("要填数字" if rule == "^\\d+$" else f"格式要符合 {rule}")
                    bad.append(f"{item_key(t)}「{inp.get('label') or inp.get('name')}」填的是「{val}」：{msg}")
    if bad:
        raise ValueError("没有保存：" + "；".join(bad))


# ---------------------------------------------------------------- 挂载
@route("GET", "/api/games")
def _(api, m, q, b):
    from .. import tools as T
    return {"games": MT.listing(api.cfg), "needs_setup": T.needs_setup(api.cfg)}


@route("POST", "/api/games/detect")
def _(api, m, q, b):
    d = MT.detect(str(b.get("path", "")))
    if d["ok"]:
        same = MT.identify(api.cfg, d)
        if same:
            rec = GD.record(api.cfg, same)
            if rec.get("followed", True):
                return {"ok": False, "error": f"这个脚本已经挂着了：「{rec['name']}」在用它。要改设置请到「设置 → 工具与游戏」。"}
            d["restore"] = {"id": same, "name": rec["name"]}
        pr = GD.match_preset(d)
        if pr:
            d["preset"] = {"id": pr["id"], "name": pr["name"], "refresh": (pr.get("config") or {}).get("refresh", "")}
            # 批注 #171（11-03）：显示名字默认用游戏名（预设里的，例如「时空中的绘旅人」），不用工具自己的名字（「MaaSH」）
            d["name"] = (pr.get("config") or {}).get("name") or d.get("name", "")
    return d


@route("POST", "/api/games")
def _(api, m, q, b):
    r = MT.add(api.cfg, b)
    api.sched.wake()
    return {"ok": True, **r}


@route("PUT", r"/api/games/(\w+)")
def _(api, m, q, b):
    MT.update(api.cfg, m.group(1), b)
    api.sched.wake()
    return {"ok": True, "games": MT.listing(api.cfg)}


@route("POST", r"/api/games/(\w+)/follow")
def _(api, m, q, b):
    MT.follow(api.cfg, m.group(1), bool(b.get("on", True)))
    api.sched.wake()
    return {"ok": True, "games": MT.listing(api.cfg)}


@route("DELETE", r"/api/games/(\w+)")
def _(api, m, q, b):
    MT.delete(api.cfg, m.group(1))
    api.sched.wake()
    return {"ok": True, "games": MT.listing(api.cfg)}


@route("POST", r"/api/games/(\w+)/check")
def _(api, m, q, b):
    from .. import tools as T
    return T.check(api.cfg, m.group(1))


@route("POST", r"/api/games/(\w+)/scan")
def _(api, m, q, b):
    from .. import tools as T
    return {"found": T.scan(m.group(1), api.cfg)}


@route("GET", r"/api/games/(\w+)/advanced")
def _(api, m, q, b):
    from .. import advanced
    return advanced.view(api.cfg, m.group(1), api.adapter(m.group(1)).task_names())


@route("PUT", r"/api/games/(\w+)/advanced")
def _(api, m, q, b):
    from .. import advanced
    gid = m.group(1)
    r = advanced.update(api.cfg, gid, b, api.adapter(gid).task_names())
    api.sched.wake()
    return r


# ---------------------------------------------------------------- 任务、任务预设、计划
@route("GET", r"/api/schema/(\w+)")
def _(api, m, q, b):
    g = api.game(m.group(1))
    sc = api.adapter(m.group(1)).schema()
    if g.get("notice"):
        sc["notice"] = g["notice"]
    return sc


@route("POST", r"/api/tasks/(\w+)/(enable|disable)")
def _(api, m, q, b):
    ad = api.adapter(m.group(1))
    if b.get("task") not in ad.task_names():
        raise ValueError(f"没有这个任务：{b.get('task')}")
    ad.set_task_enabled(b["task"], m.group(2) == "enable", b.get("reason", ""))
    api.sched.wake()
    return {"ok": True}


def routines_view(api, gid: str) -> dict:
    """任务预设和挂在上面的定时。"""
    from ..schedule import Schedule, days_text, when_text
    api.store.ensure_routines(gid, api.adapter(gid).seed())
    doc = api.store.routines(gid)
    rules = [r for r in Schedule(api.cfg).rules() if r["game"] == gid]
    g = api.game(gid)
    for r in rules:
        r["text"] = f"{days_text(r['days'])} · {when_text(r['when'], g)}"
    return {**doc, "rules": rules}


@route("GET", r"/api/routines/(\w+)")
def _(api, m, q, b):
    return routines_view(api, m.group(1))


@route("PUT", r"/api/routines/(\w+)")
def _(api, m, q, b):
    """整份保存任务预设。renamed = {旧名: 新名}：定时跟着改名；删掉的任务预设，它的定时一起删。"""
    from ..schedule import Schedule
    gid = m.group(1)
    api.game(gid)
    schema = api.adapter(gid).schema()
    from .. import rounds as RD
    from ..store import item_key
    g = api.cfg["games"][gid]
    for r in (b.get("routines") or {}).values():
        check_inputs(schema, r.get("tasks"))
        if r.get("again"):  # 单个任务的「自动重复」
            r["again"] = RD.check_preset(g, r["again"], {item_key(t) for t in r.get("tasks") or []})
        else:
            r.pop("again", None)
    api.store.save_routines(gid, {"routines": b.get("routines") or {}})
    sch = Schedule(api.cfg)
    for old, new in (b.get("renamed") or {}).items():
        sch.routine_renamed(gid, old, new)
    gone = sch.routines_kept(gid, set((b.get("routines") or {}).keys()))
    api.sched.wake()
    return {"ok": True, "removed_rules": len(gone), **routines_view(api, gid)}


@route("GET", r"/api/today/(\w+)")
def _(api, m, q, b):
    """游戏页「今天的进度」：今天各条里有哪些任务、各自状态，和今天的条目。"""
    from ..schedule import Schedule
    from ..timeutil import sched_day
    gid = m.group(1)
    g = api.game(gid)
    sch = Schedule(api.cfg)
    doc = sch.day(sched_day())
    items = [{"id": x["id"], "kind": x["kind"], "routine": x.get("routine", ""), "tasks": x.get("tasks", []),
              "when": x["when"], "skipped": x["id"] in doc["skip"], "ran": doc["ran"].get(x["id"], "")}
             for x in doc["batches"] if x["game"] == gid]
    # 11-04：今天跳过的条目（「跳过当前序列」）里的任务也列出来，标成「今天跳过」；不然列表是空的，同步、改选项都找不到它们
    alive = {item_key(t) for t in sch.game_tasks(gid)}
    tasks = sch.game_tasks(gid, with_skipped=True)
    return {"day": game_day(g).isoformat(), "tasks": tasks, "status": api.store.status(gid, game_day(g)),
            "items": items, "today_choices": sch.day_choices(sched_day(), gid),
            "skip_tasks": sch.skip_tasks(sched_day(), gid),
            "batch_skipped": [item_key(t) for t in tasks if item_key(t) not in alive]}


@route("POST", r"/api/today/(\w+)/mark-done")
def _(api, m, q, b):
    """把没做成的任务手动标成已完成（10-31）：{keys: [...]}。今天不再算失败，也不再自动重跑。"""
    from ..store import DONE
    gid = m.group(1)
    g = api.game(gid)
    day = game_day(g)
    st = api.store.status(gid, day)
    keys = [str(k) for k in b.get("keys") or [] if str(k)]
    if not keys:
        raise ValueError("没选任务")
    from ..signals import clear_fuse
    clear_fuse(api.cfg, gid)  # 标成已完成 = 你处理过了：今天的熔断也解除（11-02）
    from ..schedule import Schedule
    from ..timeutil import sched_day
    sch = Schedule(api.cfg)
    skipped = set(sch.skip_tasks(sched_day(), gid))
    for k in keys:  # 11-03：跳过了的任务标成已完成：不再显示「跳过」
        if k in skipped:
            sch.set_skip_task(sched_day(), gid, k, False)
    api.store.record(gid, day, [{"task": k, "result": "succeeded", "attempts": 0, "minutes": 0,
                                 "detail": "手动标记为已完成" + (f"（原来：{st[k].get('detail') or st[k]['result']}）"
                                                          if st.get(k) and st[k].get("result") not in DONE else "")}
                                for k in keys])
    api.sched.wake()
    return {"ok": True, "status": api.store.status(gid, day)}


@route("POST", r"/api/today/(\w+)/skip")
def _(api, m, q, b):
    """「今日任务」右键「跳过此次」/「不跳过了」：{key, on}。正在跑的就是它：马上停下它，接着跑后面的。"""
    from ..schedule import Schedule
    from ..timeutil import sched_day
    gid = m.group(1)
    api.game(gid)
    key, on = str(b.get("key") or ""), bool(b.get("on", True))
    sch = Schedule(api.cfg)
    if key not in {item_key(t) for t in sch.game_tasks(gid, with_skipped=True)}:
        raise ValueError("今天没有这个任务")
    sch.set_skip_task(sched_day(), gid, key, on)
    cur = ((api.rs.current() or {}).get("current") or {})
    if on and cur.get("game") == gid and key in (cur.get("task"), item_key({"task": cur.get("task", "")})):
        api.rs.request_skip("task", gid, cur.get("task", ""))
    api.sched.wake()
    return {"ok": True, "skip_tasks": sch.skip_tasks(sched_day(), gid)}


@route("PUT", r"/api/today/(\w+)/choices")
def _(api, m, q, b):
    """游戏页「今日任务」里改了选项、选「仅今日」：{choices: {任务键: 选项 | null}}，只在今天生效。"""
    from ..schedule import Schedule
    from ..store import item_key
    from ..timeutil import sched_day
    gid = m.group(1)
    api.game(gid)
    sch = Schedule(api.cfg)
    patch = b.get("choices") or {}
    known = {item_key(t): t for t in sch.game_tasks(gid, with_skipped=True)}
    bad = [k for k in patch if k not in known]
    if bad:
        raise ValueError("今天没有这些任务：" + "、".join(bad))
    check_inputs(api.adapter(gid).schema(), [{**known[k], "choices": v} for k, v in patch.items() if v is not None])
    sch.set_day_choices(sched_day(), gid, patch)
    api.sched.wake()
    return {"ok": True, "today_choices": sch.day_choices(sched_day(), gid)}


# ---------------------------------------------------------------- 运行记录、报告
@route("GET", r"/api/runs/(\w+)")
def _(api, m, q, b):
    g = api.game(m.group(1))
    day = date.fromisoformat(q["day"][0]) if q.get("day") else game_day(g)
    return {"game": m.group(1), "day": day.isoformat(), "runs": report.list_runs(api.cfg, m.group(1), day)}


@route("GET", r"/api/report/([\w-]+)")
def _(api, m, q, b):
    return report.build(api.cfg, m.group(1))


# ---------------------------------------------------------------- 工具自己的设置（不支持的工具会说明原因）
def _today_tasks(api, gid: str) -> list[dict]:
    """今天要跑的（11-03）：今天各条里的任务，盖上「仅今日」改过的选项，去掉今天右键跳过的。"""
    from ..planner import _apply_day
    from ..schedule import Schedule
    from ..timeutil import sched_day
    sch = Schedule(api.cfg)
    g = api.game(gid)
    skip = set(sch.skip_tasks(sched_day(), gid))
    tasks = _apply_day(api.cfg, gid, game_day(g), sch.game_tasks(gid))
    return [t for t in tasks if item_key(t) not in skip and t.get("_base") not in skip]


@route("POST", r"/api/bettergi/(\w+)/sync")
def _(api, m, q, b):  # 两边不一样时选「以管家为准」；今日任务的「同步到 BetterGI」：写的都是今天要跑的（含仅今日的选项）
    gid = m.group(1)
    api.game(gid)
    return api.adapter(gid).sync_plan(_today_tasks(api, gid), force=True)


@route("POST", r"/api/today/(\w+)/import-tool")
def _(api, m, q, b):
    """今日任务「从 BetterGI 同步（仅今日）」（11-03）：今天按工具一条龙现在的设置跑，任务预设不动。
    - 今天的任务里、工具也启用了的：今天的选项改成「跟工具」（空选择 = 运行时沿用工具里的值）
    - 工具没启用的：今天跳过（工具之前的事，例如胡桃签到，不动）
    - 工具启用了、今天的任务里没有的：只说明，不自动加（要跑就「添加任务」）"""
    from ..schedule import Schedule
    from ..timeutil import sched_day
    gid = m.group(1)
    g = api.game(gid)
    ad = api.adapter(gid)
    if not hasattr(ad, "enabled_items"):
        raise ValueError("这个游戏的工具不能同步（只有 BetterGI 这类自带一条龙的工具可以）")
    tool = ad.import_items()
    names = [t["task"] for t in tool]
    pre = set(getattr(ad, "pre_tasks", dict)() or {})
    rec = g.get("recovery_task", "")
    sch, day = Schedule(api.cfg), sched_day()
    doc = sch.day(day)
    for x in doc["batches"]:  # 上次同步加的、还没开始跑的：先去掉，下面按工具现在的设置重新算（不重复加）
        if x["game"] == gid and x["kind"] == "once" and x.get("label") == SYNC_LABEL and x["id"] not in doc["ran"]:
            sch.remove_once(day, x["id"])
    skip = set(sch.skip_tasks(day, gid))
    patch, now_skip, now_run, have = {}, [], [], set()
    for t in sch.game_tasks(gid, with_skipped=True):
        k = item_key(t)
        have.add(t["task"])
        if t["task"] == rec or t["task"] in pre:
            continue
        if t["task"] in names:
            patch[k] = {}
            if k in skip:
                sch.set_skip_task(day, gid, k, False)
                now_run.append(k)
        elif k not in skip:
            sch.set_skip_task(day, gid, k, True)
            now_skip.append(k)
    if patch:
        sch.set_day_choices(day, gid, patch)
    if hasattr(ad, "mark_synced"):
        ad.mark_synced()
    from ..bettergi import FINISH
    missing = [n for n in names if n not in have and n not in pre and n != FINISH]
    added = _today_extra(api, gid, missing)
    api.sched.wake()
    parts = [f"{len(patch)} 项的选项今天跟 BetterGI"]
    if now_skip:
        parts.append(f"今天跳过（BetterGI 没启用）：{'、'.join(now_skip)}")
    if now_run:
        parts.append(f"不再跳过：{'、'.join(now_run)}")
    if added:
        parts.append(f"加进今天：{'、'.join(missing)}（{added}）")
    return {"ok": True, "msg": "；".join(parts), "skipped": now_skip, "added": missing}


SYNC_LABEL = "从 BetterGI 同步（仅今日）"


def _today_extra(api, gid: str, keys: list[str]) -> str:
    """「从 BetterGI 同步（仅今日）」：工具里启用了、今天各条里没有的任务，加一条今天的一次性条目（11-04）。
    跟这个游戏今天定时那条同样的开始条件（例如闲时），排在它后面；没有定时就加入队列。再同步一次换掉上次加的那条，不重复加。
    返回说明（空 = 没加）。"""
    from ..schedule import Schedule
    from ..timeutil import sched_day
    sch, day = Schedule(api.cfg), sched_day()
    if not keys:
        return ""
    doc = sch.day(day)
    rule = next((x for x in doc["batches"] if x["game"] == gid and x["kind"] == "rule"), None)
    w = dict(rule["when"]) if rule else {"kind": "queue"}
    if w.get("kind") not in ("queue", "at", "idle"):
        w = {"kind": "queue"}  # 「刷新后马上」一次性条目没有：按加入队列
    try:
        b = sch.add_once(day, {"game": gid, "tasks": keys, "when": w, "label": SYNC_LABEL})
    except ValueError:  # 例如还没设置什么算闲时：按加入队列
        w = {"kind": "queue"}
        b = sch.add_once(day, {"game": gid, "tasks": keys, "when": w, "label": SYNC_LABEL})
    ids = [y["id"] for y in sch.day(day)["batches"]]
    if rule and rule["id"] in ids:  # 排在定时那条后面
        rest = [i for i in ids if i != b["id"]]
        k = rest.index(rule["id"]) + 1
        sch.set_order(day, rest[:k] + [b["id"]] + rest[k:])
    from ..schedule import when_text
    return f"今天{'跟定时一起' if rule else '加入队列'}跑：{when_text(w, api.game(gid))}"


@route("PUT", r"/api/bettergi/(\w+)/group")
def _(api, m, q, b):  # 配置组里单条脚本的开关和顺序
    return api.adapter(m.group(1)).write_group(str(b.get("group", "")), b.get("projects") or [])


@route("POST", r"/api/import/(\w+)")
def _(api, m, q, b):  # 从工具同步：用它当前的设置覆盖一套任务预设（界面上正在看的那套，没有就叫「日常」）
    gid = m.group(1)
    ad = api.adapter(gid)
    items = ad.import_items()
    doc = api.store.routines(gid)
    name = str(b.get("routine") or "").strip() or next(iter(doc["routines"]), "") or "日常"
    doc["routines"][name] = {"tasks": items}
    api.store.save_routines(gid, doc)
    ad.mark_synced()
    return {"ok": True, "routine": name, "routines": routines_view(api, gid)}


@route("POST", r"/api/open/(\w+)")
def _(api, m, q, b):  # 打开工具自己的界面（例如去 BetterGI 布置配置组）；{updater: true} 有自带更新程序的开更新程序
    ad = api.adapter(m.group(1))
    up = bool((b or {}).get("updater")) and bool(getattr(ad, "updater_exe", lambda: "")())
    ad.open_gui(updater=True) if up else ad.open_gui()
    return {"ok": True, "updater": up}


@route("POST", r"/api/launch/(\w+)")
def _(api, m, q, b):  # 只开模拟器和游戏，不跑任务（游戏页「用模拟器启动游戏」）
    return {"ok": True, "msg": api.adapter(m.group(1)).launch_game()}


@route("GET", "/api/pcres")
def _(api, m, q, b):  # 电脑游戏分辨率：当前设置、开关、有没有待恢复的备份、屏幕大小
    from .. import pcres
    out = {gid: {**pcres.describe(gid), "enabled": pcres.enabled(api.cfg, gid), "name": api.cfg["games"][gid]["name"],
                 "pending_restore": pcres.pending_restore(api.cfg, gid)}
           for gid in api.cfg["games"] if pcres.supported(gid)}
    return {"games": out, "screen": pcres.screen_size()}


@route("POST", r"/api/pcres/(\w+)/restore")
def _(api, m, q, b):
    from .. import pcres
    return {"ok": True, "msg": pcres.restore(api.cfg, m.group(1))}


@route("POST", r"/api/games/(\w+)/refetch-banners")
def _(api, m, q, b):
    """活动页轮播右键「重新获取题图」（11-01）：模拟器临时调高分辨率（游戏「高级」里选），只跑「读游戏内公告」，读完改回。"""
    from .. import games as G
    from ..timeutil import sched_day
    gid = m.group(1)
    g = api.game(gid)
    if not g.get("notice_reader"):
        raise ValueError(f"{g['name']}的题图不是从游戏内公告读的，不用重新获取")
    res = str(g.get("notice_resolution") or "1920x1080")
    tasks = [G.NOTICE_TASK] + ([G.EVENTS_TASK] if g.get("events_reader") else [])  # 时绘：再进游戏读活动中心的大图
    bt = api.enqueue(sched_day(), {"game": gid, "tasks": tasks, "when": {"kind": "now"}, "rerun": True,
                                    "label": "重新获取题图", "hires": res})
    return {"ok": True, "batch": bt, "resolution": res}


# ---------------------------------------------------------------- 导入工具自带的预设（11-02：挂上以后也能导入）
@route("GET", r"/api/games/(\w+)/tool-routines")
def _(api, m, q, b):
    gid = m.group(1)
    api.game(gid)
    have = set(api.store.routines(gid)["routines"])
    ad = api.adapter(gid)
    tr = ad.tool_routines() if hasattr(ad, "tool_routines") else {}
    return {"routines": [{"name": k, "count": len(v), "exists": k in have} for k, v in tr.items()]}


@route("POST", r"/api/games/(\w+)/import-routines")
def _(api, m, q, b):
    from .. import mount as MT
    gid = m.group(1)
    api.game(gid)
    names = b.get("names")
    got = MT.import_routines(api.cfg, gid, [str(x) for x in names] if isinstance(names, list) else None, str(b.get("as") or ""))
    api.sched.wake()
    return {"ok": True, "imported": got}
