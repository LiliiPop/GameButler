#!/bin/sh
# 编译启动器 GameButler.exe（在 Linux 上用 Mono：apt-get install mono-mcs mono-devel）。
# 输出到管家根目录；WebView2 的三个 dll 留在 launcher\ 里（GameButler.exe.config 指向这里）。
set -e
cd "$(dirname "$0")"
API=/usr/lib/mono/4.8-api
RES=$(mktemp --suffix=.res)
python3 mkres.py icon.ico app.manifest "$RES"
mcs -target:winexe -platform:x64 -optimize+ -codepage:utf8 -out:../GameButler.exe \
  -win32res:"$RES" \
  -nostdlib -lib:$API -r:$API/mscorlib.dll -r:$API/System.dll -r:$API/System.Core.dll \
  -r:$API/System.Drawing.dll -r:$API/System.Windows.Forms.dll -r:$API/System.Web.Extensions.dll \
  -r:Microsoft.Web.WebView2.Core.dll -r:Microsoft.Web.WebView2.WinForms.dll \
  src/GameButler.cs
cp GameButler.exe.config ../GameButler.exe.config
echo "已生成 ../GameButler.exe"
