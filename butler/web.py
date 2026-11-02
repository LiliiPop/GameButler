"""本地网页界面 + 接口。只监听 127.0.0.1，不对外开放。这个文件只管 HTTP：收请求、按路由表找处理函数、回 JSON、发静态文件。
各接口写在 butler/api/ 下（按领域分文件），每个功能一个接口，事情交给对应的模块做。

接口一览（JSON；{gid} = 游戏 id，{day} = YYYY-MM-DD 或 today）：

总览 / 运行
  GET    /api/state                         各游戏概况（主页卡片）
  GET    /api/running                       现在在不在跑、跑到哪个任务；是否让出电脑；能不能「继续」
  POST   /api/stop                          停止：正在跑的停下，排着的「立即」批次也不开始，一起记进「继续」
  POST   /api/continue  ·  DELETE /api/continue   继续上次停下的（排进今天的队列）/ 不继续了
  POST   /api/running/pause|resume          暂停 / 继续当前任务（只有 BetterGI 支持）
  POST   /api/yield  ·  POST /api/resume    让出电脑 / 恢复调度
日程与调度
  GET    /api/schedule/today                今天的条目（正在跑 / 接下来 / 跑过的）、各游戏的任务预设和定时、闲时、睡眠提醒
  PUT    /api/schedule/today/order          今天拖动后的顺序（只改今天）
  POST   /api/schedule/today/items          加一条一次性的（「开始」也是它：不写 when = 现在）
  POST   /api/schedule/today/items/{id}/skip|unskip|run-now|delete|save-as-routine
  POST   /api/schedule/rules  ·  PUT|DELETE /api/schedule/rules/{id}  ·  PUT /api/schedule/rules-order   任务预设上的定时
  GET    /api/idle                          什么算闲时：条件组和现在差什么（改在 PUT /api/settings/scheduler 的 idle_groups）
  GET    /api/scheduler                     调度现在的判断、等你回答的提醒、调度记录
  POST   /api/scheduler/on|off  ·  POST /api/scheduler/answer {choice: now|later|skip}  ·  POST /api/scheduler/wake（叫醒电脑后）
游戏
  GET    /api/games                         全部游戏记录（挂着的和取消挂载的）
  POST   /api/games/detect {path}           识别一个文件夹 / 程序
  POST   /api/games                         挂载（以前挂过的恢复原来那条）
  PUT    /api/games/{gid}                   改设置（名字、刷新时间、路径、模拟器、命令、时段、分辨率开关）
  POST   /api/games/{gid}/follow {on}       取消挂载 / 重新挂载
  DELETE /api/games/{gid}                   彻底删除
  POST   /api/games/{gid}/check|scan        检查工具 / 在常见位置找工具
  GET    /api/schema/{gid}                  任务与选项定义（含开关状态）
  POST   /api/tasks/{gid}/enable|disable    任务开关
  GET|PUT /api/routines/{gid}（带定时；renamed 改名）  ·  GET /api/today/{gid}（今天的进度）
  GET    /api/runs/{gid}?day=               运行记录
  GET    /api/report/{day}                  每日汇总（含推送正文）
读数 / 抽卡记录
  GET|POST /api/readings/{gid}  ·  PUT /api/readings/{gid}/defs
  POST   /api/gacha/{gid}/import  ·  GET /api/gacha/template
活动
  GET    /api/news  ·  GET /api/news/item/{id}  ·  POST /api/news/act  ·  POST /api/news/refresh
设置
  GET    /api/settings                      全部设置 + 开机自动启动、是否管理员
  PUT    /api/settings/{section}            scheduler（不含开关）/ push / appearance / news / evidence / emulator
  GET|PUT /api/games/{gid}/advanced          游戏页「高级」：启动任务、顺序、成败判定、超时（butler/advanced.py）
  GET    /api/themes  ·  PUT|DELETE /api/themes/{id}   界面主题：自带的列表、自建主题的保存 / 删除
  POST   /api/settings/autostart {on}  ·  POST /api/settings/open {what}  ·  POST /api/push/test
  GET    /api/evidence  ·  POST /api/evidence/clean
  GET    /api/emulators  ·  POST /api/browse {title}
  GET    /api/pcres  ·  POST /api/pcres/{gid}/restore
  POST   /api/bettergi/{gid}/sync  ·  PUT /api/bettergi/{gid}/group  ·  POST /api/import/{gid}
  POST   /api/open/{gid}                    打开工具自己的界面
  GET    /api/catalog  ·  GET /api/catalog/job/{id}  ·  POST /api/catalog/download
  GET|POST /api/ui-notes  ·  POST /api/ui-notes/{id}  ·  POST /api/ui-notes/{id}/delete
程序
  GET    /api/app  ·  POST /api/app/restart  ·  POST /api/app/quit
文件
  GET    /shots/{gid}/{路径}  ·  /evidence/{游戏日}/{gid}/{文件}  ·  /news-img/{文件}  ·  /static/{文件}
"""

from __future__ import annotations

import json
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import autostart
from . import evidence as EV
from . import games as G
from . import news
from . import settings as S
from .api import APP, ROOT, Api, NotFound
from .api import load as load_routes
from .launch import spawn_background
from .runstate import is_admin, now_bj

STATIC = ROOT / "static"
PORT = 8765


def make_handler(cfg: dict, sched):
    api = Api(cfg, sched)
    R = load_routes()
    data_dir = api.data_dir
    game = api.game

    # ------------------------------------------------ 文件
    def file_response(parts: list[str]):
        if parts[0] == "static":
            base, path = STATIC.resolve(), (STATIC / Path(*parts[1:])).resolve()
        elif parts[0] == "shots" and len(parts) >= 3:
            game(parts[1])
            base = (data_dir / "maafw" / parts[1]).resolve()
            path = (base / Path(*parts[2:])).resolve()
        elif parts[0] == "evidence" and len(parts) == 4:
            base = EV.root(cfg).resolve()
            path = (base / parts[1] / parts[2] / parts[3]).resolve()
        elif parts[0] == "news-img" and len(parts) == 2:
            p = news.img_path(cfg, parts[1])
            if not p:
                raise NotFound(parts[1])
            base, path = p.parent.resolve(), p.resolve()
        else:
            raise NotFound("/".join(parts))
        if base not in path.parents or not path.is_file():
            raise NotFound("/".join(parts))
        types = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
                 ".json": "application/json; charset=utf-8", ".html": "text/html; charset=utf-8", ".woff2": "font/woff2"}
        if path.suffix.lower() not in types:
            raise NotFound(path.name)
        return path.read_bytes(), types[path.suffix.lower()]

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method: str):
            u = urlparse(self.path)
            path = unquote(u.path)
            try:
                if method == "GET" and not path.startswith("/api/"):
                    parts = [x for x in path.strip("/").split("/") if x]
                    if not parts:
                        return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                    data, ctype = file_response(parts)
                    return self._send(200, data, ctype)
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                for meth, pat, fn in R:
                    mt = pat.match(path)
                    if meth == method and mt:
                        return self._send(200, fn(api, mt, parse_qs(u.query), body))
                raise NotFound(path)
            except NotFound as e:
                return self._send(404, {"error": f"没有：{e}"})
            except (ValueError, KeyError) as e:  # 请求不对（界面上显示这句话）
                return self._send(400, {"error": str(e).strip("'\"")})
            except Exception as e:
                import traceback
                print(f"[{now_bj()}] {method} {path} 出错：\n{traceback.format_exc()}", flush=True)
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def do_DELETE(self):
            self._handle("DELETE")

    return H


def serve(cfg: dict, open_browser: bool = True, port: int = PORT):
    from .scheduler import Scheduler
    url = f"http://127.0.0.1:{port}"
    sched = Scheduler(cfg)
    restarted = "--restarted" in sys.argv
    for i in range(240 if restarted else 1):  # 重启时：最多等 2 分钟让旧的后台放开端口
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg, sched))
            break
        except OSError:
            if i == (239 if restarted else 0):
                print(f"管家已经在运行：{url}")  # 端口被占用：管家已经开着（例如开机自动启动的那个），直接打开界面
                if open_browser:
                    webbrowser.open(url)
                return
            time.sleep(0.5)
    srv.daemon_threads = True
    APP["server"], APP["started"] = srv, now_bj()
    try:
        from . import selfupdate
        selfupdate.cleanup_old()
    except Exception:
        pass
    print(f"[{now_bj()}] 管家已启动：{url}（管理员：{'是' if is_admin() else '否'}）", flush=True)
    from .housekeeping import start_daily
    start_daily(cfg["machine"]["data_dir"])

    def _later(sec: float, fn):  # 后台线程（daemon）：退出时不用等它到点（11-02：以前开机 2 分钟内重启，旧进程要等定时器到点才退出）
        t = threading.Timer(sec, fn)
        t.daemon = True
        t.start()

    def loop(name: str, every: float, fn):
        """后台的定时小事：出错记进调度记录（界面「调度记录」里看得到），下一轮照常。"""
        def run():
            while True:
                try:
                    fn()
                except Exception as e:
                    sched.log(f"{name}出错：{type(e).__name__}: {e}")
                time.sleep(every)
        threading.Thread(target=run, daemon=True).start()

    def updates_tick():  # 脚本工具的新版本：开机 1 分钟后查一次，之后每 12 小时（butler/updates.py）
        from . import updates
        updates.check(cfg)
    _later(60, lambda: loop("检查工具更新", 12 * 3600, updates_tick))

    def selfupdate_tick():  # 管家自己的新版本（11-02）：每 6 小时问一次 GitHub；开了自动更新就下载，没有任务在跑时换上（每 10 分钟看一次）
        from . import selfupdate
        selfupdate.tick(cfg, port)
    _later(120, lambda: loop("检查管家更新", 600, selfupdate_tick))

    news_state = {"last": time.time() - S.get(cfg, "news")["interval_hours"] * 3600 + 20}  # 启动 20 秒后读第一次

    def news_tick():  # 活动日历：每隔几个小时在后台进程里读一次（改 news.py 不用重启管家）
        flag = Path(cfg["machine"]["data_dir"]) / "news" / "refresh.flag"  # 读完游戏内公告会放这个文件：马上再整理一次
        due = time.time() - news_state["last"] >= S.get(cfg, "news")["interval_hours"] * 3600
        if flag.exists():
            flag.unlink()
            due = True
        if due and spawn_background("news", ["news", "fetch", "--from-butler"], cfg["machine"]["data_dir"]):
            news_state["last"] = time.time()
    loop("读活动公告", 30, news_tick)

    def tool_tick():  # 各工具自己的小事（例如 BetterGI 开着时没写进去的计划，等它关掉后补写）
        for gid in list(cfg["games"]):
            msg = G.adapter(cfg, gid).tick()
            if msg:
                sched.log(msg, gid)
    loop("工具定时检查", 60, tool_tick)
    sched.run_in_background()
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    srv.server_close()  # 马上放开端口：重启 / 更新时新的后台在等它（11-02）
    print(f"[{now_bj()}] 管家已退出", flush=True)
