"""活动日历的来源：每种来源一个文件，这里登记类型和默认来源。

type：
  mihoyo_ann  米哈游游戏内公告（getAnnList + getAnnContent）：有题图、开始和结束时间
  mys_news    米游社官方资讯列表：更新公告正文里拆活动
  html_list   官网新闻列表页：找出新闻链接，再进文章页读标题、题图和正文里的时间
  papegames   叠纸官网（Next.js）
  jx3_api     剑网3 官网新闻接口
  ingame      游戏内公告栏（「📰读游戏内公告」截图识别的结果）
  bili_dyn    B 站官方号动态（匿名读，不用登录；宣传图是原图）
  wiki        B 站 wiki 上玩家整理的官方消息（代号鸢 FB搬运、恋与深空活动表）
  taptap      TapTap 官方号帖子

每个读取器：read(src, data_dir, miss) → 条目列表。整个来源读不到就抛错（来源状态记失败）；
个别文章 / 正文 / 日期没读全，记进 miss（来源状态里显示「几条没读全、为什么」），不当作没发生。
新加一种来源：在这个文件夹里加一个文件，再在下面登记。
"""
from . import bili_dyn, html_list, taptap, wiki, ingame, jx3_api, mihoyo_ann, mys_news, papegames

READERS = {"mihoyo_ann": mihoyo_ann.read, "mys_news": mys_news.read, "html_list": html_list.read,
           "papegames": papegames.read, "jx3_api": jx3_api.read, "ingame": ingame.read,
           "bili_dyn": bili_dyn.read, "wiki": wiki.read, "taptap": taptap.read}

DEFAULT_SOURCES = [
    {"id": "genshin_ann", "game": "genshin", "type": "mihoyo_ann",
     "host": "hk4e-ann-api.mihoyo.com", "biz": "hk4e_cn", "gamecode": "hk4e", "region": "cn_gf01"},
    {"id": "starrail_ann", "game": "starrail", "type": "mihoyo_ann",
     "host": "hkrpg-ann-api.mihoyo.com", "biz": "hkrpg_cn", "gamecode": "hkrpg", "region": "prod_gf_cn"},
    {"id": "tot_mys", "game": "tot", "type": "mys_news", "gids": 4, "slug": "wd"},
    {"id": "lysk_web", "game": "lysk", "type": "papegames", "base": "https://deepspace.papegames.com"},
    {"id": "sh_web", "game": "sh", "type": "html_list",
     "urls": ["https://hlr.163.com/news/", "https://hlr.163.com/index.html"],
     "match": r"/news/(?:official|update)/\d{8}/", "multi": True},
    {"id": "sh_bili", "game": "sh", "type": "bili_dyn", "mid": "441833336", "img_rank": 3.5},  # 时绘官方 B 站号（11-02）
    {"id": "sh_ingame", "game": "sh", "type": "ingame"},   # 游戏内「学院公告」（闲时批次「读公告 · 读资源」里的「📰读游戏内公告」读的）
    # 站外来源（11-02）：尽量不进游戏读；游戏内的只在站外都读不到、且设置里允许时才读
    {"id": "yuan_fb", "game": "yuan", "type": "wiki", "mode": "fb_index", "site": "yuan", "page": "FB搬运", "prefix": "FB-"},
    {"id": "lysk_wiki", "game": "lysk", "type": "wiki", "mode": "act_table", "site": "lysk", "page": "活动"},
    {"id": "lysk_tap", "game": "lysk", "type": "taptap", "app": "201633"},
    {"id": "yuan_ingame", "game": "yuan", "type": "ingame"},  # 游戏内：主界面「公告」+「活动」页（港服官网没有公告列表）
    {"id": "lysk_ingame", "game": "lysk", "type": "ingame"},  # 游戏内公告（登录页右侧图标：活动公告 + 系统公告）
    # 代号鸢港服：发行商 qookkagames 的官网没有公告列表（10-22 实测），以后改为读游戏内公告栏（模拟器截图识别）
    {"id": "jx3_web", "game": "jx3", "type": "jx3_api"},
]
