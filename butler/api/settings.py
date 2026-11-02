"""设置、界面主题、开机自动启动、推送测试、留证截图、模拟器、选文件夹、常见脚本下载、界面批注、程序本身。"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

from .. import autostart
from .. import evidence as EV
from .. import notify
from .. import wake
from .. import settings as S
from ..runstate import is_admin
from . import APP, ROOT, route


def all_settings(api) -> dict:
    cfg = api.cfg
    return {"scheduler": S.get(cfg, "scheduler"), "push": notify.public_settings(cfg),
            "appearance": S.get(cfg, "appearance"), "news": S.get(cfg, "news"), "evidence": S.get(cfg, "evidence"),
            "emulator": S.get(cfg, "emulator"), "autostart": autostart.status(),
            "logs_dir": str(api.data_dir / "logs"), "root": str(ROOT), "admin": is_admin(), "launcher": autostart.EXE.exists(),
            "power": wake.status(cfg, api.sched), "ingame": ingame_view(cfg)}


SRC_NAME = {"html_list": "官网", "papegames": "官网", "bili_dyn": "B 站官方号", "wiki": "B 站 wiki", "taptap": "TapTap 官方号",
            "mihoyo_ann": "官方公告接口", "mys_news": "米游社", "jx3_api": "官网"}


def ingame_view(cfg: dict) -> list[dict]:
    """设置「游戏内读取」（11-02）：哪些游戏能进游戏读公告 / 读抽卡资源，它们的站外来源现在读不读得到。"""
    from ..news import _dir, _load, offsite_down, sources
    read = {s["id"] for s in _load(_dir(cfg) / "sources.json", [])}
    out = []
    for gid, g in cfg["games"].items():
        if not (g.get("notice_reader") or g.get("gacha_reader") or g.get("pc_gacha")):
            continue
        down, ids = offsite_down(cfg, gid)
        names = [SRC_NAME.get(s["type"], s["type"]) for s in sources(cfg) if s["id"] in ids]
        out.append({"id": gid, "name": g["name"], "notice": bool(g.get("notice_reader")), "offsite": list(dict.fromkeys(names)),
                    "down": down, "unread": bool(ids) and not (set(ids) & read), "gacha": bool(g.get("gacha_reader") or g.get("pc_gacha")), "read_gacha": g.get("read_gacha", True) is not False})
    return out


@route("GET", "/api/settings")
def _(api, m, q, b):
    return all_settings(api)


@route("PUT", r"/api/settings/(scheduler|push|appearance|news|evidence|emulator)")
def _(api, m, q, b):
    sec = m.group(1)
    if sec == "push":
        notify.save_settings(api.cfg, dict(b))
    else:
        if sec == "scheduler" and "enabled" in b:
            raise ValueError("开关自动调度用 /api/scheduler/on|off")
        if sec == "evidence" and "tasks" in b:  # 只改传来的游戏，别的游戏（例如取消挂载的）的勾选留着
            b = {**b, "tasks": {**S.get(api.cfg, "evidence")["tasks"], **b["tasks"]}}
        S.update(api.cfg, sec, b)
    api.sched.wake()
    return {"ok": True, **all_settings(api)}


# ---------------------------------------------------------------- 界面主题（butler/themes.py）
@route("GET", "/api/themes")
def _(api, m, q, b):
    from .. import themes
    return {"builtin": themes.builtin(), "user": themes.user(api.cfg)}


@route("PUT", r"/api/themes/([\w-]+)")
def _(api, m, q, b):
    from .. import themes
    return themes.save(api.cfg, m.group(1), b)


@route("DELETE", r"/api/themes/([\w-]+)")
def _(api, m, q, b):
    from .. import themes
    if api.appearance()["theme"] == f"user:{m.group(1)}":
        raise ValueError("这个主题正在用：先换成别的主题再删")
    themes.delete(api.cfg, m.group(1))
    return {"ok": True}


# ---------------------------------------------------------------- 开机自动启动、文件夹、推送
@route("POST", "/api/settings/autostart")
def _(api, m, q, b):
    if not autostart.available():
        raise ValueError("只有用 GameButler.exe 启动的管家才能设置开机自动启动")
    if b.get("on"):
        if not autostart.enable():
            raise RuntimeError("设置失败：任务计划程序没有接受（需要管理员身份）")
    else:
        autostart.disable()
    return {"ok": True, **all_settings(api)}


@route("POST", "/api/settings/open")
def _(api, m, q, b):
    path = api.data_dir / "logs" if b.get("what", "logs") == "logs" else ROOT
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.Popen(["explorer.exe", str(path)])
    return {"ok": True, "path": str(path)}


@route("POST", "/api/push/test")
def _(api, m, q, b):
    ok, why = notify.send(api.cfg, "游戏日常管家：推送测试", "能收到这条，说明微信推送设置好了。")
    if not ok:
        raise ValueError(why)
    return {"ok": True, "message": why}


# ---------------------------------------------------------------- 留证截图
@route("GET", "/api/evidence")
def _(api, m, q, b):  # 能勾留证的游戏和任务、保留天数、占用
    from .. import games as G
    on = S.get(api.cfg, "evidence")
    out = []
    for gid, g in api.cfg["games"].items():
        if not G.available(g)[0]:
            continue
        ad = G.adapter(api.cfg, gid)
        names = ad.evidence_tasks()
        if names is None:  # 这个工具不支持留证
            continue
        names = [n for n in names if ad.usable(n)]  # 只列任务库里启用的
        sel = set(on["tasks"].get(gid, []))
        out.append({"id": gid, "name": g["name"], "tasks": [{"task": n, "on": n in sel} for n in names]})
    return {"games": out, "keep_days": on["keep_days"], **EV.usage(api.cfg), "fail": EV.fail_usage(api.cfg)}


@route("POST", "/api/evidence/clean")
def _(api, m, q, b):  # what = evidence（留证截图，按天删）| fail（失败截图，按张删）
    if b.get("what") == "fail":
        n = EV.fail_clean(api.cfg, before=b.get("before"), all_=bool(b.get("all")))
        return {"ok": True, "files": n, "fail": EV.fail_usage(api.cfg)}
    n = EV.clean(api.cfg, before=b.get("before"), all_=bool(b.get("all")))
    return {"ok": True, "days": n, **EV.usage(api.cfg)}


# ---------------------------------------------------------------- 模拟器、选文件夹、常见脚本下载
@route("GET", "/api/emulators")
def _(api, m, q, b):
    from .. import tools as T
    return T.emulators(api.cfg)


@route("POST", "/api/browse")
def _(api, m, q, b):
    from .. import tools as T
    return {"path": T.browse(str(b.get("title") or "选择文件夹"))}


@route("GET", "/api/catalog")
def _(api, m, q, b):
    from .. import catalog as CT
    return {"items": CT.items()}


@route("GET", r"/api/catalog/job/(.+)")
def _(api, m, q, b):
    from .. import catalog as CT
    return CT.status(m.group(1))


@route("POST", "/api/catalog/download")
def _(api, m, q, b):
    from .. import catalog as CT
    return {"job": CT.start(str(b.get("id", "")), str(b.get("dest", "")))}


# ---------------------------------------------------------------- 界面批注（开发用）
@route("GET", "/api/ui-notes")
def _(api, m, q, b):
    from .. import uinotes as UN
    return {"notes": UN.load(api.cfg)}


@route("POST", "/api/ui-notes")
def _(api, m, q, b):
    from .. import uinotes as UN
    return UN.add(api.cfg, b)


@route("POST", r"/api/ui-notes/([\w-]+)")
def _(api, m, q, b):
    from .. import uinotes as UN
    return {"notes": UN.update(api.cfg, m.group(1), b)}


@route("POST", r"/api/ui-notes/([\w-]+)/delete")
def _(api, m, q, b):
    from .. import uinotes as UN
    return {"notes": UN.delete(api.cfg, m.group(1))}


# ---------------------------------------------------------------- 程序本身
@route("GET", "/api/app")
def _(api, m, q, b):
    return {"pid": os.getpid(), "admin": is_admin(), "started": APP["started"], "python": sys.executable, "root": str(ROOT)}


@route("POST", "/api/app/restart")
def _(api, m, q, b):
    # 重启后台：先起一个新的后台进程（它会等端口空出来），再停掉自己。不占启动器「意外退出自动重启」的次数
    args = [sys.executable, str(ROOT / "gb.py"), "web", "--no-browser", "--restarted"]
    args += [a for a in sys.argv[1:] if a.startswith("--log=")]
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "DETACHED_PROCESS", 0))
    errlog = open(api.data_dir / "logs" / "restart.log", "ab")  # 新进程起不来时看这里
    subprocess.Popen(args, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=errlog, stderr=subprocess.STDOUT,
                     creationflags=flags, close_fds=True)
    api.sched.stop()
    threading.Timer(0.5, APP["server"].shutdown).start()
    return {"ok": True}


@route("POST", "/api/app/quit")
def _(api, m, q, b):
    api.sched.stop()
    threading.Timer(0.3, APP["server"].shutdown).start()
    return {"ok": True}


# ---------------------------------------------------------------- 脚本工具的新版本（butler/updates.py）
@route("GET", "/api/updates")
def _(api, m, q, b):
    from .. import updates
    return updates.cached(api.cfg)


@route("POST", "/api/updates/check")
def _(api, m, q, b):
    from .. import updates
    return updates.check(api.cfg)
