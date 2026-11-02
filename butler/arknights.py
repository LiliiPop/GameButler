"""明日方舟 MAA（MaaAssistantArknights）的接法（总纲 10-23，离线写好，还没有实机测过——用户没装明日方舟）。

两种情况，添加脚本时按选的程序认：
1. maa-cli（maa.exe，官方命令行版）：管家用自己的配置目录（data/maa_ark/<游戏>/，用 MAA_CONFIG_DIR 指过去，不动用户自己的），
   写好连接设置（MuMu 实例的 adb 地址）和任务文件，每个任务跑一次 `maa run <任务>`，看退出码。
   任务：开始唤醒（StartUp）、刷理智（Fight，默认不吃理智药、不碎石）、公招（Recruit）、基建（Infrast）、
   信用商店（Mall）、领奖励（Award）。参数按 MAA 集成文档的字段名。
2. MAA 图形界面（MAA.exe，里面有 MaaCore.dll）：没法逐项控制，只能整体跑一次「一键长草」——
   需要用户在 MAA 设置里打开「启动 MAA 后直接运行」和「完成后退出 MAA」，管家启动它、等它退出。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

TASKS = {
    "开始唤醒": {"type": "StartUp", "params": {"client_type": "Official", "start_game_enabled": True}},
    "刷理智": {"type": "Fight", "params": {"stage": "", "medicine": 0, "stone": 0}},
    "公招": {"type": "Recruit", "params": {"refresh": True, "select": [4], "confirm": [3, 4], "times": 4}},
    "基建": {"type": "Infrast", "params": {"mode": 0, "facility": ["Mfg", "Trade", "Power", "Control", "Reception", "Office", "Dorm"],
                                         "drones": "_NotUse", "dorm_trust_enabled": True}},
    "信用商店": {"type": "Mall", "params": {"shopping": True, "buy_first": ["招聘许可", "龙门币"], "blacklist": ["家具零件"]}},
    "领奖励": {"type": "Award", "params": {"award": True, "mail": True}},
}
OPTIONS = {"刷理智": {"关卡": ("stage", "", "空 = 上次打的关卡，例如 1-7、CE-6")}}


def is_cli(exe: str) -> bool:
    d = Path(exe).parent
    return Path(exe).name.lower() == "maa.exe" and not (d / "MaaCore.dll").exists()


def commands(g: dict) -> dict:
    """生成 CommandGame 用的命令表。"""
    if not is_cli(g.get("exe", "")):
        return {"一键长草": {"args": [], "timeout": 120, "exit_ok_means_done": True,
                          "description": "启动 MAA 图形界面，跑它自己设置好的一键长草，等它退出。"
                                         "要先在 MAA 设置里打开「启动 MAA 后直接运行」和「完成后退出 MAA」。"}}
    out = {}
    for name, t in TASKS.items():
        c = {"args": ["run", f"gb_{t['type']}", "--batch"], "timeout": 60 if t["type"] != "Fight" else 120,
             "exit_ok_means_done": True}
        if name in OPTIONS:
            for label, (field, dflt, hint) in OPTIONS[name].items():
                c.setdefault("defaults", {})[label] = dflt
                c.setdefault("help", {})[label] = hint
        out[name] = c
    return out


def _toml_val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_val(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def prepare(cfg: dict, gid: str, address: str, adb: str, choices: dict | None = None) -> dict:
    """写管家自己的 maa-cli 配置目录（连接 + 任务文件）。返回给子进程的环境变量。"""
    root = Path(cfg["machine"]["data_dir"]) / "maa_ark" / gid
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "tasks").mkdir(parents=True, exist_ok=True)
    (root / "profiles" / "default.toml").write_text(
        "[connection]\n" f"adb_path = {_toml_val(adb)}\n" f"address = {_toml_val(address)}\n" 'config = "General"\n',
        encoding="utf-8")
    for name, t in TASKS.items():
        params = dict(t["params"])
        for label, (field, _, _) in OPTIONS.get(name, {}).items():
            v = (choices or {}).get(label)
            if isinstance(v, dict):
                v = v.get(label)
            if v not in (None, ""):
                params[field] = v
        lines = ["[[tasks]]", f"name = {_toml_val(name)}", f"type = {_toml_val(t['type'])}", "", "[tasks.params]"]
        lines += [f"{k} = {_toml_val(v)}" for k, v in params.items()]
        (root / "tasks" / f"gb_{t['type']}.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dict(os.environ, MAA_CONFIG_DIR=str(root))
