"""B 站官方号动态（11-02，先给时空中的绘旅人用）：活动宣传图是原图，比游戏内公告的小题图清楚，也比官网更新快。

不用登录（这是给所有人用的功能，不能依赖谁的账号）。照 B 站网页自己的做法匿名读：
  1. /x/frontend/finger/spi 领一个匿名设备号（buvid3 / buvid4），放进 cookie；
  2. /x/web-interface/nav 拿当天的 WBI 签名密钥（没登录也给）；
  3. /x/polymer/web-dynamic/v1/feed/space 带签名和网页指纹参数读动态（最多两页）。
主接口被风控（-352 / -412）时退回旧接口 dynamic_svr/space_history；都不行就抛错，来源状态里写原因，别的来源照常。

来源配置：{"type": "bili_dyn", "mid": "<B 站 UID>", "img_rank": 3.5}
- 动态里写了活动时间的 → 一条活动（一篇写了好几个活动的拆开）；配图（横图）当题图；
- 没写时间、但有「活动名」和横图的 → 只当题图（img_only），按名字配给别的来源里同名的活动。
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import random
import re
import string
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from ..common import BJ, UA, _fmt, _now, extract_activities, extract_period, guess_name

MIXIN = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39,
         12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63,
         57, 62, 11, 36, 20, 34, 44, 52]
# 网页版发请求时带的「浏览器指纹」参数（固定值即可；不带的话匿名请求很容易被风控）
DM = {"dm_img_list": "[]", "dm_img_str": "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ",
      "dm_cover_img_str": "QU5HTEUgKEludGVsLCBJbnRlbChSKSBVSEQgR3JhcGhpY3MgNjMwIERpcmVjdDNEMTEgdnNfNV8wIHBzXzVfMCwgRDNEMTEpR29vZ2xlIEluYy4gKEludGVsKQ",
      "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}'}


class BiliError(RuntimeError):
    pass


class Client:
    def __init__(self, mid: str, data_dir: Path | None = None):
        self.mid = str(mid)
        self.data_dir = data_dir
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.referer = f"https://space.bilibili.com/{self.mid}/dynamic"

    def _cookie(self, name: str, value: str):
        self.jar.set_cookie(http.cookiejar.Cookie(0, name, value, None, False, ".bilibili.com", True, True, "/", True,
                                                  False, int(time.time()) + 86400 * 30, False, None, None, {}))

    def get(self, url: str, raw: str = "") -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": self.referer, "Origin": "https://space.bilibili.com",
                                                   "Accept": "application/json, text/plain, */*", "Accept-Language": "zh-CN,zh;q=0.9"})
        for attempt in (1, 2):
            try:
                with self.op.open(req, timeout=20) as r:
                    body = r.read()
                break
            except urllib.error.HTTPError as e:
                raise BiliError(f"HTTP {e.code}")
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2)
        if raw and self.data_dir:  # 排查用：最近一次的原始返回
            p = self.data_dir / "raw" / f"{raw}.txt"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(f"URL: {url}\n\n".encode() + body[:400_000])
        try:
            return json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            raise BiliError("返回的不是 JSON（可能被拦截）")

    def setup(self):
        """匿名设备号 + 当天的签名密钥。"""
        try:
            d = self.get("https://api.bilibili.com/x/frontend/finger/spi").get("data") or {}
            if d.get("b_3"):
                self._cookie("buvid3", d["b_3"])
            if d.get("b_4"):
                self._cookie("buvid4", d["b_4"])
        except Exception:
            pass  # 没领到设备号也试试
        self._cookie("b_nut", str(int(time.time())))
        try:  # 网页也会先领一个 bili_ticket（有它被限流得少一些）；领不到不影响
            import hmac
            ts = int(time.time())
            sign = hmac.new(b"XgwSnGZ1p", f"ts{ts}".encode(), hashlib.sha256).hexdigest()
            req = urllib.request.Request("https://api.bilibili.com/bili-ticket/v1/GenWebTicket?" + urllib.parse.urlencode(
                {"key_id": "ec02", "hexsign": sign, "context[ts]": ts, "csrf": ""}), data=b"", method="POST",
                headers={"User-Agent": UA, "Referer": self.referer})
            with self.op.open(req, timeout=15) as r:
                t = (json.loads(r.read().decode("utf-8", "replace")).get("data") or {}).get("ticket")
            if t:
                self._cookie("bili_ticket", t)
        except Exception:
            pass
        self._cookie("_uuid", "".join(random.choices(string.hexdigits.upper(), k=32)) + "infoc")
        nav = self.get("https://api.bilibili.com/x/web-interface/nav").get("data") or {}
        img = (nav.get("wbi_img") or {})
        key = "".join(Path(urllib.parse.urlparse(img.get(k, "")).path).stem for k in ("img_url", "sub_url"))
        if len(key) < 64:
            raise BiliError("没拿到签名密钥（wbi_img）")
        self.mixin = "".join(key[i] for i in MIXIN)[:32]

    def signed(self, params: dict) -> str:
        p = {**params, "wts": int(time.time())}
        p = {k: re.sub(r"[!'()*]", "", str(v)) for k, v in sorted(p.items())}
        q = urllib.parse.urlencode(p, quote_via=urllib.parse.quote)
        return q + "&w_rid=" + hashlib.md5((q + self.mixin).encode()).hexdigest()

    def feed(self, pages: int = 2) -> list[dict]:
        """新接口：返回原始动态条目。"""
        self.setup()
        out, offset = [], ""
        for k in range(pages):
            q = self.signed({"host_mid": self.mid, "offset": offset, "timezone_offset": -480,
                             "platform": "web", "features": "itemOpusStyle", "web_location": "333.1387", **DM})
            d = self.get("https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?" + q, raw=f"bili_{self.mid}_{k}")
            if d.get("code") != 0:
                raise BiliError(f"B 站返回 {d.get('code')}：{d.get('message', '')}")
            data = d.get("data") or {}
            out += data.get("items") or []
            offset = data.get("offset") or ""
            if not data.get("has_more") or not offset:
                break
            time.sleep(1.5)
        return out

    def opus(self) -> list[dict]:
        """空间「图文」列表（11-02：新接口匿名时常给空列表、旧接口已停用 404，再试这个）。返回原始条目。"""
        if not getattr(self, "mixin", ""):
            self.setup()
        out, offset = [], ""
        for k in (1, 2):  # 一页 20 条，读两页（大约一个月）
            q = self.signed({"host_mid": self.mid, "page": k, "offset": offset, "type": "all", "web_location": "333.1387", **DM})
            d = self.get("https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/feed/space?" + q,
                         raw=f"bili_{self.mid}_opus" + ("" if k == 1 else "2"))
            if d.get("code") != 0:
                if out:
                    break
                raise BiliError(f"图文列表返回 {d.get('code')}：{d.get('message', '')}")
            data = d.get("data") or {}
            out += data.get("items") or []
            offset = data.get("offset") or ""
            if not data.get("has_more") or not offset:
                break
            time.sleep(1.2)
        return out

    def opus_detail(self, oid: str, raw: str = "") -> dict:
        """一条图文的详情（11-02：图文列表只给封面，帖子里的多张图要看详情）。"""
        if not getattr(self, "mixin", ""):
            self.setup()
        q = self.signed({"id": oid, "timezone_offset": -480, "features": "onlyfansVote,onlyfansAssetsV2,decorationCard,htmlNewStyle,ugcDelete,editable,opusPrivateVisible",
                         "web_location": "333.1368", **DM})
        d = self.get("https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/detail?" + q, raw=raw)
        if d.get("code") != 0:
            raise BiliError(f"详情返回 {d.get('code')}：{d.get('message', '')}")
        return d.get("data") or {}

    def history(self) -> list[dict]:
        """旧接口（不要签名）：返回原始卡片。"""
        d = self.get("https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/space_history?"
                     + urllib.parse.urlencode({"host_uid": self.mid, "offset_dynamic_id": 0, "need_top": 1, "platform": "web"}),
                     raw=f"bili_{self.mid}_old")
        if d.get("code") != 0:
            raise BiliError(f"旧接口返回 {d.get('code')}：{d.get('message') or d.get('msg', '')}")
        return (d.get("data") or {}).get("cards") or []


# ---------------------------------------------------------------- 解析成统一的「帖子」
def _https(u: str) -> str:
    u = (u or "").strip()
    return "https:" + u if u.startswith("//") else re.sub(r"^http:", "https:", u)


def posts_from_feed(items: list[dict]) -> list[dict]:
    """新接口的条目 → [{id, ts, text, title, pics:[(url,w,h)], url, top}]（转发的不要）。"""
    out = []
    for it in items:
        if it.get("type") in ("DYNAMIC_TYPE_FORWARD", "DYNAMIC_TYPE_LIVE_RCMD"):
            continue
        mods = it.get("modules") or {}
        au = mods.get("module_author") or {}
        dyn = mods.get("module_dynamic") or {}
        major = dyn.get("major") or {}
        text, title, pics = (dyn.get("desc") or {}).get("text") or "", "", []
        if major.get("opus"):
            op = major["opus"]
            title = op.get("title") or ""
            text = ((op.get("summary") or {}).get("text") or "") or text
            pics = [(p.get("url", ""), p.get("width") or 0, p.get("height") or 0) for p in op.get("pics") or []]
        if major.get("draw"):
            pics = [(p.get("src", ""), p.get("width") or 0, p.get("height") or 0) for p in major["draw"].get("items") or []]
        if major.get("archive"):  # 视频（PV）：封面
            a = major["archive"]
            title = title or a.get("title", "")
            text = text or a.get("desc", "")
            pics = [(a.get("cover", ""), 16, 9)]
        if major.get("article"):
            a = major["article"]
            title = title or a.get("title", "")
            text = text or a.get("desc", "")
            pics = [(c, 16, 9) for c in a.get("covers") or []]
        ts = int(au.get("pub_ts") or 0)
        out.append({"id": str(it.get("id_str") or ""), "ts": ts, "text": text, "title": title,
                    "pics": [(_https(u), w, h) for u, w, h in pics if u], "top": (mods.get("module_tag") or {}).get("text") == "置顶",
                    "url": f"https://www.bilibili.com/opus/{it.get('id_str')}"})
    return out


def posts_from_opus(items: list[dict]) -> list[dict]:
    """「图文」列表的条目：只有摘要和封面，没有发布时间（用读取时间代替，活动时间以正文为准）。"""
    out = []
    for it in items:
        oid = str(it.get("opus_id") or it.get("id_str") or "")
        if not oid:
            m = re.search(r"/opus/(\d+)", it.get("jump_url", ""))
            oid = m.group(1) if m else ""
        cov = it.get("cover") or {}
        text = it.get("content") or it.get("title") or ""
        if isinstance(text, dict):
            text = text.get("text") or ""
        pics = [(cov.get("url", ""), cov.get("width") or 0, cov.get("height") or 0)] if cov.get("url") else []
        if oid and text:
            out.append({"id": oid, "ts": int(it.get("pub_ts") or it.get("ts") or time.time()), "text": text, "title": "",
                        "pics": [(_https(u), w, h) for u, w, h in pics], "top": False,
                        "url": f"https://www.bilibili.com/opus/{oid}"})
    return out


def detail_pics(data: dict) -> tuple[list, int]:
    """详情里的图（帖子正文 / 顶部图集里所有 bfs 图片，按出现顺序去重）和发布时间。"""
    pics, seen, ts = [], set(), 0

    def walk(x):
        nonlocal ts
        if isinstance(x, dict):
            u = x.get("url") or x.get("src") or ""
            if isinstance(u, str) and "/bfs/" in u and re.search(r"\.(jpe?g|png|webp|gif)$", u.split("@")[0]) \
                    and "/face/" not in u and "/garb/" not in u and "/emote/" not in u:
                u = _https(u)
                if u not in seen:
                    seen.add(u)
                    pics.append((u, x.get("width") or 0, x.get("height") or 0))
            if not ts and str(x.get("pub_ts") or "").isdigit():
                ts = int(x["pub_ts"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(data.get("item") or data)
    pics = [p for p in pics if not (p[1] and p[1] < 200)]  # 小图标不要
    return pics, ts


def posts_from_history(cards: list[dict]) -> list[dict]:
    out = []
    for c in cards:
        desc = c.get("desc") or {}
        if desc.get("type") == 1:  # 转发
            continue
        try:
            card = json.loads(c.get("card") or "{}")
        except json.JSONDecodeError:
            continue
        item = card.get("item") or {}
        text = item.get("description") or item.get("content") or card.get("desc") or card.get("dynamic") or ""
        title = item.get("title") or card.get("title") or ""
        pics = [(p.get("img_src", ""), p.get("img_width") or 0, p.get("img_height") or 0) for p in item.get("pictures") or []]
        if not pics and card.get("pic"):
            pics = [(card["pic"], 16, 9)]
        if not pics and card.get("image_urls"):
            pics = [(u, 16, 9) for u in card["image_urls"]]
        did = str(desc.get("dynamic_id_str") or desc.get("dynamic_id") or "")
        out.append({"id": did, "ts": int(desc.get("timestamp") or 0), "text": text, "title": title,
                    "pics": [(_https(u), w, h) for u, w, h in pics if u], "top": False,
                    "url": f"https://t.bilibili.com/{did}"})
    return out


def _banner(pics) -> str:
    """优先第一张横图；没有横图就用第一张（竖版长图：页面上只露最上面的标题部分，11-02）。太大的按 1920 宽取。"""
    land = [p for p in pics if not (p[1] and p[2] and p[1] < p[2] * 1.2)]
    for u, w, h in land + list(pics):
        return u + ("@1920w.jpg" if "hdslb.com" in u and "@" not in u else "")
    return ""


def _name(post: dict) -> str:
    """活动名：书名号「」里的（第一行或标题里），否则第一行去掉【…】和话题。"""
    head = (post["title"] + "\n" + post["text"]).strip()
    first = "\n".join(head.split("\n")[:3])
    m = re.search(r"「([^」]{2,24})」", first)
    if m:
        return m.group(1).strip()
    line = next((x for x in head.split("\n") if x.strip()), "")
    line = re.sub(r"#[^#]{1,30}#|【[^】]{0,12}】|\[[^\]]{0,12}\]", "", line).strip(" ：:!！~～")
    return line[:30]


def to_items(posts: list[dict], src: dict, now: datetime) -> list[dict]:
    out = []
    rank = float(src.get("img_rank", 3.5))
    for p in posts:
        if not p["ts"]:
            continue
        ref = datetime.fromtimestamp(p["ts"], BJ)
        if now - ref > timedelta(days=60) and not p["top"]:
            continue
        text = re.sub(r"\r", "", p["text"])
        banner = _banner(p["pics"])
        alls = [u + ("@1920w.jpg" if "hdslb.com" in u and "@" not in u else "") for u, _, _ in p["pics"]]
        base = {"game": src["game"], "source": src["id"], "url": p["url"], "content": "", "img_rank": rank,
                "source_title": "B 站官方号动态", "seen_at": _fmt(ref),
                "banner_urls": [banner] + [u for u in alls if u != banner] if banner else []}  # 11-02：一条动态的所有图都下
        acts = extract_activities(text)
        if len(acts) > 1:  # 一条动态写了好几个活动
            for k, (name, st, en, sub, seg) in enumerate(acts):
                out.append({**base, "id": f"{src['id']}:{p['id']}:{k}", "kind": "活动", "title": name,
                            "start": _fmt(st), "end": _fmt(en), "banner_url": banner if k == 0 else "",
                            "subtitle": sub, "text": seg})
            continue
        st, en = extract_period(text, ref)
        name = guess_name((p["title"] + "\n" + p["text"]).strip())
        if not name:
            continue
        sub = next((x.strip() for x in text.split("\n") if len(x.strip()) >= 8 and name not in x), "")[:90]
        if st:
            out.append({**base, "id": f"{src['id']}:{p['id']}", "kind": "活动", "title": name, "start": _fmt(st),
                        "end": _fmt(en), "banner_url": banner, "subtitle": sub, "text": text[:900]})
        elif banner and re.search(r"「[^」]{2,24}」", (p["title"] + p["text"])[:200]):  # 宣传图：只当题图，配给同名活动
            out.append({**base, "id": f"{src['id']}:{p['id']}", "kind": "活动", "title": name, "start": "", "end": "",
                        "banner_url": banner, "subtitle": "", "text": "", "img_only": True})
    return out


def read(src: dict, data_dir: Path, miss) -> list[dict]:
    c = Client(src["mid"], data_dir)
    errs, posts = [], []
    try:
        posts = posts_from_feed(c.feed())
    except Exception as e:
        errs.append(f"新接口：{e}")
    # 11-02：新接口匿名时常常只给几条；就算给够了也只到两三周前。再读「图文」列表（约 40 条、一个多月）补上，
    # 不够再试旧接口。图文列表只有封面：还在进行 / 没写时间的帖子读一下详情，拿全帖子里的图
    for name, fn, conv in (("图文列表", c.opus, posts_from_opus), ("旧接口", c.history, posts_from_history)):
        if name == "旧接口" and len(posts) >= 8:
            break
        try:
            have = {p["id"] for p in posts}
            more = [p for p in conv(fn()) if p["id"] not in have]
            if name == "图文列表":
                now = _now()
                ends = {p["id"]: extract_period(p["text"], now)[1] for p in more}
                # 写了结束时间、还没结束的先读（活动本身），没写时间的（宣传图、预告）排后面；最多 30 条
                live = [p for p in more if ends[p["id"]] and ends[p["id"]] >= now] + [p for p in more if not ends[p["id"]]]
                for k, p in enumerate(live[:30]):
                    try:
                        pics, ts = detail_pics(c.opus_detail(p["id"], raw=f"bili_{c.mid}_detail" if k == 0 else ""))
                        if pics:
                            p["pics"] = pics
                        if ts:
                            p["ts"] = ts
                    except Exception as e:
                        miss.add("帖子详情读不到（只用了封面）", e)
                    time.sleep(0.5)
            posts += more
            if more and len(have) < 8:
                miss.add(f"新接口没给全，用了{name}", errs[0] if errs else "匿名访问被限流", 0)
        except Exception as e2:
            errs.append(f"{name}：{e2}")
    if not posts:
        raise BiliError("B 站对不登录的访问没给动态（返回空列表）" + (f"；{'；'.join(errs)}" if errs else "") + "。过一会儿再读")
    return to_items(posts, src, _now())
