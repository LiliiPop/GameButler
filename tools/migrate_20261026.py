"""10-26：「跑完关模拟器」从每个游戏记录（close_emulator_after）改成一个设置（设置 → 模拟器 → 跑完关模拟器）。
有游戏写了 false、没有写 true 的 → 设成「一直开着」；否则保持默认「每次跑完关」。然后从游戏记录里去掉这一项。
用法：python tools/migrate_20261026.py <管家文件夹>"""
import json
import sys
from pathlib import Path

DATA = Path(sys.argv[1]).resolve() / "data"
vals = []
for p in sorted((DATA / "games").glob("*.json")):
    g = json.loads(p.read_text(encoding="utf-8"))
    if "close_emulator_after" in g:
        vals.append(bool(g.pop("close_emulator_after")))
        p.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {p.name}：去掉 close_emulator_after")
if vals and not any(vals):
    sp = DATA / "settings.json"
    s = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    s.setdefault("emulator", {})["close"] = "keep_open"
    sp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  跑完关模拟器：一直开着")
else:
    print("  跑完关模拟器：每次跑完关（默认）")
