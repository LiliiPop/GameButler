"""常见脚本列表（总纲 10-23）：点「下载」在用户自己的电脑上从 GitHub 下载最新 Release、解压到用户选的文件夹，
然后走「添加脚本」的识别流程。不经过云端，不改下载下来的文件。

列表来自 config/presets/：只放确认过仓库地址的项目。
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

def items() -> list[dict]:
    """可以下载的：config/presets/ 里写了 GitHub 仓库的预设。"""
    from .gamesdb import presets
    return [{k: p[k] for k in ("id", "name", "game", "repo", "kind")} for p in presets() if p.get("repo")]


UA = "GameButler/1.0"
_JOBS: dict = {}


def _api(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def pick_asset(assets: list[dict]) -> dict | None:
    """Windows x64 的 zip：名字里有 win 和 x64 / x86_64 / amd64 的优先；没有就取第一个 zip。"""
    zips = [a for a in assets if a.get("name", "").lower().endswith(".zip")]
    score = lambda n: (("win" in n) * 2 + bool(re.search(r"x64|x86_64|amd64", n)) * 2 - ("arm" in n) * 3
                       - bool(re.search(r"linux|mac|osx|android|source", n)) * 5)
    zips.sort(key=lambda a: score(a["name"].lower()), reverse=True)
    return zips[0] if zips and score(zips[0]["name"].lower()) > 0 else None


def status(job_id: str) -> dict:
    return _JOBS.get(job_id) or {"state": "none"}


def start(item_id: str, dest: str) -> str:
    it = next((x for x in items() if x["id"] == item_id), None)
    if not it:
        raise ValueError("列表里没有这个")
    dest_p = Path(dest)
    if not dest_p.parent.exists():
        raise ValueError(f"找不到文件夹 {dest_p.parent}")
    job = f"{item_id}-{int(time.time())}"
    _JOBS[job] = {"state": "running", "msg": "查最新版本…", "done": 0, "total": 0, "path": str(dest_p), "name": it["name"]}
    threading.Thread(target=_run, args=(job, it, dest_p), daemon=True).start()
    return job


def _run(job: str, it: dict, dest: Path):
    st = _JOBS[job]
    try:
        rel = _api(f"https://api.github.com/repos/{it['repo']}/releases/latest")
        a = pick_asset(rel.get("assets") or [])
        if not a:
            raise RuntimeError(f"最新版本 {rel.get('tag_name', '')} 里没有找到 Windows 的 zip，请到 GitHub 页面手动下载")
        st.update(msg=f"下载 {a['name']}（{rel.get('tag_name', '')}）", total=int(a.get("size") or 0), version=rel.get("tag_name", ""))
        tmp = dest.parent / (a["name"] + ".part")
        req = urllib.request.Request(a["browser_download_url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            while True:
                buf = r.read(1 << 16)
                if not buf:
                    break
                f.write(buf)
                st["done"] += len(buf)
        st["msg"] = "解压…"
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp) as z:
            for m in z.infolist():  # 防止压缩包里有跳出目标文件夹的路径
                target = (dest / m.filename).resolve()
                if dest.resolve() not in target.parents and target != dest.resolve():
                    raise RuntimeError("压缩包里有不安全的路径，停止解压")
            z.extractall(dest)
        tmp.unlink(missing_ok=True)
        inner = [x for x in dest.iterdir()]
        if len(inner) == 1 and inner[0].is_dir():  # 压缩包里只有一层文件夹：用里面那层
            st["path"] = str(inner[0])
        st.update(state="done", msg="已下载并解压")
    except Exception as e:
        st.update(state="failed", msg=f"{type(e).__name__}: {e}")
