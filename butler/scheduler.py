"""自动调度：管家开着时，在「下一个该做事的时刻」醒来看一眼（不是固定每分钟轮询）。

每次醒来（tick）：
1. 有运行时段的任务，时段全部过去还没做完 → 记「错过时段」并推送。
2. 按今天日程的顺序看每个批次（schedule.py）：到没到点、要不要等闲时、该跑哪些任务（planner.py 算）。
3. 找到第一个可以跑的批次就开跑；同一模拟器上紧挨着、也已就绪的整份计划批次一起跑。
   要跑的任务在这里算好写进请求文件，运行进程照单执行。

规则（时间一律北京时间）：
- 「立即」批次：你手动排的，自动调度关着也跑；只跑一次；不受补跑次数限制。
- 定时（任务预设上的）和到点 / 闲时的一次性条目：自动调度开着才跑；脚本熔断过的游戏当天不再自动跑；
  失败的任务当天最多再补跑 fail_retries 次，两次至少隔 retry_gap_minutes 分钟（设置 → 调度）。
- 闲时：idle.py（用户自己搭的条件组，没有默认）。
- 电脑端游戏（要占前台）：屏幕锁着时不开始（脚本看不到窗口），等解锁；到点（不是闲时）时你在用电脑 → 先提醒
  （启动器的提醒卡片和网页都能回答）：现在开始 / 推迟 postpone_minutes 分钟 / 今天跳过这一批；没人回答照样开始。
- 「让出电脑」时什么都不开始（你手动排的「立即」批次也等恢复调度，10-26 定）。同一时间只跑一次。

睡眠：电脑睡着时什么都不跑。设置里开了「叫醒电脑」时，每次醒来把下一个到点时刻交给 wake.py（Windows 计划任务）；
有要跑的时让电脑保持醒着直到跑完（keep_awake，不改电源设置）。

状态：data/scheduler/state.json（按游戏日记每个任务自动跑了几次、上次自动运行时间、推迟到什么时候）、
      data/scheduler/log.jsonl（调度记录）。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

from . import games as G
from . import jsonio
from . import planner as P
from . import settings as S
from .launch import spawn_run
from .runstate import RunState, now_bj
from . import idle as IDLE
from . import wake as WAKE
from .schedule import Schedule, window_bounds
from .store import Store
from .timeutil import BJ, game_day, parse_hm, sched_day

MAX_SLEEP = 5 * 60         # 没事做时最多睡多久（电脑从睡眠醒来后，最多这么久就会重新看一遍）
RUNNING_CHECK = 180        # 正在跑：多久看一次跑完没有
ASK_IF_USED_S = 10 * 60    # 电脑游戏到点（不是闲时的）：这么久之内碰过键鼠，算你在用电脑，先问一声


# 电脑游戏（BetterGI 等）跑的时候会模拟键鼠，Windows 把它当成有人在用电脑。跑完以后按「这次运行开始前已经闲了多久
# + 运行用掉的时间」算，不用重新等满闲时（11-01：原神 18:25 跑完，又白等 30 分钟）。跑完之后有真的操作就照常算。
OWN_INPUT: dict = {}  # {"pre": 开跑时的空闲秒数, "t0": 开跑时刻, "t1": 跑完时刻}（time.time()）


def idle_seconds() -> float | None:
    """距离最后一次「你的」键盘 / 鼠标操作过了多少秒（电脑游戏运行期间脚本模拟的操作不算）。"""
    raw = raw_idle_seconds()
    o = OWN_INPUT
    if raw is None or not o.get("t0"):
        return raw
    import time
    now = time.time()
    if o.get("t1") is None:  # 还在跑：期间的操作都当成脚本的
        return (o.get("pre") or 0) + (now - o["t0"])
    if raw < now - o["t1"] - 3:  # 跑完之后又有操作：是你在用电脑
        return raw
    return max(raw, (o.get("pre") or 0) + (now - o["t0"]))


def raw_idle_seconds() -> float | None:
    """距离最后一次键盘 / 鼠标操作过了多少秒（只在 Windows 上有；别的系统返回 None = 当作一直空闲）。"""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    li = LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(li)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        raise OSError("读不到键鼠空闲时间（GetLastInputInfo 失败）")
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0


def is_pc_game(g: dict) -> bool:
    """要占电脑前台的游戏：挂载时定了 pc 的按它，否则不是模拟器上跑的都算。"""
    if "pc" in g:
        return bool(g["pc"])
    return not G.type_class(g).uses_emulator(g)


def forget_state(cfg: dict, gid: str):
    """彻底删除：调度状态里这个游戏的条目。"""
    p = Path(cfg["machine"]["data_dir"]) / "scheduler" / "state.json"
    if p.exists():
        jsonio.update(p, {}, lambda d: d.pop(gid, None) and None)


class Scheduler:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.data = Path(cfg["machine"]["data_dir"])
        self.dir = self.data / "scheduler"
        self.store = Store(str(self.data))
        self.rs = RunState(str(self.data))
        self.lock = threading.RLock()        # tick / 回答提醒 / 开始 互斥
        self.prompt: dict | None = None      # 正在等你回答的提醒
        self.events: list[dict] = []         # 最近的调度记录（给界面看）
        self.last_tick = ""
        self.next_check = ""
        self.batch_info: list[dict] = []
        self.child = None                    # 自己开的运行进程（刚开出来、还没拿到运行锁时也算在跑）
        self._stop = threading.Event()
        self._wake = threading.Event()

    def wake(self):
        """计划 / 日程 / 开关变了：马上重新算。"""
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    # ---------- 状态 ----------
    def enabled(self) -> bool:
        return S.get(self.cfg, "scheduler")["enabled"]

    def set_enabled(self, on: bool):
        S.update(self.cfg, "scheduler", {"enabled": bool(on)})
        self.log(f"自动调度已{'开启' if on else '关闭'}")
        self.wake()

    def game_state(self, gid: str) -> dict:
        day = game_day(self.cfg["games"][gid]).isoformat()
        gs = jsonio.read(self.dir / "state.json", {}).get(gid) or {}
        if gs.get("day") != day:  # 新的游戏日：清零
            gs = {"day": day, "attempts": {}, "last_run": "", "postponed_until": ""}
        return gs

    def _save_game_state(self, gid: str, fn):
        def upd(doc):
            gs = doc.get(gid) or {}
            day = game_day(self.cfg["games"][gid]).isoformat()
            if gs.get("day") != day:
                gs = {"day": day, "attempts": {}, "last_run": "", "postponed_until": ""}
            fn(gs)
            doc[gid] = gs
        jsonio.update(self.dir / "state.json", {}, upd)

    def log(self, msg: str, game: str = ""):
        ev = {"time": now_bj(), "game": game, "msg": msg}
        with self.lock:
            self.events = (self.events + [ev])[-50:]
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    # ---------- 判断一个批次 ----------
    def evaluate(self, b: dict, doc: dict, now: datetime) -> dict:
        """一个批次现在的情况：{plan: P.Plan|None, why, next: datetime|None, wait_idle: bool}。"""
        gid = b["game"]
        g = self.cfg["games"][gid]
        row = {"plan": None, "why": "", "next": None, "wait_idle": False}
        ok, why = G.available(g)
        if not ok:
            return {**row, "why": f"工具没接好：{why}"}
        if not b["enabled"]:
            return {**row, "why": "定时已关"}
        if b["id"] in doc["skip"]:
            return {**row, "why": "今天跳过"}
        manual = b["start"]["mode"] == "now"
        day = game_day(g, now)
        if manual:
            if b["id"] in doc["ran"]:
                note = doc.get("ran_why", {}).get(b["id"])
                return {**row, "why": note or f"已在 {doc['ran'][b['id']][11:16]} 开始跑过"}
        else:
            if not self.enabled():
                return {**row, "why": "自动调度关着（「现在」的照跑）"}
            st, en = window_bounds(g, b, day)
            if now < st:
                return {**row, "why": f"{st:%H:%M} 开始", "next": st}
            if now >= en:
                return {**row, "final": True, "why": f"今天的时段 {b['start']['from']}–{b['start']['to'] or '刷新'} 已过（北京时间）"}
            from .signals import fused
            fz = fused(self.cfg, gid, day)
            if fz:
                return {**row, "final": True, "why": f"今天已熔断：{fz}，不再自动运行"}
            gs = self.game_state(gid)
            if gs["postponed_until"] and now.strftime("%Y-%m-%d %H:%M") < gs["postponed_until"]:
                until = datetime.strptime(gs["postponed_until"], "%Y-%m-%d %H:%M").replace(tzinfo=BJ)
                return {**row, "why": f"推迟到 {gs['postponed_until'][11:]}", "next": until}
        p = P.plan(self.cfg, self.store, gid, b["tasks"] or None, manual=manual, rerun=bool(b.get("rerun")), now=now,
                   routine=b.get("routine", ""), wait=bool(b["start"].get("queue")))
        row.update(plan=p, next=p.next)
        if not p.keys:
            return {**row, "why": p.why}
        if not manual:  # 自动补跑的上限和间隔
            sset = S.get(self.cfg, "scheduler")
            gs = self.game_state(gid)
            maxn = 1 + int(sset["fail_retries"])
            keys = [k for k in p.keys if gs["attempts"].get(k, 0) < maxn]
            if not keys:
                return {**row, "plan": None, "final": True, "why": "今天这一轮跑完了，没做成的等你处理（调度设置里可以设「失败后自动补跑」）"
                        if maxn == 1 else f"没做成的已自动重试到上限（共试了 {maxn} 次都没成），不再自动跑；没有算成完成，等你处理：右键可重跑或标为已完成"}
            if gs["last_run"] and any(gs["attempts"].get(k) for k in keys):
                last = datetime.strptime(gs["last_run"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ)
                gap = timedelta(minutes=int(sset["retry_gap_minutes"]))
                fresh = [k for k in keys if not gs["attempts"].get(k)]
                if now - last < gap and not fresh:
                    return {**row, "plan": None, "why": f"上次自动运行在 {gs['last_run'][11:16]}，{gap.seconds // 60} 分钟内不补跑",
                            "next": last + gap}
                if now - last < gap:
                    keys = fresh
            if keys != p.keys:
                drop = set(p.keys) - set(keys)
                p.items = [t for t in p.items if (t.get("key") or t["task"]) not in drop]
                p.keys = keys
            row["wait_idle"] = b["start"]["idle"]
        return row

    def idle_ok(self, now: datetime) -> tuple[bool, float, str]:
        """闲时判定（idle.py）：(是不是闲时, 大约还要等几秒, 差什么)。"""
        st = IDLE.status(self.cfg, now, idle_seconds())
        if st["ok"]:
            return True, 0, ""
        return False, st["wait_s"] or MAX_SLEEP, st["why"]

    # ---------- 主循环 ----------
    def tick(self) -> float:
        """看一眼现在该做什么；返回下次该醒来的秒数。"""
        with self.lock:
            now = datetime.now(BJ)
            self.last_tick = now_bj()
            waits = [MAX_SLEEP]
            wake_at: list = []
            self._mark_missed(now, waits)
            doc = Schedule(self.cfg).day(sched_day(now))
            rows, ready = [], []
            ahead = False  # 排在前面的还有没轮完的（「加入队列」的条目要等它们）
            for b in doc["batches"]:
                try:
                    r = self.evaluate(b, doc, now)
                except Exception as e:  # 一个批次算不出来不影响别的批次：原因显示在这个批次上
                    r = {"plan": None, "why": f"出错：{type(e).__name__}: {e}", "next": None, "wait_idle": False}
                    self.log(f"批次出错：{type(e).__name__}: {e}", b["game"])
                if b["start"]["mode"] == "now" and r["plan"] and not r["plan"].keys and not r["plan"].next and b["id"] not in doc["ran"]:
                    # （11-06：还在等今天的运行时段开的「加入队列」不算用掉）
                    # 「立即」批次到开始时已经没有要跑的：这一批就算用掉了，原因记在批次上
                    Schedule(self.cfg).mark_ran(sched_day(now), b["id"], r["why"])
                    self.log(f"没有要跑的：{r['why']}", b["game"])
                    r = {**r, "plan": None, "next": None}
                alive = bool(r["plan"] and r["plan"].keys) or bool(r["next"])
                if b["start"].get("queue") and ahead and alive:
                    # 11-03：「加入队列」本来要等前面的轮完；但里面只在某个时段跑、而且时段正开着的任务不等
                    # （时绘「领体力 · 午间」12:00–15:00 排在闲时的日常后面，等日常跑完时段可能已经过了）——只先跑这几项，其余照旧排队
                    urgent = self._open_window_items(b, r["plan"], now) if r["plan"] else []
                    if urgent:
                        r["plan"].items = [t for t in r["plan"].items if t["task"] == self.cfg["games"][b["game"]].get("recovery_task", "")
                                           or t in urgent]
                        r["plan"].keys = [k for k in r["plan"].keys if k in {self._key(t) for t in urgent}]
                        r = {**r, "why": "到了它的运行时段：先跑这几项，不等前面的"}
                    else:
                        r = {**r, "plan": None, "why": "排队中：等前面的轮完"}
                ahead = ahead or alive
                if r["plan"] and r["plan"].keys and r["wait_idle"]:
                    ok, w, why = self.idle_ok(now)
                    if not ok:
                        r = {**r, "why": why}
                        waits.append(w)
                        wake_at.append(IDLE.next_time_start(self.cfg, now))
                        r["plan"] = None
                if r["plan"] and r["plan"].keys and is_pc_game(self.cfg["games"][b["game"]]) and WAKE.is_locked():
                    r = {**r, "plan": None, "why": "屏幕锁着：电脑游戏要解锁后才能跑（脚本看不到窗口）"}
                    waits.append(60)
                if r["next"] and not r["plan"]:
                    wake_at.append(r["next"])
                if r["next"]:
                    waits.append((r["next"] - now).total_seconds())
                rows.append({"id": b["id"], "game": b["game"], "due": r["plan"].keys if r["plan"] else [],
                             "why": r["why"], "next": r["next"].strftime("%Y-%m-%d %H:%M") if r["next"] else "",
                             "final": bool(r.get("final"))})  # 今天不会再自动跑了（这一轮跑完 / 时段已过 / 熔断）
                if r["plan"] and r["plan"].keys:
                    ready.append((b, r["plan"]))
            self.batch_info = rows
            self._power(now, ready, [w for w in wake_at if w])
            if self.rs.paused():  # 让出电脑：什么都不开始，等恢复调度（恢复时会马上重新算）
                for r in rows:
                    if r["due"]:
                        r["why"] = f"{self.rs.paused().get('reason') or '让出电脑'}中：恢复调度后开始"
                ready = []
                waits = [MAX_SLEEP]
            if self.rs.current() or (self.child is not None and self.child.poll() is None):
                self._maybe_yield(ready, now)
                return RUNNING_CHECK
            if self.prompt:  # 等你回答：到提醒超时再看
                return max(5.0, self._prompt_left(now))
            later = min(max(5.0, w) for w in waits)
            if not ready:
                return later
            ready = self.prioritize(ready, now)
            b, p = ready[0]
            g = self.cfg["games"][b["game"]]
            if is_pc_game(g):
                if b["start"]["mode"] == "window" and not b["start"]["idle"] and (idle_seconds() or 1e9) < ASK_IF_USED_S:
                    self.ask(b, p)
                    return max(5.0, self._prompt_left(now))
                self.start([(b, p)], "日程")
                return RUNNING_CHECK
            # 模拟器游戏：后面紧挨着的、也已就绪、在同一个模拟器上的整份计划批次一起跑（不用反复开关模拟器）
            group = [(b, p)]
            emu = G.emulator_of(g)
            if not b["tasks"] and not b.get("routine") and emu:
                for b2, p2 in ready[1:]:
                    g2 = self.cfg["games"][b2["game"]]
                    if b2["tasks"] or G.emulator_of(g2) != emu or any(x[0]["game"] == b2["game"] for x in group):
                        break
                    group.append((b2, p2))
            self.start(group, "日程")
            return RUNNING_CHECK

    def _maybe_yield(self, ready: list, now: datetime):
        """正在跑别的游戏、又有赶时段的任务能跑了（11-02）：让正在跑的做完手上这一项就停，剩下的放回「接下来」，
        先跑赶时段的。只对模拟器上的 MAA 类游戏有效（BetterGI 一条龙没法在两项之间停）。"""
        if not ready or self.rs.yield_req() or self.rs.stop_requested():
            return
        cur = self.rs.current() or {}
        cg = (cur.get("current") or {}).get("game") or (cur.get("games") or [""])[0]
        g = self.cfg["games"].get(cg)
        if not g or is_pc_game(g) or g.get("type") != "maa":
            return
        urgent = [(b, p) for b, p in ready if b["game"] != cg and self._window_end(b, p, now)]
        if not urgent:
            return
        b = min(urgent, key=lambda bp: self._window_end(*bp, now))[0]
        name = self.cfg["games"][b["game"]]["name"]
        self.rs.request_yield(f"{name}有只在某个时段跑的任务", b["game"])
        self.log(f"让出：{g['name']}做完手上这一项先停，先跑「{name}」赶时段的任务，剩下的稍后接着跑", cg)

    def _window_end(self, b: dict, p, now: datetime):
        """这一条里正在时段里的任务，最早哪个时刻截止（没有就 None）。"""
        from .planner import window_of
        from .timeutil import window_instances
        g = self.cfg["games"][b["game"]]
        day = game_day(g, now)
        ends = []
        for t in p.items:
            spec = window_of(g, t)
            if spec:
                try:
                    ends += [e for a, e in window_instances(g, day, spec) if a <= now < e]
                except Exception:
                    continue
        return min(ends) if ends else None

    @staticmethod
    def _key(t: dict) -> str:
        from .store import item_key
        return item_key(t)

    def _open_window_items(self, b: dict, plan, now: datetime) -> list:
        """这一批要跑的任务里，「只在某个时段跑」而且时段现在正开着的。"""
        from .planner import window_of
        from .timeutil import window_instances
        g = self.cfg["games"][b["game"]]
        day = game_day(g, now)
        out = []
        for t in plan.items:
            spec = window_of(g, t)
            try:
                if spec and any(a <= now < e for a, e in window_instances(g, day, spec)):
                    out.append(t)
            except Exception:
                continue
        return out

    def prioritize(self, ready: list, now: datetime) -> list:
        """几条同时能跑时谁先（11-01 定，默认就这样）：
        1. 里面有「只在某个时段跑」的任务、而且那个时段正开着的，先跑，时段先结束的更先（时绘午间 15:00 截止，别排在别人后面错过）；
           插到别人前面时只跑这几个赶时段的任务，这套预设剩下的照原来的顺序轮（11-01）；
        2. 补跑（这一条要跑的任务今天都已经自动跑过）排在第一次跑的后面；
        3. 其余照日程里的顺序。"""
        from .planner import window_of
        from .timeutil import window_instances

        from .store import item_key
        urgent: dict = {}

        def deadline(b, p):
            g = self.cfg["games"][b["game"]]
            day = game_day(g, now)
            ends = []
            for t in p.items:
                spec = window_of(g, t)
                if spec:
                    hit = [e for a, e in window_instances(g, day, spec) if a <= now < e]
                    if hit:
                        ends += hit
                        urgent.setdefault(b["id"], set()).add(item_key(t))
            return min(ends) if ends else None

        def retry(b, p):
            if b["start"]["mode"] != "window":  # 你手动加的（现在 / 加入队列 / 重跑失败项）不算补跑
                return False
            att = self.game_state(b["game"])["attempts"]
            return bool(p.keys) and all(att.get(k) for k in p.keys)

        keyed = []
        for i, (b, p) in enumerate(ready):
            try:
                dl = deadline(b, p)
            except Exception:  # 算不出时段：按没有时段处理
                dl = None
            keyed.append(((0, dl, 0, i) if dl else (1, now, 1 if retry(b, p) else 0, i), (b, p)))
        keyed.sort(key=lambda x: x[0])
        out = [bp for _, bp in keyed]
        if out[0][0]["id"] != ready[0][0]["id"] and keyed[0][0][0] == 0:
            b0, p0 = out[0]
            keep = urgent.get(b0["id"], set())
            rec = self.cfg["games"][b0["game"]].get("recovery_task", "")
            if keep and set(p0.keys) - keep:  # 只跑赶时段的这几项（加上启动游戏）
                p0.items = [t for t in p0.items if t["task"] == rec or item_key(t) in keep]
                p0.keys = [k for k in p0.keys if k in keep]
        if out[0][0]["id"] != ready[0][0]["id"]:
            self.log(f"先跑「{self.cfg['games'][out[0][0]['game']]['name']}」：" +
                     ("里面有快到截止的时段任务" if keyed[0][0][0] == 0 else "别的是补跑，排在第一次跑的后面"), out[0][0]["game"])
        return out

    def _power(self, now: datetime, ready: list, wake_at: list):
        """有要跑的：让电脑保持醒着（跑的时候运行进程自己也会）；下一个到点时刻交给 wake.py 叫醒电脑。"""
        soon = not self.rs.paused() and bool(ready or any((w - now).total_seconds() < 180 for w in wake_at))
        if soon != getattr(self, "_awake", None):
            from .main import keep_awake
            keep_awake(soon)
            self._awake = soon
        try:
            later = [w for w in wake_at if w > now + timedelta(minutes=3)]
            self.next_wake = WAKE.plan(self.cfg, min(later) if later and self.enabled() else None, self.log)
        except Exception as e:  # 叫醒设不上不影响调度
            self.log(f"设叫醒电脑出错：{type(e).__name__}: {e}")

    def _mark_missed(self, now: datetime, waits: list):
        """时段全部过去还没做完的任务记「错过时段」，有新记的就推送。"""
        hit = []
        cur = self.rs.current() or {}
        running = set(cur.get("games", []))  # 正在跑的游戏：等它跑完再看（它可能正在做这个任务）
        from .timeutil import window_text
        for gid, g in self.cfg["games"].items():
            if not G.available(g)[0] or gid in running:
                continue
            try:
                keys = P.missed(self.cfg, self.store, gid, now)
                if keys:
                    plan = {t.get("key") or t["task"]: t for t in P.today_tasks(self.cfg, gid)}
                    self.store.record(gid, game_day(g, now), [
                        {"task": k, "result": "missed", "detail": f"运行时段 {window_text(P.window_of(g, plan[k]))} 已过，没有做成",
                         "attempts": 0, "minutes": 0} for k in keys])
                    self.log(f"错过时段：{'、'.join(keys)}", gid)
                    hit.append(gid)
                end = P.next_window_end(self.cfg, self.store, gid, now)
                if end:
                    waits.append((end - now).total_seconds() + 1)
            except Exception as e:  # 一个游戏出错不影响别的游戏
                self.log(f"检查错过时段出错：{type(e).__name__}: {e}", gid)
        if hit:
            from .notify import after_run
            threading.Thread(target=after_run, args=(self.cfg, hit), daemon=True).start()

    def start(self, group: list[tuple[dict, P.Plan]], by: str):
        """开跑：记下自动运行次数，「立即」批次标成已跑，把算好的任务交给运行进程。"""
        sch = Schedule(self.cfg)
        day = sched_day()
        for b, p in group:
            for x in p.skipped:  # 这批里跳过的任务：记进调度记录（日程页能看到）
                self.log(f"跳过：{x}", b["game"])
            if b["start"]["mode"] == "now":
                sch.mark_ran(day, b["id"])
            else:
                def fn(gs, keys=p.keys):
                    for k in keys:
                        gs["attempts"][k] = gs["attempts"].get(k, 0) + 1
                    gs["last_run"] = now_bj()
                    gs["postponed_until"] = ""
                self._save_game_state(b["game"], fn)
        self.rs.clear_stop()  # 上次留下的停止标记（没在跑时点的停止）不能带到这次
        pc_run = any(is_pc_game(self.cfg["games"][b["game"]]) for b, _ in group)
        if pc_run:
            import time
            try:
                pre = raw_idle_seconds()
            except OSError:
                pre = None
            if pre is not None:
                OWN_INPUT.clear()
                OWN_INPUT.update(pre=pre, t0=time.time(), t1=None)
        self.child = spawn_run(self.cfg, [{"game": b["game"], "batch": b["id"], "routine": b.get("routine", ""), "items": p.items, "keys": p.keys,
                                         **({"hires": b["hires"]} if b.get("hires") else {})}
                                       for b, p in group], by)
        def waiter(c=self.child, pc=pc_run):
            c.wait()
            if pc and OWN_INPUT.get("t1", 0) is None:
                import time
                OWN_INPUT["t1"] = time.time()
            self.wake()  # 跑完马上看下一批
        threading.Thread(target=waiter, daemon=True).start()
        self.log("开始运行：" + "、".join(self.cfg["games"][b["game"]]["name"] for b, _ in group))

    def cancel_queued(self) -> list[str]:
        """你点了停止：今天排着、还没开始的「立即」批次也不再开始，记进「继续」（点继续时一起接着跑）。"""
        from .store import DONE
        with self.lock:
            sch = Schedule(self.cfg)
            day = sched_day()
            doc = sch.day(day)
            games, names = {}, []
            for b in doc["batches"]:  # 正在跑的那一批开始时已经标成跑过了
                if b["start"]["mode"] != "now" or b["id"] in doc["ran"] or b["id"] in doc["skip"]:
                    continue
                g = self.cfg["games"][b["game"]]
                st = self.store.status(b["game"], game_day(g))
                keys = [k for k in sch.batch_keys(b) if st.get(k, {}).get("result") not in DONE or b.get("rerun")]
                sch.mark_ran(day, b["id"], "已停止：你点了停止，这一批没有开始")
                if keys:
                    rt = b.get("routine", "")
                    games[b["game"] + (f"#{rt}" if rt else "")] = {"game": b["game"], "keys": keys,
                                                                 "game_day": game_day(g).isoformat(), "routine": rt,
                                                                 **({"rerun": True} if b.get("rerun") else {})}
                names.append(g["name"])
            if games:
                self.rs.save_continue({"stopped_at": now_bj(), "source": "界面停止", "games": games, "current": None})
            if names:
                self.log("停止：排着的也不开始了：" + "、".join(names))
            return names

    # ---------- 提醒 ----------
    def _prompt_left(self, now: datetime) -> float:
        asked = datetime.strptime(self.prompt["asked_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ)
        return self.prompt["timeout_s"] + 2 - (now - asked).total_seconds()

    def ask(self, b: dict, p: P.Plan):
        """你在用电脑时，电脑端游戏开跑前先问一声（启动器的提醒卡片和网页都能回答）。"""
        g = self.cfg["games"][b["game"]]
        s = S.get(self.cfg, "scheduler")
        keys = p.keys
        text = (f"管家准备运行「{g['name']}」（{len(keys)} 项：{'、'.join(keys[:4])}{' 等' if len(keys) > 4 else ''}）。\n"
                f"它会占用电脑前台，运行期间不能用电脑。\n"
                f"{int(s['prompt_timeout_seconds']) // 60} 分钟没回答：照样开始（这是你定的时间）。")
        self.prompt = {"game": b["game"], "batch": b["id"], "name": g["name"], "tasks": keys, "asked_at": now_bj(),
                       "text": text, "auto_start": True, "timeout_s": int(s["prompt_timeout_seconds"]),
                       "choices": {"now": "现在开始", "later": f"推迟 {s['postpone_minutes']} 分钟", "skip": "今天跳过"}}
        self.log(f"你在用电脑，先问一声再跑「{g['name']}」", b["game"])

    def answer(self, choice: str, via: str = "界面") -> bool:
        with self.lock:
            p = self.prompt
            if not p:
                return False
            self.prompt = None
            gid = p["game"]
            if choice == "now":
                self.log(f"{via}：现在开始「{p['name']}」", gid)
                self._start_prompted(p)
            elif choice == "later":
                mins = int(S.get(self.cfg, "scheduler")["postpone_minutes"])
                until = (datetime.now(BJ) + timedelta(minutes=mins)).strftime("%Y-%m-%d %H:%M")
                self._save_game_state(gid, lambda gs: gs.update(postponed_until=until))
                self.log(f"{via}：「{p['name']}」推迟到 {until[11:]}", gid)
            elif choice == "skip":
                Schedule(self.cfg).set_skip(sched_day(), p["batch"], True)
                self.log(f"{via}：「{p['name']}」这一批今天跳过", gid)
            self.wake()
            return True

    def _start_prompted(self, p: dict):
        """回答「现在开始」或没人回答：按这一批现在的情况重新算一遍再开跑。"""
        doc = Schedule(self.cfg).day(sched_day())
        b = next((x for x in doc["batches"] if x["id"] == p["batch"]), None)
        if not b:
            self.log("要开始的批次已经不在今天的日程里了", p["game"])
            return
        r = self.evaluate(b, doc, datetime.now(BJ))
        if not (r["plan"] and r["plan"].keys):
            self.log(f"「{p['name']}」现在没有要跑的：{r['why']}", p["game"])
            return
        self.start([(b, r["plan"])], "提醒")

    def _prompt_expired(self):
        with self.lock:
            if self.prompt and self._prompt_left(datetime.now(BJ)) <= 0:
                p, self.prompt = self.prompt, None
                self.log(f"提醒没人回答：「{p['name']}」按你定的时间开始", p["game"])
                self._start_prompted(p)

    def loop(self):
        self.log("自动调度已启动" + ("" if self.enabled() else "（当前关闭，界面里打开后生效）"))
        while not self._stop.is_set():
            try:
                self._prompt_expired()
                wait = self.tick()
                wait = min(wait, self._daily_push())
            except Exception as e:  # 记下来给界面看；下一轮照常（这一轮的错误会在界面的调度记录里显示）
                self.log(f"调度出错：{type(e).__name__}: {e}")
                wait = 60
            wait = max(5.0, min(float(wait), MAX_SLEEP))
            self.next_check = (datetime.now(BJ) + timedelta(seconds=wait)).strftime("%Y-%m-%d %H:%M:%S")
            self._wake.wait(wait)
            self._wake.clear()

    def _daily_push(self) -> float:
        """到了每日汇总时间就推当天汇总；返回离下一次还有几秒。"""
        from . import notify
        at_s = S.get(self.cfg, "push")["daily_at"]
        if not notify.enabled(self.cfg) or not at_s:
            return MAX_SLEEP
        now = datetime.now(BJ)
        at = datetime.combine(now.date(), parse_hm(at_s), tzinfo=BJ)
        if now >= at:
            day = sched_day(at).isoformat()  # 汇总的是推送时刻所在的那一天（4 点换日）
            if not notify.daily_done(self.cfg, day):
                self.log(f"每日汇总推送：{notify.daily(self.cfg, day)}")
            at += timedelta(days=1)
        return max(5.0, (at - now).total_seconds())

    def run_in_background(self):
        threading.Thread(target=self.loop, daemon=True).start()

    def status(self) -> dict:
        return {"enabled": self.enabled(), "paused": self.rs.paused(), "idle_seconds": idle_seconds(),
                "idle": IDLE.status(self.cfg, datetime.now(BJ), idle_seconds()), "next_wake": getattr(self, "next_wake", ""),
                "last_tick": self.last_tick,
                "next_check": self.next_check, "batches": self.batch_info, "prompt": self.prompt,
                "events": list(reversed(self.events[-20:]))}
