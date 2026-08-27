#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量嵌入生成模块

负责生成文本的向量嵌入表示，支持语义相似度计算
"""

import logging
import os
import json
import numpy as np
from typing import List, Tuple, Optional, Dict, Any
import base64
import time
import threading

# 配置日志
logger = logging.getLogger(__name__)

# 默认模型配置
# 优先检测本地存在的模型
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_MODEL_PATH_BGE = os.path.join(
    PROJECT_ROOT, "models", "BERT", "bge-small-zh-v1.5"
)

# ── 职责界限 ──────────────────────────────────────────
# 记忆系统 embedding 统一使用 bge-small-zh-v1.5（中文，512 维，CLS pooling）：
#   - 路径：models/BERT/bge-small-zh-v1.5
#   - 用途：记忆向量检索（C++/Python 余弦）、加权记忆 embedding、MEMORY.md 偏好去重、
#           ChromaDB 参考对话/知识库召回、OpenAI 兼容 embedding 接口
#   - DataOps 零样本分类（core/services/data_ops/bert_definitions.py）同样用该模型
# 替换说明（2026-08）：原先记忆系统用 all-MiniLM-L6-v2（英文，384 维，mean pooling），
# 对中文口语化记忆检索区分度差（top1≈44%）。已用同一评测集（tests/scripts/memory/
# compare_embedding_models.py）对比 all-MiniLM-L6-v2 / bge-small-zh-v1.5 /
# Qwen3-Embedding-0.6B / harrier-oss-v1-0.6b，bge-small-zh-v1.5 兼顾召回（top1=96%、
# mrr=0.98）与加载/内存开销，故作为统一模型。
# 注意：切换后维度由 384 变为 512，需重建已有 ChromaDB 集合与长期/加权记忆的 embedding。
if os.path.exists(LOCAL_MODEL_PATH_BGE) and os.path.exists(
    os.path.join(LOCAL_MODEL_PATH_BGE, "config.json")
):
    DEFAULT_EMBEDDING_MODEL = LOCAL_MODEL_PATH_BGE
    EMBEDDING_DIMENSION = 512  # bge-small-zh-v1.5 的隐藏维度
    logger.info(
        f"检测到本地模型 bge-small-zh-v1.5，将优先使用: {DEFAULT_EMBEDDING_MODEL}"
    )
else:
    # 本地缺模型时的回退项（仍为 384 维，避免维度不一致导致检索报错）
    DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_DIMENSION = 384
    logger.info(f"未检测到本地 bge-small-zh 模型，使用默认配置: {DEFAULT_EMBEDDING_MODEL}")

MAX_BATCH_SIZE = 32  # 批量处理的最大文本数量


class EmbeddingGenerator:
    """
    向量嵌入生成器，负责文本到向量的转换和相似度计算
    """

    _instance = None
    _lock = threading.RLock()
    _initialized = False

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EmbeddingGenerator, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._model = None
            self._tokenizer = None
            self._ort_session = None
            self._ort_input_names = None
            self._ort_output_names = None
            self._backend_name = None
            self._backend_detail = None
            self._model_loaded = False
            self._loading_lock = threading.RLock()
            self._model_name = DEFAULT_EMBEDDING_MODEL
            self._use_hash_fallback = False
            self._last_error = None
            self._metrics: Dict[str, Any] = {}
            self._available = False
            EmbeddingGenerator._initialized = True

    def _env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        value = os.environ.get(key)
        if value is None:
            return default
        value = str(value).strip()
        return value if value else default

    def _env_bool(self, key: str, default: bool = False) -> bool:
        value = self._env(key)
        if value is None:
            return default
        return value.lower() in {"1", "true", "yes", "y", "on"}

    def _env_int(self, key: str, default: int) -> int:
        value = self._env(key)
        if value is None:
            return default
        try:
            return int(value)
        except Exception:
            return default

    def _candidate_onnx_paths(self) -> List[str]:
        candidates: List[str] = []
        explicit = self._env("XIAOYOU_EMBEDDING_ONNX_MODEL_PATH")
        if explicit:
            candidates.append(explicit)

        model_path = self._model_name
        if model_path:
            if os.path.isabs(model_path) and os.path.isdir(model_path):
                candidates.extend(
                    [
                        os.path.join(model_path, "model.onnx"),
                        os.path.join(model_path, "model_quantized.onnx"),
                        os.path.join(model_path, "onnx", "model.onnx"),
                        os.path.join(model_path, "onnx", "model_quantized.onnx"),
                    ]
                )
            else:
                potential_dir = os.path.join(
                    PROJECT_ROOT, "models", "embedding", model_path
                )
                if os.path.isdir(potential_dir):
                    candidates.extend(
                        [
                            os.path.join(potential_dir, "model.onnx"),
                            os.path.join(potential_dir, "model_quantized.onnx"),
                            os.path.join(potential_dir, "onnx", "model.onnx"),
                            os.path.join(potential_dir, "onnx", "model_quantized.onnx"),
                        ]
                    )

        local_dir = LOCAL_MODEL_PATH_BGE
        if os.path.isdir(local_dir):
            candidates.extend(
                [
                    os.path.join(local_dir, "model.onnx"),
                    os.path.join(local_dir, "model_quantized.onnx"),
                    os.path.join(local_dir, "onnx", "model.onnx"),
                    os.path.join(local_dir, "onnx", "model_quantized.onnx"),
                ]
            )

        unique: List[str] = []
        seen = set()
        for c in candidates:
            if not c:
                continue
            norm = os.path.normpath(c)
            if norm in seen:
                continue
            seen.add(norm)
            unique.append(norm)
        return unique

    def _resolve_tokenizer_path(self) -> Optional[str]:
        explicit = self._env("XIAOYOU_EMBEDDING_TOKENIZER_PATH")
        if explicit and os.path.exists(explicit):
            return explicit

        model_path = self._model_name
        if model_path:
            if os.path.isdir(model_path) and os.path.exists(
                os.path.join(model_path, "config.json")
            ):
                return model_path
            potential_dir = os.path.join(
                PROJECT_ROOT, "models", "embedding", model_path
            )
            if os.path.isdir(potential_dir) and os.path.exists(
                os.path.join(potential_dir, "config.json")
            ):
                return potential_dir

        if os.path.isdir(LOCAL_MODEL_PATH_BGE) and os.path.exists(
            os.path.join(LOCAL_MODEL_PATH_BGE, "config.json")
        ):
            return LOCAL_MODEL_PATH_BGE
        return None

    def _select_ort_providers(
        self, ort_module
    ) -> Tuple[List[Any], List[str], List[str]]:
        available = []
        try:
            available = list(ort_module.get_available_providers())
        except Exception:
            available = []

        # Check for forced CPU mode
        if self._env_bool("XIAOYOU_FORCE_CPU_EMBEDDING", False):
            priority_raw = "CPUExecutionProvider"
        else:
            priority_raw = self._env(
                "XIAOYOU_EMBEDDING_ORT_EP_PRIORITY",
                "QNNExecutionProvider,OpenVINOExecutionProvider,DmlExecutionProvider,CUDAExecutionProvider,CPUExecutionProvider",
            )
        priority = [p.strip() for p in str(priority_raw).split(",") if p.strip()]

        selected_names: List[str] = [p for p in priority if p in set(available)]
        if not selected_names and "CPUExecutionProvider" in available:
            selected_names = ["CPUExecutionProvider"]

        providers: List[Any] = []

        openvino_cache_dir = self._env("XIAOYOU_EMBEDDING_OPENVINO_CACHE_DIR")
        qnn_options_json = self._env("XIAOYOU_EMBEDDING_QNN_PROVIDER_OPTIONS_JSON")
        openvino_options_json = self._env(
            "XIAOYOU_EMBEDDING_OPENVINO_PROVIDER_OPTIONS_JSON"
        )

        qnn_options: Dict[str, Any] = {}
        if qnn_options_json:
            try:
                qnn_options = json.loads(qnn_options_json)
            except Exception:
                qnn_options = {}

        openvino_options: Dict[str, Any] = {}
        if openvino_options_json:
            try:
                openvino_options = json.loads(openvino_options_json)
            except Exception:
                openvino_options = {}
        if openvino_cache_dir and "cache_dir" not in openvino_options:
            openvino_options["cache_dir"] = openvino_cache_dir

        for name in selected_names:
            if name == "OpenVINOExecutionProvider" and openvino_options:
                providers.append((name, openvino_options))
            elif name == "QNNExecutionProvider" and qnn_options:
                providers.append((name, qnn_options))
            else:
                providers.append(name)
        return providers, selected_names, available

    def _normalize_embedding_dim(self, vec: np.ndarray) -> np.ndarray:
        if vec.ndim != 1:
            vec = np.asarray(vec).reshape(-1)
        if vec.shape[0] == EMBEDDING_DIMENSION:
            return vec.astype(np.float32, copy=False)
        if vec.shape[0] > EMBEDDING_DIMENSION:
            vec = vec[:EMBEDDING_DIMENSION]
        else:
            pad = np.zeros(EMBEDDING_DIMENSION - vec.shape[0], dtype=np.float32)
            vec = np.concatenate([vec.astype(np.float32, copy=False), pad], axis=0)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.astype(np.float32, copy=False)

    def _ort_encode_batch(self, texts: List[str]) -> List[np.ndarray]:
        from transformers import AutoTokenizer

        if self._ort_session is None:
            raise RuntimeError("ORT session not initialized")
        if self._tokenizer is None:
            tokenizer_path = self._resolve_tokenizer_path()
            if not tokenizer_path:
                raise RuntimeError("Tokenizer path not found")
            self._tokenizer = AutoTokenizer.from_pretrained(
                tokenizer_path, local_files_only=True
            )
        max_length = self._env_int("XIAOYOU_EMBEDDING_MAX_LENGTH", 256)
        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="np",
        )

        input_feed: Dict[str, Any] = {}
        assert self._ort_input_names is not None
        for name in self._ort_input_names:
            if name in encoded:
                value = encoded[name]
                if (
                    isinstance(value, np.ndarray)
                    and value.dtype.kind in {"i", "u"}
                    and value.dtype != np.int64
                ):
                    value = value.astype(np.int64, copy=False)
                input_feed[name] = value

        outputs = self._ort_session.run(None, input_feed)
        assert self._ort_output_names is not None
        output_map = {n: v for n, v in zip(self._ort_output_names, outputs)}

        if "sentence_embedding" in output_map:
            emb = output_map["sentence_embedding"]
        elif "embedding" in output_map:
            emb = output_map["embedding"]
        else:
            first = outputs[0]
            if isinstance(first, np.ndarray) and first.ndim == 3:
                last_hidden = first
                # bge-small-zh-v1.5 使用 CLS（第 0 个 token）作为句向量
                # （与 tests/scripts/memory/compare_embedding_models.py 的评测配置一致）
                emb = last_hidden[:, 0, :]
            else:
                emb = first

        emb = np.asarray(emb)
        if emb.ndim == 1:
            emb = np.expand_dims(emb, axis=0)

        result: List[np.ndarray] = []
        for i in range(emb.shape[0]):
            vec = emb[i]
            vec = vec.astype(np.float32, copy=False)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            result.append(self._normalize_embedding_dim(vec))
        return result

    def _try_init_ort_backend(self) -> bool:
        backend_pref = self._env("XIAOYOU_EMBEDDING_BACKEND", "auto")
        backend_pref = str(backend_pref).lower()
        if backend_pref not in {"auto", "ort", "onnx", "onnxruntime"}:
            return False

        onnx_paths = self._candidate_onnx_paths()
        onnx_path = None
        for p in onnx_paths:
            if os.path.isfile(p):
                onnx_path = p
                break
        if not onnx_path:
            return False

        import onnxruntime as ort
        from transformers import AutoTokenizer

        providers, selected_names, available = self._select_ort_providers(ort)
        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = 4
        sess_options.inter_op_num_threads = 4
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.enable_mem_pattern = False
        sess_options.enable_cpu_mem_arena = True

        start = time.time()
        session = ort.InferenceSession(
            onnx_path, sess_options=sess_options, providers=providers
        )
        load_s = time.time() - start

        tokenizer_path = self._resolve_tokenizer_path()
        if not tokenizer_path:
            raise RuntimeError("Tokenizer path not found")
        self._tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_path, local_files_only=True
        )

        self._ort_session = session
        self._ort_input_names = [i.name for i in session.get_inputs()]
        self._ort_output_names = [o.name for o in session.get_outputs()]
        self._backend_name = "onnxruntime"
        self._backend_detail = {
            "onnx_path": onnx_path,
            "tokenizer_path": tokenizer_path,
            "providers": selected_names,
            "available_providers": available,
            "ort_providers_effective": session.get_providers(),
        }
        self._metrics["ort_load_seconds"] = float(load_s)

        if self._env_bool("XIAOYOU_EMBEDDING_WARMUP", False):
            warm_start = time.time()
            _ = self._ort_encode_batch(["warmup"])
            self._metrics["ort_warmup_seconds"] = float(time.time() - warm_start)

        logger.info(
            "Embedding backend initialized: %s (%s)",
            self._backend_name,
            json.dumps(self._backend_detail, ensure_ascii=False),
        )
        return True

    def _load_model(self):
        """加载嵌入模型（懒加载）"""
        with self._loading_lock:
            if not self._model_loaded:
                try:
                    logger.info(f"开始加载嵌入模型: {self._model_name}")
                    start_time = time.time()

                    self._use_hash_fallback = False
                    self._last_error = None
                    self._backend_name = None
                    self._backend_detail = None
                    self._ort_session = None
                    self._tokenizer = None
                    self._ort_input_names = None
                    self._ort_output_names = None
                    self._model = None

                    try:
                        if self._try_init_ort_backend():
                            self._model_loaded = True
                            end_time = time.time()
                            logger.info(
                                "模型加载流程完成，耗时: %.2f秒",
                                end_time - start_time,
                            )
                            return
                    except Exception as e:
                        self._last_error = str(e)
                        logger.warning("ONNXRuntime 后端初始化失败，将回退: %s", e)

                    # 尝试导入sentence_transformers
                    try:
                        # HF_ENDPOINT 已在 main.py 启动时统一设置
                        # 忽略SSL验证错误（针对某些特定网络环境）
                        import ssl

                        try:
                            _create_unverified_https_context = (
                                ssl._create_unverified_context
                            )
                        except AttributeError:
                            pass
                        else:
                            ssl._create_default_https_context = (
                                _create_unverified_https_context
                            )

                        from sentence_transformers import SentenceTransformer

                        # 策略优化：强制离线加载。如果本地不存在模型，直接转为哈希后备方案。
                        # 绝对禁止在推理流程中触发联网下载，否则会导致严重的首 token 延迟。
                        logger.info(
                            f"正在检查本地 SentenceTransformer 模型: {self._model_name}"
                        )

                        # 增加 check_path 逻辑，确保如果是相对路径则指向 models/embedding
                        model_path = self._model_name
                        if not os.path.isabs(model_path) and not os.path.exists(
                            model_path
                        ):
                            potential_path = os.path.join(
                                PROJECT_ROOT, "models", "embedding", model_path
                            )
                            if os.path.exists(potential_path):
                                model_path = potential_path

                        if os.path.exists(model_path):
                            try:
                                logger.info(f"正在从本地加载模型: {model_path}")
                                # 强制使用CPU加载模型，避免占用显存导致LLM OOM
                                self._model = SentenceTransformer(
                                    model_path, device="cpu", local_files_only=True
                                )
                                self._use_hash_fallback = False
                                self._backend_name = "sentence_transformers"
                                self._backend_detail = {
                                    "model_path": model_path,
                                    "device": "cpu",
                                }
                                logger.info("模型加载成功")
                            except Exception as e:
                                logger.error(f"本地模型加载出错: {e}")
                                self._use_hash_fallback = True
                        else:
                            logger.warning(f"本地模型目录不存在: {model_path}")
                            # 尝试最后的挣扎：看看默认路径是否存在
                            if (
                                self._model_name != LOCAL_MODEL_PATH_BGE
                                and os.path.exists(LOCAL_MODEL_PATH_BGE)
                            ):
                                try:
                                    logger.info(
                                        f"尝试加载默认备选本地模型: {LOCAL_MODEL_PATH_BGE}"
                                    )
                                    self._model = SentenceTransformer(
                                        LOCAL_MODEL_PATH_BGE,
                                        device="cpu",
                                        local_files_only=True,
                                    )
                                    self._use_hash_fallback = False
                                    self._backend_name = "sentence_transformers"
                                    self._backend_detail = {
                                        "model_path": LOCAL_MODEL_PATH_BGE,
                                        "device": "cpu",
                                    }
                                    logger.info("成功加载默认备选本地模型")
                                except Exception:
                                    self._use_hash_fallback = True
                            else:
                                self._use_hash_fallback = True

                        if self._use_hash_fallback:
                            logger.warning("=" * 40)
                            logger.warning(
                                "!!! 警告：检测到模型缺失，已进入哈希后备模式 !!!"
                            )
                            logger.warning(
                                "请手动运行: python scripts/download_embedding_model.py"
                            )
                            logger.warning("=" * 40)

                    except Exception as e:
                        logger.warning(
                            f"无法加载 sentence_transformers 模型 ({e})，将使用哈希嵌入作为后备"
                        )
                        logger.warning(
                            "这可能是因为网络连接问题或模型文件缺失。系统将继续运行，但语义搜索能力将受限。"
                        )
                        self._use_hash_fallback = True

                    self._model_loaded = True

                    end_time = time.time()
                    logger.info(
                        f"模型加载流程完成，耗时: {end_time - start_time:.2f}秒"
                    )
                except Exception as e:
                    logger.error(f"加载嵌入模型流程发生未预期的错误: {e}")
                    logger.warning("启用简单哈希嵌入作为最后防线")
                    self._use_hash_fallback = True
                    self._model_loaded = True

    def ensure_model_loaded(self):
        """确保模型已加载"""
        if not self._model_loaded:
            self._load_model()

    def _generate_simple_hash_embedding(self, text: str) -> np.ndarray:
        """最后防线：基于哈希的简单嵌入"""
        vector = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
        # 简单分词
        import re

        words = re.findall(r"\w+", text.lower())
        if not words:
            return vector

        for word in words:
            # 简单的哈希映射
            h = 0
            for c in word:
                h = (31 * h + ord(c)) & 0xFFFFFFFF
            idx = h % EMBEDDING_DIMENSION
            vector[idx] += 1.0

        # 归一化
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        return vector

    def generate_embedding(self, text: str) -> np.ndarray:
        """
        生成单个文本的向量嵌入

        Args:
            text: 输入文本

        Returns:
            文本的向量表示（numpy数组）
        """
        self.ensure_model_loaded()

        try:
            # 确保输入是字符串
            if not isinstance(text, str):
                text = str(text)

            # 检查是否使用了哈希后备方案
            if hasattr(self, "_use_hash_fallback") and self._use_hash_fallback:
                return self._generate_simple_hash_embedding(text)

            if self._ort_session is not None:
                start = time.time()
                embedding = self._ort_encode_batch([text])[0]
                self._metrics["last_infer_ms"] = float((time.time() - start) * 1000.0)
                return embedding

            if self._model is None:
                return self._generate_simple_hash_embedding(text)

            start = time.time()
            embedding = self._model.encode([text], convert_to_numpy=True)[0]
            embedding = self._normalize_embedding_dim(np.asarray(embedding))
            self._metrics["last_infer_ms"] = float((time.time() - start) * 1000.0)
            return embedding
        except Exception as e:
            logger.error(f"生成向量嵌入失败: {e}")
            # 返回哈希嵌入作为最后的手段
            return self._generate_simple_hash_embedding(text)

    def generate_embeddings_batch(self, texts: List[str]) -> List[np.ndarray]:
        """
        批量生成文本向量嵌入

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个向量对应输入文本列表中的一项
        """
        self.ensure_model_loaded()

        try:
            # 确保所有输入都是字符串
            texts = [str(text) if not isinstance(text, str) else text for text in texts]

            # 分批次处理以避免内存问题
            embeddings = []
            for i in range(0, len(texts), MAX_BATCH_SIZE):
                batch = texts[i : i + MAX_BATCH_SIZE]

                if hasattr(self, "_use_hash_fallback") and self._use_hash_fallback:
                    batch_embeddings = [
                        self._generate_simple_hash_embedding(t) for t in batch
                    ]
                elif self._ort_session is not None:
                    start = time.time()
                    batch_embeddings = self._ort_encode_batch(batch)
                    self._metrics["last_infer_ms"] = float(
                        (time.time() - start) * 1000.0
                    )
                elif self._model is not None:
                    start = time.time()
                    batch_embeddings = self._model.encode(batch, convert_to_numpy=True)
                    batch_embeddings = [
                        self._normalize_embedding_dim(np.asarray(v))
                        for v in batch_embeddings
                    ]
                    self._metrics["last_infer_ms"] = float(
                        (time.time() - start) * 1000.0
                    )
                else:
                    batch_embeddings = [
                        np.zeros(EMBEDDING_DIMENSION, dtype=np.float32) for _ in batch
                    ]

                embeddings.extend(batch_embeddings)

            return embeddings
        except Exception as e:
            logger.error(f"批量生成向量嵌入失败: {e}")
            # 返回零向量列表作为默认值
            return [np.zeros(EMBEDDING_DIMENSION, dtype=np.float32) for _ in texts]

    @staticmethod
    def cosine_similarity(embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        try:
            dot_product = np.dot(embedding1, embedding2)
            norm1 = np.linalg.norm(embedding1)
            norm2 = np.linalg.norm(embedding2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return float(dot_product / (norm1 * norm2))
        except Exception as e:
            logger.error(f"计算余弦相似度失败: {e}")
            return 0.0

    @staticmethod
    def batch_cosine_similarity(
        query_embedding: np.ndarray,
        embeddings_matrix: np.ndarray,
    ) -> np.ndarray:
        """
        批量计算查询向量与多个候选向量之间的余弦相似度

        Args:
            query_embedding: 查询向量 (dim,)
            embeddings_matrix: 候选向量矩阵 (N, dim)

        Returns:
            相似度数组 (N,)
        """
        try:
            if embeddings_matrix.ndim == 1:
                embeddings_matrix = embeddings_matrix.reshape(1, -1)
            query_norm = np.linalg.norm(query_embedding)
            if query_norm == 0:
                return np.zeros(embeddings_matrix.shape[0], dtype=np.float32)
            norms = np.linalg.norm(embeddings_matrix, axis=1)
            safe_norms = np.where(norms > 0, norms, 1.0)
            dots = embeddings_matrix @ query_embedding
            similarities = dots / (safe_norms * query_norm)
            similarities[norms == 0] = 0.0
            return similarities.astype(np.float32)
        except Exception as e:
            logger.error(f"批量计算余弦相似度失败: {e}")
            return np.zeros(max(embeddings_matrix.shape[0], 1), dtype=np.float32)



    @staticmethod
    def embedding_to_base64(embedding: np.ndarray) -> str:
        """
        将向量转换为base64编码的字符串，用于存储

        Args:
            embedding: 向量数组

        Returns:
            base64编码的字符串
        """
        try:
            # 转换为bytes并编码
            embedding_bytes = embedding.astype(np.float32).tobytes()
            return base64.b64encode(embedding_bytes).decode("utf-8")
        except Exception as e:
            logger.error(f"向量转base64失败: {e}")
            return ""

    @staticmethod
    def base64_to_embedding(base64_str: str) -> np.ndarray:
        """
        将base64编码的字符串转换回向量

        Args:
            base64_str: base64编码的字符串

        Returns:
            向量数组
        """
        try:
            # 解码并转换为numpy数组
            embedding_bytes = base64.b64decode(base64_str)
            embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
            return embedding
        except Exception as e:
            logger.error(f"base64转向量失败: {e}")
            # 返回零向量
            return np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)




# 全局实例
_embedding_generator_instance = None


def get_embedding_generator() -> EmbeddingGenerator:
    """
    获取嵌入生成器的全局实例

    Returns:
        EmbeddingGenerator: 嵌入生成器实例
    """
    global _embedding_generator_instance
    if _embedding_generator_instance is None:
        _embedding_generator_instance = EmbeddingGenerator()
    return _embedding_generator_instance


# 创建全局实例供直接使用
embedding_generator = get_embedding_generator()
