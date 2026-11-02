"""换文件的小程序（selfupdate.apply 复制到 data/update/apply_update.py 后用 python -I 运行）。
只用标准库，不导入管家自己的代码（那些文件正要被换掉）。参数：apply.json 的路径。"""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

JOB = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
ROOT, SRC = Path(JOB["root"]), Path(JOB["src"])
KEEP = {"data", "_backup", "_release", "_update"}       # 用户自己的东西：不动
CLEAN = ("butler", "runner", "static")                  # 新版本没有了的旧文件删掉


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


class Stub(BaseHTTPRequestHandler):
    """更新期间占着端口回「正在更新」：托盘启动器每几秒问一次 /api/running，问不到会当成后台崩了去重开。"""
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/running":
            return self._send(200, {"running": False, "paused": None, "updating": True})
        if p == "/api/app":
            return self._send(200, {"updating": True, "to": JOB["to"]})
        if p.startswith("/api/"):
            return self._send(503, {"error": "管家正在更新，马上就好", "updating": True})
        b = ("<!doctype html><meta charset=utf-8><title>日常管家</title><body style='font:15px system-ui;padding:40px'>"
             "管家正在更新到 " + JOB["to"] + "，马上就好…<script>setTimeout(()=>location.reload(),2000)</script>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        self._send(503, {"error": "管家正在更新，马上就好", "updating": True})

    def log_message(self, *a):
        pass


def bind_stub():
    for _ in range(240):  # 等旧后台放开端口（最多 2 分钟）
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", JOB["port"]), Stub)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            return srv
        except OSError:
            time.sleep(0.5)
    return None


def _files(src: Path, dst: Path):
    """(新文件, 目标) 一个个列出来（跳过 __pycache__）。"""
    if src.is_dir():
        for f in sorted(src.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                yield f, dst / f.relative_to(src)
    else:
        yield src, dst


def _same(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def plan():
    """要换的文件和要删的文件（11-02：一模一样的不碰——正在被启动器用着的 WebView2 dll、GameButler.exe 一般都没变）。
    返回 (changed: [(新, 目标)], removed: [目标])。"""
    changed, removed = [], []
    for s in sorted(SRC.iterdir()):
        if s.name in KEEP:
            continue
        if s.name == "config":
            pairs = [p for c in sorted(s.iterdir()) if not c.name.startswith("butler.toml")  # 这台电脑的设置不动
                     for p in _files(c, ROOT / "config" / c.name)]
        elif s.name == "runtime":
            pairs = list(_files(s, ROOT / "runtime")) if JOB.get("swap_runtime") else []
        else:
            pairs = list(_files(s, ROOT / s.name))
        changed += [(f, d) for f, d in pairs if not (d.exists() and _same(f, d))]
    for top in CLEAN:  # 新版本里删掉的旧文件
        s_top, d_top = SRC / top, ROOT / top
        if s_top.is_dir() and d_top.is_dir():
            removed += [f for f in sorted(d_top.rglob("*")) if f.is_file() and "__pycache__" not in f.parts
                        and f.suffix != ".pyc" and not (s_top / f.relative_to(d_top)).exists()]
    return changed, removed


def _put(src: Path, d: Path):
    """复制一个文件。目标被占用（正在运行的 exe / 被加载的 dll）：先把旧的改名（Windows 允许给正在用的文件改名）再复制；
    改名留下的 *.old-update 由下次启动的管家删掉。"""
    d.parent.mkdir(parents=True, exist_ok=True)
    for i in range(6):  # 杀毒软件 / 索引正在读时会短暂拒绝写
        try:
            shutil.copy2(src, d)
            return
        except PermissionError:
            time.sleep(0.5)
    old = d.with_name("GameButler.old.exe" if d == ROOT / "GameButler.exe" else d.name + ".old-update")  # 启动器启动时删 GameButler.old.exe
    try:
        old.unlink()
    except OSError:
        pass
    d.replace(old)
    shutil.copy2(src, d)


def backup(changed, removed, bk: Path):
    """只备份这次会被换掉 / 删掉的旧文件（runtime 不备份：新包里带着完整的一份）。"""
    for _, d in changed:
        if d.exists() and "runtime" not in d.relative_to(ROOT).parts[:1]:
            (bk / d.relative_to(ROOT)).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(d, bk / d.relative_to(ROOT))
    for d in removed:
        (bk / d.relative_to(ROOT)).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(d, bk / d.relative_to(ROOT))
    (bk / "_新增的文件.txt").parent.mkdir(parents=True, exist_ok=True)
    (bk / "_新增的文件.txt").write_text("\n".join(str(d.relative_to(ROOT)) for _, d in changed if not d.exists()), encoding="utf-8")


def install(changed, removed):
    for s, d in changed:
        log(f"  {d.relative_to(ROOT)}")
        _put(s, d)
    for f in removed:
        try:
            f.unlink()
            log(f"  删除 {f.relative_to(ROOT)}")
        except OSError:
            pass


def restore(bk: Path):
    """放回旧文件：一个个放，某个放不回去也接着放别的；这次新加的文件删掉。"""
    errs = []
    if not bk.exists():
        return errs
    for f in sorted(bk.rglob("*")):
        if f.is_file() and f.name != "_新增的文件.txt":
            d = ROOT / f.relative_to(bk)
            try:
                if not (d.exists() and _same(f, d)):
                    _put(f, d)
            except Exception as e:
                errs.append(f"{d.relative_to(ROOT)}：{e}")
    added = bk / "_新增的文件.txt"
    for rel in (added.read_text(encoding="utf-8").splitlines() if added.exists() else []):
        try:
            (ROOT / rel).unlink()
        except OSError:
            pass
    return errs


def start_backend():
    py = JOB["python"]
    if not Path(py).exists():
        py = str(ROOT / "runtime" / "python" / "pythonw.exe")
    args = [py, str(ROOT / "gb.py"), "web", "--no-browser", "--restarted"] + ([f"--log={JOB['log']}"] if JOB.get("log") else [])
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "DETACHED_PROCESS", 0))
    subprocess.Popen(args, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)


def main():
    log(f"更新管家 {JOB['from']} → {JOB['to']}（{SRC}）")
    srv = bind_stub()
    if not srv:
        log("旧的后台一直没退出，放弃更新")
    res = {"ok": False, "from": JOB["from"], "to": JOB["to"], "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "error": ""}
    bk = Path(JOB["backup"])
    if srv:
        try:
            changed, removed = plan()
            log(f"要换 {len(changed)} 个文件、删 {len(removed)} 个")
            backup(changed, removed, bk)
            log(f"备份到 {bk}")
            install(changed, removed)
            if not (SRC / "VERSION").exists():  # 老的发布包里没有 VERSION：按发布标签写，免得下次又当成旧版本
                (ROOT / "VERSION").write_text(JOB["to"].lstrip("vV") + "\n", encoding="utf-8")
            res["ok"] = True
            log("换好了")
        except Exception as e:
            res["error"] = f"{type(e).__name__}: {e}"[:300]
            log(f"出错，放回旧文件：{res['error']}")
            errs = restore(bk)
            if errs:
                log(f"有 {len(errs)} 个旧文件放不回去：{'；'.join(errs)[:500]}")
    else:
        res["error"] = "旧的后台没有退出"
    Path(JOB["result"]).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if res["ok"]:
        upd = Path(JOB["result"]).parent
        try:
            (upd / "ready.json").unlink()
        except OSError:
            pass
        for c in upd.iterdir():  # 解压出来的新版本用完了：删掉（几十 MB）
            if c.is_dir() and c.name != "py" and SRC.is_relative_to(c):
                shutil.rmtree(c, ignore_errors=True)
        old = sorted((p for p in (ROOT / "_backup").glob("update_*") if p.is_dir()), key=lambda p: p.stat().st_mtime)
        for p in old[:-1]:  # 11-02：更新前的备份只留最近 1 份（只有这次换掉的文件，一般几百 KB）
            shutil.rmtree(p, ignore_errors=True)
    start_backend()  # 新后台会等端口空出来（--restarted）
    time.sleep(1)
    if srv:
        srv.shutdown()
        srv.server_close()
    log("已重启后台")


main()
