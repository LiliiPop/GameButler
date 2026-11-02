"""活动日历的公共工具：网络读取、HTML 转文字、从正文里找活动时间、题图缓存、「没读全」的记录。"""
from __future__ import annotations

import hashlib
import html
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from ..timeutil import BJ

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
KEEP_DAYS = 45


class Misses:
    """一个来源这次「没读全」的地方：某篇文章、正文、题图、日期读不到。整体照样算读到了，但来源状态里写清楚几条、为什么。"""

    def __init__(self):
        self.n = 0
        self.why: Counter = Counter()

    def add(self, what: str, err, n: int = 1):
        e = err if isinstance(err, str) else f"{type(err).__name__}: {err}"
        self.n += n
        self.why[f"{what}：{e[:80]}"] += n

    def summary(self) -> dict:
        return {"incomplete": self.n, "incomplete_why": [f"{k}（{v} 条）" if v > 1 else k for k, v in self.why.most_common(3)]}

# 游戏内公告里哪些算「活动」：分组名或标签带「活动」，或标题像活动
_ACT = re.compile(r"活动|祈愿|跃迁|限时|双倍|挑战|庆典|生日|开启|上线|复刻|返场")


def _now() -> datetime:
    return datetime.now(BJ)


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def _get(url: str, data_dir: Path, raw_name: str = "", referer: str = "", timeout: int = 20, raw_cap: int = 300_000) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9",
                                               **({"Referer": referer} if referer else {})})
    ctx = ssl.create_default_context()
    for attempt in (1, 2):  # 网络偶尔超时：再试一次
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                body = r.read()
            break
        except urllib.error.HTTPError:
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)
    if raw_name:
        p = data_dir / "raw" / f"{raw_name}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"URL: {url}\n\n".encode() + body[:raw_cap])
    return body


def _text(b: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("　", " ").replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def _parse_dt(s: str) -> datetime | None:
    s = (s or "").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f).replace(tzinfo=BJ)
        except ValueError:
            pass
    return None


# 正文里的时间段：「10月13日（周一）10:00～10月22日 23:59」「2026年10月13日10:00 - 2026年10月22日23:59」「10/13 10:00~10/22 23:59」
_D = r"(?:(\d{4})\s*[年/.-]\s*)?(\d{1,2})\s*[月/.-]\s*(\d{1,2})\s*日?\s*(?:[（(][^）)]{1,4}[）)])?\s*(?:(\d{1,2})\s*[:：]\s*(\d{2}))?"
_PERIOD = re.compile(_D + r"\s*(?:版本)?(?:更新|维护|开服)?后?\s*(?:[~～至\-—–]|到)\s*" + _D)


def _ampm(text: str) -> str:
    """「上午5:00」「下午3:00」「晚上8:00」→ 24 小时制。"""
    text = re.sub(r"(下午|晚上|傍晚)\s*(\d{1,2})(\s*[:：])", lambda m: f"{int(m.group(2)) + 12 if int(m.group(2)) < 12 else m.group(2)}{m.group(3)}", text)
    return re.sub(r"(上午|早上|凌晨|中午)\s*(?=\d{1,2}\s*[:：])", "", text)


def extract_period(text: str, ref: datetime | None = None) -> tuple[datetime | None, datetime | None]:
    """从正文里找第一个像「活动时间」的时间段。优先找「活动时间 / 开放时间 / 上架时间」后面的。"""
    ref = ref or _now()
    text = _ampm(text or "")
    cands = []
    for kw in ("活动时间", "开放时间", "上架时间", "售卖时间", "限时", "时间"):
        i = text.find(kw)
        if i >= 0:
            cands.append(text[i:i + 160])
    cands.append(text)
    for chunk in cands:
        m = _PERIOD.search(chunk)
        if not m:
            continue
        y1, mo1, d1, h1, mi1, y2, mo2, d2, h2, mi2 = m.groups()
        try:
            year1 = int(y1) if y1 else ref.year
            start = datetime(year1, int(mo1), int(d1), int(h1 or 0), int(mi1 or 0), tzinfo=BJ)
            if not y1 and start - ref > timedelta(days=200):  # 跨年：12 月读到 1 月的公告
                start = start.replace(year=year1 - 1)
            year2 = int(y2) if y2 else start.year
            end = datetime(year2, int(mo2), int(d2), int(h2 if h2 else 23), int(mi2 if mi2 else 59), tzinfo=BJ)
            if end < start:
                end = end.replace(year=end.year + 1)
            if end - start > timedelta(days=200):
                continue
            return start, end
        except ValueError:
            continue
    return None, None


def _cache_img(url: str, data_dir: Path) -> str:
    """下载题图到 img/，返回文件名。下载失败抛错（由 fetch 记进「没读全」）。"""
    if not url:
        return ""
    if url.startswith("file:"):  # 游戏内公告的题图：读取时已经放进 img/
        return url[5:] if (data_dir / "img" / url[5:]).exists() else ""
    url = url.split("?")[0] if "mihoyo.com" in url or "miyoushe" in url else url
    ext = (Path(urllib.parse.urlparse(url).path).suffix or ".jpg").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"
    name = hashlib.sha1(url.encode()).hexdigest()[:20] + ext
    p = data_dir / "img" / name
    if not p.exists():
        body = _get(url, data_dir, timeout=15)
        if len(body) <= 500:
            raise ValueError(f"题图只有 {len(body)} 字节，不像图片")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    return name



_A = re.compile(r'(?is)<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>')
_OG_IMG = re.compile(r'(?is)<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)')
_OG_TITLE = re.compile(r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)')
_TITLE = re.compile(r"(?is)<title>(.*?)</title>")
_IMG = re.compile(r'(?is)<img[^>]+src=["\']([^"\']+\.(?:jpg|jpeg|png|webp))')


def _clean_title(t: str) -> str:
    t = strip_html(t)
    t = re.split(r"__|_《|\s[-|｜]\s", t)[0].strip()
    return t


def extract_activities(body: str) -> list[tuple[str, datetime, datetime, str]]:
    """更新公告里常常一次列好几个活动：「【限时活动】缱绻假日 … 活动时间：3月12日更新后-4月23日05:00」。
    逐行找「活动时间 / 开放时间」，活动名取它前面最近的一行标题。"""
    lines = [x.strip() for x in body.split("\n") if x.strip()]
    out, seen = [], set()
    for i, ln in enumerate(lines):
        if not re.search(r"(活动|开放|上架|售卖|卡池|祈愿)时间", ln):
            continue
        st, en = extract_period(ln + " " + (lines[i + 1] if i + 1 < len(lines) else ""))
        if not st:
            continue
        name, nj = "", -1
        for j in range(i - 1, max(-1, i - 4), -1):
            cand = re.sub(r"^[\d一二三四五六七八九十]+[、.．]\s*|^[■◆●◇·\-—🔥✨]+\s*", "", lines[j])
            cand = re.sub(r"^【[^】]{1,8}】\s*", "", cand) or cand  # 去掉「【限时活动】」这类前缀
            if 2 <= len(cand) <= 40 and not re.search(r"(时间|条件|说明|规则|奖励)[:：]", cand):
                name, nj = cand.strip("【】[] "), j
                break
        # 副标题：活动名上面紧挨着的短标题（系列名、同系列的另一张卡），加上活动说明的第一句
        ctx = []
        for j in range(nj - 1, max(-1, nj - 3), -1):
            c = re.sub(r"^[■◆●◇·\-—🔥✨]+\s*", "", lines[j]).strip()
            if not c or len(c) > 40 or re.search(r"时间|说明[:：]?$|^\d+\.", c) or extract_period(c)[0]:
                break
            if not _BOILER.match(c) and c.strip("【】") != name:
                ctx.insert(0, c.strip("【】"))
        desc = ""
        for j in range(i + 1, min(len(lines), i + 5)):
            c = lines[j]
            if extract_period(c)[0] or re.fullmatch(r"[🔥✨\s]*(活动)?说明[:：]?", c) or _BOILER.match(c):
                continue
            desc = re.sub(r"^\d+[.、．]\s*", "", c)[:90]
            break
        sub = " / ".join(ctx + ([desc] if desc else []))
        seg = "\n".join(lines[i + 1:i + 14])[:900]  # 这个活动后面的说明（到下一个活动为止的大概范围），重写副标题用
        key = (name, st, en)
        if name and key not in seen:
            seen.add(key)
            out.append((name, st, en, sub, seg))
    return out


# 副标题里不要的套话：参与条件、入口、维护说明之类
_BOILER = re.compile(r"^(参与条件|活动入口|活动地点|活动规则)|^【?新增内容通知】?$|直接更新以下内容|不停服|^(新闻|公告|活动|相册)[:：]?$")


_SCRIPT = re.compile(r'(?is)<script[^>]+src=["\']([^"\']+\.js[^"\']*)')


def _list_summary(text: str, title: str) -> str:
    """新闻列表里链接文字常是「新闻 / 标题 / 摘要」：只取摘要那句。"""
    for ln in reversed([x.strip() for x in (text or "").split("\n") if x.strip()]):
        if ln != title and title not in ln and not re.fullmatch(r"新闻|公告|活动|相册", ln):
            return ln[:90]
    return ""



def banner_period(text: str, ref: datetime) -> tuple[datetime | None, datetime | None]:
    """图片 banner 上的日期，识别出来常常粘在一起：「10月19日5:00~10月27日4:59」「10/195:00 11/54:59」
    「10月21日5:0012月18日4:59」（箭头没识别出来）。"""
    found = []
    for m in re.finditer(r"(\d{1,2})[月/](\d{1,2})日?\s*(\d{1,2}):(\d{2})", text or ""):
        mo, dd, hh, mi = map(int, m.groups())
        if not (1 <= mo <= 12 and 1 <= dd <= 31 and hh < 24 and mi < 60):
            continue
        y = ref.year + (1 if mo < ref.month - 6 else 0) - (1 if mo > ref.month + 6 else 0)
        try:
            found.append(datetime(y, mo, dd, hh, mi, tzinfo=BJ))
        except ValueError:
            pass
    if len(found) >= 2:
        return found[0], found[1]
    return (found[0], None) if found else (None, None)


def after_note(text: str, start: datetime | None) -> str:
    """开始时间写的是「10月22日更新后」「维护后」这种：时分不知道，返回 "更新后" / "维护后"，界面上照原话显示，不写 00:00。"""
    if not start or (start.hour, start.minute) != (0, 0):
        return ""
    m = re.search(rf"(?:\d{{4}}年)?0?{start.month}月0?{start.day}日\s*(?:版本)?(更新|维护|开服)后", _ampm(text or "")) or \
        re.search(rf"(?:\d{{4}}/)?0?{start.month}/0?{start.day}\s*(?:版本)?(更新|维护|开服)后", text or "")  # 「11/05维护后」
    return m.group(1) + "后" if m else ""


_ART_SEP = re.compile(r"(?<=[\u4e00-\u9fff])\s*[+＋·•.。,，|丨/\\_\-~]+\s*(?=[\u4e00-\u9fff])")


def fix_art_title(title: str, notice: str = "") -> str:
    """艺术字标题：每个字单独识别出来，中间夹着「+」「·」之类（「鸢+舞+长+空」→「鸢舞长空」）。
    只在每段都是一个字时才拼起来（「密探特训·四十五期」这种正常的不动）；公告里有【同字数、多数字相同】的名字时用公告里的写法。"""
    parts = [x for x in _ART_SEP.split(title or "") if x]
    t = "".join(parts) if len(parts) >= 3 and all(len(x) == 1 for x in parts) else (title or "")
    if t and notice and t not in notice:
        for m in re.finditer(r"【([^】]{2,12})】", notice):
            n = m.group(1)
            if len(n) == len(t) and sum(a == b for a, b in zip(n, t)) * 2 > len(t):
                return n
    return t


def forecast_from_text(text: str, ref: datetime, game: str, src_id: str, src_title: str) -> list[dict]:
    """公告里的「后续更新内容预告」：按日期分段、按「1、2、」分条，变成「预告」条目（时间线上用虚线显示）。
    例：「10月29日\n1、……开启新历险活动（11月1日开启）\n2、神秘洞窟迎来全新敌人（11月1日开启）\n11月5日\n1、新增左慈限时活动【建木培植志】」
    条目里写了「（M月D日开启）」的整条按它；没写结束时间的，先画一天。正式公告出来后（同名活动），预告条目自动不显示。"""
    i = text.find("预告")
    if i < 0:
        return []
    seg = text[i:]
    end = re.search(r"\n(感谢|发件人|近期收到)", seg)
    seg = seg[:end.start()] if end else seg
    out, day = [], None
    for ln in seg.split("\n"):
        ln = ln.strip()
        m = re.fullmatch(r"(\d{1,2})月(\d{1,2})日[：:]?", ln)
        if m:
            day = (int(m.group(1)), int(m.group(2)))
            continue
        m = re.match(r"^(\d+)[、.．]\s*(.+)", ln)
        if not m or not day:
            continue
        whole = m.group(2)
        # 一条里写了「（M月D日开启）」的，整条都按这个日期（10-28 用户定：以原文写的日期为准，不管列在哪个日期下面）；
        # 「A，同时 B（11月1日开启）」照样拆成两条，两条都用 11月1日
        m2 = re.search(r"[（(](\d{1,2})月(\d{1,2})日\s*开启[）)]", whole)
        for body in [x for x in re.split(r"[，,]\s*(?:同时|并且|并|另外)", whole) if x.strip()]:
            mo, dd = day
            if m2:
                mo, dd = int(m2.group(1)), int(m2.group(2))
                body = body.replace(m2.group(0), "")
            st, _ = banner_period(f"{mo}月{dd}日0:00", ref)
            if not st:
                continue
            name = re.search(r"【([^】]{2,16})】", body)
            title = name.group(1) if name else re.split(r"[，,。；;]", body)[0].strip()
            title = re.sub(r"^(新增|开启|全新)", "", title)[:30]
            if not title:
                continue
            out.append({"id": f"{src_id}:fc:{hashlib.sha1((title + str(st.date())).encode()).hexdigest()[:10]}", "game": game,
                        "source": src_id, "kind": "预告", "title": title, "start": _fmt(st), "end": _fmt(st + timedelta(days=1)),
                        "start_note": "预告", "forecast": True, "banner_url": "", "url": "", "content": "",
                        "subtitle": whole.strip()[:90], "source_title": src_title + " · 后续更新预告", "text": whole.strip()})
    return out


_ANY_IMG = re.compile(r'(?is)<img[^>]+?(?:data-src|data-original|src)=["\']([^"\']+\.(?:jpg|jpeg|png|webp)(?:\?[^"\']*)?)["\']')
_JUNK_IMG = re.compile(r"(?i)nie\.topBar|/comm/|/share\.|logo|icon|qrcode|erweima|ewm|avatar|loading|blank|btn|\.gif")


_GENERIC = re.compile(r"^(公告|活动|预告|活动预告|限时活动|新活动|福利|重要|通知|更新|维护|新闻|爆料|情报|速报|官方|置顶|抽奖|互动"
                      r"|活动返场|活动复刻|活动开启|活动玩法|(活动)?(复刻)?说明|玩法说明|全新照片墙|照片墙|系统更新|版本更新|新增内容"
                      r"|第\s*\d+\s*期|\d+\s*期)$")


def _bracket_name(s: str) -> str:
    """【活动返场·往日拾遗】→ 往日拾遗；【怪谈：时融|活动玩法】→ 怪谈：时融；【季旅专列·第13期】→ 季旅专列（去掉套话和期数）。"""
    parts = [x.strip() for x in re.split(r"[·•|｜丨/]", s) if x.strip()]
    keep = [x for x in parts if not _GENERIC.match(x)]
    return "·".join(keep)


def guess_name(text: str) -> str:
    """一段官方帖子里的活动名（11-02，B 站 / wiki / TapTap 共用），按顺序：
    第一行里的「」→ 第一行里非套话的【】→ 第一行被表情隔开的第一段（「✨白马入雒🐫限时机率提升」→ 白马入雒）
    → 前三行里的「」→ 第一行去掉话题 #…# 和【…】。"""
    # 只有话题的行（「#时空中的绘旅人#」）不算第一行
    lines = [x.strip() for x in (text or "").split("\n") if re.sub(r"#[^#]{1,30}#", "", x).strip()]
    if not lines:
        return ""
    first = re.sub(r"#[^#]{1,30}#", "", lines[0]).strip()
    m = re.search(r"「([^」]{2,24})」", first)
    if m:
        return m.group(1).strip()
    for m in re.finditer(r"【([^】]{2,30})】", first):
        nm = _bracket_name(m.group(1))
        if len(nm) >= 2:
            return nm[:30]
    line = re.sub(r"#[^#]{1,30}#|【[^】]{0,12}】|\[[^\]]{0,12}\]", "", first).strip(" ：:!！~～")
    parts = [x.strip(" ·:：!！~～") for x in re.split(r"[\u2600-\u27BF\U0001F000-\U0001FAFF\uFE0F]+", line)]
    parts = [x for x in parts if len(x) >= 2 and not _GENERIC.match(x)]
    if len(parts) > 1:
        return parts[0][:30]
    m = re.search(r"「([^」]{2,24})」", "\n".join(lines[:3]))
    if m:
        return m.group(1).strip()
    return (parts[0] if parts else line)[:30]


def pick_img(art: str) -> str:
    """文章页的题图（11-02）：og:image 和正文里的图，跳过网站顶栏（网易 nie.topBar）、分享图、logo、二维码这类；
    正文（「时间：」之后）里的第一张优先。都没有返回空。"""
    k = re.search(r"(发布)?时间[:：]", art)
    body = art[k.start():] if k else art
    cands = [m.group(1) for m in _ANY_IMG.finditer(body)]
    og = _OG_IMG.search(art)
    cands += [og.group(1)] if og else []
    cands += [m.group(1) for m in _ANY_IMG.finditer(art)]
    return next((c for c in cands if not _JUNK_IMG.search(c)), "")


def _article_body(body: str) -> str:
    """官网文章页：去掉正文前面的网站导航（网易游戏全目录之类），从「时间：」那一行之后开始。"""
    lines = body.split("\n")
    k = next((i for i, x in enumerate(lines) if re.match(r"\s*(发布)?时间[:：]", x)), -1)
    return "\n".join(lines[k + 1:]) if 0 <= k < len(lines) - 1 else body


def _norm(t: str) -> str:
    t = re.sub(r"[\s「」『』《》【】\[\]（）()·:：!！?？,，。.丨|｜]", "", t or "")
    return re.sub(r"(现已|正式)?(开启|开放|上线)$", "", t)


def img_size(path) -> tuple[int, int]:
    """图片宽高（只读文件头：PNG / JPEG / GIF / WEBP），读不出返回 (0, 0)。"""
    import struct
    try:
        with open(path, "rb") as f:
            b = f.read(256 * 1024)
    except OSError:
        return 0, 0
    try:
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", b[16:24])
        if b[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", b[6:10])
        if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            if b[12:16] == b"VP8X":
                return 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")
            if b[12:16] == b"VP8 ":
                w, h = struct.unpack("<HH", b[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if b[12:16] == b"VP8L":
                v = int.from_bytes(b[21:25], "little")
                return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
        if b[:2] == b"\xff\xd8":
            i = 2
            while i < len(b) - 9:
                if b[i] != 0xFF:
                    i += 1
                    continue
                m = b[i + 1]
                if m in (0xC0, 0xC1, 0xC2, 0xC3):
                    h, w = struct.unpack(">HH", b[i + 5:i + 9])
                    return w, h
                i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
    except Exception:
        pass
    return 0, 0


BANNER_ASPECT = 2.7  # 活动页轮播的宽高比（约 1200×440）：合并时挑和它最接近的图当题图


def pick_banner(names: list[str], img_dir) -> str:
    """合并成一个活动时挑题图（11-02）：
    1. 宽高比接近轮播（2:1 ~ 3.6:1，铺满时几乎不裁）的宽图，越接近越好；
    2. 能完整显示的竖图（卡面这类，高不超过宽的 2.2 倍），越大越好；
    3. 其余（16:9、方图、长图），按宽高比接近程度；
    600 宽以下的游戏内小截图排在最后。"""
    import math
    best, key = "", None
    for n in names:
        w, h = img_size(Path(img_dir) / n)
        if not w or not h:
            continue
        a = w / h
        if w < 600:
            k = (3, abs(math.log(a / BANNER_ASPECT)))
        elif 2.0 <= a <= 3.6:
            k = (0, abs(math.log(a / BANNER_ASPECT)))
        elif h > w and h <= 2.2 * w:
            k = (1, -min(w, 2000))
        else:
            k = (2, abs(math.log(a / BANNER_ASPECT)))
        if key is None or k < key:
            best, key = n, k
    return best or (names[0] if names else "")
