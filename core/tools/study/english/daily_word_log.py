"""每日新背单词日志（按 YYYY/MM/DD 文件夹组织）

与 unfamiliar_word.txt（历史生词本）互补：
- unfamiliar_word.txt 是用户长期积累的生词
- daily/YYYY/MM/DD.txt 是每天新背的、不会的单词

路径：data/study_data/English/Words/daily/YYYY/MM/DD.txt
格式：与 unfamiliar_word.txt 一致，每行 'word' 或 'word count'

设计要点：
1. lazy 创建：第一次写入时自动 mkdir + 创建文件，不预生成空文件
2. App 每日复习使用持久化批次：扫描全部历史日志、排除已经处理的记录，
   按日期从旧到新领取固定一批；同一天背空后不会继续自动翻下一批
3. mark 操作：单词可能在多天文件里出现，默认改最近一次出现该词的那天；
   指定 date 时只改那个文件
4. 单文件解析复用 UnfamiliarWordBook，保证格式行为一致

拆分说明（薄壳门面 + 按职责拆 mixin 子模块）
--------------------------------------------
原 1125 行单文件按职责拆成下列子模块，``DailyWordLogManager`` 由 mixin 组合而成，
**对外路径、类名与方法名不变**（``from core.tools.study.english.daily_word_log
import DailyWordLogManager`` 照旧可用）：

| 子模块 | 职责 |
|---|---|
| ``daily_word_log_source.py`` | daily 源文件签名、自写检测与批次状态落盘 |
| ``daily_word_log_review.py`` | 待复习判定与当天批次生成 |
| ``daily_word_log_queue.py``  | 最终复习队列的读取、锁定与同步 |
| ``daily_word_log_words.py``  | 单日文件访问、单词读取与抽查 |
| ``daily_word_log_marks.py``  | 标记认识/不认识、移除与最近 N 天统计 |

本文件保留：单例入口、时区助手、``__init__`` 与日期/路径工具、``list_dates`` /
``get_recent_dates`` / ``ensure_today_file`` / ``get_default_review_date``。

⚠️ 本门面同时是模块级 patch 点：测试与排查脚本会 patch 本模块的
``safe_json_dump`` / ``safe_json_load`` / ``get_current_time`` /
``get_current_time_str`` / ``_instance`` / ``_instance_lock``，子模块因此在
**调用期**从本模块取名（见各子模块头部说明），不能顶层 from-import 固化。

拆分是**纯搬家**：未改逻辑、命名与断言，唯一差异是 import 与 mixin 样板行。
"""
from __future__ import annotations

import datetime
import os
import threading
from typing import Dict, List, Optional

from core.tools.study.english.daily_word_log_marks import DailyWordLogMarksMixin
from core.tools.study.english.daily_word_log_queue import DailyWordLogQueueMixin
from core.tools.study.english.daily_word_log_review import DailyWordLogReviewMixin
from core.tools.study.english.daily_word_log_source import DailyWordLogSourceMixin
from core.tools.study.english.daily_word_log_words import DailyWordLogWordsMixin
from core.tools.study.english.unfamiliar_word_book import UnfamiliarWordBook
from core.utils.atomic_io import safe_json_dump, safe_json_load
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, get_current_time_str

logger = get_logger("DailyWordLog")


def _configured_tz():
    """返回项目配置时区（默认 Asia/Shanghai）的 tzinfo。

    供 datetime.fromtimestamp 使用，避免退化成服务器本地时区：
    naive fromtimestamp 会按服务器本地时区取日期，部署到非 Asia/Shanghai
    的机器时会与业务日期错位，进而把当天记录误判成 historical_backlog。
    """
    return get_current_time().tzinfo

_instance: Optional["DailyWordLogManager"] = None
_instance_lock = threading.Lock()


def get_daily_word_log() -> "DailyWordLogManager":
    """单例获取每日单词日志管理器"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is not None:
                return _instance
            _instance = DailyWordLogManager()
    return _instance


class DailyWordLogManager(
    DailyWordLogReviewMixin,
    DailyWordLogSourceMixin,
    DailyWordLogQueueMixin,
    DailyWordLogWordsMixin,
    DailyWordLogMarksMixin,
):
    """按日期组织的每日新背单词日志

    具体职责由 mixin 提供（见模块头部表格），本类只保留构造、日期/路径工具与
    跨职责的入口方法。
    """

    def __init__(self, base_dir: Optional[str] = None):
        # core/tools/study/english/daily_word_log.py -> 项目根
        project_root = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
            )
        )
        self.base_dir = base_dir or os.path.join(
            project_root, "data", "study_data", "English", "Words", "daily"
        )
        # 缓存：date_str -> UnfamiliarWordBook 实例
        self._books: Dict[str, UnfamiliarWordBook] = {}
        self._lock = threading.Lock()
        # 可重入锁：批次状态读改写的方法内部还会再次加锁
        self._review_state_lock = threading.RLock()
        # 本管理器自己写入过的日期文件签名（date -> sha1），用于区分用户手动编辑
        self._self_written: Dict[str, str] = {}
        self._review_state_path = os.path.join(
            self.base_dir, "_review_source_state.json"
        )
        self._review_batch_state_path = os.path.join(
            self.base_dir, "_review_batch_state.json"
        )
        self._review_queue_state_path = os.path.join(
            self.base_dir, "_review_queue_state.json"
        )

    # ------------------------------------------------------------------
    # 日期与路径
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """'2026-08-05' / '2026/08/05' -> '2026/08/05'"""
        return str(date_str or "").replace("-", "/").strip()

    def _date_to_path(self, date_str: str) -> str:
        """'2026/08/05' -> base_dir/2026/08/05.txt"""
        normalized = self._normalize_date(date_str)
        parts = normalized.split("/")
        return os.path.join(self.base_dir, *parts) + ".txt"

    @staticmethod
    def _get_today_str() -> str:
        return get_current_time_str("%Y/%m/%d")

    def get_yesterday_str(self) -> str:
        """返回昨天日期。"""
        today = datetime.datetime.strptime(self._get_today_str(), "%Y/%m/%d").date()
        return (today - datetime.timedelta(days=1)).strftime("%Y/%m/%d")

    def get_default_review_date(self) -> str:
        """返回 daily 复习默认应读取的日期。

        优先选择今天之前最近的非空日志。这样即使昨天没有背词、
        只留下空占位文件，前一份尚未处理的词也会继续进入今天。
        当天首次选中非空来源后会持久化锁定；即使该文件随复习
        被清空，也不会在同一天继续向更早的历史文件链式回溯。
        如果历史上没有任何非空日志，回退到昨天，保持空结果的
        日期语义稳定。
        """
        today_str = self._normalize_date(self._get_today_str())
        today = datetime.datetime.strptime(today_str, "%Y/%m/%d").date()

        with self._review_state_lock:
            state = safe_json_load(self._review_state_path, default={})
            if isinstance(state, dict) and state.get("review_date") == today_str:
                source_date = self._normalize_date(state.get("source_date", ""))
                try:
                    source_day = datetime.datetime.strptime(
                        source_date, "%Y/%m/%d"
                    ).date()
                except ValueError:
                    source_day = None
                if source_day is not None and source_day < today:
                    return source_date

            candidates = []
            for date_str in self.list_dates():
                try:
                    candidate_date = datetime.datetime.strptime(
                        self._normalize_date(date_str), "%Y/%m/%d"
                    ).date()
                except ValueError:
                    continue
                if candidate_date < today:
                    candidates.append((candidate_date, date_str))

            for _, date_str in sorted(candidates, reverse=True):
                if not self.get_words_for_date(date_str):
                    continue
                source_date = self._normalize_date(date_str)
                try:
                    safe_json_dump(
                        {
                            "review_date": today_str,
                            "source_date": source_date,
                            "selected_at": get_current_time_str(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                        },
                        self._review_state_path,
                    )
                except OSError as e:
                    logger.warning(f"持久化 daily 复习来源失败: {e}")
                return source_date
        return self.get_yesterday_str()

    # ------------------------------------------------------------------
    # 单文件访问 / 日期列表
    # ------------------------------------------------------------------

    def ensure_today_file(self) -> str:
        """确保今天的文件存在（创建目录 + 空文件），返回文件路径

        后端启动时调用，避免 AI 第一次写入时才触发文件创建。
        幂等：文件已存在时不覆盖。
        """
        today = self._get_today_str()
        path = self._date_to_path(today)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            # 创建空文件占位，便于用户后续手动追加内容
            open(path, "w", encoding="utf-8").close()
            logger.info(f"Created daily word log: {path}")
        return path

    def list_dates(self) -> List[str]:
        """列出所有有记录的日期（降序，最新在前）"""
        dates: List[str] = []
        if not os.path.exists(self.base_dir):
            return dates

        try:
            for year in sorted(os.listdir(self.base_dir), reverse=True):
                year_path = os.path.join(self.base_dir, year)
                if not os.path.isdir(year_path) or not year.isdigit():
                    continue
                for month in sorted(os.listdir(year_path), reverse=True):
                    month_path = os.path.join(year_path, month)
                    if not os.path.isdir(month_path) or not month.isdigit():
                        continue
                    for day_file in sorted(os.listdir(month_path), reverse=True):
                        if not day_file.endswith(".txt"):
                            continue
                        day = day_file[:-4]
                        if day.isdigit():
                            dates.append(f"{year}/{month}/{day}")
        except OSError as e:
            logger.warning(f"Failed to list daily dates: {e}")

        return dates

    def get_recent_dates(self, days: int = 7) -> List[str]:
        """获取最近 N 天的日期列表（含今天，降序）"""
        today_str = self._get_today_str()
        y, m, d = map(int, today_str.split("/"))
        today = datetime.date(y, m, d)
        return [
            (today - datetime.timedelta(days=i)).strftime("%Y/%m/%d")
            for i in range(max(1, days))
        ]
