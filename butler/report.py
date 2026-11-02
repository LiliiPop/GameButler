"""运行记录和每日汇总。界面、推送都从这里取，不经过网页层。

- list_runs：某个游戏某个游戏日的运行记录（data/runs/<日期>/<游戏>-<时间>.jsonl，每次运行一份）。
- build：某个日程日的汇总：每个游戏的任务状态（各按自己的游戏日，日期和日程日相同）、需要处理的、提醒、
  快结束 / 新出的活动，以及推送用的纯文字。
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from . import evidence as EV
from . import games as G
from . import news
from . import rounds as R
from .runstate import now_bj
from .store import DONE, NEED_ATTENTION, RESULT_CN, Store, item_key
from .timeutil import BJ, game_day, sched_day

RUN_RE = re.compile(r"^(?P<gid>.+)-(?P<stamp>\d{8}-\d{6})\.jsonl$")


# ---------------------------------------------------------------- 运行记录
def _url_after(path: str, anchor: list[str], prefix: str) -> str:
    """截图的完整路径 → 界面用的地址：取 anchor 那几段之后的部分（管家文件夹搬过地方也认得出）。"""
    parts = re.split(r"[\\/]+", path)
    n = len(anchor)
    for i in range(len(parts) - n, -1, -1):
        if [x.lower() for x in parts[i:i + n]] == [x.lower() for x in anchor]:
            return prefix + "/".join(parts[i + n:])
    return ""  # 不在管家的数据文件夹里：界面没法打开，由调用方写进这次运行的消息


def shot_url(gid: str, path: str) -> str:
    return _url_after(path, ["maafw", gid], f"/shots/{gid}/")


def evidence_url(path: str) -> str:
    return _url_after(path, ["evidence"], "/evidence/")


def _urls(paths: list[str], conv, messages: list, ts) -> list[str]:
    out = []
    for p in paths:
        u = conv(p)
        if u:
            out.append(u)
        else:
            messages.append({"level": "warn", "text": f"截图不在管家的数据文件夹里，界面打不开：{p}", "time": ts})
    return out


def read_run(path: Path, gid: str, data_dir: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    if not text.endswith("\n"):
        lines = lines[:-1]  # 正在跑：最后一行可能还没写完
    events = [json.loads(x) for x in (y.strip() for y in lines) if x.startswith("{")]  # 别的行是执行器底层组件的调试输出
    stamp = RUN_RE.match(path.name).group("stamp")
    started = datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=BJ)  # 文件名就是北京时间
    tasks: dict = {}
    order = []
    summary = None
    messages = []
    last_ts = None
    for e in events:
        k = e.get("event")
        last_ts = e.get("bj") or last_ts
        if k == "task_start":
            if e["task"] not in tasks:
                tasks[e["task"]] = {"task": e["task"], "attempts": [], "result": "running", "detail": ""}
                order.append(e["task"])
            tasks[e["task"]]["attempts"].append({"attempt": e.get("attempt", 1), "start": e.get("bj") or e.get("ts"),
                                                  "result": "running"})
        elif k == "task_end":
            t = tasks.setdefault(e["task"], {"task": e["task"], "attempts": [], "result": "", "detail": ""})
            if e["task"] not in order:
                order.append(e["task"])
            att = t["attempts"][-1] if t["attempts"] and t["attempts"][-1].get("result") == "running" else {}
            if not att:
                t["attempts"].append(att)
            att.update({"attempt": e.get("attempt", 1), "end": e.get("bj") or e.get("ts"), "result": e["result"],
                        "detail": e.get("detail", ""), "minutes": e.get("minutes", 0), "focus": e.get("focus", []),
                        "flags": e.get("flags", []),
                        "shots": _urls(e.get("shots", []), lambda s: shot_url(gid, s), messages, e.get("bj")),
                        "evidence": _urls(e.get("evidence", []), evidence_url, messages, e.get("bj"))})
            t["result"], t["detail"] = e["result"], e.get("detail", "")
        elif k in ("fatal", "warn", "abort"):
            messages.append({"level": k, "text": e.get("reason") or e.get("msg", ""), "time": e.get("bj") or e.get("ts")})
        elif k == "info" and "已截图" not in e.get("msg", ""):
            messages.append({"level": "info", "text": e.get("msg", ""), "time": e.get("bj") or e.get("ts")})
        elif k == "summary":
            summary = e
    out_tasks = []
    for name in order:
        t = tasks[name]
        t["tries"] = len([a for a in t["attempts"] if a.get("result") != "running"])
        t["minutes"] = round(sum(a.get("minutes", 0) for a in t["attempts"]), 1)
        t["shots"] = [s for a in t["attempts"] for s in a.get("shots", [])]
        t["evidence"] = [s for a in t["attempts"] for s in a.get("evidence", [])]
        out_tasks.append(t)
    return {"id": f"{gid}-{stamp}", "started": started.strftime("%Y-%m-%d %H:%M:%S"), "last_event": last_ts,
            "finished": summary is not None, "ok": bool(summary and summary.get("ok")),
            "stopped": bool(summary and summary.get("stopped")), "aborted": bool(summary and summary.get("aborted")),
            "tasks": out_tasks, "messages": messages[-30:],
            "log": "/".join(path.relative_to(data_dir).parts)}


def list_runs(cfg: dict, gid: str, day: date) -> list[dict]:
    data_dir = Path(cfg["machine"]["data_dir"])
    g = cfg["games"][gid]
    out = []
    for d in (day, day + timedelta(days=1)):  # 游戏日 D 的运行，文件夹（北京时间日期）只可能是 D 或 D+1
        for p in sorted((data_dir / "runs" / d.strftime("%Y%m%d")).glob(f"{gid}-*.jsonl")):
            m = RUN_RE.match(p.name)
            if not m or m.group("gid") != gid:
                continue
            started = datetime.strptime(m.group("stamp"), "%Y%m%d-%H%M%S").replace(tzinfo=BJ)
            if game_day(g, started) == day:
                out.append(read_run(p, gid, data_dir))
    out.sort(key=lambda r: r["started"])
    return out


def forget(cfg: dict, gid: str):
    """彻底删除：这个游戏的运行记录。"""
    for f in (Path(cfg["machine"]["data_dir"]) / "runs").glob(f"*/{gid}-*"):
        f.unlink()


# ---------------------------------------------------------------- 汇总
def plain(text: str) -> str:
    from .notify import plain as _p
    return _p(text)


def build(cfg: dict, day_str: str = "today") -> dict:
    store = Store(cfg["machine"]["data_dir"])
    games = cfg["games"]
    the_day = sched_day() if day_str in ("today", "") else date.fromisoformat(day_str)
    out, lines = [], []
    tot_done = tot_all = tot_att = tot_alert = 0
    nowtxt = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
    for gid, g in games.items():
        if not G.available(g)[0]:
            continue
        ad = G.adapter(cfg, gid)
        from .schedule import Schedule
        # 今天的报告：每个游戏按它自己的游戏日（04:00 换日后、05:00 刷新的游戏还在前一天，跑的记录也记在前一天）
        gd = game_day(g) if the_day == sched_day() else the_day
        st = store.status(gid, gd)
        tasks = Schedule(cfg).game_tasks(gid, the_day)  # 这一天各条里的任务，加上没在里面但这天跑过的
        have = {item_key(t) for t in tasks}
        tasks += [{"task": k, "key": k} for k in st if k not in have]
        rows = []
        for t in tasks:
            if not ad.usable(t["task"]):
                continue
            k = item_key(t)
            s = st.get(k, {})
            rows.append({"task": k, "result": s.get("result", "pending"), "detail": s.get("detail", ""),
                         "time": s.get("time", ""), "attempts": s.get("attempts", 0),
                         **({"alert": s["alert"]} if s.get("alert") else {}),
                         **({"evidence": evs} if (evs := EV.files_for(cfg, gd.isoformat(), gid, k)) else {})})
        if gd == game_day(g):  # 自动重复：已排上的轮次也列出来
            for rd in R.for_game(cfg, gid, store, gd)[0]:
                if not ad.usable(rd["task"]):
                    continue
                s = st.get(rd["key"], {})
                rows.append({"task": rd["key"], "result": s.get("result", "pending"), "detail": s.get("detail", ""),
                             "time": s.get("time", ""), "attempts": s.get("attempts", 0),
                             "round_of": rd["_base"], "not_before": rd["_not_before"].strftime("%Y-%m-%d %H:%M"),
                             **({"alert": s["alert"]} if s.get("alert") else {})})
        listed = {r["task"] for r in rows}
        for k, s in st.items():  # 计划里没有、但今天点名跑过的任务也列出来
            if k not in listed:
                rows.append({"task": k, "result": s["result"], "detail": s.get("detail", ""), "time": s.get("time", ""),
                             "attempts": s.get("attempts", 0), "extra": True, **({"alert": s["alert"]} if s.get("alert") else {})})
        done = [r for r in rows if r["result"] in DONE]
        att = [r for r in rows if r["result"] in NEED_ATTENTION]
        pend = [r for r in rows if r["result"] == "pending"]
        runs = list_runs(cfg, gid, gd)
        last = runs[-1] if runs else None
        alerts = [{"task": r["task"], "text": r["alert"]} for r in rows if r.get("alert")]
        tot_alert += len(alerts)
        out.append({"id": gid, "name": g["name"], "day": gd.isoformat(), "total": len(rows),
                    "done": len(done), "attention": att, "alerts": alerts, "pending": [r["task"] for r in pend], "tasks": rows,
                    "runs": len(runs), "last_run": ({"started": last["started"], "ok": last["ok"],
                                                     "finished": last["finished"]} if last else None)})
        tot_done += len(done)
        tot_all += len(rows)
        tot_att += len(att)
        if not rows:
            continue
        # 推送正文：纯文字，不带 emoji（任务名里的图标也去掉）
        later = [r for r in pend if r.get("not_before", "") > nowtxt]
        notyet = [r for r in pend if r not in later]
        state = "全部完成" if len(done) == len(rows) else ("有问题" if att else "进行中")
        lines.append(f"【{plain(g['name'])}】{len(done)}/{len(rows)} {state}")
        for r in att:
            lines.append(f"  {RESULT_CN[r['result']]} · {plain(r['task'])}" + (f"：{plain(r['detail'])}" if r["detail"] else ""))
        for a in alerts:
            lines.append(f"  提醒 · {plain(a['task'])}：{plain(a['text'])}")
        if notyet:
            lines.append(f"  未运行：{'、'.join(plain(r['task']) for r in notyet[:6])}{' 等' if len(notyet) > 6 else ''}")
        if later:
            lines.append(f"  稍后再跑：{'、'.join(plain(r['task']) + '（' + r['not_before'][11:] + '）' for r in later[:6])}")
    news_part = {"ending": [], "new": []}
    if the_day == sched_day():  # 活动提醒（只放在当天的报告里）：快结束的写「建议检查完成情况」
        hl = news.highlights(cfg)
        tz = cfg["machine"]["timezone"]
        gname = lambda gid: plain(games[gid]["name"]) if gid in games else gid
        for it in hl["ending"]:
            loc = news.local_of(it["end"], tz)
            it["text"] = f"{gname(it['game'])}『{plain(it['title'])}』{it['end'][5:]}（北京时间）" \
                         + (f"· 本地 {loc} " if loc else "") + "结束，建议检查完成情况"
        for it in hl["new"]:
            it["text"] = f"{gname(it['game'])}『{plain(it['title'])}』" + \
                (f"{it['start'][5:]} ～ {it['end'][5:]}（北京时间）" if it.get("start") and it.get("end") else "")
        news_part = {"ending": [{k: it[k] for k in ("id", "game", "title", "end", "text")} for it in hl["ending"]],
                     "new": [{k: it.get(k, "") for k in ("id", "game", "title", "start", "end", "text")} for it in hl["new"]]}
        if hl["ending"] or hl["new"]:
            lines.append("【活动】")
            lines += [f"  快结束 · {it['text']}" for it in hl["ending"][:8]]
            lines += [f"  新活动 · {it['text']}" for it in hl["new"][:8]]
    title = f"游戏日常 {the_day.isoformat()}：完成 {tot_done}/{tot_all}" + (f"，{tot_att} 项需处理" if tot_att else "") \
        + (f"，{tot_alert} 条提醒" if tot_alert else "")
    return {"day": the_day.isoformat(), "generated": now_bj(), "games": out,
            "summary": {"total": tot_all, "done": tot_done, "attention": tot_att, "alerts": tot_alert},
            "title": title, "text": "\n".join(lines), "news": news_part}


def problems(rep: dict, gids: list[str] | None = None) -> list[str]:
    """汇总里需要处理的和提醒，一条一行（推送用）。"""
    out = []
    for g in rep["games"]:
        if gids and g["id"] not in gids:
            continue
        name = plain(g["name"])
        for r in g["attention"]:
            out.append(f"{name} · {plain(r['task'])}：{RESULT_CN[r['result']]}" + (f"，{plain(r['detail'])}" if r.get("detail") else ""))
        for a in g["alerts"]:
            out.append(f"{name} · {plain(a['task'])}：{plain(a['text'])}")
    return out
