"""网页接口：每个功能一个接口，事情交给对应的模块做。按领域分文件：

  running.py   总览 / 运行：状态、停止、继续、暂停、让出电脑
  schedule.py  日程与调度
  games.py     游戏：挂载、任务与选项、任务预设、计划、运行记录、高级设置、工具自己的设置
  data.py      读数、抽卡记录、活动
  settings.py  设置、主题、留证、模拟器、常见脚本下载、界面批注、程序本身

每个接口用 @route(方法, 路径正则) 登记，处理函数收到 (api, 匹配结果, 查询参数, 请求体)。
api 是 Api 对象：配置、调度、存储、运行状态，以及几个各处都用的小函数。
接口一览见 butler/web.py 开头。
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .. import games as G
from .. import planner as P
from .. import settings as S
from ..runstate import RunState
from ..schedule import Schedule
from ..store import Store
from ..timeutil import BJ, sched_day

ROOT = Path(__file__).resolve().parents[2]
APP = {"server": None, "started": ""}  # web.serve() 填入；/api/app/quit、restart 用它停止服务
ROUTES: list = []                         # [(方法, 正则, 处理函数)]


class NotFound(Exception):
    pass


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


def day_of(s: str) -> date:
    return sched_day() if s == "today" else date.fromisoformat(s)


class Api:
    def __init__(self, cfg: dict, sched):
        self.cfg, self.sched = cfg, sched
        self.data_dir = Path(cfg["machine"]["data_dir"])
        self.store = Store(str(self.data_dir))
        self.rs = RunState(str(self.data_dir))

    def game(self, gid: str) -> dict:
        if gid not in self.cfg["games"]:
            raise NotFound(f"没有这个游戏：{gid}")
        return self.cfg["games"][gid]

    def adapter(self, gid: str):
        self.game(gid)
        return G.adapter(self.cfg, gid)

    def enqueue(self, day: date, body: dict) -> dict:
        """加一条一次性的（「开始」「继续」也走这里）。「现在」跑却没有要跑的：直接说明原因，不加。"""
        when = body.get("when") or {"kind": "now"}
        if when.get("kind") in ("now", "queue"):
            g = self.game(body["game"])
            p = P.plan(self.cfg, self.store, body["game"], body.get("tasks") or None, manual=True,
                       rerun=bool(body.get("rerun")), now=datetime.now(BJ), routine=str(body.get("routine") or ""))
            if not p.keys:
                raise ValueError(f"{g['name']}：没有要跑的。{p.why}")
        from ..signals import clear_fuse
        # 中止队列以后你点「开始 / 立即开始 / 继续」：恢复调度；「加入队列」只排着，不恢复（11-02）。让出电脑都不恢复
        if when.get("kind") == "now" and (self.rs.paused() or {}).get("reason") == "中止队列":
            self.rs.resume()
        clear_fuse(self.cfg, body["game"])  # 你手动排了这个游戏（重跑 / 现在跑 / 继续…）= 熔断的事处理好了，今天可以接着自动跑（11-02）
        same = None if body.get("hires") else self._pending_same(day, body)
        if same:  # 同一个游戏、同一套预设已经有一条排着还没跑：并进去，不再加一条（10-31）
            self.sched.wake()
            return {**same, "merged": True, "paused": bool(self.rs.paused())}
        if when.get("kind") in ("now", "queue") and not body.get("hires") and not body.get("routine"):
            # 11-03：「开始」「立即开始」「继续」不再复制一条「今天的任务」——把今天日程里本来就有这些任务的条目挪到现在（或队尾）；
            # 只有哪条都不包含的任务才另加一条
            moved, left = self._move_rules(day, body, p.keys)
            if moved and not left:
                self.sched.wake()
                return {**moved, "merged": True, "paused": bool(self.rs.paused())}
            if moved:
                body = {**body, "tasks": left}
        b = Schedule(self.cfg).add_once(day, {"game": body["game"], "tasks": body.get("tasks") or [],
                                              "routine": body.get("routine") or "", "when": when,
                                              "label": body.get("label", ""), "rerun": bool(body.get("rerun")),
                                              "hires": body.get("hires", "")})
        self.sched.wake()
        return {**b, "paused": bool(self.rs.paused())}

    def _move_rules(self, day: date, body: dict, want: list[str]) -> tuple[dict | None, list[str]]:
        """把要跑的任务交给今天日程里已有的定时条目：它们回到「接下来」（立即 = 最前面，加入队列 = 队尾），只跑这几项，
        跑完恢复原样（Schedule.requeue）。正在跑的那条里的任务不用再排。返回 (挪过的第一条, 哪条都不包含的任务)。"""
        kind = (body.get("when") or {"kind": "now"}).get("kind")
        sch = Schedule(self.cfg)
        doc = sch.day(day)
        cur = (self.rs.current() or {}).get("batch", "")
        rerun = bool(body.get("rerun"))
        left, hit, running = list(dict.fromkeys(want)), [], None
        for x in doc["batches"]:
            if x["game"] != body["game"] or x["kind"] != "rule" or not left:
                continue
            ks = [k for k in sch.batch_keys({**x, "tasks": [], "requeue": False}) if k in left]
            if not ks:
                continue
            left = [k for k in left if k not in ks]
            if x["id"] == cur and not rerun:
                running = x  # 正在跑的这条本来就会跑到它们
                continue
            if x["id"] == cur:
                left += ks  # 要「再跑一次」正在跑的那条里的任务：另加一条
                continue
            # 已经挪过、还没开始的才并进去；跳过了的条目上留着的是作废的那一轮（11-04：原神并进了整套一条龙）
            prev = list(x.get("tasks") or []) if x.get("requeue") and x["id"] not in doc["skip"] else []
            sch.requeue(day, x["id"], prev + [k for k in ks if k not in prev], queue=kind == "queue", rerun=rerun)
            hit.append(x["id"])
        if not hit:
            return running, left
        ids = [y["id"] for y in sch.day(day)["batches"]]
        rest = [i for i in ids if i not in hit]
        sch.set_order(day, hit + rest if kind == "now" else rest + hit)
        return next(y for y in sch.day(day)["batches"] if y["id"] == hit[0]), left

    def _pending_same(self, day: date, body: dict) -> dict | None:
        """同一游戏、同一套预设今天已经有的条目：新加的并进它，不另加一条（11-01）。
        - 排着还没跑的一次性条目 / 已经放回「接下来」的条目：把任务并进去；
        - 定时生成的条目（没在跑）：让它回到「接下来」，只跑这几项（Schedule.requeue）。"""
        kind = (body.get("when") or {"kind": "now"}).get("kind")
        if kind not in ("now", "queue"):
            return None
        sch = Schedule(self.cfg)
        doc = sch.day(day)
        rt, tasks = str(body.get("routine") or ""), [str(x) for x in body.get("tasks") or []]
        cur = (self.rs.current() or {}).get("batch", "")
        for x in doc["batches"]:
            if x["game"] != body["game"] or x.get("routine", "") != rt or x["id"] == cur:
                continue
            pending = x["start"]["mode"] == "now" and x["id"] not in doc["ran"] and x["id"] not in doc["skip"]
            if pending and (x.get("requeue") or x["kind"] == "once"):
                if x.get("tasks") and tasks:
                    sch.add_tasks(day, x["id"], tasks)
                    return x
                if not x.get("tasks") and not x.get("requeue"):
                    return x  # 它本来就跑整套（或今天全部），新加的已经包含在里面
                if x.get("requeue") and not tasks:
                    sch.add_tasks(day, x["id"], sch.batch_keys({**x, "tasks": []}))
                    return x
            elif x["kind"] == "rule" and rt:
                sch.requeue(day, x["id"], tasks or sch.batch_keys({**x, "tasks": []}), queue=kind == "queue")
                ids = [y["id"] for y in sch.day(day)["batches"]]
                order = [x["id"]] + [i for i in ids if i != x["id"]] if kind == "now" else [i for i in ids if i != x["id"]] + [x["id"]]
                sch.set_order(day, order)
                return sch.day(day)["batches"][0 if kind == "now" else -1]
        return None

    def appearance(self) -> dict:
        return S.get(self.cfg, "appearance")


def load():
    """登记全部接口（按文件导入一次）。"""
    from . import data, games, running, schedule, settings  # noqa: F401  （导入即登记）
    return ROUTES
