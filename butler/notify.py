"""微信推送：把每天的汇总、运行中出的问题推到微信。

支持两家（都是把消息发到你关注的微信公众号 / 服务号，免费额度够每天几条）：
  pushplus  https://www.pushplus.plus  微信扫码登录 → 「一对一推送」复制 token
  serverchan  https://sct.ftqq.com（Server酱 Turbo，SendKey 以 SCT 开头）
              或 https://sc3.ft07.com（Server酱³，SendKey 以 sctp 开头）

设置在「设置 → 微信推送」（data/settings.json 的 push）；SendKey / token 只存在 data/secrets.json。
推送状态（上次结果、当天推过的问题、当天汇总推过没有）只记在 data/push_state.json。
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from . import jsonio
from . import settings as S
from .timeutil import BJ, sched_day

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002300-\U000023FF\U000025A0-\U000025FF\U0000FE0F\U0000200D\U000020E3]")


def plain(text: str) -> str:
    """去掉 emoji（任务名里的图标等），连带多出来的空格。"""
    return re.sub(r"[ \t]{2,}", " ", _EMOJI.sub("", str(text))).strip()


def _secrets(cfg: dict) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "secrets.json"


def _state_path(cfg: dict) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "push_state.json"


def settings(cfg: dict) -> dict:
    return {**S.get(cfg, "push"), "token": jsonio.read(_secrets(cfg), {}).get("push_token", "")}


def save_settings(cfg: dict, patch: dict):
    """界面保存：provider / daily_at / on_problem 进设置文件，token 进 secrets.json。"""
    tok = patch.pop("token", None)
    if tok is not None:
        tok = str(tok).strip()
        if tok and not re.fullmatch(r"[A-Za-z0-9_\-]{8,80}", tok):
            raise ValueError("SendKey 格式不对：应是一串字母和数字（Server酱的以 SCT 开头）")
        jsonio.update(_secrets(cfg), {}, lambda d: d.update(push_token=tok))
    if patch:
        S.update(cfg, "push", patch)


def public_settings(cfg: dict) -> dict:
    """给界面看的：SendKey 只露出前 3 位和后 4 位。"""
    p = settings(cfg)
    t = p["token"]
    return {"provider": p["provider"], "configured": bool(p["provider"] and t),
            "token_masked": (t[:3] + "****" + t[-4:]) if len(t) > 8 else ("已填" if t else ""),
            "daily_at": p["daily_at"], "on_problem": p["on_problem"],
            "last": jsonio.read(_state_path(cfg), {}).get("last_result", "")}


def enabled(cfg: dict) -> bool:
    p = settings(cfg)
    return bool(p["provider"] and p["token"])


def send(cfg: dict, title: str, text: str, timeout: int = 15) -> tuple[bool, str]:
    """推一条消息。返回 (成功?, 说明)。"""
    p = settings(cfg)
    prov, token = p["provider"], p["token"]
    if not prov or not token:
        return False, "还没有设置推送（管家「设置」页填 SendKey）"
    title, text = plain(title)[:100], plain(text)
    if prov == "pushplus":
        url = "https://www.pushplus.plus/send"
        body = {"token": token, "title": title, "content": text, "template": "txt"}
    elif prov == "serverchan":
        url = (f"https://{token}.push.ft07.com/send" if token.startswith("sctp")
               else f"https://sctapi.ftqq.com/{token}.send")
        body = {"title": title, "desp": text.replace("\n", "\n\n")}  # Markdown：空行才换行
    else:
        return False, f"不认识的推送服务：{prov}（可选 pushplus / serverchan）"
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json;charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode("utf-8", errors="replace") or "{}")
    except Exception as e:
        return False, f"推送失败：{type(e).__name__}: {e}"
    code = resp.get("code")
    ok = code in (0, 200)
    why = "已推送" if ok else f"推送服务返回：{resp.get('msg') or resp.get('message') or resp}"
    jsonio.update(_state_path(cfg), {}, lambda st: st.update(last_result=f"{datetime.now(BJ):%m-%d %H:%M} {why}"))
    return ok, why


# ---------- 运行结束：推新出现的问题 ----------
def after_run(cfg: dict, gids: list[str]) -> str:
    """一次运行结束（或记了「错过时段」）后调用：有当天还没推过的需要处理 / 提醒就推一条。"""
    if not enabled(cfg) or not settings(cfg)["on_problem"]:
        return ""
    from . import report
    rep = report.build(cfg, "today")
    day = rep["day"]
    seen = set(jsonio.read(_state_path(cfg), {}).get("problems", {}).get(day, []))
    new = [x for x in report.problems(rep, gids) if x not in seen]
    if not new:
        return ""
    ok, why = send(cfg, f"游戏日常：{len(new)} 项需要看一下", "\n".join(new))
    if ok:
        jsonio.update(_state_path(cfg), {}, lambda st: st.update(problems={day: sorted(seen | set(new))}))  # 只留当天的
    return why


def followed_block(cfg: dict) -> str:
    """关注（加星标）的活动随每日汇总推送（设置里打开 push_followed 时）；push_images 时附题图。"""
    try:
        from . import news
        from .newscat import load_prefs
        p = load_prefs(cfg["machine"]["data_dir"])
        if not p.get("push_followed"):
            return ""
        now = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
        names = {g: plain(v.get("name", g)) for g, v in cfg.get("games", {}).items()}
        items = [it for it in news.load(cfg)["items"] if it.get("starred") and (not it.get("end") or it["end"] >= now)]
        if not items:
            return ""
        out = ["", "【关注的活动】"]
        for it in sorted(items, key=lambda x: x.get("end") or "9999"):
            left = ""
            if it.get("end"):
                h = (datetime.strptime(it["end"], "%Y-%m-%d %H:%M") - datetime.strptime(now, "%Y-%m-%d %H:%M")).total_seconds() / 3600
                left = f"，剩 {int(h)} 小时" if h < 48 else f"，剩 {int(h // 24)} 天"
            out.append(f"  {names.get(it['game'], it['game'])}『{plain(it['title'])}』{(it.get('end') or '')[5:]} 结束{left}")
            if p.get("push_images") and it.get("banner_url", "").startswith("http"):
                out.append(f"![]({it['banner_url']})")
        return "\n".join(out)
    except Exception as e:
        return f"\n（关注的活动没能列出：{e}）"


def daily_done(cfg: dict, day: str) -> bool:
    """这一天的汇总推过（或推过但失败了）没有。"""
    return jsonio.read(_state_path(cfg), {}).get("daily", {}).get("day") == day


def daily(cfg: dict, day: str = "today", force: bool = False) -> str:
    """推某一天的汇总。自动推送每天只推一次：推失败也记下（结果在调度记录里），当天不再重试；
    force（手动推）不管推没推过，也不记。"""
    if not enabled(cfg):
        return "没有设置推送"
    from . import report
    rep = report.build(cfg, day)
    if not force and daily_done(cfg, rep["day"]):
        return "这天的汇总已经推过"
    ok, why = send(cfg, rep["title"], (rep["text"] or "今天没有布置任务") + followed_block(cfg))
    if not force:
        jsonio.update(_state_path(cfg), {}, lambda st: st.update(daily={"day": rep["day"], "ok": ok, "result": why}))
    return why
