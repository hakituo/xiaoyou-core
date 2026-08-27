"""表情包向量索引构建脚本（离线一次性）

读取 data/memes/_index/semantic_metadata.json（增强版自带 caption），
用 bge-small-zh-v1.5 模型把 caption+tags 编码成向量，输出 numpy 内存索引：
- vectors.npy：N×512 浮点矩阵
- paths.json：N 个图片相对路径

运行时由 clients/bots/qq/meme_search.py 懒加载做余弦检索。

数据来源优先级：
1. semantic_metadata.json（增强版自带 caption，优先用）
2. descriptions.json（兜底，由 build_meme_descriptions.py 用 VL 模型生成）

用法：
    python -m scripts.meme.build_meme_vector_index
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.logger import get_logger

logger = get_logger("build_meme_vector_index")

MEMES_ROOT = PROJECT_ROOT / "data" / "memes"
INDEX_DIR = MEMES_ROOT / "_index"
SEMANTIC_METADATA_PATH = INDEX_DIR / "semantic_metadata.json"
DESCRIPTIONS_PATH = INDEX_DIR / "descriptions.json"  # 兜底
VECTORS_PATH = INDEX_DIR / "vectors.npy"
PATHS_PATH = INDEX_DIR / "paths.json"

# bge-small-zh-v1.5 模型路径（与 DataOps 共用）
BGE_MODEL_PATH = PROJECT_ROOT / "models" / "BERT" / "bge-small-zh-v1.5"
EMBEDDING_DIM = 512


def _load_items_from_semantic_metadata() -> list[tuple[str, str]]:
    """从 semantic_metadata.json 加载 (相对路径, caption+tags 文本) 列表。

    增强版格式：{images: {entry_id: {relative_path, caption, tags, visible_text, ...}}}
    relative_path 形如 "memes/angry/xxx.jpg"，需要转成 "angry/xxx.jpg"。
    """
    if not SEMANTIC_METADATA_PATH.is_file():
        return []
    try:
        with open(SEMANTIC_METADATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"读取 semantic_metadata.json 失败: {e}")
        return []
    images = data.get("images") if isinstance(data, dict) else None
    if not isinstance(images, dict):
        logger.error("semantic_metadata.json 格式错误：缺少 images 字段")
        return []
    result: list[tuple[str, str]] = []
    for entry_id, meta in images.items():
        if not isinstance(meta, dict):
            continue
        rel = meta.get("relative_path") or ""
        if not rel:
            continue
        # 去掉 "memes/" 前缀，转成相对 MEMES_ROOT 的路径
        if rel.startswith("memes/"):
            rel = rel[len("memes/"):]
        rel = rel.replace("\\", "/")
        caption = meta.get("caption") or ""
        tags = meta.get("tags") or []
        visible_text = meta.get("visible_text") or ""
        if not caption:
            continue
        # 组合 caption + tags + visible_text 作为 embedding 输入
        parts = [caption]
        if visible_text and visible_text not in caption:
            parts.append(f"画面文字：{visible_text}")
        if isinstance(tags, list) and tags:
            tag_str = "、".join(t for t in tags if isinstance(t, str) and t)
            if tag_str:
                parts.append(f"标签：{tag_str}")
        text = " | ".join(parts)
        result.append((rel, text))
    return result


def _load_items_from_descriptions() -> list[tuple[str, str]]:
    """从 descriptions.json 加载（兜底，VL 脚本生成的格式）。

    组合 caption + tags + text 作为 embedding 输入，语义更丰富：
    "卡通女仆张嘴伸手喊「别让我逮到你」...常在被对方气到后用来抱怨算账 | 标签：愤怒威胁、恼火追打 | 画面文字：别让我逮到你"
    """
    if not DESCRIPTIONS_PATH.is_file():
        return []
    try:
        with open(DESCRIPTIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"读取 descriptions.json 失败: {e}")
        return []
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    result: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        p = item.get("path")
        cap = item.get("caption")
        if not (p and cap):
            continue
        tags = item.get("tags") or []
        text = item.get("text") or ""
        # 组合三部分作为 embedding 输入
        parts = [str(cap)]
        if text and text not in cap:
            parts.append(f"画面文字：{text}")
        if isinstance(tags, list) and tags:
            tag_str = "、".join(t for t in tags if isinstance(t, str) and t)
            if tag_str:
                parts.append(f"标签：{tag_str}")
        combined = " | ".join(parts)
        result.append((str(p), combined))
    return result


def _load_bge_model():
    """加载 bge-small-zh-v1.5 模型，优先 ONNX，回退 sentence-transformers。"""
    onnx_path = BGE_MODEL_PATH / "onnx" / "model.onnx"
    if onnx_path.is_file():
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer
            logger.info(f"使用 ONNX 加载: {onnx_path}")
            tokenizer = AutoTokenizer.from_pretrained(str(BGE_MODEL_PATH))
            session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
            return ("onnx", tokenizer, session)
        except Exception as e:
            logger.warning(f"ONNX 加载失败，回退 sentence-transformers: {e}")

    try:
        from sentence_transformers import SentenceTransformer
        logger.info(f"使用 sentence-transformers 加载: {BGE_MODEL_PATH}")
        model = SentenceTransformer(str(BGE_MODEL_PATH), device="cpu")
        return ("st", None, model)
    except Exception as e:
        logger.error(f"sentence-transformers 加载失败: {e}")
        return (None, None, None)


def _encode_batch(backend, texts: list[str]) -> np.ndarray:
    """用 bge 模型批量编码，返回 N×512 矩阵。"""
    mode, tokenizer, model = backend
    if mode == "onnx":
        encoded = tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )
        # 与 DataOps bert_runtime_mixin.py 一致：只传 input_ids + attention_mask
        ort_inputs = {
            "input_ids": encoded["input_ids"].astype(np.int64),
            "attention_mask": encoded["attention_mask"].astype(np.int64),
        }
        try:
            outputs = model.run(["last_hidden_state"], ort_inputs)
            cls_vec = np.asarray(outputs[0])[:, 0, :]  # CLS pooling
        except Exception:
            outputs = model.run(["pooler_output"], ort_inputs)
            cls_vec = np.asarray(outputs[0])
        norms = np.linalg.norm(cls_vec, axis=1, keepdims=True)
        norms = np.where(norms > 0, norms, 1.0)
        return (cls_vec / norms).astype(np.float32)
    elif mode == "st":
        vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return np.asarray(vecs, dtype=np.float32)
    else:
        raise RuntimeError("bge 模型未加载")


def run() -> int:
    """主流程。返回处理的向量数。"""
    # 合并两个数据源：
    # - semantic_metadata.json（增强版自带，场景导向 caption）
    # - descriptions.json（VL 脚本生成，场景导向 caption）
    # 同一图片在两个源都有时，descriptions.json 优先（VL 新生成的质量更可控）
    meta_items = _load_items_from_semantic_metadata()
    desc_items = _load_items_from_descriptions()
    logger.info(
        f"数据源：semantic_metadata.json {len(meta_items)} 条，"
        f"descriptions.json {len(desc_items)} 条"
    )

    # 用 dict 去重：path -> text，descriptions 优先覆盖
    merged: dict[str, str] = {}
    for rel, text in meta_items:
        merged[rel] = text
    for rel, text in desc_items:
        merged[rel] = text  # 覆盖 semantic_metadata 的同路径条目
    items = list(merged.items())
    logger.info(f"合并去重后 {len(items)} 条 caption（descriptions.json 优先）")

    if not items:
        logger.error(
            "无可用 caption 数据。请：\n"
            "  1. 把增强版 semantic_metadata.json 放到 data/memes/_index/\n"
            "  2. 或运行 python -m scripts.meme.build_meme_descriptions 用 VL 生成"
        )
        return 0

    # 过滤掉图片文件已不存在的条目
    valid: list[tuple[str, str]] = []
    for rel, caption in items:
        if (MEMES_ROOT / rel).is_file():
            valid.append((rel, caption))
        else:
            logger.debug(f"图片不存在，跳过: {rel}")
    if not valid:
        logger.error("没有有效的图片-描述对（图片可能都已删除）")
        return 0
    logger.info(
        f"待编码：{len(valid)} 条（原 {len(items)} 条，跳过 {len(items)-len(valid)} 条失效）"
    )

    backend = _load_bge_model()
    if backend[0] is None:
        logger.error("bge 模型加载失败，请确认 models/BERT/bge-small-zh-v1.5/ 存在")
        return 0

    paths = [p for p, _ in valid]
    texts = [c for _, c in valid]

    # 分批编码避免内存峰值
    batch_size = 32
    all_vecs: list[np.ndarray] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        vecs = _encode_batch(backend, batch)
        all_vecs.append(vecs)
        logger.info(f"  编码 {min(i+batch_size, len(texts))}/{len(texts)}")

    matrix = np.vstack(all_vecs).astype(np.float32)
    logger.info(f"向量矩阵 shape: {matrix.shape}")

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(VECTORS_PATH, matrix)
    with open(PATHS_PATH, "w", encoding="utf-8") as f:
        json.dump(paths, f, ensure_ascii=False)
    logger.info(f"已保存向量到 {VECTORS_PATH} ({matrix.shape})")
    logger.info(f"已保存路径到 {PATHS_PATH} ({len(paths)} 条)")
    return matrix.shape[0]


def main() -> int:
    count = run()
    return 0 if count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
