"""定期清理：MaaFramework 的调试日志和截图会越积越多（几天就上 GB），只留最近的。

管家启动时清一次，之后每天清一次。只动管家自己的 data 目录，不碰 MAA 项目和游戏。
"""
from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

KEEP = {
    "debug_logs": 3,     # data/maafw/<游戏>/debug/maafw.bak.*.log：留最近几份
    "shots_days": 14,    # 管家自己的卡住截图（stuck，运行记录里链着）：留多少天
    "error_days": 3,     # 脚本出错截图（MaaFramework 的 on_error、vision）：留多少天（11-06：代号鸢 3 天就 600 MB）
    "error_mb": 300,     # 并且每个游戏最多留这么多 MB，超过从旧的删
    "runs_days": 60,     # data/runs/<日期>：运行记录留多少天
    "logs_days": 30,     # data/logs：管家自己的输出日志
}


def _older(p: Path, days: float) -> bool:
    try:
        return time.time() - p.stat().st_mtime > days * 86400
    except OSError:
        return False


def _rm(p: Path) -> int:
    try:
        n = p.stat().st_size if p.is_file() else 0
        shutil.rmtree(p) if p.is_dir() else p.unlink()
        return n
    except OSError:
        return 0


def clean(data_dir: str | Path) -> dict:
    data = Path(data_dir)
    freed, files = 0, 0
    for game in (data / "maafw").glob("*"):
        logs = sorted((game / "debug").glob("maafw.bak.*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in logs[KEEP["debug_logs"]:]:
            freed += _rm(p); files += 1
        for p in (game / "stuck").glob("*"):
            if p.is_file() and _older(p, KEEP["shots_days"]):
                freed += _rm(p); files += 1
        shots = [p for sub in ("debug/on_error", "debug/vision") for p in (game / sub).glob("*") if p.is_file()]
        shots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        total = 0
        for p in shots:
            try:
                size = p.stat().st_size
            except OSError:
                continue
            total += size
            if _older(p, KEEP["error_days"]) or total > KEEP["error_mb"] * 1048576:
                freed += _rm(p); files += 1
    for day in (data / "runs").glob("*"):
        if day.is_dir() and _older(day, KEEP["runs_days"]):
            freed += sum(f.stat().st_size for f in day.rglob("*") if f.is_file())
            _rm(day); files += 1
    from . import jsonio  # 留证截图：按设置里的保留天数
    from .settings import DEFAULTS
    keep = int((jsonio.read(data / "settings.json", {}).get("evidence") or {}).get("keep_days", DEFAULTS["evidence"]["keep_days"]))
    for day in (data / "evidence").glob("*"):
        if day.is_dir() and _older(day, keep + 1):
            freed += sum(f.stat().st_size for f in day.rglob("*") if f.is_file())
            _rm(day); files += 1
    for p in (data / "logs").glob("*.log*"):
        if _older(p, KEEP["logs_days"]):
            freed += _rm(p); files += 1
    return {"files": files, "mb": round(freed / 1048576, 1)}


def start_daily(data_dir: str | Path):
    def loop():
        while True:
            try:
                r = clean(data_dir)
                if r["files"]:
                    print(f"· 清理旧日志和截图：{r['files']} 个，{r['mb']} MB", flush=True)
            except Exception as e:  # 清理失败不影响管家
                print(f"· 清理失败：{e}", flush=True)
            time.sleep(86400)
    threading.Thread(target=loop, daemon=True).start()
