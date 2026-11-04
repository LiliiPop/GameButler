"""原神 BetterGI 一条龙：把 BetterGI 的一条龙配置当成管家的任务库。

- 任务库 = BetterGI 内置的一条龙任务 + User\\ScriptGroup 里的全部配置组 + 「🏁 结束后操作」
  配置组里的单项（脚本 / 路线）只读显示，具体布置在 BetterGI 里做；管家每次都读最新文件。
- 运行前：按当天计划改写一条龙配置文件（默认「默认配置.json」）——只改启用开关、顺序、管家里改过的选项和结束后操作，
  其余字段原样保留；改写前备份到 data\\bettergi_backup\\。BetterGI 正在运行时不写（它退出时会把内存里的配置存回去）。
- 管家里没改过的选项，运行时沿用 BetterGI 文件里的当前值（所以在 BetterGI 里改的选项会自动生效）；
  在 BetterGI 里改了「启用哪些项 / 顺序」时，用「从 BetterGI 同步」把当前设置导入默认任务预设。
- 启动：管家以管理员身份运行时直接启动（不弹确认）；否则用计划任务 \\GameButler\\BetterGI一条龙；都不行才直接启动（会弹确认）。
- 结果：按日志里的「一条龙任务执行: i/n」（内置任务）和「配置组 \"X\" 加载完成」（配置组）把每一项分开记录；
  没轮到的项记为「未运行」（不写失败，之后照常再跑）。
- 暂停 / 继续 / 停止：用 BetterGI 自带的「暂停」「取消任务」快捷键（User\\config.json 的 hotKeyConfig）。
  这两个键为空时，启动前由管家填上（默认 Ctrl + Shift + F9 / F10，全局注册）；你自己设过就用你的。
  管家按下快捷键来暂停 / 继续；停止时先按「取消任务」让 BetterGI 自己收手，20 秒没反应再强制结束。
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

from collections import Counter, deque

from .bgilog import OneDragonLog
from .runstate import NO_WINDOW, is_admin, kill_image, kill_tree
from .store import item_key

FINISH = "🏁 结束后操作"
HOTKEYS = {"suspend": ("suspendHotkey", "Ctrl + Shift + F9"), "cancel": ("cancelTaskHotkey", "Ctrl + Shift + F10")}
_VK_MOD = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B}


def _vk(name: str) -> int:
    n = name.strip()
    low = n.lower()
    if low in _VK_MOD:
        return _VK_MOD[low]
    if re.fullmatch(r"f([1-9]|1\d|2[0-4])", low):
        return 0x6F + int(low[1:])
    if len(n) == 1 and n.isalnum():
        return ord(n.upper())
    if re.fullmatch(r"d\d", low):
        return 0x30 + int(low[1])
    if re.fullmatch(r"numpad\d", low):
        return 0x60 + int(low[-1])
    named = {"pause": 0x13, "scroll": 0x91, "insert": 0x2D, "home": 0x24, "end": 0x23,
             "pageup": 0x21, "prior": 0x21, "pagedown": 0x22, "next": 0x22, "oem3": 0xC0}
    if low in named:
        return named[low]
    raise ValueError(f"不认识的按键：{name}")


def send_hotkey(spec: str):
    """模拟按下一个组合键，例如 "Ctrl + Shift + F9"（BetterGI 全局快捷键收得到；管家要和原神同为管理员身份）。"""
    if os.name != "nt":
        raise OSError("只在 Windows 上能按快捷键")
    import ctypes
    keys = [_vk(p) for p in spec.split("+") if p.strip()]
    if not keys:
        raise ValueError("快捷键是空的")
    ev = ctypes.windll.user32.keybd_event
    for k in keys:
        ev(k, 0, 0, 0)
        time.sleep(0.03)
    for k in reversed(keys):
        ev(k, 0, 2, 0)  # KEYEVENTF_KEYUP
        time.sleep(0.03)
COMPLETION = ["无", "关闭游戏", "关闭软件", "关闭游戏和软件", "关机"]
COUNTRIES = ["蒙德", "璃月", "稻妻", "须弥", "枫丹", "纳塔", "挪德卡莱"]
TREASURE = ["每天重复", "须臾树脂", "祝圣精华", "祝圣油膏", "大英雄的经验", "流浪者的经验", "精锻用魔矿", "摩拉"]

# 内置任务 → [(选项名, 配置字段, 类型, 可选值)]；类型：select / switch / int / str / checkbox
BUILTIN: dict[str, dict] = {
    "领取邮件": {"desc": "打开邮箱，全部领取。", "opts": []},
    "合成树脂": {"desc": "到合成台把原粹树脂合成浓缩树脂。", "opts": [
        ("合成台所在国家", "CraftingBenchCountry", "select", "countries"),
        ("保留原粹树脂数量", "MinResinToKeep", "int", None)]},
    "领取每日奖励": {"desc": "到冒险家协会领取每日委托奖励。", "opts": [
        ("冒险家协会所在国家", "AdventurersGuildCountry", "select", "countries"),
        ("领每日奖励时切换的队伍", "DailyRewardPartyName", "str", None)]},
    "领取尘歌壶奖励": {"desc": "进尘歌壶领好感和宝钱，并在阿圆处买洞天百宝物品。", "opts": [
        ("进入尘歌壶的方式", "SereniteaPotTpType", "select", ["地图传送", "尘歌壶道具"]),
        ("洞天百宝要买的物品", "SecretTreasureObjects", "checkbox", "treasure")]},
    "自动秘境": {"desc": "用原粹树脂刷秘境（按星期分别设置秘境请在 BetterGI 里改）。", "opts": [
        ("秘境", "DomainName", "select", "domains"),
        ("刷秘境用的队伍", "PartyName", "str", None),
        ("按星期使用不同秘境", "WeeklyDomainEnabled", "switch", None)]},
    "自动首领讨伐": {"desc": "讨伐指定首领（详细设置请在 BetterGI 里改）。", "opts": [
        ("首领", "AutoBossName", "str", None),
        ("首领讨伐队伍", "AutoBossTeamName", "str", None),
        ("指定讨伐次数", "AutoBossSpecifyRunCount", "switch", None),
        ("讨伐次数", "AutoBossRunCount", "int", None)]},
    "自动地脉花": {"desc": "刷地脉花（详细设置请在 BetterGI 里改）。", "opts": [
        ("地脉花一条龙模式", "LeyLineOneDragonMode", "switch", None),
        ("地脉花次数", "LeyLineRunCount", "int", None)]},
    "自动幽境危战": {"desc": "幽境危战（详细设置请在 BetterGI 里改）。", "opts": []},
}


def _read_json(path: Path) -> dict:
    """读 BetterGI 的配置文件；读不出来直接报错并指出是哪个文件。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise RuntimeError(f"BetterGI 的文件读不出来：{path}（{e}）") from e


_LOG_HEAD = re.compile(r"^\[\d\d:\d\d:\d\d\.\d+\] \[\w+\] ")  # BetterGI 日志每条的头一行


class LogTail:
    """跟着读日志：只读启动之后新写入的内容；不完整的最后一行留到下次。"""

    def __init__(self, pattern: str):
        self.pattern = pattern
        self.offsets: dict[str, int] = {}

    def skip_existing(self):
        for p in glob.glob(self.pattern):
            try:
                self.offsets[p] = os.path.getsize(p)
            except OSError:
                pass

    def read(self) -> list[str]:
        out = []
        for p in sorted(glob.glob(self.pattern)):
            try:
                with open(p, "rb") as f:
                    f.seek(self.offsets.get(p, 0))  # 启动后新出现的文件（例如跨午夜）从头读
                    data = f.read()
            except OSError:
                continue
            cut = data.rfind(b"\n")
            if cut < 0:
                continue
            self.offsets[p] = self.offsets.get(p, 0) + cut + 1
            out += [x.strip() for x in data[:cut].decode("utf-8", errors="replace").splitlines() if x.strip()]
        return out


class BetterGIGame:
    """接在 games.ReservedGame 之后使用（见 games.py 的 BetterGIAdapter）。"""

    # ---------- 路径 ----------
    @property
    def exe(self) -> Path:
        return Path(self.g["exe"])

    @property
    def root(self) -> Path:
        return self.exe.parent

    @property
    def config_name(self) -> str:
        return self.g.get("onedragon_config", "默认配置")

    @property
    def config_path(self) -> Path:
        return self.root / "User" / "OneDragon" / f"{self.config_name}.json"

    def load_config(self) -> dict:
        return _read_json(self.config_path)

    def script_groups(self) -> dict[str, dict]:
        out = {}
        for p in sorted(glob.glob(str(self.root / "User" / "ScriptGroup" / "*.json"))):
            d = _read_json(Path(p))
            out[d.get("name") or Path(p).stem] = d
        return out

    def domains(self) -> list[str]:
        tp = _read_json(self.root / "GameTask" / "AutoTrackPath" / "Assets" / "tp.json")
        names = []
        for area in tp.get("data", []):
            for pt in area.get("points", []):
                if str(pt.get("type", "")).endswith("Domain") and pt.get("name") and pt["name"] not in names:
                    names.append(pt["name"])
        return names

    # ---------- 任务库 ----------
    # ---------- BetterGI 之前先做的事（例如胡桃的米游社签到）：config 的 [games.genshin.pre_tasks] ----------
    def pre_tasks(self) -> dict:
        return dict(self.g.get("pre_tasks", {}))

    def task_names(self) -> list[str]:
        cfg = self._safe_config()
        names = list(self.pre_tasks()) + list(BUILTIN)
        names += [n for n in self.script_groups() if n not in names]
        names += [n for n in (cfg.get("TaskDefinitions") or {}).values() if n not in names]  # 其他（改过名的等）
        return names + [FINISH]

    def _safe_config(self) -> dict:
        """一条龙配置；BetterGI 里还没有这份配置（还没建过）时是空的，文件坏了直接报错。"""
        return self.load_config() if self.config_path.exists() else {}

    def _values(self, kind, cur):
        if kind == "countries":
            vals = list(COUNTRIES)
        elif kind == "domains":
            vals = self.domains()
        elif kind == "treasure":
            vals = list(TREASURE)
        else:
            vals = list(kind or [])
        for v in ([cur] if isinstance(cur, str) else (cur or [])):
            if v and v not in vals:
                vals.insert(0, v)
        return vals

    def current_choices(self, task: str, cfg: dict | None = None) -> dict:
        """BetterGI 文件里这一项的当前值（按名称的选择，格式同 MAA）。"""
        cfg = cfg if cfg is not None else self._safe_config()
        if task == FINISH:
            return {"完成后操作": cfg.get("CompletionAction") or "无"}
        out = {}
        for label, field, typ, _ in BUILTIN.get(task, {}).get("opts", []):
            v = cfg.get(field)
            if typ == "switch":
                out[label] = "Yes" if v else "No"
            elif typ in ("int", "str"):
                out[label] = {label: "" if v is None else str(v)}
            elif typ == "checkbox":
                out[label] = list(v or [])
            else:
                out[label] = v or ""
        return out

    def schema(self) -> dict:
        cfg = self._safe_config()
        groups = self.script_groups()
        options, tasks = {}, []
        for name in self.task_names():
            opt_names = []
            group_items = None
            if name in self.pre_tasks():
                desc = self.pre_tasks()[name].get("description") or "在启动 BetterGI 之前先打开的程序。"
                if name == "米游社签到":
                    from . import mys
                    if mys.logged_in(self.cfg):
                        desc = "已登录米游社：管家自己签到（不用胡桃），签到结果记在运行记录里。账号在「设置 → 米游社账号」管理。"
            elif name == FINISH:
                desc = "一条龙全部跑完后 BetterGI 做什么。选「关闭游戏和软件」最省事；管家另外会在 90 秒后兜底关闭。"
                options["完成后操作"] = {"type": "select", "label": "完成后操作", "description": "",
                                    "cases": [{"name": c, "label": "", "description": "", "sub": []} for c in COMPLETION],
                                    "default": cfg.get("CompletionAction") or "无"}
                opt_names = ["完成后操作"]
            elif name in BUILTIN:
                desc = BUILTIN[name]["desc"]
                for label, field, typ, vals in BUILTIN[name]["opts"]:
                    cur = cfg.get(field)
                    opt_names.append(label)
                    if typ in ("select", "checkbox"):
                        cases = self._values(vals, cur)
                        options[label] = {"type": typ, "label": label, "description": "",
                                          "cases": [{"name": c, "label": "", "description": "", "sub": []} for c in cases],
                                          "default": (list(cur or []) if typ == "checkbox" else (cur or (cases[0] if cases else "")))}
                    elif typ == "switch":
                        options[label] = {"type": "switch", "label": label, "description": "",
                                          "cases": [{"name": "Yes", "label": "开启", "description": "", "sub": []},
                                                    {"name": "No", "label": "关闭", "description": "", "sub": []}],
                                          "default": "Yes" if cur else "No"}
                    else:
                        options[label] = {"type": "input", "label": label, "description": "",
                                          "inputs": [{"name": label, "label": label, "description": "",
                                                      "default": "" if cur is None else str(cur),
                                                      "pipeline_type": "int" if typ == "int" else "string",
                                                      "verify": "^\\d+$" if typ == "int" else None}]}
            elif name in groups:
                projects = groups[name].get("projects", []) or []
                group_items = [{"name": p.get("name", ""), "folder": p.get("folderName", ""), "type": p.get("type", ""),
                                "enabled": p.get("status") == "Enabled", "schedule": p.get("schedule", "")}
                               for p in projects]
                on = sum(1 for p in group_items if p["enabled"])
                names = "、".join(p["name"] for p in group_items if p["enabled"])[:200]
                desc = (f"BetterGI 配置组：共 {len(group_items)} 项，启用 {on} 项（{names}）。"
                        "组里的单项在 BetterGI 里修改，管家每次读取最新内容。")
            else:
                desc = "BetterGI 一条龙里的任务（管家不认识它的选项，请在 BetterGI 里设置）。"
            t = {"name": name, "entry": "", "description": desc, "options": opt_names,
                 "mfa_choices": self.current_choices(name, cfg), "default_check": False, "placeholder": False,
                 "kind": "pre" if name in self.pre_tasks() else "finish" if name == FINISH else ("builtin" if name in BUILTIN else
                                                          ("group" if name in groups else "other"))}
            if group_items is not None:
                t["group_items"] = group_items
            # 长任务提醒：配置组里启用了特定脚本（例如锄地一条龙）。任务本身的 task_notices 由 games.decorate 加
            notes = [txt for sc, txt in self.g.get("script_notices", {}).items()
                     if any(p["enabled"] and p["name"] == sc for p in (group_items or []))]
            if notes:
                t["notice"] = " ".join(notes)
            tasks.append(t)
        return {"tasks": tasks, "options": options, "presets": [], "reserved": False,
                "bettergi": {"config": self.config_name, "config_path": str(self.config_path),
                             "exe": str(self.exe), "changed_outside": self.changed_outside()}}

    def enabled_items(self) -> list[dict]:
        """BetterGI 当前一条龙配置里启用的项（按顺序）+ 结束后操作。选项不写（运行时沿用 BetterGI 的值）。"""
        cfg = self._safe_config()
        defs = cfg.get("TaskDefinitions") or {}
        en = cfg.get("TaskEnabledList") or {}
        items = [{"task": defs[i], "choices": {}} for i in cfg.get("TaskOrder", []) if en.get(i) and i in defs]
        pre = [{"task": n, "choices": {}} for n, c in self.pre_tasks().items() if c.get("default", True)]
        return pre + items + [{"task": FINISH, "choices": {}}]

    def tool_routines(self) -> dict:
        """BetterGI 自己的一条龙设置（挂载时问你要不要一同导入）。"""
        items = self.enabled_items()
        return {"日常": items} if items else {}

    def seed(self) -> dict:
        """管家不带默认任务清单：挂载时选了「一同导入工具自带的预设」才导入 BetterGI 当前的一条龙（用户 10-26 定）。"""
        routines = {k: {"tasks": v} for k, v in self.tool_routines().items()} if self.g.get("import_tool_routines") else {}
        return {"default": next(iter(routines), ""), "routines": routines}

    # ---------- 改动检测 ----------
    def _state_path(self) -> Path:
        return Path(self.cfg["machine"]["data_dir"]) / "bettergi_state.json"

    def changed_outside(self) -> bool:
        """管家上次写入 / 同步之后，BetterGI 的一条龙配置又被改过（多半是在 BetterGI 里改的）。"""
        st = self._read_state()
        if "mtime" not in st or not self.config_path.exists():  # 还没同步过 / BetterGI 还没有这份配置
            return False
        return self.config_path.stat().st_mtime > float(st["mtime"]) + 1

    def mark_synced(self):
        mt = self.config_path.stat().st_mtime if self.config_path.exists() else 0
        self._update_state(lambda st: st.update(mtime=mt, time=datetime.now().isoformat(timespec="seconds")))

    # ---------- 写一条龙配置 ----------
    def write_plan(self, items: list[dict]) -> tuple[list[str], list[str]]:
        """按计划改写一条龙配置；返回（实际启用的任务名（按顺序，不含结束后操作），没写进去的选项说明）。
        要填数字的选项不是数字：这一项不写，按 BetterGI 里原来的值跑，并把原因交给调用方记进运行记录（用户 10-26 定）。"""
        cfg = self.load_config()
        raw = self.config_path.read_bytes()
        backup = Path(self.cfg["machine"]["data_dir"]) / "bettergi_backup" / \
            f"{datetime.now():%Y%m%d-%H%M%S}-{self.config_name}.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(raw)
        olds = sorted(backup.parent.glob("*.json"))
        for p in olds[:-30]:  # 只留最近 30 份
            try:
                p.unlink()
            except OSError:
                pass

        defs = cfg.setdefault("TaskDefinitions", {})
        by_name = {v: k for k, v in defs.items()}
        order, names, finish, unwritten = [], [], None, []
        for it in items:
            n = it["task"]
            if n == FINISH:
                finish = it
                continue
            if n in self.pre_tasks():
                continue  # 不属于 BetterGI
            if n in names:
                continue  # 一条龙里同一项只能出现一次
            if n not in by_name:
                tid = str(uuid.uuid4())
                defs[tid] = n
                by_name[n] = tid
            order.append(by_name[n])
            names.append(n)
            merged = self.current_choices(n, cfg)
            merged.update(it.get("choices") or {})
            for label, field, typ, _ in BUILTIN.get(n, {}).get("opts", []):
                if label not in (it.get("choices") or {}):
                    continue  # 管家里没改过的选项：保持 BetterGI 的值
                v = merged[label]
                if typ == "switch":
                    cfg[field] = (v == "Yes")
                elif typ == "int":
                    v = v.get(label, "") if isinstance(v, dict) else v
                    try:
                        cfg[field] = int(str(v).strip() or 0)
                    except ValueError:
                        unwritten.append(f"{n}「{label}」填的是「{v}」，不是数字，没写进去，这次按 BetterGI 里的设定（{cfg.get(field)}）跑")
                elif typ == "str":
                    cfg[field] = str(v.get(label, "") if isinstance(v, dict) else v)
                elif typ == "checkbox":
                    cfg[field] = list(v or [])
                else:
                    cfg[field] = str(v)
        cfg["TaskEnabledList"] = {tid: (tid in order) for tid in defs}
        cfg["TaskOrder"] = order + [tid for tid in cfg.get("TaskOrder", []) if tid not in order and tid in defs] + \
            [tid for tid in defs if tid not in order and tid not in cfg.get("TaskOrder", [])]
        self._deferred_close = ""
        if finish is not None:
            act = (finish.get("choices") or {}).get("完成后操作") or self.current_choices(FINISH, cfg)["完成后操作"]
            act = act if act in COMPLETION else "无"
            from . import pcgacha
            if pcgacha.conf_of(self.g) and act in ("关闭游戏", "关闭游戏和软件"):
                # 11-02：要读抽卡资源：先不让 BetterGI 关游戏，管家读完再按这个设置关
                self._deferred_close, act = act, "无"
            cfg["CompletionAction"] = act
        text = json.dumps(cfg, ensure_ascii=False, indent=2).replace("\n", "\r\n")
        tmp = self.config_path.with_suffix(".管家写入中")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.config_path)
        self.mark_synced()
        return names, unwritten

    # ---------- 双向同步（模块 C）：管家里改了就写回 BetterGI ----------
    def _read_state(self) -> dict:
        from . import jsonio
        return jsonio.read(self._state_path(), {})

    def _update_state(self, fn):
        from . import jsonio
        return jsonio.update(self._state_path(), {}, fn)

    def running(self) -> bool:
        from .runstate import is_running
        return is_running(self.exe.name)

    def bgi_names(self) -> list[str]:
        cfg = self._safe_config()
        defs = cfg.get("TaskDefinitions") or {}
        en = cfg.get("TaskEnabledList") or {}
        return [defs[i] for i in cfg.get("TaskOrder", []) if en.get(i) and i in defs]

    def plan_names(self, items: list[dict]) -> list[str]:
        out = []
        for it in items:
            if it["task"] in self.pre_tasks() or it["task"] == FINISH or it["task"] in out:
                continue
            out.append(it["task"])
        return out

    def sync_status(self, items: list[dict]) -> dict:
        st = self._read_state()
        mine, theirs = self.plan_names(items), self.bgi_names()
        return {"pending": bool(st.get("pending")), "changed_outside": self.changed_outside(),
                "running": self.running(), "same": mine == theirs, "butler": mine, "bettergi": theirs,
                "last_sync": st.get("time", "")}

    def sync(self, items: list[dict], force: bool = False) -> dict:
        """把（今天要跑的）计划写回 BetterGI 的一条龙配置。
        BetterGI 开着：先记「待写入」，等它关掉再写（它退出时会把自己那份存回去）。
        BetterGI 那边在上次同步后改过、两边又不一样：不写，返回 conflict，由你选以哪边为准（force=True 以管家为准）。"""
        mine, theirs = self.plan_names(items), self.bgi_names()
        if self.running():
            self._update_state(lambda st: st.update(pending=True))
            return {"result": "pending", "msg": "BetterGI 开着：等它关掉后写入"}
        if not force and self.changed_outside() and mine != theirs:
            return {"result": "conflict", "butler": mine, "bettergi": theirs,
                    "msg": "BetterGI 里的一条龙在上次同步后改过，和管家的不一样"}
        names, unwritten = self.write_plan(items)
        self._update_state(lambda st: st.pop("pending", None) and None)
        return {"result": "written", "names": names, "unwritten": unwritten,
                "msg": f"已写入 BetterGI「{self.config_name}」" + (f"；{'；'.join(unwritten)}" if unwritten else "")}

    def write_group(self, group: str, projects: list[dict]) -> dict:
        """在管家里开关、调整配置组（ScriptGroup）里单条脚本的顺序，写回配置组文件（先备份）。"""
        if self.running():
            raise RuntimeError("BetterGI 开着：先关掉它再改配置组")
        path = None
        for p in sorted(glob.glob(str(self.root / "User" / "ScriptGroup" / "*.json"))):
            d = _read_json(Path(p))
            if (d.get("name") or Path(p).stem) == group:
                path = Path(p)
                break
        if not path:
            raise RuntimeError(f"没找到配置组「{group}」")
        raw = path.read_bytes()
        backup = Path(self.cfg["machine"]["data_dir"]) / "bettergi_backup" / f"{datetime.now():%Y%m%d-%H%M%S}-group-{path.name}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(raw)
        d = json.loads(raw.decode("utf-8-sig"))
        old = d.get("projects", []) or []
        key = lambda p: (p.get("name", ""), p.get("folderName", p.get("folder", "")))
        by = {key(p): p for p in old}
        out = []
        for want in projects:
            p = by.pop(key(want), None)
            if p is None:
                continue
            p["status"] = "Enabled" if want.get("enabled") else "Disabled"
            out.append(p)
        out += list(by.values())  # 界面上没列到的保持原样，放在后面
        for i, p in enumerate(out):
            if "index" in p:
                p["index"] = i + 1
        d["projects"] = out
        text = json.dumps(d, ensure_ascii=False, indent=2).replace("\n", "\r\n")
        tmp = path.with_suffix(".管家写入中")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return {"ok": True, "enabled": sum(1 for p in out if p.get("status") == "Enabled"), "total": len(out)}

    # ---------- 快捷键（暂停 / 取消任务） ----------
    @property
    def user_config_path(self) -> Path:
        return self.root / "User" / "config.json"

    def hotkeys(self) -> dict:
        """BetterGI 当前设置的暂停 / 取消任务快捷键（没设是空字符串）。"""
        hk = _read_json(self.user_config_path).get("hotKeyConfig", {})
        return {k: hk.get(field, "") for k, (field, _) in HOTKEYS.items()}

    def ensure_hotkeys(self) -> list[str]:
        """暂停 / 取消任务快捷键为空时填上（BetterGI 没在运行时才改；它运行中改了也会被它覆盖）。返回填了哪些。"""
        p = self.user_config_path
        text = p.read_text(encoding="utf-8-sig")
        d = json.loads(text)
        hk = d.setdefault("hotKeyConfig", {})
        filled = []
        for k, (field, default) in HOTKEYS.items():
            if not str(hk.get(field, "")).strip():
                hk[field] = self.g.get(f"{k}_hotkey", default)
                hk[field + "Type"] = "GlobalRegister"
                filled.append(f"{field}={hk[field]}")
        if filled:
            bdir = Path(self.cfg["machine"]["data_dir"]) / "bettergi_backup"
            bdir.mkdir(parents=True, exist_ok=True)
            (bdir / f"config.json.{datetime.now():%Y%m%d-%H%M%S}").write_text(text, encoding="utf-8")
            tmp = p.with_suffix(".管家写入中")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, p)
        return filled

    def press(self, which: str) -> str:
        """按 BetterGI 的暂停（suspend，再按一次继续）或取消任务（cancel）快捷键。返回按的键。"""
        spec = self.hotkeys().get(which, "")
        if not spec:
            raise RuntimeError("BetterGI 里没有设置这个快捷键（管家下次启动 BetterGI 前会自动设上）")
        send_hotkey(spec)
        return spec

    # ---------- 启动 ----------
    def launch(self, ctx, args: list[str]):
        """返回 (Popen, 说明)。"""
        if os.name != "nt":
            return subprocess.Popen([str(self.exe), *args], cwd=str(self.root)), "直接启动"
        if is_admin():
            return subprocess.Popen([str(self.exe), *args], cwd=str(self.root)), "直接启动（管家有管理员权限，不弹确认）"
        task = self.g.get("launch_task")
        if task and self.config_name == self.g.get("launch_task_config", "默认配置") and \
                subprocess.run(["schtasks", "/Query", "/TN", task], capture_output=True,
                               creationflags=NO_WINDOW).returncode == 0:
            p = subprocess.Popen(["schtasks", "/Run", "/TN", task], creationflags=NO_WINDOW,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return p, f"通过计划任务「{task}」启动（免确认）"
        try:
            return subprocess.Popen([str(self.exe), *args], cwd=str(self.root)), \
                "直接启动（管家没有管理员权限，可能弹出确认窗口）"
        except OSError as e:
            if getattr(e, "winerror", 0) != 740:
                raise
            os.startfile(str(self.exe), arguments=" ".join(args), cwd=str(self.root))  # type: ignore[call-arg]
            return None, "以管理员身份启动（会弹出确认窗口）"

    def open_gui(self):
        """「去 BetterGI 布置」：打开 BetterGI 界面（不带参数）。"""
        if is_admin() or os.name != "nt":
            subprocess.Popen([str(self.exe)], cwd=str(self.root))
        else:
            os.startfile(str(self.exe), cwd=str(self.root))  # type: ignore[call-arg]

    # ---------- 日志 ----------
    def _log_lines(self, since: float, offsets: dict) -> list[str]:
        pattern = self.g.get("log_glob") or str(self.root / "log" / "better-genshin-impact*.log")
        lines = []
        for path in glob.glob(pattern):
            try:
                if os.path.getmtime(path) < since - 5:
                    continue
                with open(path, "rb") as f:
                    f.seek(offsets.get(path, 0))
                    data = f.read()
                    offsets[path] = f.tell()
                lines += data.decode("utf-8", errors="replace").splitlines()
            except OSError:
                continue
        return lines

    def run_pre(self, it: dict, ctx) -> dict:
        """打开一个程序放在后台（已经在运行就不重复打开），不等它结束。"""
        c = self.pre_tasks()[it["task"]]
        key = item_key(it)
        exe = c.get("exe", "")
        ctx.emit("task_start", task=key, attempt=1)
        name = os.path.basename(exe)
        from . import mys
        if c.get("kind") == "mys_sign" or (it["task"] == "米游社签到" and mys.logged_in(self.cfg)):
            # 11-02：扫码登录过米游社 → 管家自己签到（不用胡桃），结果看得到；没登录、也没配胡桃 → 提示去登录
            if mys.logged_in(self.cfg) or not exe:
                try:
                    ok, why = mys.sign_all(self.cfg)
                except Exception as e:
                    ok, why = False, f"签到出错：{type(e).__name__}: {e}"
                ev = {"task": key, "attempt": 1, "result": "succeeded" if ok else "failed", "detail": why,
                      "minutes": 0, "focus": [], "flags": [], "shots": []}
                ctx.emit("task_end", **ev)
                return {**ev, "attempts": 1}
        if ctx.is_running(name):
            res, why = "succeeded", f"{name} 已经在运行，没有重复打开"
        elif not os.path.exists(exe):
            res, why = "failed", f"找不到 {exe}"
        else:
            try:
                if os.name == "nt":
                    os.startfile(exe, cwd=os.path.dirname(exe))  # type: ignore[call-arg]
                else:
                    subprocess.Popen([exe], cwd=os.path.dirname(exe))
                time.sleep(int(c.get("wait_s", 5)))
                res, why = "succeeded", c.get("done_text") or f"已打开 {name}（在后台运行）"
            except OSError as e:
                res, why = "failed", f"打开失败：{e}"
        ev = {"task": key, "attempt": 1, "result": res, "detail": why, "minutes": 0, "focus": [], "flags": [], "shots": []}
        ctx.emit("task_end", **ev)
        return {**ev, "attempts": 1}

    # ---------- 运行 ----------
    def run(self, items: list[dict], ctx) -> dict:
        from . import pcres  # 开关开着时：跑之前把原神调成 1920×1080 窗口化，跑完恢复
        return pcres.wrap(self.cfg, self.gid, ctx, lambda: self._run(items, ctx))

    def _run(self, items: list[dict], ctx) -> dict:
        g = self.g
        exe_name = self.exe.name
        items = [it for it in items if it["task"] in self.task_names()]
        pre_results = []
        for it in items:  # 先做 BetterGI 之前的事（例如打开胡桃签到）
            if it["task"] in self.pre_tasks():
                pre_results.append(self.run_pre(it, ctx))
        if not [it for it in items if it["task"] not in self.pre_tasks()]:
            return {"ok": all(r["result"] == "succeeded" for r in pre_results), "results": pre_results}
        if ctx.is_running(exe_name):
            ctx.emit("fatal", reason="BetterGI 正在运行。请先关掉它（它退出时会把自己的一条龙配置存回去，覆盖管家布置的内容）")
            return {"ok": False, "results": pre_results}
        try:
            names, unwritten = self.write_plan(items)
        except Exception as e:
            ctx.emit("fatal", reason=f"写一条龙配置失败：{e}")
            return {"ok": False, "results": []}
        keys = {}
        for it in items:
            keys.setdefault(it["task"], item_key(it))
        finish_key = keys.get(FINISH)
        ctx.emit("info", msg=f"已写入一条龙配置「{self.config_name}」：{'、'.join(names) or '（没有任务）'}")
        for w in unwritten:
            ctx.emit("warn", msg=w)
        if not names:
            ctx.emit("fatal", reason="计划里没有可以交给 BetterGI 的任务")
            return {"ok": False, "results": pre_results}

        try:
            filled = self.ensure_hotkeys()
            if filled:
                ctx.emit("info", msg=f"已在 BetterGI 里设好暂停 / 取消任务快捷键：{'、'.join(filled)}")
        except Exception as e:
            ctx.emit("warn", msg=f"没能设置 BetterGI 的暂停 / 取消任务快捷键（暂停功能不可用）：{e}")
        tail = LogTail(self.g.get("log_glob") or str(self.root / "log" / "better-genshin-impact*.log"))
        tail.skip_existing()  # 启动前已有的日志一律不看（含当天的旧运行）
        try:
            proc, how = self.launch(ctx, ["--startOneDragon", self.config_name])
        except Exception as e:
            ctx.emit("fatal", reason=f"启动 BetterGI 失败：{e}")
            return {"ok": False, "results": []}
        ctx.emit("info", msg=how)
        if proc is not None:
            ctx.set_runner(proc.pid)

        t0 = time.monotonic()
        per = g.get("task_timeouts", {})
        timeout_s = int(max(g.get("timeout", 180), sum(per.get(n, g.get("item_timeout", 30)) for n in names)) * 60)
        wait = [exe_name] + list(g.get("wait_processes", []))
        seen_at = time.monotonic()
        results: dict[str, dict] = {}
        log = OneDragonLog(self.config_name, names)
        cur_t0 = None
        overall, overall_why = None, ""

        def handle(evs):
            nonlocal cur_t0, overall, overall_why
            for ev in evs:
                kind = ev[0]
                if kind == "start":
                    cur_t0 = time.monotonic()
                    ctx.emit("task_start", task=keys.get(ev[1], ev[1]), attempt=1)
                elif kind == "end":
                    _, name, res, why, focus = ev
                    k = keys.get(name, name)
                    e = {"task": k, "attempt": 1, "result": res, "detail": why,
                         "minutes": round((time.monotonic() - (cur_t0 or time.monotonic())) / 60, 1),
                         "focus": focus, "flags": [], "shots": []}
                    if res == "succeeded" and hasattr(self, "pc_evidence"):  # 留证：日志里这一项结束的那一刻截原神窗口（11-02）
                        evf = self.pc_evidence(k, name)
                        if evf:
                            e["evidence"] = evf
                    ctx.emit("task_end", **e)
                    results[k] = {**e, "attempts": 1}
                    cur_t0 = None
                elif kind == "warn":
                    ctx.emit("warn", msg=ev[1])
                elif kind == "focus":
                    ctx.emit("focus", text=ev[1])
                elif kind == "over":
                    overall, overall_why = ev[1], ev[2]

        def finish_item(res, why):
            handle(log.close(res, why))

        # 11-04：每一项的卡死判断（「卡死处理」开着时）：
        # - 不出声：这一项开始后 BetterGI 日志 10 分钟没有一行新内容（「圣遗物实时评分」这种不会自己结束的脚本跑了 8 小时）
        # - 原地打转：10 分钟里日志只是那几行在重复（数字不算，如坐标），其中一行出现了 ≥ 40 次，最近一分钟还在出
        from . import settings as SET
        stall_s = 600 if SET.get(self.cfg, "scheduler").get("stuck_restart") else 0
        line_at = time.monotonic()
        lines = deque(maxlen=5000)  # (时间, 去掉数字的日志内容)
        stalled = ""

        def looping(now):
            if cur_t0 is None or now - cur_t0 < stall_s:
                return ""
            recent = [m for t, m in lines if now - t <= stall_s and t >= cur_t0]
            if not recent:
                return ""
            c = Counter(recent)
            top, hits = c.most_common(1)[0]
            if "暂停" in top:  # 「当前获取焦点的窗口为: explorer，不是原神，暂停」：你切走了窗口，BetterGI 自己在等，不算卡住
                return ""
            if len(c) <= 8 and hits >= 40 and any(m == top and now - t <= 60 for t, m in lines):
                return f"BetterGI 日志 {stall_s // 60} 分钟里只是这几行在重复（{'；'.join(m[:30] for m, _ in c.most_common(3))}），没有进展"
            return ""

        while overall is None:
            time.sleep(3)
            got = tail.read()
            if got:
                line_at = time.monotonic()
            for s in got:
                t = s.strip()
                if t and not _LOG_HEAD.match(t):  # 日志是「[时间] [级别] [..] 类名」一行 + 内容一行：只数内容
                    lines.append((time.monotonic(), re.sub(r"\d+(\.\d+)?", "#", t)[:80]))
                handle(log.feed(s))
                if overall:
                    break
            if overall:
                break
            now = time.monotonic()
            if stall_s and cur_t0 is not None and not ctx.rs.suspended():
                if now - max(line_at, cur_t0) > stall_s:
                    stalled = f"BetterGI 日志 {stall_s // 60} 分钟没有新内容（这一项一直没有输出，可能是不会自己结束的脚本，或卡住了）"
                else:
                    stalled = looping(now)
            if stalled or ctx.stop_requested():
                why = "已手动停止" if not stalled else stalled
                try:  # 先让 BetterGI 自己取消任务（暂停中也一样），等它在日志里确认
                    self.press("cancel")
                    t_c = time.monotonic()
                    while time.monotonic() - t_c < 20:
                        time.sleep(2)
                        if any("任务被取消" in s for s in tail.read()):
                            why = "已手动停止（BetterGI 已取消任务）"
                            break
                except Exception as e:
                    ctx.emit("warn", msg=f"没能让 BetterGI 自己取消任务，直接结束：{e}")
                ctx.rs.set_suspended(None)
                if stalled:  # 卡住的这一项记「卡住」（算失败，按重试规则再跑）；后面没轮到的照常记「未运行」，之后再跑
                    finish_item("stalled", stalled)
                    overall, overall_why = "stalled", stalled
                    break
                finish_item("stopped", why)
                overall, overall_why = "stopped", why
                break
            if ctx.rs.suspended():  # 暂停期间不算超时
                t0 += 3
                if cur_t0 is not None:
                    cur_t0 += 3
            if time.monotonic() - t0 > timeout_s:
                finish_item("timeout", f"超过 {timeout_s // 60} 分钟未完成")
                overall, overall_why = "timeout", "超时"
                break
            if (proc is not None and proc.poll() is None) or any(ctx.is_running(p) for p in wait):
                seen_at = time.monotonic()
                continue
            if time.monotonic() - seen_at > 30:  # BetterGI 已经不在了，日志里也没有结束标志
                finish_item("failed", "BetterGI 退出了，日志里没有结束标志")
                overall, overall_why = "failed", "BetterGI 退出了，日志里没有结束标志"

        if overall in ("timeout", "stopped", "stalled"):
            if proc is not None and proc.poll() is None:
                kill_tree(proc.pid)
            for exe in [exe_name] + list(g.get("processes", [])):
                kill_image(exe)
        # 没执行到的项
        for n in names:
            k = keys.get(n, n)
            if k not in results:
                # 没轮到的项不算失败：记「未运行」（stopped 不写进当天状态，界面显示未运行，之后照常再跑）
                why = {"stopped": "未运行（已手动停止）", "cancelled": "未运行（一条龙在 BetterGI 里被中断）",
                       "timeout": "未运行（一条龙超时）",
                       "stalled": "未运行（前面一项卡住，一条龙停下了）"}.get(overall, "未运行（一条龙中途结束）")
                res = "stopped"
                ctx.emit("task_end", task=k, attempt=1, result=res, detail=why, minutes=0, focus=[], flags=[], shots=[])
                results[k] = {"task": k, "attempt": 1, "attempts": 1, "result": res, "detail": why, "minutes": 0,
                              "focus": [], "flags": [], "shots": []}
        # 读抽卡资源（11-02）：一条龙做完、游戏还开着时读；关游戏的「结束后操作」推到读完以后由管家来做
        if overall == "succeeded" and hasattr(self, "read_gacha_pc"):
            later = getattr(self, "_deferred_close", "")
            self.read_gacha_pc(ctx, close=bool(later))
            if later == "关闭游戏和软件" and ctx.is_running(exe_name):
                kill_image(exe_name)
        elif getattr(self, "_deferred_close", "") and overall not in ("timeout", "stopped"):  # 没做完也照原设置关
            for e in list(g.get("processes", [])) + ([exe_name] if self._deferred_close == "关闭游戏和软件" else []):
                if e != "BetterGI.exe" or self._deferred_close == "关闭游戏和软件":
                    if ctx.is_running(e):
                        kill_image(e)
        # 结束后操作：等 BetterGI 自己关闭游戏和软件，超时兜底
        if finish_key and overall == "succeeded":
            ctx.emit("task_start", task=finish_key, attempt=1)
            t1 = time.monotonic()
            close = list(g.get("close_after", [exe_name]))
            grace = time.monotonic() + int(g.get("close_grace_s", 90))
            while time.monotonic() < grace and any(ctx.is_running(e) for e in close):
                time.sleep(3)
            left = [e for e in close if ctx.is_running(e)]
            for e in left:
                kill_image(e)
            why = "BetterGI 已按设置自行关闭" if not left else f"一条龙已结束，但 90 秒内没有自己关闭，已强制结束：{'、'.join(left)}"
            ev = {"task": finish_key, "attempt": 1, "result": "succeeded", "detail": why,
                  "minutes": round((time.monotonic() - t1) / 60, 1), "focus": [], "flags": [], "shots": []}
            ctx.emit("task_end", **ev)
            results[finish_key] = {**ev, "attempts": 1}
        ctx.set_runner(0)
        self.mark_synced()  # BetterGI 退出时会再存一次配置，不算用户改动
        out = pre_results + list(results.values())
        ctx.emit("info", msg=f"一条龙结果：{overall_why}")
        return {"ok": overall == "succeeded" and all(r["result"] in ("succeeded", "exhausted") for r in out),
                "results": out, "stopped": overall in ("stopped", "cancelled")}


def forget(cfg: dict, gid: str):
    """彻底删除：和 BetterGI 的同步状态。写配置前的备份（bettergi_backup）是你 BetterGI 原来的设置，留着。"""
    from . import gamesdb as GD
    from . import jsonio
    if GD.record(cfg, gid).get("type") == "bettergi":
        jsonio.remove(Path(cfg["machine"]["data_dir"]) / "bettergi_state.json")
