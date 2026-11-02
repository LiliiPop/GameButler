"""米游社扫码登录 + 每日签到（11-02：原神；崩铁、未定事件簿）。

不用装胡桃工具箱：在管家里用米游社 App 扫二维码登录，管家拿到这个米游社账号的 stoken，
每天跑「米游社签到」时换出当天的 cookie_token、查出账号下这个游戏的角色，逐个签到（米游社「每日签到」福利）。
同一个米游社账号只扫一次码，几个游戏都用它。

移植自 Snap Hutao Remastered（https://github.com/SnapHutaoRemasteringProject/Snap.Hutao.Remastered，MIT License，
Copyright (c) 2022-2025 DGP Studio / 2026 DGP Studio (Snap.Nicole) / 2026 Snap.HutaoRemasteringProject）：
  - 扫码登录：Web/Hoyolab/Passport/HoyoPlayPassportClient.cs（createQRLogin / queryQRLoginStatus，HoyoPlay 请求头）
  - stoken → cookie_token / ltoken：Web/Hoyolab/Passport/PassportClient.cs、Service/User/UserInitializationService.cs
  - 角色列表：Web/Hoyolab/Takumi/Auth/AuthClient.cs（getActionTicketBySToken）+ Takumi/Binding/BindingClient.cs
  - 签到：Web/Hoyolab/Takumi/Event/BbsSignReward/SignInClient.cs（luna/info、luna/sign，x-rpc-signgame: hk4e）
  - DS 签名：Web/Hoyolab/DataSigning/DataSignAlgorithm.cs、DataSignOptions.cs；盐和版本号：HoyolabOptions.cs、SaltConstants.cs
崩铁、未定事件簿的签到参数（活动编号、game_biz、请求头）参照 MihoyoBBSTools
（https://github.com/Womsxd/MihoyoBBSTools，MIT License，Copyright (c) 2021-2022 Womsxd）的 setting.py / gamecheckin.py。
  完整许可证见 docs/THIRD_PARTY_NOTICES.md。

没有移植的：设备指纹（device_fp，原作者注明不要照搬那段伪造的设备信息）、极验人机验证。
米游社要求人机验证时（返回 gt / challenge），这次签到记成失败，提示去米游社 App 里手动签一次。

存在 data/mys.json（只在这台电脑上，不上传）：
  {"device_id36", "device_id53", "accounts": [{aid, mid, stoken, ltoken, nickname, added,
                                               roles_by: {游戏: [角色…]}, last_by: {游戏: {time, ok, text}}}]}
stoken 相当于米游社的登录凭证：不要把 data 文件夹发给别人。
"""
from __future__ import annotations

import hashlib
import json
import random
import string
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from . import jsonio
from .timeutil import BJ

# ---------------------------------------------------------------- 常量（来自 Snap Hutao：HoyolabOptions.cs / SaltConstants.cs / ApiEndpoints.csv）
CN_VERSION = "2.95.1"
SALT_K2 = "sfYPEgpxkOe1I3XVMLdwp1Lyt9ORgZsq"
SALT_LK2 = "sidQFEglajEz7FA0Aj7HQPV88zpf17SO"
SALT_PROD = "JwYDpKvLj6MrMqqYU6jTKF17KNO2PXoS"
UA_BBS = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) miHoYoBBS/{CN_VERSION}"
UA_HYP = "HYPContainer/1.1.4.133"
# 各游戏的米游社签到（luna/info、luna/sign 同一套接口）：活动编号、game_biz、额外请求头
GAMES = {
    "genshin": {"name": "原神", "biz": "hk4e_cn", "act_id": "e202311201442471",
                "headers": {"x-rpc-signgame": "hk4e", "Origin": "https://act.mihoyo.com", "Referer": "https://act.mihoyo.com/"}},
    "starrail": {"name": "崩坏：星穹铁道", "biz": "hkrpg_cn", "act_id": "e202304121516551",
                 "headers": {"Origin": "https://act.mihoyo.com", "Referer": "https://act.mihoyo.com/"}},
    "tot": {"name": "未定事件簿", "biz": "nxx_cn", "act_id": "e202202251749321",
            "headers": {"Referer": "https://webstatic.mihoyo.com/bbs/event/signin/nxx/index.html?bbs_auth_required=true"
                                   "&bbs_presentation_style=fullscreen&act_id=e202202251749321"}},
}

QR_CREATE = "https://passport-api.mihoyo.com/account/ma-cn-passport/app/createQRLogin"
QR_QUERY = "https://passport-api.mihoyo.com/account/ma-cn-passport/app/queryQRLoginStatus"
COOKIE_TOKEN = "https://passport-api.mihoyo.com/account/auth/api/getCookieAccountInfoBySToken"
LTOKEN = "https://passport-api.mihoyo.com/account/auth/api/getLTokenBySToken"
ACTION_TICKET = "https://api-takumi.mihoyo.com/auth/api/getActionTicketBySToken"
ROLES_BY_TICKET = "https://api-takumi.mihoyo.com/binding/api/getUserGameRoles"
ROLES_BY_COOKIE = "https://api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie"
SIGN_INFO = "https://api-takumi.mihoyo.com/event/luna/info"
SIGN = "https://api-takumi.mihoyo.com/event/luna/sign"

QR_EXPIRED = -3501
ALREADY_SIGNED = -5003


class MysError(RuntimeError):
    pass


# ---------------------------------------------------------------- 存储
def _p(cfg) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "mys.json"


def _doc(cfg) -> dict:
    d = jsonio.read(_p(cfg), {}) or {}
    if not d.get("device_id36") or not d.get("device_id53"):  # 这台电脑固定一个设备号（米游社按设备号认登录）
        def fn(x):
            x.setdefault("device_id36", str(uuid.uuid4()))
            x.setdefault("device_id53", "".join(random.choices(string.ascii_lowercase + string.digits, k=53)))
            x.setdefault("accounts", [])
        d = jsonio.update(_p(cfg), {}, fn)
    d.setdefault("accounts", [])
    return d


def _migrate(a: dict) -> dict:
    """11-02 第一版只有原神：roles / last → roles_by / last_by。"""
    if "roles_by" not in a:
        a["roles_by"] = {"genshin": a.pop("roles", [])} if a.get("roles") else {}
        a.pop("roles", None)
    if "last_by" not in a:
        a["last_by"] = {"genshin": a.pop("last")} if a.get("last") else {}
        a.pop("last", None)
    return a


def accounts(cfg) -> list[dict]:
    """给界面看的账号列表（不含 token）：每个游戏的角色和上次签到结果。"""
    out = []
    for a in map(_migrate, _doc(cfg)["accounts"]):
        out.append({"aid": a["aid"], "nickname": a.get("nickname") or "", "added": a.get("added", ""),
                    "games": [{"id": gid, "name": g["name"], "last": a["last_by"].get(gid) or {},
                               "roles": [{"uid": r["game_uid"], "nickname": r.get("nickname", ""),
                                          "region_name": r.get("region_name", ""), "level": r.get("level")}
                                         for r in a["roles_by"].get(gid) or []]} for gid, g in GAMES.items()]})
    return out


def logged_in(cfg) -> bool:
    return bool(_doc(cfg)["accounts"])


def remove(cfg, aid: str):
    jsonio.update(_p(cfg), {}, lambda d: d.update(accounts=[a for a in d.get("accounts", []) if a.get("aid") != aid]))


def _save_account(cfg, acc: dict):
    def fn(d):
        lst = [a for a in d.get("accounts", []) if a.get("aid") != acc["aid"]]
        lst.append(acc)
        d["accounts"] = lst
    jsonio.update(_p(cfg), {}, fn)


# ---------------------------------------------------------------- 请求
def _rand(n: int) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _ds1(salt: str) -> str:
    """DS 第一代：md5("salt=…&t=…&r=…")；r 是 6 位小写字母 + 数字（DataSignAlgorithm.cs，includeChars = true）。"""
    t, r = int(time.time()), _rand(6)
    return f"{t},{r},{hashlib.md5(f'salt={salt}&t={t}&r={r}'.encode()).hexdigest()}"


def _ds2(salt: str, body: str, query: str) -> str:
    """DS 第二代：再带上 b=请求体、q=排好序的查询串（PROD 盐没有请求体时 b = "{}"）。"""
    t, r = int(time.time()), _rand(6)
    q = "&".join(sorted(query.split("&"))) if query else ""
    return f"{t},{r},{hashlib.md5(f'salt={salt}&t={t}&r={r}&b={body}&q={q}'.encode()).hexdigest()}"


def _call(method: str, url: str, headers: dict, body: dict | None = None, timeout=15) -> dict:
    data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8") if body is not None else None
    h = {"Accept": "application/json", **headers}
    if data is not None:
        h["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise MysError(f"米游社返回 HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MysError(f"连不上米游社：{e}") from e


def _hyp(d: dict) -> dict:  # HoyoPlay（扫码登录）的请求头（HttpClientConfiguration.XRpc5）
    return {"User-Agent": UA_HYP, "x-rpc-app_id": "ddxf5dufpuyo", "x-rpc-client_type": "3", "x-rpc-device_id": d["device_id53"]}


def _xrpc(d: dict) -> dict:  # 米游社 App（签到、角色）的请求头（XRpc）
    return {"User-Agent": UA_BBS, "x-rpc-app_version": CN_VERSION, "x-rpc-client_type": "5", "x-rpc-device_id": d["device_id36"]}


def _xrpc2(d: dict) -> dict:  # 通行证（换 token）的请求头（XRpc2）
    return {"User-Agent": UA_BBS, "x-rpc-aigis": "", "x-rpc-app_id": "bll8iq97cem8", "x-rpc-app_version": CN_VERSION,
            "x-rpc-client_type": "2", "x-rpc-device_id": d["device_id36"], "x-rpc-device_name": "",
            "x-rpc-game_biz": "bbs_cn", "x-rpc-sdk_version": "2.16.0"}


def _ok(r: dict, what: str) -> dict:
    if r.get("retcode") != 0:
        raise MysError(f"{what}失败：{r.get('message') or ''}（{r.get('retcode')}）")
    return r.get("data") or {}


# ---------------------------------------------------------------- 扫码登录
def qr_create(cfg) -> dict:
    """返回 {"url": 二维码内容, "ticket": 用来查状态}。用米游社 App 扫。"""
    d = _doc(cfg)
    data = _ok(_call("POST", QR_CREATE, _hyp(d), {}), "生成登录二维码")
    return {"url": data.get("url", ""), "ticket": data.get("ticket", "")}


def qr_status(cfg, ticket: str) -> dict:
    """查二维码状态：{"state": "waiting" | "scanned" | "expired" | "done", ...}；done 时已经保存好账号。"""
    d = _doc(cfg)
    r = _call("POST", QR_QUERY, _hyp(d), {"ticket": ticket})
    if r.get("retcode") == QR_EXPIRED:
        return {"state": "expired"}
    data = _ok(r, "查询扫码状态")
    st = data.get("status", "")
    if st != "Confirmed":
        return {"state": "scanned" if st == "Scanned" else "waiting"}
    stoken = next((t["token"] for t in data.get("tokens") or [] if t.get("token_type") == 1), "")
    ui = data.get("user_info") or {}
    if not stoken or not ui.get("aid"):
        raise MysError("扫码成功了，但米游社没有给登录凭证")
    acc = {"aid": str(ui["aid"]), "mid": ui.get("mid", ""), "stoken": stoken, "nickname": ui.get("account_name") or "",
           "added": datetime.now(BJ).strftime("%Y-%m-%d %H:%M"), "roles_by": {}, "last_by": {}}
    acc["ltoken"] = _ltoken(d, acc)
    found = []
    for gid, g in GAMES.items():  # 一次查出这个账号在各游戏的角色（只扫一次码）
        try:
            acc["roles_by"][gid] = _roles(d, acc, gid)
        except MysError:
            acc["roles_by"][gid] = []
        if acc["roles_by"][gid]:
            found.append(f"{g['name']} {len(acc['roles_by'][gid])} 个")
    _save_account(cfg, acc)
    return {"state": "done", "aid": acc["aid"], "found": found}


# ---------------------------------------------------------------- token 和角色
def _stoken_cookie(acc: dict) -> str:
    return f"mid={acc['mid']};stoken={acc['stoken']};stuid={acc['aid']}"


def _ltoken(d: dict, acc: dict) -> str:
    h = {**_xrpc2(d), "Cookie": _stoken_cookie(acc), "DS": _ds2(SALT_PROD, "{}", "")}
    return _ok(_call("GET", LTOKEN, h), "换取 ltoken").get("ltoken", "")


def _cookie_token(d: dict, acc: dict) -> str:
    h = {**_xrpc2(d), "Cookie": _stoken_cookie(acc), "DS": _ds2(SALT_PROD, "{}", "")}
    tok = _ok(_call("GET", COOKIE_TOKEN, h), "换取 cookie_token").get("cookie_token", "")
    if not tok:
        raise MysError("换取 cookie_token 失败：米游社没给")
    return tok


def _roles(d: dict, acc: dict, gid: str) -> list[dict]:
    """这个米游社账号下某个游戏的角色（国服 / B 服）。"""
    biz, name = GAMES[gid]["biz"], GAMES[gid]["name"]
    q = urllib.parse.urlencode({"action_type": "game_role", "stoken": acc["stoken"], "uid": acc["aid"]})
    h = {**_xrpc(d), "Cookie": _stoken_cookie(acc), "DS": _ds1(SALT_K2)}
    try:
        ticket = _ok(_call("GET", f"{ACTION_TICKET}?{q}", h), "取角色凭证").get("ticket", "")
        ck = f"ltuid={acc['aid']};ltoken={acc.get('ltoken', '')}"
        data = _ok(_call("GET", f"{ROLES_BY_TICKET}?{urllib.parse.urlencode({'action_ticket': ticket, 'game_biz': biz})}",
                         {"User-Agent": UA_BBS, "Cookie": ck}), f"查{name}角色")
    except MysError:  # 退一步：用 cookie_token 查
        ck = f"account_id={acc['aid']};cookie_token={_cookie_token(d, acc)};ltuid={acc['aid']};ltoken={acc.get('ltoken', '')}"
        data = _ok(_call("GET", f"{ROLES_BY_COOKIE}?game_biz={biz}", {"User-Agent": UA_BBS, "Cookie": ck}), f"查{name}角色")
    return [{k: r.get(k) for k in ("game_uid", "nickname", "region", "region_name", "level")} for r in data.get("list") or []]


# ---------------------------------------------------------------- 签到
def sign_all(cfg, gid: str = "genshin") -> tuple[bool, str]:
    """所有登录的米游社账号下，这个游戏的所有角色都签一次。返回 (全部成功, 说明)。"""
    if gid not in GAMES:
        return False, f"米游社签到还不支持这个游戏：{gid}"
    name = GAMES[gid]["name"]
    d = _doc(cfg)
    if not d["accounts"]:
        return False, "还没登录米游社：到「设置 → 米游社账号」扫码登录"
    lines, ok_all, any_role = [], True, False
    for acc in map(_migrate, d["accounts"]):
        mine, ok_acc = [], True
        try:
            ct = _cookie_token(d, acc)
            if not acc["roles_by"].get(gid):  # 登录时没查到（或以前只查了原神）：再查一次
                acc["roles_by"][gid] = _roles(d, acc, gid)
            for r in acc["roles_by"][gid]:
                any_role = True
                ok, msg = _sign_one(d, acc, ct, r, gid)
                ok_acc &= ok
                mine.append(f"{r.get('nickname') or ''}（{r['game_uid']}）：{msg}")
            if not acc["roles_by"][gid]:
                mine.append(f"米游社账号 {acc['aid']} 下没有{name}角色")
        except MysError as e:
            ok_acc = False
            msg = str(e)
            if "-100" in msg or "登录" in msg or "-1004" in msg:
                msg += "。登录可能失效了：到「设置 → 米游社账号」重新扫码"
            mine.append(f"米游社账号 {acc['aid']}：{msg}")
        if acc["roles_by"].get(gid) or not ok_acc:
            acc["last_by"][gid] = {"time": datetime.now(BJ).strftime("%Y-%m-%d %H:%M"), "ok": ok_acc, "text": "；".join(mine)[-300:]}
        ok_all &= ok_acc
        lines += mine
        _save_account(cfg, acc)
    if not any_role and ok_all:  # 所有账号下都没有这个游戏的角色：不算完成
        return False, f"登录的米游社账号下都没有{name}角色（游戏账号要先在米游社里绑定）"
    return ok_all, "；".join(lines)


def _sign_one(d: dict, acc: dict, cookie_token: str, role: dict, gid: str) -> tuple[bool, str]:
    g = GAMES[gid]
    base = {**_xrpc(d), "Cookie": f"account_id={acc['aid']};cookie_token={cookie_token}", **g["headers"]}
    q = urllib.parse.urlencode({"lang": "zh-cn", "act_id": g["act_id"], "region": role["region"], "uid": role["game_uid"]})
    info = _ok(_call("GET", f"{SIGN_INFO}?{q}", {**base, "DS": _ds1(SALT_LK2)}), "查签到状态")
    if info.get("is_sign"):
        return True, f"今天已经签过（本月第 {info.get('total_sign_day', '?')} 天）"
    r = _call("POST", SIGN, {**base, "DS": _ds1(SALT_LK2)},
              {"act_id": g["act_id"], "region": role["region"], "uid": role["game_uid"]})
    if r.get("retcode") == ALREADY_SIGNED:
        return True, "今天已经签过"
    data = _ok(r, "签到")
    if data.get("is_risk") or (data.get("success") == 1 and data.get("gt")):
        return False, "米游社要求人机验证，这次没签上：今天请在米游社 App 里手动签一次"
    return True, f"签到成功（本月第 {int(info.get('total_sign_day') or 0) + 1} 天）"
