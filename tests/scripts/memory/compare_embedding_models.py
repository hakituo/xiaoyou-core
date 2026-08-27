#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比项目可用 embedding 模型的中文聊天记忆检索表现。

该脚本只读取本地模型，不修改正式配置或现有记忆向量。评测重点是口语化查询
对历史偏好、日程和项目约束的召回能力，而不是模型官方排行榜分数。
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MINILM_PATH = PROJECT_ROOT / "models" / "embedding" / "all-MiniLM-L6-v2"
BGE_PATH = PROJECT_ROOT / "models" / "BERT" / "bge-small-zh-v1.5"
QWEN3_PATH = PROJECT_ROOT / "models" / "embedding" / "Qwen3-Embedding-0.6B"
HARRIER_PATH = (
    PROJECT_ROOT / "models" / "embedding" / "harrier-oss-v1-0.6b-ONNX"
)


# 每条文档只表达一个可检索事实，查询尽量避开原文措辞，并加入相近干扰项。
DOCUMENTS: list[tuple[str, str]] = [
    ("reply_concise", "用户平时喜欢先给结论，回复简洁一点，不要铺垫太长。"),
    ("debug_detailed", "遇到复杂故障时要把证据链和根因讲清楚，不能只给一句结论。"),
    ("config_first", "用户不喜欢硬编码，可变化的行为应该优先放到配置或模板中。"),
    ("dirty_worktree", "项目工作区经常有未提交修改，处理任务时不能覆盖或清理无关改动。"),
    ("python_venv", "这个项目运行 Python 和测试时统一使用 venv_core 或 venv_cpu。"),
    ("gradle_rule", "Android 构建默认交给用户在 Android Studio 执行，助手只做静态检查。"),
    ("chinese_comments", "项目里的代码注释统一使用中文，并尽量兼容 Windows 与 Linux。"),
    ("sleep_reminder", "用户希望晚上十二点十五分提醒他放下手机准备睡觉。"),
    ("wake_alarm", "工作日早上七点半叫用户起床，周末不需要。"),
    ("friday_meeting", "本周五下午三点有一次小游项目的需求评审会议。"),
    ("october_trip", "国庆假期十月三日坐高铁去上海，返程时间还没确定。"),
    ("mother_birthday", "用户妈妈的生日是五月十二日，要提前一周准备礼物。"),
    ("cat_name", "用户养了一只橘猫，名字叫年糕，胆子比较小。"),
    ("no_cilantro", "用户吃饭不要香菜，但葱和蒜都可以接受。"),
    ("lactose", "用户有轻微乳糖不耐，喝普通牛奶容易肚子不舒服。"),
    ("coffee", "用户喝咖啡通常选无糖美式，下午四点以后尽量不喝。"),
    ("penicillin", "用户对青霉素过敏，就医或用药时需要主动提醒。"),
    ("knee", "用户右膝旧伤，运动时避免高强度深蹲和长距离跑步。"),
    ("phone_budget", "用户换手机的预算大约四千元，更看重续航和拍照。"),
    ("japanese", "用户最近在学日语，每天计划复习二十个单词。"),
    ("low_pressure", "主动关心要自然、低压力，避免连续追问和说教。"),
    ("qq_duplicate", "之前 QQ 重复消息的排查重点是适配器重放与双通道路由。"),
    ("websocket_delivery", "WebSocket 写入成功不等于客户端收到，必须沿链路确认最终送达。"),
    ("local_llm", "本地对话模型使用 GGUF 和 C++ 推理后端，启动由环境开关控制。"),
    ("vocab_sources", "词汇学习要区分 daily 和 unfamiliar 两种来源，不能混淆来源标签。"),
    ("history_store", "原始聊天记录按 JSONL 持久化，关键词工具可以直接搜索历史消息。"),
    ("weighted_memory", "长期加权记忆把 embedding 以 Base64 写进 JSON，并由 C++ 做余弦检索。"),
    ("chroma_reference", "ChromaDB 原设计用于参考对话和知识库的向量召回，不负责保存聊天流水。"),
    ("telegram_lifecycle", "Telegram 客户端生命周期由主程序托管，避免重复启动轮询。"),
    ("test_required", "每次代码优化后都要提供验证脚本并实际运行确认效果。"),
]


QUERIES: list[tuple[str, str]] = [
    ("平常回答我是不是别绕太久？", "reply_concise"),
    ("真遇到难查的 bug 应该讲到什么程度？", "debug_detailed"),
    ("我最反感把可变逻辑写成哪种形式？", "config_first"),
    ("仓库里还有我的改动时你要注意什么？", "dirty_worktree"),
    ("跑这个项目的 Python 应该进哪个环境？", "python_venv"),
    ("安卓那边默认由谁负责编译？", "gradle_rule"),
    ("晚上几点该催我别玩手机了？", "sleep_reminder"),
    ("周一早晨什么时候喊我起来？", "wake_alarm"),
    ("周五下午那个安排具体是什么？", "friday_meeting"),
    ("国庆准备去哪座城市？", "october_trip"),
    ("五月中旬是谁过生日？", "mother_birthday"),
    ("我家那只胆小的宠物叫什么？", "cat_name"),
    ("点餐时哪种配菜不要放？", "no_cilantro"),
    ("我喝拿铁以后为什么可能不舒服？", "lactose"),
    ("下午想提神时我通常喝什么？", "coffee"),
    ("看医生开抗生素时必须说哪件事？", "penicillin"),
    ("我的腿不适合做哪些训练？", "knee"),
    ("四千左右选新机我主要在乎什么？", "phone_budget"),
    ("我每天外语词汇的复习量是多少？", "japanese"),
    ("主动来关心我的时候语气应该怎样？", "low_pressure"),
    ("上次企鹅消息发了两遍应该从哪里查？", "qq_duplicate"),
    ("服务端说写成功为什么还不能算送到了？", "websocket_delivery"),
    ("我的聊天流水实际上存在哪类文件里？", "history_store"),
    ("长期记忆向量是怎样落盘和搜索的？", "weighted_memory"),
    ("那个向量库原本召回的是什么，不是聊天记录吧？", "chroma_reference"),
    ("学习单词时为什么不能把两个列表直接混一起？", "vocab_sources"),
    ("改完代码后还需要补什么来证明有效？", "test_required"),
]


def _normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.clip(norms, 1e-12, None)


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def _load_onnx_encoder(
    model_path: Path,
    pooling: str,
    onnx_filename: str = "model.onnx",
) -> tuple[Callable, dict[str, Any]]:
    import onnxruntime as ort
    from transformers import AutoTokenizer

    onnx_path = model_path / "onnx" / onnx_filename
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 4
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.enable_mem_pattern = False
    options.enable_cpu_mem_arena = True

    before_rss = _rss_mb()
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    session = ort.InferenceSession(
        str(onnx_path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    load_seconds = time.perf_counter() - started
    input_names = {item.name for item in session.get_inputs()}

    def encode(texts: list[str]) -> np.ndarray:
        encoded = tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="np",
        )
        feed = {
            name: encoded[name].astype(np.int64, copy=False)
            for name in input_names
            if name in encoded
        }
        outputs = session.run(None, feed)
        hidden = np.asarray(outputs[0])
        if hidden.ndim == 2:
            vectors = hidden
        elif pooling == "cls":
            vectors = hidden[:, 0, :]
        else:
            mask = np.expand_dims(encoded["attention_mask"].astype(np.float32), -1)
            vectors = np.sum(hidden * mask, axis=1) / np.clip(
                np.sum(mask, axis=1), 1e-12, None
            )
        return _normalize(vectors)

    external_weight_paths = [
        Path(f"{onnx_path}.data"),
        Path(f"{onnx_path}_data"),
        Path(f"{onnx_path}_data_1"),
    ]
    weight_bytes = onnx_path.stat().st_size + sum(
        path.stat().st_size for path in external_weight_paths if path.is_file()
    )
    metadata = {
        "load_seconds": load_seconds,
        "rss_load_delta_mb": max(0.0, _rss_mb() - before_rss),
        "device": "cpu",
        "weight_mb": weight_bytes / (1024 * 1024),
    }
    return encode, metadata


def _last_token_pool(last_hidden: Any, attention_mask: Any) -> Any:
    import torch

    if bool((attention_mask[:, -1].sum() == attention_mask.shape[0]).item()):
        return last_hidden[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_indices = torch.arange(last_hidden.shape[0], device=last_hidden.device)
    return last_hidden[batch_indices, sequence_lengths]


def _load_qwen3_encoder(device: str) -> tuple[Callable, dict[str, Any]]:
    import torch
    import torch.nn.functional as functional
    from transformers import AutoModel, AutoTokenizer

    before_rss = _rss_mb()
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(str(QWEN3_PATH), local_files_only=True)
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = AutoModel.from_pretrained(
        str(QWEN3_PATH), local_files_only=True, dtype=dtype
    ).eval()
    model.to(device)
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
    load_seconds = time.perf_counter() - started

    task = (
        "Given a Chinese conversational memory query, retrieve the past memory "
        "that is most relevant to answering it."
    )

    def encode(texts: list[str], *, is_query: bool = False) -> np.ndarray:
        prepared = (
            [f"Instruct: {task}\nQuery:{text}" for text in texts]
            if is_query
            else texts
        )
        batches: list[np.ndarray] = []
        for start in range(0, len(prepared), 16):
            batch = prepared[start : start + 16]
            inputs = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            ).to(device)
            with torch.inference_mode():
                hidden = model(**inputs).last_hidden_state
                vectors = functional.normalize(
                    _last_token_pool(hidden, inputs["attention_mask"]), p=2, dim=1
                )
            batches.append(vectors.float().cpu().numpy())
        if device == "cuda":
            torch.cuda.synchronize()
        return np.vstack(batches).astype(np.float32)

    metadata = {
        "load_seconds": load_seconds,
        "rss_load_delta_mb": max(0.0, _rss_mb() - before_rss),
        "device": device,
        "weight_mb": (QWEN3_PATH / "model.safetensors").stat().st_size
        / (1024 * 1024),
    }
    if device == "cuda":
        metadata["gpu_peak_mb_after_load"] = torch.cuda.max_memory_allocated() / (
            1024 * 1024
        )
    return encode, metadata


def _evaluate(
    name: str,
    documents: np.ndarray,
    queries: np.ndarray,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    document_ids = [item[0] for item in DOCUMENTS]
    similarities = queries @ documents.T
    reciprocal_ranks: list[float] = []
    margins: list[float] = []
    top1_hits = 0
    top3_hits = 0
    misses: list[dict[str, Any]] = []

    for row, (query, expected_id) in enumerate(QUERIES):
        ranking = np.argsort(-similarities[row])
        expected_index = document_ids.index(expected_id)
        rank = int(np.where(ranking == expected_index)[0][0]) + 1
        reciprocal_ranks.append(1.0 / rank)
        top1_hits += int(rank == 1)
        top3_hits += int(rank <= 3)
        best_other = max(
            float(score)
            for index, score in enumerate(similarities[row])
            if index != expected_index
        )
        margins.append(float(similarities[row, expected_index]) - best_other)
        if rank != 1:
            misses.append(
                {
                    "query": query,
                    "expected": expected_id,
                    "rank": rank,
                    "top3": [
                        {
                            "id": document_ids[int(index)],
                            "score": round(float(similarities[row, int(index)]), 4),
                        }
                        for index in ranking[:3]
                    ],
                }
            )

    total = len(QUERIES)
    return {
        "model": name,
        "dimension": int(documents.shape[1]),
        "top1": top1_hits / total,
        "top3": top3_hits / total,
        "mrr": float(np.mean(reciprocal_ranks)),
        "mean_margin": float(np.mean(margins)),
        "min_margin": float(np.min(margins)),
        "miss_count": len(misses),
        "misses": misses,
        **metadata,
    }


def _time_encoding(
    encoder: Callable,
    *,
    qwen: bool = False,
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    document_texts = [item[1] for item in DOCUMENTS]
    query_texts = [item[0] for item in QUERIES]

    started = time.perf_counter()
    documents = encoder(document_texts)
    document_seconds = time.perf_counter() - started
    started = time.perf_counter()
    queries = encoder(query_texts, is_query=True) if qwen else encoder(query_texts)
    query_seconds = time.perf_counter() - started
    total_seconds = document_seconds + query_seconds
    return documents, queries, {
        "document_encode_seconds": document_seconds,
        "query_encode_seconds": query_seconds,
        "encode_seconds": total_seconds,
        "texts_per_second": (len(DOCUMENTS) + len(QUERIES)) / total_seconds,
    }


def _run_onnx(name: str, path: Path, pooling: str) -> dict[str, Any]:
    encoder, metadata = _load_onnx_encoder(path, pooling)
    documents, queries, timings = _time_encoding(encoder)
    result = _evaluate(name, documents, queries, {**metadata, **timings})
    del encoder
    gc.collect()
    return result


def _run_harrier() -> dict[str, Any]:
    base_encoder, metadata = _load_onnx_encoder(
        HARRIER_PATH, "mean", "model_q4.onnx"
    )
    task = (
        "Given a Chinese conversational memory query, retrieve the past memory "
        "that is most relevant to answering it."
    )

    def encode(texts: list[str], *, is_query: bool = False) -> np.ndarray:
        prepared = (
            [f"Instruct: {task}\nQuery: {text}" for text in texts]
            if is_query
            else texts
        )
        return base_encoder(prepared)

    documents, queries, timings = _time_encoding(encode, qwen=True)
    result = _evaluate(
        "harrier-0.6b-q4-1024-cpu",
        documents,
        queries,
        {**metadata, **timings},
    )
    gc.collect()
    return result


def _run_qwen3(device: str) -> list[dict[str, Any]]:
    encoder, metadata = _load_qwen3_encoder(device)
    documents, queries, timings = _time_encoding(encoder, qwen=True)
    common = {**metadata, **timings}
    if device == "cuda":
        import torch

        common["gpu_peak_mb"] = torch.cuda.max_memory_allocated() / (1024 * 1024)
    results = [_evaluate(f"qwen3-0.6b-1024-{device}", documents, queries, common)]

    # Qwen3 使用 MRL 训练，可以安全截取前 384 维后重新归一化，测试兼容现有维度。
    documents_384 = _normalize(documents[:, :384])
    queries_384 = _normalize(queries[:, :384])
    results.append(
        _evaluate(f"qwen3-0.6b-384-{device}", documents_384, queries_384, common)
    )
    del encoder, documents, queries
    gc.collect()
    return results


def _print_summary(results: list[dict[str, Any]]) -> None:
    print("\n模型对比（27 条查询，30 条候选记忆）")
    print(
        f"{'model':30} {'dim':>5} {'top1':>7} {'top3':>7} "
        f"{'mrr':>7} {'margin':>9} {'load_s':>8} {'enc_s':>8} {'text/s':>8}"
    )
    for item in results:
        print(
            f"{item['model']:30} {item['dimension']:5d} "
            f"{item['top1']:7.1%} {item['top3']:7.1%} {item['mrr']:7.3f} "
            f"{item['mean_margin']:9.3f} {item['load_seconds']:8.2f} "
            f"{item['encode_seconds']:8.2f} {item['texts_per_second']:8.1f}"
        )
    for item in results:
        if not item["misses"]:
            continue
        print(f"\n{item['model']} 的 Top-1 失误：")
        for miss in item["misses"]:
            predicted = ", ".join(row["id"] for row in miss["top3"])
            print(
                f"- {miss['query']} | 应为 {miss['expected']} | "
                f"排名 {miss['rank']} | 前三 {predicted}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--qwen-device", choices=("cpu", "cuda"), default="cpu"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    required = [
        MINILM_PATH / "onnx" / "model.onnx",
        BGE_PATH / "onnx" / "model.onnx",
        HARRIER_PATH / "onnx" / "model_q4.onnx_data",
        QWEN3_PATH / "model.safetensors",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("缺少本地模型文件：", *missing, sep="\n- ", file=sys.stderr)
        return 2

    results = [
        _run_onnx("current-minilm-384-cpu", MINILM_PATH, "mean"),
        _run_onnx("bge-small-zh-512-cpu", BGE_PATH, "cls"),
        _run_harrier(),
        *_run_qwen3(args.qwen_device),
    ]
    _print_summary(results)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n详细结果已写入：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
