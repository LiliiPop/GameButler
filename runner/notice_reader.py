"""读游戏内公告栏：截图 + 文字识别，把每条公告的标题、正文、题图存成 JSON，管家的活动日历再从里面拆活动。

只点公告栏里的列表、翻页、返回，不改游戏、不消耗任何东西。
目前支持：时空中的绘旅人（学院公告）。之后加恋与深空、代号鸢。

结果：<out_dir>/<游戏>.json
  {"game": "sh", "fetched": "2026-10-23 05:10", "items": [{"title", "date", "text", "banner"}]}
  banner 是同目录下 <游戏>/ 里的 PNG 文件名（没有题图时为空）。
"""
from __future__ import annotations

import json
import re
import struct
import time
import zlib
from pathlib import Path

import numpy


def png_bytes(img: numpy.ndarray) -> bytes:
    """BGR 图 → PNG（不依赖 PIL / cv2）。"""
    h, w = img.shape[:2]
    rgb = numpy.ascontiguousarray(img[:, :, ::-1]).tobytes()
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


class Screen:
    """对 MaaFramework 控制器 / Tasker 的一层薄封装：截图、文字识别、点击、滑动、返回键。坐标按 1280×720。"""

    def __init__(self, controller, tasker, log=print, stop=lambda: False):
        self.c, self.t, self.log, self.stop = controller, tasker, log, stop
        self.img = None
        self.low_res: list[str] = []  # 存成低清版的题图：原因
        self.nobanner: list = []      # 没认出题图的公告：(标题, 当时的画面)，存到 debug/ 方便调

    def shot(self):
        self.c.post_screencap().wait()
        self.img = self.c.cached_image
        return self.img

    def ocr(self, roi, fresh=True) -> list[tuple[str, tuple[int, int, int, int]]]:
        from maa.pipeline import JOCR, JRecognitionType
        img = self.shot() if fresh or self.img is None else self.img
        d = self.t.post_recognition(JRecognitionType.OCR, JOCR(roi=tuple(roi)), img).wait().get()
        n = d.nodes[0] if d and d.nodes else None
        res = n.recognition.all_results if n and n.recognition else []
        return [(r.text.strip(), tuple(r.box)) for r in res if r.text.strip() and r.score >= 0.5]

    def find(self, roi, pattern, fresh=True):
        for text, box in self.ocr(roi, fresh):
            if re.search(pattern, text):
                return text, box
        return None

    def locate(self, roi, word, fresh=True):
        """找某个词的中心点。识别时相邻的几个按钮文字常被连成一段（如「联系客服问题反馈学院公告」），
        按字在这段里的位置算横坐标，不能直接点整段的中间。"""
        for text, (x, y, w, h) in self.ocr(roi, fresh):
            i = text.find(word)
            if i >= 0:
                return int(x + w * (i + len(word) / 2) / len(text)), int(y + h / 2)
        return None

    def hi_png(self, box) -> bytes:
        """题图用原始分辨率截：识别用的截图缩到短边 720，存题图时临时换成原图大小再截一张，按比例裁同一块。
        原图截不成、或模拟器本身就只有 720：存 720 的那张（有图最重要），原因记在 low_res 里，读完写进结果。"""
        x, y, w, h = [int(v) for v in box]
        low = self.img
        try:
            self.c.set_screenshot_use_raw_size(True)
            self.c.post_screencap().wait()
            raw = self.c.cached_image
            k = min(raw.shape[:2]) / min(low.shape[:2])
            if k > 1.05:
                X, Y, W, H = int(x * k), int(y * k), int(w * k), int(h * k)
                return png_bytes(raw[Y:Y + H, X:X + W])
            if min(raw.shape[:2]) <= 760:  # 识别用的截图本来就是原图大小时不算低清；模拟器本身只有 720 才算
                self.low_res.append(f"模拟器分辨率只有 {raw.shape[1]}×{raw.shape[0]}")
        except Exception as e:
            self.low_res.append(f"原图没截成（{type(e).__name__}: {e}）")
        finally:  # 换回识别用的 720：换不回来后面的坐标全错，直接报错
            # 「用原图大小」优先于「短边 720」，必须先关掉它（10-26：没关，读完公告后 MaaLYSK 什么都认不出，启动卡 8 分钟）
            self.c.set_screenshot_use_raw_size(False)
            self.c.set_screenshot_target_short_side(720)
            self.c.post_screencap().wait()
            self.img = self.c.cached_image
        return png_bytes(low[y:y + h, x:x + w])

    def click(self, x, y, wait=1.2):
        self.c.post_click(int(x), int(y)).wait()
        time.sleep(wait)

    def swipe(self, x1, y1, x2, y2, ms=700, wait=1.2):
        self.c.post_swipe(int(x1), int(y1), int(x2), int(y2), ms).wait()
        time.sleep(wait)

    back_key = 4  # 安卓返回键；电脑游戏（Win32）用 Esc = 27

    def back(self, wait=1.5):
        self.c.post_click_key(self.back_key).wait()
        time.sleep(wait)


def lines_of(results, full_right=1080) -> list[str]:
    """识别结果 → 按行排好的文字；上一行写满（到右边）时把下一行接上去（同一段被折行）。"""
    rows = sorted(results, key=lambda r: (r[1][1], r[1][0]))
    out, prev_right = [], 0
    for text, (x, y, w, h) in rows:
        if re.fullmatch(r"\W*[A-Za-z0-9]{0,2}\W*N[O0o][.\s,]*[1lI!|]\W*\w?", text):
            continue  # 恋与深空公告右下角的装饰水印「NO.1」
        if out and prev_right >= full_right and not re.match(r"^(\d+[.、]|[►▶●•※*>》]|.{0,6}[:：]$)", text):
            out[-1] += text
        else:
            out.append(text)
        prev_right = x + w
    return out


def banner_box_plain(img, roi):
    """颜色不鲜艳的题图（11-02 时绘「怪谈：时融」：暗蓝灰色）：找一块和面板底色明显不同的矩形。"""
    x0, y0, w0, h0 = roi
    a = img[y0:y0 + h0, x0:x0 + w0].astype(numpy.int16)
    bg = numpy.median(a.reshape(-1, 3), axis=0)
    diff = numpy.abs(a - bg).max(axis=2) > 40
    rows = numpy.where(diff.sum(axis=1) > w0 * 0.2)[0]
    if len(rows) < 40:
        return None
    ys = [rows[0]]
    for r in rows[1:]:
        if r - ys[-1] > 6:
            break
        ys.append(r)
    if len(ys) < 40:  # 正文一行字只有十几像素高，不会被当成题图
        return None
    cols = numpy.where(diff[ys[0]:ys[-1] + 1].mean(axis=0) > 0.5)[0]
    if len(cols) < 80:
        return None
    return x0 + int(cols[0]), y0 + int(ys[0]), int(cols[-1] - cols[0] + 1), int(ys[-1] - ys[0] + 1)


def banner_box(img, roi):
    """在 roi 里找题图：一块颜色鲜艳的矩形；找不到再按「和底色不同的一块」找（banner_box_plain）。返回 (x, y, w, h) 或 None。"""
    return banner_box_vivid(img, roi) or banner_box_plain(img, roi)


def banner_box_vivid(img, roi):
    """颜色鲜艳的矩形。"""
    x0, y0, w0, h0 = roi
    a = img[y0:y0 + h0, x0:x0 + w0].astype(numpy.int16)
    sat = (a.max(axis=2) - a.min(axis=2)) > 45
    rows = numpy.where(sat.sum(axis=1) > w0 * 0.12)[0]
    cols = numpy.where(sat.sum(axis=0) > h0 * 0.12)[0]
    if len(rows) < 40 or len(cols) < 80:
        return None
    # 取第一段连续的行（题图下面可能还有彩色文字）
    ys = [rows[0]]
    for r in rows[1:]:
        if r - ys[-1] > 6:
            break
        ys.append(r)
    if len(ys) < 40:
        return None
    # 题图下沿常有一条浅色的字条（如「免费获得纪念R卡」）：颜色不鲜艳，但和底色不同，接着往下算
    bg = numpy.median(a[-10:].reshape(-1, 3), axis=0)
    band = a[:, cols[0]:cols[-1] + 1]
    nonbg = (numpy.abs(band - bg).max(axis=2) > 18).mean(axis=1) > 0.5
    end = ys[-1]
    while end + 1 < h0 and nonbg[end + 1]:
        end += 1
    return x0 + int(cols[0]), y0 + int(ys[0]), int(cols[-1] - cols[0] + 1), int(end - ys[0] + 1)


# ====================================================================== 时空中的绘旅人
class SHNotice:
    """学院公告：左边列表（每条带日期角标），右边详情（标题栏、题图、正文）。

    进入方式：登录页右侧「学院公告」图标（10-26 定：只在登录页读，不进游戏从主界面找）。
    游戏已经进去了就重新打开游戏回到登录页；读完停在登录页，接着由启动任务进游戏（游戏记录的 before_startup）。
    """
    DIALOG = (520, 90, 240, 60)          # 「学院公告」大标题
    LIST = (120, 178, 258, 452)
    TITLE = (412, 186, 710, 36)
    BODY = (405, 228, 745, 400)
    LOGIN_ICON = (1160, 245, 110, 35)    # 登录页右侧「学院公告」文字
    SKIP = re.compile(r"系统(更新|公告)|修复|优化|维护|防沉迷|隐私|协议")

    def __init__(self, scr: Screen, package: str = ""):
        self.s, self.package = scr, package

    def open(self) -> bool:
        s = self.s
        restarted = False
        t0 = time.time()
        while time.time() - t0 < 240 and not s.stop():
            if s.find(self.DIALOG, "学院公告"):
                return True
            hit = s.locate(self.LOGIN_ICON, "学院公告", fresh=False)
            if hit:
                s.log("登录页：点「学院公告」")
                s.click(hit[0], hit[1] - 30, 4)  # 公告栏弹出要一两秒：等够再看，免得又点一下把它关掉
                continue
            if not restarted and self.package and time.time() - t0 > 20:
                s.log("不在登录页：重新打开游戏回到登录页")
                s.c.post_stop_app(self.package).wait()
                time.sleep(3)
                s.c.post_start_app(self.package).wait()
                restarted = True
            time.sleep(4)
        return False

    def rows(self) -> list[dict]:
        """当前列表里能看到的条目：标题（两行的拼起来）、日期、点击位置。"""
        res = self.s.ocr(self.LIST)
        titles = sorted([r for r in res if r[1][0] >= 195 and not re.fullmatch(r"[.\d]+", r[0])], key=lambda r: r[1][1])
        nums = [r for r in res if r[1][0] < 195 and re.fullmatch(r"\.?\d{1,2}", r[0])]
        rows: list[dict] = []
        for text, (x, y, w, h) in titles:
            cy = y + h / 2
            if rows and cy - rows[-1]["cy"] < 40:      # 同一条的第二行
                rows[-1]["title"] += text
                rows[-1]["cy"] = (rows[-1]["cy"] + cy) / 2
                continue
            rows.append({"title": text, "cy": cy})
        for r in rows:
            near = sorted((n for n in nums if abs(n[1][1] + n[1][3] / 2 - r["cy"]) < 34), key=lambda n: n[1][1])
            if len(near) >= 2:
                r["date"] = f"{int(near[0][0].strip('.')):02d}-{int(near[1][0]):02d}"
        # 列表上下边缘被切掉一半的条目不要（滚动后会完整出现）
        return [r for r in rows if 200 < r["cy"] < 615]

    def detail(self) -> tuple[str, str, bytes]:
        s = self.s
        t = s.ocr(self.TITLE)
        title = "".join(x[0] for x in sorted(t, key=lambda r: r[1][0]) if len(x[0]) > 1)
        img = s.img
        bb = banner_box(img, (412, 228, 720, 200))
        banner = s.hi_png(bb) if bb else b""
        if not bb:  # 没认出题图：留一张当时的画面（data/news/ingame/sh/debug/），方便看是题图颜色太淡还是本来就没有（11-02）
            s.nobanner.append((title, png_bytes(img)))
        inside = lambda b: bb and bb[0] <= b[0] + b[2] / 2 <= bb[0] + bb[2] and bb[1] <= b[1] + b[3] / 2 <= bb[1] + bb[3]
        lines = lines_of([r for r in s.ocr(self.BODY, fresh=False) if not inside(r[1])])  # 题图上的字不算正文
        for _ in range(3):  # 正文长：往下翻，直到没有新的行
            s.swipe(770, 590, 770, 300, 800, 1.0)
            key = lambda t: re.sub(r"[\W_]", "", t)  # 翻页前后同一行可能差个标点 / 箭头
            have = {key(x) for x in lines}
            more = [x for x in lines_of(s.ocr(self.BODY)) if key(x) not in have]
            if not more:
                break
            lines += more
        return title, "\n".join(lines), banner

    def read(self, limit=24) -> list[dict]:
        s = self.s
        out, seen, idle = [], set(), 0
        while len(out) < limit and idle < 2 and not s.stop():
            new = [r for r in self.rows() if r["title"] not in seen]
            if not new:
                idle += 1
            for r in new:
                seen.add(r["title"])
                if self.SKIP.search(r["title"]):
                    continue
                s.click(290, r["cy"], 1.5)
                title, text, banner = self.detail()
                s.log(f"读到：{title or r['title']}")
                out.append({"title": title or r["title"], "list_title": r["title"], "date": r.get("date", ""),
                            "text": text, "banner_png": banner})
                if len(out) >= limit or s.stop():
                    break
            s.swipe(250, 560, 250, 300, 900)
        return out

    def close(self):
        if self.s.find(self.DIALOG, "学院公告"):  # 关掉公告栏，停在登录页（登录页上再按返回会弹「确定退出」）
            self.s.back(2)


# ====================================================================== 恋与深空
class LYSKNotice:
    """登录页右侧第 2 个图标打开公告：上面两个标签「活动公告 / 系统公告」，下面左右箭头翻页。
    活动公告是一张张图片 banner（标题、日期写在图里），系统公告是文字（版本内容一览，要往下翻）。
    竖屏 900×1600；下面的坐标都按 900 宽写，运行时按实际截图大小缩放。"""
    W = 900

    def __init__(self, scr: Screen, package: str = ""):
        self.s, self.package = scr, package
        self.k = 1.0

    def R(self, x, y, w=0, h=0):
        k = self.k
        return (int(x * k), int(y * k), int(w * k), int(h * k)) if w else (int(x * k), int(y * k))

    def _scale(self):
        img = self.s.shot()
        self.k = img.shape[1] / self.W

    def at_dialog(self, fresh=True):
        hit = self.s.ocr(self.R(390, 230, 400, 70), fresh)
        return sum(1 for t, _ in hit if t in ("活动公告", "系统公告")) >= 1

    def at_login(self, fresh=True):
        return bool(self.s.find(self.R(250, 1250, 400, 100), "进入游戏", fresh))

    def open(self) -> bool:
        s = self.s
        self._scale()
        restarted = False
        t0 = time.time()
        while time.time() - t0 < 240 and not s.stop():
            if self.at_dialog():
                return True
            if self.at_login(fresh=False):
                s.log("登录页：点右侧的公告图标")
                s.click(*self.R(863, 165), 2.5)
                continue
            if not restarted and self.package and time.time() - t0 > 20:
                # 公告栏只在登录页有：游戏已经进去了，就重启回登录页（只是重新打开游戏，不影响进度）
                s.log("不在登录页：重新打开游戏回到登录页")
                self.s.c.post_stop_app(self.package).wait()
                time.sleep(3)
                self.s.c.post_start_app(self.package).wait()
                restarted = True
            time.sleep(4)
        return False

    def _fingerprint(self):
        x, y, w, h = self.R(110, 298, 680, 895)
        a = self.s.img[y:y + h:max(1, h // 24), x:x + w:max(1, w // 24)].astype(numpy.int16)
        return a

    def _same(self, a, b):
        return a is not None and b is not None and a.shape == b.shape and float(numpy.abs(a - b).mean()) < 8

    def read_banners(self, limit=12) -> list[dict]:
        s = self.s
        s.click(*self.R(490, 263), 2)
        out, first = [], None
        for _ in range(limit):
            if s.stop():
                break
            res = s.ocr(self.R(110, 298, 680, 895))
            fp = self._fingerprint()
            if first is not None and self._same(fp, first):
                break  # 翻回第一张了
            first = fp if first is None else first
            x, y, w, h = self.R(110, 298, 680, 895)
            png = s.hi_png((x, y, w, h))
            texts = [(t, b) for t, b in res if t not in ("查看详情",) and not re.fullmatch(r"[+＋\d\s]+", t)]
            dates = [t for t, _ in texts if re.search(r"\d{1,2}[月/]\d", t) and re.search(r"\d:\d\d", t)]
            words = sorted([(t, b) for t, b in texts if t not in dates and len(t) >= 2], key=lambda r: -r[1][3])
            title = words[0][0] if words else ""
            head = next((t for t, b in words[1:] if b[3] >= 30), "")
            lines = [t for t, _ in sorted(texts, key=lambda r: (r[1][1], r[1][0]))]
            s.log(f"活动公告：{title}{('（' + dates[0] + '）') if dates else ''}")
            out.append({"title": title, "list_title": head, "date": "", "text": "\n".join(lines),
                        "period": dates[0] if dates else "", "banner_png": png, "kind": "banner"})
            s.click(*self.R(777, 1258), 2)
        return out

    def read_system(self, limit=6) -> list[dict]:
        s = self.s
        s.click(*self.R(690, 263), 2)
        out, first = [], None
        for _ in range(limit):
            if s.stop():
                break
            roi = self.R(110, 298, 680, 895)
            lines = lines_of(s.ocr(roi), full_right=int(560 * self.k))
            key = lambda t: re.sub(r"[\W_]", "", t)
            sig = key("".join(lines[:3]))
            if first is not None and sig == first:
                break
            first = sig if first is None else first
            for _ in range(8):  # 往下翻到底
                s.swipe(*self.R(450, 1050), *self.R(450, 520), 900, 1.2)
                have = key("".join(lines))  # 翻页边界上那半行会再读一遍：已经包含在读过的文字里的不要
                more = [x for x in lines_of(s.ocr(roi), full_right=int(560 * self.k)) if key(x) not in have]
                if not more:
                    break
                lines += more
            title = lines[0].lstrip("·• ") if lines else ""
            s.log(f"系统公告：{title}（{len(lines)} 行）")
            out.append({"title": title, "list_title": "", "date": "", "text": "\n".join(lines),
                        "banner_png": b"", "kind": "system"})
            s.click(*self.R(777, 1258), 2)
        return out

    def read(self) -> list[dict]:
        return self.read_banners() + self.read_system()

    def close(self):
        if self.at_dialog():
            self.s.back(2)  # 关掉公告，停在登录页（接下来的启动任务会点「进入游戏」）


# ====================================================================== 代号鸢（港服）
class YuanNotice:
    """主界面左上「公告」：一整篇文字公告（更新内容里写着各活动的结束时间）；
    主界面右侧「活动」：活动列表，每张卡片有活动名、一句说明、「剩余时间：5天20时」。
    竖屏 720×1280，坐标按 720 宽写，运行时按实际截图缩放。"""
    W = 720

    def __init__(self, scr: Screen):
        self.s, self.k = scr, 1.0

    def R(self, x, y, w=0, h=0):
        k = self.k
        return (int(x * k), int(y * k), int(w * k), int(h * k)) if w else (int(x * k), int(y * k))

    def at_main(self, fresh=True):
        return len([t for t, _ in self.s.ocr(self.R(600, 150, 120, 330), fresh) if t in ("商城", "秘宝", "活动")]) >= 2

    def at_notice(self, fresh=True):
        return bool(self.s.find(self.R(200, 290, 320, 70), "公告通知", fresh))

    def at_events(self, fresh=True):
        return bool(self.s.find(self.R(20, 370, 690, 910), "剩余时间", fresh))

    def open(self) -> bool:
        s = self.s
        self.k = s.shot().shape[1] / self.W
        for _ in range(8):
            if s.stop():
                return False
            if self.at_notice() or self.at_events(fresh=False) or self.at_main(fresh=False):
                return True
            s.log("没认出当前画面，按一次返回键")
            s.back(2)
        return False

    def read_notice(self) -> list[dict]:
        s = self.s
        if not self.at_notice():
            if not self.at_main(fresh=False):
                return []
            hit = s.locate(self.R(150, 170, 110, 45), "公告", fresh=False)
            if not hit:
                return []
            s.log("主界面：点「公告」")
            s.click(hit[0], hit[1] - 12, 2.5)
            if not self.at_notice():
                return []
        roi = self.R(60, 350, 630, 690)
        full = int(600 * self.k)
        lines = lines_of(s.ocr(roi), full_right=full)
        key = lambda t: re.sub(r"[\W_]", "", t)
        for _ in range(12):
            s.swipe(*self.R(360, 950), *self.R(360, 480), 900, 1.2)
            have = key("".join(lines))
            more = [x for x in lines_of(s.ocr(roi), full_right=full) if key(x) not in have]
            if not more:
                break
            lines += more
        s.log(f"公告：{len(lines)} 行")
        s.click(*self.R(664, 222), 2)  # 右上角关闭
        if self.at_notice():
            s.back(2)
        return [{"title": "公告", "list_title": "", "date": "", "text": "\n".join(lines), "banner_png": b"", "kind": "system"}]

    def read_events(self, limit=20) -> list[dict]:
        s = self.s
        if not self.at_events():
            if not self.at_main(fresh=False):
                return []
            hit = s.locate(self.R(600, 150, 120, 330), "活动", fresh=False)
            if not hit:
                return []
            s.log("主界面：点「活动」")
            s.click(hit[0], hit[1] - 25, 3)
            if not self.at_events():
                return []
        cards: dict = {}
        idle = 0
        while len(cards) < limit and idle < 3 and not s.stop():
            res = s.ocr(self.R(20, 150, 690, 1130))
            img = s.img
            titles = [r for r in res if r[1][3] >= 45 * self.k and r[1][0] > 280 * self.k and r[1][1] > 360 * self.k
                      and "剩余" not in r[0] and r[0] != "活动"]
            new = 0
            for t, (x, y, w, h) in sorted(titles, key=lambda r: r[1][1]):
                t = t.strip("。.，,★☆ ")
                cy = y + h / 2
                top, bot = int(cy - 85 * self.k), int(cy + 125 * self.k)
                if bot > img.shape[0] - 10:
                    continue  # 卡片没完整露出来：翻页后再读
                inside = [r for r in res if top <= r[1][1] + r[1][3] / 2 <= bot and r[0].strip("。.，, ") != t]
                sub = "".join(r[0] for r in sorted(inside, key=lambda r: (r[1][1], r[1][0])) if "剩余" not in r[0])
                remain = next((r[0] for r in inside if "剩余" in r[0]), "")
                old = cards.get(t)
                if old:
                    if remain and not old["remain"]:  # 上一页时这张卡的最后一行被底部的渐隐挡住了
                        old["remain"] = remain
                        old["text"] = "\n".join(x for x in (old["list_title"], remain) if x)
                    continue
                new += 1
                x0, x1 = int(20 * self.k), int(700 * self.k)
                cards[t] = {"title": t, "list_title": sub, "date": "", "text": "\n".join(x for x in (sub, remain) if x),
                            "remain": remain, "banner_png": self.s.hi_png((x0, top, x1 - x0, bot - top)), "kind": "card"}
            idle = 0 if new else idle + 1
            s.swipe(*self.R(360, 1000), *self.R(360, 680), 1000, 1.5)  # 每次只翻一张半，每张卡都能完整露出来一次
        for c in cards.values():
            s.log(f"活动：{c['title']}{('（' + c['remain'] + '）') if c['remain'] else ''}")
        return list(cards.values())

    def read(self) -> list[dict]:
        return self.read_notice() + self.read_events()

    def close(self):
        for _ in range(2):  # 回到主界面
            if self.at_main():
                break
            self.s.back(2)


READERS = {"sh": SHNotice, "lysk": LYSKNotice, "yuan": YuanNotice}


# ====================================================================== 活动中心（只拿题图，11-02）
# entry / override：用 MAA 项目自己的流程走到活动中心（弹窗、主界面主题差异它都处理好了），override 让它到「活动中心」就停。
# home：读完回主界面用的节点。
EVENTS = {
    "sh": {"entry": "清红点", "override": {"红点_活动中心": {"next": [], "on_error": []}}, "home": "公共_返回主界面"},
}


class SHEvents:
    """时绘「活动中心」：左边一列活动名（每格约 67 像素高，最多 8 格），右边是这个活动的整页（就是最大最清楚的宣传图）。
    坐标按 1280×720，取自 MaaSH 清红点（redpoint.json）里的位置。"""
    TITLE = (94, 12, 232, 76)            # 「活动中心」
    LIST = (30, 90, 225, 540)            # 左边活动名
    SLOTS = [117 + round(67.4 * i) for i in range(8)]
    PAGE = (250, 80, 1030, 640)          # 右边活动页

    def __init__(self, scr: Screen):
        self.s = scr

    def names(self) -> dict[int, str]:
        """每一格的活动名（OCR 的行按纵坐标归到最近的格子）。"""
        out: dict[int, str] = {}
        for text, (x, y, w, h) in sorted(self.s.ocr(self.LIST), key=lambda r: r[1][1]):
            cy = y + h / 2
            k = min(range(len(self.SLOTS)), key=lambda i: abs(self.SLOTS[i] - cy))
            if abs(self.SLOTS[k] - cy) < 30 and len(re.sub(r"\W", "", text)) >= 2:
                out[k] = (out.get(k, "") + text).strip()
        return out

    def read(self) -> list[dict]:
        s = self.s
        if not s.find(self.TITLE, "活动中心"):
            return []
        got = []
        for k, name in sorted(self.names().items()):
            if s.stop():
                break
            s.click(135, self.SLOTS[k], 2.2)  # 活动页有动画：等一会儿再截
            s.shot()
            if not s.find(self.TITLE, "活动中心", fresh=False):  # 点进了别的界面（跳转类活动）：退回来，跳过这一格
                s.back(2)
                continue
            png = s.hi_png(self.PAGE)
            s.debug.append((name, png_bytes(s.img)))
            s.log(f"活动中心：{name}")
            got.append({"title": name, "banner_png": png})
        return got


def run_events(game: str, controller, tasker, out_dir: str, log=print, stop=lambda: False) -> tuple[str, str]:
    """活动中心已经打开（MAA 流程走过来的）：每个活动截一张，存到 out_dir/<游戏>_events/。"""
    scr = Screen(controller, tasker, log, stop)
    scr.debug = []
    items = SHEvents(scr).read() if game == "sh" else []
    if stop():
        return "stopped", "已手动停止"
    out = Path(out_dir) / f"{game}_events"
    out.mkdir(parents=True, exist_ok=True)
    for f in out.rglob("*.png"):
        f.unlink()
    (out / "debug").mkdir(exist_ok=True)  # 整页画面留一份：第一次跑完对一下裁的位置
    for n, (t, png) in enumerate(scr.debug):
        (out / "debug" / f"{n:02d}-{re.sub(r'[^0-9A-Za-z一-龥]+', '', t)[:20] or 'page'}.png").write_bytes(png)
    saved = []
    for k, it in enumerate(items):
        name = f"{k:02d}.png"
        (out / name).write_bytes(it.pop("banner_png"))
        saved.append({**it, "banner": name})
    (Path(out_dir) / f"{game}_events.json").write_text(json.dumps(
        {"game": game, "fetched": time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 8 * 3600)), "items": saved},
        ensure_ascii=False, indent=1), encoding="utf-8")
    if not saved:
        return "failed", "活动中心打开了，但一个活动也没认出来"
    why = f"活动中心：截了 {len(saved)} 个活动"
    if scr.low_res:
        why += f"（低清：{'；'.join(dict.fromkeys(scr.low_res))}）"
    return "succeeded", why


def run(game: str, controller, tasker, out_dir: str, log=print, stop=lambda: False, package: str = "") -> tuple[str, str]:
    """读一个游戏的公告栏，存到 out_dir。返回 (结果, 说明)，结果同其他任务：succeeded / failed / stopped。"""
    cls = READERS.get(game)
    if not cls:
        return "failed", f"还不支持读这个游戏的公告栏：{game}"
    scr = Screen(controller, tasker, log, stop)
    r = cls(scr, package) if cls in (LYSKNotice, SHNotice) else cls(scr)
    if not r.open():
        return ("stopped", "已手动停止") if stop() else ("failed", "没能打开公告栏")
    items = r.read()
    r.close()
    if stop():
        return "stopped", "已手动停止"
    out = Path(out_dir)
    (out / game).mkdir(parents=True, exist_ok=True)
    for f in (out / game).glob("*.png"):  # 只留这一次的题图
        f.unlink()
    dbg = out / game / "debug"
    if getattr(scr, "nobanner", None):
        dbg.mkdir(exist_ok=True)
        for f in dbg.glob("*.png"):
            f.unlink()
        for n, (t, png) in enumerate(scr.nobanner):
            (dbg / f"{n:02d}-{re.sub(r'[^0-9A-Za-z一-龥]+', '', t)[:20] or 'notice'}.png").write_bytes(png)
    saved = []
    for k, it in enumerate(items):
        png = it.pop("banner_png")
        it["banner"] = ""
        if png:
            name = f"{k:02d}.png"
            (out / game / name).write_bytes(png)
            it["banner"] = name
        saved.append(it)
    (out / f"{game}.json").write_text(json.dumps({"game": game, "fetched": time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 8 * 3600)),
                                                  "items": saved}, ensure_ascii=False, indent=1), encoding="utf-8")
    if not saved:
        return "failed", "公告栏打开了，但一条也没读到"
    why = f"读到 {len(saved)} 条公告"
    if scr.low_res:
        why += (f"；{len(scr.low_res)} 张题图是低清版（{'；'.join(dict.fromkeys(scr.low_res))}）。"
                "想要清楚的题图：把模拟器分辨率调高（例如 1920×1080）后再跑一次「读公告」")
    return "succeeded", why
