"""BetterGI 一条龙日志 → 每一项的结果。

只看日志文字，不碰进程、时间和界面：bettergi.py 的执行器负责启动、超时、停止和计时，
每读到一行就交给 OneDragonLog.feed()，按它返回的事件记录结果。tests/bgilog_test.py 用真实日志回放。

判定规则都在下面几张表里。新加一条判定：往表里加一行，再在 tests/fixtures/bgi/ 放一段对应的真实日志。
"""
from __future__ import annotations

import re

# ---------- 进度：哪句日志表示走到了哪一项 ----------
START = r"(参数指定的|启用)一条龙配置：\s*"             # + 配置名：出现之后才认结果（之前的是别的运行）
ITEM_START = re.compile(r"一条龙任务执行:\s*(\d+)/(\d+)")   # 第 i 项开始（也就是上一项结束）
GROUP_START = re.compile(r'配置组\s*"([^"]+)"\s*加载完成')  # 配置组不打印「一条龙任务执行」，按名字认
ENABLED = re.compile(r"启用一条龙任务的数量:\s*(\d+)")       # 和管家布置的项数对不上 → 提醒
ROUTE = re.compile(r"开始处理第\s*\d+\s*组第\s*(\d+)/(\d+)\s*个")  # 配置组路线进度，写进结果说明
SCRIPT_END = re.compile(r'脚本执行结束:\s*"([^"]+)",\s*耗时:\s*(\S+)')
ALL_DONE = "一条龙和配置组任务结束"                       # 整个一条龙正常走完
CANCELLED = "任务被取消，退出执行"                       # 在 BetterGI 里被中断（或管家按了取消键）

# ---------- 这一项其实没做成：BetterGI 照样往下走，管家记失败 ----------
# (优先级, 正则, 原因)。同一项里先出现的原因留着，只有优先级更高的才替换它。
# 原因里的 {0} {1} 是正则的分组。
FAIL_RULES = [
    # 10-20 / 10-21：原神是 3200×2400，BetterGI 每一项都报错却照样「执行完」
    (3, re.compile(r"分辨率不是 16:9.*?当前分辨率为\s*(\d+\s*x\s*\d+)"),
     "原神窗口分辨率不是 16:9（当前 {0}），这一项没做成。请把原神手动调成 1920×1080 窗口化后重跑（或在设置里打开「运行前调整分辨率」）"),
    (2, re.compile(r"分辨率不是 16:9"),
     "原神窗口分辨率不是 16:9，这一项没做成。请把原神手动调成 1920×1080 窗口化后重跑（或在设置里打开「运行前调整分辨率」）"),
    # 10-24「前往合成台领取奖励执行异常：点击传送点后未出现交互面板」、10-26「合成树脂执行异常：当前获取焦点的窗口不是原神」
    (1, re.compile(r"(\S{0,20}执行异常[:：].*)"), "BetterGI 报错：{0}"),
    # 10-26「领取邮件奖励异常」：整行只有这几个字，下一行是异常的类型和原因
    (1, re.compile(r"^(\S{2,20}异常)$"), "BetterGI 报错：{0}"),
]

# ---------- 只是提示：失败时附在原因后面，也进运行记录的「问题」 ----------
ISSUES = [
    ("获取游戏区域截图失败", "截图失败"),
    ("不是原神，暂停", "原神窗口失去焦点（可能有人在用电脑）"),
    ("传送失败", "传送失败"),
    ("检测到复苏界面", "角色被击败"),
    ("游戏已退出", "游戏已退出"),
]
FOCUS_WINDOW = re.compile(r"当前获取焦点的窗口为:\s*([^，,]+)")
SKIP_FOCUS = '→ "任务启动'   # 不当成这一项的正文


class OneDragonLog:
    """一次一条龙运行的日志解析。feed(一行) 返回事件列表：

    ("start", 任务名)                         这一项开始
    ("end", 任务名, 结果, 说明, 正文摘要)       这一项结束；结果是 succeeded / failed / stopped / timeout
    ("warn", 文字)                            要进运行记录的提醒
    ("focus", 文字)                           这一项的日志正文（界面上滚动显示）
    ("over", 整体结果, 说明)                   日志里的结束标志：succeeded / cancelled
    """

    def __init__(self, config_name: str, names: list[str]):
        self.names = list(names)
        self.start_re = re.compile(START + re.escape(config_name))
        self.started = False
        self.over = None
        self.err_next = False
        self._reset(None)

    def _reset(self, cur):
        self.cur = cur
        self.focus, self.errors, self.issues = [], [], []
        self.fail, self.fail_rank = "", 0
        self.route, self.scripts = "", []

    # ---- 一项结束 ----
    def close(self, result: str, why: str) -> list[tuple]:
        """结束当前这一项（日志里下一项开始了，或执行器那边停止 / 超时 / BetterGI 退出了）。"""
        if self.cur is None:
            return []
        if result == "succeeded" and self.fail:  # BetterGI 自己走完了这一项，但日志说明它其实没做成
            result, why = "failed", self.fail
        extra = []
        if self.route:
            extra.append(f"路线进度 {self.route}")
        if self.scripts:
            extra.append("、".join(self.scripts[-3:]))
        if result == "succeeded" and self.errors:
            extra.append(f"日志里有 {len(self.errors)} 条错误")
        if result not in ("succeeded", "stopped") and self.issues:  # 你手动停的：不附最后一句警告（多半是你切窗口时报的）
            why = f"{why}：{self.issues[-1]}"
        if extra:
            why = f"{why}（{'；'.join(extra)}）"
        focus = (self.focus[-5:] + [f"[问题] {e}" for e in self.issues[-2:]] + [f"[错误] {e}" for e in self.errors[-2:]])[-8:]
        ev = ("end", self.cur, result, why, focus)
        self._reset(None)
        return [ev]

    def _begin(self, name) -> list[tuple]:
        out = self.close("succeeded", "BetterGI 日志：这一项执行完")
        self._reset(name)
        return out + [("start", name)]

    # ---- 逐行 ----
    def feed(self, s: str) -> list[tuple]:
        if self.over:
            return []
        out = []
        if self.err_next and not s.startswith("["):
            if self.cur:
                self.errors.append(s[:160])
            self.err_next = False
        if s.startswith("["):  # 每条日志的抬头：[时间] [级别] [线程] 类名；正文在下一行
            self.err_next = " [ERR] " in s[:24]
            return out
        if not self.started:
            self.started = bool(self.start_re.search(s))
            return out

        m = ENABLED.search(s)
        if m and int(m.group(1)) != len(self.names):
            out.append(("warn", f"BetterGI 启用了 {m.group(1)} 项，管家布置的是 {len(self.names)} 项"))
        m = ITEM_START.search(s)
        if m:
            i = int(m.group(1)) - 1
            if 0 <= i < len(self.names):
                return out + self._begin(self.names[i])
            return out + self.close("succeeded", "BetterGI 日志：这一项执行完") + \
                [("warn", f"BetterGI 日志里的第 {i + 1} 项不在管家的计划里")]
        m = GROUP_START.search(s)
        if m and m.group(1) != self.cur:
            if m.group(1) in self.names:
                return out + self._begin(m.group(1))
            return out + self.close("succeeded", "BetterGI 日志：这一项执行完") + \
                [("warn", f"BetterGI 在跑配置组「{m.group(1)}」，不在管家的计划里")]
        m = ROUTE.search(s)
        if m:
            self.route = f"{m.group(1)}/{m.group(2)}"
        m = SCRIPT_END.search(s)
        if m and not m.group(1).endswith(".json"):
            self.scripts.append(f"{m.group(1)} {m.group(2)}")
        for sig, txt in ISSUES:
            if sig in s:
                m2 = FOCUS_WINDOW.search(s)
                self.issues.append(txt + (f"（当前窗口：{m2.group(1)}）" if m2 else ""))
        if self.cur:
            for rank, rx, why in FAIL_RULES:
                m = rx.search(s)
                if m and rank > self.fail_rank:
                    self.fail, self.fail_rank = why.format(*[(g or "")[:120] for g in m.groups()]), rank
            if not s.startswith(SKIP_FOCUS):
                self.focus.append(s[:160])
                out.append(("focus", s[:160]))
        if ALL_DONE in s:
            self.over = ("succeeded", "日志：一条龙和配置组任务结束")
            return out + self.close("succeeded", "BetterGI 日志：这一项执行完") + [("over", *self.over)]
        if CANCELLED in s:  # 当前这项记「已中断」，后面的由执行器记「未运行」
            self.over = ("cancelled", "日志：任务被取消，退出执行（在 BetterGI 里中断）")
            return out + self.close("stopped", "在 BetterGI 里被中断") + [("over", *self.over)]
        return out
