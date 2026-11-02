"""读抽卡资源（总纲 10-23）：「💎读抽卡资源」任务。只看不点抽卡按钮，不消耗任何东西。

做法：从主界面按 route 点进卡池（或商店）界面 → 识别顶栏 bar_roi 里的数字，按从左到右的顺序对上 keys →
按返回键退回去。结果用 reading 事件交给管家，记成读数（来源 ocr）。

每个游戏在 config 里写（坐标按短边 720 的截图，横屏 1280×720、竖屏 720×1280）：
  [games.<id>.gacha_reader]
  route = [{ word = "许愿", roi = [0, 0, 720, 1280] }]   # 依次点这些字（找不到就失败，不乱点）
  bar_roi = [300, 0, 420, 80]                          # 顶栏数字所在区域
  keys = ["钻石", "许愿券"]                            # 顶栏从左到右的数字分别是什么
  back = 2                                             # 读完按几次返回
  avoid = ["抽一次", "抽十次"]                          # 安全：点之前核对，点的字里含这些就不点
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from notice_reader import Screen, png_bytes  # noqa: E402

NUM_RE = re.compile(r"(\d[\d,，.]*)\s*(万)?")
AVOID = ("抽一次", "抽十次", "十连", "单抽", "购买", "兑换", "确认", "支付", "充值")


def _num(text: str):
    m = NUM_RE.search(text.replace(" ", ""))
    if not m:
        return None
    raw = m.group(1).replace(",", "").replace("，", "")
    try:
        v = float(raw) if "." in raw else int(raw)
    except ValueError:
        return None
    if m.group(2):
        v = v * 10000
    return int(v)


def run(game: str, controller, tasker, conf: dict, log=print, stop=lambda: False, out_dir: str = "") -> tuple[str, str, dict]:
    """返回 (结果, 说明, {资源: 数量})。"""
    s = Screen(controller, tasker, log, stop)
    s.back_key = int(conf.get("back_key", 4))
    img = s.shot()
    h, w = img.shape[:2]
    full = [0, 0, w, h]
    avoid = tuple(conf.get("avoid") or ()) + AVOID

    def dump(tag):  # debug = true：每一步存整张截图（校准用）
        if conf.get("debug") and out_dir:
            try:
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                Path(out_dir, f"full_{game}_{tag}.png").write_bytes(png_bytes(s.shot()))
            except Exception:
                pass
    dump("0")
    for step in conf.get("route") or []:
        if stop():
            return "stopped", "已手动停止", {}
        if step.get("key"):  # 电脑游戏：按快捷键（原神 F3 = 114 打开祈愿；Esc = 27 打开菜单）
            controller.post_click_key(int(step["key"])).wait()
            time.sleep(float(step.get("wait", 2.5)))
            dump(f"key{step['key']}")
            continue
        word = step["word"]
        pos = None
        for _ in range(3):
            pos = s.locate(step.get("roi") or full, word)
            if pos:
                break
            time.sleep(1.5)
        if not pos:
            return "failed", f"没找到「{word}」（不在主界面？）", {}
        hit = s.find([max(0, pos[0] - 60), max(0, pos[1] - 20), 120, 40], ".+")
        if hit and any(a in hit[0] for a in avoid):
            return "failed", f"要点的位置上写着「{hit[0]}」，为了不误花资源没有点", {}
        s.click(*pos, wait=float(step.get("wait", 2.5)))
        dump(word)
    time.sleep(1.0)
    for i, (x, y) in enumerate(conf.get("probe_icons") or []):  # 校准：点顶栏图标看物品说明（名字），截图后按返回关掉
        if stop():
            return "stopped", "已手动停止", {}
        s.click(x, y, wait=1.8)
        dump(f"icon{i}")
        log(f"图标{i}：" + " | ".join(t for t, _ in s.ocr(full, fresh=False))[:600])
        s.back(wait=1.5)
        dump(f"icon{i}_back")
    if conf.get("calibrate"):  # 校准：整屏识字记下来（看顶栏的数字和图标在哪），配合 dump 的整张截图
        log("整屏识别：" + " | ".join(f"{t}@{b[0]},{b[1]},{b[2]},{b[3]}" for t, b in s.ocr(full))[:1500])
    texts = s.ocr(conf.get("bar_roi") or full)
    if conf.get("debug"):
        log("顶栏识别：" + " | ".join(f"{t}@{b[0]},{b[1]}" for t, b in texts))
    nums = sorted(((box[0], _num(t), t) for t, box in texts if _num(t) is not None), key=lambda x: x[0])
    keys = conf.get("keys") or []
    if keys and all(isinstance(k, dict) for k in keys):  # 每个数字单独一块区域（图标会被认成字，比如「1O」）
        vals, miss = {}, []
        for k in keys:
            got = [(b[0], _num(re.sub(r"[OoＯ]", "0", t)), t) for t, b in s.ocr(k["roi"], fresh=False)]
            got = [x for x in got if x[1] is not None]
            if got:
                vals[k["key"]] = sorted(got)[-1][1]
            elif not k.get("optional"):  # optional：只在某些卡池显示的格子（绘旅人限定池的「限时老荷兰」）
                miss.append(k["key"])
        for _ in range(int(conf.get("back", 1))):
            s.back()
        if miss:
            return "failed", f"没读到：{'、'.join(miss)}" + (f"（读到 {vals}）" if vals else ""), vals
        return "succeeded", "读到 " + "、".join(f"{k} {v}" for k, v in vals.items()), vals
    if out_dir:  # 留一张顶栏截图，核对用
        try:
            x, y, bw, bh = conf.get("bar_roi") or full
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            Path(out_dir, f"gacha_bar_{game}.png").write_bytes(png_bytes(s.img[y:y + bh, x:x + bw]))
        except Exception:
            pass
    for _ in range(int(conf.get("back", 1))):
        s.back()
    if len(nums) < len(keys):
        return "failed", f"顶栏只读到 {len(nums)} 个数字（{'、'.join(t for _, _, t in nums) or '没有'}），要 {len(keys)} 个", {}
    vals = {k: n for k, (_, n, _) in zip(keys, nums)}
    return "succeeded", "读到 " + "、".join(f"{k} {v}" for k, v in vals.items()), vals
