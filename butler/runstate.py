"""运行状态：同一时间只允许一次运行；记录正在跑什么；停止 / 让出电脑的标记。

data/running.json   正在运行的内容（运行结束删除）
data/stop.flag      请求停止（执行器每 2 秒检查一次；运行结束、调度开新一次运行前清除）
data/skip.flag      跳过正在跑的任务 / 这个游戏这次剩下的（执行器把它当成只对当前游戏的停止）
data/paused.json    让出电脑：调度暂停（/api/resume 清除）
data/suspend.json   当前任务被暂停（BetterGI 自带的暂停热键；再按一次继续）
data/resume.json    停止时还没跑完的任务（「继续」用）
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from . import jsonio
from .timeutil import BJ

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def now_bj() -> str:
    return datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")


def pid_alive(pid: int) -> bool:
    """进程是否还在。Windows 上不能用 os.kill(pid, 0)（会直接结束进程）。"""
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = wintypes.DWORD()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_admin() -> bool:
    """管家是否以管理员身份运行（这样启动 BetterGI 等要管理员权限的程序时不会再弹确认窗口）。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def kill_tree(pid: int):
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def is_running(exe_name: str) -> bool:
    """按进程名看程序开着没有（Windows）。"""
    if os.name != "nt" or not exe_name:
        return False
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"], capture_output=True,
                         creationflags=NO_WINDOW)
    return exe_name.lower().encode() in out.stdout.lower()


def kill_image(exe_name: str):
    """按进程名结束（让出电脑时关闭 PC 游戏 / 工具）。"""
    if os.name == "nt" and exe_name:
        subprocess.run(["taskkill", "/IM", exe_name, "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)


class RunState:
    def __init__(self, data_dir: str):
        self.root = Path(data_dir)
        self.running_path = self.root / "running.json"
        self.stop_path = self.root / "stop.flag"
        self.paused_path = self.root / "paused.json"

    # ---------- 读写 ----------
    def _read(self, p: Path):
        return jsonio.read(p, None)

    def _write(self, p: Path, obj):
        jsonio.write(p, obj)

    def read_running(self) -> dict | None:
        return self._read(self.running_path)

    # ---------- 运行锁 ----------
    def current(self) -> dict | None:
        """正在运行的内容；进程已经不在了的残留记录视为没有在运行。"""
        r = self._read(self.running_path)
        if r and pid_alive(int(r.get("pid") or 0)):
            return r
        return None

    def acquire(self, games: list[str]) -> dict:
        cur = self.current()
        if cur:
            raise RuntimeError(f"已经有一次运行在进行（{', '.join(cur.get('games', []))}，开始于 {cur.get('started')}）")
        # 不清停止标记：进程刚开出来、还没拿到锁时你点了停止，这里要认（旧的标记由调度在开跑前清掉）
        self.set_suspended(None)
        doc = {"pid": os.getpid(), "started": now_bj(), "games": games, "done_games": [],
               "current": None, "runner_pid": 0}
        self._write(self.running_path, doc)
        return doc

    def update(self, **kw):
        """只有持有运行锁的进程能改。"""
        def fn(doc):
            if doc.get("pid") == os.getpid():
                doc.update(kw)
        jsonio.update(self.running_path, {}, fn)

    def release(self):
        doc = self._read(self.running_path)
        if doc and doc.get("pid") == os.getpid():
            jsonio.remove(self.running_path)
        self.clear_stop()
        self.clear_skip()
        self.clear_yield()
        self.set_suspended(None)

    # ---------- 停止 ----------
    def request_stop(self, reason: str = "手动停止"):
        self._write(self.stop_path, {"time": now_bj(), "reason": reason})

    def stop_requested(self) -> bool:
        return self.stop_path.exists()

    def stop_reason(self) -> str:
        return (self._read(self.stop_path) or {}).get("reason", "")

    def clear_stop(self):
        jsonio.remove(self.stop_path)

    # ---------- 跳过（运行条上的「跳过当前任务」/ 右键「跳过当前序列」） ----------
    @property
    def skip_path(self) -> Path:
        return self.root / "skip.flag"

    def request_skip(self, scope: str, game: str, task: str = ""):
        """scope = task：停下这个任务，接着跑这个游戏剩下的；game：这个游戏这次剩下的都不跑，接着下一个游戏。"""
        self._write(self.skip_path, {"scope": scope, "game": game, "task": task, "time": now_bj()})

    def skip_req(self) -> dict | None:
        return self._read(self.skip_path)

    def clear_skip(self):
        jsonio.remove(self.skip_path)

    # ---------- 让出（11-02）：有赶时段的任务时，正在跑的游戏做完手上这一项就停，剩下的放回「接下来」 ----------
    @property
    def yield_path(self) -> Path:
        return self.root / "yield.flag"

    def request_yield(self, reason: str, game: str):
        self._write(self.yield_path, {"reason": reason, "for": game, "time": now_bj()})

    def yield_req(self) -> dict | None:
        return self._read(self.yield_path)

    def clear_yield(self):
        jsonio.remove(self.yield_path)

    # ---------- 停止后继续（data/resume.json；和「让出电脑」的 resume 接口无关） ----------
    @property
    def continue_path(self) -> Path:
        return self.root / "resume.json"

    def save_continue(self, doc: dict):
        """记下还没跑完的。已有的记录一定是这次停止记下的（每次开始新的运行都会清掉）：合在一起，
        例如停止时排队还没开始的批次 + 正在跑、被停下的那个。"""
        jsonio.update(self.continue_path, {}, lambda old: {**old, **doc, "games": {**old.get("games", {}), **doc["games"]}})

    def clear_continue(self):
        jsonio.remove(self.continue_path)

    def get_continue(self, cfg: dict) -> dict | None:
        """停止时记下的「还没跑完」：{"games": {游戏[#任务预设]: {"game", "keys": [...], "game_day": 日期, "routine"}}, …}。
        跨过任一游戏的刷新、或游戏已经取消挂载，就作废。"""
        doc = self._read(self.continue_path)
        if not doc:
            return None
        from .timeutil import game_day
        for x in doc["games"].values():
            gid = x["game"]
            g = cfg["games"].get(gid)
            if not g or game_day(g).isoformat() != x["game_day"]:
                self.clear_continue()
                return None
        return doc

    def forget(self, gid: str):
        """彻底删除：「继续」记录里这个游戏的部分。"""
        if not self.continue_path.exists():
            return
        doc = jsonio.update(self.continue_path, {"games": {}},
                            lambda d: {**d, "games": {k: v for k, v in d["games"].items() if v["game"] != gid}})
        if not doc["games"]:
            self.clear_continue()

    # ---------- 让出电脑 ----------
    # ---------- 暂停 / 继续当前任务（BetterGI 自带的暂停热键） ----------
    @property
    def suspend_path(self) -> Path:
        return self.root / "suspend.json"

    def set_suspended(self, doc: dict | None):
        if doc:
            self._write(self.suspend_path, doc)
        else:
            jsonio.remove(self.suspend_path)

    def suspended(self) -> dict | None:
        return self._read(self.suspend_path)

    def pause(self, reason: str = "让出电脑"):
        self._write(self.paused_path, {"since": now_bj(), "reason": reason})

    def resume(self):
        jsonio.remove(self.paused_path)

    def paused(self) -> dict | None:
        return self._read(self.paused_path)
