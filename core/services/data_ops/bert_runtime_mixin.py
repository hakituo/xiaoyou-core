from core.utils.logger import get_logger
import hashlib
import json

import os
import time
from typing import Dict, List, Optional

import numpy as np
import onnxruntime as ort
# 直接从子模块导入，绕过 transformers 5.x _LazyModule 的延迟加载机制
# 避免在 asyncio.to_thread 多线程环境下触发竞态条件导致 ImportError
from transformers.models.auto.tokenization_auto import AutoTokenizer

from .bert_definitions import (
    CATEGORY_DEFINITIONS,
    DISCOURSE_DEFINITIONS,
    EMBEDDINGS_CACHE_DIR,
    IMPORTANCE_DEFINITIONS,
    INTENT_DEFINITIONS,
    MODEL_RELATIVE_PATH,
    ONNX_MODEL_RELATIVE_PATH,
    STATE_EVENT_DEFINITIONS,
    TOPIC_DEFINITIONS,
)


logger = get_logger("DataOps.BertAnalyzer")


class BertRuntimeMixin:
    def _initialize(self):
        try:
            from core.utils.common import get_project_root

            root = str(get_project_root())
        except Exception:
            root = os.getcwd()

        self.model_path = os.path.join(root, ONNX_MODEL_RELATIVE_PATH)
        self.tokenizer_path = os.path.join(root, MODEL_RELATIVE_PATH)
        self._cache_dir = os.path.join(root, EMBEDDINGS_CACHE_DIR)

        if not os.path.exists(self.model_path):
            logger.error("ONNX model not found at %s", self.model_path)
            return

        try:
            t_start = time.time()
            logger.info("Loading BERT ONNX model from %s...", self.model_path)

            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = 4
            sess_options.inter_op_num_threads = 4
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.enable_mem_pattern = False
            # [内存优化] 禁用 CPU 内存竞技场，防止 onnxruntime 预分配内存不释放
            # enable_cpu_mem_arena=True 会让 onnxruntime 维护一个内存池，每次推理后不归还给 OS，
            # RSS 只增不减。禁用后每次推理的临时内存会归还给 OS，轻微性能损失但避免内存膨胀。
            sess_options.enable_cpu_mem_arena = False

            self._session = ort.InferenceSession(
                self.model_path,
                sess_options=sess_options,
                providers=["CPUExecutionProvider"],
            )
            self._tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_path)

            t_model = time.time()
            logger.info("BERT ONNX model loaded in %.1fms", (t_model - t_start) * 1000)

            self._load_or_compute_embeddings()

            t_emb = time.time()
            logger.info("Embeddings ready in %.1fms", (t_emb - t_model) * 1000)

            logger.info(
                "BERT Analyzer initialized successfully in %.1fms (Zero-Shot Mode).",
                (time.time() - t_start) * 1000,
            )
        except Exception as e:
            logger.error("Failed to initialize BERT Analyzer: %s", e)
            self._session = None
            self._topic_embeddings = None
            self._importance_embeddings = None
            self._discourse_embeddings = None
            self._state_event_embeddings = None

    def _get_cache_key(self, definitions: Dict[str, List[str]]) -> str:
        content = json.dumps(definitions, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def _load_embeddings_from_cache(self, cache_key: str) -> Optional[Dict[str, np.ndarray]]:
        cache_file = os.path.join(self._cache_dir, f"{cache_key}.npz")
        if not os.path.exists(cache_file):
            return None
        try:
            data = np.load(cache_file, allow_pickle=True)
            return {key: data[key] for key in data.files}
        except Exception as e:
            logger.warning("Failed to load embeddings cache %s: %s", cache_key, e)
            return None

    def _save_embeddings_to_cache(self, cache_key: str, embeddings: Dict[str, np.ndarray]):
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            cache_file = os.path.join(self._cache_dir, f"{cache_key}.npz")
            np.savez(cache_file, **embeddings)
            logger.debug("Saved embeddings cache: %s", cache_key)
        except Exception as e:
            logger.warning("Failed to save embeddings cache %s: %s", cache_key, e)

    def _load_list_embeddings_from_cache(self, cache_key: str) -> Optional[Dict[str, List[np.ndarray]]]:
        cache_file = os.path.join(self._cache_dir, f"{cache_key}.npz")
        if not os.path.exists(cache_file):
            return None
        try:
            data = np.load(cache_file, allow_pickle=True)
            result = {}
            for key in data.files:
                val = data[key]
                if val.ndim == 0:
                    item = val.item()
                    result[key] = [np.array(v) for v in item] if isinstance(item, list) else []
                elif val.ndim in (2, 3):
                    result[key] = [val[i] for i in range(val.shape[0])]
                else:
                    result[key] = [val]
            return result if result else None
        except Exception as e:
            logger.warning("Failed to load list embeddings cache %s: %s", cache_key, e)
            return None

    def _save_list_embeddings_to_cache(self, cache_key: str, embeddings: Dict[str, List[np.ndarray]]):
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            cache_file = os.path.join(self._cache_dir, f"{cache_key}.npz")
            save_dict = {}
            for key, emb_list in embeddings.items():
                if emb_list:
                    save_dict[key] = np.stack(emb_list, axis=0)
            if save_dict:
                np.savez(cache_file, **save_dict)
                logger.debug("Saved list embeddings cache: %s", cache_key)
        except Exception as e:
            logger.warning("Failed to save list embeddings cache %s: %s", cache_key, e)

    def _load_or_compute_embeddings(self):
        cache_keys = {
            "category": self._get_cache_key(CATEGORY_DEFINITIONS),
            "intent": self._get_cache_key(INTENT_DEFINITIONS),
            "topic": self._get_cache_key(TOPIC_DEFINITIONS),
            "importance": self._get_cache_key(IMPORTANCE_DEFINITIONS),
            "discourse": self._get_cache_key(DISCOURSE_DEFINITIONS),
            "state_event": self._get_cache_key(STATE_EVENT_DEFINITIONS),
            "intent_examples": self._get_cache_key({k: v for k, v in INTENT_DEFINITIONS.items()}),
        }

        self._category_embeddings = self._load_embeddings_from_cache(cache_keys["category"])
        self._intent_embeddings = self._load_embeddings_from_cache(cache_keys["intent"])
        self._topic_embeddings = self._load_embeddings_from_cache(cache_keys["topic"])
        self._importance_embeddings = self._load_embeddings_from_cache(cache_keys["importance"])
        self._discourse_embeddings = self._load_embeddings_from_cache(cache_keys["discourse"])
        self._state_event_embeddings = self._load_embeddings_from_cache(cache_keys["state_event"])
        self._intent_example_embeddings = self._load_list_embeddings_from_cache(cache_keys["intent_examples"])

        all_cached = all(
            [
                self._category_embeddings,
                self._intent_embeddings,
                self._topic_embeddings,
                self._importance_embeddings,
                self._discourse_embeddings,
                self._state_event_embeddings,
                self._intent_example_embeddings,
            ]
        )
        if all_cached:
            logger.info("Loaded all embeddings from cache")
            return

        logger.info("Computing embeddings (cache miss)...")
        if not self._category_embeddings:
            self._category_embeddings = self._compute_embeddings_for_dict(CATEGORY_DEFINITIONS)
            self._save_embeddings_to_cache(cache_keys["category"], self._category_embeddings)
        if not self._intent_embeddings:
            self._intent_embeddings = self._compute_embeddings_for_dict(INTENT_DEFINITIONS)
            self._save_embeddings_to_cache(cache_keys["intent"], self._intent_embeddings)
        if not self._topic_embeddings:
            self._topic_embeddings = self._compute_embeddings_for_dict(TOPIC_DEFINITIONS)
            self._save_embeddings_to_cache(cache_keys["topic"], self._topic_embeddings)
        if not self._importance_embeddings:
            self._importance_embeddings = self._compute_embeddings_for_dict(IMPORTANCE_DEFINITIONS)
            self._save_embeddings_to_cache(cache_keys["importance"], self._importance_embeddings)
        if not self._discourse_embeddings:
            self._discourse_embeddings = self._compute_embeddings_for_dict(DISCOURSE_DEFINITIONS)
            self._save_embeddings_to_cache(cache_keys["discourse"], self._discourse_embeddings)
        if not self._state_event_embeddings:
            self._state_event_embeddings = self._compute_embeddings_for_dict(STATE_EVENT_DEFINITIONS)
            self._save_embeddings_to_cache(cache_keys["state_event"], self._state_event_embeddings)
        if not self._intent_example_embeddings:
            self._intent_example_embeddings = {}
            for key, keywords in INTENT_DEFINITIONS.items():
                embeddings = []
                clean_keywords = [str(kw).strip() for kw in keywords if str(kw).strip()]
                for emb in self._get_text_embeddings_batch(clean_keywords):
                    if emb is not None:
                        norm = np.linalg.norm(emb)
                        if norm > 0:
                            emb = emb / norm
                        embeddings.append(emb)
                if embeddings:
                    self._intent_example_embeddings[key] = embeddings
            self._save_list_embeddings_to_cache(
                cache_keys["intent_examples"], self._intent_example_embeddings
            )

    @staticmethod
    def _softmax(x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        x = x - np.max(x)
        ex = np.exp(x)
        s = float(np.sum(ex))
        if s <= 0:
            return np.zeros_like(ex, dtype=np.float64)
        return ex / s

    def _compute_embeddings_for_dict(self, definitions: Dict[str, List[str]]) -> Dict[str, np.ndarray]:
        result = {}
        for key, keywords in definitions.items():
            clean_keywords = [str(kw).strip() for kw in keywords if str(kw).strip()]
            embeddings = [emb for emb in self._get_text_embeddings_batch(clean_keywords) if emb is not None]
            if embeddings:
                proto_emb = np.mean(embeddings, axis=0)
                norm = np.linalg.norm(proto_emb)
                if norm > 0:
                    proto_emb = proto_emb / norm
                result[key] = proto_emb
        return result

    def _get_text_embeddings_batch(
        self, texts: List[str], batch_size: int = 32
    ) -> List[Optional[np.ndarray]]:
        normalized = [str(text).strip() for text in texts]
        if not self._session or not self._tokenizer:
            return [None] * len(normalized)
        if not normalized:
            return []
        safe_batch_size = max(1, int(batch_size))
        results: List[Optional[np.ndarray]] = [None] * len(normalized)
        try:
            for start in range(0, len(normalized), safe_batch_size):
                chunk = normalized[start : start + safe_batch_size]
                if not chunk:
                    continue
                inputs = self._tokenizer(
                    chunk, return_tensors="np", padding=True, truncation=True, max_length=128
                )
                ort_inputs = {
                    "input_ids": inputs["input_ids"].astype(np.int64),
                    "attention_mask": inputs["attention_mask"].astype(np.int64),
                }
                try:
                    outputs = self._session.run(["last_hidden_state"], ort_inputs)
                    batch = np.asarray(outputs[0])[:, 0, :]
                except Exception:
                    outputs = self._session.run(["pooler_output"], ort_inputs)
                    batch = np.asarray(outputs[0])
                if batch.ndim != 2:
                    raise ValueError("embedding batch shape invalid")
                for idx in range(min(len(chunk), batch.shape[0])):
                    emb = batch[idx]
                    norm = float(np.linalg.norm(emb))
                    if norm > 0:
                        emb = emb / norm
                    results[start + idx] = emb
            return results
        except Exception as e:
            logger.warning("Batch embedding failed, fallback to single inference: %s", e)
            for idx, text in enumerate(normalized):
                if not text:
                    continue
                results[idx] = self._get_text_embedding(text)
            return results

    def _get_text_embedding(self, text: str) -> Optional[np.ndarray]:
        if not self._session or not self._tokenizer:
            return None
        try:
            inputs = self._tokenizer(
                text, return_tensors="np", padding=True, truncation=True, max_length=128
            )
            ort_inputs = {
                "input_ids": inputs["input_ids"].astype(np.int64),
                "attention_mask": inputs["attention_mask"].astype(np.int64),
            }
            try:
                outputs = self._session.run(["last_hidden_state"], ort_inputs)
                cls_emb = outputs[0][0][0]
            except Exception:
                outputs = self._session.run(["pooler_output"], ort_inputs)
                cls_emb = outputs[0][0]
            norm = float(np.linalg.norm(cls_emb))
            if norm > 0:
                cls_emb = cls_emb / norm
            return cls_emb
        except Exception as e:
            logger.error("Error computing embedding for text '%s...': %s", text[:20], e)
            return None

    def _classify_with_generic_head(
        self,
        *,
        text: str,
        fallback_embeddings: Optional[Dict[str, np.ndarray]],
        content_emb: Optional[np.ndarray],
        fallback_default: str,
        min_confidence: float = 0.35,
    ) -> tuple[str, float]:
        if isinstance(fallback_embeddings, dict) and fallback_embeddings and content_emb is not None:
            best_label = fallback_default
            best_score = -1.0
            for label, proto_emb in fallback_embeddings.items():
                if proto_emb is None:
                    continue
                score = float(np.dot(content_emb, proto_emb))
                if score > best_score:
                    best_score = score
                    best_label = str(label)
            return best_label, max(0.0, min(1.0, best_score))

        return fallback_default, 0.0
