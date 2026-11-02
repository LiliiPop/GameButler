"""任务预设与完成状态的存储。全部是 JSON 文件，放在 data 目录下，方便备份和手动查看。

data/routines/<游戏>.json        {"routines": {"日常": {"tasks": [...]}}}（没有「默认」：哪套挂了定时哪套就跑，见 schedule.py）
data/status/<游戏日>/<游戏>.json   {任务键: {"result": ..., "time": ..., "detail": ...}}

任务项格式：{"task": "任务名", "choices": {选项名: 值}, "key"?: "任务键"}（再跑一轮在日程的批次上）
- key：同一个任务在一天里出现多次时（例如未定「进修副本」两个关卡、绘旅人午间/晚间各领一次体力）用来区分，
  状态按 key 记录。没写 key 时 key = 任务名；重复的任务自动补成「任务名 #2」「任务名 #3」。
- 任务的运行时段写在游戏记录的 windows 里（按任务键或任务名），不写在任务项上。
游戏日一律按北京时间 + 该游戏的刷新时刻计算（timeutil.game_day）。
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from . import jsonio
from .timeutil import BJ

DONE = ("succeeded", "exhausted")
NEED_ATTENTION = ("failed", "timeout", "stalled", "missed")
RESULT_CN = {"exhausted": "完成（无可做）", "succeeded": "完成", "failed": "失败", "timeout": "超时",
             "stalled": "卡住", "missed": "错过时段", "stopped": "已停止"}


def item_key(t: dict) -> str:
    return t.get("key") or t["task"]


def normalize_tasks(tasks: list[dict]) -> list[dict]:
    """补齐重复任务的 key（不改已有的 key）。"""
    seen: dict[str, int] = {}
    used = {t["key"] for t in tasks if t.get("key")}
    out = []
    for t in tasks:
        t = dict(t)
        t.setdefault("choices", {})
        if not t.get("key"):
            n = seen.get(t["task"], 0) + 1
            seen[t["task"]] = n
            if n > 1 or t["task"] in used:
                k, i = f"{t['task']} #{n}", n
                while k in used:
                    i += 1
                    k = f"{t['task']} #{i}"
                t["key"] = k
        else:
            seen[t["task"]] = seen.get(t["task"], 0) + 1
        used.add(item_key(t))
        out.append(t)
    return out


class Store:
    def __init__(self, data_dir: str):
        self.root = Path(data_dir)

    # ---------- 通用 ----------
    def _read(self, path: Path, default):
        return jsonio.read(path, default)

    def _write(self, path: Path, obj):
        jsonio.write(path, obj)

    # ---------- 任务预设 ----------
    def routines(self, gid: str) -> dict:
        doc = self._read(self.root / "routines" / f"{gid}.json", {"routines": {}})
        out = {"routines": doc.get("routines", {})}
        for r in out["routines"].values():
            r["tasks"] = normalize_tasks(r.get("tasks", []))
        return out

    def save_routines(self, gid: str, doc: dict):
        rs = doc.get("routines", {})
        for name in rs:
            if not str(name).strip():
                raise ValueError("任务预设要有名字")
        for r in rs.values():
            r["tasks"] = normalize_tasks(r.get("tasks", []))
        self._write(self.root / "routines" / f"{gid}.json", {"routines": rs})

    def ensure_routines(self, gid: str, seed) -> dict:
        """第一次使用时生成任务预设。seed 可以是任务项列表（生成一套「日常」），
        也可以是完整文档 {"routines": {名: {"tasks": [...]}}}（例如从 MFA 的多个实例导入）；空的就什么都不生成。"""
        doc = self.routines(gid)
        if not doc["routines"] and seed:
            doc = {"routines": seed.get("routines", {})} if isinstance(seed, dict) else {"routines": {"日常": {"tasks": seed}}}
            if doc["routines"]:
                self.save_routines(gid, doc)
        return doc

    # ---------- 完成状态 ----------
    def status(self, gid: str, day: date) -> dict:
        return self._read(self.root / "status" / day.isoformat() / f"{gid}.json", {})

    def record(self, gid: str, day: date, results: list[dict]):
        """记任务结果（每个任务一结束就记）。手动停止的不记；当天已经做完的不被后来的失败覆盖。"""
        now = datetime.now(BJ)

        def fn(st):
            for r in results:
                if r["result"] == "stopped":
                    continue
                prev = st.get(r["task"], {})
                if prev.get("result") in DONE and r["result"] not in DONE:
                    continue
                entry = {"result": r["result"], "time": now.strftime("%H:%M"), "at": now.strftime("%Y-%m-%d %H:%M:%S"),
                         "detail": r.get("detail", ""), "attempts": r.get("attempts", 1), "minutes": r.get("minutes", 0)}
                if r.get("shots"):
                    entry["shots"] = r["shots"]
                if r.get("alert"):  # 任务本身做完了，但有需要你知道的事（例如时绘日常未满 8 个）
                    entry["alert"] = r["alert"]
                st[r["task"]] = entry
        jsonio.update(self.root / "status" / day.isoformat() / f"{gid}.json", {}, fn)

    # ---------- 彻底删除 ----------
    def forget(self, gid: str):
        jsonio.remove(self.root / "routines" / f"{gid}.json")
        for sub in ("status",):
            for f in (self.root / sub).glob(f"*/{gid}.json"):
                jsonio.remove(f)
