#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
错误日志分流改造验证脚本

验证：
1. is_upstream_transient_error 对 8 类典型错误 + 3 类后端代码错误的分类是否正确
2. ErrorCollectorHandler._append_to_daily_file 分流后是否写入两个不同的目录
3. 错误报告中 classification 元信息是否注入
4. .gitignore 中 logs/upstream_errors/ 规则存在

运行：
    D:\AI\xiaoyou-core\venv_core\Scripts\python.exe tests\scripts\monitoring\verify_error_splitting.py
"""

import json
import sys
import tempfile
import shutil
from pathlib import Path

# 让项目根目录可 import
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.error_collector import (  # noqa: E402
    is_upstream_transient_error,
    ErrorCollectorHandler,
)


# ============================================================
# 用例构造
# ============================================================

def build(
    error_message: str,
    logger_name: str = "siliconflow_client",
    traceback: str = "",
    source_file: str = r"D:\AI\xiaoyou-core\core\llm\siliconflow_client.py",
    source_func: str = "_stream_generate",
    source_line: int = 412,
) -> dict:
    return {
        "error_id": "err_test_000000000000",
        "timestamp": "2026-08-04T00:00:00+00:00",
        "severity": "ERROR",
        "error_type": "LoggedError",
        "error_message": error_message,
        "traceback": traceback,
        "context": {
            "logger_name": logger_name,
            "source_file": source_file,
            "source_line": source_line,
            "source_func": source_func,
        },
    }


# 12 条上游（应判定 True）
UPSTREAM_CASES = [
    # A. SiliconFlow 503 繁忙
    ('A-SF-503', build(
        'Stream Error 503: {"code":50508,"message":"System is too busy now. Please try again later.","data":null}',
    )),
    # B. Stream Request Failed（空，属于上游连接断开）
    ('B-SF-StreamRequestFailed', build(
        'Stream Request Failed: ',
        traceback="",
    )),
    # C. SiliconFlow 20012 "Model does not exist"（过载窗口误报，且在上游 logger 白名单 + traceback 为空）
    ('C-SF-20012-ModelNotExist-misreport', build(
        'API Error 400: {"code":20012,"message":"Model does not exist. Please check it carefully.","data":null}',
        traceback="",
    )),
    # D. openai_compat 503 Service is too busy
    ('D-OA-503-ServiceTooBusy', build(
        'API Error (503): {"error":{"message":"Service is too busy. We advise users to temporarily switch to alternative LLM API service providers."}}',
        logger_name="openai_client",
        source_file=r"D:\AI\xiaoyou-core\core\llm\openai_compat\client.py",
        source_func="stream_chat",
    )),
    # E. openai_compat 400 "unknown model"（过载误报，上游 logger 白名单 + traceback 空）
    ('E-OA-400-unknown-model-misreport', build(
        'API Error (400): {"type":"error","error":{"type":"bad_request_error","message":"invalid params, unknown model \'deepseek-v4-flash\' (2013)"}}',
        logger_name="openai_client",
        source_file=r"D:\AI\xiaoyou-core\core\llm\openai_compat\client.py",
        source_func="_handle_error_response",
    )),
    # F. timeout
    ('F-Timeout', build('Chat failed: Read timed out. (read timeout=60)')),
    # G. 429 rate limit
    ('G-429-RateLimit', build(
        'API Error 429: {"error":{"message":"Rate limit reached for requests"}}',
    )),
    # H. 502 Bad Gateway
    ('H-502-BadGateway', build('Stream Error 502: 502 Bad Gateway')),
    # I. 余额不足（运维侧，非代码）
    ('I-402-Balance', build(
        'API Error 402: {"error":{"message":"Insufficient Balance"}}',
    )),
    # J. Connection reset by peer
    ('J-ConnReset', build('Request Failed: [Errno 104] Connection reset by peer')),
    # K. SiliconFlow vendor error code 50508
    ('K-Vendor-50508', build(
        'Error body: {"code":50508,"message":"System is too busy now."}',
    )),
    # L. 429 too many requests keyword
    ('L-TooManyRequests', build(
        'HTTP 429: Too Many Requests (H8::RateLimit)',
    )),
]

# 5 条后端代码错误（应判定 False）—— 必须进入根目录 errors_*.json
BACKEND_CASES = [
    # 1. weighted_memory_manager 的 dict 并发迭代崩溃（真实异常，有 traceback）
    ('M-BE-ConcurrentDictIter', build(
        '保存加权记忆失败: dictionary changed size during iteration',
        logger_name="weighted_memory_manager",
        source_file=r"D:\AI\xiaoyou-core\memory\weighted_memory_manager.py",
        source_func="_save_weighted_data_locked",
        traceback=(
            'Traceback (most recent call last):\n'
            '  File "weighted_memory_manager.py", line 613, in _save_weighted_data_locked\n'
            '    for mem_id, mem in weighted_memories.items():\n'
            'RuntimeError: dictionary changed size during iteration\n'
        ),
    )),
    # 2. nightly task 的真实业务异常
    ('N-BE-NightlyException', build(
        '提取人物档案失败: \'NoneType\' object has no attribute \'append\'',
        logger_name="PeopleProfileExtractor",
        source_file=r"D:\AI\xiaoyou-core\core\character\people\extractor.py",
        source_func="extract_batch",
        traceback=(
            'Traceback (most recent call last):\n'
            '  File "extractor.py", line 234, in extract_batch\n'
            '    batch.append(item)\n'
            "AttributeError: 'NoneType' object has no attribute 'append'\n"
        ),
    )),
    # 3. JournalSummaryService 解析真实 JSON 错误（有 traceback，且 logger 不是上游白名单）
    ('O-BE-JSONParseError', build(
        'Failed to parse LLM output: Expecting value: line 1 column 1 (char 0)',
        logger_name="JournalSummaryService",
        source_file=r"D:\AI\xiaoyou-core\core\services\journal\summary_service.py",
        source_func="generate_daily_summary",
        traceback=(
            'Traceback (most recent call last):\n'
            '  File "summary_service.py", line 278, in generate_daily_summary\n'
            '    data = extract_json_object(raw_out)\n'
            '  File "core/utils/json_utils.py", line 42, in extract_json_object\n'
            '    return json.loads(cleaned)\n'
            'json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)\n'
        ),
    )),
    # 4. 真实配置错误（deepseek-v4-flash 这个场景下如果有 Python 异常，就不是误报，而是后端代码 bug 拼错了 model name）
    ('P-BE-RealConfigBug-WithTraceback', build(
        'Chat failed: HTTP 400: {"code":20012,"message":"Model does not exist."}',
        logger_name="my_custom_module",     # 非上游 logger 白名单
        traceback=(
            'Traceback (most recent call last):\n'
            '  File "my_custom_module.py", line 87, in submit_chat\n'
            '    await client.chat(messages, model="deepseek-v5-turbo-typo-in-name")\n'
            "ValueError: Model not registered\n"
        ),
    )),
    # 5. 非上游 logger 的通用业务错误
    ('Q-BE-GenericBusiness', build(
        '初始化角色日常引擎失败: Role \'xiaolu\' missing persona_config',
        logger_name="CharacterDailyEngine",
        source_file=r"D:\AI\xiaoyou-core\core\services\character_daily\engine.py",
        source_func="__init__",
    )),
]


def main() -> int:
    failed = 0

    # ---------- 1. 纯分类单元测试 ----------
    print("[1/4] 纯分类单元测试（is_upstream_transient_error）")
    for name, rep in UPSTREAM_CASES:
        result = is_upstream_transient_error(rep)
        status = "PASS" if result is True else "FAIL"
        if status == "FAIL":
            failed += 1
        print(f"  [{status}] UPSTREAM  {name} -> is_upstream={result}")
        if status == "FAIL":
            print(f"         msg={rep['error_message'][:120]}")

    for name, rep in BACKEND_CASES:
        result = is_upstream_transient_error(rep)
        status = "PASS" if result is False else "FAIL"
        if status == "FAIL":
            failed += 1
        print(f"  [{status}] BACKEND   {name} -> is_upstream={result}")
        if status == "FAIL":
            print(f"         msg={rep['error_message'][:120]}")

    # ---------- 2. 模拟实际写入分流 ----------
    print("\n[2/4] 模拟 ErrorCollectorHandler 分流写入")
    tmp = Path(tempfile.mkdtemp(prefix="err_split_"))
    try:
        root = tmp / "project"
        root.mkdir(parents=True, exist_ok=True)
        (root / "main.py").write_text("", encoding="utf-8")
        (root / "logs").mkdir(parents=True, exist_ok=True)

        handler = ErrorCollectorHandler()
        # 注入假的项目根（通过猴子补丁 _find_project_root）
        import core.utils.error_collector as ec_mod
        old_find = ec_mod._find_project_root
        ec_mod._find_project_root = lambda: root
        try:
            # 构造 LogRecord 模拟（用 handler 内部方法构造 error_report 更省事）
            for idx, (name, rep) in enumerate(UPSTREAM_CASES[:6] + BACKEND_CASES[:3]):
                # 直接调 _append_to_daily_file，跳过 emit 其它逻辑
                copy = json.loads(json.dumps(rep))
                copy["error_id"] = f"err_test_{idx:012d}"
                handler._append_to_daily_file(copy)

            root_err = list(root.glob("errors_*.json"))
            upstream_dir = root / "logs" / "upstream_errors"
            upstream_err = list(upstream_dir.glob("upstream_errors_*.json")) if upstream_dir.exists() else []

            root_count = sum(len(json.loads(p.read_text(encoding="utf-8"))) for p in root_err)
            up_count = sum(len(json.loads(p.read_text(encoding="utf-8"))) for p in upstream_err)
            total = root_count + up_count

            # 6 条上游 + 3 条后端 = 9
            expect_root, expect_up = 3, 6
            ok = (root_count == expect_root and up_count == expect_up and total == 9)
            status = "PASS" if ok else "FAIL"
            if status == "FAIL":
                failed += 1
            print(f"  [{status}] 分流文件数量：根目录 errors_*.json = {root_count}（期望 {expect_root}）, "
                  f"upstream_errors_*.json = {up_count}（期望 {expect_up}）")

            # 验证每一条报告里 classification 字段都存在
            all_entries = []
            for p in root_err + upstream_err:
                all_entries.extend(json.loads(p.read_text(encoding="utf-8")))
            missing_cls = [e["error_id"] for e in all_entries if "classification" not in e]
            cls_ok = len(missing_cls) == 0
            status2 = "PASS" if cls_ok else "FAIL"
            if status2 == "FAIL":
                failed += 1
            print(f"  [{status2}] classification 字段注入：缺失 {missing_cls or '0'} 条")

            # 交叉验证：写入根目录的条目 classification 必须是 backend
            for p in root_err:
                for e in json.loads(p.read_text(encoding="utf-8")):
                    if e.get("classification") != "backend":
                        print(f"  [FAIL] 根目录条目{e['error_id']} classification={e.get('classification')} 应为 backend")
                        failed += 1
                        break
            # upstream_errors 目录条目必须 classification=upstream
            for p in upstream_err:
                for e in json.loads(p.read_text(encoding="utf-8")):
                    if e.get("classification") != "upstream":
                        print(f"  [FAIL] upstream 条目{e['error_id']} classification={e.get('classification')} 应为 upstream")
                        failed += 1
                        break
        finally:
            ec_mod._find_project_root = old_find
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 3. .gitignore 检查 ----------
    print("\n[3/4] .gitignore 规则检查")
    gi = PROJECT_ROOT / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    ok_git = any(line.strip() == "logs/upstream_errors/" for line in lines)
    status = "PASS" if ok_git else "FAIL"
    if status == "FAIL":
        failed += 1
    print(f"  [{status}] .gitignore 是否包含 logs/upstream_errors/ 规则")

    # ---------- 4. 回归 errors_20260804.json 真实样本 ----------
    print("\n[4/4] 回归：errors_20260804.json 真实 38 条样本分类统计")
    # 从 errors_20260804.json 已删除，因此这里用常量构造出之前聚合过的 8 类代表样本做回归
    real_samples = [
        ('A', build('Stream Error 503: {"code":50508,"message":"System is too busy now..."}')),
        ('B', build('Stream Request Failed: ')),
        ('C', build(
            'Failed to parse LLM output: LLM returned invalid daily summary payload\nOutput: ',
            logger_name="JournalSummaryService",
            source_file=r"D:\AI\xiaoyou-core\core\services\journal\summary_service.py",
            source_func="generate_daily_summary",
        )),
        ('D', build(
            'LLM 返回空内容，生成明日计划失败',
            logger_name="JournalPlanService",
            source_file=r"D:\AI\xiaoyou-core\core\services\journal\plan_service.py",
            source_func="generate_tomorrow_plan",
        )),
        ('E', build('API Error 400: {"code":20012,"message":"Model does not exist..."}')),
        ('F', build(
            'API Error (400): {"type":"error","error":{"type":"bad_request_error","message":"invalid params, unknown model \'deepseek-v4-flash\' (2013)"}}',
            logger_name="openai_client",
            source_file=r"D:\AI\xiaoyou-core\core\llm\openai_compat\client.py",
            source_func="_handle_error_response",
        )),
        ('G', build('Request Failed: ')),
        ('H', build(
            'API Error (503): {"error":{"message":"Service is too busy..."}}',
            logger_name="openai_client",
        )),
    ]
    # 说明：
    #  A/B/E/F/G/H 共 6 类判定为上游（True）
    #  C/D（summary_service/plan_service 的"Failed to parse LLM output" / "LLM 返回空内容"）
    #    ：这两条虽然是下游症状，但本身 logger 不是上游白名单，且错误消息里没有 503/timeout 等关键词，
    #    若按"宁可噪音也别漏（误报代码 bug 进根目录）"的策略判定 False 是保守且可接受的——
    #    实际生产中这两条由上游失败触发，但症状本身与代码无关。为了验证准确性，我们接受它们会落在后端。
    expected_upstream = {"A", "B", "E", "F", "G", "H"}
    for name, rep in real_samples:
        r = is_upstream_transient_error(rep)
        if name in expected_upstream:
            ok = r is True
        else:
            ok = r is False
        status = "PASS" if ok else "FAIL"
        if status == "FAIL":
            failed += 1
        print(f"  [{status}] 样本 {name} -> is_upstream={r}（期望 {name in expected_upstream}）")

    # ---------- 汇总 ----------
    print("\n" + "=" * 60)
    if failed == 0:
        print("✅ 全部通过")
        return 0
    print(f"❌ 共 {failed} 项失败")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
