"""电脑游戏的抽卡资源（11-02）：原神（BetterGI）、崩铁（三月七）跑完后，游戏还开着时，管家自己打开卡池界面读顶栏数字。

- 不登录任何账号；只按键、点「跃迁」这种入口字、识字，不点抽卡按钮。
- 用 runner/maa_runner.py + MaaFramework 的 Win32 控制器接管游戏窗口（管家自带的 Python 里有 maafw），
  任务就是模拟器游戏用的「💎读抽卡资源」（runner/gacha_reader.py），路线里多了「按键」一步。
- 识字模型借用已挂载的 MAA 项目的 resource（里面带 model/ocr）。

游戏记录 pc_gacha（预设里写好；坐标按短边 720 的截图，16:9 窗口 = 1280×720）：
  {"exe": ["YuanShen.exe", "GenshinImpact.exe"], "window_regex": "^原神$",
   "route": [{"key": 114, "wait": 3}],             # F3 = 祈愿
   "bar_roi": [760, 0, 520, 64], "keys": ["纠缠之缘", "原石"], "back": 1, "back_key": 27,
   "calibrate": true}                               # 校准中：只存截图、记下识别到的字，不记读数
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from . import games as G
from . import winshot


def conf_of(g: dict) -> dict | None:
    c = g.get("pc_gacha")
    return c if c and g.get("read_gacha", True) is not False else None


def ocr_resource(cfg: dict) -> str:
    """找一个带识字模型（model/ocr）的 MAA 项目 resource 目录。"""
    for gid, g in cfg["games"].items():
        if G.kind(g) not in ("maa",) or not g.get("project_dir"):
            continue
        try:
            for p in G.adapter(cfg, gid).project().resource_paths():
                path = (Path(g["project_dir"]) / p).resolve()
                if (path / "model" / "ocr").exists():
                    return str(path)
        except Exception:
            continue
    return ""


def window_open(conf: dict) -> bool:
    try:
        return bool(winshot._windows_of(conf.get("exe") or []))
    except Exception:
        return False


def read(cfg: dict, gid: str, ctx) -> bool:
    """游戏窗口还开着就读一次。返回是否读了（读成没成都算读了）。"""
    g = cfg["games"][gid]
    conf = conf_of(g)
    if not conf:
        return False
    if not window_open(conf):
        ctx.emit("info", msg="没读抽卡资源：游戏已经关了。要读的话，把工具里的「完成后操作」改成不关游戏（管家读完会自己关）")
        return False
    res = ocr_resource(cfg)
    if not res:
        ctx.emit("warn", msg="没读抽卡资源：找不到识字模型（需要至少挂载一个 MAA 类的模拟器游戏）")
        return False
    data_dir = Path(cfg["machine"]["data_dir"]) / "maafw" / gid
    job = {
        "game": gid, "project_dir": str(Path(res).parent), "data_dir": str(data_dir),
        "resource_paths": [res], "agent": None,
        "controller": {"type": "win32", "window_regex": conf.get("window_regex", ""), "class_regex": conf.get("class_regex", ""),
                       "screencap": conf.get("screencap", "FramePool"), "mouse": conf.get("mouse", "Seize"),
                       "keyboard": conf.get("keyboard", "Seize")},
        "tasks": [{"name": G.GACHA_TASK, "task": G.GACHA_TASK, "entry": f"@gacha:{gid}", "override": {},
                   "gacha_conf": {**conf, "debug": bool(conf.get("calibrate") or conf.get("debug"))},
                   "timeout_s": 180, "stall_s": 0, "retries": 0, "retry_on_fail": False, "restart_on_fail": False,
                   "fail_retries": 0, "evidence": False, "judge": {}, "alert_hints": []}],
        "recovery": {}, "stop_file": getattr(ctx, "stop_file", ""), "evidence_dir": "",
    }
    job_path = ctx.log_path.with_suffix(".gacha.job.json")
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    ctx.emit("info", msg="游戏还开着：打开卡池界面读抽卡资源" + ("（校准中：只截图，不记读数）" if conf.get("calibrate") else ""))
    py = str(G.RUNTIME_PY) if G.RUNTIME_PY.exists() else "python"
    proc = subprocess.Popen([py, "-u", str(G.RUNNER), str(job_path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            cwd=str(Path(res).parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    t0 = time.monotonic()
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "reading" and conf.get("calibrate"):
                ctx.emit("info", msg=f"校准中，读到的数（不记）：{ev.get('values')}")
                continue
            if ev.get("event") == "summary":
                break
            ctx.forward(ev)
            if time.monotonic() - t0 > 240:
                break
        proc.wait(timeout=20)
    except Exception:
        pass
    finally:
        if proc.poll() is None:
            G.kill_tree(proc.pid)
    return True
