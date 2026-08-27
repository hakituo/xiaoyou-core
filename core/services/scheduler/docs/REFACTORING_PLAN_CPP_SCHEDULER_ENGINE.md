# cpp_scheduler_engine.py 解耦拆分规划

**规划日期**: 2026-04-26
**规划版本**: 1.0
**规划者**: Xiaoyou Core Team

## 一、现状分析

### 1.1 文件规模
- **文件路径**: `core/services/scheduler/cpp_scheduler_engine.py`
- **代码行数**: 2608 行
- **职责数量**: 10+ 个主要职责

### 1.2 当前职责清单

| 序号 | 职责 | 代码行数估算 | 复杂度 | 说明 |
|------|------|-------------|--------|------|
| 1 | 调度器生命周期管理 | ~200 行 | 中 | 初始化、启动、停止 C++ 调度器 |
| 2 | LLM 模型管理 | ~400 行 | 高 | Python/C++ LLM 加载、卸载、切换 |
| 3 | GPU 资源管理 | ~500 行 | 高 | GPU 显存管理、设备切换、offload/restore |
| 4 | KV Cache 管理 | ~200 行 | 中 | KV Cache 的保存、恢复、迁移 |
| 5 | 推理任务提交 | ~600 行 | 高 | LLM 推理任务的提交、执行、重试、降级 |
| 6 | Circuit Breaker 机制 | ~100 行 | 中 | 断路器模式，防止 C++ 后端雪崩 |
| 7 | 生物系统管理 | ~100 行 | 低 | 生物系统的状态管理 |
| 8 | 健康检查和重启 | ~200 行 | 中 | GPU 工作器健康检查、调度器重启 |
| 9 | 状态查询 | ~150 行 | 低 | 获取调度器和生物系统的状态 |
| 10 | 辅助工具函数 | ~158 行 | 低 | 错误判断、补丁函数等 |

### 1.3 现有模块分析

项目中已经存在以下模块，但 **未被 cpp_scheduler_engine.py 使用**：

| 模块文件 | 职责 | 状态 |
|---------|------|------|
| `llm_model_manager.py` | LLM 模型管理（加载、卸载、配置） | ✅ 已存在，未使用 |
| `gpu_resource_manager.py` | GPU 资源管理（显存管理、设备切换） | ✅ 已存在，未使用 |
| `kv_cache_manager.py` | KV Cache 紧急保存/恢复 | ✅ 已存在，已使用 |
| `circuit_breaker.py` | 断路器机制 | ✅ 已存在，已使用 |
| `cpp_llm_handler.py` | C++ 后端 LLM 执行 | ✅ 已存在，已使用 |
| `python_llm_handler.py` | Python 后端 LLM 执行 | ✅ 已存在，已使用 |
| `inference_stats.py` | 推理统计信息 | ✅ 已存在，已使用 |
| `nvidia_smi_monitor.py` | NVIDIA SMI 监控 | ✅ 已存在，已使用 |

### 1.4 核心问题

1. **职责过多**: 单个文件承担了 10+ 个职责，违反单一职责原则
2. **代码重复**: `llm_model_manager.py` 和 `gpu_resource_manager.py` 中的代码与 `cpp_scheduler_engine.py` 中的代码重复
3. **难以维护**: 2608 行代码难以理解和维护
4. **难以测试**: 大量职责耦合在一起，难以进行单元测试
5. **难以扩展**: 新功能难以添加，容易引入 bug

## 二、拆分目标

### 2.1 主要目标

1. **单一职责**: 每个模块只负责一个职责
2. **低耦合**: 模块之间依赖关系清晰，易于替换
3. **高内聚**: 相关功能聚合在一起，易于理解
4. **可测试**: 每个模块可以独立测试
5. **可扩展**: 新功能可以轻松添加

### 2.2 拆分原则

1. **渐进式拆分**: 先拆分低风险模块，再拆分高风险模块
2. **保持兼容**: 拆分后保持 API 兼容性
3. **充分测试**: 每次拆分后进行充分测试
4. **文档同步**: 同步更新技术文档

## 三、拆分方案

### 3.1 模块拆分规划

```
core/services/scheduler/
├── cpp_scheduler_engine.py          # 主引擎（精简后，~300 行）
│   ├── CPPSchedulerEngine           # 主类
│   ├── get_scheduler_engine()       # 全局实例获取
│
├── llm_model_manager.py             # LLM 模型管理（已存在，需整合）
│   ├── LLMModelManager              # 模型管理器
│   ├── setup_python_llm()           # Python LLM 加载
│   ├── _build_cpp_llm_config()      # C++ LLM 配置构建
│   └── _patch_llama_cpp_internals() # llama_cpp 补丁
│
├── gpu_resource_manager.py          # GPU 资源管理（已存在，需整合）
│   ├── GPUResourceManager           # GPU 资源管理器
│   ├── offload_llm_to_cpu()         # LLM 迁移到 CPU
│   ├── restore_llm_to_gpu()         # LLM 回迁到 GPU
│   ├── offload_kv_cache_to_cpu()    # KV Cache 迁移到 CPU
│   └── restore_kv_cache_to_gpu()    # KV Cache 回迁到 GPU
│
├── scheduler_lifecycle.py           # 调度器生命周期管理（新建）
│   ├── SchedulerLifecycle           # 生命周期管理器
│   ├── initialize()                 # 初始化调度器
│   ├── start()                      # 启动调度器
│   ├── stop()                       # 停止调度器
│   └── get_status()                 # 获取状态
│
├── inference_executor.py            # 推理任务执行器（新建）
│   ├── InferenceExecutor            # 推理执行器
│   ├── submit_llm_task()            # 提交 LLM 任务
│   ├── _submit_llm_task_cpp()       # C++ 后端推理
│   ├── _submit_llm_task_python()    # Python 后端推理
│   └── _submit_llm_task_with_retry() # 带重试的推理
│
├── health_monitor.py                # 健康检查和重启（新建）
│   ├── HealthMonitor                # 健康监控器
│   ├── health_check_gpu_worker()    # GPU 工作器健康检查
│   └── restart_scheduler()          # 重启调度器
│
├── bio_system_manager.py            # 生物系统管理（新建）
│   ├── BioSystemManager             # 生物系统管理器
│   ├── get_biological_system()      # 获取生物系统
│   └── apply_bio_before_infer()     # 推理前应用生物系统
│
├── error_utils.py                   # 错误工具（已存在）
│   ├── is_oom_error()               # OOM 错误判断
│   ├── is_cuda_backend_error()      # CUDA 错误判断
│   └── friendly_llm_error()         # 友好错误提示
│
├── circuit_breaker.py               # 断路器（已存在）
├── kv_cache_manager.py              # KV Cache 管理（已存在）
├── cpp_llm_handler.py               # C++ LLM 处理器（已存在）
├── python_llm_handler.py            # Python LLM 处理器（已存在）
├── inference_stats.py               # 推理统计（已存在）
└── nvidia_smi_monitor.py            # NVIDIA SMI 监控（已存在）
```

### 3.2 详细拆分计划

#### 阶段 1: 低风险拆分（预计 1-2 天）

**目标**: 拆分独立性强、风险低的功能

| 任务 | 源代码位置 | 目标模块 | 风险等级 | 说明 |
|------|-----------|---------|---------|------|
| 1.1 | 辅助工具函数 (L50-128) | `error_utils.py` | 低 | 已存在，只需迁移引用 |
| 1.2 | 健康检查和重启 (L1982-2097) | `health_monitor.py` | 低 | 独立功能，无外部依赖 |
| 1.3 | 生物系统管理 (L2273-2329) | `bio_system_manager.py` | 低 | 独立功能，无外部依赖 |

#### 阶段 2: 中风险拆分（预计 2-3 天）

**目标**: 拆分有依赖但接口清晰的功能

| 任务 | 源代码位置 | 目标模块 | 风险等级 | 说明 |
|------|-----------|---------|---------|------|
| 2.1 | 调度器生命周期 (L1390-1468, L1919-1981) | `scheduler_lifecycle.py` | 中 | 需要协调多个组件 |
| 2.2 | 状态查询 (L1469-1550) | `scheduler_lifecycle.py` | 中 | 依赖调度器状态 |

#### 阶段 3: 高风险拆分（预计 3-5 天）

**目标**: 拆分核心功能，需要充分测试

| 任务 | 源代码位置 | 目标模块 | 风险等级 | 说明 |
|------|-----------|---------|---------|------|
| 3.1 | LLM 模型管理 (L1552-1918, L463-608) | `llm_model_manager.py` | 高 | 核心功能，需要充分测试 |
| 3.2 | GPU 资源管理 (L621-1000, L1124-1389) | `gpu_resource_manager.py` | 高 | 核心功能，需要充分测试 |
| 3.3 | 推理任务执行 (L2142-2591) | `inference_executor.py` | 高 | 核心功能，需要充分测试 |

### 3.3 模块接口设计

#### 3.3.1 CPPSchedulerEngine（主引擎）

```python
class CPPSchedulerEngine:
    """C++ 调度引擎主类（精简后）"""
    
    def __init__(self):
        self.scheduler = None
        self.bio_system = None
        self.enabled = False
        self._started = False
        
        # 组合各个管理器
        self.model_manager = LLMModelManager()
        self.gpu_manager = GPUResourceManager(self.model_manager)
        self.lifecycle = SchedulerLifecycle(self)
        self.inference_executor = InferenceExecutor(self)
        self.health_monitor = HealthMonitor(self)
        self.bio_system_manager = BioSystemManager(self)
    
    # 代理方法，保持 API 兼容性
    async def start(self, **kwargs):
        return await self.lifecycle.start(**kwargs)
    
    async def stop(self):
        return await self.lifecycle.stop()
    
    async def submit_llm_task(self, prompt: str, **kwargs):
        async for token in self.inference_executor.submit_llm_task(prompt, **kwargs):
            yield token
    
    async def offload_llm_to_cpu(self, urgent: bool = False):
        return await self.gpu_manager.offload_llm_to_cpu(urgent)
    
    async def restore_llm_to_gpu(self):
        return await self.gpu_manager.restore_llm_to_gpu()
    
    def get_status(self):
        return self.lifecycle.get_status()
    
    def get_biological_system(self):
        return self.bio_system_manager.get_biological_system()
```

#### 3.3.2 LLMModelManager（模型管理器）

```python
class LLMModelManager:
    """LLM 模型管理器"""
    
    def __init__(self):
        self.llm = None
        self._gpu_config = None
        self._llm_backend = None
        self._llm_setup_lock = asyncio.Lock()
        self._llm_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="LLMWorker")
    
    def setup_python_llm(self, config: Dict[str, Any], return_instance: bool = False):
        """初始化 Python 侧 Llama 实例"""
        pass
    
    def _build_cpp_llm_config(self, config: Dict[str, Any]) -> LLMModelConfig:
        """构建 C++ LLM 配置"""
        pass
    
    async def reload_llm(self):
        """重新加载 LLM"""
        pass
    
    async def unload_llm(self):
        """卸载 LLM"""
        pass
```

#### 3.3.3 GPUResourceManager（GPU 资源管理器）

```python
class GPUResourceManager:
    """GPU 资源管理器"""
    
    def __init__(self, model_manager: LLMModelManager):
        self.model_manager = model_manager
    
    async def offload_llm_to_cpu(self, urgent: bool = False):
        """将 LLM 迁移到 CPU"""
        pass
    
    async def restore_llm_to_gpu(self):
        """将 LLM 回迁到 GPU"""
        pass
    
    async def offload_kv_cache_to_cpu(self):
        """将 KV Cache 迁移到 CPU"""
        pass
    
    async def restore_kv_cache_to_gpu(self):
        """将 KV Cache 回迁到 GPU"""
        pass
```

#### 3.3.4 SchedulerLifecycle（调度器生命周期）

```python
class SchedulerLifecycle:
    """调度器生命周期管理器"""
    
    def __init__(self, engine: CPPSchedulerEngine):
        self.engine = engine
    
    async def start(self, worker_count: int = 4, gpu_config: Optional[Dict] = None, preload_llm: bool = False):
        """启动调度器"""
        pass
    
    async def stop(self):
        """停止调度器"""
        pass
    
    def get_status(self) -> Dict[str, Any]:
        """获取调度器状态"""
        pass
```

#### 3.3.5 InferenceExecutor（推理执行器）

```python
class InferenceExecutor:
    """推理任务执行器"""
    
    def __init__(self, engine: CPPSchedulerEngine):
        self.engine = engine
    
    async def submit_llm_task(self, prompt: str, **kwargs) -> AsyncGenerator:
        """提交 LLM 任务"""
        pass
    
    async def _submit_llm_task_cpp(self, prompt: str, **kwargs) -> AsyncGenerator:
        """C++ 后端推理"""
        pass
    
    async def _submit_llm_task_python(self, prompt: str, **kwargs) -> AsyncGenerator:
        """Python 后端推理"""
        pass
```

#### 3.3.6 HealthMonitor（健康监控器）

```python
class HealthMonitor:
    """健康监控器"""
    
    def __init__(self, engine: CPPSchedulerEngine):
        self.engine = engine
    
    async def health_check_gpu_worker(self) -> bool:
        """GPU 工作器健康检查"""
        pass
    
    async def restart_scheduler(self) -> bool:
        """重启调度器"""
        pass
```

#### 3.3.7 BioSystemManager（生物系统管理器）

```python
class BioSystemManager:
    """生物系统管理器"""
    
    def __init__(self, engine: CPPSchedulerEngine):
        self.engine = engine
    
    def get_biological_system(self):
        """获取生物系统"""
        return self.engine.bio_system
    
    async def apply_bio_before_infer(self, prompt_text: str):
        """推理前应用生物系统"""
        pass
```

## 四、实施步骤

### 4.1 准备阶段

1. **创建测试脚本**: `tests/test_cpp_scheduler_refactoring.py`
   - 测试调度器初始化
   - 测试 LLM 加载/卸载
   - 测试 GPU 资源管理
   - 测试推理任务提交
   - 测试健康检查

2. **创建备份**: 复制 `cpp_scheduler_engine.py` 为 `cpp_scheduler_engine.py.backup`

3. **更新文档**: 在 `PROJECT_TECHNICAL_REFERENCE.md` 中记录拆分计划

### 4.2 执行阶段

#### 阶段 1: 低风险拆分

**步骤 1.1: 迁移错误工具函数**

```bash
# 1. 确认 error_utils.py 中已包含所需函数
# 2. 在 cpp_scheduler_engine.py 中更新导入
# 3. 删除 cpp_scheduler_engine.py 中的重复代码
# 4. 运行测试
```

**步骤 1.2: 创建 health_monitor.py**

```python
# core/services/scheduler/health_monitor.py

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cpp_scheduler_engine import CPPSchedulerEngine

logger = logging.getLogger(__name__)


class HealthMonitor:
    """健康监控器"""
    
    def __init__(self, engine: "CPPSchedulerEngine"):
        self.engine = engine
    
    async def health_check_gpu_worker(self) -> bool:
        """GPU 工作器健康检查"""
        if not self.engine.scheduler or not self.engine._gpu_worker_ready:
            logger.warning("健康检查：调度器或GPU工作器未就绪")
            return False
        
        try:
            logger.info("提交健康检查任务到C++调度器...")
            
            from .scheduler_wrapper import scheduler_py
            
            req = scheduler_py.LLMInferenceRequest()
            req.prompt = "Hi"
            req.maxTokens = 4
            req.temperature = 0.1
            req.streamOutput = False
            
            task = scheduler_py.LLMTask(req)
            self.engine.scheduler.submitTask(task)
            
            start_time = time.time()
            max_wait = 15.0
            
            while time.time() - start_time < max_wait:
                status = task.getStatus()
                if status == scheduler_py.TaskStatus.COMPLETED:
                    resp = task.getResponse()
                    if resp.success and resp.generatedText:
                        logger.info(f"C++ GPU健康检查通过，响应: {resp.generatedText[:20]}")
                        return True
                    else:
                        logger.error(f"C++ GPU健康检查失败: {resp.errorMessage}")
                        return False
                elif status == scheduler_py.TaskStatus.FAILED:
                    resp = task.getResponse()
                    logger.error(f"C++ GPU健康检查任务失败: {resp.errorMessage}")
                    return False
                
                await asyncio.sleep(0.1)
            
            logger.error(f"C++ GPU健康检查超时（{max_wait}秒）")
            try:
                task_id = task.getTaskId()
                await asyncio.to_thread(self.engine.scheduler.cancelTask, task_id)
            except Exception:
                pass
            return False
        
        except Exception as e:
            logger.error(f"C++ GPU健康检查异常: {e}")
            return False
    
    async def restart_scheduler(self) -> bool:
        """重启调度器"""
        try:
            logger.info("开始重启C++调度器...")
            
            saved_config = None
            if self.engine._gpu_config:
                saved_config = dict(self.engine._gpu_config)
            
            logger.info("停止当前C++调度器...")
            await self.engine.stop()
            
            try:
                import gc
                import torch
                
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                    logger.info("GPU缓存已清理")
            except Exception as e:
                logger.warning(f"清理GPU缓存时出错: {e}")
            
            await asyncio.sleep(2.0)
            
            logger.info("重新启动C++调度器...")
            await self.engine.start()
            
            if saved_config and self.engine._llm_backend == "cpp":
                logger.info("重新初始化GPU工作器...")
                await asyncio.to_thread(self.engine._setup_gpu_worker, saved_config)
            
            if self.engine.scheduler and self.engine._started:
                logger.info("C++调度器重启成功")
                return True
            else:
                logger.error("C++调度器重启后状态异常")
                return False
        
        except Exception as e:
            logger.error(f"重启C++调度器失败: {e}")
            return False
```

**步骤 1.3: 创建 bio_system_manager.py**

```python
# core/services/scheduler/bio_system_manager.py

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cpp_scheduler_engine import CPPSchedulerEngine

logger = logging.getLogger(__name__)


class BioSystemManager:
    """生物系统管理器"""
    
    def __init__(self, engine: "CPPSchedulerEngine"):
        self.engine = engine
    
    def get_biological_system(self):
        """获取生物系统"""
        return self.engine.bio_system
    
    async def apply_bio_before_infer(self, prompt_text: str):
        """推理前应用生物系统"""
        bio = self.engine.bio_system
        if not bio:
            return
        
        try:
            from config.integrated_config import get_settings
            
            s = get_settings().scheduler
            enable_delay = bool(getattr(s, "bio_enable_cognitive_delay", False))
            max_delay = float(getattr(s, "bio_max_cognitive_delay", 1.8) or 1.8)
            min_apply = float(getattr(s, "bio_min_delay_to_apply", 0.2) or 0.2)
            energy_base = float(getattr(s, "bio_energy_cost_base", 0.005) or 0.005)
            energy_k = float(getattr(s, "bio_energy_cost_complexity", 0.02) or 0.02)
            dopamine_reward = float(getattr(s, "bio_dopamine_reward", 0.01) or 0.01)
            cortisol_base = float(getattr(s, "bio_cortisol_cost_base", 0.002) or 0.002)
            cortisol_k = float(getattr(s, "bio_cortisol_cost_complexity", 0.006) or 0.006)
        except Exception:
            enable_delay = False
            max_delay = 1.8
            min_apply = 0.2
            energy_base = 0.005
            energy_k = 0.02
            dopamine_reward = 0.01
            cortisol_base = 0.002
            cortisol_k = 0.006
        
        try:
            text = str(prompt_text or "")
        except Exception:
            text = ""
        
        complexity = min(1.0, float(len(text)) / 200.0) if text else 0.0
        
        if enable_delay:
            try:
                delay = float(bio.calculateCognitiveDelay(float(complexity)) or 0.0)
                if max_delay > 0:
                    delay = min(delay, max_delay)
                if delay > min_apply:
                    await asyncio.sleep(delay)
            except Exception:
                pass
        
        try:
            bio.consumeEnergy(float(energy_base + complexity * energy_k))
        except Exception:
            pass
        
        try:
            if dopamine_reward != 0:
                bio.adjustNeurotransmitter("dopamine", float(dopamine_reward))
        except Exception:
            pass
        
        try:
            inc = float(cortisol_base + complexity * cortisol_k)
            if inc != 0:
                bio.adjustNeurotransmitter("cortisol", inc)
        except Exception:
            pass
```

#### 阶段 2-3: 按计划执行

按照 3.2 节的详细计划，逐步执行剩余的拆分任务。

### 4.3 验证阶段

1. **运行单元测试**: 确保所有测试通过
2. **运行集成测试**: 确保系统整体功能正常
3. **性能测试**: 确保性能没有下降
4. **压力测试**: 确保在高负载下稳定运行

### 4.4 文档更新阶段

1. **更新 PROJECT_TECHNICAL_REFERENCE.md**: 记录新的模块结构
2. **更新 UPDATES.md**: 记录拆分更新
3. **更新 README.md**: 更新模块说明

## 五、风险评估与应对

### 5.1 风险清单

| 风险 | 可能性 | 影响 | 应对措施 |
|------|--------|------|---------|
| API 不兼容 | 中 | 高 | 保持代理方法，确保向后兼容 |
| 性能下降 | 低 | 中 | 充分测试，性能基准对比 |
| 功能缺失 | 低 | 高 | 详细测试用例，覆盖所有功能 |
| 循环依赖 | 中 | 中 | 清晰的依赖关系图，避免循环 |
| 测试不足 | 中 | 高 | 编写充分的单元测试和集成测试 |

### 5.2 回滚计划

如果拆分后出现严重问题：

1. **立即回滚**: 恢复 `cpp_scheduler_engine.py.backup`
2. **分析问题**: 定位问题原因
3. **修复问题**: 修复后重新拆分
4. **重新测试**: 确保问题已解决

## 六、预期收益

### 6.1 代码质量

- **可读性提升**: 每个模块职责清晰，易于理解
- **可维护性提升**: 模块独立，修改影响范围小
- **可测试性提升**: 每个模块可以独立测试

### 6.2 开发效率

- **并行开发**: 不同模块可以并行开发
- **快速定位**: 问题定位更快
- **安全修改**: 修改影响范围可控

### 6.3 系统稳定性

- **降低耦合**: 模块间依赖清晰
- **易于扩展**: 新功能可以独立添加
- **易于调试**: 问题隔离更容易

## 七、时间估算

| 阶段 | 预计时间 | 累计时间 |
|------|---------|---------|
| 准备阶段 | 0.5 天 | 0.5 天 |
| 阶段 1: 低风险拆分 | 1-2 天 | 1.5-2.5 天 |
| 阶段 2: 中风险拆分 | 2-3 天 | 3.5-5.5 天 |
| 阶段 3: 高风险拆分 | 3-5 天 | 6.5-10.5 天 |
| 验证阶段 | 1 天 | 7.5-11.5 天 |
| 文档更新 | 0.5 天 | 8-12 天 |

**总计**: 8-12 个工作日

## 八、总结

本规划详细分析了 `cpp_scheduler_engine.py` 的现状，提出了渐进式的拆分方案，将 2608 行代码拆分为 7 个独立模块，每个模块职责清晰、易于维护。拆分过程分为 3 个阶段，从低风险到高风险逐步推进，确保系统稳定性。

拆分完成后，将显著提升代码质量、开发效率和系统稳定性，为后续功能扩展和维护奠定良好基础。
