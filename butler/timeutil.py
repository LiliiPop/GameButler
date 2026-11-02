"""时间工具：所有判定一律按北京时间，不依赖电脑本地时区设置。

管家里只有两种「哪一天」：
- 游戏日（game_day）：某个游戏从它的每日刷新时刻起算的一天。任务做没做完、计划、运行记录都按它。
- 日程日（sched_day）：北京时间 04:00 换日。日程队列、报告、主页的「今天」都按它。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BJ = ZoneInfo("Asia/Shanghai")
DAY_SWITCH = time(4, 0)


def now_bj() -> datetime:
    return datetime.now(BJ)


def parse_hm(s: str) -> time:
    h, m = str(s).strip().split(":")
    if not (0 <= int(h) <= 24 and 0 <= int(m) <= 59):
        raise ValueError(f"时间格式不对：{s}")
    return time(23, 59, 59) if int(h) == 24 else time(int(h), int(m))


def to_bj(naive_local: datetime, machine_tz: ZoneInfo) -> datetime:
    """脚本日志里的时间是电脑本地时间（无时区），换算成北京时间。"""
    return naive_local.replace(tzinfo=machine_tz).astimezone(BJ)


def day_of(ts_bj: datetime, refresh: time) -> date:
    shifted = ts_bj - timedelta(hours=refresh.hour, minutes=refresh.minute)
    return shifted.date()


def game_day(g: dict, ts_bj: datetime | None = None) -> date:
    """这个游戏现在（或 ts_bj 时）是哪个游戏日。刷新时间是游戏记录的必填项。"""
    return day_of(ts_bj or now_bj(), parse_hm(g["refresh"]))


def day_start(g: dict, day: date) -> datetime:
    """游戏日 day 开始的时刻（北京时间）。"""
    return datetime.combine(day, parse_hm(g["refresh"]), tzinfo=BJ)


def on_game_day(g: dict, day: date, hm: str) -> datetime:
    """游戏日 day 里的某个钟点：早于刷新时刻的算第二天凌晨。"""
    t, refresh = parse_hm(hm), parse_hm(g["refresh"])
    return datetime.combine(day if t >= refresh else day + timedelta(days=1), t, tzinfo=BJ)


def sched_day(ts_bj: datetime | None = None) -> date:
    return day_of(ts_bj or now_bj(), DAY_SWITCH)


# ---------------------------------------------------------------- 时段
def parse_windows(spec) -> list[tuple[time, time]]:
    """"12:00-15:00,17:30-21:00" 或 ["12:00-15:00", ...] → [(开始, 结束)]。结束早于开始表示跨午夜。"""
    if not spec:
        return []
    parts = spec if isinstance(spec, (list, tuple)) else str(spec).replace("，", ",").split(",")
    out = []
    for p in parts:
        p = str(p).strip()
        if not p:
            continue
        a, b = p.replace("～", "-").replace("~", "-").split("-")
        out.append((parse_hm(a), parse_hm(b)))
    return out


def window_text(spec) -> str:
    return "北京时间 " + "、".join(f"{a:%H:%M}–{b:%H:%M}" for a, b in parse_windows(spec))


def window_instances(g: dict, day: date, spec) -> list[tuple[datetime, datetime]]:
    """时段在游戏日 day 里具体是哪几段（北京时间，按开始排序）。"""
    out = []
    for a, b in parse_windows(spec):
        st = on_game_day(g, day, a.strftime("%H:%M"))
        en = datetime.combine(st.date(), b, tzinfo=BJ)
        if en <= st:
            en += timedelta(days=1)
        out.append((st, en))
    return sorted(out)
