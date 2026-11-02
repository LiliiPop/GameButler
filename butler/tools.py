"""工具与游戏（设置页）：检查每个挂载的游戏的工具接得对不对、找工具、选文件夹、列 MuMu 实例。

- 检查：路径对不对、有没有 interface.json / 程序、任务能不能读出来、版本、MAA 工具有没有自带 Python。
- 自动查找：按预设（config/presets/）里写的常见文件夹名，在各个盘的根目录和常见文件夹下找（两层），不全盘扫描。
- 选择文件夹：在电脑上弹 Windows 的文件夹选择窗口（PowerShell），选好后把路径带回来。
"""
from __future__ import annotations

import json
import os
import re
import string
import subprocess
from pathlib import Path

from . import gamesdb as GD

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def check(cfg: dict, gid: str) -> dict:
    """检查一个游戏的工具：返回 {ok, items:[{ok, text}], version, tasks}。"""
    from . import games as G
    g = GD.record(cfg, gid)
    items = G.type_class(g).check_items(cfg, gid, g)
    ver = next((x["version"] for x in items if "version" in x), "")
    ntask = next((x["tasks"] for x in items if "tasks" in x), 0)
    items = [{"ok": x["ok"], "text": x["text"]} for x in items]
    return {"ok": all(x["ok"] for x in items), "items": items, "version": ver, "tasks": ntask}


def scan(gid: str, cfg: dict) -> list[str]:
    """按这个游戏的预设里写的常见文件夹名，在常见位置找工具（各盘根目录、Program Files、用户文件夹下两层）。"""
    g = GD.record(cfg, gid)
    pr = GD.preset(g.get("preset", "")) if g.get("preset") else None
    if not pr or os.name != "nt":
        return []
    from . import games as G
    want = "interface.json" if G.type_class(g).path_field == "project_dir" else Path(g.get("exe", "")).name
    bases = []
    for drv in string.ascii_uppercase:
        root = f"{drv}:\\"
        if os.path.exists(root):
            bases += [root, os.path.join(root, "Program Files"), os.path.join(root, "Games")]
    home = os.path.expanduser("~")
    bases += [home, os.path.join(home, "Desktop"), os.path.join(home, "Downloads"), os.path.join(home, "Documents")]
    found = []
    for b in bases:
        for name in pr.get("look", []):
            for cand in (Path(b) / name, *(Path(b) / name).glob("*")):
                target = cand / want
                if target.exists():
                    p = str(cand if want == "interface.json" else target)
                    if p not in found:
                        found.append(p)
    return found[:5]


def browse(title: str = "选择文件夹") -> str:
    """在电脑上弹出文件夹选择窗口，返回选中的路径（取消返回空）。
    11-02：直接调 Windows 的选文件夹窗口（shell32.SHBrowseForFolderW），不再经过 PowerShell——
    有的电脑上 PowerShell 不在 PATH 里 / 被安全软件拦下（「系统找不到指定的文件」）。调不起来时再用完整路径试 PowerShell。"""
    if os.name != "nt":
        return ""
    try:
        return _browse_native(title)
    except ValueError:  # 选了「此电脑」之类：直接告诉你
        raise
    except Exception as e:  # 极少见：再试 PowerShell（用完整路径，不靠 PATH）
        first = f"{type(e).__name__}: {e}"
    ps_exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "$f=New-Object System.Windows.Forms.FolderBrowserDialog;"
          f"$f.Description='{title}';$f.ShowNewFolderButton=$true;"
          "$w=New-Object System.Windows.Forms.Form;$w.TopMost=$true;"
          "if($f.ShowDialog($w) -eq 'OK'){[Console]::OutputEncoding=[Text.Encoding]::UTF8;Write-Output $f.SelectedPath}")
    try:
        p = subprocess.run([ps_exe if os.path.exists(ps_exe) else "powershell", "-NoProfile", "-STA", "-Command", ps],
                           capture_output=True, timeout=600, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"选择文件夹的窗口打不开（{first}；{type(e).__name__}: {e}）。可以直接把路径粘贴进输入框") from e
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", errors="replace").strip()[:300]
        raise RuntimeError(f"选择文件夹的窗口打不开：{err or f'退出代码 {p.returncode}'}；可以直接把路径粘贴进输入框")
    return p.stdout.decode("utf-8", errors="replace").strip()  # 空 = 你点了取消


def _browse_native(title: str) -> str:
    """Windows 自带的选文件夹窗口（新样式：可以新建文件夹、可以粘贴路径）。在单独的线程里跑（要单线程套间 COM）。"""
    import ctypes
    import threading
    from ctypes import wintypes

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p), ("pszDisplayName", wintypes.LPWSTR),
                    ("lpszTitle", wintypes.LPCWSTR), ("ulFlags", wintypes.UINT), ("lpfn", ctypes.c_void_p),
                    ("lParam", wintypes.LPARAM), ("iImage", ctypes.c_int)]
    out: dict = {}

    def run():
        try:
            shell32, ole32, user32 = ctypes.windll.shell32, ctypes.windll.ole32, ctypes.windll.user32
            ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
            shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
            shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFOW)]
            shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
            ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            user32.GetForegroundWindow.restype = wintypes.HWND
            name = ctypes.create_unicode_buffer(260)
            # 挂在当前最前面的窗口（管家窗口）上：弹在它上面，不会躲到后面
            # 11-02：后台进程弹的窗口 Windows 不让它自己跑到最前面 → 窗口一出来就设成置顶、再拉到前台
            CB = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.UINT, wintypes.LPARAM, wintypes.LPARAM)
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]

            def on_msg(hwnd, msg, lp, data):
                if msg == 1:  # BFFM_INITIALIZED
                    user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)  # HWND_TOPMOST, 不改位置大小, 显示
                    user32.SetForegroundWindow(hwnd)
                return 0
            cb = CB(on_msg)
            bi = BROWSEINFOW(user32.GetForegroundWindow(), None, name, title, 0x0001 | 0x0010 | 0x0040,
                             ctypes.cast(cb, ctypes.c_void_p), 0, 0)
            pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))  # 只要文件夹 | 有输入框 | 新样式（能新建文件夹）
            if not pidl:
                out["path"] = ""
                return
            buf = ctypes.create_unicode_buffer(32768)
            ok = shell32.SHGetPathFromIDListW(pidl, buf)
            ole32.CoTaskMemFree(pidl)
            out["path"] = buf.value if ok else ""
            if not ok:
                out["error"] = "选的不是硬盘上的文件夹（例如「此电脑」「网络」），请选一个具体的文件夹"
        except Exception as e:
            out["exc"] = e
        finally:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(900)
    if "exc" in out:
        raise out["exc"]
    if out.get("error"):
        raise ValueError(out["error"])
    return out.get("path", "")


def _vm_resolutions(mumu_dir: str) -> dict:
    """实例没开时 MuMuManager 不给分辨率：从实例配置文件里读（10-23 对过 MuMu 12 / 15 的格式）。
    vms/MuMuPlayer-12.0-<序号>/configs/customer_config.json 的 "setting.resolution.current" = "宽:高:DPI"；
    没有时看 shell_config.json 的 "renderer.resolution.width/height/dpi"。
    返回 {序号: (宽, 高, DPI)}，读不到的是 {序号: "原因"}。"""
    out = {}
    root = Path(mumu_dir, "vms")
    for d in sorted(root.glob("*")) if root.exists() else []:
        m = re.search(r"-(\d+)$", d.name)
        if m:
            try:
                out[m.group(1)] = _vm_resolution(d / "configs")
            except (OSError, ValueError, TypeError) as e:
                out[m.group(1)] = f"读不到分辨率：{e}"
    return out


def _vm_resolution(conf: Path) -> tuple:
    def get(d, dotted):
        """"a.b.c"：嵌套字典或扁平的点号键都认。"""
        if dotted in d:
            return d[dotted]
        cur = d
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur
    num = lambda v: int(float(v)) if v not in (None, "") and float(v) > 0 else None
    cc, sc = conf / "customer_config.json", conf / "shell_config.json"
    if cc.exists():
        parts = str(get(json.loads(cc.read_text(encoding="utf-8-sig")), "setting.resolution.current") or "").split(":")
        if len(parts) >= 2 and num(parts[0]) and num(parts[1]):
            return num(parts[0]), num(parts[1]), num(parts[2]) if len(parts) > 2 else None
    if sc.exists():
        sh = json.loads(sc.read_text(encoding="utf-8-sig"))
        w, h = num(get(sh, "renderer.resolution.width")), num(get(sh, "renderer.resolution.height"))
        if w and h:
            return w, h, num(get(sh, "renderer.resolution.dpi"))
    raise ValueError(f"{conf} 里的配置文件没有分辨率")


def emulators(cfg: dict) -> dict:
    """MuMu 多开实例列表：[{name, index, started, resolution}]。"""
    from .mumu import MuMu
    from .settings import get
    d = get(cfg, "emulator")["mumu_dir"]
    close = get(cfg, "emulator")["close"]
    if not d or not os.path.exists(os.path.join(d, "nx_main", "MuMuManager.exe")):
        return {"ok": False, "mumu_dir": d, "error": "没找到 MuMu 模拟器（MuMuManager.exe）：在下面选 MuMu 的安装文件夹", "instances": []}
    try:
        out = []
        files = _vm_resolutions(d)
        for i in MuMu(d).instances():
            w, h, dpi = i.get("resolution_width"), i.get("resolution_height"), i.get("resolution_dpi")
            err = ""
            if not (w and h):  # 实例没开：从配置文件读
                f = files.get(str(i.get("index")), "读不到分辨率：没找到这个实例的配置文件夹")
                if isinstance(f, str):
                    err = f
                else:
                    w, h, dpi = f
            out.append({"name": i.get("name", ""), "index": i.get("index"), "started": bool(i.get("is_android_started")),
                        "resolution": f"{w}×{h}" if not err else "", "dpi": dpi or "", "resolution_error": err})
        return {"ok": True, "mumu_dir": d, "close": close, "instances": out}
    except Exception as e:
        return {"ok": False, "mumu_dir": d, "error": str(e), "instances": []}


def needs_setup(cfg: dict) -> bool:
    """第一次打开：还没挂过任何游戏，也没有仅关注的游戏（11-02）。"""
    from . import watch as W
    return not GD.all_records(cfg) and not W.records(cfg)
