"""排任务：某个游戏现在该跑哪些任务。自动调度和「开始」都只调用这里，运行进程照单执行，不再自己算。

输入：游戏、条目用哪套任务预设（空 = 今天各条里的任务，或点名的临时任务）、点名的任务（空 = 整套）、是不是你手动排的、要不要重跑今天做过的、
      批次上的再跑一轮。
输出：要跑的任务项（已排好顺序，需要时在最前面加上启动游戏的任务）、跳过的说明、下次可能有活干的时刻。

规则：
- 当天已经做完的不跑（批次勾了「今天做过的也再跑」除外）。
- 停用的任务不跑。
- 有运行时段的任务（游戏记录的 windows）：
    手动排的：不在时段内直接跳过，说明「任务 xx 的运行时段是 xx–xx，已跳过」；
    自动的：等下一个时段开始。时段全部过去还没做完的由 missed() 记成「错过时段」。
- 自动重复（任务预设上给单个任务设的接力 / 到点再跑，rounds.py）的轮次到点才跑；接力第一轮受跨天间隔限制。
- 读公告、读资源（read_extras）：整套跑时顺带加上，排在最前面（启动游戏之后）。
- 顺序：游戏记录的 run_order 固定先后、always_last 放最后；recovery_task（启动游戏）有任务要跑时放在最前面，
  只有 before_startup 列的任务排在它前面（例如恋与深空的读公告要在登录页做，做完停在登录页，再由启动任务进游戏）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import games as G
from . import rounds as R
from .store import DONE, Store, item_key
from .timeutil import game_day, window_instances, window_text


@dataclass
class Plan:
    game: str
    day: str
    items: list = field(default_factory=list)     # 交给运行进程的任务项（含启动任务）
    keys: list = field(default_factory=list)      # 要跑的任务键（不含启动任务）
    skipped: list = field(default_factory=list)   # 跳过的说明
    next: datetime | None = None                  # 还有没到点的任务时，最早什么时候到点
    why: str = ""                                 # 没有要跑的任务时的原因


def window_of(g: dict, t: dict) -> str:
    w = g.get("windows") or {}
    return w.get(item_key(t)) or w.get(t.get("_base", "")) or w.get(t["task"]) or ""


def resolve_named(store: Store, gid: str, named: list[str], first: list[dict] | None = None) -> list[dict]:
    """临时点名的任务：先在 first（今天各条里的任务）里找，再找第一套含有它的任务预设，都没有就用工具默认。"""
    pools = ([first] if first else []) + [r["tasks"] for r in store.routines(gid)["routines"].values()]
    out = []
    for n in named:
        hit = next((t for pool in pools for t in pool if item_key(t) == n), None) or \
            next((t for pool in pools for t in pool if t["task"] == n), None) or {"task": n, "choices": {}}
        if hit not in out:
            out.append(hit)
    return out


def source(cfg: dict, store: Store, gid: str, day, routine: str, named: list[str] | None = None) -> list[dict]:
    """条目的任务来源：
    - 某套任务预设：按它的任务和选项；
    - 没有任务预设、点了任务（临时勾的）：今天各条里有这个任务就用那一项的选项，否则用第一套含有它的任务预设里的，
      都没有就用工具默认（resolve_named）；
    - 没有任务预设、也没点任务（游戏页的「开始」）：今天各条里的任务。"""
    if routine:
        rs = store.routines(gid)["routines"]
        if routine not in rs:
            raise ValueError(f"没有这套任务预设：{routine}")
        return _apply_day(cfg, gid, day, rs[routine]["tasks"])
    from .schedule import Schedule
    today = Schedule(cfg).game_tasks(gid)
    return _apply_day(cfg, gid, day, resolve_named(store, gid, named, today) if named else today)


def _apply_day(cfg: dict, gid: str, day, tasks: list[dict]) -> list[dict]:
    """「仅今日」改过的选项（日程当天文件里的 choices）：只在今天生效，盖过任务预设里的。"""
    from .schedule import Schedule
    from .timeutil import sched_day
    g = cfg["games"].get(gid) or {}
    if not g or day != game_day(g):
        return tasks
    ov = Schedule(cfg).day_choices(sched_day(), gid)
    if not ov:
        return tasks
    return [{**t, "choices": ov[item_key(t)], "_today": True} if item_key(t) in ov else t for t in tasks]


def plan(cfg: dict, store: Store, gid: str, named: list[str] | None, *, manual: bool, rerun: bool = False,
         now: datetime, routine: str = "") -> Plan:
    g = cfg["games"][gid]
    ad = G.adapter(cfg, gid)
    day = game_day(g, now)
    out = Plan(game=gid, day=day.isoformat())
    src = source(cfg, store, gid, day, routine, named)
    st = store.status(gid, day)
    # 再跑一轮：批次上设的，对这个批次的任务生效
    again = R.preset_again(store, gid, routine)  # 任务预设上给单个任务设的「自动重复」
    rounds, gates = R.expand(g, [t for t in src if not named or item_key(t) in named], again or {}, st,
                             store.status(gid, day - timedelta(days=1)), day, g.get("recovery_task", ""))
    rec = g.get("recovery_task", "")
    extras = read_extras(cfg, gid)
    if not named:  # 整套跑的时候顺带读公告、读抽卡资源（当天做过的下面会跳过）
        # 11-02：读公告 / 读资源不再是预设里的任务，只按设置决定；预设里以前加过的不算
        src = [t for t in src if t["task"] not in INGAME_READS or t["task"] in extras]
        src = list(src) + [{"task": x, "choices": {}} for x in extras if not any(t["task"] == x for t in src)]
    cands = list(src) + rounds

    if named:
        picked = []
        for n in named:
            hit = [t for t in cands if item_key(t) == n or t.get("_base") == n] or \
                  [t for t in src if t["task"] == n]
            if not hit:
                if n not in ad.task_names():
                    out.skipped.append(f"{n}（这个工具里没有这个任务）")
                    continue
                hit = [{"task": n, "choices": {}}]
            for t in hit:
                if t in picked:
                    continue
                if t["task"] != rec and t["task"] not in ad.task_names():
                    out.skipped.append(f"{n}（这个工具里没有这个任务）")
                    continue
                picked.append(t)
        cands = picked

    nexts = []
    items = []
    from .schedule import Schedule
    from .timeutil import sched_day
    skip = set(Schedule(cfg).skip_tasks(sched_day(now), gid)) if day == game_day(g) else set()
    for t in cands:
        k = item_key(t)
        if t["task"] == rec:
            continue
        if (k in skip or t.get("_base") in skip) and not (named and k in named):  # 今天右键跳过的（点名要跑的照跑）
            out.skipped.append(f"{k}（今天跳过）")
            continue
        if st.get(k, {}).get("result") in DONE and not rerun:
            continue
        if t.get("_not_before") and (t["_not_before"] > now or not t.get("_ready", True)):
            nexts.append(t["_not_before"])
            continue
        if not ad.usable(t["task"]):
            out.skipped.append(f"{k}（已停用：{ad.disabled_reason(t['task'])}）")
            continue
        if k in gates and gates[k] > now:
            out.skipped.append(f"{k}（接力：{gates[k]:%m-%d %H:%M} 以后）")
            nexts.append(gates[k])
            continue
        spec = window_of(g, t)
        if spec:
            wins = window_instances(g, day, spec)
            if not any(a <= now < b for a, b in wins):
                if manual:
                    out.skipped.append(f"任务 {k} 的运行时段是 {window_text(spec)}，已跳过")
                else:
                    later = [a for a, _ in wins if a > now]
                    if later:
                        nexts.append(min(later))
                continue
        items.append(t)

    pools = [src] + [r["tasks"] for r in store.routines(gid)["routines"].values()]
    rec_item = next((t for pool in pools for t in pool if t["task"] == rec), {"task": rec, "choices": {}})  # 启动任务的选项（例如选服）

    if named and rec in named and not items:  # 只点了启动游戏
        items = [rec_item]
        out.items = R.strip(items)
        out.keys = [rec]
        return out

    order = g.get("run_order") or []
    if order:  # 固定先后（例如崩铁：清体力在每日实训之前），没列出的任务保持原来的位置
        pos = {n: i for i, n in enumerate(order)}
        slots = [i for i, t in enumerate(items) if t["task"] in pos]
        ranked = sorted((items[i] for i in slots), key=lambda t: pos[t["task"]])
        for i, t in zip(slots, ranked):
            items[i] = t
    last = g.get("always_last") or []
    items = [t for t in items if t["task"] not in last] + [t for t in items if t["task"] in last]
    # 读公告、读资源放在最前面（启动游戏之后；要在登录页读的由下面 before_startup 再挪到启动前）
    items = [t for t in items if t["task"] in extras] + [t for t in items if t["task"] not in extras]

    pre = g.get("before_startup") or []
    items = [t for t in items if t["task"] in pre] + [t for t in items if t["task"] not in pre]
    out.keys = [item_key(t) for t in items]
    if rec and any(t["task"] not in pre for t in items):
        k = sum(1 for t in items if t["task"] in pre)
        items = items[:k] + [rec_item] + items[k:]
    out.items = R.strip(items)
    out.next = min(nexts) if nexts else None
    if not out.keys:
        out.why = "；".join(out.skipped) or ("今天需要跑的都已完成" + ("，还有任务没到时间" if nexts else ""))
    return out


INGAME_READS = (G.NOTICE_TASK, G.EVENTS_TASK, G.GACHA_TASK)


def read_extras(cfg: dict, gid: str) -> list[str]:
    """这个游戏跑日常时顺带做的（11-02 起都在设置里定，不在任务预设里）：
    - 读游戏内公告（给活动日历）：只在设置「站外来源都读不到时，进游戏读」打开、且这个游戏的站外来源上一次全没读到时；
    - 读抽卡资源（给总览和资源曲线）：设置里每个游戏的开关（游戏记录 read_gacha）。"""
    from . import settings as S
    from .news import offsite_down
    g = cfg["games"][gid]
    out = []
    if g.get("notice_reader") and S.get(cfg, "news").get("ingame_fallback") and offsite_down(cfg, gid)[0]:
        out.append(G.NOTICE_TASK)
        if g.get("events_reader"):  # 和读公告一起开关
            out.append(G.EVENTS_TASK)
    if g.get("gacha_reader") and g.get("read_gacha", True):
        out.append(G.GACHA_TASK)
    return out


def today_tasks(cfg: dict, gid: str) -> list[dict]:
    from .schedule import Schedule
    return Schedule(cfg).game_tasks(gid)


def missed(cfg: dict, store: Store, gid: str, now: datetime) -> list[str]:
    """今天各条里有时段、时段已经全部过去、一次都没跑过的任务键。"""
    g = cfg["games"][gid]
    ad = G.adapter(cfg, gid)
    day = game_day(g, now)
    st = store.status(gid, day)
    out = []
    for t in today_tasks(cfg, gid):
        spec = window_of(g, t)
        k = item_key(t)
        if not spec or not ad.usable(t["task"]) or k in st:  # 跑过的（成功、失败都算）不改记录
            continue
        wins = window_instances(g, day, spec)
        if wins and all(b <= now for _, b in wins):
            out.append(k)
    return out


def next_window_end(cfg: dict, store: Store, gid: str, now: datetime) -> datetime | None:
    """今天还没结束的任务时段里，最早在什么时候结束（调度在那时醒来记「错过时段」）。"""
    g = cfg["games"][gid]
    day = game_day(g, now)
    ends = []
    for t in today_tasks(cfg, gid):
        spec = window_of(g, t)
        if spec:
            ends += [b for _, b in window_instances(g, day, spec) if b > now]
    return min(ends) if ends else None
