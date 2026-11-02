"""睡眠与锁屏：电脑睡着时什么都不会跑，锁着屏时电脑游戏跑不了。

叫醒电脑（设置 scheduler.wake_from_sleep，默认开）：
  调度每次醒来都算一下「下一个要到点的时刻」（定时的开始、闲时里时段的开始），在 Windows 任务计划程序里
  放一个「唤醒计算机运行此任务」的任务 \\GameButler\\Wake，比那个时刻早 2 分钟。到点时 Windows 把电脑叫醒，
  任务调 POST /api/scheduler/wake，管家马上重新看一遍。没有要到点的就把这个任务删掉。
  能不能叫醒取决于 Windows：电源选项里要「允许使用唤醒定时器」；不少笔记本（现代待机）不理会唤醒定时器。
  叫醒后有要跑的，管家让电脑在跑完之前保持醒着（不改电源设置）。
锁屏：
  叫醒后屏幕通常是锁着的。锁屏时脚本看不到也点不了电脑游戏的窗口，所以电脑游戏（原神、崩铁、剑三）等解锁后再跑；
  模拟器上的游戏不受影响。
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import jsonio
from . import settings as S

TASK = r"\GameButler\Wake"
LEAD = timedelta(minutes=2)
PORT = 8765
_cache: dict = {}


def supported() -> bool:
    return os.name == "nt"


def _run(args: list[str], timeout=20) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _state_path(cfg: dict) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "scheduler" / "wake.json"


def _xml(at: datetime, port: int) -> str:
    start = at.astimezone().replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")
    cmd = (f"try {{ Invoke-WebRequest -UseBasicParsing -Method Post -TimeoutSec 20 "
           f"http://127.0.0.1:{port}/api/scheduler/wake | Out-Null }} catch {{}}")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>日常管家：电脑睡着时，到下一个定时前把电脑叫醒（管家自动维护，不要手动改）</Description></RegistrationInfo>
  <Triggers><TimeTrigger><StartBoundary>{start}</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>false</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <Hidden>true</Hidden>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>powershell.exe</Command>
    <Arguments>-NoProfile -NonInteractive -WindowStyle Hidden -Command "{cmd}"</Arguments></Exec></Actions>
</Task>
"""


def plan(cfg: dict, at: datetime | None, log=None) -> str:
    """把叫醒任务设到 at 前 2 分钟；at = None 或设置里关了：删掉任务。返回现在的叫醒时间（北京时间字符串）或空。"""
    if not supported():
        return ""
    on = S.get(cfg, "scheduler")["wake_from_sleep"]
    target = (at - LEAD) if (on and at) else None
    if target and target <= datetime.now(target.tzinfo) + timedelta(seconds=30):
        target = None  # 马上就到：不用叫醒（电脑醒着）
    key = target.strftime("%Y-%m-%d %H:%M") if target else ""
    st = jsonio.read(_state_path(cfg), {})
    if st.get("at", None) == key and st.get("ok") is not False:
        return key
    try:
        if target:
            p = Path(cfg["machine"]["data_dir"]) / "scheduler" / "wake-task.xml"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_xml(target, int(cfg["machine"].get("port") or PORT)), encoding="utf-16")
            r = _run(["schtasks", "/Create", "/TN", TASK, "/XML", str(p), "/F"])
            ok = r.returncode == 0
            msg = "" if ok else (r.stderr or r.stdout).decode("gbk", "ignore").strip()
        else:
            r = _run(["schtasks", "/Delete", "/TN", TASK, "/F"])
            ok, msg = True, ""
    except (OSError, subprocess.SubprocessError) as e:
        ok, msg = False, f"{type(e).__name__}: {e}"
    jsonio.write(_state_path(cfg), {"at": key, "ok": ok, "error": msg,
                                    "set_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    if log and target:
        log(f"已设好叫醒电脑：{target.astimezone():%m-%d %H:%M}（电脑时间）" if ok else f"设叫醒电脑失败：{msg}")
    return key if ok else ""


def _power_index(sub: str, setting: str) -> int | None:
    """powercfg 里当前电源计划某一项的值（接电源时）。读不到返回 None。"""
    k = (sub, setting)
    if k in _cache and time.time() - _cache[k][0] < 600:
        return _cache[k][1]
    v = None
    try:
        r = _run(["powercfg", "/query", "SCHEME_CURRENT", sub, setting], timeout=10)
        hexes = re.findall(r":\s*0x([0-9a-fA-F]{8})\s*$", r.stdout.decode("gbk", "ignore"), re.M)
        if r.returncode == 0 and len(hexes) >= 2:
            v = int(hexes[-2], 16)  # 倒数第二个 = 接电源时，最后一个 = 用电池时
    except (OSError, subprocess.SubprocessError):
        v = None
    _cache[k] = (time.time(), v)
    return v


def is_locked() -> bool:
    """屏幕是不是锁着（锁屏、登录界面、UAC 安全桌面时都算）。读不出来按没锁算（不挡住电脑游戏）。"""
    if not supported():
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.OpenInputDesktop.restype = wintypes.HANDLE
        u.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        u.SwitchDesktop.argtypes = [wintypes.HANDLE]
        u.CloseDesktop.argtypes = [wintypes.HANDLE]
        h = u.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP：锁屏时打不开输入桌面
        if not h:
            return True
        try:
            return not u.SwitchDesktop(h)
        finally:
            u.CloseDesktop(h)
    except (OSError, AttributeError):
        return False


def status(cfg: dict, sched=None) -> dict:
    """界面上的提醒要用的：叫醒开没开、下一次叫醒、Windows 允不允许唤醒定时器、多久睡眠、唤醒要不要密码、现在锁没锁屏。"""
    on = S.get(cfg, "scheduler")["wake_from_sleep"]
    st = jsonio.read(_state_path(cfg), {})
    out = {"supported": supported(), "wake_from_sleep": on, "next_wake": st.get("at", "") if on else "",
           "wake_error": st.get("error", "") if st.get("ok") is False else "",
           "wake_timers": None, "sleep_after_min": None, "password_on_wake": None, "locked": False}
    if not supported():
        return out
    rt = _power_index("SUB_SLEEP", "RTCWAKE")          # 0 关 · 1 开 · 2 只允许重要的
    sb = _power_index("SUB_SLEEP", "STANDBYIDLE")      # 多少秒后睡眠，0 = 从不
    lk = _power_index("SUB_NONE", "CONSOLELOCK")       # 唤醒时要不要密码
    out.update(wake_timers=None if rt is None else rt == 1, sleep_after_min=None if sb is None else sb // 60,
               password_on_wake=None if lk is None else bool(lk), locked=is_locked())
    return out
