"""
系统进程查看工具 - 只读，供AI判断用户当前活动状态
"""
import asyncio
from typing import Optional
from pydantic import BaseModel, Field
from .base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("process_tool")


class ProcessCheckInput(BaseModel):
    filter_keyword: Optional[str] = Field(
        default=None,
        description="可选的关键词过滤，只返回进程名包含该关键词的进程"
    )


class ProcessCheckTool(BaseTool):
    name = "check_running_processes"
    description = (
        "查看当前电脑正在运行的应用程序（只读）。"
        "返回有窗口标题的主要进程列表，包含进程名和窗口标题，"
        "可用于判断用户当前在做什么（如玩游戏、看视频、写代码等）。"
        "不会返回系统后台进程，仅返回用户可见的应用程序。"
        "可在日常对话或主动关怀时调用，了解用户当前活动状态。"
    )
    short_description = "查看电脑正在运行的应用程序（只读）"
    category = "utility"
    args_schema = ProcessCheckInput

    # 已知用户应用程序（即使没有窗口标题也展示）
    _KNOWN_USER_APPS = {
        'qq.exe', 'wechat.exe', 'tim.exe', 'dingtalk.exe', 'feishu.exe',
        'yuanShen.exe', 'genshinimpact.exe', 'steam.exe', 'epicgameslauncher.exe',
        'msedge.exe', 'chrome.exe', 'firefox.exe', 'browser.exe',
        'code.exe', 'pycharm64.exe', 'idea64.exe', 'clion64.exe',
        'webstorm64.exe', 'goland64.exe', 'cursor.exe',
        'wps.exe', 'wpp.exe', 'et.exe', 'wpspdf.exe',
        'winword.exe', 'excel.exe', 'powerpnt.exe', 'onenote.exe',
        'notion.exe', 'obsidian.exe', 'typora.exe',
        'vlc.exe', 'potplayer.exe', 'potplayermini64.exe',
        'netease_cloudmusic.exe', 'cloudmusic.exe', 'qqmusic.exe',
        'kugou.exe', 'spotify.exe',
        'bilibili.exe', 'discord.exe', 'telegram.exe',
        'todesk.exe', 'sunloginclient.exe', 'anydesk.exe',
        'java.exe', 'javaw.exe',
        'trae cn.exe',  # 开发工具（显示一个实例）
    }

    # 系统后台进程黑名单（不展示）
    _SYSTEM_PROCESSES = {
        # Windows核心系统进程
        'system', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe',
        'services.exe', 'lsass.exe', 'svchost.exe', 'fontdrvhost.exe',
        'dwm.exe', 'winlogon.exe', 'sihost.exe', 'taskhostw.exe',
        'explorer.exe', 'ctfmon.exe', 'dllhost.exe', 'conhost.exe',
        'runtimebroker.exe', 'searchui.exe', 'shellexperiencehost.exe',
        'applicationframehost.exe', 'backgroundtaskhost.exe',
        'systemsettings.exe', 'securityhealthservice.exe',
        'securityhealthsystray.exe', 'tabtip.exe', 'perceptionsimulation.exe',
        'startmenuexperiencehost.exe', 'searchhost.exe',
        'widgetservice.exe', 'widgets.exe', 'microsoft.notes.exe',
        'audiodg.exe', 'wudfhost.exe', 'sppsvc.exe',
        'memory compression', 'system idle process', 'interrupts',
        'system and compressed memory', 'desktop window manager',
        'windows shell experience host', 'microsoft text input application',
        'windows internal isolate user mode', 'secure system',
        'service host', 'windows security notification', 'lockapp.exe',
        'logonui.exe', 'mem compression', 'taskmgr.exe',
        'dashost.exe', 'deviceassociationbroker.exe',
        'msmpeng.exe', 'mpcmdrun.exe',
        'antimalware service executable', 'windows defender',
        # 驱动/硬件服务
        'amdrsserv.exe', 'amdrssrcext.exe', 'atieclxx.exe', 'atiesrxx.exe',
        'amdfendrsr.exe', 'amdpkgsvc.exe', 'amdow.exe',
        'nvidia overlay.exe', 'nvcontainer.exe', 'nvdisplay.container.exe',
        'nvsphelper64.exe', 'nvidia telemetry container.exe',
        # 后台服务
        'hipstray.exe', 'hipsdaemon.exe', 'saaservice.exe',
        'logioptionsplus_agent.exe', 'logioptionsplus_logivoice.exe',
        'logioptionsplus_updater.exe', 'logioptionsplus_appbroker.exe',
        'gcuservice.exe', 'gcubridge.exe',
        'senaryaudioapp.exe', 'senaryaudioapp.svc.exe',
        'crashpad_handler.exe',
        'msedgewebview2.exe',  # Edge内嵌WebView（不是用户主动用的）
        'phoneexperiencehost.exe', 'crossdeviceservice.exe', 'crossdeviceresume.exe',
        'microsoftstartfeedprovider.exe', 'widgetboard.exe',
        'searchindexer.exe', 'spoolsv.exe',
        'onedrive.sync.service.exe', 'onedrive.exe',
        'sogouimebroker.exe', 'sogoucloud.exe', 'sgtool.exe', 'chsime.exe',
        'textinputhost.exe', 'shellhost.exe',
        'wmiprvse.exe', 'lsaiso.exe', 'unsecapp.exe', 'aggregatorhost.exe',
        'wlanext.exe', 'armsvc.exe', 'ngciso.exe',
        'clash-verge-service.exe',
        'wpscloudsvr.exe', 'msofficeplusservice.exe', 'officeclicktorun.exe',
        'sdxhelper.exe', 'appactions.exe', 'osddpdetect.exe', 'osdtpdetect.exe',
        'useroobebroker.exe', 'gamingservices.exe', 'gamingservicesnet.exe',
        'gameinputsvc.exe', 'gameinputredistservice.exe',
        'fevergamesservice.exe', 'wslservice.exe',
        'ss_conn_service.exe', 'ss_conn_service2.exe',
        'wsctrlsvc.exe', 'mraftersalesservice.exe', 'promecefpluginhost.exe',
        'napcatwinbootmain.exe', 'setup.exe',
        'workbuddy.exe',  # 系统助手
        'openconsole.exe',
        'memcompression',
        'node.exe',  # IDE后台node进程，不是用户主动用的
        'trae-sandbox.exe',  # Trae沙箱进程（不是主进程）
        # Windows更新/维护服务
        'usocore.exe', 'musnotification.exe', 'musnotificationux.exe',
        'sihclient.exe', 'trustedinstaller.exe', 'tiworker.exe',
        'usoisobrestart.exe', 'mousocoreworker.exe',
        # 输入法/IME
        'imebroker.exe', 'chsipaclick.exe', 'microsoft.ime.chs.exe',
        'microsoft.ime.jpn.exe', 'microsoft.ime.kor.exe',
        # 打印机服务
        'printspooler.exe', 'spoolsv.exe', 'printisolationhost.exe',
        # Windows Defender相关
        'msmpeng.exe', 'mpcmdrun.exe', 'mpuxfactsrv.exe',
        # 远程桌面/桌面服务
        'rdpclip.exe', 'rdpinput.exe', 'rdpd3d11.exe',
        'sessionenv.exe', 'rdpings.exe',
        # 电源管理
        'powrprof.dll', 'powercfg.exe', 'smart screen.exe',
        # Windows搜索/索引
        'searchapp.exe', 'searchprotocolhost.exe', 'searchfilterhost.exe',
        # 活动历史/时间线
        'activitymanager.exe', 'timebroker.exe',
        # Xbox/游戏相关后台服务
        'xboxgip.exe', 'xboxnetapisvc.exe', 'xblacsrv.exe',
        # Steam后台辅助进程（不是游戏本身）
        'steamwebhelper.exe', 'steamservice.exe',
        # 云存储/同步客户端（后台常驻）
        'nutstoreclient.exe', 'nutstore.windowshook.exe',
        'nutstoredriversvc.exe', 'nutstore_watchdog.exe',
        # 游戏加速器（后台常驻）
        'uu.exe', 'uu_ball.exe', 'uu_cloudsyn.exe', 'uu_launcher.exe', 'uu_neths_helper.exe',
        # 局域网传输工具（后台常驻）
        'localsend_app.exe',
        # Windows SmartScreen
        'smartscreen.exe',
        # 其他后台服务
        'biz_helper.exe', 'agent-tool-host.exe',
        'ntfswatcher.exe', 'nahimic3.exe',
        'qingyunlitehelperservice.exe', 'amdppkgsvc.exe', 'saclient.exe',
        'mraftersalesservice.exe', 'mraftersaleservice.exe',
        # 其他常见后台服务
        'browser_broker.exe', 'storsvc.exe', 'pcasvc.exe',
        'bthci.dll', 'bthserv.dll', 'btci.dll',
        # 任务栏相关
        'taskbar.exe', 'taskband.dll',
    }

    # AI自身使用的进程（需要特别标注）
    _AI_SELF_PROCESSES = {
        'python.exe', 'pythonw.exe',
        'windowsTerminal.exe', 'windowsterminal.exe',
        'pwsh.exe', 'cmd.exe',
    }

    async def _run(self, filter_keyword: Optional[str] = None) -> str:
        try:
            import psutil
        except ImportError:
            return "Error: psutil 未安装，无法查看进程"

        # P1-4: psutil.process_iter + Win32 API 都是同步阻塞调用
        # 整体放到线程池执行，避免阻塞事件循环
        try:
            return await asyncio.to_thread(self._run_sync, psutil, filter_keyword)
        except Exception as e:
            logger.error(f"查看进程失败: {e}")
            return f"查看进程失败: {str(e)}"

    def _run_sync(self, psutil, filter_keyword: Optional[str] = None) -> str:
        """同步实现：枚举进程和窗口标题（在线程池中执行）"""
        try:
            # 第一步：收集所有窗口标题（一次性枚举，避免逐进程调用）
            window_map = self._collect_all_window_titles()

            # 第二步：遍历进程，筛选用户应用
            results = []
            seen_names = set()

            for proc in psutil.process_iter(['name', 'pid', 'memory_info']):
                try:
                    name = proc.info['name']
                    if not name:
                        continue

                    name_lower = name.lower()

                    # 跳过系统后台进程
                    if name_lower in self._SYSTEM_PROCESSES:
                        continue

                    # 关键词过滤
                    if filter_keyword and filter_keyword.lower() not in name_lower:
                        continue

                    # 去重同名进程
                    if name_lower in seen_names:
                        continue
                    seen_names.add(name_lower)

                    pid = proc.info['pid']
                    mem_mb = 0
                    if proc.info['memory_info']:
                        mem_mb = round(proc.info['memory_info'].rss / 1024 / 1024)

                    # 获取窗口标题
                    titles = window_map.get(pid, [])
                    window_title = ""
                    if titles:
                        # 取第一个有意义的标题
                        for t in titles:
                            t_stripped = t.strip()
                            if t_stripped and len(t_stripped) > 1:
                                window_title = t_stripped
                                break

                    # 只展示有窗口标题的进程，或已知用户应用，或AI自身进程
                    has_window = bool(window_title)
                    is_known_app = name_lower in self._KNOWN_USER_APPS
                    is_ai_self = name_lower in self._AI_SELF_PROCESSES

                    if not has_window and not is_known_app and not is_ai_self:
                        continue

                    # 构建展示文本
                    entry = f"- {name}"

                    # AI自身进程特别标注
                    if is_ai_self:
                        entry += " [AI自身]"

                    if window_title:
                        # 截断过长的标题
                        display_title = window_title if len(window_title) <= 60 else window_title[:57] + "..."
                        entry += f" → {display_title}"
                    results.append((mem_mb, entry))

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

            if not results:
                if filter_keyword:
                    return f"没有找到包含 '{filter_keyword}' 的进程"
                return "没有找到用户应用程序进程"

            # 按内存占用降序排列
            results.sort(key=lambda x: x[0], reverse=True)
            lines = [r[1] for r in results]

            header = f"当前运行的应用程序（共{len(lines)}个）："
            return header + "\n" + "\n".join(lines)

        except Exception as e:
            # P1-4: 异常在线程池中抛出，由 _run 的外层 except 捕获并记录
            raise RuntimeError(f"查看进程失败: {e}") from e

    def _collect_all_window_titles(self) -> dict:
        """一次性枚举所有可见窗口的标题，返回 {pid: [title1, title2, ...]}"""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            EnumWindows = user32.EnumWindows
            GetWindowTextW = user32.GetWindowTextW
            IsWindowVisible = user32.IsWindowVisible
            GetWindowThreadProcessId = user32.GetWindowThreadProcessIdW

            window_map = {}

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def _enum_cb(hwnd, lparam):
                if not IsWindowVisible(hwnd):
                    return True

                length = GetWindowTextW(hwnd, None, 0)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    if title and len(title) > 1:
                        pid = wintypes.DWORD()
                        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        pid_val = pid.value
                        if pid_val not in window_map:
                            window_map[pid_val] = []
                        window_map[pid_val].append(title)
                return True

            EnumWindows(WNDENUMPROC(_enum_cb), 0)
            return window_map

        except Exception:
            return {}
