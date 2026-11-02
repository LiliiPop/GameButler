"""脚本工具的新版本检查（11-01）：MAA 类工具（MFA 界面）有新版本时提醒，管家不自己下载覆盖。

版本从各工具的 interface.json 读（"version"），对照两个来源：
- GitHub releases（interface.json 的 "github"）；
- Mirror酱（interface.json 的 "mirrorchyan_rid"；不带 CDK 只查版本号，不下载）。
本地是测试版（版本号里有 alpha / beta / rc）时，测试版的新版本也算；否则只看正式版。
有新版本时界面上提示，点「打开更新」打开那个工具自己的界面，用它自带的更新器（按它自己设的渠道和 CDK）更新。
结果存 data/updates.json；管家开着时每 12 小时查一次。"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from . import jsonio
from .timeutil import BJ

UA = "GameButler-update-check"


def parse_version(v: str) -> tuple:
    """v2.3.1-beta.3 → (2, 3, 1, -1, 3)；v2.3.1 → (2, 3, 1, 0, 0)。比不了的返回 ()。"""
    m = re.match(r"v?(\d+(?:\.\d+)*)(?:[-.]?(alpha|beta|rc|a|b)\.?(\d*))?", str(v or "").strip(), re.I)
    if not m:
        return ()
    nums = [int(x) for x in m.group(1).split(".")] + [0] * 3
    pre = m.group(2)
    rank = {"alpha": -3, "a": -3, "beta": -2, "b": -2, "rc": -1}.get((pre or "").lower(), 0)
    return tuple(nums[:4]) + (rank, int(m.group(3) or 0))


def is_pre(v: str) -> bool:
    return bool(re.search(r"alpha|beta|rc", str(v or ""), re.I))


def _get(url: str, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def github_latest(repo_url: str, pre: bool) -> dict:
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", repo_url or "")
    if not m:
        return {}
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    rels = _get(f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=10")
    for r in rels:
        if r.get("draft") or (r.get("prerelease") and not pre):
            continue
        return {"version": r.get("tag_name", ""), "url": r.get("html_url", ""), "date": (r.get("published_at") or "")[:10]}
    return {}


def mirror_latest(rid: str, current: str, pre: bool) -> dict:
    """Mirror酱出错时会带 JSON 说明（code / msg），把它带出来；有的资源按系统 / 架构分包，先不带、不行再带 os / arch 重试。"""
    if not rid:
        return {}
    import urllib.error
    q = f"current_version={urllib.request.quote(current)}&user_agent={UA}" + ("&channel=beta" if pre else "")
    base = f"https://mirrorchyan.com/api/resources/{urllib.request.quote(rid)}/latest?{q}"
    err = ""
    for extra in ("", "&os=windows&arch=amd64", "&os=windows&arch=x86_64"):
        try:
            d = _get(base + extra)
            break
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
                err = f"HTTP {e.code} {body.get('code', '')} {body.get('msg', '')}".strip()
            except Exception:
                err = f"HTTP {e.code}"
    else:
        raise RuntimeError(err or "查不到")
    v = (d.get("data") or {}).get("version_name", "")
    return {"version": v, "url": ""} if v else {}  # 不带 CDK 只有版本号；更新说明看 GitHub，下载交给工具自己的更新器


# 不是 MFA 界面的工具：版本从程序文件的版本信息（或文件夹名）读，对照它的 GitHub 仓库 / Mirror酱资源（11-02）
OTHER = {
    "bettergi": {"name": "BetterGI", "github": "https://github.com/babalae/better-genshin-impact", "rid": ""},  # 不在 Mirror酱上（11-02 用户确认）
    "m7a": {"name": "三月七小助手", "github": "https://github.com/moesnow/March7thAssistant", "rid": "March7thAssistant"},
}


def exe_version(path: str) -> str:
    """Windows 程序文件里的版本号（文件属性 → 详细信息）；读不到时从路径里找 v1.2.3。"""
    if os.name == "nt" and os.path.exists(path):
        try:
            import ctypes
            from ctypes import wintypes
            ver = ctypes.windll.version
            size = ver.GetFileVersionInfoSizeW(path, None)
            if size:
                buf = ctypes.create_string_buffer(size)
                ver.GetFileVersionInfoW(path, 0, size, buf)
                p, n = ctypes.c_void_p(), wintypes.UINT()
                if ver.VerQueryValueW(buf, "\\", ctypes.byref(p), ctypes.byref(n)) and n.value:
                    ffi = ctypes.cast(p, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
                    ms, ls = ffi[4], ffi[5]
                    return f"v{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}" + (f".{ls & 0xFFFF}" if ls & 0xFFFF else "")
        except Exception:
            pass
    m = re.search(r"v(\d+(?:\.\d+)+)", str(path))
    return f"v{m.group(1)}" if m else ""


def m7a_version(exe: str) -> str:
    f = Path(exe).parent / "assets" / "config" / "version.txt"
    try:
        return f.read_text(encoding="utf-8").strip()
    except OSError:
        return exe_version(exe)


def tools(cfg: dict) -> list[dict]:
    out = []
    for gid, g in cfg["games"].items():
        kind = g.get("type") or g.get("kind") or ""
        if kind in OTHER and g.get("exe"):
            o = OTHER[kind]
            v = m7a_version(g["exe"]) if kind == "m7a" else exe_version(g["exe"])
            key = os.path.normcase(g["exe"])
            if v and not any(x["key"] == key for x in out):
                out.append({"key": key, "name": o["name"], "version": v, "github": o["github"], "rid": o["rid"], "games": [gid]})
            continue
        pd = g.get("project_dir")
        if not pd:
            continue
        f = Path(pd) / "interface.json"
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not d.get("version") or not (d.get("github") or d.get("mirrorchyan_rid")):
            continue
        key = os.path.normcase(str(f.resolve()))
        if any(x["key"] == key for x in out):  # 两个游戏用同一个工具：查一次
            out[[x["key"] for x in out].index(key)]["games"].append(gid)
            continue
        out.append({"key": key, "name": d.get("name") or gid, "version": d["version"], "github": d.get("github", ""),
                    "rid": d.get("mirrorchyan_rid", ""), "games": [gid]})
    return out


def check(cfg: dict) -> dict:
    res = []
    for t in tools(cfg):
        pre = is_pre(t["version"])
        row = {"name": t["name"], "games": t["games"], "version": t["version"], "latest": "", "url": "", "source": "",
               "newer": False, "errors": []}
        for src, fn in (("GitHub", lambda: github_latest(t["github"], pre)), ("Mirror酱", lambda: mirror_latest(t["rid"], t["version"], pre))):
            try:
                r = fn()
            except Exception as e:  # 一个来源连不上不影响另一个
                row["errors"].append(f"{src}：{e}" if isinstance(e, RuntimeError) else f"{src}：{type(e).__name__}")
                continue
            # 查到的和本机一样新也记下（显示「已是最新」）；比已记的更新才换
            if r.get("version") and (parse_version(r["version"]) > parse_version(row["latest"]) if row["latest"]
                                     else parse_version(r["version"]) >= parse_version(t["version"])):
                row.update(latest=r["version"], url=r.get("url") or row["url"], source=src)
            elif r.get("url") and not row["url"]:
                row["url"] = r["url"]
        row["newer"] = bool(row["latest"]) and parse_version(row["latest"]) > parse_version(t["version"])
        res.append(row)
    doc = {"checked": datetime.now(BJ).strftime("%Y-%m-%d %H:%M"), "tools": res}
    jsonio.write(Path(cfg["machine"]["data_dir"]) / "updates.json", doc)
    return doc


def cached(cfg: dict) -> dict:
    """上次查到的最新版本 + 现在本机装的版本（每次都重新读本机版本：工具更新完马上就显示「已是最新」，不用再点检查）。"""
    doc = jsonio.read(Path(cfg["machine"]["data_dir"]) / "updates.json", {"checked": "", "tools": []})
    local = {t["name"]: t["version"] for t in tools(cfg)}
    for row in doc.get("tools", []):
        v = local.get(row["name"])
        if v and v != row["version"]:
            row["version"] = v
            row["newer"] = bool(row.get("latest")) and parse_version(row["latest"]) > parse_version(v)
    return doc
