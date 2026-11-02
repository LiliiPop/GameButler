"""电脑游戏的留证截图（11-02）：原神、崩铁这类由 BetterGI / 三月七操作的游戏，管家看不到它们走到哪一步，
只能在日志里认出「这一项做完了」的那一刻，把游戏窗口截一张。

- 按进程名找窗口（YuanShen.exe、StarRail.exe…），取那个进程最大的可见窗口；
- 从屏幕上截窗口那一块（游戏用 DirectX 画，PrintWindow 常常是黑的；跑任务时游戏在前台，屏幕上就是它）；
- 只用 ctypes + numpy + zlib（管家自带的 Python 没有 PIL）。
截不到（窗口最小化、被挡住、游戏已经关了）返回 None，不影响任务结果。
"""
from __future__ import annotations

import os
import struct
import time
import zlib

GAME_EXES = ["YuanShen.exe", "GenshinImpact.exe", "StarRail.exe", "JX3ClientX3DX64.exe", "JX3ClientX64.exe"]


def _png(bgra, w: int, h: int) -> bytes:
    import numpy
    rgb = numpy.ascontiguousarray(bgra[:, :, 2::-1])  # BGRA → RGB
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _windows_of(names: list[str]):
    """[(面积, hwnd)]：这些进程的可见、没最小化的顶层窗口。"""
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    u32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    u32.IsWindowVisible.argtypes = u32.IsIconic.argtypes = [ctypes.c_void_p]
    u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    want = {n.lower() for n in names}
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not u32.IsWindowVisible(hwnd) or u32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = k32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return True
        try:
            buf = ctypes.create_unicode_buffer(520)
            n = wintypes.DWORD(520)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) and os.path.basename(buf.value).lower() in want:
                r = wintypes.RECT()
                u32.GetClientRect(hwnd, ctypes.byref(r))
                area = (r.right - r.left) * (r.bottom - r.top)
                if area > 200 * 200:
                    out.append((area, hwnd))
        finally:
            k32.CloseHandle(h)
        return True

    u32.EnumWindows(cb, 0)
    return sorted(out, reverse=True)


def grab(names: list[str]) -> bytes | None:
    """截这些进程里最大的那个游戏窗口（只截画面，不含标题栏），返回 PNG；截不到返回 None。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        import numpy
        wins = _windows_of([n for n in GAME_EXES if n in names] or names)
        if not wins:
            return None
        hwnd = wins[0][1]
        u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
        H = ctypes.c_void_p  # 64 位下句柄是指针大小：不声明会被截成 32 位
        u32.GetDC.restype = H; u32.GetDC.argtypes = [H]
        u32.ReleaseDC.argtypes = [H, H]
        u32.GetClientRect.argtypes = [H, ctypes.POINTER(wintypes.RECT)]
        u32.ClientToScreen.argtypes = [H, ctypes.POINTER(wintypes.POINT)]
        g32.CreateCompatibleDC.restype = H; g32.CreateCompatibleDC.argtypes = [H]
        g32.CreateCompatibleBitmap.restype = H; g32.CreateCompatibleBitmap.argtypes = [H, ctypes.c_int, ctypes.c_int]
        g32.SelectObject.restype = H; g32.SelectObject.argtypes = [H, H]
        g32.BitBlt.argtypes = [H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, H, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        g32.GetDIBits.argtypes = [H, H, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
        g32.DeleteObject.argtypes = [H]; g32.DeleteDC.argtypes = [H]
        r = wintypes.RECT()
        u32.GetClientRect(hwnd, ctypes.byref(r))
        pt = wintypes.POINT(0, 0)
        u32.ClientToScreen(hwnd, ctypes.byref(pt))
        w, h = r.right - r.left, r.bottom - r.top
        sdc = u32.GetDC(0)
        mdc = g32.CreateCompatibleDC(sdc)
        bmp = g32.CreateCompatibleBitmap(sdc, w, h)
        g32.SelectObject(mdc, bmp)
        g32.BitBlt(mdc, 0, 0, w, h, sdc, pt.x, pt.y, 0x00CC0020 | 0x40000000)  # SRCCOPY | CAPTUREBLT
        hdr = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)  # BITMAPINFOHEADER，自上而下
        buf = ctypes.create_string_buffer(w * h * 4)
        g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.create_string_buffer(hdr, 44), 0)
        g32.DeleteObject(bmp)
        g32.DeleteDC(mdc)
        u32.ReleaseDC(0, sdc)
        img = numpy.frombuffer(buf.raw, dtype=numpy.uint8).reshape(h, w, 4)
        if int(img[:, :, :3].max()) < 8:  # 全黑：窗口被挡住或画面还没出来
            return None
        return _png(img, w, h)
    except Exception:
        return None


def save(cfg: dict, gid: str, game_day: str, task_key: str, names: list[str], tag: str = "end") -> str:
    """截一张存成留证截图（文件名和模拟器游戏的一样，报告按任务名找）。返回文件路径，没截到返回空。"""
    from . import evidence as EV
    png = grab(names)
    if not png:
        return ""
    d = EV.root(cfg) / game_day / gid
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{time.strftime('%H%M%S')}_{EV.safe(task_key)}_{EV.safe(tag)}.png"
    p.write_bytes(png)
    return str(p)
