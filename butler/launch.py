"""开运行进程（只有自动调度会调用：「开始」「继续」都是往日程队列里排，由调度开跑）。

不弹命令行窗口：进度在界面的运行面板里看，命令行输出写到 data/logs/run-*.log，
完整记录照旧在 data/runs/。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def console_python() -> str:
    """管家可能用 pythonw.exe（无窗口）启动；运行窗口要用 python.exe 才能显示进度。"""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return sys.executable


def spawn_run(cfg: dict, runs: list[dict], by: str) -> subprocess.Popen:
    """开一个运行进程。runs = [{"game", "batch", "items": [任务项…], "keys": [任务键…]}]，任务已经排好，
    运行进程照单执行。请求文件放在 data/requests/，运行进程读完就删（内容写进 data/logs/run-*.log）。"""
    data_dir = Path(cfg["machine"]["data_dir"])
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    req = data_dir / "requests" / f"{stamp}.json"
    req.parent.mkdir(parents=True, exist_ok=True)
    req.write_text(json.dumps({"by": by, "runs": runs}, ensure_ascii=False, indent=1), encoding="utf-8")
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out = open(logs / f"run-{stamp[:15]}.log", "w", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen([console_python(), str(ROOT / "gb.py"), "exec", str(req)], cwd=str(ROOT), stdout=out,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, creationflags=flags)
    out.close()  # 子进程已经拿到句柄
    return proc


_bg: dict = {}


def spawn_background(name: str, args: list[str], data_dir) -> bool:
    """在后台跑一个管家子命令（例如 news fetch），不弹窗口，输出追加到 data/logs/<name>.log。
    同名的上一个还没结束时不重复启动；返回是否启动了。"""
    p = _bg.get(name)
    if p is not None and p.poll() is None:
        return False
    logs = Path(data_dir) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{name}.log"
    if log.exists() and log.stat().st_size > 2_000_000:
        log.replace(logs / f"{name}.old.log")
    out = open(log, "a", encoding="utf-8")
    out.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
    out.flush()
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    _bg[name] = subprocess.Popen([console_python(), str(ROOT / "gb.py"), *args], cwd=str(ROOT), stdout=out,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out.close()
    return True


def background_running(name: str) -> bool:
    p = _bg.get(name)
    return p is not None and p.poll() is None
