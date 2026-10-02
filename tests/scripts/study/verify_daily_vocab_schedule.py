"""验证每日单词推送（check_daily_vocabulary）已挂上可配置时刻调度。

覆盖点：
1. 推送时刻可配置（study.daily_vocab_push_hours，默认早上 8 点），非法输入回退默认；
2. 默认时刻与催背时刻（12/16/20/22）不重叠，避免同一小时连推两条单词通知；
3. 到点判据：未到点不推、到点推、服务启动晚了当天补推、词库关闭不推；
4. 到点后维护循环真的会调用 check_daily_vocabulary（挂上调度）；
5. 推送只走统一入口 app_push，载荷带 target=vocab 且正文非空（点进去直达背单词页）；
6. 现有每日去重（daily_vocab_status.json 按日期）保留：同一天只推一次。
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings_life import StudySettings  # noqa: E402
from core.services.active_care.core import watchdog as watchdog_module  # noqa: E402
from core.services.active_care.shared import vocabulary as vocab_module  # noqa: E402
from core.services.notification import app_push  # noqa: E402
from core.utils.time_utils import get_current_time_str  # noqa: E402

RUNTIME_DIR = "/tmp/verify_daily_vocab"
TODAY = get_current_time_str("%Y-%m-%d")

# 空壳对象：把 settings / 存储 / 词库 / Python 模块都换成内存版，
# 验证脚本不碰真实用户目录、不加载 CET4 词库。
SimpleNamespace = types.SimpleNamespace


class _FakeStorage:
    """内存版 ActiveCareStorage：只读写 daily_vocab_status.json。"""

    def __init__(self, initial=None):
        self.files = dict(initial or {})

    async def read_json_file(self, path):
        return dict(self.files.get(path, {}))

    async def write_json_file(self, path, data):
        self.files[path] = dict(data)


class _FakeVocabularyManager:
    def get_daily_words(self, limit=20):
        return [
            {
                "word": "apple",
                "translations": [{"type": "n", "translation": "苹果"}],
                "status": "new",
            }
        ]


class _FakeVocabForLoop:
    """维护循环里的 vocab 替身：记录被调用了什么。"""

    def __init__(self, due=True):
        self.due = due
        self.daily_pushes = 0
        self.quiz_checks = 0

    def daily_vocab_push_due(self):
        return self.due

    async def check_daily_vocabulary(self):
        self.daily_pushes += 1

    async def check_daily_word_quiz(self):
        self.quiz_checks += 1


class _FakeService:
    def __init__(self, vocab):
        self._running = True
        self.vocab = vocab
        self.state_manager = self

    async def check_expired_states(self):
        return {}


class _StopLoop(Exception):
    """让维护循环只跑一轮的哨兵异常。"""


def _make_vocab(push_hours, enabled=True, storage=None):
    """造一个不依赖真实配置/用户目录的 ActiveCareVocabulary。"""
    vocab = vocab_module.ActiveCareVocabulary(storage or _FakeStorage())
    vocab.settings = SimpleNamespace(study=SimpleNamespace(enabled=enabled))
    vocab._get_runtime_dir = lambda: RUNTIME_DIR
    vocab_module.ActiveCareVocabulary._daily_push_hours = staticmethod(
        lambda: list(push_hours)
    )
    return vocab


def _run_maintenance_once(vocab):
    """把维护循环跑一轮（用假 sleep 在第二次休眠时退出）。"""
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise _StopLoop()

    async def _run():
        return await watchdog_module.WatchdogManager(_FakeService(vocab)).run_maintenance_loop()

    original_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        asyncio.run(_run())
    except _StopLoop:
        pass
    finally:
        asyncio.sleep = original_sleep


def main() -> int:
    problems: list[str] = []

    # ---- 1. 推送时刻可配置（默认早上 8 点） ----
    try:
        default_hours = StudySettings().get_daily_vocab_push_hours()
        if default_hours != [8]:
            problems.append(f"默认每日单词推送时刻应为 [8]，实际 {default_hours}")
        if StudySettings(daily_vocab_push_hours="7, 9,7").get_daily_vocab_push_hours() != [7, 9]:
            problems.append("每日单词推送时刻解析未去重/未排序")
        if StudySettings(daily_vocab_push_hours="abc").get_daily_vocab_push_hours() != [8]:
            problems.append("非法每日单词推送时刻未回退默认 8 点")
        if StudySettings(daily_vocab_push_hours="25,-1").get_daily_vocab_push_hours() != [8]:
            problems.append("越界时刻未过滤/未回退默认值")
    except Exception as exc:
        problems.append(f"每日单词推送时刻解析异常: {exc}")

    # ---- 2. 默认与催背时刻错开（别在同一小时推两条单词通知） ----
    try:
        overlap = set(StudySettings().get_daily_vocab_push_hours()) & set(
            StudySettings().get_vocab_reminder_hours()
        )
        if overlap:
            problems.append(f"每日单词推送与催背提醒默认时刻重叠: {sorted(overlap)}")
    except Exception as exc:
        problems.append(f"默认时刻重叠检查异常: {exc}")

    # ---- 3. 到点判据 ----
    vocab = _make_vocab([8])
    original_hour = vocab_module.current_hour
    try:
        for hour, expected in ((7, False), (8, True), (23, True)):
            vocab_module.current_hour = lambda h=hour: h
            if vocab.daily_vocab_push_due() is not expected:
                problems.append(f"{hour} 点的到点判据应为 {expected}")
    finally:
        vocab_module.current_hour = original_hour

    vocab_off = _make_vocab([8], enabled=False)
    if vocab_off.daily_vocab_push_due():
        problems.append("study.enabled=false 时不应判定为到点推送")

    # ---- 4. 到点后维护循环确实会推送（挂上调度）----
    due_vocab = _FakeVocabForLoop(due=True)
    _run_maintenance_once(due_vocab)
    if due_vocab.daily_pushes != 1:
        problems.append(f"到点后维护循环应推送每日单词，实际 {due_vocab.daily_pushes} 次")
    if due_vocab.quiz_checks != 1:
        problems.append("每日生词测验推送不应被每日单词调度影响")

    not_due_vocab = _FakeVocabForLoop(due=False)
    _run_maintenance_once(not_due_vocab)
    if not_due_vocab.daily_pushes != 0:
        problems.append("未到推送时刻不应推送每日单词")

    # ---- 5~6. 到点推送走 app_push，且按日期去重 ----
    storage = _FakeStorage()
    push_vocab = _make_vocab([8], storage=storage)
    vocab_module.current_hour = lambda: 8
    captured: list[dict] = []

    async def fake_async_push(title, content, target=None, data=None, notification_type="system"):
        captured.append(
            {
                "title": title,
                "content": content,
                "target": target,
                "data": data,
                "type": notification_type,
            }
        )
        return True

    fake_vm_module = types.ModuleType("core.tools.study.english.vocabulary_manager")
    fake_vm_module.get_vocabulary_manager = lambda: _FakeVocabularyManager()
    original_push = app_push.async_push_app_notification
    original_vm_module = sys.modules.get("core.tools.study.english.vocabulary_manager")
    app_push.async_push_app_notification = fake_async_push
    sys.modules["core.tools.study.english.vocabulary_manager"] = fake_vm_module
    try:
        asyncio.run(push_vocab.check_daily_vocabulary())
        if len(captured) != 1:
            problems.append(f"到点应推送 1 条每日单词，实际 {len(captured)}")
        else:
            payload = captured[0]
            if payload["target"] != app_push.TARGET_VOCAB:
                problems.append(f"每日单词 target 应为 vocab，实际 {payload['target']}")
            if not payload["content"] or not payload["data"].get("full_text"):
                problems.append("每日单词推送正文/完整词表为空")
            if payload["type"] != "vocabulary":
                problems.append(f"每日单词通知类型应为 vocabulary，实际 {payload['type']}")

        # 同一天再调用一次：daily_vocab_status.json 已记录今天，不应重复推送
        asyncio.run(push_vocab.check_daily_vocabulary())
        if len(captured) != 1:
            problems.append("同一天不应重复推送每日单词（按日期去重失效）")

        status_path = os.path.join(RUNTIME_DIR, "daily_vocab_status.json")
        if not storage.files.get(status_path, {}).get(TODAY):
            problems.append("推送后应按日期写入 daily_vocab_status.json 标记")
    finally:
        app_push.async_push_app_notification = original_push
        vocab_module.current_hour = original_hour
        if original_vm_module is None:
            sys.modules.pop("core.tools.study.english.vocabulary_manager", None)
        else:
            sys.modules["core.tools.study.english.vocabulary_manager"] = original_vm_module

    if problems:
        print("验证失败:")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("每日单词推送调度验证通过：可配置时刻 / 到点补推 / 走 app_push / 按日期去重均正确")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
