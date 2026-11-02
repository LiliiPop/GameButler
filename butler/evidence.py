"""留证截图：用户在设置里选哪些任务要截图确认，任务做成时在结束（和关键节点）各截一张，
没做成的不留证（过程中截的会删掉），看失败截图（data/maafw/<游戏>/stuck/，见下面 fail_*）。

放在 data/evidence/<游戏日>/<游戏>/，只在电脑上的运行记录和报告里显示，不推送。
不手动清理的话，保留 keep_days 天（默认 7）后自动删除。

设置（data/settings.json 的 evidence）：{"tasks": {游戏: [任务名…]}, "keep_days": 7}
挂载时游戏记录里的 evidence_default 写进设置作为初始勾选；之后只看设置。
游戏记录 evidence_nodes = {任务名: [节点名…]}：这些节点命中时也截一张（例如地宫选层）。
"""
from __future__ import annotations

import re
import shutil
from datetime import date, timedelta
from pathlib import Path


def root(cfg: dict) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "evidence"


def tasks_for(cfg: dict, gid: str) -> set[str]:
    from . import settings as S
    return set(S.get(cfg, "evidence")["tasks"].get(gid, []))


def forget(cfg: dict, gid: str):
    """彻底删除：这个游戏的留证截图和勾选。"""
    from . import settings as S
    for d in root(cfg).glob(f"*/{gid}"):
        shutil.rmtree(d)
    tasks = S.get(cfg, "evidence")["tasks"]
    if gid in tasks:
        tasks.pop(gid)
        S.update(cfg, "evidence", {"tasks": tasks})


def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name)[:40]


def files_for(cfg: dict, day: str, gid: str, task_key: str) -> list[str]:
    """某游戏日、某任务的留证截图（URL 路径）。"""
    d = root(cfg) / day / gid
    if not d.exists():
        return []
    tag = "_" + safe(task_key)
    return [f"/evidence/{day}/{gid}/{p.name}" for p in sorted(d.glob("*.png")) if tag in p.stem]


def usage(cfg: dict) -> dict:
    r = root(cfg)
    days = sorted(p.name for p in r.glob("*") if p.is_dir()) if r.exists() else []
    size = sum(f.stat().st_size for f in r.rglob("*.png")) if r.exists() else 0
    return {"days": days, "mb": round(size / 1048576, 1), "files": sum(1 for _ in r.rglob("*.png")) if r.exists() else 0}


def clean(cfg: dict, before: str | None = None, all_: bool = False) -> int:
    """删掉 before（YYYY-MM-DD）之前的；all_ = 全删；都不给 = 按 keep_days 自动清。返回删了几天的。"""
    r = root(cfg)
    if not r.exists():
        return 0
    if not before and not all_:
        from . import settings as S
        before = (date.today() - timedelta(days=S.get(cfg, "evidence")["keep_days"])).isoformat()
    n = 0
    for p in r.glob("*"):
        if p.is_dir() and (all_ or p.name < before):
            shutil.rmtree(p, ignore_errors=True)
            n += 1
    return n


# ---------------------------------------------------------------- 失败截图（任务卡住 / 失败时自动截的）
def _fail_files(cfg: dict):
    base = Path(cfg["machine"]["data_dir"]) / "maafw"
    return [p for p in base.glob("*/stuck/*") if p.is_file()] if base.exists() else []


def fail_usage(cfg: dict) -> dict:
    fs = _fail_files(cfg)
    return {"files": len(fs), "mb": round(sum(f.stat().st_size for f in fs) / 1048576, 1)}


def fail_clean(cfg: dict, before: str | None = None, all_: bool = False) -> int:
    """删失败截图：all_ = 全删；before（YYYY-MM-DD）= 删这天以前的（按文件时间）。返回删了几张。"""
    import time
    cut = time.mktime(time.strptime(before, "%Y-%m-%d")) if before else None
    n = 0
    for f in _fail_files(cfg):
        if all_ or (cut is not None and f.stat().st_mtime < cut):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n
