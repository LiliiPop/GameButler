"""各类游戏工具的接入（适配器）。

管家对每个游戏只关心四件事：有哪些任务和选项（schema）、首次生成的任务预设（seed）、
怎么跑一批任务（run，过程中按统一格式输出事件）、让出电脑时要关掉什么（processes）。

按工具类型不同的事都在这个文件里（评测 10-26：别的模块不再判断「是不是 BetterGI / MAA」）：
  记录层（游戏记录本身，取消挂载的也能用，类方法）：path_field、uses_emulator、record_problem、fill_record、
    same_tool、check_items —— 挂载、找工具、检查工具、模拟器调度用。
  能力（适配器实例）：can_suspend / press、tick、has_gui / open_gui、can_import / import_items、
    evidence_tasks、write_group、sync_plan —— 网页接口和后台小循环用；不支持的工具用基类的默认值。

type = "maa"       MaaFramework 系工具（MaaYuan / MaaTOT / MaaLYSK / MaaSH / 剑三无界），
                   由 runner/maa_runner.py 逐任务执行。控制器支持 ADB 模拟器和 Win32 窗口。
type = "bettergi"  原神 BetterGI（布置一条龙后启动，读日志逐项记录），见 bettergi.py
type = "m7a"       崩铁 三月七小助手（命令行启动，等进程退出）
type = "command"   自己添加的命令行脚本（输出存进 data/maafw/<游戏>/stdout.log，从里面找成功标志和脚本信号）
type = "maa_ark"   明日方舟 MAA，见 arknights.py

事件格式（写进 data/runs/<日期>/<游戏>-<时间>.jsonl，每行一个 JSON）：
  meta / info / warn / fatal / task_start / task_end / recovery / summary
task_end：{task, attempt, result, detail, minutes, focus[], flags[], shots[]}
result：succeeded / exhausted / failed / timeout / stalled / stopped
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import judge as J
from . import jsonio
from . import signals as SIG
from .mfa import Project, deep_merge
from .runstate import kill_image, kill_tree, NO_WINDOW
from .store import item_key
from .timeutil import game_day

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "runner" / "maa_runner.py"
RUNTIME_PY = ROOT / "runtime" / "python" / "python.exe"
STUCK_MINUTES = 10    # 卡死处理：画面多久没变化算卡住
SAFETY_MINUTES = 90   # 卡死处理开着时每项的兜底最长时间

KIND_NAMES = {"maa": "MAA 工具", "bettergi": "BetterGI", "m7a": "三月七小助手", "command": "命令行工具",
              "maa_ark": "明日方舟 MAA"}


def emulator_of(g: dict) -> str:
    """跑在哪个 MuMu 实例上（不是模拟器游戏返回空）。"""
    return g.get("emulator", "") if type_class(g).uses_emulator(g) else ""


def kind(g: dict) -> str:
    return g.get("type", "maa")


def available(g: dict) -> tuple[bool, str]:
    """这个游戏现在能不能用（工具路径存在、类型已支持）。"""
    why = type_class(g).record_problem(g)
    return not why, why


_cache: dict = {}


def adapter(cfg: dict, gid: str):
    """游戏的适配器。按游戏记录缓存（读 interface.json 比较慢）；记录一改（gamesdb.save 换了新的字典）就重新建。"""
    g = cfg["games"][gid]
    hit = _cache.get(gid)
    if hit and hit[0] is g and hit[1].cfg is cfg:
        return hit[1]
    ad = _make(cfg, gid, g)
    _cache[gid] = (g, ad)
    return ad


def type_class(g: dict):
    """游戏记录 → 它的工具类型（适配器类）。"""
    return TYPES.get(kind(g), ReservedGame)


def _make(cfg: dict, gid: str, g: dict):
    return type_class(g)(cfg, gid)


# =====================================================================================
class ReservedGame:
    """预留：还没接入的游戏，只在界面上占位。也是各工具的基类：下面的默认值 = 「这个工具不支持」。"""
    path_field = "exe"          # 游戏记录里工具路径存在哪个字段

    def __init__(self, cfg, gid):
        self.cfg, self.gid, self.g = cfg, gid, cfg["games"][gid]

    # ---------- 记录层（类方法：取消挂载的记录也能用） ----------
    @classmethod
    def uses_emulator(cls, g: dict) -> bool:
        """跑在模拟器上（要开 MuMu 实例、同一模拟器上的游戏连着跑）。"""
        return False

    @classmethod
    def record_problem(cls, g: dict) -> str:
        """工具现在能不能用；不能用返回原因。"""
        if cls is ReservedGame:
            return f"还不支持的类型：{kind(g)}"
        return "" if os.path.exists(g.get(cls.path_field, "")) else f"找不到程序 {g.get(cls.path_field)}"

    @classmethod
    def fill_record(cls, g: dict, info: dict):
        """挂载：按识别结果和你填的几项，把这类工具要的字段写进新记录。"""
        g[cls.path_field] = info["path"]

    @classmethod
    def same_tool(cls, g: dict, info: dict) -> bool:
        """取消挂载的记录和这次选的是不是同一个工具（路径变了也认）：默认按程序文件名。"""
        return bool(g.get("exe")) and Path(g["exe"]).name.lower() == Path(info["path"]).name.lower()

    @classmethod
    def user_commands(cls, g: dict) -> dict | None:
        """挂载时你自己填的命令（设置页可以改）；不是这类工具返回 None。"""
        return None

    @classmethod
    def check_items(cls, cfg: dict, gid: str, g: dict) -> list[dict]:
        """设置页「检查」：[{ok, text}]。"""
        exe = g.get(cls.path_field, "")
        ok = os.path.exists(exe)
        return [{"ok": ok, "text": f"找到 {exe}" if ok else f"找不到程序 {exe}"}]

    # ---------- 能力（不支持的工具用这些默认值） ----------
    can_suspend = False     # 能在运行中暂停 / 继续（BetterGI 的暂停键）
    can_import = False      # 能从工具自己的设置同步成任务预设

    def press(self, which: str) -> str:
        raise ValueError(f"{self.g.get('name', self.gid)} 不能暂停；请用「停止」，之后可以「继续」")

    def tick(self) -> str:
        """后台每分钟调一次：工具那边的事（例如等 BetterGI 关掉再补写）。做了事返回一句说明。"""
        return ""

    def changed_outside(self) -> bool:
        return False

    def has_gui(self) -> bool:
        return False

    def open_gui(self):
        raise ValueError("这个工具没有可以打开的界面")

    def can_launch(self) -> bool:
        """能不能只开模拟器和游戏（不跑任务）：游戏页「用模拟器启动游戏」。"""
        return False

    def launch_game(self) -> str:
        raise ValueError("这个游戏不能单独从管家启动")

    def import_items(self) -> list[dict]:
        raise ValueError("这个工具不能同步成任务预设")

    def evidence_tasks(self) -> list[str] | None:
        """能勾「留证截图」的任务；不支持留证返回 None。"""
        return None

    def sync_plan(self, tasks: list[dict], force: bool = False) -> dict:
        raise ValueError("这个工具没有要写回的设置")

    def write_group(self, group: str, projects: list[dict]) -> dict:
        raise ValueError("这个工具没有配置组")

    def schema(self) -> dict:
        ok, why = available(self.g)
        return {"tasks": [], "options": {}, "presets": [], "reserved": True, "message": why or "待接入"}

    def seed(self):
        return {"routines": {}}

    def labels(self) -> dict:
        """任务显示名（工具里写了 label / 多语言的）：{任务名: 显示名}。适配器随游戏记录缓存，这里算一次就留着。"""
        if getattr(self, "_labels", None) is None:
            self._labels = {t["name"]: t["label"] for t in self.schema()["tasks"]
                            if t.get("label") and t["label"] != t["name"]}
        return self._labels

    def task_names(self) -> list[str]:
        return []

    # ---------- 任务开关 ----------
    # 工具里的任务默认全部可用（10-22 用户要求）。
    #   停用：只有 disabled_tasks 里单独写了原因的（跑过、确实有问题），或用户在界面上手动停用的。
    #   未实测：配置了 tested_tasks 而任务不在清单里——只在界面上显示「未实测」标签，不挡住。
    #   隐藏：hidden_tasks（开发自测用的任务，例如冒烟测试），任务库、计划、运行里都不出现。
    #   提醒：task_notices（会切换账号、消耗体力 / 货币 / 树脂等），加入计划时确认一次。
    UNTESTED = "未实机测试"

    def hidden(self, task: str) -> bool:
        return task in self.g.get("hidden_tasks", [])

    def untested(self, task: str) -> bool:
        tested = self.g.get("tested_tasks")
        return tested is not None and task not in tested

    def task_notice(self, task: str) -> str:
        return str(self.g.get("task_notices", {}).get(task, ""))

    def decorate(self, tasks: list[dict]) -> list[dict]:
        """给 schema 里的任务加上开关状态（disabled / disabled_reason / switch_source / config_reason）、
        untested、notice，并去掉隐藏的任务。任务库、计划编辑都只看这里（10-26 起不再另有 /api/tasks）。
        switch_source：manual = 你在界面上开 / 关过；config = 游戏记录里停用的；"" = 默认。"""
        ov = self.overrides()
        out = []
        for t in tasks:
            n = t["name"]
            if self.hidden(n):
                continue
            why = "" if t.get("placeholder") else self.disabled_reason(n)
            t["disabled"] = bool(why)
            t["switch_source"] = "manual" if (n in ov["disabled"] or n in ov["enabled"]) else "config" if why else ""
            t["config_reason"] = self._config_reason(n)
            if why:
                t["disabled_reason"] = why
            t["untested"] = False  # 11-02：不再区分有没有实测
            note = self.task_notice(n)
            cr = self._config_reason(n)
            if cr:  # 游戏记录里原来停用的：不再停用，加任务时先提醒原因
                note = (note + " " if note else "") + f"注意：{cr}"
            if note:
                t["notice"] = (t["notice"] + " " + note) if t.get("notice") else note
            out.append(t)
        return out

    # 界面上手动开启 / 停用的记录（优先于 config）：data/task_overrides/<gid>.json
    #   {"enabled": [任务名…], "disabled": {任务名: 原因}}
    def _overrides_path(self) -> Path:
        return Path(self.cfg["machine"]["data_dir"]) / "task_overrides" / f"{self.gid}.json"

    def overrides(self) -> dict:
        return jsonio.read(self._overrides_path(), {"enabled": [], "disabled": {}})

    def set_task_enabled(self, task: str, enabled: bool, reason: str = ""):
        def fn(d):
            d["enabled"] = [t for t in d["enabled"] if t != task]
            d["disabled"].pop(task, None)
            if enabled:
                if self._config_reason(task):
                    d["enabled"].append(task)
            else:
                d["disabled"][task] = reason or "手动停用"
        jsonio.update(self._overrides_path(), {"enabled": [], "disabled": {}}, fn)

    def _config_reason(self, task: str) -> str:
        why = self.g.get("disabled_tasks", {}).get(task)
        return str(why) if why else ""

    def disabled_reason(self, task: str) -> str:
        """11-02：任务不再分启用 / 停用（以前手动停用的也算启用），跑哪些由任务预设定。
        游戏记录里写的停用原因改成加任务时的提醒（decorate 里）。"""
        return ""

    def usable(self, task: str) -> bool:
        return not self.hidden(task) and not self.disabled_reason(task)

    def filter_items(self, items: list[dict]) -> list[dict]:
        return [t for t in items if self.usable(t["task"])]

    def processes(self) -> list[str]:
        return list(self.g.get("processes", []))

    def pc_evidence(self, key: str, task: str) -> list[str]:
        """电脑游戏的留证截图（11-02）：设置里勾了这一项 → 截游戏窗口（butler/winshot.py）。截不到返回空列表。"""
        from . import evidence as EV, winshot
        sel = EV.tasks_for(self.cfg, self.gid)
        if key not in sel and task not in sel:
            return []
        p = winshot.save(self.cfg, self.gid, game_day(self.g).isoformat(), key, self.processes())
        return [p] if p else []

    def read_gacha_pc(self, ctx, close: bool | None = None):
        """11-02：工具跑完、游戏还开着 → 读抽卡资源（butler/pcgacha.py）；读完按设置关游戏（工具本来会关的）。"""
        from . import pcgacha
        conf = pcgacha.conf_of(self.g)
        if not conf:
            return
        try:
            pcgacha.read(self.cfg, self.gid, ctx)
        except Exception as e:
            ctx.emit("warn", msg=f"读抽卡资源出错：{type(e).__name__}: {e}")
        if (conf.get("close_after", True) if close is None else close) and pcgacha.window_open(conf):
            for exe in conf.get("exe") or []:
                if ctx.is_running(exe):
                    kill_image(exe)
            ctx.emit("info", msg="读完抽卡资源，已关闭游戏")

    def run(self, items, ctx) -> dict:
        ctx.emit("fatal", reason=f"{self.g.get('name', self.gid)} 还没有接入")
        return {"ok": False, "results": []}


# =====================================================================================
NOTICE_TASK = "📰读游戏内公告"
GACHA_TASK = "💎读抽卡资源"
EVENTS_TASK = "🖼读活动中心题图"


class MaaGame(ReservedGame):
    path_field = "project_dir"

    def __init__(self, cfg, gid):
        super().__init__(cfg, gid)
        self._proj = None

    @classmethod
    def uses_emulator(cls, g: dict) -> bool:
        return g.get("controller", "adb") == "adb"

    @classmethod
    def record_problem(cls, g: dict) -> str:
        return "" if os.path.exists(os.path.join(g.get("project_dir", ""), "interface.json")) \
            else f"找不到 {g.get('project_dir')}\\interface.json"

    @classmethod
    def fill_record(cls, g: dict, info: dict):
        g["project_dir"] = info["path"]
        g["project_name"] = info.get("project_name", "")
        ctl = next((c for c in info.get("controllers", []) if c["name"] == info.get("controller")), None) \
            or (info.get("controllers") or [{"name": "", "type": "adb"}])[0]
        g["iface_controller"] = ctl["name"]
        g["controller"] = "win32" if ctl["type"] == "win32" else "adb"
        if g["controller"] == "adb":
            if not info.get("emulator"):
                raise ValueError("要选模拟器实例")
            g["emulator"] = info["emulator"]
        if info.get("package"):
            g["package"] = info["package"]

    @classmethod
    def same_tool(cls, g: dict, info: dict) -> bool:
        """同一个 interface.json 项目名（文件夹搬了也认）。"""
        name = g.get("project_name")
        if not name and g.get("project_dir") and os.path.exists(os.path.join(g["project_dir"], "interface.json")):
            from .mfa import load_json
            name = load_json(os.path.join(g["project_dir"], "interface.json")).get("name", "")
        return bool(info.get("project_name")) and name == info["project_name"]

    @classmethod
    def check_items(cls, cfg: dict, gid: str, g: dict) -> list[dict]:
        from .mfa import load_json
        items = []
        d = g.get("project_dir", "")
        iface = os.path.join(d, "interface.json")
        if not os.path.exists(iface):
            items.append({"ok": False, "text": f"找不到 {iface}：选工具所在的文件夹（里面有 interface.json）"})
        else:
            items.append({"ok": True, "text": f"找到 {iface}"})
            j = load_json(iface)
            ver = str(j.get("version") or "")
            ntask = len(j.get("task", []) or []) + sum(len(load_json(os.path.join(d, rel)).get("task", []) or [])
                                                       for rel in j.get("import", []) or [])
            items.append({"ok": ntask > 0, "text": f"读到 {ntask} 个任务" + (f"，版本 {ver}" if ver else ""),
                          "version": ver, "tasks": ntask})
            py = cls(cfg if gid in cfg["games"] else {**cfg, "games": {**cfg["games"], gid: g}}, gid).python()
            items.append({"ok": os.path.exists(py), "text": f"执行器用的 Python：{py}"})
        if cls.uses_emulator(g):
            emu = g.get("emulator", "")
            items.append({"ok": bool(emu), "text": f"模拟器实例：{emu}" if emu else "还没选模拟器实例"})
        return items

    def has_gui(self) -> bool:
        return bool(self.g.get("gui_exe"))

    def open_gui(self):
        if not self.has_gui():
            raise ValueError("没有设置这个工具的界面程序（gui_exe）")
        exe = Path(self.g["project_dir"]) / self.g["gui_exe"]
        subprocess.Popen([str(exe)], cwd=str(exe.parent))

    def evidence_tasks(self) -> list[str] | None:
        return [t["name"] for t in self.schema()["tasks"] if not t.get("placeholder")]

    def can_launch(self) -> bool:
        return self.g.get("controller", "adb") == "adb" and bool(self.g.get("emulator"))

    def launch_game(self) -> str:
        """开模拟器实例（已开就跳过）、再打开游戏，不跑任何任务。给用户手动改游戏 / MAA 设置用。
        模拟器开机要一两分钟，放到后台线程里做，结果写进管家日志。"""
        if not self.can_launch():
            raise ValueError("这个游戏没有用模拟器，或者还没选模拟器实例")
        import threading
        from .mumu import MuMu
        g = dict(self.g)
        mumu = MuMu.of(self.cfg)  # 没找到 MuMu 直接报错给界面

        def work():
            try:
                inst = mumu.ensure_started(g["emulator"])
                if g.get("package"):
                    subprocess.run([mumu.adb, "-s", MuMu.address(inst), "shell", "monkey", "-p", g["package"],
                                    "-c", "android.intent.category.LAUNCHER", "1"],
                                   capture_output=True, timeout=60, creationflags=NO_WINDOW)
                print(f"用模拟器启动游戏：{g.get('name')}（实例 {g['emulator']}）", flush=True)
            except Exception as e:  # 后台线程里出错只能记在控制台；界面上已经提示过「正在打开」
                print(f"用模拟器启动游戏失败：{g.get('name')}：{e}", flush=True)
        threading.Thread(target=work, daemon=True, name="launch-game").start()
        return f"正在打开模拟器「{g['emulator']}」" + ("和游戏" if g.get("package") else "（没记录游戏包名，开好后请手动点开游戏）")

    def project(self) -> Project:
        if self._proj is None:
            g = self.g
            self._proj = Project(g["project_dir"], g.get("mfa_config"), g.get("mfa_instance"), g.get("resource"),
                                 g.get("iface_controller"))
            if not g.get("iface_controller") and g.get("controller") == "win32":  # 电脑端：用 interface 里第一个 Win32 控制器
                w = next((c for c in self._proj.controllers() if str(c.get("type", "")).lower() == "win32"), None)
                if w:
                    self._proj.want_controller = w.get("name")
            if g.get("notice_reader"):  # 管家自己加的任务：读游戏内公告栏，给活动日历用（不在 MAA 项目里）
                self._proj.tasks.append({"name": NOTICE_TASK, "entry": f"@notice:{self.gid}",
                                         "description": "打开游戏内公告栏，逐条读标题、活动时间和题图，放进管家的活动日历。只看不点别的，不消耗任何东西。"})
            if g.get("events_reader"):  # 管家自己加的任务：活动中心每个活动截一张整页图，给活动日历当题图（11-02）
                self._proj.tasks.append({"name": EVENTS_TASK, "entry": f"@events:{self.gid}",
                                         "description": "进游戏打开「活动中心」，每个活动截一张图，给活动日历当题图（公告里的题图太小时用）。只看不点领取，不消耗任何东西。"})
            if g.get("gacha_reader"):  # 管家自己加的任务：读抽卡资源（顶栏数字），给主页和资源曲线用
                self._proj.tasks.append({"name": GACHA_TASK, "entry": f"@gacha:{self.gid}",
                                         "description": "点进卡池界面，读顶栏的抽卡货币和抽卡券数量，记进管家的抽卡资源。只看不点抽卡按钮，不消耗任何东西。"})
        return self._proj

    def task_names(self) -> list[str]:
        return self.project().task_names()

    def schema(self) -> dict:
        s = self.project().schema()
        s["reserved"] = False
        s["tasks"] = self.decorate(s["tasks"])  # 任务库里全部任务都在；停用 / 未实测 / 提醒标出来，隐藏的去掉
        # 11-02：读公告 / 读活动中心 / 读抽卡资源不在任务库和预设里出现（由设置 → 游戏内读取决定什么时候顺带做）
        s["tasks"] = [t for t in s["tasks"] if t["name"] not in (NOTICE_TASK, EVENTS_TASK, GACHA_TASK)]
        rec = self.g.get("recovery_task")
        for pr in s.get("presets", []):
            pr["tasks"] = self.filter_items(pr["tasks"])
        s["presets"] = [pr for pr in s.get("presets", []) if [t for t in pr["tasks"] if t["task"] != rec]]
        return s

    def tool_routines(self) -> dict:
        """工具自己带的几套任务（挂载时问你要不要一同导入）：interface.json 的预设、MFA 里保存的配置、工具默认勾选的任务。
        {名字: [任务项…]}；写错的预设不算（游戏页上标出原因）。"""
        p, rec = self.project(), self.g.get("recovery_task")
        out: dict = {}
        for pr in p.preset_routines():
            if pr["tasks"] and not pr["error"]:
                out[pr["name"]] = self.filter_items(pr["tasks"])
        for name, items in p.instance_routines().items():
            items = self.filter_items(items)
            if [t for t in items if t["task"] != rec]:  # 只剩启动（或什么都不剩）的不要
                out.setdefault(name if name not in out else f"MFA·{name}", items)
        dflt = [{"task": t["name"], "choices": p.choices_from_mfa(t)} for t in p.tasks if t.get("default_check")]
        if dflt:
            out.setdefault("工具默认勾选", self.filter_items(dflt))
        return out

    def seed(self) -> dict:
        """首次使用时的任务预设：管家不带任何默认任务清单（用户 10-26 定）。挂载时你选了「一同导入工具自带的预设」才导入，
        否则是空的，自己在任务库里勾。"""
        routines = {k: {"tasks": v} for k, v in self.tool_routines().items()} if self.g.get("import_tool_routines") else {}
        return {"routines": routines}

    def processes(self) -> list[str]:
        return list(self.g.get("processes", [])) + ([self.g["gui_exe"]] if self.g.get("gui_exe") else [])

    def python(self) -> str:
        g = self.g
        if g.get("python"):
            return g["python"]
        py = Path(g["project_dir"]) / "python" / "python.exe"
        if py.exists():
            return str(py)
        if RUNTIME_PY.exists():
            return str(RUNTIME_PY)
        return sys.executable

    # ---------- 生成执行器的 job ----------
    def build_job(self, items: list[dict], controller: dict, stop_file: str) -> dict:
        g, m = self.g, self.cfg["machine"]
        proj = self.project()
        to = g.get("timeouts", {})
        default_min = to.get("default", 8)
        sset = None
        from . import settings as SET0
        sset = SET0.get(self.cfg, "scheduler")
        retries = int(sset.get("task_retries", 1))  # 11-02：全局（调度设置），不再看每个游戏「高级」里的 retries
        stall_skip = sset.get("stuck_action") == "skip"
        # 卡死处理（11-01 定，默认开）：看画面——10 分钟没有变化算卡住，重启游戏、按重试次数再跑。
        # 开着时不用每项的固定最长时间（11-01 代号鸢「地宫助手」次次被 15 分钟上限停掉），只留 90 分钟兜底。
        # 关着时照旧按每项的最长时间。旧的「几分钟没有识别命中 / 在两个节点间打转」会误伤正常运转，不再用
        from . import settings as SET
        stuck_on = bool(SET.get(self.cfg, "scheduler").get("stuck_restart"))
        stuck_s = STUCK_MINUTES * 60 if stuck_on else 0

        overlay = ROOT / "overlays" / self.gid          # 管家自己的覆盖资源包：不改 MAA 项目文件
        patches = []
        if (overlay / "patches.json").exists():
            patches = json.loads((overlay / "patches.json").read_text(encoding="utf-8"))
        def patched(td, choices):
            ov = proj.build_override_named(td, choices)
            eff = proj.choices_from_mfa(td)
            eff.update(choices or {})
            for pt in patches:
                if pt.get("task") == td["name"] and all(eff.get(k) == v for k, v in pt.get("when", {}).items()):
                    deep_merge(ov, pt["override"])
            return ov

        def minutes(td_name, key):
            return SAFETY_MINUTES if stuck_on else int(sset.get("task_max_minutes", 20))  # 11-02：全局

        from . import evidence as EV
        ev = EV.tasks_for(self.cfg, self.gid)
        ev_dir = EV.root(self.cfg) / game_day(g).isoformat() / self.gid
        tasks = []
        ad_nodes = list(g.get("ad_nodes", [])) if g.get("read_ads", True) else []  # 开屏活动海报（11-02，时绘）
        for it in items:
            td = proj.find_task(it["task"])
            key = item_key(it)
            shoot = key in ev or td["name"] in ev  # 留证截图：设置里勾选了的任务结束时截一张，配置了关键节点的命中时也截
            tasks.append({
                "name": key, "task": td["name"], "entry": td["entry"], "override": patched(td, it.get("choices")),
                "notice_out": str(Path(m["data_dir"]).resolve() / "news" / "ingame"),
                "gacha_conf": g.get("gacha_reader") or {},
                "judge": J.for_task(g, td["name"]),
                "alert_hints": g.get("alert_hints", []),
                "timeout_s": int(minutes(td["name"], key) * 60), "stall_s": stuck_s,
                **({"override": {**patched(td, it.get("choices")), **{n: {"pre_delay": 1500} for n in ad_nodes}}}
                   if ad_nodes and td["name"] == g.get("recovery_task") else {}),  # 点掉海报前等 1.5 秒，趁它还在截原图
                "retries": retries,
                "retry_on_fail": True,
                "restart_on_fail": False,
                "stall_skip": stall_skip,
                "fail_retries": int(g.get("fail_retries", 1)),
                "evidence": shoot,
                "startup": td["name"] == g.get("recovery_task"),
                "evidence_nodes": list(g.get("evidence_nodes", {}).get(td["name"], [])) if shoot else [],
                "evidence_end": td["name"] not in g.get("evidence_no_end", []),
                **({"ad_nodes": ad_nodes} if ad_nodes and td["name"] == g.get("recovery_task") else {}),  # 结束画面没用的（深空日常收尾停在签到页）
            })

        recovery = {}
        if g.get("recovery_task"):
            rd = proj.find_task(g["recovery_task"])
            rc = next((it.get("choices") for it in items if it["task"] == rd["name"]), None)
            recovery = {"entry": rd["entry"], "override": patched(rd, rc),
                        "timeout_s": int(minutes(rd["name"], rd["name"]) * 60), "stall_s": stuck_s,
                        "package": g.get("package", ""), "back_presses": int(g.get("back_presses", 1))}

        return {
            "game": self.gid,
            "project_dir": g["project_dir"],
            "data_dir": str(Path(m["data_dir"]) / "maafw" / self.gid),
            "resource_paths": proj.resource_paths() + ([str(overlay)] if (overlay / "pipeline").exists() else []),
            "agent": proj.agent(),
            "agent_timeout_s": int(g.get("agent_timeout_s", 120)),
            "controller": controller,
            "tasks": tasks,
            "recovery": recovery,
            "stop_file": stop_file,
            "evidence_dir": str(ev_dir),
        }

    def controller(self, ctx) -> dict:
        """准备控制器：ADB（MuMu 实例，按名称启动）或 Win32 窗口（剑三无界预留）。"""
        g = self.g
        ctype = g.get("controller", "adb")
        if ctype == "win32":
            w = {**self.project().win32_config(), **{k: v for k, v in (g.get("win32") or {}).items() if v}}  # config 里写了的优先
            if not (w.get("window_regex") or w.get("class_regex")):
                raise RuntimeError("不知道找哪个窗口：interface.json 和配置里都没写窗口标题 / 类名")
            return {"type": "win32", "class_regex": w.get("class_regex", ""), "window_regex": w.get("window_regex", ""),
                    "screencap": w.get("screencap", "FramePool"), "mouse": w.get("mouse", "Seize"),
                    "keyboard": w.get("keyboard", "Seize")}
        from .mumu import MuMu
        proj = self.project()
        mumu = MuMu.of(self.cfg)
        ctx.emit("info", msg=f"启动/检查 MuMu 实例「{g['emulator']}」…")
        inst = mumu.ensure_started(g["emulator"])
        address = MuMu.address(inst)
        ctx.emit("info", msg=f"模拟器就绪：{address}（实例 {inst['index']}）")
        dev = proj.adb_device()
        extra = {}
        if dev.get("Config"):
            try:
                extra = json.loads(dev["Config"])
            except json.JSONDecodeError as e:
                raise RuntimeError(f"MFA 里保存的设备设置（Config）读不出来：{e}；在 MFA 里重新选一次设备再试") from e
        extra.setdefault("extras", {}).setdefault("mumu", {})
        extra["extras"]["mumu"].update({"enable": True, "index": int(inst["index"]), "path": mumu.dir.replace("\\", "/")})
        adb = dev.get("AdbPath") or mumu.adb
        if not os.path.exists(adb):
            adb = mumu.adb
        return {
            "type": "adb",
            "adb_path": adb,
            "address": address,
            "screencap_methods": int(g.get("screencap_methods") or dev.get("ScreencapMethods") or 0xFFFFFFFFFFFFFFFF),
            "input_methods": int(g.get("input_methods") or dev.get("InputMethods") or 0xFFFFFFFFFFFFFFFF),
            "config": extra,
        }

    # ---------- 运行 ----------
    def run(self, items: list[dict], ctx) -> dict:
        res = getattr(ctx, "hires", "")
        if res and self.g.get("controller", "adb") == "adb":  # 「重新获取题图」：模拟器临时调高分辨率（11-01）
            try:
                with hires_session(self.cfg, self.g, ctx, res):
                    return self._run(items, ctx)
            except Exception as e:
                ctx.emit("fatal", reason=f"临时调高模拟器分辨率没成功：{e}")
                return {"ok": False, "results": []}
        return self._run(items, ctx)

    def _run(self, items: list[dict], ctx) -> dict:
        g = self.g
        if g.get("gui_exe") and ctx.is_running(g["gui_exe"]):
            ctx.emit("fatal", reason=f"检测到 {g['gui_exe']} 正在运行。请先关掉它的窗口，避免两边同时操作。")
            return {"ok": False, "results": []}
        try:
            controller = self.controller(ctx)
        except Exception as e:
            ctx.emit("fatal", reason=f"模拟器没有准备好：{e}")
            return {"ok": False, "results": []}
        job = self.build_job(items, controller, ctx.stop_file)
        job["skip_file"] = getattr(ctx, "skip_file", "")  # 跳过当前任务 / 这个游戏剩下的：执行器当成停止
        job["yield_file"] = str(ctx.rs.yield_path)  # 让出给赶时段的任务：做完手上这一项就停
        job_path = ctx.log_path.with_suffix(".job.json")
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
        python = self.python()
        ctx.emit("info", msg=f"开始执行 {len(job['tasks'])} 个任务（每个任务超时、卡住会自动重试）")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen([python, "-u", str(RUNNER), str(job_path)], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env, cwd=g["project_dir"], creationflags=NO_WINDOW)
        ctx.set_runner(proc.pid)
        summary = None
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    ctx.raw(line)  # 框架底层组件的调试输出，只留在记录文件里
                    continue
                ctx.forward(ev)
                if ev.get("event") == "summary":
                    summary = ev
                    break  # 拿到结果就不再等执行器退出（它退出时偶尔会卡住）
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)
        finally:  # 管家这边出错时执行器不能留着继续操作模拟器
            if proc.poll() is None:
                kill_tree(proc.pid)
            ctx.set_runner(0)
        return summary or {"ok": False, "results": [], "crashed": True}

    def after(self, ctx, close_emulator: bool):
        """一个游戏跑完：需要时强制关闭游戏（同一模拟器后面还有别的游戏时腾内存）。"""
        g = self.g
        if g.get("controller", "adb") != "adb":
            return
        if not close_emulator and g.get("stop_app_after") and g.get("package"):
            from .mumu import MuMu
            try:
                mumu = MuMu.of(self.cfg)
                inst = mumu.find(g["emulator"])
                subprocess.run([mumu.adb, "-s", MuMu.address(inst), "shell", "am", "force-stop", g["package"]],
                               capture_output=True, timeout=30, creationflags=NO_WINDOW)
                ctx.emit("info", msg=f"已关闭游戏 {g['package']}")
            except Exception as e:
                ctx.emit("warn", msg=f"关闭游戏失败：{e}")


# =====================================================================================
class _Gone:
    """用确认窗口（ShellExecute）启动的程序拿不到进程句柄：当作已退出，靠 wait_processes 按进程名等它。"""
    pid = 0
    returncode = 0

    def poll(self):
        return 0


class CommandGame(ReservedGame):
    """命令行工具（BetterGI 一条龙、三月七小助手等）。

    [games.<gid>.commands."任务名"]
      args = ["--startOneDragon", "{配置名}"]   # {xxx} 会变成界面上的输入项
      defaults = { 配置名 = "默认配置" }
      timeout = 120                              # 分钟
      done = ["一条龙和配置组任务结束"]          # 日志里出现即成功
      fail = ["任务被取消，退出执行"]            # 日志里出现即失败
      exit_ok_means_done = false                 # 没有 done 标志时，进程正常退出（返回码 0）是否算成功
      wait_processes = ["March7th Assistant.exe"]  # 主进程退出后，还要等这些进程也退出
      close_after = ["YuanShen.exe"]             # 结束后要关掉的进程
    """

    @classmethod
    def user_commands(cls, g: dict) -> dict | None:
        return g.get("commands", {}) if kind(g) == "command" else None   # 三月七这类的命令来自预设，不在设置页改

    @classmethod
    def fill_record(cls, g: dict, info: dict):
        from .mount import _commands
        g["exe"] = info["path"]
        if info.get("commands") or not g.get("commands"):  # 三月七这类：命令写在预设里；自己添加的：挂载时填的
            g["commands"] = _commands(info.get("commands") or [{"name": "运行", "args": "", "timeout": 60}])
        if info.get("log_glob"):
            g["log_glob"] = info["log_glob"]

    def evidence_tasks(self) -> list[str] | None:  # 11-02：电脑游戏也能留证（截游戏窗口）
        return list(self.commands())

    def has_gui(self) -> bool:  # 11-02：命令行工具（三月七小助手等）也能从管家打开它自己的界面
        return bool(self.g.get("exe")) and os.path.exists(self.g["exe"])

    def updater_exe(self) -> str:
        """工具自带的更新程序（三月七：March7th Updater.exe，和主程序同一个文件夹）；没有就是空字符串。"""
        exe = self.g.get("exe")
        if not exe:
            return ""
        d = Path(exe).parent
        for name in ("March7th Updater.exe", "Updater.exe"):
            if (d / name).exists():
                return str(d / name)
        hit = sorted(d.glob("*Updater*.exe"))
        return str(hit[0]) if hit else ""

    def gui_exe(self) -> str:
        """工具的界面程序：跑任务用的是命令行程序（三月七：March7th Assistant.exe），
        打开给你看的是同目录的启动器（March7th Launcher.exe）。没有就是空字符串（直接开主程序）。"""
        exe = self.g.get("exe")
        if not exe:
            return ""
        d = Path(exe).parent
        for name in ("March7th Launcher.exe",):
            if (d / name).exists():
                return str(d / name)
        hit = sorted(d.glob("*Launcher*.exe"))
        return str(hit[0]) if hit else ""

    def open_gui(self, updater: bool = False):
        exe = self.g.get("exe")
        if not exe or not os.path.exists(exe):
            raise ValueError(f"找不到这个工具的程序：{exe or '没有设置'}（在「设置 → 工具与游戏」里改路径）")
        if updater:  # 11-02：「打开更新」直接开更新程序，不开主程序
            exe = self.updater_exe() or exe
        else:
            exe = self.gui_exe() or exe
        if os.name == "nt":
            os.startfile(exe, cwd=str(Path(exe).parent))  # type: ignore[call-arg]  # 要管理员权限的会弹确认
        else:
            subprocess.Popen([exe], cwd=str(Path(exe).parent))

    def commands(self) -> dict:
        return self.g.get("commands", {})

    def task_names(self) -> list[str]:
        return list(self.commands())

    def schema(self) -> dict:
        tasks, opts = [], {}
        for name, c in self.commands().items():
            names = []
            for a in c.get("args", []):
                for var in re.findall(r"\{(\w+)\}", str(a)):
                    if var not in names:
                        names.append(var)
            selects = c.get("selects", {})
            for var in names:
                if var in selects:  # 例如 BetterGI 的一条龙配置：列出 User\OneDragon 里已有的配置
                    found = sorted(os.path.splitext(os.path.basename(x))[0] for x in glob.glob(selects[var]))
                    dflt = str(c.get("defaults", {}).get(var, found[0] if found else ""))
                    if dflt and dflt not in found:
                        found.insert(0, dflt)
                    opts[var] = {"type": "select", "label": var, "description": c.get("help", {}).get(var, ""),
                                 "cases": [{"name": n, "label": "", "description": "", "sub": []} for n in found],
                                 "default": dflt}
                    continue
                opts[var] = {"type": "input", "label": var, "description": "",
                             "inputs": [{"name": var, "label": var, "description": c.get("help", {}).get(var, ""),
                                         "default": str(c.get("defaults", {}).get(var, "")), "pipeline_type": "string",
                                         "verify": None}]}
            tasks.append({"name": name, "entry": " ".join(map(str, c.get("args", []))), "description": c.get("description", ""),
                          "options": names,
                          "mfa_choices": {v: (opts[v]["default"] if opts[v]["type"] == "select"
                                              else {v: str(c.get("defaults", {}).get(v, ""))}) for v in names},
                          "default_check": True, "placeholder": False})
        ok, why = available(self.g)
        tasks = self.decorate(tasks)
        return {"tasks": tasks, "options": opts, "presets": [], "reserved": not ok, "message": why}

    def seed(self) -> dict:
        """命令行脚本没有自带的预设：任务预设一开始是空的，自己在任务库里勾（用户 10-26 定）。"""
        return {"routines": {}}

    def processes(self) -> list[str]:
        out = list(self.g.get("processes", []))
        exe = os.path.basename(self.g.get("exe", ""))
        return out + ([exe] if exe else [])

    def log_glob(self) -> str:
        """工具自己的日志：log_glob 可以写相对路径（相对程序所在文件夹），没写就看程序旁边的 log\\*.log。"""
        base = os.path.dirname(self.g.get("exe", ""))
        pat = self.g.get("log_glob") or os.path.join("log", "*.log")
        return pat if os.path.isabs(pat) else os.path.join(base, pat)

    def captures_output(self) -> bool:
        """自己添加的命令行脚本和 maa-cli：输出存进文件，从里面找成功标志和脚本信号。"""
        return kind(self.g) in ("command", "maa_ark")

    def run(self, items: list[dict], ctx) -> dict:
        from . import pcres  # 崩铁：开关开着时，跑之前调成 1920×1080 窗口化，跑完恢复
        return pcres.wrap(self.cfg, self.gid, ctx, lambda: self._run(items, ctx))

    def _run(self, items: list[dict], ctx) -> dict:
        g = self.g
        results = []
        for it in items:
            if ctx.stop_requested():
                break
            name, key = it["task"], item_key(it)
            c = self.commands().get(name)
            if not c:
                ctx.emit("warn", msg=f"配置里没有命令「{name}」，跳过")
                continue
            values = {k: str(v) for k, v in c.get("defaults", {}).items()}
            for opt, val in (it.get("choices") or {}).items():
                if isinstance(val, dict):
                    values.update({k: str(v) for k, v in val.items()})
                else:
                    values[opt] = str(val)
            args = [re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), ""), str(a)) for a in c.get("args", [])]
            args = [a for a in args if a != ""]
            ctx.emit("task_start", task=key, attempt=1)
            t0 = time.monotonic()
            from .bettergi import LogTail
            tail = LogTail(self.log_glob())
            tail.skip_existing()  # 启动前已有的日志一律不看
            tails = [tail]
            if self.captures_output():
                t2 = LogTail(str(Path(self.cfg["machine"]["data_dir"]) / "maafw" / self.gid / "stdout.log"))
                t2.skip_existing()
                tails.append(t2)
            task_name = c.get("launch_task")
            via_task = bool(task_name) and os.name == "nt" and all(
                values.get(k, "") == str(v) for k, v in c.get("launch_task_when", {}).items())
            if via_task and subprocess.run(["schtasks", "/Query", "/TN", task_name], capture_output=True,
                                           creationflags=NO_WINDOW).returncode != 0:
                ctx.emit("warn", msg=f"没有找到计划任务「{task_name}」（用 GameButler.exe 启动管家就不需要它），改为直接启动，会弹出确认窗口")
                via_task = False
            if via_task:  # 用「以最高权限运行」的计划任务启动：不弹管理员确认窗口
                ctx.emit("info", msg=f"通过计划任务「{task_name}」启动（免确认）")
            out_f = None
            try:
                if via_task:
                    proc = subprocess.Popen(["schtasks", "/Run", "/TN", task_name], creationflags=NO_WINDOW,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif self.captures_output():
                    out_dir = Path(self.cfg["machine"]["data_dir"]) / "maafw" / self.gid
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out_f = open(out_dir / "stdout.log", "ab")
                    exe = g["exe"]
                    argv = [sys.executable if not RUNTIME_PY.exists() else str(RUNTIME_PY), exe, *args] if exe.lower().endswith(".py") \
                        else ["cmd", "/c", exe, *args] if exe.lower().endswith((".bat", ".cmd")) and os.name == "nt" else [exe, *args]
                    proc = subprocess.Popen(argv, cwd=os.path.dirname(exe), stdout=out_f, stderr=subprocess.STDOUT,
                                            creationflags=NO_WINDOW, env=getattr(self, "_env", None))
                else:
                    proc = subprocess.Popen([g["exe"], *args], cwd=os.path.dirname(g["exe"]))
            except OSError as e:
                proc, why = None, str(e)
                if getattr(e, "winerror", 0) == 740 and os.name == "nt":  # 程序要求管理员权限：弹一次确认窗口启动
                    import ctypes
                    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", g["exe"], subprocess.list2cmdline(args),
                                                            os.path.dirname(g["exe"]), 1)
                    if r > 32:
                        ctx.emit("info", msg="管家没有管理员权限，已用确认窗口启动（用 GameButler.exe 启动管家就不会弹）")
                        proc = _Gone()
                    else:  # 5 = 你在确认窗口里点了「否」
                        why = ("要管理员权限，确认窗口里没有允许" if r == 5 else f"要管理员权限，用确认窗口启动也失败（代码 {r}）") + \
                            "。用 GameButler.exe 启动管家（管理员）就不用确认"
                if proc is None:
                    ctx.emit("fatal", reason=f"启动失败：{why}")
                    ev = {"task": key, "attempt": 1, "result": "failed", "detail": f"启动失败：{why}", "minutes": 0,
                          "focus": [], "flags": [], "shots": []}
                    ctx.emit("task_end", **ev)
                    results.append({**ev, "attempts": 1})
                    break
            ctx.set_runner(proc.pid)
            res, why, focus = None, "", []
            timeout_s = int(c.get("timeout", g.get("timeout", 120)) * 60)
            seen_at = time.monotonic()  # 最近一次看到程序还在运行的时间
            step_re = re.compile(c["progress"]) if c.get("progress") else None
            steps = ""
            incomplete = ""
            sig_reason = ""
            while res is None:
                time.sleep(3)
                for line in [x for tl in tails for x in tl.read()]:
                    sg = SIG.parse(line)  # 脚本信号约定（butler/signals.py）
                    if sg:
                        focus.append(line.strip()[-200:])
                        kind_, txt = sg
                        if kind_ == "fuse":
                            res, why, sig_reason = "failed", f"熔断：{txt or '脚本发出熔断信号'}", "fuse"
                        elif kind_ == "manual":
                            res, why, sig_reason = "failed", f"需要人工：{txt or '脚本要求人工处理'}", "manual"
                        elif kind_ == "pause":
                            res, why = "stopped", f"脚本暂停：{txt}" if txt else "脚本暂停"
                        elif kind_ == "fail":
                            res, why = "failed", f"脚本报告失败：{txt}"
                        elif kind_ == "done":
                            res, why = "succeeded", "脚本报告完成"
                        if res:
                            break
                    if step_re and step_re.search(line):
                        m = step_re.search(line)
                        steps = "/".join(m.groups()) if m.groups() else ""
                    if any(p in line for p in c.get("focus", [])):
                        focus.append(line.strip()[-200:])
                    hit_inc = next((d for d in c.get("incomplete", []) if d in line), None)
                    if hit_inc:  # 例如三月七「每日实训未完成」：程序照常退出，但这一项没做满
                        incomplete = hit_inc
                        focus.append(line.strip()[-200:])
                    hit_done = next((d for d in c.get("done", []) if d in line), None)
                    hit_fail = next((d for d in c.get("fail", []) if d in line), None)
                    if hit_done or hit_fail:
                        focus.append(line.strip()[-200:])
                    if hit_fail:
                        res, why = "failed", f"日志：{hit_fail}"
                        break
                    if hit_done:
                        res, why = "succeeded", f"日志：{hit_done}"
                        break
                if res:
                    break
                if ctx.stop_requested():
                    res, why = "stopped", "已手动停止" if ctx.rs.stop_requested() else "已跳过"
                    break
                if time.monotonic() - t0 > timeout_s:
                    res, why = "timeout", f"超过 {timeout_s // 60} 分钟未完成"
                    break
                # 程序可能会以管理员身份重新启动自己（原进程立刻退出），所以按进程名判断它还在不在
                if proc.poll() is None or any(ctx.is_running(p) for p in c.get("wait_processes", [])):
                    seen_at = time.monotonic()
                    continue
                if c.get("done"):
                    if time.monotonic() - seen_at < 30:  # 程序退出后再给日志 30 秒
                        continue
                    res, why = "failed", "程序已退出，但日志里没有完成标志"
                else:
                    if c.get("exit_ok_means_done") and proc.returncode == 0:
                        res, why = "succeeded", "程序正常退出"
                    else:
                        res, why = "failed", f"程序退出，返回码 {proc.returncode}"
            if res == "succeeded" and incomplete:
                res, why = "failed", f"日志：{incomplete}"
            ev_files = self.pc_evidence(key, name) if res == "succeeded" else []  # 留证：日志说做完的那一刻截游戏窗口（11-02）
            if steps and res:
                why = f"{why}（进度 {steps}）"
            if res in ("timeout", "stopped") and proc.poll() is None:
                kill_tree(proc.pid)
            if res in ("timeout", "stopped"):
                for exe in self.processes():
                    kill_image(exe)
            elif c.get("close_after"):
                # 先等程序自己收尾关闭（例如 BetterGI 的「完成后：关闭游戏和软件」），超时再强制结束
                grace = time.monotonic() + int(c.get("close_grace_s", 90))
                while time.monotonic() < grace and any(ctx.is_running(e) for e in c["close_after"]):
                    time.sleep(3)
                for exe in c["close_after"]:
                    if ctx.is_running(exe):
                        ctx.emit("info", msg=f"{exe} 没有自己关闭，强制结束")
                        kill_image(exe)
            ctx.set_runner(0)
            if out_f:
                try:
                    out_f.close()
                except OSError:
                    pass
                out_f = None
            mins = round((time.monotonic() - t0) / 60, 1)
            ev = {"task": key, "attempt": 1, "result": res, "detail": why, "minutes": mins,
                  "focus": focus[-8:], "flags": [], "shots": [], **({"evidence": ev_files} if ev_files else {})}
            ctx.emit("task_end", **ev)
            results.append({**ev, "attempts": 1})
            if sig_reason:  # 熔断 / 需要人工：这个游戏后面的不跑了
                if res == "failed" and proc.poll() is None:
                    kill_tree(proc.pid)
                signal = {"signal": sig_reason, "signal_reason": why}
                if sig_reason == "fuse":
                    ctx.emit("abort", reason=why, signal="fuse")
                    signal.update(aborted=True, abort_reason=why)
                ok = False
                return {"ok": False, "results": results, **signal}
            if res == "stopped":
                break
        ok = bool(results) and all(r["result"] in ("succeeded", "exhausted") for r in results)
        if results and not ctx.stop_requested():
            self.read_gacha_pc(ctx)
        return {"ok": ok, "results": results}

    def after(self, ctx, close_emulator: bool):
        pass


# =====================================================================================
from .bettergi import BetterGIGame  # noqa: E402


class BetterGIAdapter(BetterGIGame, ReservedGame):
    """原神 BetterGI 一条龙（逐项布置、逐项记录），实现见 bettergi.py。"""
    can_suspend = True
    can_import = True

    def evidence_tasks(self) -> list[str] | None:  # 11-02：留证 = 日志里这一项结束时截原神窗口
        try:
            return [t["name"] for t in self.schema()["tasks"] if not t.get("placeholder")]
        except Exception:
            return []

    @classmethod
    def fill_record(cls, g: dict, info: dict):
        g["exe"] = info["path"]   # 其余按预设

    @classmethod
    def check_items(cls, cfg: dict, gid: str, g: dict) -> list[dict]:
        items = ReservedGame.check_items.__func__(cls, cfg, gid, g)
        if items[0]["ok"]:
            od = Path(g["exe"]).parent / "User" / "OneDragon"
            confs = sorted(p.stem for p in od.glob("*.json"))
            items.append({"ok": bool(confs), "text": f"一条龙配置：{'、'.join(confs)}" if confs else "还没有一条龙配置：先在 BetterGI 里建一个"})
        return items

    def has_gui(self) -> bool:
        return True

    def import_items(self) -> list[dict]:
        return self.enabled_items()

    def sync_plan(self, tasks: list[dict], force: bool = False) -> dict:
        return self.sync(tasks, force=force)

    def tick(self) -> str:
        """BetterGI 开着时没写进去的计划：等它关掉后补写。"""
        if not available(self.g)[0] or not self._read_state().get("pending") or self.running():
            return ""
        from .schedule import Schedule
        r = self.sync(Schedule(self.cfg).game_tasks(self.gid))
        return f"BetterGI 关掉了，补写一条龙：{r.get('msg')}"

    def schema(self) -> dict:
        s = BetterGIGame.schema(self)
        s["tasks"] = self.decorate(s["tasks"])  # 和 MAA 游戏一致
        return s

    def processes(self) -> list[str]:
        return list(dict.fromkeys(list(self.g.get("processes", [])) + [self.exe.name]))

    def after(self, ctx, close_emulator: bool):
        pass


# =====================================================================================
class ArkGame(CommandGame):
    """明日方舟 MAA（butler/arknights.py）：maa-cli 逐项跑；图形界面版整体跑一次「一键长草」。"""

    @classmethod
    def uses_emulator(cls, g: dict) -> bool:
        return g.get("controller", "adb") == "adb"

    @classmethod
    def fill_record(cls, g: dict, info: dict):
        from .arknights import is_cli
        g["exe"] = info["path"]
        if is_cli(info["path"]):
            if not info.get("emulator"):
                raise ValueError("要选模拟器实例")
            g["emulator"] = info["emulator"]
        g["package"] = info.get("package") or "com.hypergryph.arknights"

    def commands(self) -> dict:
        from . import arknights as AK
        return AK.commands(self.g)

    def processes(self) -> list[str]:
        return [os.path.basename(self.g.get("exe", ""))]

    def run(self, items: list[dict], ctx) -> dict:
        from . import arknights as AK
        g = self.g
        self._env = None
        if AK.is_cli(g.get("exe", "")):
            from .mumu import MuMu
            if not g.get("emulator"):
                ctx.emit("fatal", reason="还没选模拟器实例（设置 → 工具与游戏）")
                return {"ok": False, "results": []}
            try:
                mumu = MuMu.of(self.cfg)
                ctx.emit("info", msg=f"启动/检查 MuMu 实例「{g['emulator']}」…")
                inst = mumu.ensure_started(g["emulator"])
                address = MuMu.address(inst)
            except Exception as e:
                ctx.emit("fatal", reason=f"模拟器没有准备好：{e}")
                return {"ok": False, "results": []}
            choices = {}
            for it in items:
                choices.update(it.get("choices") or {})
            self._env = AK.prepare(self.cfg, self.gid, address, mumu.adb, choices)
            ctx.emit("info", msg=f"模拟器就绪：{address}；用 maa-cli 逐项运行")
        return self._run(items, ctx)

    def after(self, ctx, close_emulator: bool):
        pass


TYPES = {"maa": MaaGame, "bettergi": BetterGIAdapter, "m7a": CommandGame, "command": CommandGame, "maa_ark": ArkGame}


def forget(cfg: dict, gid: str):
    """彻底删除：任务开关记录、执行器的日志和截图、命令行脚本的输出。"""
    data = Path(cfg["machine"]["data_dir"])
    jsonio.remove(data / "task_overrides" / f"{gid}.json")
    jsonio.remove(data / "maafw" / gid)
    jsonio.remove(data / "maa_ark" / gid)


# ---------------------------------------------------------------- 临时调高模拟器分辨率（11-01）
from contextlib import contextmanager


@contextmanager
def hires_session(cfg: dict, g: dict, ctx, target: str):
    """「重新获取题图」：关掉实例 → 改成 target（如 1920x1080，横竖跟原来一样）→ 开机跑 → 关掉 → 配置文件原样改回。
    MAA 识别时会把截图缩到短边 720，脚本照常能认；读公告存题图时按原图大小截，题图就清楚了。"""
    from .mumu import MuMu
    mumu = MuMu.of(cfg)
    name = g["emulator"]
    inst = mumu.find(name)
    vm = mumu.vm_dir(inst)
    w, h, dpi = mumu.resolution(vm)
    tw, th = (int(x) for x in str(target).lower().split("x"))
    if h > w:
        tw, th = th, tw
    if w * h >= tw * th:
        ctx.emit("info", msg=f"模拟器已经是 {w}×{h}，不用再调高")
        yield
        return
    ctx.emit("info", msg=f"模拟器从 {w}×{h} 临时改成 {tw}×{th}，读完公告改回来")
    if inst.get("is_process_started") or inst.get("is_android_started"):
        mumu.shutdown(name)
    backup = mumu.backup_configs(vm)
    try:
        mumu.set_resolution(vm, tw, th, max(160, round(dpi * tw / w)))
        inst = mumu.ensure_started(name)
        got = mumu.screen(inst)
        if got and got[0] * got[1] <= w * h:
            raise RuntimeError(f"改完开机还是 {got[0]}×{got[1]}（MuMu 没有按配置换分辨率）")
        ctx.emit("info", msg=f"模拟器现在是 {got[0]}×{got[1]}" if got else "已按新分辨率开机")
        yield
    finally:
        try:
            mumu.shutdown(name)
        except Exception as e:
            ctx.emit("warn", msg=f"关模拟器没成功：{e}")
        try:
            mumu.restore_configs(backup)
            ctx.emit("info", msg=f"模拟器分辨率已改回 {w}×{h}")
        except Exception as e:
            ctx.emit("warn", msg=f"改回分辨率没成功：{e}（请在 MuMu 里把分辨率改回 {w}×{h}）")
