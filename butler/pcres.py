"""电脑游戏分辨率（模块 C）：运行前把游戏自己的分辨率设置改成 1920×1080 窗口化，跑完改回原值。

只改游戏自己写在注册表里的设置（相当于你在游戏设置里改），不碰游戏程序本身。游戏开着时不改（它退出时会把自己的设置写回去）。
- 原神：HKCU\\Software\\miHoYo\\原神（国际服 Genshin Impact）里的 Unity 设置
    Screenmanager Resolution Width_h…  / Screenmanager Resolution Height_h… （DWORD）
    Screenmanager Fullscreen mode_h…   （DWORD，3 = 窗口化）/ Screenmanager Is Fullscreen mode_h…（DWORD，0 = 非全屏）
  BetterGI 要求原神是 1920×1080 **窗口**，所以只调成窗口化。
- 崩铁：HKCU\\Software\\miHoYo\\崩坏：星穹铁道 的 GraphicsSettings_PCResolution_h…（二进制 JSON：{"width","height","isFullScreen"}），
  以及同样的 Screenmanager 几项。
原值存在 data/resolution_backup/<游戏>.json；中途出错也能用「恢复原分辨率」改回。
开关：游戏记录的 resolution_switch（设置页里开关，经 mount.update 保存）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

KEYS = {
    "genshin": [r"Software\miHoYo\原神", r"Software\miHoYo\Genshin Impact"],
    "starrail": [r"Software\miHoYo\崩坏：星穹铁道", r"Software\Cognosphere\Star Rail"],
}
GAME_EXE = {"genshin": ["YuanShen.exe", "GenshinImpact.exe"], "starrail": ["StarRail.exe"]}
P_W, P_H = "Screenmanager Resolution Width_h", "Screenmanager Resolution Height_h"
P_FSM, P_ISFS = "Screenmanager Fullscreen mode_h", "Screenmanager Is Fullscreen mode_h"
P_SR = "GraphicsSettings_PCResolution_h"
WANT_W, WANT_H = 1920, 1080


def supported(gid: str) -> bool:
    return gid in KEYS


def _winreg():
    if os.name != "nt":
        raise RuntimeError("只在 Windows 上可用")
    import winreg
    return winreg


def screen_size() -> tuple[int, int] | None:
    """主显示器当前的实际分辨率（不受系统缩放影响）。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DEVMODEW(ctypes.Structure):
            _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                        ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
                        ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                        ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long),
                        ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                        ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                        ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                        ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD),
                        ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                        ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                        ("dmDisplayFrequency", wintypes.DWORD)]
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        if ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):  # ENUM_CURRENT_SETTINGS
            return int(dm.dmPelsWidth), int(dm.dmPelsHeight)
    except Exception:
        pass
    return None


def _find_key(gid: str):
    winreg = _winreg()
    for path in KEYS.get(gid, []):
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
            winreg.CloseKey(k)
            return path
        except OSError:
            continue
    return None


def _values(path: str) -> dict:
    """这把注册表键里和分辨率有关的值：{名字: (值, 类型)}。"""
    winreg = _winreg()
    out = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as k:
        i = 0
        while True:
            try:
                name, val, typ = winreg.EnumValue(k, i)
            except OSError:
                break
            i += 1
            if name.startswith((P_W, P_H, P_FSM, P_ISFS, P_SR)):
                out[name] = (val, typ)
    return out


def _sr_json(val) -> dict | None:
    try:
        raw = bytes(val).rstrip(b"\x00")
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def describe(gid: str) -> dict:
    """当前分辨率设置（给界面看）。"""
    if not supported(gid):
        return {"supported": False}
    try:
        path = _find_key(gid)
    except RuntimeError as e:
        return {"supported": True, "found": False, "error": str(e)}
    if not path:
        return {"supported": True, "found": False, "error": "注册表里没找到游戏的设置（游戏至少要启动过一次）"}
    vals = _values(path)
    w = next((v for n, (v, _) in vals.items() if n.startswith(P_W)), None)
    h = next((v for n, (v, _) in vals.items() if n.startswith(P_H)), None)
    fsm = next((v for n, (v, _) in vals.items() if n.startswith(P_FSM)), None)
    isfs = next((v for n, (v, _) in vals.items() if n.startswith(P_ISFS)), None)
    sr = next((_sr_json(v) for n, (v, _) in vals.items() if n.startswith(P_SR)), None)
    if sr:
        w, h, isfs = sr.get("width", w), sr.get("height", h), int(bool(sr.get("isFullScreen")))
    windowed = (fsm == 3) if fsm is not None else (isfs == 0 if isfs is not None else None)
    return {"supported": True, "found": True, "key": "HKCU\\" + path, "width": w, "height": h, "windowed": windowed,
            "names": sorted(vals), "ok": w == WANT_W and h == WANT_H and windowed is not False}


def _backup_path(cfg, gid) -> Path:
    return Path(cfg["machine"]["data_dir"]) / "resolution_backup" / f"{gid}.json"


def enabled(cfg: dict, gid: str) -> bool:
    """开关存在游戏记录的 resolution_switch 里。"""
    return bool(cfg["games"][gid].get("resolution_switch", False))


def forget(cfg: dict, gid: str):
    """彻底删除：开关在游戏记录里，随记录删掉；分辨率备份（resolution_backup）是你游戏原来的设置，留着，
    还没恢复的可以在那里找到。"""


def apply(cfg: dict, gid: str) -> str:
    """改成 1920×1080 窗口化（先备份原值；已经有没恢复的备份时不覆盖备份）。返回说明。"""
    winreg = _winreg()
    path = _find_key(gid)
    if not path:
        raise RuntimeError("注册表里没找到游戏的设置（游戏至少要启动过一次）")
    vals = _values(path)
    if not vals:
        raise RuntimeError("注册表里没找到分辨率设置")
    bp = _backup_path(cfg, gid)
    if not bp.exists():
        bp.parent.mkdir(parents=True, exist_ok=True)
        bp.write_text(json.dumps({"key": path, "time": datetime.now().isoformat(timespec="seconds"),
                                  "values": {n: [list(v) if isinstance(v, bytes) else v, t] for n, (v, t) in vals.items()}},
                                 ensure_ascii=False), encoding="utf-8")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
        for n, (v, t) in vals.items():
            if n.startswith(P_W):
                winreg.SetValueEx(k, n, 0, t, WANT_W)
            elif n.startswith(P_H):
                winreg.SetValueEx(k, n, 0, t, WANT_H)
            elif n.startswith(P_FSM):
                winreg.SetValueEx(k, n, 0, t, 3)
            elif n.startswith(P_ISFS):
                winreg.SetValueEx(k, n, 0, t, 0)
            elif n.startswith(P_SR):
                d = _sr_json(v) or {}
                d.update(width=WANT_W, height=WANT_H, isFullScreen=False)
                winreg.SetValueEx(k, n, 0, t, json.dumps(d, separators=(",", ":")).encode("utf-8") + b"\x00")
    return "已调整为 1920×1080 窗口化（跑完恢复）"


def restore(cfg: dict, gid: str) -> str:
    bp = _backup_path(cfg, gid)
    if not bp.exists():
        return "没有需要恢复的备份"
    winreg = _winreg()
    d = json.loads(bp.read_text(encoding="utf-8"))
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, d["key"], 0, winreg.KEY_SET_VALUE) as k:
        for n, (v, t) in d["values"].items():
            winreg.SetValueEx(k, n, 0, t, bytes(v) if isinstance(v, list) else v)
    bp.unlink()
    return "已恢复原分辨率"


def pending_restore(cfg: dict, gid: str) -> bool:
    return _backup_path(cfg, gid).exists()


def wrap(cfg: dict, gid: str, ctx, run):
    """包住一次运行：开关开着时，跑之前改分辨率、跑完（含出错）恢复。屏幕小于 1920×1080 时提示并跳过这次运行。"""
    if not supported(gid) or not enabled(cfg, gid):
        return run()
    size = screen_size()
    if size and (size[0] < WANT_W or size[1] < WANT_H):
        ctx.emit("fatal", reason=f"屏幕分辨率 {size[0]}×{size[1]} 小于 1920×1080，放不下 1920×1080 的游戏窗口，这次不运行"
                                 "（可以在设置里关掉「运行前调整分辨率」后自己处理）")
        return {"ok": False, "results": []}
    if any(ctx.is_running(x) for x in GAME_EXE.get(gid, [])):
        ctx.emit("warn", msg="游戏已经开着，这次不改分辨率（游戏关着时才能改）")
        return run()
    try:
        ctx.emit("info", msg=apply(cfg, gid))
    except Exception as e:
        ctx.emit("warn", msg=f"没能调整分辨率：{e}；按游戏当前设置运行")
        return run()
    try:
        return run()
    finally:
        try:
            ctx.emit("info", msg=restore(cfg, gid))
        except Exception as e:
            ctx.emit("warn", msg=f"恢复原分辨率失败：{e}（可在设置页点「恢复原分辨率」）")
