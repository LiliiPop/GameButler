"""开机自动启动：任务计划程序里的「\\GameButler\\开机启动管家」。

登录 Windows 20 秒后以最高权限启动 GameButler.exe --tray（托盘里启动，不弹确认、不开窗口）。
界面「设置」和托盘菜单都走这里（托盘通过 /api/settings）。
"""
from __future__ import annotations

import base64
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "GameButler.exe"
TASK_PATH, TASK_NAME = "\\GameButler\\", "开机启动管家"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_cache = {"at": 0.0, "target": None}
_lock = threading.Lock()


def available() -> bool:
    return os.name == "nt" and EXE.exists()


def _ps(script: str, timeout: int = 40) -> str:
    script = "$ErrorActionPreference='SilentlyContinue';[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-EncodedCommand", enc], capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"PowerShell 没跑起来：{type(e).__name__}: {e}") from e
    return p.stdout.decode("utf-8", errors="replace").strip()


def _q(s: str) -> str:
    return s.replace("'", "''")


def target(max_age: float = 30) -> str:
    """计划任务启动的程序路径；没有计划任务返回 ""（结果缓存 max_age 秒）。"""
    if os.name != "nt":
        return ""
    with _lock:
        if _cache["target"] is not None and time.time() - _cache["at"] < max_age:
            return _cache["target"]
        out = _ps(f"$t=Get-ScheduledTask -TaskPath '{TASK_PATH}' -TaskName '{TASK_NAME}';"
                  "if($t){$t.Actions[0].Execute}else{'NONE'}")
        if not out:  # 正常总会输出 NONE 或路径：什么都没有 = 没查成（例如任务计划程序服务没开）
            raise RuntimeError("查任务计划程序没有结果")
        val = "" if out == "NONE" else out.splitlines()[-1].strip()
        _cache.update(at=time.time(), target=val)
        return val


def enabled() -> bool:
    return bool(target())


def enable() -> bool:
    if not available():
        return False
    exe, root = _q(str(EXE)), _q(str(ROOT))
    out = _ps(
        f"$a=New-ScheduledTaskAction -Execute '{exe}' -Argument '--tray' -WorkingDirectory '{root}';"
        "$t=New-ScheduledTaskTrigger -AtLogOn -User \"$env:USERDOMAIN\\$env:USERNAME\";$t.Delay='PT20S';"
        "$p=New-ScheduledTaskPrincipal -UserId \"$env:USERDOMAIN\\$env:USERNAME\" -LogonType Interactive -RunLevel Highest;"
        "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit (New-TimeSpan -Days 0) -MultipleInstances IgnoreNew;"
        f"Register-ScheduledTask -TaskPath '{TASK_PATH}' -TaskName '{TASK_NAME}' -Action $a -Trigger $t "
        "-Principal $p -Settings $s -Force|Out-Null;"
        f"if(Get-ScheduledTask -TaskPath '{TASK_PATH}' -TaskName '{TASK_NAME}'){{'OK'}}")
    _cache["target"] = None
    return out.endswith("OK")


def disable():
    if os.name == "nt":
        _ps(f"Unregister-ScheduledTask -TaskPath '{TASK_PATH}' -TaskName '{TASK_NAME}' -Confirm:$false")
    _cache["target"] = None


def status() -> dict:
    """error 非空 = 查不到现在是开还是关（界面显示原因；托盘菜单里显示成没勾选）。"""
    try:
        t = target()
    except RuntimeError as e:
        return {"available": available(), "on": False, "target": "", "ok": False, "error": f"查不到：{e}"}
    return {"available": available(), "on": bool(t), "target": t,
            "ok": bool(t) and Path(t).resolve() == EXE.resolve() if t else False, "error": ""}
