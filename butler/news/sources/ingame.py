"""游戏内公告栏（模拟器截图识别的结果）。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from pathlib import Path

from ..common import _fmt, _now, _parse_dt, banner_period, extract_period, fix_art_title, forecast_from_text

def read(src: dict, data_dir: Path, miss) -> list[dict]:
    """游戏内公告栏 + 活动中心的题图（11-02）。活动中心只提供题图（img_only），合并时按名字配给同名活动。"""
    ev = events(src, data_dir) + ads(src, data_dir)
    try:
        return _read_notice(src, data_dir, miss) + ev
    except RuntimeError:
        if ev:
            return ev
        raise


def events(src: dict, data_dir: Path) -> list[dict]:
    """「🖼读活动中心」存的 data/news/ingame/<游戏>_events.json：每个活动一张整页图，只当题图用。"""
    g = src["game"]
    f = data_dir / "ingame" / f"{g}_events.json"
    if not f.exists():
        return []
    d = json.loads(f.read_text(encoding="utf-8"))
    out = []
    for it in d.get("items", []):
        p = data_dir / "ingame" / f"{g}_events" / (it.get("banner") or "")
        if not it.get("title") or not it.get("banner") or not p.exists():
            continue
        body = p.read_bytes()
        name = hashlib.sha1(body).hexdigest()[:20] + ".png"
        (data_dir / "img").mkdir(exist_ok=True)
        if not (data_dir / "img" / name).exists():
            (data_dir / "img" / name).write_bytes(body)
        out.append({"id": f"{src['id']}:ev:{hashlib.sha1(it['title'].encode()).hexdigest()[:12]}", "game": g,
                    "source": src["id"], "kind": "活动", "title": it["title"], "start": "", "end": "",
                    "banner_url": "file:" + name, "url": "", "subtitle": "", "source_title": "游戏内 · 活动中心",
                    "text": "", "img_only": True, "img_rank": 1.2})
    return out


def ads(src: dict, data_dir: Path) -> list[dict]:
    """开屏活动海报（每天第一次进游戏弹的那几张，启动任务点掉之前截的原图）：按海报上的字配给同名活动，题图优先用它。"""
    g = src["game"]
    f = data_dir / "ingame" / f"{g}_ads.json"
    if not f.exists():
        return []
    out = []
    for it in json.loads(f.read_text(encoding="utf-8")).get("items", []):
        p = data_dir / "ingame" / f"{g}_ads" / (it.get("banner") or "")
        if not it.get("text") or not p.exists():
            continue
        body = p.read_bytes()
        name = hashlib.sha1(body).hexdigest()[:20] + ".png"
        (data_dir / "img").mkdir(exist_ok=True)
        if not (data_dir / "img" / name).exists():
            (data_dir / "img" / name).write_bytes(body)
        out.append({"id": f"{src['id']}:ad:{name[:12]}", "game": g, "source": src["id"], "kind": "活动",
                    "title": it["text"][:30], "start": "", "end": "", "banner_url": "file:" + name, "url": "",
                    "subtitle": "", "source_title": "游戏内 · 开屏海报", "text": "", "img_only": True,
                    "match_text": it["text"], "img_rank": 1.5})  # 游戏内的都排在站外之后（11-02）
    return out


def _read_notice(src: dict, data_dir: Path, miss) -> list[dict]:
    """游戏内公告栏：闲时批次里的「📰读游戏内公告」任务截图识别后存在 data/news/ingame/<游戏>.json，这里拆成活动。"""
    g = src["game"]
    f = data_dir / "ingame" / f"{g}.json"
    if not f.exists():
        raise RuntimeError("没有进游戏读过公告（站外来源都读不到、且在设置 → 游戏内读取里允许时才会读）")
    d = json.loads(f.read_text(encoding="utf-8"))
    ref = _parse_dt(d.get("fetched")) or _now()
    out = []

    def save_banner(it) -> str:
        if not it.get("banner"):
            return ""
        p = data_dir / "ingame" / g / it["banner"]
        if not p.exists():
            return ""
        body = p.read_bytes()
        name = hashlib.sha1(body).hexdigest()[:20] + ".png"
        (data_dir / "img").mkdir(exist_ok=True)
        if not (data_dir / "img" / name).exists():
            (data_dir / "img" / name).write_bytes(body)
        return "file:" + name

    def item(title, start, end, banner, sub, text, src_title):
        # 副标题开头的起止时间日历上已经有了，去掉（「10月19日上午5:00~10月27日上午4:59，可从……」→「可从……」）
        sub = re.sub(r"^\s*\d{1,2}月\d{1,2}日[^，,。]{0,12}?\d{1,2}:\d{2}(\s*[~～至-]\s*\d{1,2}月\d{1,2}日[^，,。]{0,12}?\d{1,2}:\d{2})?[^，,。]{0,4}[，,]\s*", "", sub or "")
        return {"id": f"{src['id']}:{hashlib.sha1(title.encode()).hexdigest()[:12]}", "game": g, "source": src["id"],
                "kind": "活动" if start else "公告", "title": title, "start": _fmt(start), "end": _fmt(end),
                "banner_url": banner, "url": "", "content": "", "subtitle": sub[:90], "source_title": src_title,
                "text": text[:900]}

    fc = []
    for x in d.get("items", []):
        if x.get("kind") in ("system", None) or x.get("text"):
            fc += forecast_from_text(x.get("text") or "", ref, g, src["id"], "游戏内公告")
    seen_fc = set()
    fc = [x for x in fc if not (x["id"] in seen_fc or seen_fc.add(x["id"]))]
    out += fc
    if any(it.get("kind") == "card" for it in d.get("items", [])):
        # 代号鸢式：活动页一张张卡片（名字 + 剩余时间）；结束时间优先用公告里写的「【活动名】…10月28日23:59结束」
        notice = "".join(x.get("text", "").replace("\n", "") for x in d["items"] if x.get("kind") == "system")
        for c in d["items"]:
            if c.get("kind") != "card" or not c.get("title"):
                continue
            c = {**c, "title": fix_art_title(c["title"], notice)}
            base = re.split(r"[·・]", c["title"])[0]
            st, en, how = None, None, ""
            i = notice.find(f"【{base}】")
            if i >= 0:
                seg = re.split(r"[一二三四五六七八九十]+、", notice[i:])[0]
                m = re.search(r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})\s*结束", seg)
                if m:
                    en, _ = banner_period(f"{m.group(1)}月{m.group(2)}日{m.group(3)}:{m.group(4)}", ref)
                    how = "公告"
            r = re.search(r"(\d+)\s*天\s*(\d+)\s*[时小]", c.get("remain", ""))
            if not en and r:
                en = (ref + timedelta(days=int(r.group(1)), hours=int(r.group(2)), minutes=59)).replace(second=0)
                how = "剩余时间"
            if en:
                st = ref.replace(second=0)  # 开始时间活动页上没有：记成「最早读到」的时间（fetch 里保留第一次读到的）
            it = item(c["title"], st, en, save_banner(c), c.get("list_title", ""), c.get("text", ""),
                      "游戏内 · 活动页" + (f"（结束时间按{how}）" if how else ""))
            if st:
                it["start_note"] = "最早读到"
            if not r and not how:
                it["kind"] = "常驻"  # 没有剩余时间的（每日进膳之类）：常驻玩法
            out.append(it)
        return out
    if any(it.get("kind") in ("banner", "system") for it in d.get("items", [])):
        # 恋与深空式：系统公告按「>>活动名」拆成一条条活动；活动公告的 banner 按起止时间配上去当题图
        secs = []
        for it in d["items"]:
            if it.get("kind") != "system":
                continue
            cur = None
            for ln in (it.get("text") or "").split("\n"):
                m = re.match(r"^\s*[>》]{1,2}\s*(.+)$", ln)
                if m:
                    name, _, sub = re.split(r"[:：]", m.group(1), 1)[0], "", ""
                    parts = re.split(r"[:：]", m.group(1), 1)
                    name, sub = parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")
                    same = next((x for x in secs if x["name"] == name), None)
                    if same:  # 翻页边界上同一个小标题读了两遍（第二遍可能连着下一行）：并到前一个里
                        cur = same
                        if sub != same["sub"]:
                            cur["lines"].append(sub[len(same["sub"]):] if sub.startswith(same["sub"]) else sub)
                        continue
                    cur = {"name": name, "sub": sub, "lines": []}
                    secs.append(cur)
                elif cur is not None:
                    cur["lines"].append(ln)
        used = set()
        banners = [it for it in d["items"] if it.get("kind") == "banner"]
        for sec in secs:
            body = "\n".join(([sec["sub"]] if len(sec["sub"]) > 16 else []) + sec["lines"])
            st, en = extract_period(body, ref)
            img = ""
            for k, b in enumerate(banners):
                bs, be = banner_period(b.get("period") or b.get("text", ""), ref)
                if k not in used and st and bs and abs((bs - st).total_seconds()) < 3600 and en and be \
                        and abs((be - en).total_seconds()) < 3600:
                    used.add(k)
                    img = save_banner(b)
                    break
            full = sec["name"] + (f"：{sec['sub']}" if sec["sub"] and len(sec["sub"]) <= 16 else "")  # 原标题整句
            out.append(item(full, st, en, img, sec["lines"][0] if sec["lines"] else sec["sub"], body,
                            "游戏内公告 · 系统公告"))
        for k, b in enumerate(banners):  # 系统公告里没写到的 banner：单独一条，标题是图里最大的字
            if k in used or not b.get("title"):
                continue
            bs, be = banner_period(b.get("period") or b.get("text", ""), ref)
            out.append(item(b["title"], bs, be, save_banner(b), b.get("list_title", ""), b.get("text", ""),
                            "游戏内公告 · 活动公告"))
        return out
    for it in d.get("items", []):
        title, text = it.get("title") or it.get("list_title") or "", it.get("text") or ""
        if not title:
            continue
        banner = ""
        if it.get("banner"):
            p = data_dir / "ingame" / g / it["banner"]
            if p.exists():
                body = p.read_bytes()
                name = hashlib.sha1(body).hexdigest()[:20] + ".png"
                (data_dir / "img").mkdir(exist_ok=True)
                if not (data_dir / "img" / name).exists():
                    (data_dir / "img" / name).write_bytes(body)
                banner = "file:" + name
        start, end = extract_period(text, ref)
        first = next((x for x in text.split("\n") if len(x.strip()) >= 8 and not re.match(r"^.{0,6}[:：]$", x.strip())
                      and not re.search(r"\d+月\d+日.{0,8}[-~～至]", x[:20])), "")
        out.append({"id": f"{src['id']}:{hashlib.sha1(title.encode()).hexdigest()[:12]}", "game": g, "source": src["id"],
                    "kind": "活动" if start else "公告", "title": title, "start": _fmt(start), "end": _fmt(end),
                    "banner_url": banner, "url": "", "content": "", "subtitle": first.strip()[:90],
                    "source_title": "游戏内公告" + (f"（{it['date']}）" if it.get("date") else ""), "text": text[:900]})
    return out
