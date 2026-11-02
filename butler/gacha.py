"""抽卡记录（总纲 10-23）：导入 JSON → 保底进度、五星列表、平均出金。

data/gacha/<游戏>.json：{"uid": "...", "records": [{"id", "pool", "time", "name", "rank", "type"}]}（按时间从早到晚）

能导入的格式：
- UIGF v4（原神 hk4e / 星铁 hkrpg / 绝区零 nap 都在一个文件里，按游戏取对应那段）
- UIGF v3 / v2（只有原神）、SRGF v1（只有星铁）
- 管家自己的格式（其他游戏用，模板见 TEMPLATE）：
  {"game": "lysk", "list": [{"time": "2026-10-01 12:00:00", "name": "xxx", "rank": 5, "pool": "限定"}]}
  list 要按从早到晚排（同一时间的十连按抽出来的顺序）
重复导入自动去重（有 id 用 id；没有 id 用 时间 + 名字 + 卡池 + 同一时间内的序号）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import jsonio

# 卡池：名字、保底抽数、uigf_gacha_type / gacha_type 归到哪个池
POOLS = {
    "genshin": {"301": ("角色活动", 90), "400": ("角色活动", 90), "302": ("武器活动", 80), "200": ("常驻", 90),
                "500": ("集录", 90), "100": ("新手", 20)},
    "starrail": {"11": ("角色活动", 90), "12": ("光锥活动", 80), "1": ("常驻", 90), "2": ("新手", 50),
                 "21": ("角色联动", 90), "22": ("光锥联动", 80)},
}
UIGF_KEY = {"genshin": "hk4e", "starrail": "hkrpg"}
TEMPLATE = {"game": "<游戏 id>", "list": [{"time": "2026-10-01 12:00:00", "name": "抽到的名字", "rank": 5, "pool": "限定"},
                                        {"time": "2026-10-01 12:00:00", "name": "抽到的名字", "rank": 3, "pool": "限定"}]}


def _path(cfg, gid) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "gacha" / f"{gid}.json"


def load(cfg, gid) -> dict:
    return jsonio.read(_path(cfg, gid), {"uid": "", "records": []})


def _save(cfg, gid, d):
    jsonio.write(_path(cfg, gid), d)


def forget(cfg, gid):
    jsonio.remove(_path(cfg, gid))


def parse(gid: str, doc) -> tuple[str, list[dict]]:
    """各种格式 → (uid, [记录])。认不出抛 ValueError。"""
    if not isinstance(doc, dict):
        raise ValueError("文件内容不是 JSON 对象")
    pools = POOLS.get(gid, {})

    def norm(lst, typ_field):
        out = []
        for x in lst or []:
            gt = str(x.get(typ_field) or x.get("gacha_type") or "")
            pool = pools.get(gt, (x.get("pool") or gt or "未知", 0))[0]
            rank = int(x.get("rank_type") or x.get("rank") or 0)
            out.append({"id": str(x.get("id") or ""), "pool": pool, "time": str(x.get("time", "")),
                        "name": str(x.get("name", "")), "rank": rank, "type": str(x.get("item_type", ""))})
        return out
    info = doc.get("info") or {}
    key = UIGF_KEY.get(gid)
    if key and isinstance(doc.get(key), list):  # UIGF v4
        if not doc[key]:
            raise ValueError("文件里没有这个游戏的记录")
        part = doc[key][0]
        return str(part.get("uid", "")), norm(part.get("list"), "uigf_gacha_type" if gid == "genshin" else "gacha_type")
    if isinstance(doc.get("list"), list) and (info.get("uigf_version") or info.get("srgf_version")):
        if info.get("srgf_version") and gid != "starrail":
            raise ValueError("这是星铁的抽卡记录（SRGF）")
        if info.get("uigf_version") and gid not in ("genshin",):
            raise ValueError("这是原神的抽卡记录（UIGF v3）")
        return str(info.get("uid", "")), norm(doc["list"], "uigf_gacha_type" if gid == "genshin" else "gacha_type")
    if isinstance(doc.get("list"), list):  # 管家自己的格式
        if doc.get("game") and doc["game"] != gid:
            raise ValueError(f"这个文件是「{doc['game']}」的记录")
        return str(doc.get("uid", "")), norm(doc["list"], "gacha_type")
    raise ValueError("认不出格式：支持 UIGF v4 / v3、SRGF，或管家的格式（看模板）")


def _order(r):
    return (r["time"], int(r["id"]) if r["id"].isdigit() else 0, r.get("seq", 0))


def _rid(r, n):
    return r["id"] or hashlib.sha1(f"{r['time']}|{r['name']}|{r['pool']}|{n}".encode()).hexdigest()[:16]


def import_doc(cfg, gid: str, doc, dry: bool = False) -> dict:
    uid, recs = parse(gid, doc)
    if not recs:
        raise ValueError("文件里没有抽卡记录")
    d = load(cfg, gid)
    if d.get("uid") and uid and d["uid"] != uid:
        raise ValueError(f"这个文件是 UID {uid} 的，已经导入的是 UID {d['uid']}（一个游戏先只记一个账号）")
    seen = {}
    for r in recs:  # 同一时间同名多抽（十连）：用序号区分
        k = (r["time"], r["name"], r["pool"])
        seen[k] = seen.get(k, 0) + 1
        r["id"] = _rid(r, seen[k])
    have = {r["id"] for r in d["records"]}
    new = [r for r in recs if r["id"] not in have]
    base = max((r.get("seq", 0) for r in d["records"]), default=0)
    for i, r in enumerate(new):  # 同一时间的（十连）：有数字 id 按 id，没有按文件里的顺序（文件要从早到晚）
        r["seq"] = base + i + 1
    if not dry and new:
        d["records"] = sorted(d["records"] + new, key=_order)
        d["uid"] = d.get("uid") or uid
        _save(cfg, gid, d)
    return {"ok": True, "new": len(new), "total": len(d["records"]) + (len(new) if dry else 0), "uid": uid or d.get("uid", ""),
            "dry": dry, "file_records": len(recs)}


def stats(cfg, gid) -> dict:
    """每个卡池：总抽数、距上次最高星多少抽（= 当前保底进度）、保底是多少、最高星列表、平均出金。"""
    d = load(cfg, gid)
    by = {}
    for r in d["records"]:
        by.setdefault(r["pool"], []).append(r)
    hard = {v[0]: v[1] for v in POOLS.get(gid, {}).values()}
    out = []
    for pool, rs in by.items():
        top = max((r["rank"] for r in rs), default=0)
        stars, since, gaps = [], 0, []
        for r in rs:
            since += 1
            if r["rank"] == top and top:
                stars.append({"name": r["name"], "time": r["time"], "pulls": since})
                gaps.append(since)
                since = 0
        out.append({"pool": pool, "total": len(rs), "since": since, "top_rank": top, "hard": hard.get(pool),
                    "stars": stars[-20:][::-1], "avg": round(sum(gaps) / len(gaps), 1) if gaps else None})
    order = [v[0] for v in POOLS.get(gid, {}).values()]
    out.sort(key=lambda x: order.index(x["pool"]) if x["pool"] in order else 99)
    return {"uid": d.get("uid", ""), "total": len(d["records"]), "pools": out,
            "last": d["records"][-1]["time"] if d["records"] else ""}


def brief(cfg, gid) -> dict | None:
    """主页卡片：主卡池（第一个限定池）距保底多少抽。"""
    s = stats(cfg, gid)
    if not s["pools"]:
        return None
    p = s["pools"][0]
    return {"pool": p["pool"], "since": p["since"], "hard": p["hard"]}
