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


def copy_any(s: Path, d: Path):
    if s.is_dir():
        shutil.copytree(s, d, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        d.parent.mkdir(parents=True, exist_ok=True)
        for i in range(20):  # Windows：杀毒软件 / 索引正在读时会短暂拒绝写
            try:
                shutil.copy2(s, d)
                return
            except PermissionError:
                time.sleep(0.5)
        shutil.copy2(s, d)


def entries():
    """新版本里要放进管家文件夹的东西：(源, 目标)。"""
    out = []
    for s in sorted(SRC.iterdir()):
        if s.name in KEEP:
            continue
        if s.name == "config":
            for c in sorted(s.iterdir()):
                if not c.name.startswith("butler.toml"):  # 这台电脑的设置不动
                    out.append((c, ROOT / "config" / c.name))
        elif s.name == "runtime":
            if JOB.get("swap_runtime"):
                out.append((s, ROOT / "runtime"))
        else:
            out.append((s, ROOT / s.name))
    return out


def backup(items, bk: Path):
    for s, d in items:
        if d.exists() and d.name != "runtime":  # runtime 太大不备份（新包里带着完整的一份）
            copy_any(d, bk / d.relative_to(ROOT))


def install(items):
    for s, d in items:
        if d.name.lower() == "gamebutler.exe" and d.exists():
            if d.read_bytes() == s.read_bytes():
                continue
            old = d.with_name("GameButler.old.exe")  # 正在运行的 exe 不能覆盖，但能改名；启动器下次启动时删掉旧的
            try:
                old.unlink()
            except OSError:
                pass
            d.replace(old)
        log(f"  {d.relative_to(ROOT)}")
        copy_any(s, d)
    for top in CLEAN:  # 新版本里删掉的旧文件
        s_top, d_top = SRC / top, ROOT / top
        if not s_top.is_dir() or not d_top.is_dir():
            continue
        for f in list(d_top.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and not (s_top / f.relative_to(d_top)).exists():
                try:
                    f.unlink()
                    log(f"  删除 {f.relative_to(ROOT)}")
                except OSError:
                    pass


def restore(bk: Path):
    if bk.exists():
        for p in bk.iterdir():
            copy_any(p, ROOT / p.name)


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
        items = entries()
        try:
            backup(items, bk)
            log(f"备份到 {bk}")
            install(items)
            if not (SRC / "VERSION").exists():  # 老的发布包里没有 VERSION：按发布标签写，免得下次又当成旧版本
                (ROOT / "VERSION").write_text(JOB["to"].lstrip("vV") + "\n", encoding="utf-8")
            res["ok"] = True
            log("换好了")
        except Exception as e:
            res["error"] = f"{type(e).__name__}: {e}"[:300]
            log(f"出错，放回旧文件：{res['error']}")
            try:
                restore(bk)
            except Exception as e2:
                log(f"放回旧文件也出错：{e2}")
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
        for p in old[:-3]:  # 更新前的备份只留最近 3 份
            shutil.rmtree(p, ignore_errors=True)
    start_backend()  # 新后台会等端口空出来（--restarted）
    time.sleep(1)
    if srv:
        srv.shutdown()
        srv.server_close()
    log("已重启后台")


main()
