"""什么算闲时：用户自己用两种条件搭，管家不给默认。

  键鼠不动  {"kind": "input_idle", "minutes": 30}        至少多少分钟没碰键盘鼠标
  时段      {"kind": "time", "from": "01:00", "to": "07:00"}  北京时间，可跨零点（界面上按电脑本地时间填写和显示）

存在设置 scheduler.idle_groups：[[条件, …], …]。一组里的条件同时满足才算；有好几组时满足任意一组就算。
一组里每种条件最多一个（所以一组是：只看键鼠 / 只看时段 / 两者叠加）。一组都没有 = 没设，「闲时」定时不能用。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import settings as S
from .timeutil import BJ, parse_hm

KINDS = ("input_idle", "time")


def clean_groups(v) -> list[list[dict]]:
    out = []
    for i, grp in enumerate(v or [], 1):
        if not isinstance(grp, list) or not grp:
            raise ValueError(f"闲时第 {i} 组是空的")
        seen, conds = set(), []
        for c in grp:
            k = (c or {}).get("kind")
            if k not in KINDS:
                raise ValueError(f"闲时第 {i} 组：条件只能是「键鼠不动」或「时段」")
            if k in seen:
                raise ValueError(f"闲时第 {i} 组：同一种条件只能有一个（要「或」就再加一组）")
            seen.add(k)
            if k == "input_idle":
                try:
                    n = int(c.get("minutes"))
                except (TypeError, ValueError):
                    raise ValueError(f"闲时第 {i} 组：键鼠不动的分钟数要填整数")
                if not 1 <= n <= 600:
                    raise ValueError(f"闲时第 {i} 组：键鼠不动的分钟数要在 1–600 之间")
                conds.append({"kind": k, "minutes": n})
            else:
                a, b = str(c.get("from") or ""), str(c.get("to") or "")
                parse_hm(a), parse_hm(b)
                if a == b:
                    raise ValueError(f"闲时第 {i} 组：时段的开始和结束不能一样")
                conds.append({"kind": k, "from": a, "to": b})
        out.append(conds)
    return out


def groups(cfg: dict) -> list[list[dict]]:
    return S.get(cfg, "scheduler")["idle_groups"]


def configured(cfg: dict) -> bool:
    return bool(groups(cfg))


def _in_time(c: dict, now: datetime) -> tuple[bool, datetime]:
    """现在在不在这个时段里；第二个值：不在时下一次开始，在时这次结束（北京时间）。"""
    n = now.astimezone(BJ)
    a, b = parse_hm(c["from"]), parse_hm(c["to"])
    st = n.replace(hour=a.hour, minute=a.minute, second=0, microsecond=0)
    en = n.replace(hour=b.hour, minute=b.minute, second=0, microsecond=0)
    if a < b:
        if st <= n < en:
            return True, en
        return False, st if n < st else st + timedelta(days=1)
    # 跨零点
    if n >= st:
        return True, en + timedelta(days=1)
    if n < en:
        return True, en
    return False, st


def _hm_local(hm: str) -> str:
    t = parse_hm(hm)
    d = datetime.now(BJ).replace(hour=t.hour, minute=t.minute)
    return f"{d.astimezone():%H:%M}"


def cond_text(c: dict) -> str:
    if c["kind"] == "input_idle":
        return f"键鼠不动 ≥ {c['minutes']} 分钟"
    return f"{_hm_local(c['from'])}–{_hm_local(c['to'])}（北京 {c['from']}–{c['to']}）"


def group_text(grp: list[dict]) -> str:
    return " 且 ".join(cond_text(c) for c in grp)


def text(cfg: dict) -> str:
    gs = groups(cfg)
    return "；或 ".join(group_text(g) for g in gs) if gs else "还没设置"


def status(cfg: dict, now: datetime, idle_s: float | None) -> dict:
    """现在是不是闲时、每组差什么、大约还要等几秒。idle_s = 键鼠空闲秒数（None = 读不到，按一直空闲算）。

    返回 {ok, configured, wait_s, why, groups: [{ok, conds: [{ok, text, now}]}]}。"""
    gs = groups(cfg)
    if not gs:
        return {"ok": False, "configured": False, "wait_s": None, "why": "还没设置什么算闲时",
                "groups": [], "text": "还没设置"}
    out, waits, ok_any, whys = [], [], False, []
    for i, grp in enumerate(gs, 1):
        conds, ok_all, need = [], True, 0.0
        miss = []
        for c in grp:
            if c["kind"] == "input_idle":
                have = idle_s if idle_s is not None else float("inf")
                ok = have >= c["minutes"] * 60
                left = 0 if ok else c["minutes"] * 60 - have
                mins = "—" if idle_s is None else f"{int(have // 60)} 分钟"
                conds.append({"ok": ok, "text": cond_text(c), "now": f"现在 {mins}"})
                if not ok:
                    miss.append(f"键鼠还要不动 {int(left // 60) + 1} 分钟")
                    need = max(need, left)
            else:
                ok, edge = _in_time(c, now)
                conds.append({"ok": ok, "text": cond_text(c), "now": f"现在 {now.astimezone():%H:%M}"})
                if not ok:
                    miss.append(f"电脑时间 {edge.astimezone():%H:%M} 开始")
                    need = max(need, (edge - now).total_seconds())
            ok_all = ok_all and ok
        out.append({"ok": ok_all, "conds": conds})
        if ok_all:
            ok_any = True
        else:
            waits.append(need)
            whys.append((f"第 {i} 组：" if len(gs) > 1 else "") + "，".join(miss))
    return {"ok": ok_any, "configured": True, "wait_s": None if ok_any else max(30.0, min(waits) + 5),
            "why": "现在是闲时" if ok_any else "等闲时：" + "；".join(whys), "groups": out, "text": text(cfg)}


def next_time_start(cfg: dict, now: datetime) -> datetime | None:
    """只靠时段就能成立的组（组里没有键鼠条件）下一次开始的时刻：电脑睡着时在这个时刻叫醒它。
    有键鼠条件的组：睡着时没人碰电脑，叫醒后键鼠空闲时间通常已经够了，所以也按它的时段开始算（没有时段的组不算）。"""
    best = None
    for grp in groups(cfg):
        tc = [c for c in grp if c["kind"] == "time"]
        if not tc:
            continue
        ok, edge = _in_time(tc[0], now)
        if ok:
            continue
        best = edge if best is None or edge < best else best
    return best
