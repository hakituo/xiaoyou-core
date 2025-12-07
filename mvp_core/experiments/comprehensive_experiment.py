import asyncio
import time
import argparse
import logging
import json
import psutil
import statistics
import os
import sys
import subprocess
import aiohttp
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(project_root)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ComprehensiveBenchmark")

from config import get_settings

# ================= 1. 配置区 (Config) =================
settings = get_settings()

def get_abs_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(project_root, path)

CONFIG = {
    "llm_path": get_abs_path(settings.model.text_path),
    "sd_path": get_abs_path(settings.model.sd_path),
    "vl_path": get_abs_path(settings.model.vl_path),
    "tts_api": settings.model.tts_api
}

def cpu_bound_task_blocking(duration: float):
    """
    Simulates a CPU-intensive task (e.g., Matrix Mul) that BLOCKS the thread.
    Used for Mock LLM/VL simulation.
    """
    end_time = time.time() + duration
    count = 0
    while time.time() < end_time:
        count += 1
        _ = count * count
    return count

# ================= 2. 模拟组件区 (Mock Adapters) =================

class MockLLMAdapter:
    async def generate(self, prompt: str, **kwargs):
        # Simulate CPU blocking (Inference is CPU heavy on edge if not fully offloaded)
        # 0.2s blocking to simulate token generation lag on main thread if naive
        cpu_bound_task_blocking(0.1) 
        await asyncio.sleep(0.05) # Some non-blocking wait
        return "Mock LLM Response"

class MockVLAdapter:
    async def analyze_image(self, image_path: str, prompt: str):
        # Simulate Preprocessing (CPU blocking) + Inference (GPU/Wait)
        cpu_bound_task_blocking(0.05)
        await asyncio.sleep(0.1)
        return "Mock Image Description"

class MockTTSAdapter:
    async def synthesize(self, text: str):
        # Simulate Network IO latency
        await asyncio.sleep(0.2)
        return b"fake_audio_bytes"

class MockSDAdapter:
    def generate_image(self, prompt: str, **kwargs):
        # Simulate Heavy GPU Blocking (if sync) or Wait (if async)
        # In Mock, we block CPU to show impact on main thread
        cpu_bound_task_blocking(0.3)
        return "mock_image.png"

# ================= 3. 真实组件加载区 (Real Imports) =================

class RealTTSAdapter:
    def __init__(self, api_url):
        self.api_url = api_url

    async def synthesize(self, text: str):
        try:
            ref_audio_path = os.path.join(project_root, "ref_audio", "female", "ref_calm.wav")
            params = {
                "text": text,
                "text_lang": "zh",
                "ref_audio_path": ref_audio_path,
                "prompt_lang": "zh",
                "prompt_text": "",
                "media_type": "wav"
            }
            async with aiohttp.ClientSession() as session:
                # GPT-SoVITS default API
                async with session.get(f"{self.api_url}/tts", params=params) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    else:
                        logger.error(f"TTS Error {resp.status}: {await resp.text()}")
        except Exception as e:
            logger.error(f"TTS Request Failed: {e}")
        return None

def load_real_adapters():
    """延迟加载：只有在需要时才 import 那些巨大的库""" 
    logger.info("正在加载真实模型驱动 (Local MVP)...") 
    try:
        # Import LLM
        from data.adapters.gguf_llm_adapter import GGUFLLMAdapter
        
        # Import SD
        from data.adapters.sd_adapter import SDAdapter
        
        # Import VL
        from data.adapters.vl_adapter import VLAdapter

        return GGUFLLMAdapter, SDAdapter, VLAdapter
            
    except ImportError as e:
        logger.error(f"❌ 无法加载真实模型依赖: {e}") 
        logger.error("请检查环境或使用 --workload mock") 
        sys.exit(1)

# ================= 4. 上下文/工厂模式 (Context/Factory) =================

class ExperimentContext:
    def __init__(self, mode: str, workload: str):
        self.mode = mode
        self.workload = workload
        self.llm = None
        self.vl = None
        self.tts = None
        self.sd = None
        self.scheduler = None
        self.TaskType = None
        self.TaskPriority = None

    async def setup(self):
        # 1. Initialize Adapters
        if self.workload == "mock":
            logger.info("\n=== 🔧 初始化 MOCK 模拟环境 ===") 
            self.llm = MockLLMAdapter()
            self.vl = MockVLAdapter()
            self.tts = MockTTSAdapter()
            self.sd = MockSDAdapter()
        
        elif self.workload == "real":
            logger.info("\n=== 🚀 初始化 REAL 真实环境 (全量化模型) ===") 
            GGUFLLMAdapter, SDAdapter, RealQwen2VLAdapter = load_real_adapters()
            
            self.llm = GGUFLLMAdapter(CONFIG['llm_path'], n_gpu_layers=0)
            self.tts = RealTTSAdapter(CONFIG['tts_api'])
            
            # Ensure test image exists for VL
            if not os.path.exists("test.jpg"):
                try:
                    from PIL import Image
                    img = Image.new('RGB', (224, 224), color = 'red')
                    img.save("test.jpg")
                except ImportError:
                    pass

            if RealQwen2VLAdapter:
                self.vl = RealQwen2VLAdapter(CONFIG['vl_path'])
            else:
                self.vl = MockVLAdapter()
                
            # Config for SDAdapter
            sd_conf = {
                'model_type': 'stable_diffusion',
                'sd_model_path': CONFIG['sd_path'],
                'device': 'auto', # Use auto to enable GPU if available
                'quantization': {
                    'enabled': True,
                    'precision_level': 'fp16'
                },
                'generation': {
                    'low_vram_mode': True, # Enable low vram mode (uses model offload)
                    'width': 512,
                    'height': 512,
                    'num_inference_steps': 4,
                    'local_files_only': True
                }
            }
            self.sd = SDAdapter(sd_conf)
        
        logger.info("✅ 模型加载完成")

        # 2. Initialize Scheduler (if needed)
        if self.mode == 'xy_core':
            try:
                from services.task_scheduler import GlobalTaskScheduler, TaskPriority, TaskType
                self.scheduler = GlobalTaskScheduler()
                self.TaskType = TaskType
                self.TaskPriority = TaskPriority
                await self.scheduler.start()
                logger.info("✅ 调度器已启动")
            except ImportError:
                logger.error("GlobalTaskScheduler not found!")
                sys.exit(1)

    async def teardown(self):
        if self.scheduler:
            await self.scheduler.stop()
            logger.info("🛑 调度器已停止")

# ================= 5. 实验逻辑区 (Experiment Runner) =================

class ExperimentRunner:
    def __init__(self, context: ExperimentContext):
        self.ctx = context
        self.results = {}

    # --- Task Logic Helpers ---

    async def _run_mixed_task_naive(self, task_id: int) -> float:
        """Naive Async: Everything runs in main loop. Returns duration in seconds."""
        start = time.time()
        await self.ctx.llm.generate("Hello")
        await self.ctx.tts.synthesize("Hello world")
        await self.ctx.vl.analyze_image("test.jpg", "Describe")
        
        if self.ctx.workload == 'real':
            await asyncio.to_thread(self.ctx.sd.generate_image, "A cat")
        else:
            self.ctx.sd.generate_image("A cat")
        return time.time() - start

    def _run_mixed_task_serial(self, task_id: int) -> float:
        """Serial: Blocking calls. Returns duration in seconds."""
        start = time.time()
        cpu_bound_task_blocking(0.1) # LLM
        time.sleep(0.2) # TTS
        cpu_bound_task_blocking(0.1) # VL
        cpu_bound_task_blocking(0.3) # SD
        return time.time() - start

    async def _run_mixed_task_xycore(self, task_id: int) -> float:
        """xy-core: Offloaded to Scheduler. Returns duration in seconds."""
        start = time.time()
        # 1. LLM (CPU_BOUND)
        async def run_llm():
            return await self.ctx.llm.generate("Hello")
            
        t1 = await self.ctx.scheduler.schedule_task(
            func=run_llm if self.ctx.workload == 'real' else cpu_bound_task_blocking,
            args=() if self.ctx.workload == 'real' else (0.1,),
            name=f"llm_{task_id}",
            priority=self.ctx.TaskPriority.HIGH,
            task_type=self.ctx.TaskType.CPU_BOUND
        )
        await (await self.ctx.scheduler.get_task_future(t1))

        # 2. TTS (IO_BOUND)
        await self.ctx.tts.synthesize("Hello world")

        # 3. VL (GPU_BOUND)
        async def run_vl():
            return await self.ctx.vl.analyze_image("test.jpg", "Describe")

        t3 = await self.ctx.scheduler.schedule_task(
            func=run_vl if self.ctx.workload == 'real' else cpu_bound_task_blocking,
            args=() if self.ctx.workload == 'real' else (0.05,),
            name=f"vl_{task_id}",
            priority=self.ctx.TaskPriority.MEDIUM,
            task_type=self.ctx.TaskType.GPU_BOUND
        )
        await (await self.ctx.scheduler.get_task_future(t3))

        # 4. SD (GPU_BOUND)
        def run_sd():
            res = self.ctx.sd.generate_image("A cat")
            # Save image for verification
            try:
                if isinstance(res, dict) and res.get('status') == 'success' and res.get('images'):
                    img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'experiment_results', 'generated_images')
                    os.makedirs(img_dir, exist_ok=True)
                    timestamp = int(time.time() * 1000)
                    for i, img in enumerate(res['images']):
                        img_path = os.path.join(img_dir, f"sd_task_{task_id}_{timestamp}_{i}.png")
                        img.save(img_path)
                        logger.info(f"Saved generated image to {img_path}")
            except Exception as e:
                logger.error(f"Failed to save image: {e}")
            return res

        t4 = await self.ctx.scheduler.schedule_task(
            func=run_sd if self.ctx.workload == 'real' else cpu_bound_task_blocking,
            args=() if self.ctx.workload == 'real' else (0.3,),
            name=f"sd_{task_id}",
            priority=self.ctx.TaskPriority.LOW, 
            task_type=self.ctx.TaskType.GPU_BOUND
        )
        await (await self.ctx.scheduler.get_task_future(t4))
        
        return time.time() - start

    async def _run_mixed_task(self, task_id: int) -> float:
        """Unified Task Runner. Returns duration."""
        if self.ctx.mode == 'single_thread':
            return self._run_mixed_task_serial(task_id)
        elif self.ctx.mode == 'naive_async':
            return await self._run_mixed_task_naive(task_id)
        elif self.ctx.mode == 'xy_core':
            return await self._run_mixed_task_xycore(task_id)
        return 0.0

    # --- Experiments ---

    def _calc_metrics(self, latencies: List[float]) -> Dict[str, float]:
        """Calculate detailed metrics from a list of latencies (seconds)."""
        if not latencies:
            return {}
        
        n = len(latencies)
        avg = statistics.mean(latencies)
        
        try:
            if n < 2:
                # Handle single data point case
                p50 = latencies[0]
                p95 = latencies[0]
                p99 = latencies[0]
            else:
                # statistics.quantiles requires Python 3.8+ and at least 2 data points
                quantiles = statistics.quantiles(latencies, n=100)
                p50 = quantiles[49]
                p95 = quantiles[94]
                p99 = quantiles[98]
        except (AttributeError, statistics.StatisticsError):
            # Fallback for older python or insufficient data points
            sorted_l = sorted(latencies)
            p50 = sorted_l[int(n * 0.5)]
            p95 = sorted_l[min(int(n * 0.95), n-1)]
            p99 = sorted_l[min(int(n * 0.99), n-1)]
            
        return {
            "n": n,
            "avg_ms": avg * 1000,
            "p50_ms": p50 * 1000,
            "p95_ms": p95 * 1000,
            "p99_ms": p99 * 1000,
            "min_ms": min(latencies) * 1000,
            "max_ms": max(latencies) * 1000
        }

    async def run_experiment_1_concurrency(self, concurrencies=[1, 5, 10]):
        logger.info(f"=== Exp 1: Concurrency ({self.ctx.mode}/{self.ctx.workload}) ===")
        exp_results = []
        
        # Warmup
        logger.info("Warming up...")
        try:
            await self._run_mixed_task(-1)
        except Exception:
            pass
            
        for c in concurrencies:
            logger.info(f"Running concurrency: {c}")
            start = time.time()
            task_latencies = []
            
            if self.ctx.mode == 'single_thread':
                for i in range(c): 
                    dur = self._run_mixed_task_serial(i)
                    task_latencies.append(dur)
            else:
                # For naive/xy_core, we use asyncio.gather
                tasks = []
                for i in range(c):
                    if self.ctx.mode == 'naive_async':
                        tasks.append(self._run_mixed_task_naive(i))
                    elif self.ctx.mode == 'xy_core':
                        tasks.append(self._run_mixed_task_xycore(i))
                task_latencies = await asyncio.gather(*tasks)
            
            total_dur = time.time() - start
            rps = c / total_dur
            
            metrics = self._calc_metrics(task_latencies)
            logger.info(f"Concur: {c} | Total Time: {total_dur:.2f}s | RPS: {rps:.2f} | Avg Latency: {metrics['avg_ms']:.2f}ms")
            
            result_entry = {
                "concurrency": c, 
                "rps": rps, 
                "total_time": total_dur,
                "metrics": metrics
            }
            exp_results.append(result_entry)
        
        self.results['exp1'] = exp_results

    async def run_experiment_2_blocking(self):
        logger.info(f"=== Exp 2: Blocking Latency ({self.ctx.mode}) ===")
        lags = []
        running = True
        
        async def monitor():
            while running:
                s = time.time()
                await asyncio.sleep(0.1)
                lags.append(time.time() - s - 0.1)
        
        asyncio.create_task(monitor())
        await asyncio.sleep(0.5)
        
        # Fire a heavy SD task
        logger.info("Triggering Heavy SD Task...")
        if self.ctx.mode == 'xy_core':
            def run_sd(): return self.ctx.sd.generate_image("Heavy")
            tid = await self.ctx.scheduler.schedule_task(
                func=run_sd if self.ctx.workload == 'real' else lambda: cpu_bound_task_blocking(2.0),
                name="heavy_sd",
                priority=self.ctx.TaskPriority.LOW,
                task_type=self.ctx.TaskType.GPU_BOUND
            )
            await (await self.ctx.scheduler.get_task_future(tid))
        else:
            if self.ctx.workload == 'real':
                await asyncio.to_thread(self.ctx.sd.generate_image, "Heavy")
            else:
                cpu_bound_task_blocking(2.0)
                
        running = False
        
        if lags:
            metrics = self._calc_metrics(lags)
            logger.info(f"Max Lag: {metrics['max_ms']:.2f}ms | Avg Lag: {metrics['avg_ms']:.2f}ms")
            self.results['exp2'] = {"max_lag": metrics['max_ms'], "avg_lag": metrics['avg_ms'], "metrics": metrics}
        else:
            self.results['exp2'] = {"max_lag": 0, "avg_lag": 0}

    async def run_experiment_3_distribution(self, n_requests=5):
        logger.info(f"=== Exp 3: Latency Distribution ({self.ctx.mode}) ===")
        latencies = []
        
        # Warmup
        logger.info("Warming up...")
        try:
            await self._run_mixed_task(-1)
        except Exception:
            pass
            
        for i in range(n_requests):
            dur = await self._run_mixed_task(i)
            latencies.append(dur)
            await asyncio.sleep(0.05)
            
        metrics = self._calc_metrics(latencies)
        logger.info(f"Collected {len(latencies)} samples. P50: {metrics['p50_ms']:.2f}ms, P99: {metrics['p99_ms']:.2f}ms")
        self.results['exp3'] = latencies
        self.results['exp3_metrics'] = metrics

    async def run_experiment_4_stability(self, duration=30):
        logger.info(f"=== Exp 4: Stability Test ({duration}s) ===")
        start_time = time.time()
        errors = 0
        completed = 0
        latencies = []
        
        async def stress_worker(wid):
            nonlocal errors, completed
            while time.time() - start_time < duration:
                try:
                    dur = await self._run_mixed_task(wid)
                    latencies.append(dur)
                    completed += 1
                except Exception as e:
                    errors += 1
                    logger.error(f"Error in worker {wid}: {e}")
                await asyncio.sleep(0.1)

        # Run 3 concurrent workers to stress
        await asyncio.gather(*[stress_worker(i) for i in range(3)])
        
        metrics = self._calc_metrics(latencies)
        self.results['exp4'] = {
            "duration": duration, 
            "completed": completed, 
            "errors": errors,
            "metrics": metrics
        }
        logger.info(f"Stability: {completed} tasks, {errors} errors. Avg Latency: {metrics.get('avg_ms', 0):.2f}ms")

    def save_report(self, filename):
        with open(filename, 'w') as f:
            json.dump({
                "mode": self.ctx.mode, 
                "workload": self.ctx.workload,
                "timestamp": datetime.now().isoformat(),
                "results": self.results
            }, f, indent=2)
        logger.info(f"Report saved to {filename}")

# ================= 6. 入口 (Main) =================

if __name__ == "__main__":
    # Default output path
    default_output_dir = os.path.join(os.path.dirname(__file__), '..', 'experiment_results')
    os.makedirs(default_output_dir, exist_ok=True)
    default_output_path = os.path.join(default_output_dir, 'comprehensive_results.json')

    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', default='xy_core', choices=['single_thread', 'naive_async', 'xy_core'])
    parser.add_argument('--workload', default='mock', choices=['mock', 'real'])
    parser.add_argument('--exp', type=int, default=0)
    parser.add_argument('--output', default=default_output_path)
    args = parser.parse_args()

    # 1. Initialize Context
    ctx = ExperimentContext(args.mode, args.workload)
    
    # 2. Initialize Runner
    runner = ExperimentRunner(ctx)
    
    async def main():
        try:
            await ctx.setup()
            
            if args.exp in [0, 1]: await runner.run_experiment_1_concurrency()
            if args.exp in [0, 2]: await runner.run_experiment_2_blocking()
            if args.exp in [0, 3]: await runner.run_experiment_3_distribution()
            if args.exp in [0, 4]: await runner.run_experiment_4_stability(duration=60)
            
            runner.save_report(args.output)
        finally:
            await ctx.teardown()
        
    asyncio.run(main())
