"""通过 MuMuManager.exe 管理模拟器实例：按名称找实例、启动、读当前 ADB 端口、关闭。"""
from __future__ import annotations

import json
import os
import subprocess
import time

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class MuMu:
    @classmethod
    def of(cls, cfg: dict) -> "MuMu":
        """按设置里的 MuMu 安装文件夹（设置 → 工具与游戏）。"""
        from .settings import get
        d = get(cfg, "emulator")["mumu_dir"]
        if not d or not os.path.exists(os.path.join(d, "nx_main", "MuMuManager.exe")):
            raise RuntimeError(f"没找到 MuMu 模拟器（{d or '还没选安装文件夹'}）：在「设置 → MuMu 模拟器」里选 MuMu 的安装文件夹")
        return cls(d)

    def __init__(self, mumu_dir: str):
        self.dir = mumu_dir
        self.manager = os.path.join(mumu_dir, "nx_main", "MuMuManager.exe")
        self.adb = os.path.join(mumu_dir, "nx_main", "adb.exe")

    def _call(self, *args, timeout=60) -> str:
        p = subprocess.run([self.manager, *args], capture_output=True, timeout=timeout,
                           creationflags=NO_WINDOW)
        out = p.stdout.decode("utf-8", errors="replace").strip()
        return out

    def instances(self) -> list[dict]:
        out = self._call("info", "-v", "all")
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            raise RuntimeError(f"MuMuManager 输出无法解析：{out[:200]}")
        if isinstance(data, dict) and "index" in data:  # 只有一个实例时直接返回对象
            data = {str(data["index"]): data}
        return [v for v in data.values() if isinstance(v, dict)]

    def find(self, name: str) -> dict:
        for inst in self.instances():
            if inst.get("name") == name:
                return inst
        names = [i.get("name") for i in self.instances()]
        raise RuntimeError(f"找不到名为「{name}」的 MuMu 实例，现有：{names}")

    def ensure_started(self, name: str, wait_s: int = 180) -> dict:
        """启动实例（已启动则跳过），等到安卓系统就绪并拿到 ADB 端口。
        正在关机的实例（上一次运行刚关掉它）：等它关完再启动。"""
        deadline = time.time() + wait_s
        launched = False
        while time.time() < deadline:
            inst = self.find(name)
            if inst.get("is_android_started") and inst.get("adb_port") and inst.get("is_process_started", True):
                time.sleep(5)  # 系统刚就绪时截图可能还是黑的
                return inst
            if not launched and not inst.get("is_process_started") and not inst.get("is_android_started"):
                self._call("control", "-v", str(inst["index"]), "launch")
                launched = True
            time.sleep(3)
        raise RuntimeError(f"MuMu 实例「{name}」{wait_s} 秒内没有启动完成")

    def shutdown(self, name: str, wait_s: int = 90):
        """关掉实例，等到它真的关完（不然紧接着的下一次运行会以为它还开着）。"""
        inst = self.find(name)
        self._call("control", "-v", str(inst["index"]), "shutdown")
        deadline = time.time() + wait_s
        while time.time() < deadline:
            inst = self.find(name)
            if not inst.get("is_process_started") and not inst.get("is_android_started"):
                return
            time.sleep(3)
        raise RuntimeError(f"MuMu 实例「{name}」{wait_s} 秒内没有关掉")

    # ---------- 分辨率（11-02：「重新获取题图」时临时调高，读完改回） ----------
    # 实例关着时直接改它的配置文件（MuMu 开机时读）：vms/<实例>/configs/customer_config.json 的
    # setting.resolution（mode.choose / mode.custom / current，"宽.000000:高.000000:dpi.000000"）和 shell_config.json 的
    # renderer.resolution（width / height / dpi）。改之前把两个文件原样留一份，用完原样写回。
    def vm_dir(self, inst: dict) -> str:
        import glob
        vms = os.path.join(self.dir, "vms")
        for d in glob.glob(os.path.join(vms, "*")):
            try:
                ex = json.load(open(os.path.join(d, "configs", "extra_config.json"), encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if ex.get("playerName") == inst.get("name"):
                return d
        hit = [d for d in glob.glob(os.path.join(vms, f"*-{inst['index']}")) if os.path.isdir(d)]
        if hit:
            return hit[0]
        raise RuntimeError(f"在 {vms} 里找不到实例「{inst.get('name')}」的文件夹")

    @staticmethod
    def _cfg_files(vm: str) -> list[str]:
        return [os.path.join(vm, "configs", "customer_config.json"), os.path.join(vm, "configs", "shell_config.json")]

    def resolution(self, vm: str) -> tuple[int, int, int]:
        d = json.load(open(self._cfg_files(vm)[0], encoding="utf-8"))
        cur = d["setting"]["resolution"]["current"]
        w, h, dpi = (int(float(x)) for x in cur.split(":"))
        return w, h, dpi

    def backup_configs(self, vm: str) -> dict:
        return {f: open(f, "rb").read() for f in self._cfg_files(vm)}

    @staticmethod
    def restore_configs(backup: dict):
        for f, raw in backup.items():
            with open(f, "wb") as fp:
                fp.write(raw)

    def set_resolution(self, vm: str, w: int, h: int, dpi: int):
        val = f"{w:.6f}:{h:.6f}:{dpi:.6f}"
        cf, sf = self._cfg_files(vm)
        d = json.load(open(cf, encoding="utf-8"))
        r = d["setting"]["resolution"]
        r["mode"]["choose"] = "resolution.mode.custom"
        r["mode"]["custom"] = val
        r["current"] = val
        json.dump(d, open(cf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        s = json.load(open(sf, encoding="utf-8"))
        s.setdefault("renderer", {}).setdefault("resolution", {}).update(width=f"{w:.6f}", height=f"{h:.6f}", dpi=f"{dpi:.6f}")
        json.dump(s, open(sf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    def screen(self, inst: dict) -> tuple[int, int] | None:
        """开机后用 adb 读安卓里的屏幕大小（核对用）；读不到返回 None。"""
        import re
        addr = self.address(inst)
        try:
            subprocess.run([self.adb, "connect", addr], capture_output=True, timeout=20, creationflags=NO_WINDOW)
            sz = subprocess.run([self.adb, "-s", addr, "shell", "wm", "size"], capture_output=True, timeout=20,
                                creationflags=NO_WINDOW).stdout.decode(errors="replace")
        except Exception:
            return None
        m = re.findall(r"(\d+)x(\d+)", sz)
        return tuple(map(int, m[-1])) if m else None

    @staticmethod
    def address(inst: dict) -> str:
        return f"{inst.get('adb_host_ip') or '127.0.0.1'}:{inst['adb_port']}"
