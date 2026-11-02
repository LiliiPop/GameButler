"""管家设置：全部存在 data/settings.json 一个文件里，界面改的就是这一处。

  scheduler   自动调度：开关、闲时判定、失败补跑、提醒
  push        微信推送：服务商、每日汇总时间、出问题时推送（SendKey 单独存在 data/secrets.json）
  appearance  外观配色
  news        活动日历：多久读一次、不读哪些来源
  evidence    留证截图：哪些任务截图、保留几天
  emulator    MuMu 模拟器装在哪

每一项的默认值写在 DEFAULTS 里；文件里只存改过的。
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from . import jsonio
from .timeutil import parse_hm

PALETTES = ("雾光", "晴空", "暮色", "高对比")

DEFAULTS = {
    "scheduler": {
        "enabled": False,
        "idle_groups": [],             # 什么算闲时（butler/idle.py）：几组条件，组内同时满足、组间满足任一；没有默认
        "wake_from_sleep": True,       # 电脑睡着时，到下一个定时前把它叫醒（butler/wake.py）
        "fail_retries": 0,             # 失败的任务当天自动补跑几次（0 = 每天跑一轮就停）
        "retry_gap_minutes": 60,       # 补跑至少间隔
        "postpone_minutes": 30,        # 提醒里选「推迟」推迟多久
        "prompt_timeout_seconds": 300,  # 提醒多久没人回答
        "start_delay_minutes": 10,     # 新挂载的游戏：每天刷新后多久开始跑（写进它的日程批次）
        "stuck_restart": True,         # 卡死处理（MAA 类游戏）：画面 10 分钟没有变化算卡住，重启游戏再跑；开着时不用每项的固定最长时间
        "stuck_asked": False,          # 开自动调度时问过要不要开卡死处理
        "stuck_action": "restart",     # 卡住以后：restart = 重启游戏再试这一项；skip = 不再试，直接跑下一项（11-02 改成全局）
        "task_retries": 1,             # 一项失败或卡住后，当场再试几次（11-02 改成全局，原来每个游戏「高级」里各设各的）
        "task_max_minutes": 20,        # 卡死处理关着时，每一项最长跑多久
        "halt_close": False,           # 中止队列时顺便关掉模拟器和电脑游戏 / 工具（11-02，取代「让出电脑」按钮）
    },
    "push": {"provider": "", "daily_at": "23:30", "on_problem": True},
    "appearance": {"palette": "雾光",     # 游戏配色（游戏色块、色条）
                   "theme": "minimal",    # 界面主题：static/themes/<id>.css，或自建的「user:<id>」（butler/themes.py）
                   "ui_notes": True,      # 左下角「批注」按钮（调优期间默认显示，定稿后连同批注功能一起删）
                   "home_order": "daily_first",  # 总览上先放哪块：daily_first = 日常一览在上；news_first = 当前活动在上
                   "game_colors": {},     # 自己定的游戏颜色 {游戏 id: "#RRGGBB"}，盖过配色方案里的颜色
                   "aside_order": []},    # 游戏页右栏卡片的顺序（拖动标题栏调整）
    "news": {"interval_hours": 6, "disabled": [],
             "ingame_fallback": False},  # 站外来源都读不到时，允许跑日常时进游戏读公告（11-02，默认不允许）
    "evidence": {"keep_days": 7, "tasks": {}},
    "emulator": {"mumu_dir": "",
                 "close": "each_run"},         # 跑完关模拟器：each_run = 每次跑完关；keep_open = 一直开着
}


def _path(cfg: dict) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "settings.json"


def get(cfg: dict, section: str) -> dict:
    stored = jsonio.read(_path(cfg), {}).get(section) or {}
    out = copy.deepcopy(DEFAULTS[section])
    out.update({k: v for k, v in stored.items() if k in out})
    return out


def _clean(section: str, patch: dict, cfg: dict | None = None) -> dict:
    """检查界面传来的值；不合法直接报错（ValueError 的文字给界面显示）。"""
    out = {}
    for k, v in patch.items():
        if k not in DEFAULTS[section]:
            raise ValueError(f"没有这个设置：{section}.{k}")
        if section == "scheduler":
            if k == "enabled":
                v = bool(v)
            elif k == "idle_groups":
                from .idle import clean_groups
                v = clean_groups(v)
            elif k in ("wake_from_sleep", "stuck_restart", "stuck_asked", "halt_close"):
                v = bool(v)
            elif k == "fail_retries":
                v = _int(v, 0, 3, "失败补跑次数")
            elif k == "retry_gap_minutes":
                v = _int(v, 10, 600, "补跑间隔")
            elif k == "postpone_minutes":
                v = _int(v, 5, 240, "推迟分钟数")
            elif k == "prompt_timeout_seconds":
                v = _int(v, 30, 3600, "提醒等待秒数")
            elif k == "stuck_action":
                if v not in ("restart", "skip"):
                    raise ValueError("卡住以后只能选「重启游戏再试」或「跳到下一项」")
            elif k == "task_retries":
                v = _int(v, 0, 3, "当场再试次数")
            elif k == "task_max_minutes":
                v = _int(v, 5, 180, "每项最长时间")
            elif k == "start_delay_minutes":
                v = _int(v, 0, 240, "刷新后开始分钟数")
        elif section == "push":
            if k == "provider":
                if v not in ("", "pushplus", "serverchan"):
                    raise ValueError("推送服务只能是 pushplus 或 serverchan")
            elif k == "daily_at":
                if v not in ("", None) and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(v)):
                    raise ValueError("每日汇总时间格式是 HH:MM")
                v = v or ""
            elif k == "on_problem":
                v = bool(v)
        elif section == "appearance":
            if k == "palette" and v not in PALETTES:
                raise ValueError("没有这套配色")
            if k == "theme":
                from . import themes
                v = str(v or "")
                if not themes.exists(cfg, v):
                    raise ValueError(f"没有这个主题：{v}")
            if k == "ui_notes":
                v = bool(v)
            if k == "home_order" and v not in ("daily_first", "news_first"):
                raise ValueError("总览顺序只能是「日常一览在上」或「当前活动在上」")
            if k == "game_colors":
                if not isinstance(v, dict):
                    raise ValueError("游戏颜色要写成 {游戏: 颜色}")
                for gid, c in v.items():
                    if not re.fullmatch(r"\w{1,40}", str(gid)) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(c)):
                        raise ValueError(f"游戏颜色格式不对：{gid} = {c!r}（要写成 #RRGGBB）")
                v = {str(g): str(c).upper() for g, c in v.items()}
            if k == "aside_order":
                v = [str(x)[:20] for x in (v or [])][:20]
        elif section == "news":
            if k == "interval_hours":
                v = _int(v, 1, 72, "读取间隔小时数")
            elif k == "ingame_fallback":
                v = bool(v)
            else:
                v = [str(x) for x in v or []]
        elif section == "emulator":
            v = str(v).strip()
            if k == "close" and v not in ("each_run", "keep_open"):
                raise ValueError("跑完关模拟器只能选「每次跑完关」或「一直开着」")
        elif section == "evidence":
            if k == "keep_days":
                v = _int(v, 1, 60, "保留天数")
            else:
                v = {str(g): [str(x) for x in lst] for g, lst in (v or {}).items()}
        out[k] = v
    return out


def _int(v, lo, hi, what) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what}要填整数")
    if not lo <= n <= hi:
        raise ValueError(f"{what}要在 {lo}–{hi} 之间")
    return n


def update(cfg: dict, section: str, patch: dict) -> dict:
    clean = _clean(section, patch, cfg)

    def fn(doc):
        doc.setdefault(section, {}).update(clean)
    jsonio.update(_path(cfg), {}, fn)
    return get(cfg, section)


def start_delay_hm(cfg: dict, refresh: str) -> str:
    """「刷新后马上」的开始时刻：刷新时间 + start_delay_minutes。"""
    t = parse_hm(refresh)
    m = (t.hour * 60 + t.minute + int(get(cfg, "scheduler")["start_delay_minutes"])) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"
