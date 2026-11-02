"""脚本信号约定（总纲 10-23）：脚本在日志 / focus 里输出这些，管家就能认。不输出的脚本照常能用。

  [GB_DONE] 任务名         这项确认完成
  [GB_FAIL] 任务名 原因     失败（按重试规则处理）
  [GB_MANUAL] 原因          需要人工（验证码、扫码）：这个游戏后面的任务不跑了，推送提醒
  [GB_PAUSE] 原因           脚本自己暂停（例如检测到你在用电脑）：记成「已停止」，之后照常再跑
  [GB_FUSE] 原因            熔断（剑三的 PvP）：立刻停掉整次运行，推送，当天不再自动跑这个游戏

剑三 MAA 早期约定的 [JX3_DONE] / [JX3_FAIL] / [JX3_MANUAL] / [JX3_PAUSE] / [JX3_PVP_FUSE] 也认。
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

SIG_RE = re.compile(r"\[(?:GB|JX3)_(DONE|FAIL|MANUAL|PAUSE|PVP_FUSE|FUSE)\]\s*([^\"\]\[}]*)")


def parse(line: str):
    """一行文字里的信号：返回 (种类, 后面的文字) 或 None。种类：done / fail / manual / pause / fuse。"""
    m = SIG_RE.search(line or "")
    if not m:
        return None
    k = m.group(1).lower()
    return ("fuse" if "fuse" in k else k), m.group(2).strip()


def _fuse_path(cfg) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "scheduler" / "fuse.json"


def mark_fused(cfg, gid: str, day: date, reason: str):
    from . import jsonio
    jsonio.update(_fuse_path(cfg), {}, lambda d: d.update({gid: {"day": day.isoformat(), "reason": reason}}))


def fused(cfg, gid: str, day: date) -> str:
    """这个游戏今天熔断过吗：返回原因（没有返回空）。"""
    from . import jsonio
    x = jsonio.read(_fuse_path(cfg), {}).get(gid) or {}
    return x.get("reason", "熔断") if x.get("day") == day.isoformat() else ""


def clear_fuse(cfg, gid: str):
    from . import jsonio
    if _fuse_path(cfg).exists():
        jsonio.update(_fuse_path(cfg), {}, lambda d: d.pop(gid, None) and None)
