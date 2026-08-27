"""
GPU资源管理模块
负责GPU/CPU设备切换、显存管理、KV Cache迁移
"""

from core.utils.logger import get_logger
import asyncio
import gc

import os
from typing import Optional

from ..utils.resource_utils import check_memory_pressure

logger = get_logger(__name__)


async def _cleanup_gpu_instance(inst, sync: bool = False) -> None:
    """清理旧LLM实例并释放GPU显存"""
    if inst is None:
        return

    def _do_cleanup():
        nonlocal inst
        try:
            if hasattr(inst, "close"):
                inst.close()
        except Exception:
            pass
        inst = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass

    if sync:
        await asyncio.wait_for(asyncio.to_thread(_do_cleanup), timeout=8.0)
    else:
        from core.utils.async_tasks import spawn_bg_task
        spawn_bg_task(asyncio.to_thread(_do_cleanup), name="gpu_cleanup")


def _update_resource_manager_state(device: str, vram_mb: int = 0,
                                    memory_mb: Optional[int] = None,
                                    is_offloaded: bool = False,
                                    is_loaded: bool = True) -> None:
    """更新资源管理器中的模型状态"""
    try:
        from core.resource_manager import get_resource_manager

        rm = get_resource_manager()
        model = rm.models.get("llm_engine")
        if model:
            model.device = device
            model.vram_usage_mb = vram_mb
            if memory_mb is not None:
                model.memory_usage_mb = memory_mb
            model.is_offloaded = is_offloaded
        rm.mark_model_loaded("llm_engine", is_loaded)
    except Exception:
        pass


class GPUResourceManager:
    """GPU资源管理器"""

    def __init__(self, model_manager):
        self.model_manager = model_manager
        self._prev_cpp_gpu_device_id: Optional[int] = None
        self._prev_cpp_draft_gpu_device_id: Optional[int] = None

    async def offload_kv_cache_to_cpu(self) -> bool:
        """将KV Cache从GPU迁移到CPU"""
        if not self.model_manager.llm or not isinstance(
            self.model_manager._gpu_config, dict
        ):
            return False

        async with self.model_manager._llm_setup_lock:
            current = bool(self.model_manager._gpu_config.get("offload_kqv", True))
            if not current:
                return True

            if self.model_manager._prev_offload_kqv is None:
                self.model_manager._prev_offload_kqv = current

            new_cfg = dict(self.model_manager._gpu_config)
            new_cfg["offload_kqv"] = False

            logger.info("KV Cache 正在尝试从 GPU 迁移到 CPU (offload_kqv=False)...")
            new_inst = await asyncio.to_thread(
                self.model_manager.setup_python_llm, new_cfg, True
            )
            if not new_inst:
                return False

            old_inst = self.model_manager.llm
            if old_inst:
                try:
                    state = await asyncio.to_thread(old_inst.save_state)
                    await asyncio.to_thread(new_inst.load_state, state)
                except Exception as e:
                    logger.warning(
                        "KV Cache 状态搬运失败，仍将继续切换以释放显存: %s", e
                    )

            self.model_manager.llm = new_inst
            self.model_manager._gpu_config["offload_kqv"] = False

            if old_inst:
                await _cleanup_gpu_instance(old_inst)

            return True

    async def restore_kv_cache_to_gpu(self) -> bool:
        """将KV Cache从CPU回迁到GPU"""
        if not self.model_manager.llm or not isinstance(
            self.model_manager._gpu_config, dict
        ):
            return False

        async with self.model_manager._llm_setup_lock:
            current = bool(self.model_manager._gpu_config.get("offload_kqv", True))
            if current:
                return True

            target = True
            if isinstance(self.model_manager._prev_offload_kqv, bool):
                target = bool(self.model_manager._prev_offload_kqv)
            if not target:
                return True

            new_cfg = dict(self.model_manager._gpu_config)
            new_cfg["offload_kqv"] = True

            logger.info("KV Cache 正在尝试回迁到 GPU (offload_kqv=True)...")
            new_inst = await asyncio.to_thread(
                self.model_manager.setup_python_llm, new_cfg, True
            )
            if not new_inst:
                return False

            old_inst = self.model_manager.llm
            if old_inst:
                try:
                    state = await asyncio.to_thread(old_inst.save_state)
                    await asyncio.to_thread(new_inst.load_state, state)
                except Exception as e:
                    logger.warning("KV Cache 状态搬运失败，仍将继续切换: %s", e)

            self.model_manager.llm = new_inst
            self.model_manager._gpu_config["offload_kqv"] = True
            self.model_manager._prev_offload_kqv = None

            if old_inst:
                await _cleanup_gpu_instance(old_inst)

            return True

    async def offload_llm_to_cpu(self, urgent: bool = False):
        """将LLM迁移到CPU以释放显存"""
        logger.info(
            f"Executing LLM Device Migration (GPU -> CPU), Mode: {'Urgent' if urgent else 'Atomic Hot Swap'}..."
        )

        try:
            cfg_layers = None
            if isinstance(self.model_manager._gpu_config, dict):
                try:
                    cfg_layers = int(
                        self.model_manager._gpu_config.get("n_gpu_layers", -1)
                    )
                except Exception:
                    cfg_layers = None

            if bool(self.model_manager._python_force_cpu) or cfg_layers == 0:
                return

            cpu_config = (
                self.model_manager._gpu_config.copy()
                if isinstance(self.model_manager._gpu_config, dict)
                else {}
            )
            cpu_config["force_cpu"] = True
            cpu_config["n_gpu_layers"] = 0

            async with self.model_manager._llm_setup_lock:
                self.model_manager._python_force_cpu = True
                if isinstance(self.model_manager._gpu_config, dict):
                    if cfg_layers is not None and int(cfg_layers) != 0:
                        self.model_manager._prev_n_gpu_layers = int(cfg_layers)
                    self.model_manager._gpu_config["force_cpu"] = True
                    self.model_manager._gpu_config["n_gpu_layers"] = 0

                if urgent:
                    logger.info("Emergency Mode: Releasing GPU VRAM immediately...")
                    await self.model_manager._unload_llm_locked()

                    async def background_cpu_load():
                        try:
                            async with self.model_manager._llm_setup_lock:
                                if (
                                    self.model_manager._python_force_cpu
                                    and self.model_manager.llm is None
                                ):
                                    await asyncio.to_thread(
                                        self.model_manager.setup_python_llm, cpu_config
                                    )
                                    logger.info(
                                        "LLM background migration to CPU finished"
                                    )
                        except Exception as be:
                            logger.error(
                                f"LLM background migration to CPU failed: {be}"
                            )

                    from core.utils.async_tasks import spawn_bg_task
                    spawn_bg_task(background_cpu_load(), name="bg_cpu_load")
                else:
                    logger.info("Atomic Mode: Preparing CPU instance in background...")
                    old_inst = self.model_manager.llm

                    new_inst = await asyncio.to_thread(
                        self.model_manager.setup_python_llm,
                        cpu_config,
                        return_instance=True,
                    )

                    if new_inst:
                        if old_inst:
                            try:
                                logger.info("Migrating KV Cache from GPU to CPU...")
                                state = await asyncio.to_thread(old_inst.save_state)
                                await asyncio.to_thread(new_inst.load_state, state)
                                logger.info("KV Cache migration finished")
                            except Exception as ke:
                                logger.debug(
                                    f"KV Cache migration detail error (non-fatal): {ke}"
                                )

                        self.model_manager.llm = new_inst
                        logger.info(
                            "LLM hot-swapped to CPU instance, service maintained"
                        )

                        if old_inst:
                            await _cleanup_gpu_instance(old_inst)
                    else:
                        logger.error("Failed to load CPU instance, atomic swap aborted")

            rm_model = _try_get_rm_model()
            _update_resource_manager_state(
                device="CPU", vram_mb=0,
                memory_mb=max(int(rm_model.memory_usage_mb or 0), 450) if rm_model else 450,
                is_offloaded=True, is_loaded=True,
            )

            logger.info("LLM migrated to CPU successfully.")
        except Exception as e:
            logger.error("LLM Offload failed: %s", e)

    async def restore_llm_to_gpu(self) -> bool:
        """将LLM从CPU回迁到GPU"""
        logger.info("LLM 引擎尝试回迁 GPU...")

        if not isinstance(self.model_manager._gpu_config, dict):
            logger.warning("LLM 回迁失败: 配置缺失")
            return False

        prev_layers = self.model_manager._prev_n_gpu_layers
        if not isinstance(prev_layers, int) or int(prev_layers) == 0:
            try:
                from config.integrated_config import get_settings

                prev_layers = int(get_settings().model.n_gpu_layers)
                logger.info(
                    f"未找到历史层数记录，使用 integrated_config 默认值: {prev_layers}"
                )
            except Exception:
                prev_layers = 32
                logger.info(f"未找到历史层数记录，使用兜底默认值: {prev_layers}")

        if int(prev_layers) == 0:
            logger.warning("回迁层数为 0（CPU），跳过回迁")
            return False

        logger.info(f"Python LLM 正在回迁 GPU, 目标层数: {prev_layers}")

        use_mmap = _resolve_use_mmap()
        ram_mirror_offload = _resolve_ram_mirror_offload()

        from core.modules.llm.utils import resolve_use_mmap as _resolve_mmap_util

        effective_use_mmap = _resolve_mmap_util(use_mmap, ram_mirror_offload, prev_layers)
        logger.info(
            f"Python LLM 回迁GPU: use_mmap={use_mmap}, effective_use_mmap={effective_use_mmap}"
        )

        mem_result = check_memory_pressure()
        prefer_atomic = (not effective_use_mmap) and (not mem_result.is_pressure)

        current_layers = None
        try:
            current_layers = int(self.model_manager._gpu_config.get("n_gpu_layers", -1))
        except Exception:
            current_layers = None

        if (
            self.model_manager.llm is not None
            and (not bool(self.model_manager._python_force_cpu))
            and (not bool(self.model_manager._gpu_config.get("force_cpu")))
            and (current_layers is not None and int(current_layers) != 0)
        ):
            return True

        try:
            async with self.model_manager._llm_setup_lock:
                self.model_manager._python_force_cpu = False
                self.model_manager._gpu_config.pop("force_cpu", None)
                self.model_manager._gpu_config["n_gpu_layers"] = int(prev_layers)

                if (
                    isinstance(self.model_manager._prev_n_ctx, int)
                    and self.model_manager._prev_n_ctx > 0
                ):
                    self.model_manager._gpu_config["max_context_size"] = int(
                        self.model_manager._prev_n_ctx
                    )
                    self.model_manager._gpu_config["n_ctx"] = int(
                        self.model_manager._prev_n_ctx
                    )
                if (
                    isinstance(self.model_manager._prev_n_batch, int)
                    and self.model_manager._prev_n_batch > 0
                ):
                    self.model_manager._gpu_config["max_batch_size"] = int(
                        self.model_manager._prev_n_batch
                    )
                    self.model_manager._gpu_config["n_batch"] = int(
                        self.model_manager._prev_n_batch
                    )

                if not prefer_atomic:
                    await self.model_manager._unload_llm_locked()
                    new_inst = await asyncio.to_thread(
                        self.model_manager.setup_python_llm,
                        self.model_manager._gpu_config,
                        return_instance=True,
                    )
                    if new_inst:
                        self.model_manager.llm = new_inst
                        _update_resource_manager_state(device="GPU", is_loaded=True)
                        return True
                    raise RuntimeError("无法在后台创建新的 GPU 实例")

                logger.info("Python LLM 正在执行原子化热替换 (Atomic Hot Swap)...")
                new_inst = await asyncio.to_thread(
                    self.model_manager.setup_python_llm,
                    self.model_manager._gpu_config,
                    return_instance=True,
                )

                if new_inst:
                    old_inst = self.model_manager.llm

                    if old_inst:
                        try:
                            logger.info("正在尝试搬移 KV Cache 状态以实现无感切换...")

                            def transfer_state(src, dst):
                                try:
                                    state = src.save_state()
                                    dst.load_state(state)
                                    return True
                                except Exception as se:
                                    logger.debug(
                                        f"KV Cache 状态搬移细节错误 (非致命): {se}"
                                    )
                                    return False

                            ok = await asyncio.to_thread(
                                transfer_state, old_inst, new_inst
                            )
                            if ok:
                                logger.info("KV Cache 状态已成功从 CPU 搬移至 GPU")
                        except Exception as e:
                            logger.warning(f"KV Cache 状态搬移失败 (回迁仍将继续): {e}")

                    self.model_manager.llm = new_inst
                    logger.info("Python LLM 已成功回迁 GPU，指针已原子化切换")

                    if old_inst:
                        mem_percent = check_memory_pressure().percent
                        demo_mode = _is_demo_mode()
                        sync_cleanup = demo_mode or mem_percent >= 88.0
                        await _cleanup_gpu_instance(old_inst, sync=sync_cleanup)
                else:
                    raise RuntimeError("无法在后台创建新的 GPU 实例")
        except Exception as e:
            self.model_manager._last_llm_load_error = str(e)
            logger.warning("LLM 回迁 GPU 失败: %s", e)
            return False

        _update_resource_manager_state(device="GPU", is_loaded=True)
        return True

    async def release_llm_vram_for_image_gen(self):
        """为图像生成释放LLM显存"""
        if self.model_manager.llm is None:
            return

        if self.model_manager.llm is not None:
            await self.offload_llm_to_cpu(urgent=True)
            return


def _try_get_rm_model():
    """尝试获取资源管理器中的llm_engine模型"""
    try:
        from core.resource_manager import get_resource_manager
        return get_resource_manager().models.get("llm_engine")
    except Exception:
        return None


def _resolve_use_mmap() -> Optional[bool]:
    """从配置解析use_mmap"""
    try:
        from config.integrated_config import get_settings as _get_settings
        settings = _get_settings()
        return bool(getattr(settings.model, "use_mmap", False))
    except Exception:
        return None


def _resolve_ram_mirror_offload() -> bool:
    """从配置解析ram_mirror_offload"""
    try:
        from config.integrated_config import get_settings as _get_settings
        settings = _get_settings()
        return bool(getattr(settings.model, "ram_mirror_offload", False))
    except Exception:
        return False


def _is_demo_mode() -> bool:
    """检查是否为演示模式"""
    return str(
        os.getenv("XIAOYOU_DEMO_MODE", "") or ""
    ).strip().lower() in {"1", "true", "yes", "y", "on"}
