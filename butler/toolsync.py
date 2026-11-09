"""MAA 工具（MFA 项目）和管家之间的两件事（11-09）：

1. 工具更新后，新功能要让你看到
   每次（重新）读 interface.json 时和上次记下的对比：新任务、任务预设里用到的选项新加了哪些选项 / 选项值
   （例如代号鸢 MaaYuan 更新后，心纸营建「活动版本」多了「灵山开学日」）。有变化就记一条更新提醒，
   主页顶上显示，点「看看」去这个游戏的任务预设；「知道了」收起。
   记录：data/tool_seen/<游戏>.json（上次看到的）、data/tool_updates.json（还没收起的提醒）

2. 选项以管家的任务预设为准，自动写回工具
   任务预设一保存，就把里面每个任务的选项写进工具自己的配置（MFA 当前用的那份实例 / 配置），
   在工具里打开看到的和管家一样。工具界面开着时不写（它关掉时会把自己的配置存回去，盖掉写进去的），
   记成「待写」，等它关掉后由调度顺手写。写之前备份到 _backup/mfa/。
   只改选项，不改工具里勾了哪些任务、顺序；同一个任务在几套预设里都有时，以排在前面的那套为准。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from . import jsonio

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SEEN = DATA / "tool_seen"
UPDATES = DATA / "tool_updates.json"
PENDING = DATA / "mfa_sync.json"
BACKUP = ROOT / "_backup" / "mfa"


# ================= 1. 工具更新提醒 =================
def snapshot(proj) -> dict:
    opts = {}
    for name, od in (proj.options or {}).items():
        if isinstance(od, dict):
            opts[name] = [c.get("name") for c in od.get("cases", []) or [] if isinstance(c, dict)]
    return {"version": str(proj.iface.get("version") or ""), "tasks": [t["name"] for t in proj.tasks if not str(t.get("entry", "")).startswith("@")],
            "options": opts}


def _opt_tree(proj, names, depth=0) -> list[str]:
    """选项及其所有可能出现的子选项（不管当前选的是哪一项）。"""
    out = []
    for n in names:
        if n in out or depth > 12:
            continue
        out.append(n)
        od = proj.options.get(n) or {}
        for c in od.get("cases", []) or []:
            for sub in _opt_tree(proj, c.get("option", []) or [], depth + 1):
                if sub not in out:
                    out.append(sub)
    return out


def check_update(cfg: dict, gid: str, proj) -> dict | None:
    """和上次记下的对比；有变化就记一条提醒并返回它。第一次见到这个工具只记下，不提醒。"""
    try:
        snap = snapshot(proj)
    except Exception:
        return None
    path = SEEN / f"{gid}.json"
    seen = jsonio.read(path, None)
    if seen == snap:
        return None
    jsonio.write(path, snap)
    if not seen:
        return None
    from .store import Store
    used = []
    try:
        for r in Store(cfg["machine"]["data_dir"]).routines(gid)["routines"].values():
            for t in r.get("tasks", []):
                if t["task"] not in used:
                    used.append(t["task"])
    except Exception:
        pass
    new_tasks = [t for t in snap["tasks"] if t not in seen.get("tasks", [])]
    changes = []
    so = seen.get("options", {})
    for tname in used:
        td = next((t for t in proj.tasks if t["name"] == tname), None)
        if not td:
            continue
        for opt in _opt_tree(proj, proj.task_options(td)):
            now = snap["options"].get(opt)
            if now is None:
                continue
            if opt not in so:
                changes.append({"task": tname, "option": opt, "new": True, "cases": now})
            else:
                add = [c for c in now if c not in so[opt]]
                if add:
                    changes.append({"task": tname, "option": opt, "new": False, "cases": add})
    if not new_tasks and not changes and snap["version"] == seen.get("version"):
        return None
    g = cfg["games"].get(gid, {})
    up = {"game": gid, "name": g.get("name", gid), "from": seen.get("version", ""), "to": snap["version"],
          "at": datetime.now().strftime("%Y-%m-%d %H:%M"), "new_tasks": new_tasks, "changes": changes,
          "gone_tasks": [t for t in seen.get("tasks", []) if t not in snap["tasks"]]}
    doc = jsonio.read(UPDATES, {"updates": []})
    doc["updates"] = [u for u in doc["updates"] if u.get("game") != gid] + [up]
    jsonio.write(UPDATES, doc)
    return up


def updates() -> list[dict]:
    return jsonio.read(UPDATES, {"updates": []})["updates"]


def dismiss(gid: str):
    doc = jsonio.read(UPDATES, {"updates": []})
    doc["updates"] = [u for u in doc["updates"] if u.get("game") != gid]
    jsonio.write(UPDATES, doc)


# ================= 2. 选项写回工具 =================
def _saved_from_choices(proj, opt_names: list, choices: dict, old: list | None, depth=0) -> list:
    """按名称的选择 → MFA 保存的格式（序号 / 勾选 / 输入值）。旧列表里别的项（例如没选中的那一版的子选项）原样留着。"""
    from .mfa import _case_index
    oldm = {o.get("name"): o for o in (old or []) if isinstance(o, dict)}
    out, done = [], set()
    for name in opt_names:
        od = proj.options.get(name)
        if not od or name in done or depth > 12:
            continue
        done.add(name)
        prev = dict(oldm.get(name) or {"name": name})
        typ = od.get("type", "select")
        want = choices.get(name)
        if typ == "input":
            if isinstance(want, dict):
                prev["data"] = {**(prev.get("data") or {}), **{k: str(v) for k, v in want.items()}}
            out.append(prev)
            continue
        cases = od.get("cases", []) or []
        if typ == "checkbox":
            if isinstance(want, list):
                prev["selected_cases"] = [c for c in want if _case_index(od, c) is not None]
            picked = prev.get("selected_cases") or []
            subs = []
            for c in picked:
                i = _case_index(od, c)
                if i is not None:
                    subs += cases[i].get("option", []) or []
            if subs:
                prev["sub_options"] = _saved_from_choices(proj, subs, choices, prev.get("sub_options"), depth + 1)
            out.append(prev)
            continue
        if isinstance(want, str) and _case_index(od, want) is not None:
            prev["index"] = _case_index(od, want)
        idx = prev.get("index") if isinstance(prev.get("index"), int) else 0
        subs = (cases[idx].get("option", []) or []) if 0 <= idx < len(cases) else []
        if subs:
            prev["sub_options"] = _saved_from_choices(proj, subs, choices, prev.get("sub_options"), depth + 1)
        out.append(prev)
    for name, o in oldm.items():  # 旧的、这次没涉及的：原样保留
        if name not in done:
            out.append(o)
    return out


def _wanted(cfg: dict, gid: str) -> dict:
    """{任务名: 选项}：几套任务预设里同一个任务，以排在前面的那套为准。"""
    from .store import Store
    want = {}
    for r in Store(cfg["machine"]["data_dir"]).routines(gid)["routines"].values():
        for t in r.get("tasks", []):
            if t["task"] not in want and t.get("choices"):
                want[t["task"]] = t["choices"]
    return want


def write_back(cfg: dict, gid: str) -> str:
    """把任务预设的选项写进工具的配置。返回说明；工具开着时记成待写。"""
    from . import games as G
    from .runstate import is_running
    ad = G.adapter(cfg, gid)
    if G.kind(cfg["games"][gid]) != "maa":
        return ""
    proj = ad.project()
    if not proj.saved_path or not os.path.exists(proj.saved_path):
        return "工具里还没有保存过配置，没写"
    gui = cfg["games"][gid].get("gui_exe")
    if gui and is_running(gui):
        _pending(gid, True)
        return f"{gui} 开着，等它关掉后再写进去"
    want = _wanted(cfg, gid)
    root = jsonio.read(proj.saved_path, None)
    if not isinstance(root, dict):
        return "工具的配置读不出来，没写"
    keys = [k for k in ("Instance.default.TaskItems", "TaskItems") if isinstance(root.get(k), list)]
    if not keys:
        return "工具的配置里没有任务列表，没写"
    changed = 0
    # 新版 MFA 的配置里两份列表都有（Instance.default.TaskItems 是现在用的）：两份都改，免得换版本后又读到旧的
    for it in [x for k in keys for x in root[k]]:
        if not isinstance(it, dict) or it.get("name") not in want:
            continue
        try:
            td = proj.find_task(it["name"])
        except KeyError:
            continue
        new = _saved_from_choices(proj, proj.task_options(td), want[it["name"]], it.get("option"))
        if proj._choices_from_saved(td, new) != proj._choices_from_saved(td, it.get("option")):  # 意思一样就不动
            it["option"] = new
            changed += 1
    if changed:
        BACKUP.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(proj.saved_path, BACKUP / f"{gid}-{stamp}-{Path(proj.saved_path).name}")
        olds = sorted(BACKUP.glob(f"{gid}-*"))
        for f in olds[:-5]:  # 每个游戏留最近 5 份
            try:
                f.unlink()
            except OSError:
                pass
        with open(proj.saved_path, "w", encoding="utf-8") as f:
            json.dump(root, f, ensure_ascii=False, indent=4)
        ad._proj = None  # 下次重新读（选项的「工具里的值」跟着变）
    _pending(gid, False)
    n = len({x.get("name") for k in keys for x in root[k] if isinstance(x, dict) and x.get("name") in want}) if changed else 0
    return f"已把 {n} 个任务的选项写进 {Path(proj.saved_path).name}" if changed else ""


def _pending(gid: str, on: bool):
    doc = jsonio.read(PENDING, {})
    if on:
        doc[gid] = datetime.now().strftime("%Y-%m-%d %H:%M")
    else:
        doc.pop(gid, None)
    jsonio.write(PENDING, doc)


def flush(cfg: dict, log=None):
    """调度每轮顺手：之前因为工具开着没写成的，工具关了就写。"""
    for gid in list(jsonio.read(PENDING, {}).keys()):
        if gid not in cfg["games"]:
            _pending(gid, False)
            continue
        try:
            msg = write_back(cfg, gid)
            if msg and log and "开着" not in msg:
                log(f"任务预设的选项{msg}", gid)
        except Exception as e:
            if log:
                log(f"把选项写回工具出错：{type(e).__name__}: {e}", gid)
            _pending(gid, False)
