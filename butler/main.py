"""游戏日常管家 · 命令行入口

  python gb.py web                     打开管家（网页界面 + 自动调度）
  python gb.py run <游戏> [任务…]       排进今天的队列马上跑（管家要开着）；不写任务 = 今天的计划
  python gb.py stop                    让正在进行的运行停下来
  python gb.py games                   列出挂载的游戏
  python gb.py tasks <游戏>            列出某个游戏的全部可选任务
  python gb.py enable 游戏 任务…       开启停用的任务（disable 反过来）；记在 data/task_overrides/
  python gb.py scheduler [on|off]      查看 / 开关自动调度（管家要开着）
  python gb.py push [test|now]         微信推送：发测试消息 / 立刻推当天汇总
  python gb.py news [fetch]            活动日历：读一遍各游戏官方公告 / 看各来源上次读取的结果
  python gb.py exec <请求文件>          （管家内部用）运行进程：照请求里列好的任务逐个执行
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from . import games as G
from . import settings as S
from .gamesdb import load_config
from .runstate import RunState, now_bj
from .store import DONE, RESULT_CN, Store
from .timeutil import BJ, game_day

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------------------------------------------------------- 运行上下文
class RunContext:
    """一个游戏一次运行：写 jsonl 记录、实时显示、把任务结果写进当天状态、更新 running.json。"""

    def __init__(self, cfg, gid, day, store: Store, rs: RunState):
        self.cfg, self.gid, self.day, self.store, self.rs = cfg, gid, day, store, rs
        data = Path(cfg["machine"]["data_dir"])
        now = datetime.now(BJ)
        self.stamp = now.strftime("%Y%m%d-%H%M%S")
        run_dir = data / "runs" / self.stamp[:8]
        run_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = run_dir / f"{gid}-{self.stamp}.jsonl"
        self.log = open(self.log_path, "w", encoding="utf-8")
        self.stop_file = str(rs.stop_path)
        self.skip_file = str(rs.skip_path)  # 跳过：只对正在跑的这个游戏算停止
        self.cur = None
        self.got_summary = False
        self.write({"ts": now.strftime("%Y-%m-%d %H:%M:%S"), "event": "meta", "game": gid,
                    "game_day": day.isoformat(), "tz": "Asia/Shanghai"})

    def write(self, ev: dict):
        self.log.write(json.dumps(ev, ensure_ascii=False) + "\n")
        self.log.flush()

    def raw(self, line: str):
        self.log.write(line + "\n")
        self.log.flush()

    def emit(self, kind: str, **data):
        self.forward({"ts": datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"), "event": kind, **data})

    def forward(self, ev: dict):
        """执行器的事件（时间是电脑本地时间）也加上北京时间，统一写记录。"""
        ev.setdefault("bj", datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"))
        self.write(ev)
        show(ev)
        k = ev.get("event")
        if k == "summary":
            self.got_summary = True
        elif k == "task_start":
            self.cur = {"game": self.gid, "task": ev["task"], "attempt": ev.get("attempt", 1), "since": ev["bj"], "focus": []}
            self.rs.update(current=self.cur)
        elif k == "reading":  # 读抽卡资源：记成读数
            from . import readings as RD
            RD.add_points(self.cfg, self.gid, ev["values"], "ocr")
        elif k == "focus" and self.cur:  # 脚本的最新提示文字（运行面板实时显示）
            self.cur["focus"] = (self.cur["focus"] + [str(ev.get("text", ""))[:200]])[-5:]
            self.rs.update(current=self.cur)
        elif k == "task_end":  # 每个任务一结束就写入当天状态（只在这里写）
            self.store.record(self.gid, self.day, [{**ev, "attempts": ev.get("attempt", 1)}])

    def set_runner(self, pid: int):
        self.rs.update(runner_pid=pid)

    def stop_requested(self) -> bool:
        return self.rs.stop_requested() or (self.rs.skip_req() or {}).get("game") == self.gid

    @staticmethod
    def is_running(exe: str) -> bool:
        from .runstate import is_running
        return is_running(exe)

    def close(self):
        self.log.close()


def show(ev: dict):
    t = (ev.get("bj") or ev.get("ts", ""))[11:]
    k = ev.get("event")
    if k == "task_start":
        print(f"[{t}] ▶ {ev['task']}" + (f"（第 {ev['attempt']} 次）" if ev.get("attempt", 1) > 1 else ""))
    elif k == "task_end":
        print(f"[{t}]   {RESULT_CN.get(ev['result'], ev['result'])} · {ev['minutes']} 分钟 {ev.get('detail', '')}")
        for f in ev.get("focus", [])[-3:]:
            print(f"            · {f[:160]}")
    elif k == "recovery":
        print(f"[{t}]   ↺ 恢复：{RESULT_CN.get(ev['result'], ev['result'])} {ev.get('detail', '')}")
    elif k in ("info", "warn"):
        print(f"[{t}] · {ev['msg']}")
    elif k == "fatal":
        print(f"[{t}] ✖ {ev['reason']}")
        if ev.get("trace"):
            print(ev["trace"])
    elif k == "abort":
        print(f"[{t}] ⛔ {ev.get('reason', '')}")


class _Printer:
    """给 after() 用的简易输出。"""

    def emit(self, kind, **data):
        print(f"· {data.get('msg') or data.get('reason', '')}")


# ---------------------------------------------------------------- 运行进程
def run_game(cfg, gid: str, items: list[dict], store: Store, rs: RunState, hires: str = "") -> dict:
    g = cfg["games"][gid]
    print(f"\n======== {g['name']} ========")
    day = game_day(g)
    print(f"· 游戏日 {day}（北京时间），{len(items)} 项")
    ctx = RunContext(cfg, gid, day, store, rs)
    ctx.hires = hires  # 「重新获取题图」：模拟器临时调高分辨率（games.hires_session）
    try:
        summary = G.adapter(cfg, gid).run(items, ctx)
        if not ctx.got_summary:  # 非 MAA 工具：补一条结束记录，运行记录里才算「已结束」
            ctx.write({"ts": now_bj(), "bj": now_bj(), "event": "summary", "ok": bool(summary.get("ok")),
                       "stopped": bool(summary.get("stopped")), "results": summary.get("results", [])})
    finally:
        ctx.close()
    if summary.get("signal") in ("fuse", "manual"):  # 熔断 / 需要人工 → 马上推送；熔断的今天不再自动跑
        from . import signals as SIG
        from .notify import send
        reason = summary.get("signal_reason") or summary.get("abort_reason") or ""
        if summary["signal"] == "fuse":
            SIG.mark_fused(cfg, gid, day, reason)
        ok, msg = send(cfg, f"{'⛔ 熔断' if summary['signal'] == 'fuse' else '✋ 需要人工'} · {g['name']}",
                       reason + ("\n今天不再自动运行这个游戏。" if summary["signal"] == "fuse" else "\n这个游戏后面的任务这次没跑。"))
        print(f"· 推送：{msg}")
    print("\n---- 结果 ----")
    if summary.get("crashed"):
        print("执行器异常退出，没有结果。详见记录：", ctx.log_path)
    for r in summary.get("results", []):
        mark = "✅" if r["result"] in DONE else ("⏹" if r["result"] == "stopped" else "❌")
        extra = f"（重试 {r['attempts'] - 1} 次）" if r.get("attempts", 1) > 1 else ""
        print(f"{mark} {r['task']}  {RESULT_CN.get(r['result'], r['result'])}{extra}  {r['minutes']} 分钟  {r.get('detail', '')}")
    print(f"完整记录：{ctx.log_path}")
    return summary


def cmd_exec(cfg: dict, req_path: str):
    """运行进程：请求文件 = {"by": 谁排的, "runs": [{"game", "batch", "items": [任务项…], "keys": [任务键…]}]}。
    照单逐个游戏执行；同一模拟器上的游戏连着跑，跑完最后一个再关模拟器。"""
    req = json.loads(Path(req_path).read_text(encoding="utf-8"))
    Path(req_path).unlink()  # 请求读完就删：要跑什么、谁排的都写进运行日志
    print(json.dumps(req, ensure_ascii=False))
    data_dir = cfg["machine"]["data_dir"]
    rs, store = RunState(data_dir), Store(data_dir)
    runs = [r for r in req["runs"] if r["game"] in cfg["games"]]
    rs.acquire([r["game"] for r in runs])
    print(f"（由{req.get('by', '')}启动）")
    rs.clear_continue()  # 新的一次运行开始：之前「停止后继续」的记录作废
    keep_awake(True)
    finished: list[dict] = []
    aborted = False
    try:
        for i, run in enumerate(runs):
            if rs.stop_requested():
                print("\n· 已收到停止请求，后面的游戏不再运行。")
                break
            gid = run["game"]
            g = cfg["games"][gid]
            rs.update(batch=run.get("batch", ""))  # 日程页按它认「正在跑的是哪一批」（同一游戏可能有好几批）
            rs.clear_skip()
            try:
                summary = run_game(cfg, gid, run["items"], store, rs, run.get("hires", ""))
                summary = skip_rest(cfg, gid, run, summary, store, rs)
            except Exception as e:  # 管家自己出错：这个游戏这次算没跑完，推送说明，接着跑下一个游戏
                import traceback
                traceback.print_exc()
                from .notify import send
                title = "运行出错 · " + g["name"]
                print("· 推送：" + send(cfg, title, f"{type(e).__name__}: {e}")[1])
                summary = {"crashed": True}
            rs.update(done_games=(rs.read_running() or {}).get("done_games", []) + [gid], current=None)
            if rs.yield_req() and not rs.stop_requested():  # 让出给赶时段的任务（11-02）：这一个和后面没开始的放回「接下来」
                give_back(cfg, store, summary, runs[i:])
                rs.clear_yield()
                finished.append(run)
                break
            if not rs.stop_requested():  # 停止请求在这个游戏跑的时候来的：它没跑完（各种工具都这样认）
                finished.append(run)
            if summary.get("aborted"):
                aborted = True
                print(f"\n⛔ {summary.get('abort_reason', '脚本要求停止全部任务')}，后面的游戏不再运行。")
                rs.request_stop(summary.get("abort_reason", "abort"))
            emu = G.emulator_of(g)
            last_on_emu = not any(G.emulator_of(cfg["games"][r["game"]]) == emu for r in runs[i + 1:])
            # 设置 → 模拟器：「每次跑完关」= 这次运行里这台模拟器上的最后一个游戏跑完就关；「一直开着」= 不关
            close = bool(emu) and last_on_emu and S.get(cfg, "emulator")["close"] == "each_run"
            G.adapter(cfg, gid).after(_Printer(), close)
            if close:
                from .mumu import MuMu
                try:
                    MuMu.of(cfg).shutdown(emu)
                    print(f"· 已关闭 MuMu 实例「{emu}」")
                except Exception as e:  # 关不掉只影响内存占用：写进运行日志，继续收尾
                    print(f"· 关闭模拟器失败：{type(e).__name__}: {e}")
        if rs.stop_requested() and not aborted:
            save_continue(cfg, rs, store, [r for r in runs if r not in finished])
    finally:
        keep_awake(False)
        rs.release()
    from .notify import after_run  # 微信推送：这次运行出了新的失败 / 提醒就推一条（没设置推送时什么都不做）
    msg = after_run(cfg, [r["game"] for r in runs])
    if msg:
        print(f"· 微信推送：{msg}")


def give_back(cfg, store: Store, summary: dict, left: list[dict]):
    """让出：还没轮到的任务放回各自的条目（日程「接下来」），由调度先跑赶时段的、再接着跑这些。"""
    from .schedule import Schedule
    from .timeutil import sched_day
    sch = Schedule(cfg)
    tried = {r.get("task") for r in summary.get("results", []) if not str(r.get("detail", "")).startswith("未运行")}
    for n, run in enumerate(left):
        g = cfg["games"][run["game"]]
        st = store.status(run["game"], game_day(g))
        keys = [k for k in run["keys"] if (n or k not in tried) and st.get(k, {}).get("result") not in DONE]
        if keys and run.get("batch"):
            try:
                sch.requeue(sched_day(), run["batch"], keys)
                print(f"· 让出：{g['name']} 还有 {len(keys)} 项放回「接下来」")
            except Exception as e:
                print(f"· 放回「接下来」没成功：{type(e).__name__}: {e}")


def skip_rest(cfg, gid: str, run: dict, summary: dict, store: Store, rs: RunState) -> dict:
    """运行条上点了「跳过当前任务」：那个任务停在那里，这个游戏这次还没轮到的任务接着跑（可以再跳）。
    「跳过当前序列」：这个游戏这次剩下的都不跑，直接下一个游戏。"""
    from .store import item_key
    g = cfg["games"][gid]
    rec = g.get("recovery_task", "")
    items = run["items"]
    while True:
        sk = rs.skip_req()
        rs.clear_skip()
        if not sk or sk.get("game") != gid or sk.get("scope") != "task" or rs.stop_requested() \
                or summary.get("aborted") or summary.get("signal"):
            return summary
        tried = {r.get("task") for r in summary.get("results", [])
                 if not str(r.get("detail", "")).startswith("未运行")} | {sk.get("task")}  # 没轮到的（BetterGI 记「未运行」）接着跑
        items = [t for t in items if t["task"] == rec or (item_key(t) not in tried and t["task"] not in tried)]
        if not any(t["task"] != rec for t in items):
            return summary
        print(f"\n· 跳过了「{sk.get('task')}」，接着跑剩下的 {sum(1 for t in items if t['task'] != rec)} 项")
        more = run_game(cfg, gid, items, store, rs)
        summary = {**more, "results": summary.get("results", []) + more.get("results", [])}


def keep_awake(on: bool):
    """运行期间不让电脑睡眠（不改电源设置，运行结束就恢复）。"""
    if os.name != "nt":
        return
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def save_continue(cfg, rs: RunState, store: Store, left: list[dict]):
    """手动停止时记下还没跑完的任务，供「继续」用（让出电脑、脚本熔断时不记）。"""
    stop = rs.stop_reason()
    if stop == "让出电脑":
        return
    games = {}
    for run in left:
        g = cfg["games"][run["game"]]
        st = store.status(run["game"], game_day(g))
        keys = [k for k in run["keys"] if st.get(k, {}).get("result") not in DONE]
        if keys:
            rt = run.get("routine", "")
            games[run["game"] + (f"#{rt}" if rt else "")] = {"game": run["game"], "keys": keys, "game_day": game_day(g).isoformat(),
                                                           "routine": rt}
    if not games:
        return
    cur = (rs.read_running() or {}).get("current") or {}
    rs.save_continue({"stopped_at": now_bj(), "source": stop, "games": games,
                      "current": {k: cur.get(k) for k in ("game", "task", "attempt")} if cur else None})
    print("· 已记下还没跑完的部分，可以在界面上点「继续」。")


# ---------------------------------------------------------------- 命令行
def api(method: str, path: str, body=None) -> dict:
    """命令行的「开始 / 开关调度」交给开着的管家做（和界面走同一条路）。"""
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(json.loads(e.read().decode("utf-8")).get("error", str(e)))
    except urllib.error.URLError:
        sys.exit("管家没开着：先打开 GameButler.exe（或 python gb.py web）")


def cmd_games(cfg: dict):
    for gid, g in cfg["games"].items():
        ok, why = G.available(g)
        print(f"  {'✔' if ok else '·'} {gid:<8} {g['name']}  [{G.KIND_NAMES.get(G.kind(g), G.kind(g))}]  {why}")


def cmd_tasks(cfg: dict, gid: str):
    ad = G.adapter(cfg, gid)
    names = ad.task_names()
    print(f"{cfg['games'][gid]['name']} · 共 {len(names)} 个任务\n")
    for name in names:
        why = ad.disabled_reason(name)
        print(f"  {name}" + (f"  〔已停用：{why}〕" if why else ""))


def _log_to(path: Path, max_mb: int = 5):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > max_mb * 1048576:
        path.replace(path.with_suffix(".old.log"))
    f = open(path, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = f


def main(argv=None):
    argv = argv or sys.argv[1:]
    cmds = ("web", "run", "stop", "games", "tasks", "enable", "disable", "scheduler", "push", "news", "exec")
    if not argv or argv[0] not in cmds or (argv[0] in ("tasks", "run", "exec") and len(argv) < 2):
        print(__doc__)
        return
    cfg = load_config()
    cmd = argv[0]
    if cmd == "web":
        log = next((a[6:] for a in argv if a.startswith("--log=")), "")
        if log:  # 由启动器 GameButler.exe 用 pythonw 启动：没有控制台，输出写进日志文件
            _log_to(Path(log))
        from .web import serve
        serve(cfg, open_browser="--no-browser" not in argv)
    elif cmd == "exec":
        cmd_exec(cfg, argv[1])
    elif cmd == "run":
        r = api("POST", "/api/schedule/today/batch", {"game": argv[1], "tasks": argv[2:]})
        print(f"已排进今天的队列：{r['batch']['game']}（{'、'.join(argv[2:]) or '今天的计划'}）")
    elif cmd == "tasks":
        cmd_tasks(cfg, argv[1])
    elif cmd == "games":
        cmd_games(cfg)
    elif cmd == "stop":  # 和界面的「停止」同一个接口：正在跑的停下，排着的也不开始，一起记进「继续」
        r = api("POST", "/api/stop", {})
        print(("已发出停止请求。" if r["running"] else "现在没有在运行。") +
              (f"排着的也不开始了：{'、'.join(r['cancelled'])}" if r["cancelled"] else ""))
    elif cmd in ("enable", "disable") and len(argv) >= 3:
        ad = G.adapter(cfg, argv[1])
        for t in argv[2:]:
            if t not in ad.task_names():
                print(f"没有这个任务：{t}")
                continue
            ad.set_task_enabled(t, cmd == "enable")
            why = ad.disabled_reason(t)
            print(f"{t}：{'已开启' if not why else '已停用（' + why + '）'}")
    elif cmd == "scheduler":
        if len(argv) > 1 and argv[1] in ("on", "off"):
            api("POST", f"/api/scheduler/{argv[1]}", {})
        st = api("GET", "/api/scheduler")
        print(f"自动调度：{'开启' if st['enabled'] else '关闭'}")
        for b in st["batches"]:
            print(f"  {b['game']} {b['id']}：" + (f"该跑 {len(b['due'])} 项" if b["due"] else b["why"]))
    elif cmd == "news":  # 活动日历：fetch [来源或游戏…] = 让管家读一遍官方公告；不带参数 = 看各来源上次的结果
        from . import news
        if len(argv) > 1 and argv[1] == "fetch":
            only = [a for a in argv[2:] if a != "--from-butler"]
            if "--from-butler" in argv:  # 管家后台开的读取进程：真正去读（同一时间只有这一个在写活动数据）
                r = news.fetch(cfg, only or None)
                print(f"共 {r['items']} 条")
            else:  # 你在命令行敲的：交给管家，和界面上的「刷新」同一条路
                r = api("POST", "/api/news/refresh", {"only": only})
                print("已让管家开始读取（结果看 data\\logs\\news.log）" if r["started"] else "管家正在读，等这次读完")
                return
        for s_ in news.load(cfg)["sources"]:
            print(f"{'✓' if s_['ok'] else '✗'} {s_['id']:<14} {s_['count']:>3} 条  {s_['fetched']}  {s_.get('error', '')}")
    elif cmd == "push":  # 微信推送：test = 发一条测试；now = 立刻推当天汇总
        from . import notify
        if len(argv) > 1 and argv[1] == "now":
            print(notify.daily(cfg, force=True))
        else:
            print(notify.send(cfg, "游戏日常管家：推送测试", "能收到这条，说明微信推送设置好了。")[1])
