"""MaaFramework 任务执行器。

由「游戏日常管家」启动，用各 MAA 项目自带的 python.exe 运行（保证 maafw 版本与项目一致）。
逐个任务执行，每个任务有超时和卡住检测，失败/卡住后先恢复再重试。
不修改 MAA 项目的任何文件；日志与出错截图写到管家自己的数据目录。

输入：一个 job JSON 文件（由管家生成）。
输出：stdout 每行一个 JSON 事件，供管家实时读取；结束时输出 summary 事件。
"""
from __future__ import annotations

import json
import re
import os
import struct
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

EMIT_LOCK = threading.Lock()


def emit(kind: str, **data):
    data = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": kind, **data}
    with EMIT_LOCK:
        print(json.dumps(data, ensure_ascii=False), flush=True)


try:
    from maa.agent_client import AgentClient
    from maa.context import ContextEventSink
    from maa.controller import AdbController
    from maa.event_sink import NotificationType
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.toolkit import Toolkit
except Exception as e:  # 没用项目自带的 python 启动
    emit("fatal", reason=f"无法导入 maafw：{e}。请用 MAA 项目自带的 python.exe 运行。")
    sys.exit(2)


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 管家文件夹：和管家共用信号约定
from butler.signals import parse as parse_signal  # noqa: E402


LOOP_NODES = 8    # 原地打转：最近一段时间里来回的节点不超过这么多个
LOOP_HITS = 40    # 并且其中一个做了这么多次（10 分钟 40 次 = 15 秒一圈）


class Progress(ContextEventSink):
    """记录最近一次「有进展」的时间（识别命中或执行动作），以及脚本输出的 focus 提示。"""

    def __init__(self):
        super().__init__()
        self.last = time.monotonic()
        self.last_node = ""
        self.focus: list[str] = []
        self.hits: deque = deque(maxlen=400)  # (时间, 节点名)
        self.seen: set[str] = set()            # 本任务里识别命中/执行过的全部节点名（判断 Flag 用）
        self.acts: deque = deque(maxlen=5000)  # (时间, 节点名)：动作做完的节点，判断「原地打转」用（11-04）

    def _touch(self, name, focus):
        self.last = time.monotonic()
        self.last_node = name
        self.hits.append((self.last, name))
        self.seen.add(name)
        if focus:
            text = focus if isinstance(focus, str) else json.dumps(focus, ensure_ascii=False)
            if not self.focus or self.focus[-1] != text:
                self.focus.append(text[:300])
                emit("focus", text=text[:300])  # 管家实时显示「正在做什么」

    key_nodes: set = set()   # 留证：这些节点动作完成后截一张图（1.2 秒后，等画面切过去）
    key_now: set = set()     # 留证：这些节点一认出来就截（画面就是认出来的那一页，例如深空的日程奖励页；写成「节点@识别」）
    key_done: set = set()    # 这次任务已经截过的（repeat 的节点只截一次）
    on_key = None

    def set_keys(self, names):
        self.key_nodes = {n for n in names if not n.endswith("@识别")}
        self.key_now = {n[:-3] for n in names if n.endswith("@识别")}
        self.key_done = set()

    def on_node_action(self, context, noti_type, detail):
        self._touch(detail.name, getattr(detail, "focus", None))
        if noti_type == NotificationType.Succeeded:
            self.acts.append((time.monotonic(), detail.name))
        if noti_type == NotificationType.Succeeded and detail.name in self.key_nodes and self.on_key:
            threading.Timer(1.2, self.on_key, args=(detail.name,)).start()  # 等画面切过去再截

    ad_nodes: set = set()    # 开屏活动海报：这些节点一认出来（点掉之前）就用 adb 截一张原图（11-02）
    on_ad = None

    def on_node_recognition(self, context, noti_type, detail):
        # 只把「识别成功」算作进展；识别失败会一直刷，不能算
        if noti_type == NotificationType.Succeeded:
            self._touch(detail.name, getattr(detail, "focus", None))
            if detail.name in self.ad_nodes and self.on_ad:
                threading.Thread(target=self.on_ad, args=(detail.name,), daemon=True).start()  # 节点有 pre_delay，趁海报还在截
            if detail.name in self.key_now and detail.name not in self.key_done and self.on_key:
                self.key_done.add(detail.name)
                self.on_key(detail.name)

    def reset(self):
        self.last = time.monotonic()
        self.last_node = ""
        self.focus = []
        self.hits.clear()
        self.acts.clear()
        self.seen = set()

    def looping(self, window_s: float) -> str:
        """原地打转（11-04）：最近 window_s 秒里只在几个节点之间来回（≤ LOOP_NODES 个），其中一个做了 ≥ LOOP_HITS 次
        （平均 15 秒以内就转一圈）。画面一直在变，看画面判不出卡住——代号鸢「心纸营建」进历险 → 关弹窗 → 返回 → 再进，
        10 秒一圈转了 90 分钟。返回说明（空 = 没打转）。刷体力这类正常的重复一圈要一分钟以上，到不了这个次数。"""
        now = time.monotonic()
        if not self.acts or now - self.acts[0][0] < window_s:  # 这一项跑得还不够久（或刚重置）
            return ""
        recent = [n for t, n in self.acts if now - t <= window_s]
        if not recent:
            return ""
        from collections import Counter
        c = Counter(recent)
        top, hits = c.most_common(1)[0]
        still = any(n == top for t, n in self.acts if now - t <= 60)  # 现在还在转（最近一分钟里还做过它）
        if still and len(c) <= LOOP_NODES and hits >= LOOP_HITS:
            return f"{window_s / 60:g} 分钟里一直在重复同样几步（{'、'.join(n for n, _ in c.most_common(4))}），「{top}」做了 {hits} 次，没有进展"
        return ""

    def looping(self, window_s: int) -> list[str] | None:
        """最近 window_s 秒里命中很多次、却只在 1–2 个节点之间打转 → 判为原地循环。"""
        now = time.monotonic()
        recent = [n for t, n in self.hits if now - t <= window_s]
        if len(recent) >= 10 and self.hits and now - self.hits[0][0] >= window_s:
            names = sorted(set(recent))
            if len(names) <= 2:
                return names
        return None


class Runner:
    def __init__(self, job: dict):
        self.job = job
        self.project = Path(job["project_dir"])
        self.data_dir = Path(job["data_dir"])
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.agent_proc: subprocess.Popen | None = None
        self.agent: AgentClient | None = None
        self.agents: list = []
        self.signal = ""          # 脚本信号：fuse / manual
        self.halt_reason = ""     # [GB_MANUAL] / [GB_PAUSE]：这个游戏后面的任务不跑了
        self.agent_procs: list = []
        self.progress = Progress()
        self.stop_file = job.get("stop_file") or ""
        self.skip_file = job.get("skip_file") or ""  # 管家只在这个游戏跑的时候写，跑之前清掉
        self.abort_reason = ""
        self.shots: list[str] = []
        self.evidence: list[str] = []
        self.notes: list[str] = []
        self.progress.on_key = lambda node: self.evidence_shot(node)
        self.progress.on_ad = self.ad_shot
        self.ads: list = []  # [(numpy BGR 原图, 节点名)]

    def evidence_shot(self, tag: str) -> str:
        """留证截图：存到 data/evidence/<游戏日>/<游戏>/，文件名带任务名（报告按它找）。"""
        d = self.job.get("evidence_dir")
        if not d:
            return ""
        task = getattr(self, "cur_task", "") or tag
        safe = lambda x: re.sub(r'[\\/:*?"<>|\s]+', "_", x)[:40]
        out = Path(d) / f"{time.strftime('%H%M%S')}_{safe(task)}_{safe(tag) if tag != task else 'end'}.png"
        if self._shot(out, "留证截图"):
            self.evidence.append(str(out))
            return str(out)
        return ""

    def ad_shot(self, node: str):
        """开屏活动海报（时绘每天第一次进游戏弹的那几张）：adb 截原始分辨率的画面，任务结束后再识字、存起来当题图。"""
        try:
            import numpy
            c = self.job["controller"]
            if c.get("type", "adb") != "adb":
                return
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            raw = subprocess.run([c["adb_path"], "-s", c["address"], "exec-out", "screencap"],
                                 capture_output=True, timeout=10, creationflags=flags).stdout
            w, h = struct.unpack("<II", raw[:8])
            body = raw[len(raw) - w * h * 4:]
            if w * h == 0 or len(body) != w * h * 4:
                return
            img = numpy.frombuffer(body, dtype=numpy.uint8).reshape(h, w, 4)[:, :, 2::-1].copy()  # RGBA → BGR
            if self.ads and img.shape == self.ads[-1][0].shape and \
                    float(numpy.abs(img[::8, ::8].astype(int) - self.ads[-1][0][::8, ::8]).mean()) < 6:
                return  # 同一张（上一下没点掉又认了一次）
            self.ads.append((img, node))
        except Exception as e:
            emit("warn", msg=f"开屏海报截图失败：{type(e).__name__}: {e}")

    def save_ads(self, out_dir: str):
        """把这次截到的开屏海报识字、存到 data/news/ingame/<游戏>_ads.json（活动日历按字配给同名活动当题图）。"""
        if not self.ads or not out_dir:
            return
        sys.path.insert(0, str(Path(__file__).parent))
        import notice_reader as NR
        from maa.pipeline import JOCR, JRecognitionType
        game = self.job.get("game", "")
        out = Path(out_dir) / f"{game}_ads"
        out.mkdir(parents=True, exist_ok=True)
        idx = Path(out_dir) / f"{game}_ads.json"
        try:
            old = json.loads(idx.read_text(encoding="utf-8")).get("items", [])
        except Exception:
            old = []
        day = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))
        new = []
        for k, (img, node) in enumerate(self.ads):
            h, w = img.shape[:2]
            try:
                d = self.tasker.post_recognition(JRecognitionType.OCR, JOCR(roi=(0, 0, w, h)), img).wait().get()
                n = d.nodes[0] if d and d.nodes else None
                text = "".join(r.text for r in (n.recognition.all_results if n and n.recognition else []) if r.score >= 0.5)
            except Exception:
                text = ""
            bb = NR.banner_box(img, (0, 0, w, h))  # 海报四周压暗：找出海报本身那一块
            crop = img[bb[1]:bb[1] + bb[3], bb[0]:bb[0] + bb[2]] if bb and bb[2] * bb[3] > w * h * 0.2 else img
            name = f"{time.strftime('%m%d%H%M%S')}_{k}.png"
            (out / name).write_bytes(NR.png_bytes(crop))
            new.append({"banner": name, "text": text[:400], "day": day, "node": node, "size": [int(crop.shape[1]), int(crop.shape[0])]})
        keep = (new + old)[:40]  # 最近 40 张；同样的字只留最新的
        seen, items = set(), []
        for it in keep:
            key = re.sub(r"\W", "", it.get("text", ""))[:60] or it["banner"]
            if key not in seen:
                seen.add(key)
                items.append(it)
        for f in out.glob("*.png"):
            if f.name not in {x["banner"] for x in items}:
                f.unlink()
        idx.write_text(json.dumps({"game": game, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
        emit("info", msg=f"开屏活动海报：截了 {len(new)} 张（活动日历会按海报上的字配给同名活动当题图）")
        Path(out_dir).parent.joinpath("refresh.flag").touch()
        self.ads = []

    def _shot(self, out: Path, what: str) -> bool:
        """截一张当前画面存到 out。失败在运行记录里写一句原因（不影响任务结果）。"""
        try:
            self._grab(out)
            return True
        except Exception as e:
            emit("warn", msg=f"{what}失败：{type(e).__name__}: {e}")
            return False

    def _grab(self, out: Path):
        out.parent.mkdir(parents=True, exist_ok=True)
        c = self.job["controller"]
        if c.get("type", "adb") == "adb":  # adb 直接截原图（框架的截图是缩小过的）
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            png = subprocess.run([c["adb_path"], "-s", c["address"], "exec-out", "screencap", "-p"],
                                 capture_output=True, timeout=20, creationflags=flags).stdout
            if png[:4] != b"\x89PNG":
                raise RuntimeError("adb 截图返回的不是图片" + (f"：{png[:80]!r}" if png else "（空）"))
            out.write_bytes(png)
            return
        if not self.controller.post_screencap().wait().succeeded:
            raise RuntimeError("框架截图失败")
        img = self.controller.cached_image
        import zlib, struct
        h, w = img.shape[:2]
        rgb = img[:, :, ::-1].tobytes() if img.ndim == 3 else img.tobytes()
        raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                        chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))

    def skip_scope(self) -> str:
        """管家写的跳过请求：task = 只跳过手上这一项（11-02：在执行器里直接跳，接着跑下一项，不重开游戏）；game = 这个游戏剩下的都不跑。"""
        if not self.skip_file or not os.path.exists(self.skip_file):
            return ""
        try:
            return json.load(open(self.skip_file, encoding="utf-8")).get("scope") or "game"
        except Exception:
            return "game"

    def stop_requested(self) -> bool:
        return bool(self.stop_file and os.path.exists(self.stop_file)) or self.skip_scope() == "game"

    # ---------- 初始化 ----------
    def setup(self) -> bool:
        Toolkit.init_option(str(self.data_dir))
        try:
            Tasker.set_save_on_error(True)
        except Exception as e:  # 老版本框架没有这个选项：出错时不会自动存截图
            emit("warn", msg=f"框架不支持「出错时存截图」：{type(e).__name__}: {e}")

        self.resource = Resource()
        for p in self.job["resource_paths"]:
            path = (self.project / p).resolve()
            if not self.resource.post_bundle(str(path)).wait().succeeded:
                emit("fatal", reason=f"资源加载失败：{path}")
                return False
        emit("info", msg="资源已加载")

        if self.job.get("agent") and not self.start_agent():
            return False

        c = self.job["controller"]
        for attempt in range(1, 4):
            try:
                self.controller = self.make_controller(c)
            except Exception as e:
                emit("warn", msg=f"创建控制器失败：{e}")
                self.controller = None
            if self.controller is not None and self.controller.post_connection().wait().succeeded and self.screencap_ok():
                emit("info", msg=f"已连接 {c.get('address') or '游戏窗口'}")
                break
            emit("warn", msg=f"连接或截图失败（第 {attempt} 次），10 秒后重试")
            time.sleep(10)
        else:
            emit("fatal", reason=f"无法连接或截图为空：{c.get('address') or c.get('window_regex')}")
            return False

        self.tasker = Tasker()
        self.tasker.bind(self.resource, self.controller)
        self.tasker.add_context_sink(self.progress)
        for ag in self.agents:
            if hasattr(ag, "register_sink"):
                try:
                    ag.register_sink(self.resource, self.controller, self.tasker)
                except Exception as e:
                    emit("warn", msg=f"扩展进程收不到框架事件（进度显示可能不全）：{type(e).__name__}: {e}")
        if not self.tasker.inited:
            emit("fatal", reason="Tasker 初始化失败")
            return False
        return True

    def make_controller(self, c: dict):
        if c.get("type", "adb") == "win32":  # 电脑端游戏（剑三无界预留）：按窗口类名/标题找窗口
            import re as _re
            from maa.controller import Win32Controller
            from maa.define import MaaWin32InputMethodEnum as IM, MaaWin32ScreencapMethodEnum as SM
            wins = [w for w in Toolkit.find_desktop_windows()
                    if (not c.get("class_regex") or _re.search(c["class_regex"], w.class_name or ""))
                    and (not c.get("window_regex") or _re.search(c["window_regex"], w.window_name or ""))]
            if not wins:
                raise RuntimeError("没有找到游戏窗口（游戏开着吗？）")
            pick = lambda enum, v: int(v) if str(v).isdigit() else int(getattr(enum, str(v)))
            return Win32Controller(wins[0].hwnd, pick(SM, c.get("screencap", "FramePool")),
                                   pick(IM, c.get("mouse", "Seize")), pick(IM, c.get("keyboard", "Seize")))
        return AdbController(c["adb_path"], c["address"], c["screencap_methods"], c["input_methods"], c.get("config", {}))

    def screencap_ok(self) -> bool:
        try:
            job = self.controller.post_screencap().wait()
            if not job.succeeded:
                return False
            img = self.controller.cached_image
            return img is not None and getattr(img, "size", 0) > 0 and img.max() > 0
        except Exception:
            return False

    def alive(self) -> bool:
        """还能截图吗？不能就重连三次（每次隔 10 秒）。"""
        if self.screencap_ok():
            return True
        for i in range(3):
            emit("warn", msg=f"截图失败，重新连接模拟器（第 {i + 1} 次）")
            try:
                if self.controller.post_connection().wait().succeeded and self.screencap_ok():
                    emit("info", msg="已重新连上")
                    return True
            except Exception as e:
                emit("warn", msg=f"重新连接出错：{type(e).__name__}: {e}")
            time.sleep(10)
        return False

    def start_agent(self) -> bool:
        """扩展进程（Agent）：interface.json 里可以是一个或多个（v2 数组）。"""
        agents = self.job["agent"] if isinstance(self.job["agent"], list) else [self.job["agent"]]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        for k, a in enumerate(agents):
            if not a or not a.get("child_exec"):
                continue
            client = AgentClient(a["identifier"]) if a.get("identifier") else AgentClient()
            client.bind(self.resource)
            ident = client.identifier
            exe = a["child_exec"].replace("{PROJECT_DIR}", str(self.project))
            args = [x.replace("{PROJECT_DIR}", str(self.project)) for x in a.get("child_args", [])]
            proc = subprocess.Popen([exe, *args, ident], cwd=str(self.project), creationflags=flags,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.agent_procs.append(proc)
            try:
                client.set_timeout(int(self.job.get("agent_timeout_s", 120)) * 1000)
            except Exception as e:
                emit("warn", msg=f"框架不支持设置扩展进程超时（按框架默认）：{type(e).__name__}: {e}")
            if not client.connect():
                emit("fatal", reason=f"Agent 连接失败{f'（第 {k + 1} 个）' if len(agents) > 1 else ''}")
                return False
            self.agents.append(client)
        self.agent = self.agents[0] if self.agents else None
        self.agent_proc = self.agent_procs[0] if self.agent_procs else None
        emit("info", msg=f"Agent 已连接{f'（{len(self.agents)} 个）' if len(self.agents) > 1 else ''}")
        return True

    # ---------- 执行 ----------
    def screen_sig(self):
        """画面的粗略指纹：框架最近一张截图缩成 32×18 的灰度（不额外截图）。拿不到返回 None。"""
        try:
            img = self.controller.cached_image
            if img is None or not getattr(img, "size", 0):
                return None
            h, w = img.shape[:2]
            ys = [int((i + 0.5) * h / 18) for i in range(18)]
            xs = [int((j + 0.5) * w / 32) for j in range(32)]
            g = img[ys][:, xs]
            return g.mean(axis=2) if g.ndim == 3 else g.astype(float)
        except Exception:
            return None

    def run_entry(self, entry: str, override: dict, timeout_s: int, stall_s: int) -> tuple[str, str]:
        """返回 (结果, 说明)。结果：succeeded / failed / timeout / stalled / stopped。
        stall_s > 0 = 卡死处理开着（11-01 定）：画面 stall_s 秒没有变化 → 卡住（stalled），之后重启游戏、按重试次数再跑；
        这时不用每项的固定最长时间，timeout_s 只是兜底。stall_s = 0：不判卡死，只看每项的最长时间。"""
        self.progress.reset()
        job = self.tasker.post_task(entry, override)
        start = time.monotonic()
        sig, changed, last_look = None, start, 0.0
        while True:
            if job.done:
                if job.succeeded:
                    return "succeeded", ""
                shot = self.snapshot(entry)
                if shot:
                    emit("info", msg=f"已截图：{shot}")
                return "failed", ""
            if self.stop_requested():
                self.stop()
                return "stopped", "已手动停止" if os.path.exists(self.stop_file or "\0") else "已跳过"
            if self.skip_scope() == "task":  # 跳过手上这一项：停下它，记成已跳过，接着跑下一项
                self.stop()
                try:
                    os.remove(self.skip_file)
                except OSError:
                    pass
                self.skipped_now = True
                return "stopped", "已跳过"
            now = time.monotonic()
            if now - start > timeout_s:
                shot = self.snapshot(entry)
                if shot:
                    emit("info", msg=f"已截图：{shot}")
                self.stop()
                return "timeout", f"超过 {timeout_s / 60:g} 分钟未完成"
            if stall_s and now - last_look >= 15:  # 每 15 秒看一眼画面有没有变
                last_look = now
                loop = self.progress.looping(stall_s)
                if loop:  # 画面在变，但脚本在几个节点之间原地打转：同样算卡住（11-04）
                    shot = self.snapshot(entry)
                    if shot:
                        emit("info", msg=f"已截图：{shot}")
                    self.stop()
                    return "stalled", loop
                cur = self.screen_sig()
                if cur is not None:
                    if sig is None or cur.shape != sig.shape or float(abs(cur - sig).mean()) > 1.5:
                        sig, changed = cur, now
                    elif now - changed > stall_s:  # 画面这么久没有变化：算卡住，交给下面重启游戏、按重试次数再跑（11-01）
                        shot = self.snapshot(entry)
                        if shot:
                            emit("info", msg=f"已截图：{shot}")
                        self.stop()
                        return "stalled", f"画面 {stall_s / 60:g} 分钟没有变化"
            time.sleep(2)

    def read_notice(self, t: dict) -> tuple[str, str]:
        """读游戏内公告栏，结果存到 data/news/ingame/，活动日历下次读取时并进去。"""
        sys.path.insert(0, str(Path(__file__).parent))
        import notice_reader
        game = t["entry"].split(":", 1)[1]
        try:
            res, why = notice_reader.run(game, self.controller, self.tasker, t.get("notice_out", ""),
                                         log=lambda m: emit("info", msg=m), stop=self.stop_requested,
                                         package=(self.job.get("recovery") or {}).get("package", ""))
        except Exception as e:
            shot = self.snapshot(t["name"])
            return "failed", f"读公告出错：{type(e).__name__}: {e}" + (f"（截图 {shot}）" if shot else "")
        if res == "failed":
            shot = self.snapshot(t["name"])
            if shot:
                emit("info", msg=f"已截图：{shot}")
        if res == "succeeded":  # 让管家马上重新整理活动日历
            Path(t["notice_out"]).parent.joinpath("refresh.flag").touch()
        return res, why

    def read_events(self, t: dict) -> tuple[str, str]:
        """活动中心：用 MAA 项目自己的流程走到「活动中心」（处理弹窗、从主界面进），每个活动截一张整页图，再回主界面。"""
        sys.path.insert(0, str(Path(__file__).parent))
        import notice_reader
        game = t["entry"].split(":", 1)[1]
        conf = notice_reader.EVENTS.get(game)
        if not conf:
            return "failed", f"还不支持读这个游戏的活动中心：{game}"
        try:
            res, why = self.run_entry(conf["entry"], conf["override"], 240, 120)
            if res not in ("succeeded",):
                shot = self.snapshot(t["name"])
                return ("stopped", "已手动停止") if res == "stopped" else ("failed", f"没走到活动中心（{why}）" + (f"（截图 {shot}）" if shot else ""))
            res, why = notice_reader.run_events(game, self.controller, self.tasker, t.get("notice_out", ""),
                                                log=lambda m: emit("info", msg=m), stop=self.stop_requested)
        except Exception as e:
            shot = self.snapshot(t["name"])
            return "failed", f"读活动中心出错：{type(e).__name__}: {e}" + (f"（截图 {shot}）" if shot else "")
        finally:
            try:
                if not self.stop_requested() and conf.get("home"):
                    self.run_entry(conf["home"], {}, 90, 60)  # 回主界面，后面的任务接着跑
            except Exception:
                pass
        if res == "succeeded":
            Path(t["notice_out"]).parent.joinpath("refresh.flag").touch()
        return res, why

    def read_gacha(self, t: dict) -> tuple[str, str]:
        """读抽卡资源：点进卡池界面识别顶栏数字，结果用 reading 事件交给管家。"""
        sys.path.insert(0, str(Path(__file__).parent))
        import gacha_reader
        game = t["entry"].split(":", 1)[1]
        try:
            res, why, vals = gacha_reader.run(game, self.controller, self.tasker, t.get("gacha_conf") or {},
                                              log=lambda m: emit("info", msg=m), stop=self.stop_requested,
                                              out_dir=str(self.data_dir / "gacha"))
        except Exception as e:
            shot = self.snapshot(t["name"])
            return "failed", f"读抽卡资源出错：{type(e).__name__}: {e}" + (f"（截图 {shot}）" if shot else "")
        if vals:
            emit("reading", values=vals, src="ocr")
        if res == "failed":
            shot = self.snapshot(t["name"])
            if shot:
                emit("info", msg=f"已截图：{shot}")
        return res, why

    def snapshot(self, tag: str) -> str:
        """卡住 / 失败时截一张当前画面存到管家数据目录，便于事后查看停在哪个界面。"""
        safe = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in tag)[:40]
        out = self.data_dir / "stuck" / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}.png"
        if self._shot(out, "截图"):
            self.shots.append(str(out))
            return str(out)
        return ""

    def note(self, msg: str):
        """恢复 / 收尾过程中出的错：先记着，这一项最后没做成才附在失败原因后面。"""
        self.notes.append(msg)

    def stop(self):
        try:
            job = self.tasker.post_stop()
            t0 = time.monotonic()
            while not job.done and time.monotonic() - t0 < 60:
                time.sleep(1)
            if not job.done:
                self.note("停止任务 60 秒没停下")
        except Exception as e:
            self.note(f"停止任务失败：{type(e).__name__}: {e}")

    def recover(self, hard: bool):
        rec = self.job.get("recovery") or {}
        presses = int(rec.get("back_presses", 1)) if self.job["controller"].get("type", "adb") == "adb" else 0
        for _ in range(presses):
            try:
                self.controller.post_click_key(4).wait()  # Android 返回键，关掉挡住画面的弹窗
                time.sleep(1.5)
            except Exception as e:
                self.note(f"按返回键失败：{type(e).__name__}: {e}")
                break
        if hard and rec.get("package"):
            emit("info", msg="强制关闭游戏后重新启动")
            try:
                self.controller.post_stop_app(rec["package"]).wait()
                time.sleep(3)
            except Exception as e:
                self.note(f"强制关闭游戏失败：{type(e).__name__}: {e}")
        if rec.get("entry"):
            res, why = self.run_entry(rec["entry"], rec.get("override", {}), rec.get("timeout_s", 480), rec.get("stall_s", 240))
            emit("recovery", result=res, detail=why)
            if res not in ("succeeded", "stopped") and not hard and rec.get("package"):
                # 11-07：恋与深空停在「是否离开家园？」弹窗上，按返回、走启动流程都过不去，之后每项都「重新进游戏没成功」。
                # 不强关的恢复没成功 → 再强关游戏重来一次
                return self.recover(hard=True)
            if res != "succeeded":
                self.note(f"重新进游戏没成功（{res}{'：' + why if why else ''}）")

    def run(self) -> int:
        results = []
        if not self.setup():
            emit("summary", ok=False, results=results)
            return 1
        stopped = False
        tasks = self.job["tasks"]
        stuck: list[int] = []  # 卡住 / 超时、重启游戏重跑也没做成的：等这个游戏别的任务跑完，最后再跑一次
        for idx, t in enumerate(tasks):
            if self.stop_requested():
                stopped = True
                break
            yf = self.job.get("yield_file") or ""
            if idx and yf and os.path.exists(yf):  # 有赶时段的任务（11-02）：手上这一项做完了，剩下的交回管家排
                emit("info", msg="让出给赶时段的任务，这个游戏剩下的稍后接着跑")
                stopped = True
                break
            final, stopped = self.run_task(t, last=idx + 1 == len(tasks))
            results.append(final)
            if stopped:
                break
            if t.get("startup") and final and final["result"] not in ("succeeded", "exhausted"):
                # 游戏没启动起来（例如 10-26 未定被 B 服的隐私协议弹窗挡住）：后面的任务跑了也是白跑
                why = f"没有跑：启动游戏没成功（{final['detail'] or final['result']}）"
                emit("warn", msg=why + "，这个游戏后面的任务这次不跑")
                for rest in tasks[idx + 1:]:
                    emit("task_end", task=rest["name"], attempt=0, result="failed", detail=why, minutes=0, focus=[],
                         flags=[], shots=[])
                    results.append({"task": rest["name"], "result": "failed", "detail": why, "attempts": 0, "minutes": 0,
                                    "focus": [], "flags": [], "shots": []})
                break
            if final and final["result"] in ("stalled", "timeout") and not (final["result"] == "stalled" and t.get("stall_skip")):
                stuck.append(len(results) - 1)
        for k in stuck:
            if stopped or self.abort_reason or self.stop_requested():
                stopped = stopped or self.stop_requested()
                break
            t = next(x for x in tasks if x["name"] == results[k]["task"])
            emit("info", msg=f"「{t['name']}」前面卡住了，放到最后再跑一次")
            self.notes = []
            self.recover(hard=True)
            final, stopped = self.run_task(t, last=True, once=True, attempt0=results[k]["attempts"])
            if final:
                results[k] = final
        results = [r for r in results if r]
        ok = (not stopped) and all(r["result"] in ("succeeded", "exhausted") for r in results)
        emit("summary", ok=ok, stopped=stopped and not self.signal, results=results,
             aborted=bool(self.abort_reason), abort_reason=self.abort_reason,
             **({"signal": self.signal, "signal_reason": self.abort_reason or self.halt_reason} if self.signal else {}))
        return 0

    def run_task(self, t: dict, last: bool, once: bool = False, attempt0: int = 0) -> tuple[dict | None, bool]:
        """跑一个任务（含重试）。返回 (最后一次的结果, 是否要停下整个游戏)。
        once：最后补跑的那一次，只跑一遍、不再重试。attempt0：之前已经跑过几次（第几次接着往下数）。"""
        name = t["name"]
        attempts = 1 + int(t.get("retries", 2))
        if t.get("restart_on_fail") and not t.get("retry_on_fail", True):
            attempts = max(attempts, 1 + int(t.get("fail_retries", 1)))
        if once:
            attempts = 1
        final = None
        stopped = False
        if not once:  # 最后补跑那次：接着用补跑前恢复时记下的
            self.notes = []
        self.skipped_now = False  # 11-07：上一项收尾（重开游戏）时点的「跳过当前任务」不带到这一项
        for i in range(1, attempts + 1):
            n = attempt0 + i
            if i > 1 and getattr(self, "skipped_now", False):
                # 11-07：没做成后在「重开游戏、准备重试」时点了跳过当前任务 → 这一项就此跳过，不再跑第 2 次
                self.skipped_now = False
                final = {**final, "result": "stopped", "detail": "已跳过"}
                emit("task_end", task=name, attempt=n - 1, result="stopped", detail="已跳过", minutes=final.get("minutes", 0),
                     focus=final.get("focus", []), flags=final.get("flags", []), shots=final.get("shots", []))
                return final, False
            emit("task_start", task=name, attempt=n)
            t0 = time.monotonic()
            self.shots = []
            self.evidence = []
            self.cur_task = name
            self.progress.set_keys(t.get("evidence_nodes", []))
            self.progress.ad_nodes = set(t.get("ad_nodes", []))
            if t["entry"].startswith("@notice:"):  # 管家自己的任务：读游戏内公告栏（不经过 MAA 的流程）
                res, why = self.read_notice(t)
                self.progress.reset()
            elif t["entry"].startswith("@events:"):  # 管家自己的任务：活动中心每个活动截一张图（题图用）
                res, why = self.read_events(t)
                self.progress.reset()
            elif t["entry"].startswith("@gacha:"):  # 管家自己的任务：读抽卡资源（只看顶栏数字）
                res, why = self.read_gacha(t)
                self.progress.reset()
            else:
                res, why = self.run_entry(t["entry"], t.get("override", {}), t["timeout_s"], t["stall_s"])
            mins = round((time.monotonic() - t0) / 60, 1)
            if self.ads:
                time.sleep(1.5)  # 最后一张的截图线程收尾
                try:
                    self.save_ads(t.get("notice_out", ""))
                except Exception as e:
                    emit("warn", msg=f"开屏海报没存成：{type(e).__name__}: {e}")
            focus = list(self.progress.focus)
            seen = set(self.progress.seen)
            if not t["entry"].startswith(("@notice:", "@gacha:", "@events:")):
                res, why = self.judge(t, res, why, focus, seen)
            rules = t.get("judge") or {}
            marks = set(rules.get("fail", [])) | {e["match"] for e in rules.get("success", []) if e.get("match")}
            flags = sorted(x for x in seen if x in marks)
            if res in ("failed", "timeout", "stalled") and not self.shots and not t["entry"].startswith("@"):
                self.snapshot(name)  # 失败时一定留一张失败截图（卡住 / 超时的在恢复前已经截过）
            shots = list(self.shots)
            alert = next((_plain(f) for f in reversed(focus) for h in t.get("alert_hints", []) if h in f), "")
            if alert and res == "failed":
                # 例如恋与深空「活跃值未满100」：能领的已经领了，重跑也补不上，要你手动做 → 不重试，单独提醒
                res, why = "exhausted", f"能领的已领完，但{alert}"
            if t.get("evidence") and res in ("succeeded", "exhausted") and (t.get("evidence_end", True) or not self.evidence):
                self.evidence_shot(name)  # 任务结束时的画面（关键节点已经截到、又说了不要结束画面的，就不截）
            if res not in ("succeeded", "exhausted"):  # 留证只留成功的；没做成的看失败截图，过程中截的留证删掉
                for f in self.evidence:
                    try:
                        os.remove(f)
                    except OSError:
                        pass
                self.evidence = []
            ev = list(self.evidence)
            if res in ("stalled", "timeout") and not self.alive():
                # 例如 10-17 05:14 模拟器 adb 断开：之后每个任务都「4 分钟无进展」，白白跑了 3 个多小时
                self.abort_reason = "模拟器连不上了（adb 断开、截图为空），后面的任务这次不跑了，等下次运行重新启动模拟器"
                emit("abort", reason=self.abort_reason)
                why = self.abort_reason
            retry_restart = t.get("restart_on_fail") and i < 1 + int(t.get("fail_retries", 1)) and i < attempts
            if res == "failed" and not t.get("retry_on_fail", True) and not retry_restart:
                why = why or "脚本以「失败」结束（这个游戏只在卡住/超时时重试）"
            done = res in ("succeeded", "exhausted")
            more = (not done and i < attempts and res != "stopped" and not self.abort_reason and not self.halt_reason
                    and not (res == "stalled" and t.get("stall_skip"))  # 卡住后选了「跳到下一项」（调度设置）
                    and not t.get("no_retry") and (res != "failed" or t.get("retry_on_fail", True) or retry_restart))
            if not done and not more and self.notes:  # 最后没做成：把恢复过程中出的错附上
                why = (why + "；" if why else "") + "过程中：" + "；".join(dict.fromkeys(self.notes))
            # 结果写定之后再发 task_end：管家按它记当天状态
            emit("task_end", task=name, attempt=n, result=res, detail=why, minutes=mins, focus=focus[-8:],
                 flags=flags, shots=shots, **({"alert": alert} if alert else {}), **({"evidence": ev} if ev else {}))
            final = {"task": name, "result": res, "detail": why, "attempts": n, "minutes": mins,
                     "focus": focus[-8:], "flags": flags, "shots": shots, **({"alert": alert} if alert else {})}
            if getattr(self, "skipped_now", False):  # 你点了跳过当前任务：不重试、不重开游戏，直接下一项
                self.skipped_now = False
                return final, False
            if res == "stopped" or self.abort_reason or self.halt_reason:
                return final, True
            if not more:
                break
            if self.stop_requested():
                return final, True
            if res == "failed" and not t.get("retry_on_fail", True):
                # 失败后游戏常停在弹窗上：重启游戏，从这一项重新跑（前面做完的不再重复）
                emit("info", msg=f"「{name}」失败，重启游戏后从这一项重新跑")
                self.recover(hard=True)
            else:
                self.recover(hard=(i >= 2 or res in ("timeout", "stalled")))
        # 这一项最终没做成：重启游戏再跑下一项，免得停在半路的画面 / 弹窗把后面的任务也拖垮。
        # 卡住 / 超时的一律这样（画面停在哪不知道；10-26 时绘「安排日程」第 2 次卡在日程场景，下一项「出行赠礼」跟着失败）
        bad = final and final["result"] not in ("succeeded", "exhausted")
        if (bad and not last and not self.stop_requested() and not self.abort_reason
                and not (final["result"] == "stalled" and t.get("stall_skip"))
                and (t.get("restart_on_fail") or final["result"] in ("stalled", "timeout"))):
            emit("info", msg=f"「{name}」没有做成，重启游戏后继续下一项")
            self.recover(hard=True)
        return final, stopped

    def judge(self, t: dict, res: str, why: str, focus: list[str], seen: set[str]) -> tuple[str, str]:
        """修正框架给出的「成功 / 失败」。依据分两类（游戏记录的 judge，见 butler/judge.py）：
        fail：命中即失败；success：命中即完成；任务自己列了的完成依据（required）一个都没命中、框架却报成功 → 失败；
        到这里还是失败的：命中标了 exhausted 的 = 完成（无可做），否则跑画面核对（verify），通过 = 完成（无可做）。
        脚本信号（[GB_*]）最优先，熔断只认信号。"""
        texts = [_plain(f) or f for f in focus]
        for f in texts:
            sg = parse_signal(f)
            if not sg:
                continue
            k, txt = sg
            if k == "fuse":
                self.abort_reason = f"熔断：{txt or '脚本发出熔断信号'}"
                self.signal = "fuse"
                emit("abort", reason=self.abort_reason, signal="fuse")
                return "failed", self.abort_reason
            if k == "manual":
                self.halt_reason = f"需要人工：{txt or '脚本要求人工处理'}"
                self.signal = "manual"
                emit("warn", msg=self.halt_reason)
                return "failed", self.halt_reason
            if k == "pause":
                self.halt_reason = f"脚本暂停：{txt}" if txt else "脚本暂停"
                return "stopped", self.halt_reason
        sigs = [x for x in (parse_signal(f) for f in texts) if x]
        if any(k == "fail" for k, _ in sigs):
            return "failed", "脚本报告失败：" + next(x for k, x in sigs if k == "fail")
        if any(k == "done" for k, _ in sigs) and res in ("succeeded", "failed"):
            return "succeeded", "脚本报告完成"
        if res not in ("succeeded", "failed"):
            return res, why
        hit = lambda m: m in seen or any(m in f for f in focus)
        rules = t.get("judge") or {}
        bad = next((m for m in rules.get("fail", []) if hit(m)), None)
        if bad:
            return "failed", f"命中失败依据「{bad}」"
        good = next((e["match"] for e in rules.get("success", [])
                     if e.get("match") and e.get("result") != "exhausted" and hit(e["match"])), None)
        if good:
            return "succeeded", f"命中完成依据「{good}」"
        required = [e for e in rules.get("success", []) if e.get("match") and e.get("required")]
        if required and res == "succeeded":
            res, why = "failed", "流程结束但没有命中完成标志"
        if res == "failed":
            none = next((e["match"] for e in rules.get("success", [])
                         if e.get("match") and e.get("result") == "exhausted" and hit(e["match"])), None)
            if none:
                return "exhausted", f"无可做内容（{none}）"
            for e in rules.get("success", []):
                if e.get("verify"):
                    vres, _ = self.run_entry(e["verify"], {}, 30, 30)
                    emit("info", msg=f"画面核对「{t['name']}」：{'通过' if vres == 'succeeded' else '未通过'}")
                    if vres == "succeeded":
                        missed = [f for f in self.progress.focus if "已错过" in f]
                        return "exhausted", ("画面确认：" + "；".join(missed)) if missed else "画面确认：今天已经做过"
        return res, why

    def close(self):
        for ag in self.agents:
            try:
                ag.disconnect()
            except Exception as e:  # 全部任务已经跑完：只写进运行记录，扩展进程下面直接结束
                emit("warn", msg=f"断开扩展进程失败：{type(e).__name__}: {e}")
        for pr in self.agent_procs:
            if pr.poll() is None:
                pr.terminate()


def _plain(text: str) -> str:
    """提示文字去掉 JSON 外壳和 [color:…] 标记，给界面上的提醒用。"""
    try:
        d = json.loads(text)
        if isinstance(d, dict):
            v = next(iter(d.values()), "")  # 只取第一条（后面常是同一句话的 toast 版本）
            text = str(v.get("content", "") if isinstance(v, dict) else v)
    except (ValueError, TypeError):
        pass
    return re.sub(r"\[/?color[^\]]*\]|<[^>]+>", "", str(text)).strip()


def main():
    if len(sys.argv) < 2:
        print("用法：python maa_runner.py <job.json>")
        return 2
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    r = Runner(job)
    try:
        return r.run()
    except Exception as e:
        emit("fatal", reason=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:])
        return 1
    finally:
        r.close()


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code or 0)
