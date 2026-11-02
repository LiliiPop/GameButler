"""管家自己的更新（11-02）：对比 GitHub 上最新的发布版本，下载发布包，没有任务在跑时换上新文件、自动重启。

版本号：管家文件夹里的 VERSION（例如 0.1.0）；GitHub 发布的标签写 v0.1.1 这样。
发布包：发布里的 zip（GameButler-v0.1.1-win64.zip，里面一个 GameButler/ 文件夹：代码 + GameButler.exe + runtime）；
        没有上传 zip 的发布，用 GitHub 自动生成的源码包（只有代码，没有 GameButler.exe 和 runtime）。

换文件的过程（apply）：
  1. 后台把换文件的小程序写到 data/update/apply_update.py，用另一个进程开它，然后自己退出（和「重启后台」一样）。
  2. 小程序等端口空出来，先在 8765 上回「正在更新」（托盘启动器看到后台还在，不会当成崩溃去重开）；
  3. 把要换掉的旧文件备份到 _backup/update_<旧版本>_<时间>/，再把新文件复制过来：
     不动 data/、config/butler.toml、_backup/、_release/；GameButler.exe 正在用 → 旧的改名 GameButler.old.exe
     （启动器下次启动时删掉）；runtime 有变化才换（换的时候小程序用 data/update/py 里的一份 Python 跑）；
     butler/ runner/ static/ 里新版本没有了的旧文件删掉。
  4. 出错就从备份放回去。最后开新后台（--restarted：等端口空出来），结果写 data/update/result.json。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from . import jsonio
from .updates import UA, is_pre, parse_version

ROOT = Path(__file__).resolve().parent.parent
REPO = "LiliiPop/GameButler"
_JOB: dict = {"state": "idle"}  # idle / checking / downloading / ready / applying / error
_LOCK = threading.Lock()


def current_version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _dir(cfg) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "update"


def _cache(cfg) -> Path:
    return _dir(cfg) / "check.json"


def _get(url: str, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _pick_asset(assets: list) -> dict | None:
    zips = [a for a in assets or [] if str(a.get("name", "")).lower().endswith(".zip")]
    zips.sort(key=lambda a: (("win" in a["name"].lower()) + bool(re.search(r"64", a["name"]))), reverse=True)
    return zips[0] if zips else None


def check(cfg) -> dict:
    """查 GitHub 上最新的发布版本，结果存 data/update/check.json。"""
    from . import settings as S
    cur = current_version()
    pre = S.get(cfg, "app_update")["pre"] or is_pre(cur)
    out = {"checked": datetime.now().strftime("%Y-%m-%d %H:%M"), "current": cur, "repo": REPO}
    try:
        rels = _get(f"https://api.github.com/repos/{REPO}/releases?per_page=10")
        rel = next((r for r in rels if not r.get("draft") and (pre or not r.get("prerelease"))), None)
        if not rel:
            out.update(latest="", newer=False, error="", note="GitHub 上还没有发布版本")
        else:
            a = _pick_asset(rel.get("assets"))
            tag = rel.get("tag_name", "")
            out.update(latest=tag, newer=bool(parse_version(tag)) and parse_version(tag) > parse_version(cur),
                       url=rel.get("html_url", ""), date=(rel.get("published_at") or "")[:10],
                       notes=(rel.get("body") or "")[:3000], error="",
                       package={"url": a["browser_download_url"], "size": a.get("size", 0), "name": a["name"], "full": True}
                       if a else {"url": rel.get("zipball_url", ""), "size": 0, "name": f"{tag} 源码包", "full": False})
    except Exception as e:
        out.update(error=f"{type(e).__name__}: {e}"[:300])
    _dir(cfg).mkdir(parents=True, exist_ok=True)
    jsonio.write(_cache(cfg), out)
    return out


def status(cfg) -> dict:
    c = jsonio.read(_cache(cfg), {}) or {}
    if c.get("current") and c["current"] != current_version():  # 刚更新过：版本号变了，「有新版本」要重新算
        c["current"] = current_version()
        c["newer"] = bool(parse_version(c.get("latest", ""))) and parse_version(c.get("latest", "")) > parse_version(c["current"])
    res = jsonio.read(_dir(cfg) / "result.json", None)
    ready = _ready(cfg, c.get("latest", ""))
    job = dict(_JOB)
    if job.get("state") in ("idle", "ready") and ready:
        job["state"] = "ready"
    return {"current": current_version(), "check": c, "job": job, "ready": bool(ready), "last_result": res}


def _ready(cfg, tag: str) -> Path | None:
    """下载解压好了的新版本文件夹（里面有 gb.py 的那一层）。"""
    if not tag:
        return None
    mark = jsonio.read(_dir(cfg) / "ready.json", None)
    if mark and mark.get("tag") == tag and Path(mark.get("root", "")).joinpath("gb.py").exists():
        return Path(mark["root"])
    return None


def download(cfg) -> bool:
    """在后台线程里下载、解压最新版本；已经在下就不重复。返回是否开始了。"""
    with _LOCK:
        if _JOB.get("state") in ("downloading", "applying", "checking"):
            return False
        _JOB.clear()
        _JOB.update(state="downloading", got=0, size=0)
    threading.Thread(target=_download, args=(cfg,), daemon=True).start()
    return True


def _download(cfg):
    try:
        c = check(cfg)
        if c.get("error"):
            raise RuntimeError(f"查不到新版本：{c['error']}")
        if not c.get("newer"):
            _JOB.update(state="idle")
            return
        tag, pk = c["latest"], c["package"]
        d = _dir(cfg)
        dest = d / re.sub(r"[^\w.-]", "_", tag)
        if _ready(cfg, tag):
            _JOB.update(state="ready", tag=tag)
            return
        _JOB.update(size=pk.get("size", 0), tag=tag)
        part = d / f"{dest.name}.zip.part"
        req = urllib.request.Request(pk["url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
            _JOB["size"] = int(r.headers.get("Content-Length") or pk.get("size") or 0)
            while True:
                b = r.read(256 * 1024)
                if not b:
                    break
                f.write(b)
                _JOB["got"] = _JOB.get("got", 0) + len(b)
        z = part.with_suffix("")  # .zip
        part.replace(z)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(dest)
        z.unlink(missing_ok=True)
        root = next((p.parent for p in sorted(dest.rglob("gb.py"), key=lambda p: len(p.parts)) if (p.parent / "butler").is_dir()), None)
        if not root:
            raise RuntimeError("发布包里没有管家的文件（找不到 gb.py 和 butler 文件夹）")
        jsonio.write(d / "ready.json", {"tag": tag, "root": str(root), "full": pk.get("full", False)})
        for old in d.iterdir():  # 以前下的版本删掉
            if old.is_dir() and old != dest and old.name not in ("py",):
                shutil.rmtree(old, ignore_errors=True)
        _JOB.update(state="ready", tag=tag)
    except Exception as e:
        _JOB.update(state="error", error=f"{type(e).__name__}: {e}"[:300])


def _fingerprint(p: Path) -> list:
    if not p.is_dir():
        return []
    return sorted((str(f.relative_to(p)), f.stat().st_size) for f in p.rglob("*")
                  if f.is_file() and "__pycache__" not in f.parts)


def cleanup_old():
    """更新时被占用、改名留下的旧文件（*.old-update，例如正在被启动器加载的 dll）：后台启动时删掉。"""
    for f in list(ROOT.glob("*.old-update")) + list(ROOT.glob("launcher/**/*.old-update")) + list(ROOT.glob("runtime/**/*.old-update")):
        try:
            f.unlink()
        except OSError:
            pass


def _port() -> int:
    from .web import PORT
    return PORT


def apply(api) -> dict:
    """换上下载好的新版本并重启后台。有任务在跑时不换。"""
    cfg = api.cfg
    if api.rs.current():
        raise ValueError("有任务正在运行，等它跑完再更新")
    c = jsonio.read(_cache(cfg), {}) or {}
    src = _ready(cfg, c.get("latest", ""))
    if not src:
        raise ValueError("新版本还没下载好")
    d = _dir(cfg)
    py = Path(sys.executable)
    new_rt = src / "runtime" / "python"
    swap_rt = new_rt.is_dir() and _fingerprint(new_rt) != _fingerprint(ROOT / "runtime" / "python")
    if swap_rt:  # 要换 runtime：换文件的小程序不能用正在被换掉的 Python，先复制一份出来用
        tmp = d / "py"
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(py.parent, tmp)
        py = tmp / py.name
    log = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--log=")), "")
    job = {"root": str(ROOT), "src": str(src), "port": _port(),
           "from": current_version(), "to": c.get("latest", ""), "swap_runtime": swap_rt,
           "backup": str(ROOT / "_backup" / f"update_{current_version()}_{datetime.now():%m%d%H%M}"),
           "result": str(d / "result.json"), "log": log,
           "python": str(ROOT / "runtime" / "python" / Path(sys.executable).name)
           if (ROOT / "runtime" / "python").is_dir() else sys.executable}
    jsonio.write(d / "apply.json", job)
    helper = d / "apply_update.py"
    newer_helper = src / "butler" / "selfupdate_apply.py"  # 11-02：用新版本自带的换文件小程序（修过的问题马上生效）
    shutil.copyfile(newer_helper if newer_helper.exists() else Path(__file__).with_name("selfupdate_apply.py"), helper)
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "DETACHED_PROCESS", 0))
    (Path(cfg["machine"]["data_dir"]) / "logs").mkdir(parents=True, exist_ok=True)
    errlog = open(Path(cfg["machine"]["data_dir"]) / "logs" / "selfupdate.log", "ab")
    subprocess.Popen([str(py), "-I", str(helper), str(d / "apply.json")], cwd=str(d), stdin=subprocess.DEVNULL,
                     stdout=errlog, stderr=subprocess.STDOUT, creationflags=flags, close_fds=True)
    _JOB.update(state="applying")
    from .api import APP
    api.sched.stop()
    threading.Timer(0.8, APP["server"].shutdown).start()
    return {"ok": True, "to": job["to"]}


def tick(cfg, port: int):
    """后台定时：查新版本；开了自动更新就下载，下载好、没有任务在跑时换上（通过本机接口，和点按钮一样）。"""
    from . import settings as S
    c = jsonio.read(_cache(cfg), {}) or {}
    try:
        age = time.time() - datetime.strptime(c.get("checked", ""), "%Y-%m-%d %H:%M").timestamp()
    except ValueError:
        age = 1e9
    if age > 6 * 3600 or c.get("current") != current_version():  # 每 6 小时问一次 GitHub；其余时候只看下好了没、能不能换
        c = check(cfg)
    if not (S.get(cfg, "app_update")["auto"] and c.get("newer")):
        return
    last = jsonio.read(_dir(cfg) / "result.json", None) or {}
    if last.get("to") == c["latest"] and not last.get("ok"):  # 这个版本自动换失败过：不再自动反复试（每次都会重启后台），等你手动点
        return
    if not _ready(cfg, c["latest"]):
        _download(cfg)
    if _ready(cfg, c["latest"]):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/selfupdate/apply", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass  # 有任务在跑：下次再试
