"""数据文件的统一读写：管家 data 目录下的 JSON 都经过这里。

- read：文件不存在 = 还没有数据，返回默认值的副本；内容损坏直接报错（写入是原子的，正常不会损坏）。
- write：先写临时文件再整体替换，读的一方永远看到完整的旧内容或新内容。
- update：读 → 改 → 写，整个过程持有文件锁，后台进程和运行进程同时改同一个文件也不会互相覆盖。

锁文件是目标文件所在文件夹里的 .jsonlock（同一文件夹的文件共用一把锁）。
"""
from __future__ import annotations

import copy
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path


class DataError(RuntimeError):
    pass


def read(path: Path | str, default):
    path = Path(path)
    for i in range(20):  # Windows：另一个进程正在替换这个文件时会短暂拒绝打开
        try:
            text = path.read_text(encoding="utf-8")
            break
        except FileNotFoundError:
            return copy.deepcopy(default)
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    else:
        raise DataError(f"打不开 {path}：一直被别的程序占用")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise DataError(f"{path} 内容损坏（{e}），请从备份恢复或删掉这个文件") from e


def write(path: Path | str, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:  # 落盘后再替换：断电也不会留下半个文件
        f.write(json.dumps(obj, ensure_ascii=False, indent=1))
        f.flush()
        os.fsync(f.fileno())
    for i in range(40):  # Windows：有人正在读目标文件时 os.replace 会被拒绝，稍等再试
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    raise DataError(f"写不进 {path}：一直被别的程序占用")


@contextmanager
def locked(path: Path | str):
    """同一文件夹的读改写互斥（跨进程）。"""
    lock = Path(path).parent / ".jsonlock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock, "a+b")
    acquired = False
    try:
        deadline = time.monotonic() + 60
        while not acquired:
            try:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() > deadline:
                    raise DataError(f"等不到 {lock} 的锁：可能有进程卡住了")
                time.sleep(0.02)
        yield
    finally:
        try:
            if acquired:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


def update(path: Path | str, default, fn):
    """在锁里读出文件、交给 fn 修改（fn 可以就地改，也可以返回新对象），写回并返回结果。"""
    with locked(path):
        obj = read(path, default)
        new = fn(obj)
        obj = obj if new is None else new
        write(path, obj)
        return obj


def remove(path: Path | str):
    """删掉一个文件或文件夹（不存在也算删掉了）。"""
    import shutil
    path = Path(path)
    for i in range(40):  # Windows：别的进程正在读时会短暂拒绝删除
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    raise DataError(f"删不掉 {path}：一直被别的程序占用")
