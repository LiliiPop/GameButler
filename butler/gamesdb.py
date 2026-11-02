"""游戏记录：每个挂载过的游戏一份 data/games/<游戏>.json，是这个游戏全部设置的唯一来源。

记录里有什么：
  name / type / refresh（必填，北京时间 HH:MM）/ 工具路径（project_dir 或 exe）/ 模拟器实例 / 判定规则 / 超时……
  followed      true = 挂着；false = 取消挂载（记录和数据都留着，重新挂载时接上）
  preset        挂载时套用的预设 id（config/presets/），只用来显示和重新识别
  project_name  MaaFramework 项目的 interface 名称（重新挂载时认出是同一个脚本）

config/butler.toml 只放这台电脑的设置（[machine]）。

载入后：cfg["games"] = 挂着的游戏；取消挂载的不在里面（调度、活动、主页都不出现），用 all_records() 读。
只有管家后台改记录（save），运行进程每次开始时重新读。
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

from . import jsonio

ROOT = Path(__file__).resolve().parent.parent
PRESETS = ROOT / "config" / "presets"


def load_config() -> dict:
    conf = ROOT / "config" / "butler.toml"
    if not conf.exists() and (ROOT / "config" / "butler.example.toml").exists():  # 第一次运行：用示例设置（11-02）
        import shutil
        shutil.copyfile(ROOT / "config" / "butler.example.toml", conf)
    with open(conf, "rb") as f:
        cfg = tomllib.load(f)
    m = cfg["machine"]
    d = Path(m.get("data_dir") or "data")  # 相对路径按管家文件夹算，整个文件夹搬到别处也能用
    m["data_dir"] = str(d if d.is_absolute() else (ROOT / d).resolve())
    cfg["games"] = {gid: g for gid, g in all_records(cfg).items() if g.get("followed", True)}
    return cfg


def games_dir(cfg: dict) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "games"


def all_records(cfg: dict) -> dict:
    """全部游戏记录（挂着的和取消挂载的），按添加顺序。"""
    out = []
    for p in sorted(games_dir(cfg).glob("*.json")):
        g = jsonio.read(p, None)
        out.append((g.get("order", 0), p.stem, g))
    return {gid: g for _, gid, g in sorted(out, key=lambda x: (x[0], x[1]))}


def record(cfg: dict, gid: str) -> dict:
    g = jsonio.read(games_dir(cfg) / f"{gid}.json", None)
    if g is None:
        raise KeyError(f"没有这个游戏：{gid}")
    return g


def save(cfg: dict, gid: str, g: dict):
    """写记录，并让当前进程里的 cfg 马上一致。"""
    if not re.fullmatch(r"[a-z0-9_]{1,20}", gid):
        raise ValueError(f"游戏 id 只能用小写字母、数字和下划线：{gid}")
    if not g.get("refresh"):
        raise ValueError("刷新时间是必填项")
    jsonio.write(games_dir(cfg) / f"{gid}.json", g)
    if g.get("followed", True):
        cfg.setdefault("games", {})[gid] = g
    else:
        cfg.setdefault("games", {}).pop(gid, None)


def delete(cfg: dict, gid: str):
    jsonio.remove(games_dir(cfg) / f"{gid}.json")
    cfg.setdefault("games", {}).pop(gid, None)


# ---------------------------------------------------------------- 预设
def presets() -> list[dict]:
    """config/presets/*.json：常见脚本的下载信息和调好的设置（挂载时套用）。"""
    out = [jsonio.read(p, None) for p in sorted(PRESETS.glob("*.json"))]
    return sorted(out, key=lambda x: x.get("order", 99))


def preset(pid: str) -> dict | None:
    return next((p for p in presets() if p["id"] == pid), None)


def match_preset(info: dict) -> dict | None:
    """识别结果 → 哪个预设：MaaFramework 项目按 interface 名称 / 文件夹名 / GitHub 地址，程序按文件名。"""
    path = info.get("path", "")
    names = {str(info.get("project_name") or "").lower(), Path(path).name.lower(), Path(path).parent.name.lower()}
    exe = Path(path).name.lower() if os.path.splitext(path)[1] else ""
    gh = str(info.get("github") or "").lower().rstrip("/")
    for p in presets():
        m = p.get("match") or {}
        if info.get("type") == "maa" and p.get("type") == "maa":
            if {n.lower() for n in m.get("names", [])} & names:
                return p
            if p.get("repo") and gh.endswith(p["repo"].lower()):
                return p
        if exe and exe in {e.lower() for e in m.get("exe", [])}:
            return p
    return None
