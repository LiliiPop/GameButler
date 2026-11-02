"""界面主题（评测 #8，10-26 用户定：只做「能自选主题」的架构，具体样式另出设计文档）。

- 自带主题：static/themes/<id>.css，每个文件是一组 CSS 变量（颜色、透明度、模糊、阴影、圆角）。
  第一行注释里写「主题「名字」」。app.css 只用这些变量，不写死颜色，所以加一个主题 = 加一个文件。
- 自建主题：data/themes/<id>.json = {"name": 名字, "base": 基于哪个自带主题, "vars": {"--bg": "#F6EFF1", …}}，
  只写要改的变量，其余沿用 base。界面上可以导入 / 导出这个文件。
- 用哪个：设置里 appearance.theme（自带主题的 id，或「user:<id>」）。
"""
from __future__ import annotations

import re
from pathlib import Path

from . import jsonio

STATIC = Path(__file__).resolve().parents[1] / "static" / "themes"
_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")
_VAR = re.compile(r"--[a-z0-9-]{1,40}")
_BAD_VALUE = re.compile(r"[;{}<>\\]|url\s*\(|expression|@import", re.I)


def builtin() -> list[dict]:
    out = []
    for p in sorted(STATIC.glob("*.css")):
        head = p.read_text(encoding="utf-8")[:300]
        m = re.search(r"主题「([^」]+)」", head)
        if not m:
            raise ValueError(f"主题文件开头没写「主题「名字」」：{p.name}")
        out.append({"id": p.stem, "name": m.group(1)})
    return out


def _dir(cfg: dict) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "themes"


def user(cfg: dict) -> list[dict]:
    d = _dir(cfg)
    return [{"id": f"user:{p.stem}", **jsonio.read(p, {})} for p in sorted(d.glob("*.json"))] if d.exists() else []


def check(doc: dict) -> dict:
    """自建主题的格式检查：不合格就报错，不悄悄丢掉。"""
    name = str(doc.get("name") or "").strip()
    if not name or len(name) > 30:
        raise ValueError("主题要有名字（30 个字以内）")
    base = str(doc.get("base") or "glass")
    if base not in {t["id"] for t in builtin()}:
        raise ValueError(f"没有这个自带主题：{base}")
    vars_ = doc.get("vars")
    if not isinstance(vars_, dict) or not vars_:
        raise ValueError("主题里没有要改的变量（vars）")
    for k, v in vars_.items():
        if not _VAR.fullmatch(str(k)):
            raise ValueError(f"变量名不对：{k}（要写成 --小写字母和横线）")
        if not isinstance(v, str) or not v.strip() or len(v) > 200 or _BAD_VALUE.search(v):
            raise ValueError(f"「{k}」的值不能用：{v!r}")
    return {"name": name, "base": base, "vars": {str(k): v.strip() for k, v in vars_.items()}}


def save(cfg: dict, tid: str, doc: dict) -> dict:
    if not _ID.fullmatch(tid or ""):
        raise ValueError("主题编号只能用字母、数字、下划线和横线")
    doc = check(doc)
    jsonio.write(_dir(cfg) / f"{tid}.json", doc)
    return {"id": f"user:{tid}", **doc}


def delete(cfg: dict, tid: str):
    if not _ID.fullmatch(tid or ""):
        raise ValueError("主题编号不对")
    jsonio.remove(_dir(cfg) / f"{tid}.json")


def exists(cfg: dict, theme: str) -> bool:
    if theme.startswith("user:"):
        return (_dir(cfg) / f"{theme[5:]}.json").exists()
    return theme in {t["id"] for t in builtin()}
