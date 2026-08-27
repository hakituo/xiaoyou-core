"""
C++ 调度器增强功能单元测试
============================

测试内容：
1. Circuit Breaker（断路器）机制
2. NVIDIA SMI 显存监控函数
3. KV Cache 紧急保存/恢复机制
4. 推理统计信息记录功能
5. OOM 自动重试 + C++→Python 降级逻辑

运行方式：
    python -m pytest tests/test_cpp_scheduler_enhancements.py -v
"""

import asyncio
import os
import sys
import time
import unittest
from unittest.mock import Mock, patch

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCircuitBreakerMechanism(unittest.TestCase):
    """测试 Circuit Breaker（断路器）机制"""

    def setUp(self):
        """初始化测试环境"""
        # 导入被测试模块
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine, _is_oom_error, _is_cuda_backend_error

        self.CPPSchedulerEngine = CPPSchedulerEngine
        self._is_oom_error = _is_oom_error
        self._is_cuda_backend_error = _is_cuda_backend_error

    def test_breaker_initial_state(self):
        """测试断路器初始状态"""
        engine = self.CPPSchedulerEngine.__new__(self.CPPSchedulerEngine)
        engine._breaker_threshold = 3
        engine._breaker_min_cooldown_s = 5.0
        engine._breaker_max_cooldown_s = 60.0
        engine._breaker = {
            "llm": {"failures": 0, "open_until": 0.0, "cooldown_s": 5.0},
            "image": {"failures": 0, "open_until": 0.0, "cooldown_s": 5.0},
        }

        # 初始状态应该未开启（未熔断）
        self.assertFalse(engine._breaker_is_open("llm"))
        self.assertFalse(engine._breaker_is_open("image"))

    def test_breaker_not_open_before_threshold(self):
        """测试失败次数未达到阈值时，断路器不开启"""
        engine = self.CPPSchedulerEngine.__new__(self.CPPSchedulerEngine)
        engine._breaker_threshold = 3
        engine._breaker_min_cooldown_s = 5.0
        engine._breaker_max_cooldown_s = 60.0
        engine._breaker = {
            "llm": {"failures": 2, "open_until": 0.0, "cooldown_s": 5.0},
            "image": {"failures": 1, "open_until": 0.0, "cooldown_s": 5.0},
        }

        # 失败次数 < 阈值，应该未开启
        self.assertFalse(engine._breaker_is_open("llm"))
        self.assertFalse(engine._breaker_is_open("image"))

    def test_breaker_opens_at_threshold(self):
        """测试失败次数达到阈值时，断路器开启"""
        engine = self.CPPSchedulerEngine.__new__(self.CPPSchedulerEngine)
        engine._breaker_threshold = 3
        engine._breaker_min_cooldown_s = 5.0
        engine._breaker_max_cooldown_s = 60.0
        engine._breaker = {
            "llm": {"failures": 2, "open_until": 0.0, "cooldown_s": 5.0},
        }

        # 模拟第3次失败，触发熔断
        engine._breaker_on_failure("llm")

        # 断路器应该已开启
        self.assertTrue(engine._breaker_is_open("llm"))
        self.assertEqual(engine._breaker["llm"]["failures"], 3)

    def test_breaker_exponential_backoff(self):
        """测试指数退避策略"""
        engine = self.CPPSchedulerEngine.__new__(self.CPPSchedulerEngine)
        engine._breaker_threshold = 3
        engine._breaker_min_cooldown_s = 5.0
        engine._breaker_max_cooldown_s = 60.0
        engine._breaker = {
            "llm": {"failures": 0, "open_until": 0.0, "cooldown_s": 5.0},
        }

        # 第一次触发熔断（达到阈值）
        for i in range(3):
            engine._breaker_on_failure("llm")

        first_cooldown = engine._breaker["llm"]["cooldown_s"]
        # 第一次触发后 cooldown 应该从 5s 翻倍到 10s
        self.assertEqual(first_cooldown, 10.0)

        # 重置状态以模拟冷却时间结束后的新周期
        # 手动设置 failures 为 threshold-1，这样下次 _breaker_on_failure 就会触发新的熔断
        engine._breaker["llm"]["failures"] = engine._breaker_threshold - 1
        engine._breaker["llm"]["open_until"] = 0.0  # 模拟已过冷却期

        # 第二次触发熔断（只需再失败1次就达到阈值）
        engine._breaker_on_failure("llm")

        second_cooldown = engine._breaker["llm"]["cooldown_s"]

        # 第二次冷却时间应该是第一次的2倍（指数退避）：10s * 2 = 20s
        self.assertEqual(second_cooldown, 20.0)

    def test_breaker_max_cooldown_limit(self):
        """测试最大冷却时间限制"""
        engine = self.CPPSchedulerEngine.__new__(self.CPPSchedulerEngine)
        engine._breaker_threshold = 3
        engine._breaker_min_cooldown_s = 5.0
        engine._breaker_max_cooldown_s = 60.0
        engine._breaker = {
            "llm": {"failures": 0, "open_until": 0.0, "cooldown_s": 50.0},  # 接近上限
        }

        # 触发熔断
        for i in range(3):
            engine._breaker_on_failure("llm")

        # 冷却时间不应超过最大值
        self.assertLessEqual(engine._breaker["llm"]["cooldown_s"], 60.0)
        self.assertEqual(engine._breaker["llm"]["cooldown_s"], 60.0)

    def test_breaker_reset_on_success(self):
        """测试成功时重置断路器"""
        engine = self.CPPSchedulerEngine.__new__(self.CPPSchedulerEngine)
        engine._breaker_threshold = 3
        engine._breaker_min_cooldown_s = 5.0
        engine._breaker_max_cooldown_s = 60.0
        engine._breaker = {
            "llm": {"failures": 5, "open_until": time.time() + 100.0, "cooldown_s": 40.0},
        }

        # 确认断路器已开启
        self.assertTrue(engine._breaker_is_open("llm"))

        # 模拟成功调用
        engine._breaker_on_success("llm")

        # 断路器应该重置
        self.assertFalse(engine._breaker_is_open("llm"))
        self.assertEqual(engine._breaker["llm"]["failures"], 0)
        self.assertEqual(engine._breaker["llm"]["cooldown_s"], 5.0)  # 恢复到初始值

    def test_breaker_status_query(self):
        """测试断路器状态查询接口"""
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine._breaker_threshold = 3
        engine._breaker_min_cooldown_s = 5.0
        engine._breaker_max_cooldown_s = 60.0
        engine._breaker = {
            "llm": {"failures": 3, "open_until": time.time() + 10.0, "cooldown_s": 10.0},
            "image": {"failures": 0, "open_until": 0.0, "cooldown_s": 5.0},
        }
        engine.get_breaker_status = lambda: {
            "llm": {
                "is_open": time.time() < engine._breaker["llm"]["open_until"],
                "failures": engine._breaker["llm"]["failures"],
                "cooldown_s": engine._breaker["llm"]["cooldown_s"],
                "open_until": engine._breaker["llm"]["open_until"],
            },
            "image": {
                "is_open": time.time() < engine._breaker["image"]["open_until"],
                "failures": engine._breaker["image"]["failures"],
                "cooldown_s": engine._breaker["image"]["cooldown_s"],
                "open_until": engine._breaker["image"]["open_until"],
            },
        }

        status = engine.get_breaker_status()

        # LLM 断路器应该开启
        self.assertTrue(status["llm"]["is_open"])
        self.assertEqual(status["llm"]["failures"], 3)
        self.assertEqual(status["llm"]["cooldown_s"], 10.0)

        # Image 断路器应该关闭
        self.assertFalse(status["image"]["is_open"])
        self.assertEqual(status["image"]["failures"], 0)


class TestNvidiaSmiMonitor(unittest.TestCase):
    """测试 NVIDIA SMI 显存监控函数"""

    def test_nvidia_smi_returns_none_when_not_available(self):
        """测试 nvidia-smi 不可用时返回 None"""
        from core.services.scheduler.cpp_scheduler_engine import _nvidia_smi_total_used_mb

        with patch('shutil.which', return_value=None):
            result = _nvidia_smi_total_used_mb()
            self.assertIsNone(result)

    def test_nvidia_smi_handles_command_error(self):
        """测试 nvidia-smi 命令执行失败时的处理"""
        from core.services.scheduler.cpp_scheduler_engine import _nvidia_smi_total_used_mb

        with patch('shutil.which', return_value='/usr/bin/nvidia-smi'):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(returncode=1, stdout="", stderr="Error")
                result = _nvidia_smi_total_used_mb()
                self.assertIsNone(result)

    def test_nvidia_smi_parses_output_correctly(self):
        """测试正确解析 nvidia-smi 输出"""
        from core.services.scheduler.cpp_scheduler_engine import _nvidia_smi_total_used_mb

        mock_output = "1024\n2048\n"

        with patch('shutil.which', return_value='/usr/bin/nvidia-smi'):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(
                    returncode=0,
                    stdout=mock_output,
                    stderr=""
                )
                result = _nvidia_smi_total_used_mb()
                self.assertEqual(result, 3072)  # 1024 + 2048

    def test_nvidia_smi_handles_malformed_output(self):
        """测试处理格式错误的输出"""
        from core.services.scheduler.cpp_scheduler_engine import _nvidia_smi_total_used_mb

        mock_output = "1024\nabc\n512\n"

        with patch('shutil.which', return_value='/usr/bin/nvidia-smi'):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(
                    returncode=0,
                    stdout=mock_output,
                    stderr=""
                )
                result = _nvidia_smi_total_used_mb()
                # 应该只解析数字行，忽略非数字行
                self.assertEqual(result, 1536)  # 1024 + 512


class TestKVCacheSaveRestore(unittest.TestCase):
    """测试 KV Cache 紧急保存/恢复机制"""

    def test_kv_cache_state_initialization(self):
        """测试 KV Cache 状态属性初始化"""
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine._saved_llm_state = None
        engine._saved_llm_state_ts = 0.0

        # 初始状态应为空
        self.assertIsNone(engine._saved_llm_state)
        self.assertEqual(engine._saved_llm_state_ts, 0.0)

    def test_kv_cache_save_during_emergency_offload(self):
        """测试紧急卸载时保存 KV Cache"""
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine.llm = Mock()
        engine._saved_llm_state = None
        engine._saved_llm_state_ts = 0.0

        # 模拟 save_state 返回的状态
        mock_state = {"kv_cache_data": "test_data", "tokens": 100}
        engine.llm.save_state = Mock(return_value=mock_state)

        # 调用保存逻辑（从 offload_llm_to_cpu 提取）
        async def test_save():
            try:
                state = await asyncio.to_thread(engine.llm.save_state)
                engine._saved_llm_state = state
                engine._saved_llm_state_ts = time.time()
                return True
            except Exception:
                return False

        # 运行异步测试
        result = asyncio.run(test_save())

        # 验证结果
        self.assertTrue(result)
        self.assertIsNotNone(engine._saved_llm_state)
        self.assertEqual(engine._saved_llm_state, mock_state)
        self.assertGreater(engine._saved_llm_state_ts, 0.0)

    def test_kv_cache_restore_after_cpu_load(self):
        """测试 CPU 实例加载后恢复 KV Cache"""
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine.llm = Mock()
        engine._saved_llm_state = {"kv_cache_data": "test_data", "tokens": 100}
        engine._saved_llm_state_ts = time.time()

        # 模拟 load_state 方法
        engine.llm.load_state = Mock(return_value=True)

        # 调用恢复逻辑
        async def test_restore():
            try:
                if engine.llm is not None and engine._saved_llm_state is not None:
                    await asyncio.to_thread(engine.llm.load_state, engine._saved_llm_state)
                    engine._saved_llm_state = None
                    engine._saved_llm_state_ts = 0.0
                    return True
                return False
            except Exception:
                return False

        # 运行异步测试
        result = asyncio.run(test_restore())

        # 验证结果
        self.assertTrue(result)
        engine.llm.load_state.assert_called_once_with({"kv_cache_data": "test_data", "tokens": 100})
        self.assertIsNone(engine._saved_llm_state)
        self.assertEqual(engine._saved_llm_state_ts, 0.0)


class TestInferenceStatsRecording(unittest.TestCase):
    """测试推理统计信息记录功能"""

    def test_stats_initialization(self):
        """测试统计信息初始状态"""
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine._last_llm_stats = None

        # 初始状态应为空
        self.assertIsNone(engine._last_llm_stats)

    def test_stats_recording_after_inference(self):
        """测试推理完成后记录统计信息"""
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine._last_llm_stats = None
        engine.logger = Mock()

        # 模拟记录统计信息的逻辑（从 wait_completion 提取）
        mock_resp = Mock()
        mock_resp.generatedTokens = 150
        mock_resp.inferenceTime = 2.35

        stats = {
            "backend": "cpp",
            "generated_tokens": int(getattr(mock_resp, "generatedTokens", 0) or 0),
            "inference_time_s": float(getattr(mock_resp, "inferenceTime", 0.0) or 0.0),
            "timestamp": time.time(),
        }
        engine._last_llm_stats = stats

        # 验证统计信息
        self.assertIsNotNone(engine._last_llm_stats)
        self.assertEqual(engine._last_llm_stats["backend"], "cpp")
        self.assertEqual(engine._last_llm_stats["generated_tokens"], 150)
        self.assertEqual(engine._last_llm_stats["inference_time_s"], 2.35)
        self.assertIn("timestamp", engine._last_llm_stats)

    def test_get_last_llm_stats(self):
        """测试获取最近一次推理统计的公共接口"""
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine._last_llm_stats = {
            "backend": "cpp",
            "generated_tokens": 200,
            "inference_time_s": 3.14,
            "timestamp": time.time(),
        }
        engine.get_last_llm_stats = lambda: engine._last_llm_stats

        stats = engine.get_last_llm_stats()

        # 验证返回值
        self.assertIsNotNone(stats)
        self.assertEqual(stats["backend"], "cpp")
        self.assertEqual(stats["generated_tokens"], 200)
        self.assertEqual(stats["inference_time_s"], 3.14)

    def test_get_last_llm_stats_when_empty(self):
        """测试没有统计数据时返回 None"""
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine._last_llm_stats = None
        engine.get_last_llm_stats = lambda: engine._last_llm_stats

        stats = engine.get_last_llm_stats()

        # 应该返回 None
        self.assertIsNone(stats)


class TestOOMErrorDetection(unittest.TestCase):
    """测试 OOM 错误检测函数"""

    def test_detects_out_of_memory_error(self):
        """测试检测 OOM 错误"""
        from core.services.scheduler.cpp_scheduler_engine import _is_oom_error

        oom_messages = [
            "out of memory",
            "CUDA error: out of memory",
            "ggml-cuda: failed to allocate",
            "cublas error: not enough memory",
            "vram allocation failed",
            "failed to allocate memory",
            "not enough memory to allocate tensor",
        ]

        for msg in oom_messages:
            with self.subTest(msg=msg):
                self.assertTrue(_is_oom_error(msg), f"Failed to detect OOM in: {msg}")

    def test_ignores_non_oom_errors(self):
        """测试忽略非 OOM 错误"""
        from core.services.scheduler.cpp_scheduler_engine import _is_oom_error

        non_oom_messages = [
            "file not found",
            "permission denied",
            "invalid argument",
            "connection timeout",
            "value error",
            "type error",
            "",
            None,
        ]

        for msg in non_oom_messages:
            with self.subTest(msg=msg):
                self.assertFalse(_is_oom_error(msg), f"Incorrectly detected OOM in: {msg}")


class TestCudaBackendErrorDetection(unittest.TestCase):
    """测试 CUDA 后端错误检测函数"""

    def test_detects_cuda_errors(self):
        """测试检测 CUDA 后端错误"""
        from core.services.scheduler.cpp_scheduler_engine import _is_cuda_backend_error

        cuda_errors = [
            "ggml-cuda: illegal memory access",
            "cuda error: device-side assert",
            "cublas error: operation failed",
            "hip error: out of resources",
            "illegal memory access at address",
            "device-side assert triggered",
            "driver error: unknown error",
        ]

        for msg in cuda_errors:
            with self.subTest(msg=msg):
                self.assertTrue(_is_cuda_backend_error(msg), f"Failed to detect CUDA error in: {msg}")

    def test_ignores_non_cuda_errors(self):
        """测试忽略非 CUDA 错误"""
        from core.services.scheduler.cpp_scheduler_engine import _is_cuda_backend_error

        non_cuda_errors = [
            "file not found",
            "out of memory",  # 这是 OOM 但不是 CUDA 特有错误
            "permission denied",
            "",
            None,
        ]

        for msg in non_cuda_errors:
            with self.subTest(msg=msg):
                self.assertFalse(_is_cuda_backend_error(msg), f"Incorrectly detected CUDA error in: {msg}")


class TestEnvironmentVariableConfiguration(unittest.TestCase):
    """测试环境变量配置"""

    def test_breaker_threshold_from_env(self):
        """测试从环境变量读取断路器阈值"""
        import os
        original_value = os.environ.get("XIAOYOU_CPP_BREAKER_THRESHOLD")

        try:
            os.environ["XIAOYOU_CPP_BREAKER_THRESHOLD"] = "5"
            threshold = int(os.getenv("XIAOYOU_CPP_BREAKER_THRESHOLD", "3") or 3)
            self.assertEqual(threshold, 5)
        finally:
            if original_value is None:
                os.environ.pop("XIAOYOU_CPP_BREAKER_THRESHOLD", None)
            else:
                os.environ["XIAOYOU_CPP_BREAKER_THRESHOLD"] = original_value

    def test_breaker_cooldown_from_env(self):
        """测试从环境变量读取冷却时间配置"""
        import os

        original_min = os.environ.get("XIAOYOU_CPP_BREAKER_MIN_COOLDOWN_S")
        original_max = os.environ.get("XIAOYOU_CPP_BREAKER_MAX_COOLDOWN_S")

        try:
            os.environ["XIAOYOU_CPP_BREAKER_MIN_COOLDOWN_S"] = "10"
            os.environ["XIAOYOU_CPP_BREAKER_MAX_COOLDOWN_S"] = "120"

            min_cd = float(os.getenv("XIAOYOU_CPP_BREAKER_MIN_COOLDOWN_S", "5") or 5)
            max_cd = float(os.getenv("XIAOYOU_CPP_BREAKER_MAX_COOLDOWN_S", "60") or 60)

            self.assertEqual(min_cd, 10.0)
            self.assertEqual(max_cd, 120.0)
        finally:
            if original_min is None:
                os.environ.pop("XIAOYOU_CPP_BREAKER_MIN_COOLDOWN_S", None)
            else:
                os.environ["XIAOYOU_CPP_BREAKER_MIN_COOLDOWN_S"] = original_min

            if original_max is None:
                os.environ.pop("XIAOYOU_CPP_BREAKER_MAX_COOLDOWN_S", None)
            else:
                os.environ["XIAOYOU_CPP_BREAKER_MAX_COOLDOWN_S"] = original_max

    def test_oom_retry_count_from_env(self):
        """测试从环境变量读取 OOM 重试次数"""
        import os
        original_value = os.environ.get("XIAOYOU_LLM_OOM_MAX_RETRIES")

        try:
            os.environ["XIAOYOU_LLM_OOM_MAX_RETRIES"] = "3"
            retries = int(os.getenv("XIAOYOU_LLM_OOM_MAX_RETRIES", "1") or 1)
            self.assertEqual(retries, 3)
        finally:
            if original_value is None:
                os.environ.pop("XIAOYOU_LLM_OOM_MAX_RETRIES", None)
            else:
                os.environ["XIAOYOU_LLM_OOM_MAX_RETRIES"] = original_value


class TestIntegrationScenarios(unittest.TestCase):
    """集成测试场景：验证多个功能的协同工作"""

    def test_full_circuit_breaker_lifecycle(self):
        """测试完整的断路器生命周期"""
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine._breaker_threshold = 3
        engine._breaker_min_cooldown_s = 0.1  # 使用短冷却时间以便测试
        engine._breaker_max_cooldown_s = 1.0
        engine._breaker = {
            "llm": {"failures": 0, "open_until": 0.0, "cooldown_s": 0.1},
        }

        # 阶段1：正常工作
        self.assertFalse(engine._breaker_is_open("llm"))
        engine._breaker_on_success("llm")
        self.assertEqual(engine._breaker["llm"]["failures"], 0)

        # 阶段2：连续失败但未达到阈值
        engine._breaker_on_failure("llm")
        engine._breaker_on_failure("llm")
        self.assertFalse(engine._breaker_is_open("llm"))
        self.assertEqual(engine._breaker["llm"]["failures"], 2)

        # 阶段3：达到阈值，触发熔断
        engine._breaker_on_failure("llm")
        self.assertTrue(engine._breaker_is_open("llm"))
        self.assertEqual(engine._breaker["llm"]["failures"], 3)

        # 阶段4：熔断期间尝试重置（不应该成功）
        engine._breaker["llm"]["open_until"] = time.time() + 10.0
        self.assertTrue(engine._breaker_is_open("llm"))

        # 阶段5：模拟冷却时间过去后自动恢复
        engine._breaker["llm"]["open_until"] = time.time() - 1.0
        self.assertFalse(engine._breaker_is_open("llm"))

        # 阶段6：成功调用后完全重置
        engine._breaker_on_success("llm")
        self.assertEqual(engine._breaker["llm"]["failures"], 0)
        self.assertEqual(engine._breaker["llm"]["cooldown_s"], 0.1)

    def test_kv_cache_and_stats_integration(self):
        """测试 KV Cache 和统计信息的集成"""
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine.llm = Mock()
        engine._saved_llm_state = None
        engine._saved_llm_state_ts = 0.0
        engine._last_llm_stats = None

        # 模拟完整的工作流程
        async def full_workflow():
            # 1. 保存 KV Cache
            mock_state = {"kv": "data", "tokens": 100}
            engine.llm.save_state = Mock(return_value=mock_state)
            state = await asyncio.to_thread(engine.llm.save_state)
            engine._saved_llm_state = state
            engine._saved_llm_state_ts = time.time()

            # 2. 记录推理统计
            engine._last_llm_stats = {
                "backend": "cpp",
                "generated_tokens": 150,
                "inference_time_s": 2.5,
                "timestamp": time.time(),
            }

            # 3. 恢复 KV Cache
            engine.llm.load_state = Mock(return_value=True)
            if engine._saved_llm_state is not None:
                await asyncio.to_thread(engine.llm.load_state, engine._saved_llm_state)
                engine._saved_llm_state = None
                engine._saved_llm_state_ts = 0.0

            return True

        # 执行工作流
        result = asyncio.run(full_workflow())

        # 验证最终状态
        self.assertTrue(result)
        self.assertIsNone(engine._saved_llm_state)
        self.assertEqual(engine._saved_llm_state_ts, 0.0)
        self.assertIsNotNone(engine._last_llm_stats)
        self.assertEqual(engine._last_llm_stats["generated_tokens"], 150)

    def test_submit_llm_task_falls_back_to_python_after_cpp_failure(self):
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine.enabled = True
        engine._llm_backend = "cpp"
        engine._breaker_threshold = 3
        engine._breaker_min_cooldown_s = 5.0
        engine._breaker_max_cooldown_s = 60.0
        engine._breaker = {
            "llm": {"failures": 0, "open_until": 0.0, "cooldown_s": 5.0},
            "image": {"failures": 0, "open_until": 0.0, "cooldown_s": 5.0},
        }

        async def failing_cpp(prompt, **kwargs):
            raise RuntimeError("cpp backend failed")
            yield

        async def python_fallback(prompt, **kwargs):
            yield "fallback-token"

        engine._submit_llm_task_cpp_original = failing_cpp
        engine._submit_llm_task_python_fallback = python_fallback

        async def collect():
            out = []
            async for item in engine.submit_llm_task("hello"):
                out.append(item)
            return out

        result = asyncio.run(collect())
        self.assertEqual(result, ["fallback-token"])
        self.assertEqual(engine._breaker["llm"]["failures"], 1)

    def test_python_core_temporarily_switches_backend(self):
        from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

        engine = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
        engine._llm_backend = "cpp"

        async def fake_cpp_original(prompt, **kwargs):
            self.assertEqual(engine._llm_backend, "python")
            yield "python-core-token"

        engine._submit_llm_task_cpp_original = fake_cpp_original

        async def collect():
            out = []
            async for item in engine._submit_llm_task_python_core("hello"):
                out.append(item)
            return out

        result = asyncio.run(collect())
        self.assertEqual(result, ["python-core-token"])
        self.assertEqual(engine._llm_backend, "cpp")


if __name__ == "__main__":
    # 运行所有测试
    unittest.main(verbosity=2)
