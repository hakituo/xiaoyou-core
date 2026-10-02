"""stream 迭代输出与 Transformers 流式生成（混入 StreamGenerator）。

从 ``core/modules/llm/stream_generator.py`` 拆出：
- ``_iterate_stream``：迭代 llama.cpp 的 chunk，记录首 token/卡顿诊断
- ``_generate_transformers``：transformers + TextIteratorStreamer 的流式生成

⚠️ 模块级 patch 语义：测试会 patch 门面模块的 ``time`` 与
``TextIteratorStreamer``，因此这两个名字必须在调用期从门面模块取名，
不能顶层 from-import 固化。
"""
from __future__ import annotations

import threading

# 循环引用仅为保留「按门面模块打补丁」的语义，调用期才取属性
from core.modules.llm import stream_generator as _facade
from core.utils.logger import get_logger

from .error_handler import get_error_message

logger = get_logger("LLM.STREAM_GENERATOR")


class StreamGeneratorStreamMixin:
    """chunk 迭代与 Transformers 流式生成。"""

    def _iterate_stream(
        self, stream, start_gen_time, is_gpu_infer, actual_n_gpu_layers, _put_threadsafe
    ):
        """迭代stream并产出内容"""
        if stream is None:
            logger.error("create_chat_completion返回的stream为None！")
            _put_threadsafe(
                {
                    "error": get_error_message("stream_init_failed"),
                    "done": True,
                }
            )
            return

        count = 0
        last_chunk_time = _facade.time.time()
        chunk_timeout = 30.0
        stream_iter_start = _facade.time.time()

        logger.info(
            f"开始迭代stream，is_gpu_infer={is_gpu_infer}, n_gpu_layers={actual_n_gpu_layers}"
        )

        try:
            for chunk in stream:
                current_time = _facade.time.time()
                elapsed_since_iter = current_time - stream_iter_start

                # 检测长时间无chunk
                if count == 0 and elapsed_since_iter > 10.0:
                    logger.error(
                        f"GPU推理严重问题：stream迭代开始后{elapsed_since_iter:.1f}秒仍无chunk！"
                    )
                    # 检查GPU状态
                    try:
                        import torch

                        if torch.cuda.is_available():
                            gpu_mem_used = torch.cuda.memory_allocated(0) / (1024**3)
                            gpu_mem_reserved = torch.cuda.memory_reserved(0) / (1024**3)
                            logger.error(
                                f"GPU显存状态 - 已分配: {gpu_mem_used:.2f}GB, 已保留: {gpu_mem_reserved:.2f}GB"
                            )
                    except Exception:
                        pass

                elapsed_since_last_chunk = current_time - last_chunk_time
                if count > 0 and elapsed_since_last_chunk > chunk_timeout:
                    logger.error(
                        f"推理可能卡住：已{elapsed_since_last_chunk:.1f}秒没有新token"
                    )

                if count == 0:
                    first_token_time = _facade.time.time() - start_gen_time
                    logger.info(
                        f"Received first chunk. Time to first token: {first_token_time:.4f}s"
                    )

                count += 1
                last_chunk_time = current_time

                # 检查chunk格式
                if not isinstance(chunk, dict):
                    logger.warning(f"收到非字典格式的chunk: {type(chunk)}")
                    continue

                if "choices" not in chunk or len(chunk["choices"]) == 0:
                    logger.warning(f"chunk缺少choices字段: {chunk.keys()}")
                    continue

                delta = chunk["choices"][0].get("delta", {})
                if "content" in delta and delta["content"]:
                    content = delta["content"]
                    _put_threadsafe({"content": content})

        except StopIteration:
            logger.info("Stream正常结束（StopIteration）")
        except Exception as stream_error:
            logger.error(f"Stream迭代异常: {stream_error}", exc_info=True)
            _put_threadsafe(
                {
                    "error": f"GPU推理stream异常: {str(stream_error)}",
                    "done": True,
                }
            )
            return

        total_time = _facade.time.time() - start_gen_time
        logger.info(
            f"Stream finished. Total chunks: {count}. Total time: {total_time:.4f}s"
        )

    def _generate_transformers(
        self,
        prompt_value,
        max_tokens: int,
        temperature: float,
        top_p: float,
        top_k,
        repetition_penalty: float,
        min_p,
        _put_threadsafe,
    ):
        """Transformers流式生成"""
        logger.info("Using Transformers generation.")
        if self.module.tokenizer is None or self.module.model is None:
            _put_threadsafe(
                {
                    "error": "本地模型未正确初始化，请稍后重试。",
                    "done": True,
                }
            )
            return

        if not _facade.TextIteratorStreamer:
            logger.error("TextIteratorStreamer not found.")
            _put_threadsafe(
                {"error": "Transformers library or TextIteratorStreamer not available"}
            )
            return

        streamer = _facade.TextIteratorStreamer(
            self.module.tokenizer, skip_prompt=True, skip_special_tokens=True
        )

        # 准备输入
        if isinstance(prompt_value, list):
            try:
                prompt_text = self.module.tokenizer.apply_chat_template(
                    prompt_value, tokenize=False, add_generation_prompt=True
                )
            except Exception:
                prompt_text = str(prompt_value)
        else:
            prompt_text = str(prompt_value)

        inputs = self.module.tokenizer(prompt_text, return_tensors="pt")
        if self.module.device == "cuda":
            inputs = {k: v.cuda() for k, v in inputs.items()}

        gen_kwargs = {
            "max_new_tokens": max_tokens,
            "temperature": temperature,
            "do_sample": True,
            "repetition_penalty": repetition_penalty,
            "pad_token_id": self.module.tokenizer.eos_token_id,
            "streamer": streamer,
        }
        if min_p is not None:
            gen_kwargs["min_p"] = min_p
        if top_p is not None:
            gen_kwargs["top_p"] = top_p
        if top_k is not None:
            try:
                gen_kwargs["top_k"] = int(top_k)
            except Exception:
                pass

        # 启动生成线程
        generation_thread = threading.Thread(
            target=self.module.model.generate, kwargs=dict(inputs, **gen_kwargs)
        )
        generation_thread.start()

        for new_text in streamer:
            _put_threadsafe({"content": new_text})

        generation_thread.join()
        logger.info("Generation thread joined.")
