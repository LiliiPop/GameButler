"""一次性迁移（10-28）：日程模板 + 当天计划 + 默认任务预设 → 任务预设上的定时；闲时的分钟数 / 闲时段 → 闲时条件组。

管家启动时调用：还有 data/schedule/templates.json、没有 rules.json 才做；做完把旧文件改名为 *.migrated（不删）。
迁移前后各算一遍「今天每个游戏要跑的任务」，写进 data/logs/migrate-schedule.txt；不一样的列出来。

  模板「每天」里的每个批次 → 一个定时（id 不变，所以今天的顺序、跳过、跑过照样认得）：
    用哪套：批次写了就用它，没写用这个游戏原来的默认任务预设
    只跑部分任务的批次（例如「读公告 · 读资源」）→ 先建一套同名任务预设（任务和选项取自默认任务预设），再挂定时
    时段 + 等闲时 → 闲时（从几点起、到几点为止照搬）；只有时段 → 到点
  其他模板（不是默认的）→ 不迁，报告里列出来
  闲时：idle_minutes → 一组「键鼠不动 ≥ N 分钟」；idle_windows（电脑本地时间）里每段 → 一组「时段」（换成北京时间）
        —— 这些是你自己设过的值，不是管家的默认
  任务预设文件去掉 default；当天计划（data/plans/）不再用，留在原处，报告里列出今天有单独布置的
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import jsonio
from .store import Store, item_key, normalize_tasks
from .timeutil import BJ, game_day, sched_day


def _keys(tasks, rec):
    return [item_key(t) for t in normalize_tasks(tasks) if t["task"] != rec]


def needed(cfg: dict) -> bool:
    d = Path(cfg["machine"]["data_dir"]) / "schedule"
    return (d / "templates.json").exists() and not (d / "rules.json").exists()


def migrate(cfg: dict) -> str:
    data = Path(cfg["machine"]["data_dir"])
    sdir = data / "schedule"
    lines = [f"日程迁移 {datetime.now(BJ):%Y-%m-%d %H:%M:%S}（北京时间）", ""]
    tdoc = jsonio.read(sdir / "templates.json", {})
    tname = tdoc.get("default") or "每天"
    tpls = tdoc.get("templates") or {}
    batches = (tpls.get(tname) or {}).get("batches", [])
    for other in tpls:
        if other != tname:
            lines.append(f"没迁的模板：「{other}」（{len((tpls[other] or {}).get('batches', []))} 个批次）——只迁了默认的「{tname}」")
    today = sched_day()
    old_rt = {}
    for p in (data / "routines").glob("*.json"):
        old_rt[p.stem] = jsonio.read(p, {"default": "", "routines": {}})

    # ---------- 迁移前：今天每个游戏要跑的任务（按旧的规则算） ----------
    def old_tasks(gid):
        g = cfg["games"][gid]
        rec = g.get("recovery_task", "")
        doc = old_rt.get(gid) or {"routines": {}}
        dname = doc.get("default") or next(iter(doc.get("routines", {})), "")
        plan = jsonio.read(data / "plans" / game_day(g).isoformat() / f"{gid}.json", None)
        out = []
        for b in batches:
            if b.get("game") != gid or b.get("enabled") is False:
                continue
            if b.get("routine"):
                src = (doc["routines"].get(b["routine"]) or {}).get("tasks", [])
            else:
                src = plan["tasks"] if plan else (doc["routines"].get(dname) or {}).get("tasks", [])
            ks = _keys(src, rec)
            if b.get("tasks"):
                ks = [k for k in ks if k in b["tasks"]] + [k for k in b["tasks"] if k not in ks]
            out += [k for k in ks if k not in out]
        return out

    before = {gid: old_tasks(gid) for gid in cfg["games"]}
    for gid, g in cfg["games"].items():
        if (data / "plans" / game_day(g).isoformat() / f"{gid}.json").exists():
            lines.append(f"{g['name']}：今天有单独布置的计划，迁移后不再用（今天改按任务预设跑）")

    # ---------- 任务预设：去掉默认；只跑部分任务的批次先建一套任务预设 ----------
    store = Store(str(data))
    rules = []
    for b in batches:
        gid = b.get("game", "")
        doc = old_rt.get(gid) or {"default": "", "routines": {}}
        dname = doc.get("default") or next(iter(doc.get("routines", {})), "")
        routine = b.get("routine") or dname
        if gid not in cfg["games"] and gid not in old_rt:
            lines.append(f"跳过批次 {b.get('id')}：没有这个游戏 {gid}")
            continue
        if b.get("tasks") and not b.get("routine"):
            name = b.get("label") or "部分任务"
            pool = normalize_tasks((doc["routines"].get(dname) or {}).get("tasks", []))
            items = [next((t for t in pool if item_key(t) == k), None) or next((t for t in pool if t["task"] == k), None)
                     or {"task": k, "choices": {}} for k in b["tasks"]]
            rec = (cfg["games"].get(gid) or {}).get("recovery_task", "")
            if rec and rec not in [t["task"] for t in items]:
                r0 = next((t for t in pool if t["task"] == rec), None)
                if r0:
                    items.insert(0, r0)
            doc["routines"][name] = {"tasks": items}
            routine = name
            lines.append(f"{gid}：只跑部分任务的批次「{name}」→ 新建同名任务预设（{len(items)} 项）")
        if not routine or routine not in doc.get("routines", {}):
            lines.append(f"跳过批次 {b.get('id')}（{gid}）：这个游戏没有任务预设可以挂")
            continue
        st = b.get("start") or {}
        if st.get("mode") != "window":
            continue
        when = {"kind": "idle" if st.get("idle") else "at", "at": st.get("from", ""), "until": st.get("to", "")}
        r = {"id": b["id"], "game": gid, "routine": routine, "when": when, "days": "daily",
             "enabled": b.get("enabled", True) is not False}
        for k in ("rerun", "again"):
            if b.get(k):
                r[k] = b[k]
        rules.append(r)
    for gid, doc in old_rt.items():
        store.save_routines(gid, {"routines": doc.get("routines", {})})

    # ---------- 闲时 ----------
    sp = data / "settings.json"
    sdoc = jsonio.read(sp, {})
    sch = sdoc.get("scheduler") or {}
    groups = []
    if "idle_groups" not in sch:
        groups.append([{"kind": "input_idle", "minutes": int(sch.get("idle_minutes", 30))}])
        tz = ZoneInfo(cfg["machine"].get("timezone") or "Asia/Shanghai")
        for w in sch.get("idle_windows") or []:
            a, z = [x.strip() for x in str(w).replace("～", "-").split("-")]

            def bj(hm):
                h, m = map(int, hm.split(":"))
                return datetime.now(tz).replace(hour=h, minute=m).astimezone(BJ).strftime("%H:%M")
            groups.append([{"kind": "time", "from": bj(a), "to": bj(z)}])
        sch["idle_groups"] = groups
        lines.append("闲时：" + "；或 ".join(" 且 ".join(f"键鼠不动 ≥ {c['minutes']} 分钟" if c["kind"] == "input_idle"
                                                    else f"北京 {c['from']}–{c['to']}" for c in g) for g in groups)
                     + "（从你原来的设置转过来）")
    sch.pop("idle_minutes", None)
    sch.pop("idle_windows", None)
    sdoc["scheduler"] = sch
    jsonio.write(sp, sdoc)

    jsonio.write(sdir / "rules.json", {"rules": rules})
    # 今天的文件：去掉模板名；一次性条目换成新格式（读的时候也认旧格式）
    tp = sdir / "days" / f"{today.isoformat()}.json"
    if tp.exists():
        def fn(d):
            d.pop("template", None)
        jsonio.update(tp, {}, fn)
    (sdir / "templates.json").rename(sdir / "templates.json.migrated")
    lines.append(f"定时：{len(rules)} 个（从模板「{tname}」的 {len(batches)} 个批次）")

    # ---------- 迁移后：再算一遍，对比 ----------
    from .schedule import Schedule
    s2 = Schedule(cfg)
    diff = 0
    lines.append("")
    lines.append("今天每个游戏要跑的任务（迁移前 → 迁移后；今天跳过的也算上）：")
    for gid, g in cfg["games"].items():
        rec = g.get("recovery_task", "")
        after = [item_key(t) for t in s2.game_tasks(gid, with_skipped=True) if t["task"] != rec]
        same = set(after) == set(before[gid])
        diff += not same
        lines.append(f"  {'一样' if same else '不一样'}  {g['name']}：{len(before[gid])} → {len(after)} 项")
        if not same:
            lines.append(f"      少了：{'、'.join(k for k in before[gid] if k not in after) or '无'}；"
                         f"多了：{'、'.join(k for k in after if k not in before[gid]) or '无'}")
    lines.append("")
    lines.append("结果：" + ("全部一样" if not diff else f"{diff} 个游戏不一样（见上）"))
    txt = "\n".join(lines) + "\n"
    (data / "logs").mkdir(parents=True, exist_ok=True)
    (data / "logs" / "migrate-schedule.txt").write_text(txt, encoding="utf-8")
    return txt
