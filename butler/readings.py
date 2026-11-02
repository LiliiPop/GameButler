"""读数（总纲 10-23）：「某个游戏的某项资源在某个时间是多少」。第一批是抽卡资源。

data/readings/<游戏>.json：
  {"defs": [{"key": "原石", "per_pull": 160, "standard": false}, …],   # 这个游戏记哪些资源（挂载时按游戏记录写初值）
   "points": [{"t": "2026-10-23 08:40", "key": "原石", "v": 12345, "src": "manual|ocr"}, …]}
- 读数只记每天登进游戏看到的资源（识别 + 手动记一笔），资源变化以后从日志算。
- per_pull：多少个 = 一抽（抽卡券是 1）。没填的资源只显示数量，不算进「折合多少抽」。
- standard = true：常驻池用的（相遇之缘、星轨通票），单独显示，不算进限定池的折合抽数。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from . import jsonio
from .timeutil import BJ

STALE_DAYS = 3


def _path(cfg, gid) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "readings" / f"{gid}.json"


def load(cfg, gid) -> dict:
    return jsonio.read(_path(cfg, gid), {"defs": [], "points": []})


def _save(cfg, gid, d):
    jsonio.write(_path(cfg, gid), d)


def forget(cfg, gid):
    jsonio.remove(_path(cfg, gid))


def _now() -> str:
    return datetime.now(BJ).strftime("%Y-%m-%d %H:%M")


def add_points(cfg, gid, values: dict, src: str = "manual", t: str | None = None) -> dict:
    """记一组读数：{资源: 数量}。同一来源、同一分钟、同一资源的覆盖。"""
    t = t or _now()
    vals = {}
    for k, v in values.items():
        if v in (None, ""):
            continue
        try:
            v = int(float(str(v).replace(",", "").strip()))
        except ValueError:
            raise ValueError(f"「{k}」不是数字：{v}")
        if v < 0:
            raise ValueError(f"「{k}」不能是负数")
        vals[k] = v

    def fn(d):
        known = {x["key"] for x in d["defs"]}
        for k, v in vals.items():
            d["points"] = [p for p in d["points"] if not (p["key"] == k and p["t"] == t and p.get("src") == src)]
            d["points"].append({"t": t, "key": k, "v": v, "src": src})
            if k not in known:
                d["defs"].append({"key": k})
                known.add(k)
        d["points"].sort(key=lambda p: p["t"])
        d["points"] = d["points"][-5000:]
    d = jsonio.update(_path(cfg, gid), {"defs": [], "points": []}, fn)
    return summary(cfg, gid, d)


def set_defs(cfg, gid, defs: list[dict]) -> dict:
    out = []
    for x in defs:
        k = str(x.get("key", "")).strip()
        if not k:
            continue
        item = {"key": k}
        try:
            if x.get("per_pull") not in (None, "", 0, "0"):
                item["per_pull"] = float(x["per_pull"])
        except ValueError:
            raise ValueError(f"「{k}」的单抽数量不是数字")
        if x.get("standard"):
            item["standard"] = True
        out.append(item)
    d = jsonio.update(_path(cfg, gid), {"defs": [], "points": []}, lambda d: d.update(defs=out))
    return summary(cfg, gid, d)


def latest(d: dict) -> dict:
    """每项资源最新的读数：{key: point}。"""
    out = {}
    for p in d["points"]:
        if p["key"] not in out or p["t"] >= out[p["key"]]["t"]:
            out[p["key"]] = p
    return out


def pulls_at(defs, values: dict, standard: bool = False) -> float | None:
    tot, any_ = 0.0, False
    for x in defs:
        if not x.get("per_pull") or bool(x.get("standard")) != standard or x["key"] not in values:
            continue
        tot += values[x["key"]] / float(x["per_pull"])
        any_ = True
    return tot if any_ else None


def series(d: dict, days: int = 90) -> list[dict]:
    """增长曲线：每天最后一次的读数（各资源取当时最新值）→ [{day, pulls, values}]。"""
    cut = (datetime.now(BJ) - timedelta(days=days)).strftime("%Y-%m-%d")
    cur, by_day = {}, {}
    for p in sorted(d["points"], key=lambda p: p["t"]):
        cur[p["key"]] = p["v"]
        if p["t"][:10] >= cut:
            by_day[p["t"][:10]] = dict(cur)
    return [{"day": k, "values": v, "pulls": pulls_at(d["defs"], v)} for k, v in sorted(by_day.items())]


def summary(cfg, gid, d: dict | None = None) -> dict:
    d = d or load(cfg, gid)
    last = latest(d)
    vals = {k: p["v"] for k, p in last.items()}
    at = max((p["t"] for p in last.values()), default="")
    stale = bool(at) and datetime.now(BJ) - datetime.strptime(at, "%Y-%m-%d %H:%M").replace(tzinfo=BJ) > timedelta(days=STALE_DAYS)
    pulls = pulls_at(d["defs"], vals)
    std = pulls_at(d["defs"], vals, standard=True)
    return {"defs": d["defs"], "values": vals, "at": at, "stale": stale,
            "src": sorted({p.get("src", "") for p in last.values()}),
            "pulls": None if pulls is None else round(pulls, 1), "standard_pulls": None if std is None else round(std, 1),
            "series": series(d)}


def brief(cfg, gid) -> dict | None:
    """主页卡片用：{label, pulls, at, stale}；没有读数返回 None。"""
    d = load(cfg, gid)
    if not d["points"]:
        return None
    s = summary(cfg, gid, d)
    if not s["values"]:
        return None
    if s["pulls"] is not None:
        label = f"折合 {int(s['pulls'])} 抽"
    else:
        k, v = next(iter(s["values"].items()))
        label = f"{k} {v:,}"
    return {"label": label, "pulls": s["pulls"], "at": s["at"], "stale": s["stale"]}


# ---------------------------------------------------------------- 资源一览（11-02）
def growth(series_: list[dict], days: int = 14) -> tuple[float | None, int]:
    """最近 days 天平均每天攒多少抽：只加「涨了」的天（花掉的不算进来），除以这段的天数。返回 (每天抽数, 用了几天的数据)。"""
    pts = [x for x in series_ if x.get("pulls") is not None][-(days + 1):]
    if len(pts) < 2:
        return None, 0
    d0 = datetime.strptime(pts[0]["day"], "%Y-%m-%d")
    span = (datetime.strptime(pts[-1]["day"], "%Y-%m-%d") - d0).days
    if span < 2:
        return None, span
    up = sum(max(0.0, b["pulls"] - a["pulls"]) for a, b in zip(pts, pts[1:]))
    return up / span, span


def next_pool(cfg, gid) -> dict | None:
    """这个游戏最近一个要结束的 UP 卡池（活动日历里「限定卡池 / 复刻卡池」，还没结束的里面结束最早的）。"""
    try:
        from . import news
        items = news.load(cfg)["items"]
    except Exception:
        return None
    now = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
    pools = [x for x in items if x.get("game") == gid and x.get("cat") in ("pool", "rerun") and x.get("end", "") > now
             and not x.get("forecast")]
    if not pools:
        return None
    p = min(pools, key=lambda x: x["end"])
    return {"title": p["title"], "start": p.get("start", ""), "end": p["end"], "started": p.get("start", "") <= now,
            "chars": p.get("chars") or []}


def overview(cfg) -> list[dict]:
    """总览「资源一览」：每个有读数的游戏的存量、曲线、到下一个 UP 卡池结束时大约攒到多少（仅供参考）。"""
    out = []
    for gid, g in cfg["games"].items():
        d = load(cfg, gid)
        if not d["points"]:
            continue
        s = summary(cfg, gid, d)
        if not s["values"]:
            continue
        rate, span = growth(s["series"])
        pool = next_pool(cfg, gid)
        est = None
        if pool and rate is not None and s["pulls"] is not None:
            left = (datetime.strptime(pool["end"], "%Y-%m-%d %H:%M").replace(tzinfo=BJ) - datetime.now(BJ)).total_seconds() / 86400
            pool["days_left"] = round(max(0.0, left), 1)
            est = round(s["pulls"] + rate * max(0.0, left), 1)
        elif pool:
            pool["days_left"] = round(max(0.0, (datetime.strptime(pool["end"], "%Y-%m-%d %H:%M").replace(tzinfo=BJ)
                                                - datetime.now(BJ)).total_seconds() / 86400), 1)
        out.append({"id": gid, "name": g["name"], **{k: s[k] for k in ("defs", "values", "at", "stale", "pulls", "standard_pulls")},
                    "series": [{"day": x["day"], "pulls": x["pulls"], "values": x["values"]} for x in s["series"]],
                    "rate": None if rate is None else round(rate, 2), "rate_days": span, "pool": pool, "estimate": est})
    return out
