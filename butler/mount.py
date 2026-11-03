"""挂载：游戏是挂载单位，把脚本接进来、取消挂载、重新挂载、彻底删除。

- 识别（detect）：选一个文件夹 / 程序，认出是什么：
    有 interface.json            → MaaFramework 项目（type = "maa"），任务和选项从 interface.json 读
    MAA.exe / maa.exe（明日方舟） → 明日方舟 MAA（type = "maa_ark"，见 arknights.py）
    有预设的程序（BetterGI.exe、March7th Assistant.exe） → 预设里的类型
    其他 .exe / .bat / .cmd / .py → 自定义命令（type = "command"），一条命令 = 一个任务
  认出来的脚本如果对得上 config/presets/ 里的某个预设（按 interface 名称 / 文件夹名 / GitHub 地址 / 程序名），
  添加时套用预设里调好的设置（判定依据、超时、时段、默认日常……）。
- 添加（add）：
    这个脚本以前挂过、后来取消了（同一个文件夹，或同一个项目名 / 程序名）→ 恢复原来那一条，路径变了只更新路径；
    已经挂着 → 提示已经挂着；
    都不是 → 新建一条游戏记录（data/games/<游戏>.json），生成任务预设、往每天的日程里加一个批次、写抽卡资源项。
- 取消挂载（unfollow）：记录和数据都留着，调度、活动、主页都不再出现；重新挂载就接上。
- 彻底删除（delete）：每个模块删掉自己存的这个游戏的数据，再删记录，像没挂过一样。
"""
from __future__ import annotations

import copy
import hashlib
import os
import re
import time
from datetime import datetime
from pathlib import Path

from . import gamesdb as GD
from .mfa import load_json as _jsonc

CMD_EXT = (".exe", ".bat", ".cmd", ".py", ".ps1")
PATH_KEYS = ("project_dir", "exe")


def _iface_all(d: str) -> dict:
    """interface.json 连同 import 的分文件（task / option / preset 合起来）。"""
    j = _jsonc(os.path.join(d, "interface.json"))
    j["_dir"] = d
    for rel in j.get("import", []) or []:
        part = _jsonc(os.path.join(d, rel))
        j.setdefault("task", []).extend(part.get("task", []) or [])
        if isinstance(part.get("option"), dict):
            j.setdefault("option", {}).update(part["option"])
        j.setdefault("preset", []).extend(part.get("preset", []) or [])
    return j


def _guess_package(d: str, res_paths: list[str]) -> str:
    """在资源的 pipeline 里找 StartApp 用的包名（用来卡住时强制重启游戏）。找不到返回空。"""
    pat = re.compile(r'"package"\s*:\s*"([A-Za-z][\w]*(?:\.[\w]+)+)')
    seen: dict = {}
    for rp in res_paths:
        base = Path(d, rp.replace("{PROJECT_DIR}", "").lstrip("/\\")) if "{PROJECT_DIR}" in rp else Path(d, rp)
        for f in list(base.glob("pipeline/**/*.json"))[:400]:
            try:
                for m in pat.finditer(f.read_text(encoding="utf-8", errors="ignore")):
                    seen[m.group(1)] = seen.get(m.group(1), 0) + 1
            except OSError:
                continue
    return max(seen, key=seen.get) if seen else ""


def _label(text: str, j: dict) -> str:
    """interface 里的文字：$ 开头的是多语言键，按中文翻译取。"""
    if not isinstance(text, str) or not text.startswith("$"):
        return text or ""
    from .mfa import translate
    return translate(j, text)


def detect(path: str) -> dict:
    """用户选的文件夹 / 程序 → 识别结果（不保存）。"""
    path = (path or "").strip().strip('"')
    if not path or not os.path.exists(path):
        return {"ok": False, "error": f"找不到 {path or '（没选）'}"}
    p = Path(path)
    d = p if p.is_dir() else p.parent
    # 1. MaaFramework 项目
    for cand in [d, d / "app", *[x for x in d.glob("*") if x.is_dir()][:20]]:
        if (cand / "interface.json").exists():
            try:
                j = _iface_all(str(cand))
            except Exception as e:
                return {"ok": False, "error": f"interface.json 读不出来：{e}"}
            ctrls = []
            for c in j.get("controller", []) or []:
                t = str(c.get("type", "Adb"))
                ctrls.append({"name": c.get("name", t), "label": _label(c.get("label") or c.get("name", t), j), "type": t.lower()})
            res = []
            for r in j.get("resource", []) or []:
                res += [x for x in (r.get("path") or []) if isinstance(x, str)]
            tasks = j.get("task", []) or []
            name = _label(j.get("label") or j.get("name") or cand.name, j)
            unknown = sorted(set(j) - KNOWN_TOP)
            from .mfa import Project
            try:
                pj = Project(str(cand))
                tool_r = [x["name"] for x in pj.preset_routines() if x["tasks"] and not x["error"]] + \
                    list(pj.instance_routines()) + (["工具默认勾选"] if any(t.get("default_check") for t in pj.tasks) else [])
            except (OSError, ValueError, KeyError) as e:
                return {"ok": False, "error": f"读工具自带的预设失败：{e}"}
            return {"ok": True, "type": "maa", "tool_routines": tool_r, "kind_label": "MaaFramework 项目", "path": str(cand),
                    "name": name, "project_name": j.get("name", ""), "version": str(j.get("version") or ""),
                    "controllers": ctrls, "pc": bool(ctrls) and all(c["type"] == "win32" for c in ctrls),
                    "tasks": len(tasks), "default_tasks": [t.get("name") for t in tasks if t.get("default_check")],
                    "package": _guess_package(str(cand), res), "github": j.get("github", ""),
                    "interface_version": j.get("interface_version", 1),
                    "warnings": ([f"这些 interface.json 设置管家还不认识，会忽略：{'、'.join(unknown)}"] if unknown else [])}
    # 2. 明日方舟 MAA：图形界面版（MAA.exe + MaaCore.dll）或 maa-cli（maa.exe）
    exe_ = next((d / n for n in ("MAA.exe", "maa.exe") if (d / n).exists()), None)
    if exe_ is not None and (p.is_dir() or p.name.lower() == "maa.exe"):
        gui = (d / "MaaCore.dll").exists()
        return {"ok": True, "type": "maa_ark", "kind_label": "明日方舟 MAA" + ("（图形界面版）" if gui else "（maa-cli）"),
                "path": str(exe_), "name": "明日方舟", "project_name": "arknights", "pc": gui,
                "controllers": [] if gui else [{"name": "adb", "label": "模拟器", "type": "adb"}],
                "package": "com.hypergryph.arknights",
                "warnings": ["图形界面版只能整体跑一次「一键长草」：先在 MAA 设置里打开「启动 MAA 后直接运行」和「完成后退出 MAA」。"
                             "想逐项控制（刷理智、公招、基建……）请装 maa-cli。"] if gui else
                            ["还没在明日方舟实机上测过（10-23）：第一次跑时留意结果。"]}
    # 3. 有预设的程序（BetterGI、三月七……）
    exe = str(p) if p.is_file() and p.suffix.lower() in CMD_EXT else ""
    for cand in ([Path(exe)] if exe else [x for x in d.glob("*.exe")]):
        pr = GD.match_preset({"type": "", "path": str(cand)})
        if pr and pr.get("type") not in (None, "maa"):
            return {"ok": True, "type": pr["type"], "kind_label": pr["kind"], "path": str(cand), "name": pr["game"],
                    "tool_routines": ["BetterGI 当前的一条龙"] if pr["type"] == "bettergi" else [],
                    "project_name": "", "pc": True, "controllers": [], "warnings": [], "package": ""}
    # 4. 自定义命令
    if not exe:
        cands = [x for x in d.glob("*") if x.suffix.lower() in CMD_EXT]
        if len(cands) == 1:
            exe = str(cands[0])
    if exe:
        return {"ok": True, "type": "command", "kind_label": "自定义命令", "path": exe, "name": Path(exe).stem,
                "pc": True, "controllers": [], "warnings": [], "package": ""}
    return {"ok": False, "error": "这个文件夹里没找到 interface.json，也没找到明日方舟 MAA；"
                                  "要接普通脚本，请直接选它的程序（.exe / .bat / .py）"}


KNOWN_TOP = {"interface_version", "name", "label", "title", "version", "icon", "github", "contact", "license", "welcome",
             "description", "mirrorchyan_rid", "mirrorchyan_multiplatform", "languages", "controller", "resource", "agent",
             "task", "option", "global_option", "import", "preset", "group", "message", "url", "custom_title",
             "framework_version", "$schema", "_dir"}


def _split_args(s) -> list[str]:
    if isinstance(s, list):
        return [str(x) for x in s]
    import shlex
    try:
        return shlex.split(s or "", posix=False)
    except ValueError as e:
        raise ValueError(f"参数里的引号没配对：{s}") from e




def _norm(x) -> str:
    return os.path.normcase(os.path.normpath(str(x or ""))).rstrip("\\/")


def identify(cfg: dict, info: dict) -> str:
    """这个脚本是不是已经有记录：同一个文件夹 / 程序（挂着的和取消的都算），
    或取消挂载的记录里同一个项目名（MaaFramework）/ 同一个程序名。返回游戏 id，没有返回空。"""
    want = _norm(info.get("path"))
    recs = GD.all_records(cfg)
    for gid, g in recs.items():
        for k in PATH_KEYS:
            have = _norm(g.get(k))
            if have and (have == want or have.startswith(want + os.sep) or want.startswith(have + os.sep)):
                return gid
    from . import games as G
    for gid, g in recs.items():
        if g.get("followed", True) or g.get("type", "maa") != info.get("type"):
            continue
        if G.type_class(g).same_tool(g, info):
            return gid
    return ""


def _slug(name: str, taken) -> str:
    base = re.sub(r"[^a-z0-9]+", "", (name or "").lower())[:12] or "g" + hashlib.sha1((name or "x").encode()).hexdigest()[:6]
    gid, n = base, 2
    while gid in taken:
        gid, n = f"{base}{n}", n + 1
    return gid


def _commands(cmds) -> dict:
    out = {}
    for c in cmds:
        nm = (c.get("name") or "").strip()
        if nm:
            out[nm] = {"args": _split_args(c.get("args", "")), "timeout": int(c.get("timeout") or 60),
                       "done": [x for x in c.get("done", []) if x], "fail": [x for x in c.get("fail", []) if x],
                       "exit_ok_means_done": not c.get("done")}
    if not out:
        raise ValueError("至少要有一条命令")
    return out


def add(cfg: dict, info: dict) -> dict:
    """按识别结果 + 你填的几项挂上一个游戏。返回 {"id", "restored": 是否恢复了以前的记录}。"""
    from . import games as G
    t = info.get("type")
    if t not in G.TYPES:
        raise ValueError("不认识的类型")
    cls = G.TYPES[t]
    same = identify(cfg, info)
    if same:
        g = GD.record(cfg, same)
        if g.get("followed", True):
            raise ValueError(f"「{g['name']}」已经挂着了，用的就是这个脚本。要改设置请到「设置 → 工具与游戏」。")
        g[cls.path_field] = info["path"]   # 路径变了只更新路径
        if info.get("emulator"):
            g["emulator"] = info["emulator"]
        if info.get("project_name"):
            g["project_name"] = info["project_name"]
        g["followed"] = True
        if (info.get("display_name") or "").strip():  # 批注 #171：重新挂载时填的显示名字
            g["name"] = info["display_name"].strip()
        GD.save(cfg, same, g)
        autofix(cfg, same, force=True)
        if info.get("import_tool_routines"):  # 11-02：重新挂载时也能选「一同导入工具自带的预设」
            try:
                import_routines(cfg, same, None)
            except Exception:
                pass
        return {"id": same, "restored": True}
    pr = GD.match_preset(info)
    g = copy.deepcopy(pr["config"]) if pr and pr.get("config") else {}
    g.update({"type": t, "followed": True, "added": datetime.now().strftime("%Y-%m-%d"),
              "import_tool_routines": bool(info.get("import_tool_routines")),  # 挂载时问的：一同导入工具自带的预设
              "name": (info.get("name") or g.get("name") or "").strip(), "refresh": info.get("refresh") or g.get("refresh")})
    if not g["name"]:
        raise ValueError("要填显示名")
    if not g["refresh"]:
        raise ValueError("要填每天的刷新时间")
    if pr:
        g["preset"] = pr["id"]
    cls.fill_record(g, info)
    if "pc" in info:
        g["pc"] = bool(info["pc"])
    from .judge import validate
    validate(g.get("judge"))
    recs = GD.all_records(cfg)
    want = (pr or {}).get("gid")
    gid = want if want and want not in recs else _slug(info.get("project_name") or g["name"], recs)
    g["order"] = max([r.get("order", 0) for r in recs.values()] + [0]) + 1
    GD.save(cfg, gid, g)
    autofix(cfg, gid, force=True)  # 11-02：挂上后找不到工具文件（选错了一层之类）：先自动查找一次
    g = GD.record(cfg, gid)
    _first_setup(cfg, gid, g)
    return {"id": gid, "restored": False}


def _first_setup(cfg: dict, gid: str, g: dict):
    """新挂上的游戏：生成任务预设（选了导入工具自带的预设才有）、写抽卡资源项、留证截图的初始勾选。
    不加定时：什么时候跑由你在任务预设上设（用户 10-26 定：管家不替你决定）。"""
    from . import games as G
    from . import readings as RD
    from .store import Store
    if G.available(g)[0]:
        Store(cfg["machine"]["data_dir"]).ensure_routines(gid, G.adapter(cfg, gid).seed())
    if g.pop("import_tool_routines", None) is not None:  # 只在第一次挂上时导入；以后任务预设删空了也不会自己冒出来
        GD.save(cfg, gid, g)
    if g.get("gacha_resources"):
        RD.set_defs(cfg, gid, g["gacha_resources"])
    if g.get("evidence_default"):
        from . import settings as S
        tasks = S.get(cfg, "evidence")["tasks"]
        if gid not in tasks:
            S.update(cfg, "evidence", {"tasks": {**tasks, gid: list(g["evidence_default"])}})


def update(cfg: dict, gid: str, patch: dict):
    """改游戏设置（名字、刷新时间、工具路径、模拟器、包名、命令、任务的运行时段、运行前调分辨率）。"""
    g = GD.record(cfg, gid)
    for k in ("name", "refresh", "package", "emulator", "log_glob", "project_dir", "exe"):
        if k in patch:
            g[k] = str(patch[k]).strip()
    if "refresh" in patch:
        from .timeutil import parse_hm
        parse_hm(g["refresh"])
    for k in ("read_notice", "read_gacha"):  # 跑日常时顺带读公告 / 读抽卡资源（planner.read_extras）
        if k in patch:
            g[k] = bool(patch[k])
    if "resolution_switch" in patch:  # 电脑游戏：运行前调成 1920×1080 窗口化、跑完恢复
        from . import pcres
        if not pcres.supported(gid):
            raise ValueError("这个游戏不支持运行前调整分辨率")
        g["resolution_switch"] = bool(patch["resolution_switch"])
    if "commands" in patch:
        from . import games as G
        if G.type_class(g).user_commands(g) is None:
            raise ValueError("只有自定义命令能改命令")
        g["commands"] = _commands(patch["commands"])
    if "windows" in patch:  # 任务的运行时段：{任务键或任务名: "12:00-15:00,17:30-21:00"}
        from .timeutil import parse_windows
        w = {str(k): str(v) for k, v in (patch["windows"] or {}).items() if str(v).strip()}
        for k, v in w.items():
            try:
                parse_windows(v)
            except ValueError:
                raise ValueError(f"「{k}」的运行时段格式不对：{v}（写成 HH:MM-HH:MM，多段用逗号隔开）")
        g["windows"] = w
    GD.save(cfg, gid, g)


def follow(cfg: dict, gid: str, on: bool):
    g = GD.record(cfg, gid)
    g["followed"] = bool(on)
    GD.save(cfg, gid, g)


def delete(cfg: dict, gid: str) -> dict:
    """彻底删除：每个模块删掉自己存的这个游戏的数据，最后删记录。"""
    from . import evidence, games, gacha, news, readings, report, signals, pcres
    from .bettergi import forget as bgi_forget
    from .runstate import RunState
    from .schedule import Schedule
    from .scheduler import forget_state
    from .store import Store
    GD.record(cfg, gid)  # 没有这个游戏就报错
    rs = RunState(cfg["machine"]["data_dir"])
    cur = rs.current()
    if cur and gid in cur.get("games", []):
        raise ValueError("这个游戏正在跑，先停止再删除")
    Store(cfg["machine"]["data_dir"]).forget(gid)
    Schedule(cfg).forget(gid)
    forget_state(cfg, gid)
    signals.clear_fuse(cfg, gid)
    report.forget(cfg, gid)
    games.forget(cfg, gid)
    evidence.forget(cfg, gid)
    readings.forget(cfg, gid)
    gacha.forget(cfg, gid)
    news.forget(cfg, gid)
    pcres.forget(cfg, gid)
    bgi_forget(cfg, gid)
    rs.forget(gid)
    GD.delete(cfg, gid)
    return {"ok": True}


_FIX_AT: dict = {}


def autofix(cfg: dict, gid: str, force: bool = False) -> str:
    """工具路径不对（找不到 interface.json / 程序）时，按预设里写的常见文件夹名自动查找，找到就改过来。
    返回改成的路径；没找到 / 不用改返回空。同一个游戏 10 分钟内只找一次（force 除外）。"""
    from . import games as G
    from . import tools as T
    try:
        g = GD.record(cfg, gid)
    except KeyError:
        return ""
    if G.available(g)[0] or not g.get("preset") or not g.get("followed", True):
        return ""
    if not force and time.time() - _FIX_AT.get(gid, 0) < 600:
        return ""
    _FIX_AT[gid] = time.time()
    field = G.type_class(g).path_field
    for p in T.scan(gid, cfg):
        if G.available({**g, field: p})[0]:
            g[field] = p
            GD.save(cfg, gid, g)
            return p
    return ""


def import_routines(cfg: dict, gid: str, names: list[str] | None) -> list[str]:
    """把工具自带的预设导入成任务预设（11-02：挂上以后也能导入）。names = None 导入全部。
    和已有的同名时加「（导入）」。返回导入后的名字。"""
    from . import games as G
    from .store import Store
    st = Store(cfg["machine"]["data_dir"])
    ad = G.adapter(cfg, gid)
    tr = ad.tool_routines() if hasattr(ad, "tool_routines") else {}
    doc = st.routines(gid)
    got = []
    for name, items in tr.items():
        if names is not None and name not in names:
            continue
        nm, k = name, 2
        while nm in doc["routines"]:
            nm = f"{name}（导入{'' if k == 2 else k - 1}）"
            k += 1
        doc["routines"][nm] = {"tasks": items}
        got.append(nm)
    if got:
        st.save_routines(gid, doc)
    return got


def listing(cfg: dict) -> list[dict]:
    """设置页「工具与游戏」：挂着的和取消挂载的都列出来。"""
    from . import games as G
    out = []
    for gid in list(GD.all_records(cfg)):  # 11-02：路径不对的先自动查找一次
        fixed = autofix(cfg, gid)
        if fixed:
            _FIXED[gid] = fixed
    for gid, g in GD.all_records(cfg).items():
        ok, why = G.available(g)
        on = g.get("followed", True)
        pr = GD.preset(g["preset"]) if g.get("preset") else None
        cls = G.type_class(g)
        out.append({"id": gid, "name": g["name"], "type": G.kind(g), "followed": on, "available": ok,
                    "message": why if on else "已取消挂载", "path": g.get(cls.path_field, ""),
                    "field": cls.path_field, "emulator": g.get("emulator", ""),
                    "refresh": g["refresh"], "preset": (pr or {}).get("name", ""), "url": (pr or {}).get("repo", ""),
                    "screen": (pr or {}).get("screen", ""), "commands": cls.user_commands(g),
                    "needs_emulator": cls.uses_emulator(g), "autofixed": _FIXED.pop(gid, ""),
                    "preset_id": g.get("preset", "")})
    return out


_FIXED: dict = {}
