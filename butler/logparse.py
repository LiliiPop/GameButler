"""读 MaaFramework + MFAAvalonia 系脚本的日志。

两类日志：
- 运行日志 logs/log-YYYYMMDD.log：界面层记录，有「开始任务：X」「任务失败：X」「任务已全部完成」和 focus 彩色提示。
  新旧两种格式都支持（MaaTOT/MaaLYSK/MaaSH 为新格式，MaaYuan 为旧格式）。
- 框架日志 debug/maafw.log（旧版叫 maa.log）：只抽取 Tasker.Task 成败和识别命中的节点名。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime

TS_RE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\]\[(\w+)\]\s?(.*)$")
PREFIX_RE = re.compile(r"^(?:\[(?:cfg|inst|src|op)=[^\]]*\])+\s*")
START_RE = re.compile(r"^开始任务\s*[：:]\s*(.+?)\s*$")
FAIL_RE = re.compile(r"^任务失败\s*[：:]\s*(.+?)\s*$")
FOCUS_RES = [
    re.compile(r'color:\s*(\w+)\s*">(.*?)</span>'),
    re.compile(r"\[color:(\w+)\](.*?)\[/color\]"),
]
EMOJI_RE = re.compile(r"[^\w\u4e00-\u9fff\-·（）()]+")


def clean_name(name: str) -> str:
    """去掉任务名里的 emoji 和空白，便于匹配配置。"""
    return EMOJI_RE.sub("", name).strip()


def parse_ts(s: str) -> datetime:
    return datetime.strptime(s[:23], "%Y-%m-%d %H:%M:%S.%f")


@dataclass
class Event:
    ts: datetime
    kind: str  # start / fail / done / abort / focus / record
    text: str = ""
    color: str = ""


def read_runtime_log(path: str) -> list[Event]:
    events: list[Event] = []
    seen_focus: set[tuple[str, str]] = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = TS_RE.match(line.rstrip("\r\n"))
            if not m:
                continue  # 异常堆栈等续行
            ts = parse_ts(m.group(1))
            body = PREFIX_RE.sub("", m.group(3))
            if body.startswith("[Record]"):
                events.append(Event(ts, "record", body[len("[Record]"):].strip()))
                continue
            if (sm := START_RE.match(body)):
                events.append(Event(ts, "start", sm.group(1)))
                continue
            if (fm := FAIL_RE.match(body)):
                events.append(Event(ts, "fail", fm.group(1)))
                continue
            if body.startswith("任务已全部完成"):
                events.append(Event(ts, "done"))
                continue
            if "已放弃本次任务" in body:
                events.append(Event(ts, "abort"))
                continue
            if "color:" in body and ("MonitorMarkdown" in line or "Focus 内容文件解析失败" in line):
                for rx in FOCUS_RES:
                    for color, text in rx.findall(body):
                        key = (ts.strftime("%H:%M:%S"), text)
                        if key in seen_focus:
                            continue
                        seen_focus.add(key)
                        events.append(Event(ts, "focus", text.strip(), color.capitalize()))
                    if rx.search(body):
                        break
    return events


@dataclass
class FwEvent:
    ts: datetime
    kind: str  # task_ok / task_fail / hit
    name: str


TASK_RE = re.compile(r'msg=Tasker\.Task\.(Succeeded|Failed)\].*?"entry":"([^"]+)".*?"task_id":(\d+)')
HIT_RE = re.compile(r'msg=Node\.Recognition\.Succeeded\].*?"name":"([^"]+)".*?"reco_id":(\d+)')


def read_framework_log(path: str, since: datetime | None = None,
                       hit_filter=lambda name: name.startswith("Flag_")) -> list[FwEvent]:
    """只扫描含关键字的行；同一事件会被两个进程各记一次，按 id 去重。"""
    out: list[FwEvent] = []
    seen: set[tuple[str, str]] = set()
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "EventDispatcher" not in line:
                continue
            if "Tasker.Task." in line:
                m = TASK_RE.search(line)
                if not m:
                    continue
                key = ("t" + m.group(1), m.group(3))
                kind = "task_ok" if m.group(1) == "Succeeded" else "task_fail"
                name = m.group(2)
            elif "Node.Recognition.Succeeded" in line:
                m = HIT_RE.search(line)
                if not m or not hit_filter(m.group(1)):
                    continue
                key = ("h", m.group(2))
                kind, name = "hit", m.group(1)
            else:
                continue
            if key in seen:
                continue
            seen.add(key)
            ts = parse_ts(line[1:24])
            if since and ts < since:
                continue
            out.append(FwEvent(ts, kind, name))
    return out


ERR_SHOT_RE = re.compile(r"^(\d{4})\.(\d\d)\.(\d\d)-(\d\d)\.(\d\d)\.(\d\d)\.(\d+)_(.+)\.png$")


def list_error_shots(folder: str) -> list[tuple[datetime, str]]:
    shots = []
    if not os.path.isdir(folder):
        return shots
    for fn in os.listdir(folder):
        m = ERR_SHOT_RE.match(fn)
        if m:
            y, mo, d, h, mi, s, ms, _node = m.groups()
            ts = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), int(ms[:3].ljust(3, "0")) * 1000)
            shots.append((ts, os.path.join(folder, fn)))
    return sorted(shots)


@dataclass
class Segment:
    """一次运行中的一个任务。"""
    name: str
    start: datetime
    end: datetime
    explicit_fail: bool = False
    focus: list[Event] = field(default_factory=list)
    records: list[Event] = field(default_factory=list)
    fw: list[FwEvent] = field(default_factory=list)
    shots: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return clean_name(self.name)

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


@dataclass
class Run:
    start: datetime
    end: datetime
    segments: list[Segment]
    finished: bool
    aborted: bool


def split_runs(events: list[Event]) -> list[Run]:
    runs: list[Run] = []
    segs: list[Segment] = []
    run_start: datetime | None = None
    last_ts: datetime | None = None

    def close(end: datetime, finished: bool, aborted: bool):
        nonlocal segs, run_start
        if segs or aborted:
            if segs:
                segs[-1].end = end
            runs.append(Run(run_start or end, end, segs, finished, aborted))
        segs, run_start = [], None

    for ev in events:
        last_ts = ev.ts
        if ev.kind == "start":
            if run_start is None:
                run_start = ev.ts
            if segs:
                segs[-1].end = ev.ts
            segs.append(Segment(ev.text, ev.ts, ev.ts))
        elif ev.kind in ("done", "abort"):
            close(ev.ts, ev.kind == "done", ev.kind == "abort")
        elif segs:
            seg = segs[-1]
            seg.end = ev.ts
            if ev.kind == "fail":
                seg.explicit_fail = True
            elif ev.kind == "focus":
                seg.focus.append(ev)
            elif ev.kind == "record":
                seg.records.append(ev)
    if segs and last_ts:
        close(last_ts, False, False)  # 日志在运行中途截止（还在跑或进程被杀）
    return runs


def attach(runs: list[Run], fw: list[FwEvent], shots: list[tuple[datetime, str]]):
    """把框架事件和出错截图按时间挂到对应任务上。"""
    for run in runs:
        for i, seg in enumerate(run.segments):
            nxt = run.segments[i + 1].start if i + 1 < len(run.segments) else run.end
            lo, hi = seg.start, max(nxt, seg.end)
            seg.fw = [e for e in fw if lo <= e.ts <= hi]
            seg.shots = [p for t, p in shots if lo <= t <= hi]
