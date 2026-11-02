"""打发布包（11-02）：把管家文件夹打成 _release/GameButler-v<版本>-win64.zip，顶层一个 GameButler/ 文件夹。

用法（在管家文件夹里）：runtime\\python\\python.exe tools\\make_release.py
  1. 先改 VERSION（例如 0.1.1），代码推到 GitHub；
  2. 跑这个脚本；
  3. 在 GitHub 上新建发布，标签写 v0.1.1，把生成的 zip 传上去。
  之后别人的管家（设置 → 管家更新）就能查到、自动下载换上。

不打进去：data/、_backup/、_release/、config/butler.toml、__pycache__、*.bak_*、tools 里的 .bat、ui_src*.tar 之类的本机文件。
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_TOP = {"data", "_backup", "_release", "_update", ".git"}
SKIP_RE = re.compile(r"(__pycache__|\.pyc$|\.bak_|^config/butler\.toml|^tools/.*\.bat$|^ui_src.*\.tar$|^GameButler\.old\.exe$|\.log$)")


def main():
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    out = ROOT / "_release" / f"GameButler-v{ver}-win64.zip"
    out.parent.mkdir(exist_ok=True)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(ROOT.rglob("*")):
            rel = f.relative_to(ROOT).as_posix()
            if not f.is_file() or rel.split("/")[0] in SKIP_TOP or SKIP_RE.search(rel):
                continue
            z.write(f, "GameButler/" + rel)
            n += 1
    for need in ("gb.py", "VERSION", "GameButler.exe", "runtime/python"):
        if not (ROOT / need).exists():
            print(f"注意：管家文件夹里没有 {need}，发布包里也没有", file=sys.stderr)
    print(f"{out}  {n} 个文件  {out.stat().st_size / 1048576:.1f} MB")


main()
