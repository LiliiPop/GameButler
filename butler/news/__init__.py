"""游戏资讯 / 活动日历：读各游戏的官方公告，整理成「活动 + 起止时间 + 题图 + 链接」。

只读官方公开的内容，不登录、不走云端 API。由管家后台定时在后台进程里跑（gb.py news fetch），
改这个文件不用重启管家。

数据：
  data/news/items.json     全部活动 / 公告（id → item），结束超过 45 天的自动清掉
  data/news/sources.json   每个来源最近一次读取的结果（成功与否、条数、错误），界面和排查用
  data/news/raw/<来源>.txt  每个来源最近一次的原始返回（截前 300KB），排查用
  data/news/img/<hash>.*   题图缓存

item 字段：
  id, game, source, kind（活动 / 公告 / 外观）, title, start, end（北京时间 "YYYY-MM-DD HH:MM"，可空）,
  img（缓存文件名，可空）, url（原文网址，可空）, detail（有正文可在管家里看时为 True）, seen（第一次读到的北京时间）
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from ..timeutil import BJ
from .common import KEEP_DAYS, Misses, _cache_img, pick_banner, _fmt, _norm, _now, _parse_dt, after_note
from .sources import DEFAULT_SOURCES, READERS


def sources(cfg: dict) -> list[dict]:
    """挂着的游戏的来源，去掉设置里关掉的（设置 → 活动日历）。"""
    from .. import settings as S
    off = set(S.get(cfg, "news")["disabled"])
    return [s for s in DEFAULT_SOURCES if s["id"] not in off and s["game"] in cfg["games"]]


VERSION_DAYS = {"genshin": 42, "starrail": 42}


def version_forecast(items: list[dict]) -> list[dict]:
    """按版本周期推算下一个版本（原神、星铁约 42 天一个版本）：找最新的「x.y版本」公告的开始日期，往后加周期。"""
    out = []
    for gid, days in VERSION_DAYS.items():
        best = None
        for it in items:
            if it.get("game") != gid or not it.get("start"):
                continue
            m = re.search(r"(\d+)\.(\d+)\s*版本", it.get("title", ""))
            if not m:
                continue
            v = (int(m.group(1)), int(m.group(2)))
            st = _parse_dt(it["start"])
            if st and (best is None or v > best[0] or (v == best[0] and st < best[1])):
                best = (v, st)
        if not best:
            continue
        (a, b), st = best
        nxt = st.replace(hour=0, minute=0) + timedelta(days=days)
        nv = f"{a}.{b + 1}"
        out.append({"id": f"rule:{gid}:ver:{nv}", "game": gid, "source": "rules", "kind": "预告", "title": f"{nv} 版本（推测）",
                    "start": _fmt(nxt), "end": _fmt(nxt + timedelta(days=1)), "start_note": "推测", "forecast": True,
                    "banner_url": "", "url": "", "img": "", "subtitle": f"按 {a}.{b} 版本 {st:%m-%d} 开始、约 {days} 天一个版本推算，以官方公告为准",
                    "source_title": "按版本周期推算（不是公告）", "text": "", "fixed_cat": "version", "detail": False, "seen": _fmt(nxt)})
    return out


# ---------------------------------------------------------------- 存储
SOURCE_MAX_S = 150  # 一个来源最多读多久


def offsite_down(cfg: dict, gid: str) -> tuple[bool, list[str]]:
    """这个游戏的站外来源（官网、B 站、wiki、TapTap…）上一次是不是全都没读到（11-02）。
    返回 (全挂了, 站外来源 id)。没有站外来源的游戏算「全挂了」；还没读过的不算（不知道）。"""
    off = [s["id"] for s in sources(cfg) if s["game"] == gid and s["type"] != "ingame"]
    if not off:
        return True, []
    st = {s["id"]: s for s in _load(_dir(cfg) / "sources.json", [])}
    seen = [st[i] for i in off if i in st]
    return bool(seen) and len(seen) == len(off) and not any(s.get("ok") for s in seen), off


def _dir(cfg: dict) -> Path:
    d = Path(cfg["machine"]["data_dir"]) / "news"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(p: Path, default):
    from .. import jsonio
    return jsonio.read(p, default)


def _save(p: Path, obj):
    from .. import jsonio
    jsonio.write(p, obj)


def forget(cfg: dict, gid: str):
    """彻底删除：这个游戏的活动条目（连正文和题图）、游戏内公告的读取结果、活动页里按游戏的设置。"""
    from .. import jsonio
    from .. import newscat as NC
    d = Path(cfg["machine"]["data_dir"]) / "news"
    items = _load(d / "items.json", {})
    gone = [it for it in items.values() if it["game"] == gid]
    if gone:
        keep = {k: v for k, v in items.items() if v["game"] != gid}
        _save(d / "items.json", keep)
        used = {it.get("img") for it in keep.values()} | {n for it in keep.values() for n in (it.get("imgs") or [])}
        for it in gone:
            jsonio.remove(d / "content" / f"{hashlib.sha1(it['id'].encode()).hexdigest()[:16]}.html")
            if it.get("img") and it["img"] not in used:
                jsonio.remove(d / "img" / it["img"])
    jsonio.remove(d / "ingame" / f"{gid}.json")
    jsonio.remove(d / "ingame" / gid)
    def fn(p):
        for k in ("hidden_cats", "track", "extra_chars"):
            (p.get(k) or {}).pop(gid, None)
        if gid in p.get("games_off", []):
            p["games_off"].remove(gid)
    NC.update_prefs(cfg["machine"]["data_dir"], fn)



def _shared(a: str, b: str, n: int) -> bool:
    """两个名字有没有一段至少 n 个字相同。"""
    return any(a[i:i + n] in b for i in range(len(a) - n + 1)) if len(a) >= n and len(b) >= n else False


def _lock(path: Path, stale_s: int) -> bool:
    """建一个锁文件；已经有、而且不旧 → False。超过 stale_s 秒的当作上次没收尾，作废。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in (1, 2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime < stale_s:
                    return False
            except OSError:
                pass
            path.unlink(missing_ok=True)
    return False


def fetch(cfg: dict, only: list[str] | None = None) -> dict:
    """读一遍各来源（11-02：按来源加锁，不同来源可以同时读；同一个来源正在被另一次读取读时，这次跳过它）。
    读到的结果并进活动数据时再排一次队（write.lock），并且那时重新读一遍文件，不会覆盖另一次读取刚写进去的。"""
    return _fetch(cfg, only)


def _fetch(cfg: dict, only: list[str] | None = None) -> dict:
    d = _dir(cfg)
    current = {s["id"] for s in sources(cfg)}
    now = _now()
    # 11-02：各来源同时读（以前一个一个读，TapTap、米游社慢的时候一次要好几分钟），每个最多 SOURCE_MAX_S 秒，
    # 超时的记成没读到、不等它；读到的结果再按原来的顺序一个个并进去
    want = [s for s in sources(cfg) if not only or s["id"] in only or s["game"] in only]
    locks = d / "locks"
    todo = []
    for s in want:
        if _lock(locks / f"{s['id']}.lock", SOURCE_MAX_S + 120):
            todo.append(s)
        else:
            print(f"· {s['id']} 正在被另一次读取读，这次跳过", flush=True)
    if not todo:
        return {"items": len(_load(d / "items.json", {})), "skipped": True}
    try:
        return _fetch_locked(cfg, d, todo, current, now)
    finally:
        for s in todo:
            (locks / f"{s['id']}.lock").unlink(missing_ok=True)


def _fetch_locked(cfg: dict, d: Path, todo: list[dict], current: set, now) -> dict:
    want_img: list = []
    misses: dict[str, Misses] = {}
    results: dict = {}
    for s in todo:
        misses[s["id"]] = Misses()

    def work(s):
        t = time.time()
        print(f"· 读取 {s['id']} …", flush=True)
        try:
            results[s["id"]] = ("ok", READERS[s["type"]](s, d, misses[s["id"]]), time.time() - t)
        except Exception as e:
            results[s["id"]] = ("err", e, time.time() - t)
        (d / "locks" / f"{s['id']}.lock").unlink(missing_ok=True)  # 读完就放开：别的读取可以接着读这个来源（并进数据时会排队）
        print(f"  · {s['id']} 读完，{time.time() - t:.0f} 秒", flush=True)  # 界面上「正在读取」按这一行判断读完了
    threads = []
    for s in todo:
        th = threading.Thread(target=work, args=(s,), daemon=True, name=f"news-{s['id']}")
        th.start()
        threads.append(th)
        time.sleep(0.2)
    deadline = time.time() + SOURCE_MAX_S
    for th in threads:
        th.join(max(0.0, deadline - time.time()))
    # 并进活动数据：排队（另一次读取可能也在写），拿到后重新读一遍文件
    t_wait = time.time()
    while not _lock(d / "write.lock", 300) and time.time() - t_wait < 240:
        time.sleep(1)
    try:
        return _merge(cfg, d, todo, current, now, results, misses, want_img)
    finally:
        (d / "write.lock").unlink(missing_ok=True)


def _merge(cfg, d, todo, current, now, results, misses, want_img) -> dict:
    items: dict = _load(d / "items.json", {})
    status = {s["id"]: s for s in _load(d / "sources.json", []) if s["id"] in current}
    for src in todo:
        st = {"id": src["id"], "game": src["game"], "type": src["type"], "fetched": _fmt(now), "ok": False,
              "count": 0, "error": ""}
        first = not status.get(src["id"], {}).get("ok")  # 这个来源第一次读到：不算「新活动」，免得第一天刷屏
        baseline = _fmt(now - timedelta(days=2))
        t0 = time.time()
        miss = misses[src["id"]]
        try:
            r = results.get(src["id"]) or ("err", TimeoutError(f"超过 {SOURCE_MAX_S} 秒没读完（网站太慢或没响应），这次先跳过"), SOURCE_MAX_S)
            t0 -= r[2]
            if r[0] == "err":
                raise r[1]
            got = r[1]
            from .. import newscat as NC
            if not NC.load_prefs(cfg["machine"]["data_dir"]).get("fetch_all"):  # 版本更新公告、说明类公告默认不抓
                got = [it for it in got if it.get("forecast") or it.get("img_only") or NC.classify(it) not in NC.DROP]
            for it in got:
                st_, en_ = _parse_dt(it.get("start")), _parse_dt(it.get("end"))
                if st_ and en_ and en_ - st_ > timedelta(days=60):  # 防沉迷说明、FAQ 这类常驻公告：不进日历和轮播
                    it["kind"] = "常驻"
                old = items.get(it["id"], {})
                if it.get("start_note") == "最早读到":  # 开始时间不知道的：一直用第一次读到的时间，不随每天重读往后挪
                    it["start"] = it["first_read"] = old.get("first_read") or it.get("start")
                elif not it.get("start_note") and st_:
                    note = after_note(it.get("text", "") + "\n" + (it.get("subtitle") or ""), st_)
                    if note:
                        it["start_note"] = note
                # 11-02：一条活动的所有图都下（最多 6 张）；img_map 记「图片地址 → 文件名」，下次不重复下
                bu = it.get("banner_url") or ""
                urls = ([bu] + [u for u in it.pop("banner_urls", []) or [] if u and u != bu])[:6] if bu else []
                it.pop("banner_urls", None)
                omap = dict(old.get("img_map") or {})
                if not omap and old.get("img") and old.get("banner_url") == bu:  # 以前只记了一张
                    omap[bu] = old["img"]
                imap = {u: omap[u] for u in urls if omap.get(u) and (d / "img" / omap[u]).exists()}  # 图不在了（被误删）：重新下载
                if not it.get("end") or it["end"] >= _fmt(now - timedelta(days=1)):
                    want_img += [(it["id"], u, src["id"]) for u in urls if u not in imap]  # 题图最后一起并行下载
                img = imap.get(bu, "")
                content = it.pop("content", "")
                if content:
                    (d / "content").mkdir(exist_ok=True)
                    (d / "content" / f"{hashlib.sha1(it['id'].encode()).hexdigest()[:16]}.html").write_text(
                        content, encoding="utf-8")
                it.setdefault("img_rank", 1 if src["type"] == "ingame" else 3)  # 题图优先：官网 3 > 活动中心 2 > 游戏内公告 1（11-02）
                items[it["id"]] = {**it, "img": img, "img_map": imap, "_urls": urls, "img_groups": None,
                                   "imgs": [imap[u] for u in urls if u in imap], "detail": bool(content),
                                   "seen": old.get("seen") or (baseline if first else _fmt(now))}
            st.update(ok=True, count=len(got))
            ids = {it["id"] for it in got}
            for k in [k for k, it in items.items() if it.get("source") == src["id"] and k not in ids]:
                items.pop(k)  # 这个来源这次没再给的（旧的读法留下的、被撤下的）去掉
        except Exception as e:
            st["error"] = f"{type(e).__name__}: {e}"[:300]
        print(f"  {'✓' if st['ok'] else '✗'} {src['id']} {st['count']} 条，{time.time() - t0:.0f} 秒 {st['error']}", flush=True)
        status[src["id"]] = st
    if want_img:  # 只下进行中 / 将要开始的活动的题图，6 个一起下；一次最多 60 张，其余下次读取时再下
        from concurrent.futures import ThreadPoolExecutor
        t0 = time.time()

        def one(x):
            try:
                return _cache_img(x[1], d), None
            except Exception as e:
                return "", e
        with ThreadPoolExecutor(6) as ex:
            got_img = list(ex.map(one, want_img[:150]))
        for (iid, url, sid), (name, err) in zip(want_img, got_img):
            if err is not None:
                misses[sid].add("题图下载失败", err)
            elif iid in items and name:
                x = items[iid]
                x.setdefault("img_map", {})[url] = name
                x["imgs"] = [x["img_map"][u] for u in x.get("_urls", [url]) if u in x["img_map"]]
                x["img"] = x["img_map"].get(x.get("banner_url"), "") or x["img"] or name
        print(f"· 题图 {sum(1 for n, _ in got_img if n)}/{len(got_img)} 张，{time.time() - t0:.0f} 秒", flush=True)
    for sid, m in misses.items():  # 「几条没读全、为什么」写进来源状态（界面上显示，旁边有「重读」）
        status[sid].update(m.summary())
    # 活动中心的整页图（只当题图）：配给同一游戏、名字互相包含的活动；比它原来的题图来源好就换上。配不上的不单独显示（11-02）
    rank = lambda it: it.get("img_rank", 3) if it.get("img") else 0

    def own(x):  # 这条自己帖子里的图（img_map 只记自己的图片地址；老数据只有一张 img）
        return list(dict.fromkeys((x.get("img_map") or {}).values())) or ([x["img"]] if x.get("img") else [])
    # 开屏海报（img_rank 4，最清楚）：海报上识别出的字里包含活动名就配上
    for e in sorted([x for x in items.values() if x.get("img_only")], key=lambda x: x.get("img_rank", 0)):
        ne = _norm(e["title"])
        mt = _norm(e.get("match_text", ""))
        for it in items.values():
            if it.get("img_only") or it["game"] != e["game"] or not ne:
                continue
            ni = _norm(it["title"])
            names = [ni] + [_norm(x) for x in re.findall(r"「([^」]+)」", it["title"])]  # 官网标题：书名号里的才是活动名
            hit = any(len(x) >= 3 and x in mt for x in names) if mt else (ni and (ne in ni or ni in ne))
            if hit and e.get("img"):  # 11-02：配上的图算另一组，最后和合并的一样按尺寸挑一张题图
                it["img_groups"] = (it.get("img_groups") or [own(it)]) + [own(e)]
                it["_merged"] = True
    for k in [k for k, x in items.items() if x.get("img_only")]:
        items.pop(k)
    # 合并重复：同一游戏同名的；或起止时间完全相同、一个名字包含另一个的（官网活动文章和更新公告里各写了一次）
    ingame = {s["id"] for s in DEFAULT_SOURCES if s["type"] == "ingame"}

    # 11-02：每条一个固定的分，合并时分高的留下当标题（两两比较的先后不影响结果）：
    # 官方渠道 > 不是附属内容（卡面 SSR/SR、常驻内容更新、服装上架…）> 名字被同游戏别的帖子正文提到的次数多（活动本身）> 有「」/ 题图 > 长
    texts: dict = {}
    for x in items.values():
        texts.setdefault(x["game"], []).append((x["id"], _norm(x.get("text", ""))))
    _SUB = re.compile(r"S?SR|\bR\+|常驻|内容更新|服装|上架|装扮|返利|累充|礼包")

    def score(x):
        n = _norm(x["title"])
        mentions = sum(1 for i, t in texts.get(x["game"], []) if i != x["id"] and len(n) >= 4 and n in t)
        return (x.get("source") not in ingame, not _SUB.search(x["title"]), mentions,
                ("「" in x["title"]) + bool(x.get("img")), len(x["title"]), x["id"])

    def better(a, b):  # 返回 (保留, 去掉)。官方渠道的优先，游戏内读到的只补充细节
        return (a, b) if score(a) >= score(b) else (b, a)
    from .. import newscat as NC
    _cc: dict = {}

    _ct: dict = {}

    def cat(x):  # 活动类型（限定 / 复刻卡池算一类）
        if x["id"] not in _ct:
            c = NC.classify(x, NC.CHARS.get(x["game"], []))
            _ct[x["id"]] = "pool" if c in ("pool", "rerun") else c
        return _ct[x["id"]]

    def chars(x):  # 这条说到的角色（角色名单里的 + 帖子里新出现的「名字」）
        if x["id"] not in _cc:
            _cc[x["id"]] = set(NC.chars_in(x, NC.CHARS.get(x["game"], [])))
        return _cc[x["id"]]
    vals = sorted(items.values(), key=lambda x: x["id"])
    gone = set()
    for i, a in enumerate(vals):
        if a["id"] in gone:
            continue
        for b in vals[i + 1:]:
            if b["id"] in gone or a["game"] != b["game"]:
                continue
            na, nb = _norm(a["title"]), _norm(b["title"])
            exact = na == nb
            same = (a.get("start") and a.get("start") == b.get("start") and a.get("end") == b.get("end")
                    and na and nb and (na in nb or nb in na))
            # 11-02：不同渠道写法不一样（「馥夜轻漾」/「馥夜轻漾」5星思念UP许愿…），名字互相包含、结束在同一天也算同一个
            same = same or (min(len(na), len(nb)) >= 3 and (na in nb or nb in na)
                            and (a.get("end") or "")[:10] == (b.get("end") or "")[:10] and a.get("end"))
            # 11-02：起止时间分秒不差 + 名字有一段相同（「缱绻假日·世纪来电」/「缱绻假日·罗夏SR+[世纪来电]」）
            # 或一条的正文里写着另一条的完整名字（「罗夏的日常」正文：在「缱绻假日·世纪来电」活动期间…）
            # + 两条里出现同一个角色（都说到罗夏）→ 同一个活动
            same = same or (a.get("start") and a.get("end") and a.get("start") == b.get("start") and a.get("end") == b.get("end")
                            and (_shared(na, nb, 4) or (len(na) >= 6 and na in _norm(b.get("text", "")))
                                 or (len(nb) >= 6 and nb in _norm(a.get("text", ""))))
                            and bool(chars(a) & chars(b)))
            # 11-02：名字不完全一样的，还要活动类型相同（「叶瑄SSR·叠轨晨昏」是卡池、「怪谈：时融」是活动：不合并）
            same = exact or (same and cat(a) == cat(b))
            if not same:
                continue
            keep, drop = better(a, b)
            for f in ("url", "img", "start", "end"):
                if not keep.get(f) and drop.get(f):
                    keep[f] = drop[f]
            if drop.get("source") in ingame and len(drop.get("text") or "") > len(keep.get("text") or ""):
                keep["text"] = drop["text"]  # 游戏内公告写得更细：正文用它的（时间、名字仍以官方号为准）
                keep["subtitle"] = keep.get("subtitle") or drop.get("subtitle", "")
                keep["also_ingame"] = True
            # 合并过：每条帖子的图各算一组；最后从所有图里挑一张当题图，只留它所在那条帖子的图（拖动能看）（11-02）
            grp = lambda x: x.get("img_groups") or [own(x)]
            keep["img_groups"] = [g_ for g_ in grp(keep) + grp(drop) if g_]
            keep["_merged"] = True
            if drop.get("img") and rank(drop) > rank(keep):  # 题图按来源挑：官网的优先（11-02）
                keep["img"], keep["img_rank"] = drop["img"], drop.get("img_rank", 3)
            keep["detail"] = keep.get("detail") or drop.get("detail")
            if "活动" in (keep.get("kind"), drop.get("kind")):
                keep["kind"] = "活动"
            gone.add(drop["id"])
            if drop is a:
                break
    for k in gone:
        items.pop(k, None)
    # 11-02：合并成一个活动的，题图从所有图里挑和轮播尺寸最接近的；其余的图留在 imgs（拖动轮播能看）
    pins = NC.load_prefs(cfg["machine"]["data_dir"]).get("img_pin") or {}  # 右键「固定为该活动题图」
    for it in items.values():
        if not it.get("_merged"):
            it["imgs"] = own(it)  # 没合并的：就是它自己帖子的图（不沿用以前合并留下的）
            if it.get("img") not in it["imgs"]:
                it["img"] = (it.get("img_map") or {}).get(it.get("banner_url"), "") or (it["imgs"][0] if it["imgs"] else "")
        if it.pop("_merged", False) and it.get("img_groups"):
            alln = [n for g_ in it["img_groups"] for n in g_ if (d / "img" / n).exists()]
            pin = pins.get(it["id"])
            best = pin if pin in alln else (pick_banner(alln, d / "img") if alln else "")
            if best:
                it["img"] = best
                it["imgs"] = next(g_ for g_ in it["img_groups"] if best in g_)
            else:
                it["imgs"] = own(it)
        it.pop("_urls", None)
        it.pop("img_groups", None)
    # 清掉结束超过 45 天的
    cut = _fmt(now - timedelta(days=KEEP_DAYS))
    for k in [k for k, it in items.items() if (it.get("end") or it.get("seen", "")) < cut]:
        items.pop(k)
    _save(d / "items.json", items)
    _save(d / "sources.json", list(status.values()))
    used = {it.get("img") for it in items.values()} | {n for it in items.values() for n in (it.get("imgs") or [])}
    for f in (d / "img").glob("*") if (d / "img").exists() else []:  # 不再用到的题图删掉
        if f.name not in used and time.time() - f.stat().st_mtime > 3600:  # 刚下的不删（11-02：两次读取同时进行时，另一次会把这次刚下的当成没用的删掉）
            try:
                f.unlink()
            except OSError:
                pass
    keep = {hashlib.sha1(k.encode()).hexdigest()[:16] + ".html" for k in items}
    for f in (d / "content").glob("*.html") if (d / "content").exists() else []:
        if f.name not in keep:
            try:
                f.unlink()
            except OSError:
                pass
    return {"items": len(items), "sources": list(status.values())}


# 按规则算出来的周期条目（总纲 10-23）：周常重置、深渊轮换之类。游戏配置里可以写 cycles 覆盖：
#   cycles = [{ name = "深境螺旋", monthly_day = 16, at = "04:00", note = "…" }, { name = "每周重置", weekday = 1, at = "04:00" }]
#   weekday：1 = 周一 … 7 = 周日（北京时间）
DEFAULT_CYCLES = {
    "genshin": [{"name": "深境螺旋", "monthly_day": 16, "at": "04:00", "note": "每月 16 日 04:00 重置"},
                {"name": "幻想真境剧诗", "monthly_day": 1, "at": "04:00", "note": "每月 1 日 04:00 重置"},
                {"name": "每周重置", "weekday": 1, "at": "04:00", "note": "周本树脂减半次数等每周一 04:00 刷新"}],
    "starrail": [{"name": "每周重置", "weekday": 1, "at": "04:00", "note": "模拟宇宙积分、历战余响次数等每周一 04:00 刷新"}],
}


def cycle_items(cfg: dict, back_days: int = 21, ahead_days: int = 50) -> list[dict]:
    now = _now()
    lo, hi = now - timedelta(days=back_days), now + timedelta(days=ahead_days)
    out = []
    for gid, g in cfg.get("games", {}).items():
        for c in g.get("cycles") or DEFAULT_CYCLES.get(gid, []):
            try:
                hh, mm = map(int, str(c.get("at", "04:00")).split(":"))
            except ValueError:
                continue
            starts = []
            if c.get("monthly_day"):
                y, m = lo.year, lo.month
                while True:
                    try:
                        st = datetime(y, m, int(c["monthly_day"]), hh, mm, tzinfo=BJ)
                    except ValueError:
                        st = None
                    if st and st > hi:
                        break
                    if st:
                        starts.append(st)
                    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
                    if datetime(y, m, 1, tzinfo=BJ) > hi + timedelta(days=31):
                        break
            elif c.get("weekday"):
                d0 = lo.replace(hour=hh, minute=mm, second=0, microsecond=0)
                d0 -= timedelta(days=(d0.isoweekday() - int(c["weekday"])) % 7)
                while d0 <= hi:
                    starts.append(d0)
                    d0 += timedelta(days=7)
            for i, st in enumerate(starts):
                en = (starts[i + 1] if i + 1 < len(starts) else
                      st + (timedelta(days=7) if c.get("weekday") else timedelta(days=30))) - timedelta(minutes=1)
                if en < lo:
                    continue
                out.append({"id": f"rule:{gid}:{c['name']}:{st:%Y%m%d}", "game": gid, "source": "rules", "kind": "周期",
                            "title": c["name"], "start": _fmt(st), "end": _fmt(en), "banner_url": "", "url": "", "img": "",
                            "subtitle": c.get("note", ""), "source_title": "按规则推算（不是公告）", "text": c.get("note", ""),
                            "fixed_cat": "cycle", "detail": False, "seen": _fmt(st)})
    return out


def load(cfg: dict, raw: bool = False) -> dict:
    """只给出当前启用的来源的内容（在 [news] disabled 里关掉的来源，读过的旧内容也不再显示）。
    raw=False 时按 newscat 分类、标出隐藏 / 关注 / 追踪的角色，并带上用户设置。"""
    from .. import newscat as NC
    d = _dir(cfg)
    on = {x["id"] for x in sources(cfg)}
    items = [it for it in _load(d / "items.json", {}).values() if it.get("source") in on]
    imgs = {f.name for f in (d / "img").glob("*")} if (d / "img").exists() else set()
    items = [{**it, "img": it["img"] if it.get("img") in imgs else "",
              "imgs": [n for n in (it.get("imgs") or []) if n in imgs]} for it in items]  # 图不在了就先不显示（不显示裂图）
    items = [{**it, "img": it["img"] or (it["imgs"][0] if it["imgs"] else "")} for it in items]
    srcs = [x for x in _load(d / "sources.json", []) if x.get("id") in on]
    if not raw:
        items += cycle_items(cfg) + version_forecast(items)
        real = [(_norm(x["title"]), x["game"]) for x in items if not x.get("forecast")]
        items = [x for x in items if not x.get("forecast") or not any(
            g == x["game"] and len(_norm(x["title"])) >= 2 and _norm(x["title"]) in t for t, g in real)]
    if raw:
        return {"items": items, "sources": srcs}
    prefs = NC.load_prefs(cfg["machine"]["data_dir"])
    return {"items": NC.decorate(items, prefs), "sources": srcs, "prefs": prefs,
            "cats": [{"id": k, "label": v[0], "default": v[1]} for k, v in NC.CATS.items()]
                    + [{"id": k, "label": v, "default": True, "user": True} for k, v in (prefs.get("user_cats") or {}).items()],
            "chars": NC.characters(items, prefs)}


def act(cfg: dict, body: dict) -> dict:
    """界面上的关注 / 屏蔽操作。body = {act, id?, game?, cat?, name?, key?, value?}"""
    from .. import newscat as NC
    return NC.update_prefs(cfg["machine"]["data_dir"], lambda p: _apply(p, body))


def _apply(p: dict, body: dict):
    """act 的一次修改（在锁里就地改）。"""
    from .. import newscat as NC
    a, iid, g, cat, name = body.get("act"), body.get("id", ""), body.get("game", "*"), body.get("cat", ""), body.get("name", "")

    def toggle(lst: list, x, on: bool):
        if on and x not in lst:
            lst.append(x)
        if not on and x in lst:
            lst.remove(x)
    if a in ("hide", "unhide"):
        toggle(p["hidden_items"], iid, a == "hide")
    elif a in ("follow", "unfollow"):
        toggle(p["followed"], iid, a == "follow")
        toggle(p["asked"], iid, True)
    elif a == "asked":
        toggle(p["asked"], iid, True)
    elif a == "pin_img":  # 右键「固定为该活动题图」（11-02）：value = 图片文件名；空 = 恢复自动挑的
        v = str(body.get("value") or "").strip()
        pins = p.setdefault("img_pin", {})
        if v and re.fullmatch(r"[0-9a-f]{20}\.\w{3,4}", v):
            pins[iid] = v
        else:
            pins.pop(iid, None)
    elif a == "set_cat":
        if cat in NC.CATS or cat in p["user_cats"]:
            p["cat_override"][iid] = cat
        else:
            p["cat_override"].pop(iid, None)
    elif a == "set_tag":  # 日历左边的标签：value 空 = 恢复自动
        v = str(body.get("value") or "").strip()[:6]
        if v:
            p["tag_override"][iid] = v
        else:
            p["tag_override"].pop(iid, None)
    elif a == "set_dates":  # 自己改起止时间（北京时间 YYYY-MM-DD HH:MM）；都空 = 恢复识别的
        st, en = str(body.get("start") or "").strip(), str(body.get("end") or "").strip()
        for v in (st, en):
            if v and not re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", v):
                raise ValueError(f"时间格式不对：{v}（要写成 2026-11-01 05:00）")
        if st and en and en <= st:
            raise ValueError("结束要晚于开始")
        if st or en:
            p["date_override"][iid] = {"start": st, "end": en}
        else:
            p["date_override"].pop(iid, None)
    elif a == "add_cat":  # 自己建一个类别，并把这条活动放进去（id 给了的话）
        label = name.strip()[:12]
        if not label:
            raise ValueError("类别要有名字")
        if label in [v[0] for v in NC.CATS.values()] or label in p["user_cats"].values():
            raise ValueError(f"已经有叫「{label}」的类别了")
        cid = "u_" + hashlib.sha1(label.encode()).hexdigest()[:8]
        p["user_cats"][cid] = label
        if iid:
            p["cat_override"][iid] = cid
    elif a == "del_cat":  # 删掉自己建的类别：放进去的活动回到自动分类
        p["user_cats"].pop(cat, None)
        p["cat_override"] = {k: v for k, v in p["cat_override"].items() if v != cat}
    elif a in ("hide_cat", "unhide_cat"):
        toggle(p["hidden_cats"].setdefault(g, []), cat, a == "hide_cat")
    elif a in ("track", "untrack"):
        toggle(p["track"].setdefault(g, []), name, a == "track")
    elif a == "add_char" and name.strip():
        toggle(p["extra_chars"].setdefault(g, []), name.strip(), True)
    elif a == "set":  # push_followed / push_images / fetch_all
        k = body.get("key")
        if k in ("push_followed", "push_images", "fetch_all"):
            p[k] = bool(body.get("value"))
    elif a == "news_off":  # 活动页 / 主页按游戏的显示开关（两边共用）
        toggle(p.setdefault("games_off", []), g, bool(body.get("value")))
    else:
        raise ValueError(f"不认识的操作：{a}")


def content_of(cfg: dict, item_id: str) -> str:
    p = _dir(cfg) / "content" / f"{hashlib.sha1(item_id.encode()).hexdigest()[:16]}.html"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def img_path(cfg: dict, name: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{20}\.(jpg|jpeg|png|webp|gif)", name or ""):
        return None
    p = _dir(cfg) / "img" / name
    return p if p.exists() else None


# ---------------------------------------------------------------- 报告用：新活动、快结束的
def highlights(cfg: dict, hours: int = 48) -> dict:
    now = _now()
    nowt, soon = _fmt(now), _fmt(now + timedelta(hours=hours))
    since = _fmt(now - timedelta(hours=24))
    def short(it):  # 持续超过 90 天的是常驻说明，不算活动
        a, b = _parse_dt(it.get("start")), _parse_dt(it.get("end"))
        return not (a and b and (b - a).days > 60)
    items = [it for it in load(cfg)["items"] if not it.get("hidden") and short(it)]
    ending = sorted([it for it in items if it.get("end") and nowt <= it["end"] <= soon], key=lambda x: x["end"])
    new = [it for it in items if it.get("seen", "") >= since and (not it.get("end") or it["end"] >= nowt)
           and it not in ending]
    return {"ending": ending, "new": new}


def local_of(bj: str, machine_tz: str) -> str:
    """北京时间字符串 → 电脑本地时间 "MM-DD HH:MM"。"""
    from zoneinfo import ZoneInfo
    dt = _parse_dt(bj)
    if not dt:
        return ""
    try:
        tz = ZoneInfo(machine_tz)
    except (KeyError, ValueError) as e:  # ZoneInfoNotFoundError 是 KeyError
        raise ValueError(f"config/butler.toml 里的电脑时区写错了：{machine_tz!r}") from e
    return dt.astimezone(tz).strftime("%m-%d %H:%M")
