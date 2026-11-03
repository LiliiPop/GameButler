"""读 MaaFramework 项目的 interface.json 和 MFAAvalonia 保存的选项，拼出每个任务要用的 pipeline_override。

管家不改 MAA 项目的任何文件，只读：
- <项目>/interface.json：全部任务、选项定义；interface v2 的 "import" 分文件也一起读（允许 // 注释、尾逗号）
- MFA 保存的选项：
  · 旧版 MFA：config/*.json（每个文件一套配置，键 TaskItems / Instance.default.TaskItems）
  · 新版 MFA：config/instances/*.json（每个文件一个「实例」，有 InstanceName；TaskItems 里 default_check = 是否勾选）

选项类型：select / switch（单选，值 = case 名）、checkbox（多选，值 = case 名列表）、input（值 = {输入名: 值}）。

ProjectInterface V2（v2.3.1）里管家支持的（10-23 补齐）：
- 控制器从 interface.json 读（type Adb / Win32，win32 的窗口匹配和截图 / 输入方式），可以选哪一个；attach_resource_path
- 选项作用范围：global_option < resource.option < controller.option < task.option（后面的覆盖前面的）；
  选项 / 任务上的 controller、resource 限制：当前控制器或资源不适用的选项不生效、任务不显示
- 多语言：languages + "$键"，取中文；description / welcome 可以是 Markdown 文件路径
- agent 可以是数组（多个扩展进程）
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re


# 批注 #175（11-03）：管家自己管的事，工具里的同类选项在管家里不显示、不传（保持工具的默认值）。
# MaaSH 的「质检截图」是作用于全部任务的资源选项，原来每个任务下面都显示一遍；截图由管家「设置 → 运行记录输出 · 截图」管
BUTLER_MANAGED = {"质检截图"}


# ---------------- 读 JSON（容忍注释和尾逗号） ----------------
def _strip_jsonc(s: str) -> str:
    out, i, n, in_str = [], 0, len(s), False
    while i < n:
        c = s[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(s[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if s.startswith("//", i):
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        if s.startswith("/*", i):
            j = s.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_strip_jsonc(text))


def deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


def _case_index(od: dict, case_name) -> int | None:
    for i, c in enumerate(od.get("cases", [])):
        if c.get("name") == case_name:
            return i
    return None


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


_TR_CACHE: dict = {}
_TR_ERR: dict = {}  # 翻译文件读不出来的项目文件夹 → 原因（游戏页顶上显示）


def translate(iface: dict, text, base_dir: str | None = None):
    """多语言：「$键」→ 中文（languages 里 zh_cn / zh-CN / zh_Hans 的翻译文件）。不是 $ 开头的原样返回。"""
    if not isinstance(text, str) or not text.startswith("$"):
        return text
    base_dir = base_dir or iface.get("_dir", "")
    langs = iface.get("languages") or {}
    key = (base_dir, json.dumps(langs, sort_keys=True))
    if key not in _TR_CACHE:
        table = {}
        for code in ("zh_cn", "zh-CN", "zh_CN", "zh-cn", "zh_Hans", "zh-Hans", "zh"):
            rel = langs.get(code)
            if rel:
                path = os.path.join(base_dir, rel)
                try:
                    table = load_json(path)
                except (OSError, ValueError) as e:  # 只影响显示：任务名显示成原始键名，游戏页顶上说明原因
                    _TR_ERR[base_dir] = f"工具的中文翻译文件读不出来，任务名显示成原始键名：{path}（{e}）"
                break
        _TR_CACHE[key] = table
    k = text[1:]
    return _TR_CACHE[key].get(k) or _TR_CACHE[key].get(text) or k


def _doc_text(base_dir: str, text) -> str:
    """description 可以是直接的文字、Markdown 文件路径或网址：文件就读出来（截断），网址原样。"""
    if not isinstance(text, str) or not text:
        return ""
    if len(text) < 200 and re.search(r"\.(md|txt)$", text, re.I):
        path = os.path.join(base_dir, text)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8-sig") as f:
                    return f.read()[:2000]
            except (OSError, UnicodeDecodeError) as e:  # 只影响显示：说明处直接写原因
                return f"（说明文件读不出来：{path}，{e}）"
    return text


class Project:
    def __init__(self, project_dir: str, mfa_config: str | None = None, mfa_instance: str | None = None,
                 resource: str | None = None, controller: str | None = None):
        self.dir = project_dir
        self.iface = load_json(os.path.join(project_dir, "interface.json"))
        self.iface["_dir"] = project_dir
        self.want_controller = controller
        self.options: dict = dict(self.iface.get("option", {}) or {})
        self.tasks: list = list(self.iface.get("task", []) or [])
        self.presets: list = list(self.iface.get("preset", []) or [])
        for rel in self.iface.get("import", []) or []:  # interface v2：任务和选项分文件
            path = os.path.join(project_dir, rel)
            if not os.path.exists(path):
                continue
            part = load_json(path)
            self.tasks += part.get("task", []) or []
            self.options.update(part.get("option", {}) or {})
            self.presets += part.get("preset", []) or []
            for k in ("global_option",):
                if part.get(k):
                    self.iface.setdefault(k, []).extend(part[k])
        self.want_instance = mfa_instance
        self.want_resource = resource
        self.saved_path = ""
        self.instances = self._load_instances(mfa_config)          # [{name, path, root, items}]
        main = self._pick_instance(mfa_config, mfa_instance)
        self.saved_root = main["root"] if main else {}
        self.saved_path = main["path"] if main else ""
        self.instance_name = main["name"] if main else ""
        # 按任务名查 MFA 保存值：先用选定的实例/配置，其次其余实例（同名任务取第一个）
        self.saved_items: dict = {}
        # （旧版 MFA 的多份 config 是互相独立的配置，不互相补）
        others = [i for i in self.instances if i is not main and main and main["new"] and i["new"]]
        for inst in ([main] if main else []) + others:
            for it in inst["items"]:
                self.saved_items.setdefault(it.get("name"), it)

    # ---------- MFA 保存的配置 ----------
    def _load_instances(self, mfa_config: str | None) -> list[dict]:
        paths = []
        if mfa_config:
            paths.append(os.path.join(self.dir, mfa_config))
        found = glob.glob(os.path.join(self.dir, "config", "instances", "*.json"))
        found += glob.glob(os.path.join(self.dir, "config", "*.json"))
        paths += sorted(found, key=os.path.getmtime, reverse=True)  # 最近保存的在前
        out, seen = [], set()
        for path in paths:
            if path in seen or not os.path.exists(path):
                continue
            seen.add(path)
            try:
                d = load_json(path)
            except (OSError, ValueError) as e:
                raise ValueError(f"MFA 保存的配置读不出来：{path}（{e}）") from e
            if not isinstance(d, dict):
                continue  # 不是 MFA 的配置（例如别的工具放在 config 里的列表）
            for key in ("Instance.default.TaskItems", "TaskItems"):
                if isinstance(d.get(key), list) and d[key]:
                    name = d.get("InstanceName") or os.path.splitext(os.path.basename(path))[0]
                    items = [x for x in d[key] if isinstance(x, dict)]  # MFA 存的列表里偶尔有 null（10-24 MaaSH）
                    out.append({"name": name, "path": path, "root": d, "items": items,
                                "new": "instances" in os.path.normpath(path).split(os.sep)})
                    break
        return out

    def _pick_instance(self, mfa_config, mfa_instance):
        if not self.instances:
            return None
        if mfa_config:
            want = os.path.normpath(os.path.join(self.dir, mfa_config))
            for i in self.instances:
                if os.path.normpath(i["path"]) == want:
                    return i
        if mfa_instance:
            for i in self.instances:
                if i["name"] == mfa_instance:
                    return i
        return self.instances[0]  # 没指定：最近保存的那份

    def adb_device(self) -> dict:
        return self.saved_root.get("Instance.default.AdbDevice") or self.saved_root.get("AdbDevice") or {}

    def resource_name(self) -> str:
        return (self.want_resource or self.saved_root.get("Instance.default.Resource")
                or self.saved_root.get("Resource") or "")

    def resource_def(self) -> dict:
        res = self.iface.get("resource", []) or []
        want = self.resource_name()
        for r in res:
            if r.get("name") == want:
                return r
        if self.want_resource:
            raise KeyError(f"interface.json 里没有资源「{self.want_resource}」，可选：{[r.get('name') for r in res]}")
        ctl = self.controller_name()
        for r in res:  # 没指定：第一个支持当前控制器的
            if not r.get("controller") or ctl in r["controller"]:
                return r
        return res[0] if res else {}

    def resource_paths(self) -> list[str]:
        """按 interface.json 里的顺序返回资源包路径（例如 B 服 = base + bilibili，后加载的覆盖先加载的）；
        当前控制器有 attach_resource_path 的，接在后面。"""
        paths = list(self.resource_def().get("path") or [])
        paths += list(self.controller_def().get("attach_resource_path") or [])
        return [p.replace("{PROJECT_DIR}", ".").lstrip("/") if isinstance(p, str) and p.startswith("{PROJECT_DIR}") else p
                for p in paths]

    def controllers(self) -> list[dict]:
        return list(self.iface.get("controller", []) or [])

    def controller_def(self) -> dict:
        cs = self.controllers()
        for c in cs:
            if c.get("name") == self.want_controller:
                return c
        if self.want_controller is None:
            return next((c for c in cs if str(c.get("type", "")).lower() == "adb"), cs[0] if cs else {})
        return cs[0] if cs else {}

    def controller_name(self) -> str:
        return self.controller_def().get("name", "")

    def win32_config(self) -> dict:
        """interface.json 里 Win32 控制器的设置 → 执行器用的格式（窗口匹配、截图方式、输入方式）。"""
        w = self.controller_def().get("win32") or {}
        inp = w.get("input")
        return {"class_regex": w.get("class_regex", ""), "window_regex": w.get("window_regex", ""),
                "screencap": w.get("screencap", "FramePool"), "mouse": w.get("mouse", inp or "Seize"),
                "keyboard": w.get("keyboard", inp or "Seize")}

    def agent(self):
        """扩展进程：一个（dict）或多个（list）。统一返回 list 或 None。"""
        a = self.iface.get("agent")
        if not a:
            return None
        return a if isinstance(a, list) else [a]

    # ---------- 选项作用范围（v2.3） ----------
    def _applies(self, d: dict) -> bool:
        """选项 / 任务上的 controller、resource 限制：当前的不在名单里就不适用。"""
        cl, rl = d.get("controller"), d.get("resource")
        if cl and self.controller_name() and self.controller_name() not in cl:
            return False
        if rl and self.resource_name_eff() and self.resource_name_eff() not in rl:
            return False
        return True

    def resource_name_eff(self) -> str:
        return self.resource_def().get("name", "")  # 指定的资源不存在：resource_def 直接报错

    def scoped_options(self) -> list[str]:
        """不属于某个任务、但对所有任务生效的选项：global_option、当前资源的 option、当前控制器的 option（按这个顺序）。"""
        out = []
        for name in (list(self.iface.get("global_option", []) or []) + list(self.resource_def().get("option", []) or [])
                     + list(self.controller_def().get("option", []) or [])):
            if name not in out:
                out.append(name)
        return out

    def task_options(self, task_def: dict) -> list[str]:
        """这个任务要显示 / 生效的全部选项：作用范围选项在前，任务自己的在后（后面的覆盖前面的）。"""
        out = [n for n in self.scoped_options()]
        for n in task_def.get("option", []) or []:
            if n in out:
                out.remove(n)
            out.append(n)
        return [n for n in out if self._applies(self.options.get(n) or {}) and n not in BUTLER_MANAGED]

    def tr(self, text):
        return translate(self.iface, text, self.dir)

    # ---------- 任务 ----------
    def task_names(self) -> list[str]:
        return [t["name"] for t in self.tasks]

    def find_task(self, name: str) -> dict:
        for t in self.tasks:
            if t["name"] == name:
                return t
        norm = lambda s: re.sub(r"\s+", "", s)
        for t in self.tasks:  # 容忍空格差异
            if norm(t["name"]) == norm(name):
                return t
        raise KeyError(f"interface.json 里没有任务「{name}」")

    def selected_case(self, task_name: str, option_name: str) -> str:
        """供界面显示：某个选项当前选的是哪一项（单选）。"""
        v = self.choices_from_mfa(self.find_task(task_name)).get(option_name)
        return v if isinstance(v, str) else ""

    # ================= 按「名称」保存的选择（管家自己的任务预设 / 每日计划用） =================
    # 选择的格式：{选项名: 选项值}
    #   select / switch：case 名，例如 {"请选择游戏版本": "代号鸢 - 港服"}
    #   checkbox：case 名列表，例如 {"喵喵牌游玩男主": ["沈星回", "祁煜"]}
    #   input：{输入名: 值}，例如 {"账号前3位": {"account": "abc"}}
    # 子选项也平铺在同一个字典里（interface.json 里选项名全局唯一）。

    def _default_choice(self, od: dict):
        typ = od.get("type", "select")
        if typ == "input":
            return {i["name"]: i.get("default", "") for i in od.get("inputs", [])}
        cases = od.get("cases", [])
        if typ == "checkbox":
            dc = od.get("default_case")
            return [c for c in _as_list(dc) if _case_index(od, c) is not None]
        idx = _case_index(od, od.get("default_case"))
        return cases[idx if idx is not None else 0]["name"] if cases else None

    def _choices_from_saved(self, task_def: dict, saved_opts: list | None) -> dict:
        """把 MFA 保存的序号 / 勾选 / 输入值转换成按名称的选择。"""
        out: dict = {}

        def walk(opt_names, saved_list):
            saved = {o.get("name"): o for o in (saved_list or []) if isinstance(o, dict)}
            for name in opt_names:
                od = self.options.get(name)
                if not od or not self._applies(od):
                    continue
                s = saved.get(name) or {}
                typ = od.get("type", "select")
                if typ == "input":
                    vals = self._default_choice(od)
                    if isinstance(s.get("data"), dict):
                        vals.update({k: v for k, v in s["data"].items() if k in vals or not vals})
                    out[name] = vals
                    continue
                cases = od.get("cases", [])
                if not cases:
                    continue
                if typ == "checkbox":
                    sel = s.get("selected_cases") if isinstance(s.get("selected_cases"), list) else None
                    picked = [c for c in (sel if sel is not None else self._default_choice(od))
                              if _case_index(od, c) is not None]
                    out[name] = picked
                    subs = []
                    for c in picked:
                        subs += cases[_case_index(od, c)].get("option", []) or []
                    walk(subs, s.get("sub_options"))
                    continue
                idx = s.get("index") if isinstance(s.get("index"), int) else _case_index(od, od.get("default_case"))
                idx = idx if idx is not None and 0 <= idx < len(cases) else 0
                out[name] = cases[idx]["name"]
                walk(cases[idx].get("option", []) or [], s.get("sub_options"))

        walk(self.task_options(task_def), saved_opts)
        return out

    def choices_from_mfa(self, task_def: dict) -> dict:
        """MFA 里保存的选项 → 按名称的选择，作为第一次导入的初值。"""
        saved_item = self.saved_items.get(task_def["name"], {})
        return self._choices_from_saved(task_def, saved_item.get("option"))

    def build_override_named(self, task_def: dict, chosen: dict | None) -> dict:
        """按名称选择拼 pipeline_override；没选的选项退回 MFA 保存值，再退回默认值。"""
        merged = self.choices_from_mfa(task_def)
        merged.update(chosen or {})
        override = copy.deepcopy(task_def.get("pipeline_override", {}) or {})

        def apply(name, depth=0):
            od = self.options.get(name)
            if not od or depth > 12 or not self._applies(od):
                return
            typ = od.get("type", "select")
            if typ == "input":
                vals = self._default_choice(od)
                if isinstance(merged.get(name), dict):
                    vals.update(merged[name])
                types = {i["name"]: i.get("pipeline_type", "string") for i in od.get("inputs", [])}
                deep_merge(override, _substitute(od.get("pipeline_override", {}) or {}, vals, types))
                return
            cases = od.get("cases", [])
            if not cases:
                return
            if typ == "checkbox":
                want = merged.get(name)
                want = self._default_choice(od) if want is None else _as_list(want)
                for c in cases:  # 按 interface 里的顺序合并已勾选的项
                    if c["name"] in want:
                        deep_merge(override, c.get("pipeline_override", {}) or {})
                        for sub in c.get("option", []) or []:
                            apply(sub, depth + 1)
                deep_merge(override, od.get("pipeline_override", {}) or {})
                return
            idx = _case_index(od, merged.get(name))
            if idx is None:
                idx = _case_index(od, od.get("default_case")) or 0
            deep_merge(override, cases[idx].get("pipeline_override", {}) or {})
            for sub in cases[idx].get("option", []) or []:
                apply(sub, depth + 1)

        for opt in self.task_options(task_def):
            apply(opt)
        return override

    # ---------- 从 MFA 导入任务预设 ----------
    def instance_routines(self) -> dict:
        """把 MFA 里的每个实例/配置转成一套任务预设：{实例名: [任务项…]}（只取勾选的，保留顺序和重复项）。"""
        out = {}
        names = set(self.task_names())
        for inst in self.instances:
            items = []
            for it in inst["items"]:
                if it.get("name") not in names:
                    continue
                checked = it.get("default_check", it.get("check", it.get("is_checked", True)))
                if checked is False:
                    continue
                td = self.find_task(it["name"])
                items.append({"task": td["name"], "choices": self._choices_from_saved(td, it.get("option"))})
            if items:
                out.setdefault(inst["name"], items)
        return out

    def preset_routines(self) -> list[dict]:
        """interface.json 自带的预设（preset）：[{name, tasks: [任务项…], error}]。
        预设写错了（用了工具里没有的任务）：这一个预设标出原因、不能选，不影响别的（10-26 MaaLYSK「特色功能」）。"""
        out = []
        for p in self.presets:
            name = p.get("name") or f"预设{len(out) + 1}"
            items, missing = [], []
            for t in p.get("task", []) or []:
                try:
                    td = self.find_task(t.get("name", ""))
                except KeyError:
                    missing.append(t.get("name", ""))
                    continue
                ch = self._choices_from_saved(td, None)
                for k, v in (t.get("option") or {}).items():
                    ch[k] = v
                items.append({"task": td["name"], "choices": ch})
            if missing:
                out.append({"name": name, "tasks": [], "error": f"这个预设用了工具里没有的任务：{'、'.join(missing)}"})
            elif items:
                out.append({"name": name, "tasks": items, "error": ""})
        return out

    def schema(self) -> dict:
        """给编辑器用：全部任务和选项定义（只含界面需要的字段）。文字按中文翻译；当前控制器 / 资源不适用的任务不给。"""
        tr = self.tr
        opts = {}
        for name, od in self.options.items():
            typ = od.get("type", "select")
            item = {"type": typ, "label": tr(od.get("label", "")), "description": _doc_text(self.dir, tr(od.get("description", "")))}
            if typ == "input":
                item["inputs"] = [{**{k: i.get(k) for k in ("name", "default", "pipeline_type", "verify")},
                                   "label": tr(i.get("label", "")), "description": tr(i.get("description", "")),
                                   "pattern_msg": tr(i.get("pattern_msg", ""))} for i in od.get("inputs", [])]
            else:
                item["cases"] = [{"name": c["name"], "label": tr(c.get("label", "")), "description": tr(c.get("description", "")),
                                  "sub": c.get("option", []) or []} for c in od.get("cases", [])]
                item["default"] = self._default_choice(od)
            opts[name] = item
        tasks = []
        for t in self.tasks:
            if not self._applies(t):
                continue
            tasks.append({"name": t["name"], "label": tr(t.get("label", "")), "entry": t.get("entry"),
                          "description": _doc_text(self.dir, tr(t.get("description", ""))),
                          "options": self.task_options(t), "mfa_choices": self.choices_from_mfa(t),
                          "default_check": bool(t.get("default_check", False)),
                          "placeholder": t.get("entry") == "stop"})  # entry=stop：分割线/未实现的占位任务
        presets = self.preset_routines()
        warnings = [_TR_ERR[self.dir]] if self.dir in _TR_ERR else []
        return {"tasks": tasks, "options": opts, "presets": presets, "warnings": warnings,
                "controllers": [{"name": c.get("name", ""), "label": tr(c.get("label") or c.get("name", "")),
                                 "type": str(c.get("type", "Adb")).lower()} for c in self.controllers()],
                "controller": self.controller_name()}


def _substitute(obj, values: dict, types: dict):
    if isinstance(obj, dict):
        return {k: _substitute(v, values, types) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute(v, values, types) for v in obj]
    if isinstance(obj, str):
        m = re.fullmatch(r"\{(\w+)\}", obj)
        if m and m.group(1) in values:
            v, t = values[m.group(1)], types.get(m.group(1), "string")
            if t == "int":
                try:
                    return int(v)
                except (TypeError, ValueError) as e:
                    raise ValueError(f"选项「{m.group(1)}」要填整数，现在是：{v!r}") from e
            if t == "bool":
                return str(v).lower() in ("1", "true", "yes")
            return v
        return re.sub(r"\{(\w+)\}", lambda mm: str(values.get(mm.group(1), mm.group(0))), obj)
    return obj
