"""10-25 重构的一次性迁移：把旧格式的配置和数据转成新格式。只需要跑一次，跑之前先整份备份。

用法（Python 3.11+）：python tools/migrate_20261025.py <管家文件夹>

做的事：
1. config/butler.toml 里的游戏 → config/presets/（调好的设置，以后重新挂载时套用）+ data/games/<游戏>.json（每个游戏一份记录）。
   data/games.json 里界面设过的路径 / 模拟器 / 自己添加的游戏 / 取消关注 并进记录。butler.toml 只留 [machine]。
2. 判定依据收成 judge.fail / judge.success 两类；时段只写在游戏记录的 windows 里（从 Routine / 计划的任务项上挪过来）。
3. 日程批次：闲时 / 几点开始 / 几点前完成 → 时段；计划上的 run_at 去掉。
4. 设置合并进 data/settings.json；推送状态只留 data/push_state.json。
5. 抽卡资源项写进读数文件；去掉米游社的数据；分辨率开关写进游戏记录。
6. 「继续」记录转成新格式。删掉不再使用的旧文件。
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
DATA = ROOT / "data"
OLD_TOML = ROOT / "config" / "butler.toml"
PRESETS = ROOT / "config" / "presets"


def rd(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else copy.deepcopy(default)


def wr(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def rm(p: Path):
    if p.exists():
        p.unlink()
        print(f"  删除 {p.relative_to(ROOT)}")


if (DATA / "games").exists():
    sys.exit("data/games/ 已经存在：看起来已经迁移过了")
old = tomllib.loads(OLD_TOML.read_text(encoding="utf-8"))
OV = rd(DATA / "games.json", {})

# ---------------------------------------------------------------- 预设
META = {  # 预设 id: (游戏 id, 显示名, 游戏, 仓库, 类别, 匹配, 常见文件夹, 屏幕)
    "maayuan": ("yuan", "MaaYuan", "代号鸢", "syoius/MaaYuan", "MaaFramework 项目", {"names": ["MaaYuan"]},
                ["MaaYuan"], "720×1280 竖屏（MuMu 平板 / 手机版均可）"),
    "maatot": ("tot", "MaaTOT", "未定事件簿", "Coxwtwo/MaaTOT", "MaaFramework 项目", {"names": ["MaaTOT"]},
               ["MaaTOT"], "1280×720（竖屏实例 720×1280 也行，游戏会自己横过来）"),
    "maalysk": ("lysk", "MaaLYSK", "恋与深空", "Witty36/MaaLYSK", "MaaFramework 项目", {"names": ["MaaLYSK"]},
                ["MaaLYSK"], "900×1600 竖屏，320 DPI（建议单独一个实例）"),
    "maash": ("sh", "MaaSH（时绘 MAA）", "时空中的绘旅人", "LiliiPop/MaaSH", "MaaFramework 项目", {"names": ["MaaSH"]},
              ["MaaSH", "MaaSH/app"], "1280×720（竖屏实例 720×1280 也行，游戏会自己横过来）"),
    "maajx3": ("jx3", "MaaJX3（剑三无界）", "剑网三无界", "", "MaaFramework 项目", {"names": ["MaaJX3"]}, ["MaaJX3"], "电脑端"),
    "bettergi": ("genshin", "BetterGI", "原神", "babalae/better-genshin-impact", "BetterGI", {"exe": ["BetterGI.exe"]},
                 ["BetterGI", "BetterGI/BetterGI", "Genshin Impact plugin"], "电脑端，原神要 1920×1080 窗口"),
    "m7a": ("starrail", "三月七小助手", "崩坏：星穹铁道", "moesnow/March7thAssistant", "三月七",
            {"exe": ["March7th Assistant.exe"]},
            ["March7thAssistant", "March7thAssistant_full", "March7thAssistant_full/March7thAssistant_full"],
            "电脑端，崩铁 1920×1080 窗口"),
    "m9a": ("", "M9A", "重返未来：1999", "MaaXYZ/M9A", "MaaFramework 项目", {"names": ["M9A"]}, ["M9A"], ""),
    "maa": ("", "MAA（明日方舟）", "明日方舟", "MaaAssistantArknights/MaaAssistantArknights", "明日方舟 MAA（图形界面版）",
            {}, ["MAA"], ""),
    "maacli": ("", "maa-cli", "明日方舟", "MaaAssistantArknights/maa-cli", "明日方舟 MAA（命令行版，可以逐项控制）",
               {}, ["maa-cli"], ""),
}
PERSONAL = {"project_dir", "exe", "emulator", "python", "pre_tasks", "launch_task", "launch_task_config"}
DROP = {"enabled", "note", "in_all", "deadlines", "abort_hints", "fail_hints", "fail_nodes", "success_hints",
        "success_flags", "flag_optional", "benign", "verify", "fail_means_done", "seed_name", "resolution_switch"}


def judge_of(g: dict) -> dict:
    fail = [x for x in g.get("fail_nodes", []) + g.get("fail_hints", []) if not x.startswith("[JX3_")]
    succ = {"*": [{"match": h, "required": False} for h in g.get("success_hints", [])]
                 + [{"match": b, "result": "exhausted"} for b in g.get("benign", [])]}
    opt = set(g.get("flag_optional", []))
    for task, flags in (g.get("success_flags") or {}).items():
        succ.setdefault(task, []).extend(f if task not in opt else {"match": f, "required": False} for f in flags)
    for task, node in (g.get("verify") or {}).items():
        succ.setdefault(task, []).append({"verify": node})
    out = {}
    if fail:
        out["fail"] = {"*": fail}
    succ = {k: v for k, v in succ.items() if v}
    if succ:
        out["success"] = succ
    return out


def converted(g: dict) -> dict:
    out = {k: v for k, v in g.items() if k not in DROP}
    j = judge_of(g)
    if j:
        out["judge"] = j
    if out.get("log_glob") and out.get("exe"):  # 改成相对程序所在文件夹
        base = os.path.dirname(out["exe"])
        if out["log_glob"].lower().startswith(base.lower() + "\\"):
            out["log_glob"] = out["log_glob"][len(base) + 1:]
    tasks = []
    for t in out.get("tasks", []):  # 任务清单里的时段挪到 windows
        if isinstance(t, dict) and t.get("window"):
            out.setdefault("windows", {})[t.get("key") or t["task"]] = t["window"]
            t = {k: v for k, v in t.items() if k != "window"}
        tasks.append(t)
    if "tasks" in out:
        out["tasks"] = tasks
    return out


print("1. 预设和游戏记录")
PRESETS.mkdir(parents=True, exist_ok=True)
by_gid = {}
for order, (pid, (gid, name, game, repo, kind, match, look, screen)) in enumerate(META.items()):
    p = {"id": pid, "order": order, "name": name, "game": game, "repo": repo, "kind": kind, "match": match,
         "look": look, "screen": screen}
    if gid and gid in old.get("games", {}):
        g = converted(old["games"][gid])
        p["gid"] = gid
        p["type"] = g.get("type", "maa")
        p["config"] = {k: v for k, v in g.items() if k not in PERSONAL}
        by_gid[gid] = pid
    elif pid in ("maa", "maacli"):
        p["type"] = "maa_ark"
    elif pid == "m9a":
        p["type"] = "maa"
    wr(PRESETS / f"{pid}.json", p)
    print(f"  预设 {pid}")

pcres = rd(DATA / "pcres.json", {})
n = 0
for gid, g in old.get("games", {}).items():
    if g.get("enabled", True) is False:
        print(f"  {gid}：还没接入（{g.get('note', '')}），只留预设")
        continue
    rec = converted(g)
    o = OV.get(gid) or {}
    for k in ("project_dir", "exe", "emulator"):
        if k in o:
            rec[k] = o[k]
    if rec.get("python", "").lower().endswith("gamebutler\\runtime\\python\\python.exe"):
        rec.pop("python")  # 工具没有自带 Python 时本来就用管家自带的
    rec["followed"] = o.get("followed", True) is not False and o.get("enabled", True) is not False
    rec["preset"] = by_gid.get(gid, "")
    if gid in pcres:
        rec["resolution_switch"] = bool(pcres[gid])
    n += 1
    rec["order"] = n
    wr(DATA / "games" / f"{gid}.json", rec)
    print(f"  记录 {gid}（{'挂着' if rec['followed'] else '取消挂载'}）")
for gid, o in OV.items():  # 自己添加的游戏
    if gid.startswith("_") or not isinstance(o, dict) or not isinstance(o.get("custom"), dict):
        continue
    rec = converted(o["custom"])
    rec.pop("custom", None)
    rec["followed"] = o.get("followed", True) is not False
    n += 1
    rec["order"] = n
    wr(DATA / "games" / f"{gid}.json", rec)
    print(f"  记录 {gid}（自己添加的）")
GAMES = {p.stem: rd(p) for p in (DATA / "games").glob("*.json")}

print("2. Routine / 计划里的时段、run_at")
for p in list((DATA / "routines").glob("*.json")) + list((DATA / "plans").glob("*/*.json")):
    gid = p.stem
    doc = rd(p)
    lists = [r["tasks"] for r in doc.get("routines", {}).values()] if "routines" in doc else [doc.get("tasks", [])]
    changed = False
    for lst in lists:
        for t in lst:
            if t.get("window"):
                if gid in GAMES:
                    GAMES[gid].setdefault("windows", {}).setdefault(t.get("key") or t["task"], t["window"])
                t.pop("window")
                changed = True
    if doc.pop("run_at", None) is not None:
        changed = True
    if changed:
        wr(p, doc)
        print(f"  {p.relative_to(DATA)}")
for gid, g in GAMES.items():
    wr(DATA / "games" / f"{gid}.json", g)

print("3. 日程批次")
sset = rd(DATA / "schedule" / "settings.json", {})


def is_pc(g):
    if "pc" in g:
        return bool(g["pc"])
    return g.get("type", "maa") not in ("maa", "maa_ark") or g.get("controller", "adb") != "adb"


def hm_plus(hm: str, minutes: int) -> str:
    h, m = map(int, hm.split(":"))
    t = (h * 60 + m + minutes) % 1440
    return f"{t // 60:02d}:{t % 60:02d}"


delay = int(old.get("scheduler", {}).get("start_delay_minutes", 10))


def batch(b: dict) -> dict:
    g = GAMES.get(b["game"])
    st = b.get("start") or {"mode": "idle"}
    mode = st.get("mode")
    if mode in ("now", "window") or not g:
        if mode == "window":
            st = {"mode": "window", "from": st["from"], "to": st.get("to", ""), "idle": bool(st.get("idle"))}
        return {**b, "start": st}
    first = hm_plus(g["refresh"], delay)
    if mode == "idle":
        st = {"mode": "window", "from": first, "to": "", "idle": is_pc(g) or bool(sset.get("emu_wait_idle"))}
    elif mode == "at":
        st = {"mode": "window", "from": st["at"], "to": "", "idle": False}
    elif mode == "before":
        st = {"mode": "window", "from": first, "to": st["before"], "idle": False}
    return {**b, "start": st}


tp = DATA / "schedule" / "templates.json"
if tp.exists():
    t = rd(tp)
    for tpl in t["templates"].values():
        tpl["batches"] = [batch(b) for b in tpl["batches"]]
    wr(tp, t)
    print("  templates.json")
for p in (DATA / "schedule" / "days").glob("*.json"):
    d = rd(p)
    d["once"] = [batch(b) for b in d.get("once", [])]
    wr(p, d)

print("4. 设置 / 推送状态")
sch_old = old.get("scheduler", {})
settings = {
    "scheduler": {
        "enabled": bool(rd(DATA / "scheduler" / "settings.json", {}).get("enabled", sch_old.get("enabled", False))),
        "idle_minutes": int(sset.get("idle_minutes", sch_old.get("idle_minutes", 30))),
        "idle_windows": sset.get("idle_windows", []),
        "fail_retries": int(sset.get("fail_retries", 0)),
        "retry_gap_minutes": int(sset.get("retry_gap_minutes", sch_old.get("retry_gap_minutes", 60))),
        "postpone_minutes": int(sch_old.get("postpone_minutes", 30)),
        "prompt_timeout_seconds": int(sch_old.get("prompt_timeout_seconds", 300)),
        "start_delay_minutes": delay,
    },
    "push": {k: v for k, v in {**{k: old.get("push", {}).get(k) for k in ("provider", "daily_at", "on_problem")},
                               **rd(DATA / "push.json", {})}.items() if v is not None and k in ("provider", "daily_at", "on_problem")},
    "emulator": {"mumu_dir": (OV.get("_machine") or {}).get("mumu_dir") or old["machine"].get("mumu_dir", "")},
    "news": {"interval_hours": int(old.get("news", {}).get("interval_hours", 6)), "disabled": old.get("news", {}).get("disabled", [])},
}
if (DATA / "ui.json").exists():
    settings["appearance"] = {"palette": rd(DATA / "ui.json")["palette"]}
ev = rd(DATA / "evidence.json", {})
ev_tasks = dict(ev.get("tasks", {}))
for gid, g in old.get("games", {}).items():
    if gid in GAMES and gid not in ev_tasks and g.get("evidence_default"):
        ev_tasks[gid] = g["evidence_default"]
settings["evidence"] = {"keep_days": int(ev.get("keep_days", 7)), "tasks": ev_tasks}
wr(DATA / "settings.json", settings)
print("  settings.json")
ps = rd(DATA / "push_state.json", {})
sp = rd(DATA / "scheduler" / "push.json", {})
last = max(sp.get("day", ""), ps.pop("daily_sent", ""))
if last:
    ps["daily"] = {"day": last, "ok": True, "result": "（迁移前推过）"}
wr(DATA / "push_state.json", ps)
st = rd(DATA / "scheduler" / "state.json", {})
st = {gid: {"day": x["day"], "attempts": x.get("attempts", {}), "last_run": x.get("last_run", ""),
            "postponed_until": x.get("postponed_until", "")} for gid, x in st.items() if gid in GAMES}
wr(DATA / "scheduler" / "state.json", st)

print("5. 读数 / 米游社 / 密钥")
DEFAULTS = {
    "genshin": [{"key": "原石", "per_pull": 160}, {"key": "纠缠之缘", "per_pull": 1}, {"key": "相遇之缘", "per_pull": 1, "standard": True}],
    "starrail": [{"key": "星琼", "per_pull": 160}, {"key": "星轨专票", "per_pull": 1}, {"key": "星轨通票", "per_pull": 1, "standard": True}],
}
for gid, g in GAMES.items():
    p = DATA / "readings" / f"{gid}.json"
    d = rd(p, {"defs": [], "points": []})
    d.setdefault("points", [])
    before = len(d["points"])
    d["points"] = [x for x in d["points"] if x.get("src") != "mys" and not x["key"].endswith("·本月获得")]
    if not d.get("defs"):
        d["defs"] = g.get("gacha_resources") or DEFAULTS.get(gid, [])
    if d["defs"] or d["points"]:
        wr(p, d)
        print(f"  readings/{gid}.json（去掉 {before - len(d['points'])} 条米游社读数）")
sec = rd(DATA / "secrets.json", {})
sec = {k: v for k, v in sec.items() if k == "push_token"}
wr(DATA / "secrets.json", sec)

print("6. 继续记录")
rs = rd(DATA / "resume.json", None)
if rs and isinstance(rs.get("games"), list):
    games = {}
    for gid in rs["games"]:
        day = rs["game_days"][gid]
        plan = rd(DATA / "plans" / day / f"{gid}.json", None)
        if plan is None:
            r = rd(DATA / "routines" / f"{gid}.json")
            plan = r["routines"][r["default"]]
        status = rd(DATA / "status" / day / f"{gid}.json", {})
        rec = GAMES[gid].get("recovery_task")
        keys = [(t.get("key") or t["task"]) for t in plan["tasks"] if t["task"] != rec]
        keys = [k for k in keys if status.get(k, {}).get("result") not in ("succeeded", "exhausted")]
        if rs.get("only"):
            keys = [k for k in keys if k in rs["only"]["keys"]]
        if keys:
            games[gid] = {"keys": keys, "game_day": day}
    if games:
        wr(DATA / "resume.json", {"stopped_at": rs["stopped_at"], "source": rs.get("source", ""), "games": games,
                                  "current": rs.get("current")})
        print(f"  resume.json：{games}")
    else:
        rm(DATA / "resume.json")

print("7. 旧文件")
for p in ("games.json", "push.json", "ui.json", "evidence.json", "pcres.json", "run_request.json",
          "scheduler/settings.json", "scheduler/push.json", "schedule/settings.json"):
    rm(DATA / p)
(ROOT / "config" / "butler.toml.before-20261025").write_text(OLD_TOML.read_text(encoding="utf-8"), encoding="utf-8")
m = old["machine"]
OLD_TOML.write_text(f"""# 游戏日常管家 · 这台电脑的设置
# 游戏的设置在 data/games/<游戏>.json（界面「设置 → 工具与游戏」里改）；其他设置在 data/settings.json（界面「设置」里改）。
# 常见脚本调好的设置（挂载时套用）在 config/presets/。改之前的完整配置留在 config/butler.toml.before-20261025。

[machine]
timezone = "{m['timezone']}"       # 电脑时区：只用来把脚本日志里的本地时间换算成北京时间
data_dir = '{m.get('data_dir', 'data')}'                  # 管家数据目录；相对路径 = 管家文件夹下
""", encoding="utf-8")
print("  config/butler.toml 只留 [machine]；原来的另存为 butler.toml.before-20261025")
print("完成")
