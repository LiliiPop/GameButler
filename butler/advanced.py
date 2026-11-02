"""游戏页「高级」（评测 #6）：一个工具挂上后「跑得稳」靠的那些设置，原来只能改 data/games/<游戏>.json。

这里列出每一项：中文说明、现在的值、填法；保存时检查格式，不对直接报错（不悄悄改成默认值）。
预设（config/presets/*.json）里写的就是这些字段，给脚本作者的说明见 docs/给脚本作者.md。
"""
from __future__ import annotations

from . import gamesdb as GD
from . import judge as J

# kind：int 整数 · bool 开关 · task 一个任务名 · tasks 任务名列表 · minutes {任务名: 分钟} · counts {任务名: 次数} · judge 成败判定
FIELDS = [
    {"key": "recovery_task", "kind": "task", "types": ["maa"], "label": "启动任务",
     "help": "启动游戏、进到主界面的那个任务。有任务要跑时自动放在最前面；任务卡住时也用它重新进游戏。留空 = 没有。"},
    {"key": "before_startup", "kind": "tasks", "types": ["maa"], "label": "排在启动前的任务",
     "help": "要在登录页做的任务（例如读登录页公告），排在启动任务前面。"},
    {"key": "run_order", "kind": "tasks", "types": ["maa"], "label": "固定先后",
     "help": "这些任务总是按这里的先后跑（不管计划里怎么排）。"},
    {"key": "always_last", "kind": "tasks", "types": ["maa"], "label": "总放最后",
     "help": "例如「日常收尾」「结束后操作」。"},
    {"key": "judge", "kind": "judge", "types": ["maa"], "label": "成败判定",
     "help": "什么算完成、什么算失败。fail = 命中就判失败；success = 命中就判完成（写在某个任务下的默认必须命中）。"
             "match 是识别节点名或提示里的字；result: exhausted = 完成（无可做）；verify = 失败后跑这个节点核对画面。"},
    {"key": "timeouts", "kind": "timeouts", "types": ["maa"], "label": "超时和卡住",
     "help": "default = 每个任务最长几分钟；retries = 超时后重试几次；再写「任务名: 分钟」单独给某个任务。"
             "卡死判断不在这里：日程页「调度设置」里的「卡死处理」默认开着，画面 10 分钟没有变化就重启游戏，这时这里的最长时间不用（只留 90 分钟兜底）；关掉后才按这里的。stall_minutes 已不再使用。"},
    {"key": "task_retries", "kind": "counts", "types": ["maa"], "label": "单个任务的重试次数",
     "help": "{任务名: 次数}，覆盖上面的 retries。"},
    {"key": "retry_on_fail", "kind": "bool", "types": ["maa"], "label": "失败也重试", "default": True,
     "help": "任务报失败（不是卡住）时也按重试次数再跑。关掉 = 只在卡住、超时时重试。"},
    {"key": "restart_on_fail", "kind": "bool", "types": ["maa"], "label": "重试前重启游戏", "default": False,
     "help": "重试前先强关游戏、跑启动任务。"},
    {"key": "notice_resolution", "kind": "choice", "types": ["maa"], "label": "重新获取题图的分辨率", "default": "1920x1080",
     "choices": [["1920x1080", "1920×1080（题图约放大 1.5 倍）"], ["2560x1440", "2560×1440（约放大 2 倍，更吃性能）"]],
     "help": "活动页轮播上右键「重新获取题图」时，模拟器临时改成这个分辨率重读游戏内公告，读完改回原来的。"},
    {"key": "back_presses", "kind": "int", "types": ["maa"], "label": "恢复时按几次返回", "default": 1,
     "help": "任务失败或超时、重启游戏前，先按几次安卓返回键关掉挡住画面的弹窗。", "min": 1, "max": 10},
    {"key": "timeout", "kind": "int", "types": ["bettergi", "m7a", "command", "maa_ark"], "label": "整次最长几分钟",
     "help": "超过就停下，没跑完的记「未运行」。", "min": 5, "max": 1440},
]


def fields_for(g: dict) -> list[dict]:
    return [f for f in FIELDS if g.get("type") in f["types"]]


def view(cfg: dict, gid: str, task_names: list[str]) -> dict:
    g = GD.record(cfg, gid)
    return {"fields": [{**{k: f[k] for k in ("key", "kind", "label", "help") }, "value": g.get(f["key"]),
                        **{k: f[k] for k in ("default", "min", "max", "choices") if k in f}}
                       for f in fields_for(g)], "tasks": task_names}


def _tasks(v, names: set, label: str) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ValueError(f"「{label}」要填任务名列表")
    bad = [x for x in v if x not in names]
    if bad:
        raise ValueError(f"「{label}」里这些任务工具里没有：{'、'.join(bad)}")
    return v


def _num_map(v, names: set, label: str, lo: float, hi: float, extra: set = frozenset()) -> dict:
    if not isinstance(v, dict):
        raise ValueError(f"「{label}」要写成 {{任务名: 数字}}")
    out = {}
    for k, x in v.items():
        if k not in names and k not in extra:
            raise ValueError(f"「{label}」里的「{k}」工具里没有这个任务")
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not lo <= x <= hi:
            raise ValueError(f"「{label}」里「{k}」要填 {lo:g}–{hi:g} 的数字：{x!r}")
        out[k] = x
    return out


def update(cfg: dict, gid: str, patch: dict, task_names: list[str]) -> dict:
    """patch = {字段: 新值}；值为 null = 删掉这一项（用默认）。"""
    g = GD.record(cfg, gid)
    allowed = {f["key"]: f for f in fields_for(g)}
    names = set(task_names)
    for k, v in patch.items():
        f = allowed.get(k)
        if not f:
            raise ValueError(f"这个游戏没有「{k}」这项设置")
        if v is None:
            g.pop(k, None)
            continue
        kind, label = f["kind"], f["label"]
        if kind == "int":
            if isinstance(v, bool) or not isinstance(v, int) or not f["min"] <= v <= f["max"]:
                raise ValueError(f"「{label}」要填 {f['min']}–{f['max']} 的整数：{v!r}")
        elif kind == "choice":
            if v not in [c[0] for c in f["choices"]]:
                raise ValueError(f"「{label}」只能选：" + "、".join(c[1] for c in f["choices"]))
        elif kind == "bool":
            if not isinstance(v, bool):
                raise ValueError(f"「{label}」只能开或关")
        elif kind == "task":
            if v != "" and v not in names:
                raise ValueError(f"「{label}」：工具里没有「{v}」这个任务")
        elif kind == "tasks":
            v = _tasks(v, names, label)
        elif kind == "counts":
            v = _num_map(v, names, label, 0, 10)
        elif kind == "timeouts":
            v = _num_map(v, names, label, 0.5, 600, {"default", "stall_minutes", "retries"})
        elif kind == "judge":
            v = J.validate(v)
            for scope in ("fail", "success"):
                bad = [t for t in (v.get(scope) or {}) if t != "*" and t not in names]
                if bad:
                    raise ValueError(f"「{label}」里这些任务工具里没有：{'、'.join(bad)}")
        g[k] = v
    GD.save(cfg, gid, g)
    return view(cfg, gid, task_names)
