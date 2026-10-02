"""
活动分类映射表与分类函数

从 activity_detector.py 拆出的纯数据与分类逻辑模块，包含：
1. PROCESS_CATEGORY_MAP — 进程名到活动类别的映射表
2. WINDOW_TITLE_KEYWORD_MAP — 窗口标题关键词到活动类别的映射表
3. is_system_process() — 判断是否为系统/后台进程
4. classify_by_process_name() — 根据进程名进行活动分类
5. classify_by_window_title() — 根据窗口标题进行二次分类
6. extract_relevant_keyword() — 从窗口标题中提取有意义的关键词
"""
from enum import Enum
from typing import Dict, Tuple


class UserActivityCategory(str, Enum):
    """用户活动类别枚举"""
    IDLE = "idle"                    # 空闲/桌面无活跃操作
    WORKING = "working"              # 工作（IDE、文档、浏览器工作相关）
    STUDYING = "studying"            # 学习（教育类软件、阅读工具）
    GAMING = "gaming"                # 游戏
    ENTERTAINMENT = "entertainment"  # 娱乐（视频、音乐、社交）
    COMMUNICATION = "communication"  # 即时通讯（QQ、微信等）
    BROWSING = "browsing"            # 一般浏览
    UNKNOWN = "unknown"              # 无法识别

# 进程名 -> 活动类别的映射表（跨平台通用）
# key: 进程名（小写），value: (category, display_name)
PROCESS_CATEGORY_MAP: Dict[str, Tuple[UserActivityCategory, str]] = {
    # ===== 开发/工作类 =====
    "code": (UserActivityCategory.WORKING, "VS Code"),
    "code - insiders": (UserActivityCategory.WORKING, "VS Code Insiders"),
    "code64": (UserActivityCategory.WORKING, "VS Code"),
    "clion": (UserActivityCategory.WORKING, "CLion"),
    "idea": (UserActivityCategory.WORKING, "IntelliJ IDEA"),
    "intellij idea": (UserActivityCategory.WORKING, "IntelliJ IDEA"),
    "pycharm": (UserActivityCategory.WORKING, "PyCharm"),
    "webstorm": (UserActivityCategory.WORKING, "WebStorm"),
    "rider": (UserActivityCategory.WORKING, "Rider"),
    "goland": (UserActivityCategory.WORKING, "GoLand"),
    "datagrip": (UserActivityCategory.WORKING, "DataGrip"),
    "phpstorm": (UserActivityCategory.WORKING, "PHPStorm"),
    "rubymine": (UserActivityCategory.WORKING, "RubyMine"),
    "appcode": (UserActivityCategory.WORKING, "AppCode"),
    "android studio": (UserActivityCategory.WORKING, "Android Studio"),
    "studio64": (UserActivityCategory.WORKING, "Android Studio"),
    "xcode": (UserActivityCategory.WORKING, "Xcode"),
    "sublime_text": (UserActivityCategory.WORKING, "Sublime Text"),
    "subl": (UserActivityCategory.WORKING, "Sublime Text"),
    "notepad++": (UserActivityCategory.WORKING, "Notepad++"),
    "notepadpp": (UserActivityCategory.WORKING, "Notepad++"),
    "vim": (UserActivityCategory.WORKING, "Vim"),
    "nvim": (UserActivityCategory.WORKING, "Neovim"),
    "emacs": (UserActivityCategory.WORKING, "Emacs"),
    "nano": (UserActivityCategory.WORKING, "Nano"),
    "typora": (UserActivityCategory.WORKING, "Typora"),
    "obsidian": (UserActivityCategory.WORKING, "Obsidian"),
    "notion": (UserActivityCategory.WORKING, "Notion"),
    "winword": (UserActivityCategory.WORKING, "Word"),
    "excel": (UserActivityCategory.WORKING, "Excel"),
    "powerpnt": (UserActivityCategory.WORKING, "PowerPoint"),
    "mspaint": (UserActivityCategory.WORKING, "画图"),
    "visio": (UserActivityCategory.WORKING, "Visio"),
    "outlook": (UserActivityCategory.WORKING, "Outlook"),
    "thunderbird": (UserActivityCategory.WORKING, "Thunderbird"),
    "foxitpdf": (UserActivityCategory.WORKING, "Foxit PDF"),
    "acrord32": (UserActivityCategory.WORKING, "Adobe Reader"),
    "sumatrapdf": (UserActivityCategory.WORKING, "SumatraPDF"),
    "gitkraken": (UserActivityCategory.WORKING, "GitKraken"),
    "sourcetree": (UserActivityCategory.WORKING, "SourceTree"),
    "tortoisegit": (UserActivityCategory.WORKING, "TortoiseGit"),
    "tortoisesvn": (UserActivityCategory.WORKING, "TortoiseSVN"),
    "fiddler": (UserActivityCategory.WORKING, "Fiddler"),
    "postman": (UserActivityCategory.WORKING, "Postman"),
    "insomnia": (UserActivityCategory.WORKING, "Insomnia"),
    "docker desktop": (UserActivityCategory.WORKING, "Docker Desktop"),
    "wsl": (UserActivityCategory.WORKING, "WSL"),
    "wsl_host": (UserActivityCategory.WORKING, "WSL"),
    "windowsterminal": (UserActivityCategory.WORKING, "Windows Terminal"),
    "wt": (UserActivityCategory.WORKING, "Windows Terminal"),
    "powershell_ise": (UserActivityCategory.WORKING, "PowerShell ISE"),
    "cmd": (UserActivityCategory.WORKING, "命令提示符"),
    "conhost": (UserActivityCategory.IDLE, "控制台主机"),  # 控制台主机不算活跃操作
    "explorer": (UserActivityCategory.IDLE, "资源管理器"),  # 文件管理器不算活跃操作
    "taskmgr": (UserActivityCategory.WORKING, "任务管理器"),

    # ===== 学习类 =====
    "anki": (UserActivityCategory.STUDYING, "Anki"),
    "ankiconnectserver": (UserActivityCategory.STUDYING, "AnkiConnect"),
    "xmind": (UserActivityCategory.STUDYING, "XMind"),
    "mindmanager": (UserActivityCategory.STUDYING, "MindManager"),
    "freemind": (UserActivityCategory.STUDYING, "FreeMind"),
    "zotero": (UserActivityCategory.STUDYING, "Zotero"),
    "endnote": (UserActivityCategory.STUDYING, "EndNote"),
    "citavi": (UserActivityCategory.STUDYING, "Citavi"),
    "matlab": (UserActivityCategory.STUDYING, "MATLAB"),
    "mathematica": (UserActivityCategory.STUDYING, "Mathematica"),
    "maple": (UserActivityCategory.STUDYING, "Maple"),
    "spss": (UserActivityCategory.STUDYING, "SPSS"),
    "stata": (UserActivityCategory.STUDYING, "Stata"),
    "origin": (UserActivityCategory.STUDYING, "Origin"),
    "geogebra": (UserActivityCategory.STUDYING, "GeoGebra"),
    "desmos": (UserActivityCategory.STUDYING, "Desmos"),
    "calibre": (UserActivityCategory.STUDYING, "Calibre"),
    "kindle": (UserActivityCategory.STUDYING, "Kindle"),
    "adobe digital editions": (UserActivityCategory.STUDYING, "ADE电子书"),
    "onedrive": (UserActivityCategory.IDLE, "OneDrive"),  # 同步服务不算活跃操作

    # ===== 游戏类 =====
    "steam": (UserActivityCategory.GAMING, "Steam"),
    "steamwebhelper": (UserActivityCategory.GAMING, "Steam"),
    "gamescope": (UserActivityCategory.GAMING, "Gamescope"),
    "epic games launcher": (UserActivityCategory.GAMING, "Epic Games"),
    "epicgameslauncher": (UserActivityCategory.GAMING, "Epic Games"),
    "ubisoft connect": (UserActivityCategory.GAMING, "Ubisoft Connect"),
    "upc": (UserActivityCategory.GAMING, "Ubisoft Connect"),
    "ea app": (UserActivityCategory.GAMING, "EA App"),
    "ea desktop": (UserActivityCategory.GAMING, "EA Desktop"),
    "battle.net": (UserActivityCategory.GAMING, "Battle.net"),
    "gamingonlineservices": (UserActivityCategory.GAMING, "Battle.net"),
    "minecraft": (UserActivityCategory.GAMING, "Minecraft"),
    "javaw": (UserActivityCategory.GAMING, "Java(Minecraft)"),
    "roblox": (UserActivityCategory.GAMING, "Roblox"),
    "robloxplayerbeta": (UserActivityCategory.GAMING, "Roblox Player"),
    "league of legends": (UserActivityCategory.GAMING, "英雄联盟"),
    "leagueclient": (UserActivityCategory.GAMING, "英雄联盟客户端"),
    "leagueclientux": (UserActivityCategory.GAMING, "英雄联盟客户端"),
    "valorant": (UserActivityCategory.GAMING, "Valorant"),
    "csgo": (UserActivityCategory.GAMING, "CSGO"),
    "cs2": (UserActivityCategory.GAMING, "CS2"),
    "dota2": (UserActivityCategory.GAMING, "DOTA2"),
    "apex legends": (UserActivityCategory.GAMING, "Apex Legends"),
    "overwatch": (UserActivityCategory.GAMING, "守望先锋"),
    "genshin impact": (UserActivityCategory.GAMING, "原神"),
    "yuanshen": (UserActivityCategory.GAMING, "原神"),
    "honkai star rail": (UserActivityCategory.GAMING, "崩坏：星穹铁道"),
    "hsr": (UserActivityCategory.GAMING, "星穹铁道"),
    "honkai impact 3rd": (UserActivityCategory.GAMING, "崩坏3"),
    "wuwa": (UserActivityCategory.GAMING, "鸣潮"),
    "zzz": (UserActivityCategory.GAMING, "绝区零"),
    "zenlesszonezero": (UserActivityCategory.GAMING, "绝区零"),
    "nfs": (UserActivityCategory.GAMING, "极品飞车"),
    "fifa": (UserActivityCategory.GAMING, "FIFA"),
    "fc24": (UserActivityCategory.GAMING, "FC24"),
    "nba2k": (UserActivityCategory.GAMING, "NBA2K"),
    "simcity": (UserActivityCategory.GAMING, "模拟城市"),
    "civilization": (UserActivityCategory.GAMING, "文明系列"),
    "factorio": (UserActivityCategory.GAMING, "异星工厂"),
    "terraria": (UserActivityCategory.GAMING, "泰拉瑞亚"),
    "starvalley": (UserActivityCategory.GAMING, "星露谷"),
    "stardew valley": (UserActivityCategory.GAMING, "星露谷"),
    "bethesda.net launcher": (UserActivityCategory.GAMING, "Bethesda"),
    "gog galaxy": (UserActivityCategory.GAMING, "GOG Galaxy"),
    "unity": (UserActivityCategory.GAMING, "Unity编辑器"),
    "unreal editor": (UserActivityCategory.GAMING, "Unreal Editor"),
    "ue4editor": (UserActivityCategory.GAMING, "Unreal Editor 4"),
    "ue5editor": (UserActivityCategory.GAMING, "Unreal Editor 5"),
    "godot": (UserActivityCategory.GAMING, "Godot引擎"),
    "rpgmaker": (UserActivityCategory.GAMING, "RPG Maker"),
    "game maker": (UserActivityCategory.GAMING, "Game Maker"),
    "construct": (UserActivityCategory.GAMING, "Construct"),
    "blender": (UserActivityCategory.WORKING, "Blender"),  # Blender 也常用于3D建模工作
    "maya": (UserActivityCategory.WORKING, "Maya"),
    "3ds max": (UserActivityCategory.WORKING, "3ds Max"),
    "cinema 4d": (UserActivityCategory.WORKING, "Cinema 4D"),
    "zbrush": (UserActivityCategory.WORKING, "ZBrush"),
    "substance painter": (UserActivityCategory.WORKING, "Substance Painter"),
    "substance designer": (UserActivityCategory.WORKING, "Substance Designer"),

    # ===== 娱乐类 =====
    "spotify": (UserActivityCategory.ENTERTAINMENT, "Spotify"),
    "itunes": (UserActivityCategory.ENTERTAINMENT, "iTunes"),
    "foobar2000": (UserActivityCategory.ENTERTAINMENT, "foobar2000"),
    "potplayer": (UserActivityCategory.ENTERTAINMENT, "PotPlayer"),
    "potplayer64": (UserActivityCategory.ENTERTAINMENT, "PotPlayer"),
    "vlc": (UserActivityCategory.ENTERTAINMENT, "VLC"),
    "mpv": (UserActivityCategory.ENTERTAINMENT, "mpv"),
    "mpv.net": (UserActivityCategory.ENTERTAINMENT, "mpv.NET"),
    "media player classic": (UserActivityCategory.ENTERTAINMENT, "MPC"),
    "mpc-hc": (UserActivityCategory.ENTERTAINMENT, "MPC-HC"),
    "mpc-be": (UserActivityCategory.ENTERTAINMENT, "MPC-BE"),
    "mpc-qt": (UserActivityCategory.ENTERTAINMENT, "MPC-QT"),
    "windows media player": (UserActivityCategory.ENTERTAINMENT, "WMP"),
    "wmplayer": (UserActivityCategory.ENTERTAINMENT, "WMP"),
    "iina": (UserActivityCategory.ENTERTAINMENT, "IINA"),
    "plex": (UserActivityCategory.ENTERTAINMENT, "Plex"),
    "jellyfin": (UserActivityCategory.ENTERTAINMENT, "Jellyfin"),
    "emby": (UserActivityCategory.ENTERTAINMENT, "Emby"),
    "kodi": (UserActivityCategory.ENTERTAINMENT, "Kodi"),
    "netflix": (UserActivityCategory.ENTERTAINMENT, "Netflix"),
    "disney+": (UserActivityCategory.ENTERTAINMENT, "Disney+"),
    "hulu": (UserActivityCategory.ENTERTAINMENT, "Hulu"),
    "amazon prime video": (UserActivityCategory.ENTERTAINMENT, "Prime Video"),
    "youtube music": (UserActivityCategory.ENTERTAINMENT, "YouTube Music"),
    "qqmusic": (UserActivityCategory.ENTERTAINMENT, "QQ音乐"),
    "neteasecloudmusic": (UserActivityCategory.ENTERTAINMENT, "网易云音乐"),
    "kuwo": (UserActivityCategory.ENTERTAINMENT, "酷我音乐"),
    "kugou": (UserActivityCategory.ENTERTAINMENT, "酷狗音乐"),
    "aimp": (UserActivityCategory.ENTERTAINMENT, "AIMP"),
    "aimp3": (UserActivityCategory.ENTERTAINMENT, "AIMP3"),
    "audacious": (UserActivityCategory.ENTERTAINMENT, "Audacious"),
    "clementine": (UserActivityCategory.ENTERTAINMENT, "Clementine"),
    "deadbeef": (UserActivityCategory.ENTERTAINMENT, "DeaDBeeF"),

    # ===== 即时通讯类 =====
    "qq": (UserActivityCategory.COMMUNICATION, "QQ"),
    "qq.exe": (UserActivityCategory.COMMUNICATION, "QQ"),
    "tim": (UserActivityCategory.COMMUNICATION, "TIM"),
    "wechat": (UserActivityCategory.COMMUNICATION, "微信"),
    "weixin": (UserActivityCategory.COMMUNICATION, "微信"),
    "dingtalk": (UserActivityCategory.COMMUNICATION, "钉钉"),
    "feishu": (UserActivityCategory.COMMUNICATION, "飞书"),
    "lark": (UserActivityCategory.COMMUNICATION, "飞书(Lark)"),
    "slack": (UserActivityCategory.COMMUNICATION, "Slack"),
    "discord": (UserActivityCategory.COMMUNICATION, "Discord"),
    "teams": (UserActivityCategory.COMMUNICATION, "Microsoft Teams"),
    "telegram": (UserActivityCategory.COMMUNICATION, "Telegram"),
    "telegram desktop": (UserActivityCategory.COMMUNICATION, "Telegram"),
    "whatsapp": (UserActivityCategory.COMMUNICATION, "WhatsApp"),
    "skype": (UserActivityCategory.COMMUNICATION, "Skype"),
    "zoom": (UserActivityCategory.COMMUNICATION, "Zoom"),
    "zoom meetings": (UserActivityCategory.COMMUNICATION, "Zoom Meetings"),
    "腾讯会议": (UserActivityCategory.COMMUNICATION, "腾讯会议"),
    "wemeetapp": (UserActivityCategory.COMMUNICATION, "腾讯会议"),
    "tencent meeting": (UserActivityCategory.COMMUNICATION, "腾讯会议"),
    "irc": (UserActivityCategory.COMMUNICATION, "IRC客户端"),
    "hexchat": (UserActivityCategory.COMMUNICATION, "HexChat"),
    "irssi": (UserActivityCategory.COMMUNICATION, "Irssi"),
    "weechat": (UserActivityCategory.COMMUNICATION, "WeeChat"),
    "element": (UserActivityCategory.COMMUNICATION, "Element(Matrix)"),
    "signal": (UserActivityCategory.COMMUNICATION, "Signal"),
    "line": (UserActivityCategory.COMMUNICATION, "LINE"),
    "kakao": (UserActivityCategory.COMMUNICATION, "KakaoTalk"),
    "threema": (UserActivityCategory.COMMUNICATION, "Threema"),
    "tox": (UserActivityCategory.COMMUNICATION, "Tox"),
    "jami": (UserActivityCategory.COMMUNICATION, "Jami"),
    "wire": (UserActivityCategory.COMMUNICATION, "Wire"),
    "viber": (UserActivityCategory.COMMUNICATION, "Viber"),
    "icq": (UserActivityCategory.COMMUNICATION, "ICQ"),
    "jabber": (UserActivityCategory.COMMUNICATION, "Jabber"),
    "pidgin": (UserActivityCategory.COMMUNICATION, "Pidgin"),
    "gajim": (UserActivityCategory.COMMUNICATION, "Gajim"),
    "dino": (UserActivityCategory.COMMUNICATION, "Dino"),
    "fractal": (UserActivityCategory.COMMUNICATION, "Fractal"),

    # ===== 浏览器类（需要结合窗口标题进一步判断） =====
    "chrome": (UserActivityCategory.BROWSING, "Chrome"),
    "google chrome": (UserActivityCategory.BROWSING, "Google Chrome"),
    "chromium": (UserActivityCategory.BROWSING, "Chromium"),
    "microsoft edge": (UserActivityCategory.BROWSING, "Edge"),
    "msedge": (UserActivityCategory.BROWSING, "Edge"),
    "firefox": (UserActivityCategory.BROWSING, "Firefox"),
    "brave": (UserActivityCategory.BROWSING, "Brave Browser"),
    "brave browser": (UserActivityCategory.BROWSING, "Brave Browser"),
    "opera": (UserActivityCategory.BROWSING, "Opera"),
    "operagx": (UserActivityCategory.GAMING, "Opera GX"),
    "vivaldi": (UserActivityCategory.BROWSING, "Vivaldi"),
    "arc": (UserActivityCategory.BROWSING, "Arc Browser"),
    "safari": (UserActivityCategory.BROWSING, "Safari"),
    "maxthon": (UserActivityCategory.BROWSING, "傲游浏览器"),
    "360se": (UserActivityCategory.BROWSING, "360安全浏览器"),
    "360browser": (UserActivityCategory.BROWSING, "360浏览器"),
    "liebao": (UserActivityCategory.BROWSING, "猎豹浏览器"),
    "sougou": (UserActivityCategory.BROWSING, "搜狗浏览器"),
    "centbrowser": (UserActivityCategory.BROWSING, "百分浏览器"),
    "yandex": (UserActivityCategory.BROWSING, "Yandex Browser"),
    "tor browser": (UserActivityCategory.BROWSING, "Tor Browser"),
}

# 窗口标题关键词 -> 活动类别的映射（用于浏览器等需要二次分类的应用）
# 优先级高于进程名匹配
WINDOW_TITLE_KEYWORD_MAP: Dict[str, UserActivityCategory] = {
    # ===== 工作相关关键词 =====
    "github": UserActivityCategory.WORKING,
    "gitlab": UserActivityCategory.WORKING,
    "bitbucket": UserActivityCategory.WORKING,
    "stackoverflow": UserActivityCategory.WORKING,
    "segmentfault": UserActivityCategory.WORKING,
    "juejin": UserActivityCategory.WORKING,
    "csdn": UserActivityCategory.WORKING,
    "zhihu": UserActivityCategory.BROWSING,
    "知乎": UserActivityCategory.BROWSING,
    "jira": UserActivityCategory.WORKING,
    "confluence": UserActivityCategory.WORKING,
    "notion": UserActivityCategory.WORKING,
    "飞书": UserActivityCategory.WORKING,
    "石墨": UserActivityCategory.WORKING,
    "腾讯文档": UserActivityCategory.WORKING,
    "金山文档": UserActivityCategory.WORKING,
    "google doc": UserActivityCategory.WORKING,
    "google sheet": UserActivityCategory.WORKING,
    "google slide": UserActivityCategory.WORKING,
    "office online": UserActivityCategory.WORKING,
    "figma": UserActivityCategory.WORKING,
    "sketch": UserActivityCategory.WORKING,
    "canva": UserActivityCategory.WORKING,
    "excalidraw": UserActivityCategory.WORKING,
    "draw.io": UserActivityCategory.WORKING,
    "processon": UserActivityCategory.WORKING,
    "语雀": UserActivityCategory.WORKING,
    "wolai": UserActivityCategory.WORKING,
    "aws": UserActivityCategory.WORKING,
    "azure": UserActivityCategory.WORKING,
    "cloud console": UserActivityCategory.WORKING,
    "vercel": UserActivityCategory.WORKING,
    "netlify": UserActivityCategory.WORKING,
    "heroku": UserActivityCategory.WORKING,
    "docker hub": UserActivityCategory.WORKING,
    "npm": UserActivityCategory.WORKING,
    "pypi": UserActivityCategory.WORKING,
    "crates.io": UserActivityCategory.WORKING,
    "maven": UserActivityCategory.WORKING,
    "npmjs": UserActivityCategory.WORKING,
    "leetcode": UserActivityCategory.STUDYING,
    "力扣": UserActivityCategory.STUDYING,
    "codewars": UserActivityCategory.STUDYING,
    "hackerrank": UserActivityCategory.STUDYING,
    "kaggle": UserActivityCategory.STUDYING,
    "colab": UserActivityCategory.STUDYING,
    "jupyter": UserActivityCategory.STUDYING,
    "replit": UserActivityCategory.STUDYING,
    "codepen": UserActivityCategory.WORKING,
    "codesandbox": UserActivityCategory.WORKING,
    "stackblitz": UserActivityCategory.WORKING,

    # ===== 学习相关关键词 =====
    "mooc": UserActivityCategory.STUDYING,
    "慕课": UserActivityCategory.STUDYING,
    "学堂在线": UserActivityCategory.STUDYING,
    "coursera": UserActivityCategory.STUDYING,
    "edx": UserActivityCategory.STUDYING,
    "udemy": UserActivityCategory.STUDYING,
    "bilibili学习": UserActivityCategory.STUDYING,
    "公开课": UserActivityCategory.STUDYING,
    "网课": UserActivityCategory.STUDYING,
    "教程": UserActivityCategory.STUDYING,
    "文档": UserActivityCategory.WORKING,
    "wiki": UserActivityCategory.BROWSING,
    "mdn": UserActivityCategory.WORKING,
    "w3school": UserActivityCategory.STUDYING,
    "runoob": UserActivityCategory.STUDYING,
    "菜鸟教程": UserActivityCategory.STUDYING,
    "tutorial": UserActivityCategory.STUDYING,
    "learn": UserActivityCategory.STUDYING,
    "课程": UserActivityCategory.STUDYING,
    "考试": UserActivityCategory.STUDYING,
    "题库": UserActivityCategory.STUDYING,
    "试卷": UserActivityCategory.STUDYING,
    "作业": UserActivityCategory.STUDYING,
    "论文": UserActivityCategory.STUDYING,
    "文献": UserActivityCategory.STUDYING,
    "知网": UserActivityCategory.STUDYING,
    "wanfang": UserActivityCategory.STUDYING,
    "arxiv": UserActivityCategory.STUDYING,
    "scholar": UserActivityCategory.STUDYING,
    "researchgate": UserActivityCategory.STUDYING,
    "springer": UserActivityCategory.STUDYING,
    "ieee": UserActivityCategory.STUDYING,
    "acm": UserActivityCategory.STUDYING,
    "libgen": UserActivityCategory.STUDYING,
    "z-library": UserActivityCategory.STUDYING,

    # ===== 游戏相关关键词 =====
    "steam": UserActivityCategory.GAMING,
    "epic games": UserActivityCategory.GAMING,
    "twitch": UserActivityCategory.ENTERTAINMENT,
    "youtube gaming": UserActivityCategory.ENTERTAINMENT,
    "斗鱼": UserActivityCategory.ENTERTAINMENT,
    "虎牙": UserActivityCategory.ENTERTAINMENT,
    "bilibili直播": UserActivityCategory.ENTERTAINMENT,
    "游戏": UserActivityCategory.GAMING,
    "game": UserActivityCategory.GAMING,
    "电竞": UserActivityCategory.GAMING,
    "esports": UserActivityCategory.GAMING,

    # ===== 视频娱乐关键词 =====
    "youtube": UserActivityCategory.ENTERTAINMENT,
    "bilibili": UserActivityCategory.ENTERTAINMENT,
    "哔哩哔哩": UserActivityCategory.ENTERTAINMENT,
    "优酷": UserActivityCategory.ENTERTAINMENT,
    "爱奇艺": UserActivityCategory.ENTERTAINMENT,
    "iqiyi": UserActivityCategory.ENTERTAINMENT,
    "腾讯视频": UserActivityCategory.ENTERTAINMENT,
    "芒果tv": UserActivityCategory.ENTERTAINMENT,
    "netflix": UserActivityCategory.ENTERTAINMENT,
    "disney+": UserActivityCategory.ENTERTAINMENT,
    "hulu": UserActivityCategory.ENTERTAINMENT,
    "prime video": UserActivityCategory.ENTERTAINMENT,
    "hbo": UserActivityCategory.ENTERTAINMENT,
    "动画": UserActivityCategory.ENTERTAINMENT,
    "动漫": UserActivityCategory.ENTERTAINMENT,
    "番剧": UserActivityCategory.ENTERTAINMENT,
    "电影": UserActivityCategory.ENTERTAINMENT,
    "电视剧": UserActivityCategory.ENTERTAINMENT,
    "综艺": UserActivityCategory.ENTERTAINMENT,
    "tiktok": UserActivityCategory.ENTERTAINMENT,
    "抖音": UserActivityCategory.ENTERTAINMENT,
    "快手": UserActivityCategory.ENTERTAINMENT,
    "小红书": UserActivityCategory.ENTERTAINMENT,
    "微博": UserActivityCategory.ENTERTAINMENT,
    "twitter": UserActivityCategory.ENTERTAINMENT,
    "instagram": UserActivityCategory.ENTERTAINMENT,
    "facebook": UserActivityCategory.ENTERTAINMENT,
    "reddit": UserActivityCategory.BROWSING,
    "pinterest": UserActivityCategory.ENTERTAINMENT,
    "淘宝": UserActivityCategory.ENTERTAINMENT,
    "京东": UserActivityCategory.ENTERTAINMENT,
    "天猫": UserActivityCategory.ENTERTAINMENT,
    "拼多多": UserActivityCategory.ENTERTAINMENT,
    "闲鱼": UserActivityCategory.ENTERTAINMENT,
    "购物": UserActivityCategory.ENTERTAINMENT,
}


def is_system_process(process_name: str) -> bool:
    """判断是否为系统/后台进程"""
    system_prefixes = (
        "svchost", "services", "system", "idle", "registry",
        "smss", "csrss", "wininit", "winlogon", "lsass",
        "taskhost", "sihost", "runtimebroker", "shellexperiencehost",
        "searchindexer", "compmgmtlauncher", "fontdrvhost",
        "dwm", "audiodg", "sdwmain", "wlanext",
        "dbus", "systemd", "pulseaudio", "pipewire", "wireplumber",
        "gvfs", "xdg-permission", "ksmserver", "kwin", "plasmashell",
        "gnome-shell", "gnome-keyring-d", "agent",
        "kernel_task", "launchd", "distnoted", "cfprefsd",
        "nsurlsessiond", "coreauthui", "trustd",
    )
    name_lower = process_name.lower().strip()
    return any(name_lower.startswith(p) or name_lower == p for p in system_prefixes)


def classify_by_process_name(process_name: str) -> Tuple[UserActivityCategory, str]:
    """根据进程名进行活动分类"""
    name_lower = process_name.lower().strip()

    # 精确匹配
    if name_lower in PROCESS_CATEGORY_MAP:
        cat, display = PROCESS_CATEGORY_MAP[name_lower]
        return cat, display

    # 包含匹配（处理带版本号后缀的进程名，如 "chrome.123"）
    for key, (cat, display) in PROCESS_CATEGORY_MAP.items():
        if name_lower.startswith(key + ".") or name_lower.startswith(key + "_"):
            return cat, display

    # 特殊后缀处理
    for suffix in ("_x64.exe", "_x86.exe", ".exe", ".app", ".bin"):
        if name_lower.endswith(suffix):
            trimmed = name_lower[:-len(suffix)]
            if trimmed in PROCESS_CATEGORY_MAP:
                cat, display = PROCESS_CATEGORY_MAP[trimmed]
                return cat, display

    return UserActivityCategory.UNKNOWN, process_name


def classify_by_window_title(window_title: str) -> UserActivityCategory:
    """根据窗口标题进行二次分类（主要用于浏览器）"""
    if not window_title:
        return UserActivityCategory.UNKNOWN

    title_lower = window_title.lower().strip()

    # 遍历关键词映射，按关键词长度降序排列优先匹配长关键词
    sorted_keywords = sorted(
        WINDOW_TITLE_KEYWORD_MAP.items(),
        key=lambda x: len(x[0]),
        reverse=True,
    )

    for keyword, category in sorted_keywords:
        if keyword.lower() in title_lower:
            return category

    return UserActivityCategory.UNKNOWN


def extract_relevant_keyword(window_title: str) -> str:
    """从窗口标题中提取最有意义的关键词片段"""
    if not window_title:
        return ""
    # 常见浏览器标题格式："页面标题 - 浏览器名称"，取前面的部分
    parts = window_title.split(" - ")
    if len(parts) > 1:
        # 去掉常见的浏览器后缀
        browser_suffixes = [
            "google chrome", "microsoft edge", "mozilla firefox",
            "brave", "opera", "vivaldi", "arc", "safari",
            "chromium", "internet explorer",
        ]
        last_part = parts[-1].strip().lower()
        if any(suffix in last_part for suffix in browser_suffixes):
            return parts[0].strip()[:40]
    return window_title.strip()[:40]
