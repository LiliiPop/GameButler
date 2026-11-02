"""活动日历：分类、角色识别、副标题重写、用户的关注 / 屏蔽设置。

分类和重写都在「读出来给界面」时做（news.load），改了规则不用重新抓取。
用户设置存在 data/news_prefs.json：
  hidden_items   不再关注的活动 id
  hidden_cats    {"*": [类别…], "<游戏>": [类别…]}  不再关注的类别
  cat_override   {活动 id: 类别}  手动改过的类别
  tag_override   {活动 id: 标签}  手动改过的标签（日历左边那一小格，默认按类别和游戏自动起）
  user_cats      {类别 id: 名称}  自己建的类别（id 以 u_ 开头）
  date_override  {活动 id: {"start": "YYYY-MM-DD HH:MM", "end": …}}  自己改的起止时间（北京时间，空 = 用识别的）
  track          {"<游戏>": [角色…]}  追踪的角色
  extra_chars    {"<游戏>": [角色…]}  用户补充的角色名
  followed       关注（加星标）的活动 id
  asked          追踪角色提醒已经问过的活动 id（不再重复问）
  push_followed  关注的活动随每日汇总推送到微信
  push_images    推送时带题图
  fetch_all      连「版本更新公告」「说明类公告」也抓（默认不抓）
"""
from __future__ import annotations

import re
from pathlib import Path

# 类别：id → (名称, 默认显示)
CATS = {
    "pool": ("限定卡池", True),
    "rerun": ("复刻卡池", True),
    "version": ("版本活动", True),
    "event": ("活动", True),
    "welfare": ("福利活动", True),
    "shop": ("商城上新", True),
    "pass": ("大月卡", True),
    "sweet": ("专属甜心", True),          # 未定事件簿的专属甜心系统（图纸等）
    "merch": ("周边上新", True),
    "qxqy": ("千星奇域", True),
    "other": ("其他", True),
    "cycle": ("周期 / 重置", True),
    "update": ("版本更新公告", False),
    "notice": ("说明类公告", False),
    "resident": ("常驻", False),
}
DROP = {"update", "notice"}           # 默认不抓取
HIDDEN = {"update", "notice", "resident"}

# 各游戏的大月卡叫法
PASS_NAMES = {"genshin": "纪行", "tot": "绮思", "starrail": "无名勋礼", "lysk": "密约"}
# 各游戏抽卡的叫法（判定卡池用）
POOL_WORDS = {
    "genshin": r"祈愿", "starrail": r"跃迁", "lysk": r"许愿|思念", "tot": r"SSR|女神之影|启示|心之所向|限定卡|卡池",
    "sh": r"画灵|SSR|卡池|召唤", "yuan": r"传唤|卡池|UP|up|概率提升",
}
# 角色名单（种子；卡池标题里「角色·卡名」的写法会自动补充）
CHARS = {
    "lysk": ["沈星回", "黎深", "祁煜", "秦彻", "夏以昼"],
    "sh": ["叶瑄", "艾因", "路辰", "罗夏", "司岚"],
    "tot": ["左然", "莫弈", "夏彦", "陆景和"],
    "yuan": ["刘辩", "袁基", "左慈", "孙策", "傅融", "张角", "孙权", "曹丕", "董卓", "吕布"],
}

R = lambda *a: re.compile("|".join(a))
NOTICE = R(r"防沉迷", r"FAQ", r"常用问题", r"声明", r"问卷", r"玩家社区", r"社区一览", r"公平运营", r"福利速览", r"内容一览",
           r"世界任务说明", r"反诈", r"诈骗", r"创作激励", r"获奖名单", r"补偿", r"实名", r"隐私", r"用户协议", r"招募",
           r"社媒", r"小程序", r"跃迁记录统计", r"祈愿记录", r"紊乱地脉", r"活动一览$", r"版本活动一览",
           r"重置说明", r"机制说明", r"任务说明", r"开启公告说明", r"规则说明", r"调研")
UPDATE = R(r"更新说明", r"版本更新", r"维护", r"修复", r"不停服", r"更新公告", r"优化", r"问题说明", r"已知问题",
           r"新增内容公告", r"更新预告", r"停服", r"客户端")
MERCH = R(r"周边", r"手办", r"实体", r"线下", r"快闪", r"印章", r"通贩", r"谷子", r"徽章", r"立牌", r"抱枕", r"官方商城",
          r"服饰新品", r"联名")
WELFARE = R(r"累充", r"累计充值", r"签到", r"登录", r"赠送", r"免费", r"福利", r"回馈", r"抽奖", r"补给", r"每日领取",
            r"存粮", r"领取奖励", r"自选邀请", r"自选.*角色")
RERUN = R(r"复刻", r"返场", r"重临", r"再临", r"回归")
SHOP = R(r"礼包", r"外观", r"时装", r"服装", r"服饰", r"家具", r"上架", r"上新", r"商城", r"兑换", r"装扮", r"头像框")
VERSION = R(r"版本活动", r"周年", r"主题活动", r"主线", r"庆典", r"生日", r"版本.*活动", r"嘉年华", r"节日")
EVENT = R(r"活动", r"挑战", r"玩法", r"限时", r"奇遇", r"采风", r"对决", r"副本", r"时限内")


# 日历左边的标签：没写的取类别名前两个字
TAG = {"pool": "限定", "rerun": "复刻", "version": "版本", "event": "活动", "welfare": "福利", "shop": "商城", "pass": "大月卡",
       "sweet": "甜心", "merch": "周边", "qxqy": "千星", "other": "其他", "cycle": "周期", "update": "更新", "notice": "说明", "resident": "常驻"}


def auto_tag(it: dict, cat: str) -> str:
    t = (it.get("title") or "") + " " + (it.get("subtitle") or "")
    if cat == "pass":  # 大月卡按各游戏自己的叫法
        return PASS_NAMES.get(it.get("game", ""), TAG["pass"])
    if cat == "shop":
        for word, tag in ((r"家具|家装|家居", "家居"), (r"服装|服饰|时装|套装|装扮", "服饰"), (r"配饰|饰品", "配饰"), (r"礼包", "礼包")):
            if re.search(word, it.get("title") or "") or (tag != "礼包" and re.search(word, t)):
                return tag
        return TAG["shop"]
    if cat == "sweet":
        return "图纸" if "图纸" in t else TAG["sweet"]
    return TAG.get(cat, "")


def _plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def classify(it: dict, names: list[str] | None = None) -> str:
    """主要看标题；副标题只在判断「版本活动 / 小活动」时参考（副标题里常有礼包、徽章之类的字，容易误判）。"""
    g = it.get("game", "")
    t = it.get("title", "") or ""
    sub = it.get("subtitle", "") or ""
    head = t + " " + sub
    # 11-02：官方号 / wiki / TapTap 的帖子标题常常只是活动名（「白马入雒」），类别看帖子开头两行（「✨白马入雒🐫限时机率提升」）
    lead = " ".join([x for x in (it.get("text") or "").split("\n") if x.strip()][:2])
    if not (it.get("source") or "").endswith("_ingame") and re.search(r"[概机]率(提升|UP|up)|UP许愿|限时传唤|限时.{0,4}(许愿|祈愿|跃迁)", t + " " + lead):
        return "rerun" if re.search(r"复刻|返场", t + " " + lead) else "pool"
    if (it.get("source") or "").startswith("yuan_ingame"):
        # 代号鸢活动页：标题只是活动名（「棺珠折骨」），类别要看下面那句说明（「【绝密·密探】限时概率提升」）
        if re.search(r"概率提升|概率UP|概率up|限时传唤", sub):
            return "rerun" if re.search(r"复刻|返场", head) else "pool"
        t = head
    if it.get("kind") == "常驻" and not re.search(r"时限内|限时", t):  # 跨版本的限时奖励（如「时限内完成探索任务」）仍显示
        return "resident"
    if g == "genshin" and re.search(r"米游社.*签到", head):
        return "resident"
    if NOTICE.search(t):
        return "notice"
    if UPDATE.search(t) and not EVENT.search(t.replace("更新", "")):
        return "update"
    if g == "genshin" and (re.search(r"千星|奇域|奇偶|绮星", head) or re.search(r"千星奇域|奇偶", _plain(clean_text(it.get("text", "")))[:600])):
        return "qxqy"
    if g in PASS_NAMES and PASS_NAMES[g] in t:
        return "pass"
    if MERCH.search(t):
        return "merch"
    if g == "tot" and "图纸" in t:  # 专属甜心的家装图纸更新
        return "sweet"
    cn = _card_name(t)
    roles = names if names is not None else CHARS.get(g, [])
    pool = re.search(POOL_WORDS.get(g, r"卡池"), t) or (cn and cn[0] in roles)
    if WELFARE.search(t):
        return "welfare"
    if pool and not SHOP.search(t):
        return "rerun" if RERUN.search(t) else "pool"
    if SHOP.search(t):
        return "shop"
    if VERSION.search(head):
        return "version"
    if EVENT.search(head) or it.get("kind") == "活动":
        return "event"
    return "other"


def _card_name(title: str) -> tuple[str, str] | None:
    """「沈星回·愿得此瞬」「祁煜·玄面无相」→ (角色, 卡名)。"""
    m = re.fullmatch(r"\s*[「『]?([一-龥]{2,4})[·・•]([一-龥A-Za-z0-9]{2,10})[」』]?\s*", title or "")
    return (m.group(1), m.group(2)) if m else None


def characters(items: list[dict], prefs: dict) -> dict[str, list[str]]:
    """每个游戏的角色名单：种子 + 卡池标题里自动收集的 + 用户补充的。"""
    out = {g: list(v) for g, v in CHARS.items()}
    for it in items:  # 「角色·卡名」写法、且说明里提到抽卡的，才认作角色
        cn = _card_name(it.get("title", ""))
        hay = (it.get("subtitle", "") or "") + (it.get("text", "") or "")[:200]
        if cn and re.search(POOL_WORDS.get(it["game"], r"卡池"), hay) and cn[0] not in out.setdefault(it["game"], []):
            out[it["game"]].append(cn[0])
    for g, names in (prefs.get("extra_chars") or {}).items():
        for n in names:
            if n and n not in out.setdefault(g, []):
                out[g].append(n)
    return out


_JUNK = re.compile(r"^(修复|优化|调整)|==|\s[|｜]\s|官方网站|浏览器|游戏全目录|热点推荐|网易游戏|客服中心|购卡充值|我的足迹|\$\w+")


def clean_text(text: str) -> str:
    """去掉正文里的网页框架文字、修复说明（会混进副标题、误判角色）。"""
    lines = (text or "").split("\n")
    if any("游戏全目录" in x for x in lines):  # 旧数据：正文前面带着网站导航
        k = next((i for i, x in enumerate(lines) if re.match(r"\s*(发布)?时间[:：]", x)), len(lines) - 1)
        lines = lines[k + 1:]
    return "\n".join(ln for ln in lines if ln.strip() and not _JUNK.search(ln.strip()))


def chars_in(it: dict, names: list[str]) -> list[str]:
    sub = "" if _JUNK.search(it.get("subtitle", "") or "") else it.get("subtitle", "")
    hay = " ".join([it.get("title", ""), sub, it.get("source_title", ""), clean_text(it.get("text", ""))[:300]])
    out = [n for n in names if n in hay]
    # 11-02：新角色还不在名单里：帖子里「」括起来、句子里说到密探 / 角色 / 思念 / 概率提升 / UP 的名字（「全新绝密密探「竺大力」「安世高」的获取机率大幅提升」）
    for sent in re.split(r"[。！!；;\n]", it.get("text", "") or ""):
        if re.search(r"密探|角色|思念|[概机]率|UP|up|登场|加入常驻", sent):
            for m in re.findall(r"「([^」·\s]{2,6})」", sent):
                if m not in out and m != it.get("title") and not re.search(r"活动|卡池|许愿|祈愿|任务|奖励", m):
                    out.append(m)
    return out


# ---------------------------------------------------------------- 副标题重写
_DURATION = re.compile(r"^(活动)?(将)?(持续|截止|结束|开放)(到|至)?|^活动时间|^[\d月日:：\s~～\-]+$|将于.*(开启|结束)")
_PLAY = re.compile(r"消耗|完成|参与|通关|翻开|挑战|收集|提升.*等级|任务|关卡|点击|前往|派遣|探索")
_BRACKET = re.compile(r"[\[【［]([^\]】］]{1,16})[\]】］](\s*[*×x]\s*\d+)?")


_COST = re.compile(r"(消耗|花费|使用|支付|解锁|购买)\s*$")
_CURRENCY = re.compile(r"^(钻石|星石|原石|星琼|白金币|深空币|金币|点券|晶石|水晶|画币|彩钻|宝石|元宝)")
_ITEM_TAIL = re.compile(r"^[\u4e00-\u9fff]{0,6}?(装扮|服装|套装|时装|头像框|头像|称号|卡面|卡牌|家具|装饰|挂件|徽章|表情|邀请函|自选包|礼盒)")


def _rewards(text: str, title: str = "") -> tuple[list[str], list[str], list[str]]:
    """从说明里找奖励：免费可得的、要付费的、付费要花的。返回 (免费, 付费, 花费)。
    「消耗[钻石]*610解锁[绮夜珍礼]，则可额外领取校园装扮」：钻石是花的、绮夜珍礼是买的东西，奖励是「校园装扮」，算付费。"""
    free, paid, cost = [], [], []
    tn = _n(title)
    for sent in re.split(r"[。；;\n]", text or ""):
        if not re.search(r"获得|获取|领取|得到|奖励|赠送|附赠", sent):
            continue
        names, spent = [], []
        for m in _BRACKET.finditer(sent):
            n = m.group(1) + (m.group(2) or "").replace(" ", "")
            if re.fullmatch(r"(主界面|活动|出行|假日|采购|花架|设置|学院公告|系统|商店).*|(首通|通关|活动|任务|每日|累计)?(奖励|任务|道具)", n) or (tn and _n(m.group(1)) == tn):
                continue
            before = sent[max(0, m.start() - 4):m.start()]
            if _COST.search(before) or (_CURRENCY.match(m.group(1)) and m.group(2) and re.search(r"消耗|花费|支付", before + sent[m.end():m.end() + 4])):
                spent.append(n)  # 要花的钻石、要解锁的付费项：不是奖励
                continue
            tail = _ITEM_TAIL.match(sent[m.end():])  # 「[幽梦]自选校园装扮」：括号后面跟着的才是完整奖励名
            names.append(n + tail.group(0) if tail and not m.group(2) else n)
        if not names:  # 奖励没加括号：「额外领取校园装扮」
            mm = re.search(r"(?:领取|获得|获取|得到)(?:额外|全部)?([\u4e00-\u9fff]{2,8}?)(?=[，,。；;、！!]|$)", sent)
            if mm and not re.match(r"^(奖励|活动|道具|资格)$", mm.group(1)):
                names = [mm.group(1)]
        if not names:
            continue
        is_paid = bool(spent) or bool(re.search(r"购买|礼包|充值|付费|累充", sent))
        bucket = paid if is_paid else free
        for n in names:
            if n not in bucket:
                bucket.append(n)
        if is_paid:
            for n in spent:
                if n not in cost:
                    cost.append(n)
    return free[:4], paid[:4], cost[:3]


def _n(t: str) -> str:
    return re.sub(r"[\s「」『』《》【】\[\]（）()·:：!！?？,，。.]", "", t or "")


def rewrite_subtitle(it: dict, cat: str) -> str:
    """副标题不清楚时，按规则转写；清楚的保持原样（10-23 用户规则）。
    - 卡池：【角色】【卡牌名】限时 up / 限时复刻（卡名里含角色名时去重）
    - 参与活动可获得【奖励】；可付费获得【付费奖励】
    - 只讲持续时间的：顺着说明往下找有用的信息
    - 讲活动打法的：奖励提前，打法另起一段"""
    sub = (it.get("subtitle") or "").strip()
    if _JUNK.search(sub):
        sub = ""
    text = clean_text(it.get("text") or "")
    title = it.get("title") or ""
    lines = []
    if cat in ("pool", "rerun"):
        cn = _card_name(title)
        if cn and cn[0] in (it.get("chars") or []):
            role, card = cn
            card = card.replace(role, "").strip("·・ ") or card
            lines.append(f"【{role}】【{card}】限时{'复刻' if cat == 'rerun' else ' up'}")
    sub = re.sub(r"^.*(直接更新以下内容|不停服维护)[^/]*/\s*", "", sub).strip()
    unclear = not sub or bool(_DURATION.search(sub)) or len(sub) < 6 or sub.endswith(("：", ":")) or "==" in sub
    play = bool(sub) and bool(_PLAY.search(sub)) and not re.search(r"获得|奖励", sub)
    if not (unclear or play or lines):
        return sub
    free, paid, cost = _rewards(sub + "\n" + text, title)
    if free:
        lines.append("参与活动可获得" + "、".join(f"【{x}】" for x in free))
    if paid:
        spend = [x for x in cost if _CURRENCY.match(x)]
        lines.append("可付费获得" + "、".join(f"【{x}】" for x in paid) + (f"（消耗{'、'.join(spend)}）" if spend else ""))
    if play and not ((free or paid) and re.search(r"领取|获取|得到", sub)):
        lines.append("\n" + sub)  # 打法另起一段（这句本身就是在讲奖励、上面已经转写过的不再重复）
    elif unclear and not (free or paid):
        # 只讲时间：往下找第一句像样的说明
        for ln in (text or "").split("\n"):
            ln = ln.strip()
            if len(ln) >= 8 and not _DURATION.search(ln) and not re.match(r"^(参与条件|活动入口|活动时间)", ln) \
                    and _n(ln) not in _n(title) and _n(title) not in _n(ln) and len(re.findall(r"[，。、：；！]", ln)) * 30 >= min(len(ln), 90):
                lines.append(ln[:90])
                break
    if not lines:
        return "" if (unclear and sub.endswith(("：", ":"))) or "==" in sub else sub
    if sub and not unclear and not play and cat in ("pool", "rerun"):
        lines.append(sub)
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- 用户设置
def prefs_path(data_dir) -> Path:
    return Path(data_dir) / "news_prefs.json"


def _defaults(d: dict) -> dict:
    for k, v in (("hidden_items", []), ("hidden_cats", {}), ("cat_override", {}), ("tag_override", {}), ("user_cats", {}), ("date_override", {}),
                 ("track", {}), ("extra_chars", {}),
                 ("followed", []), ("asked", []), ("push_followed", False), ("push_images", True), ("fetch_all", False)):
        d.setdefault(k, v)
    return d


def load_prefs(data_dir) -> dict:
    from . import jsonio
    return _defaults(jsonio.read(prefs_path(data_dir), {}))


def update_prefs(data_dir, fn) -> dict:
    """在锁里读出设置、交给 fn 就地修改、写回。"""
    from . import jsonio
    return jsonio.update(prefs_path(data_dir), {}, lambda d: fn(_defaults(d)) and None)


def tot_exchange(it: dict) -> bool:
    """未定事件簿的「兑换」类一律不显示（10-23 用户规则）。"""
    return it.get("game") == "tot" and "兑换" in (it.get("title") or "")


def decorate(items: list[dict], prefs: dict) -> list[dict]:
    """给每条活动加上：cat（类别）、hidden（是否隐藏及原因）、chars（涉及的角色）、starred、subtitle2（重写后的副标题）。"""
    names = characters(items, prefs)
    track = prefs.get("track") or {}
    hc = prefs.get("hidden_cats") or {}
    out = []
    for it in items:
        it = dict(it)
        pin = (prefs.get("img_pin") or {}).get(it["id"])
        if pin and pin in (it.get("imgs") or []):  # 自己固定的题图（11-02）
            it["img"], it["img_pinned"] = pin, True
        do = (prefs.get("date_override") or {}).get(it["id"])
        if do:  # 自己改过起止时间：盖过识别的
            it["start_auto"], it["end_auto"] = it.get("start"), it.get("end")
            it.update({k: v for k, v in do.items() if k in ("start", "end") and v})
            if do.get("start") and not do.get("end") and it.get("end_auto") and it.get("start_auto"):
                from datetime import datetime as _dt  # 只改了开始：结束跟着平移，长度不变
                f = "%Y-%m-%d %H:%M"
                try:
                    it["end"] = (_dt.strptime(do["start"], f) + (_dt.strptime(it["end_auto"], f) - _dt.strptime(it["start_auto"], f))).strftime(f)
                except ValueError:
                    pass
            it["dates_fixed"] = True
        cat = (prefs.get("cat_override") or {}).get(it["id"]) or it.get("fixed_cat") or classify(it, names.get(it["game"], []))
        uc = prefs.get("user_cats") or {}
        if cat not in CATS and cat not in uc:
            cat = classify(it, names.get(it["game"], []))
        it["cat"] = cat
        it["cat_label"] = uc[cat] if cat in uc else CATS.get(cat, ("其他", True))[0]
        it["tag"] = (prefs.get("tag_override") or {}).get(it["id"]) or (uc[cat][:3] if cat in uc else auto_tag(it, cat))
        why = ""
        if it["id"] in prefs.get("hidden_items", []):
            why = "不再关注这个活动"
        elif cat in hc.get("*", []) or cat in hc.get(it["game"], []):
            why = "不再关注这一类"
        elif cat in HIDDEN and not prefs.get("cat_override", {}).get(it["id"]):
            why = "默认不显示的类别"
        elif tot_exchange(it):
            why = "未定事件簿的兑换类不显示"
        it["hidden"] = why
        it["chars"] = chars_in(it, names.get(it["game"], []))
        it["tracked"] = [c for c in it["chars"] if c in track.get(it["game"], [])]
        it["starred"] = it["id"] in prefs.get("followed", [])
        it["subtitle2"] = rewrite_subtitle(it, cat)
        it.pop("text", None)
        out.append(it)
    return out
