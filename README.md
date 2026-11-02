# GameButler · 游戏日常管家

把几个游戏的日常脚本（MAA 系列、BetterGI、三月七小助手…）放在一起管：什么时候跑、跑了什么、哪里没做成、活动日历、抽卡资源。
本地运行（127.0.0.1:8765 的网页界面 + 托盘启动器），不登录任何游戏或社区账号。

## 能做什么

- **日程与调度**：任务预设 + 定时 / 闲时；中止队列、跳过、原地暂停（BetterGI）；卡死处理、失败重试；叫醒电脑。
- **挂载脚本工具**：MaaFramework 系的 MAA（模拟器游戏，管家自己的执行器 `runner/maa_runner.py`）、BetterGI 一条龙、三月七小助手等命令行工具。
- **运行记录与报告**：每项的结果、失败截图、留证截图（模拟器游戏按关键节点；电脑游戏截游戏窗口）、微信推送（Server酱）。
- **活动日历**：官方渠道为主（官网、B 站官方号、B 站 wiki、TapTap 官方号、米哈游公告接口），游戏内公告只在站外都读不到且设置允许时才读；分类、关注 / 屏蔽、角色追踪、题图轮播。
- **抽卡资源**：跑日常时顺带读卡池界面顶栏，记折合抽数，画增长曲线，估算到下一个 UP 卡池结束时能攒多少（仅供参考）。

## 目录

| 路径 | 作用 |
| --- | --- |
| `gb.py` | 命令行入口（`web` / `run` / `stop` / `news fetch` …） |
| `butler/` | 管家后台：调度、适配器、活动日历（`news/`）、读数、推送、网页接口（`api/`） |
| `runner/` | 执行器：MaaFramework 跑任务、读游戏内公告、读抽卡资源 |
| `static/` | 网页界面 |
| `config/presets/` | 常见脚本调好的设置（挂载时套用） |
| `config/butler.example.toml` | 这台电脑的设置示例（复制成 `config/butler.toml`） |
| `overlays/` | 管家给各 MAA 补的识别模板（不改 MAA 自己的文件） |
| `launcher/` | 启动器 GameButler.exe 的源码（C# + WebView2），`build.sh` 编译 |
| `tools/` | 备用小工具 |
| `docs/给脚本作者.md` | 给脚本作者：预设格式、成败判定、`[GB_*]` 信号 |

不在仓库里：`runtime/`（自带 Python 3.12 嵌入版 + maafw 5.14.3 + tzdata）、`data/`（你的数据）、`config/butler.toml`、编译好的 `GameButler.exe`。

## 运行

1. 准备 `runtime/python/`（Python 3.12，装好 `maafw==5.14.3`、`numpy`、`tzdata`），或用发布包里带的。
2. 复制 `config/butler.example.toml` 为 `config/butler.toml`。
3. 双击 `GameButler.exe`（需要管理员权限），或命令行 `runtime\python\python.exe gb.py web`。

详细说明见 `使用说明.txt`。

## 许可证与第三方代码

本项目用 MIT 许可证（见 `LICENSE`）。米游社扫码登录和每日签到（`butler/mys.py`）移植自
[Snap Hutao Remastered](https://github.com/SnapHutaoRemasteringProject/Snap.Hutao.Remastered)（MIT），
崩铁、未定事件簿的签到参数参照 [MihoyoBBSTools](https://github.com/Womsxd/MihoyoBBSTools)（MIT），
界面上画二维码用的是 [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator)（MIT）。
完整声明见 `docs/THIRD_PARTY_NOTICES.md`。
