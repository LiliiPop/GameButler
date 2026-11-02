"""界面批注（10-24）：用户在界面上点「✎ 批注」，点任意按钮 / 文字写意见，存在 data/ui_notes.json，开发时直接读。"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from . import jsonio
from .timeutil import BJ


def _p(cfg) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "ui_notes.json"


def load(cfg) -> list[dict]:
    return jsonio.read(_p(cfg), [])  # 没有文件 = 还没有批注；坏了直接报错


def add(cfg, body: dict) -> dict:
    n = {"id": f"n{int(time.time() * 1000)}", "time": datetime.now(BJ).strftime("%Y-%m-%d %H:%M"), "status": "open"}
    for k in ("page", "target", "text", "path", "comment", "rect", "viewport", "theme", "kind", "change"):
        if k in body:
            n[k] = body[k]
    if not str(n.get("comment", "")).strip():
        raise ValueError("批注内容是空的")

    def fn(notes):
        n["no"] = max([x.get("no", 0) for x in notes] + [0]) + 1
        notes.append(n)
    jsonio.update(_p(cfg), [], fn)
    return n


def update(cfg, nid: str, body: dict) -> list[dict]:
    def fn(notes):
        for n in notes:
            if n["id"] == nid:
                if "comment" in body:
                    n["comment"] = str(body["comment"])
                if body.get("status") in ("open", "done"):
                    n["status"] = body["status"]
    return jsonio.update(_p(cfg), [], fn)


def delete(cfg, nid: str) -> list[dict]:
    return jsonio.update(_p(cfg), [], lambda notes: [n for n in notes if n["id"] != nid])
