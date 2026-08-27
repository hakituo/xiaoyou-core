"""
UIE信息抽取器。

用UIE模型从用户对话中提取结构化信息（作息时间、饮食、活动等），
取代extractor.py中的正则+关键词硬编码方式。

支持两种后端：
1. onnx - ONNX Runtime推理（推荐，需要先转换模型）
2. paddle - PaddleNLP Taskflow（开发验证用，需要安装paddlepaddle）

UIE的核心思想：把信息抽取转化为"标签-文本"的匹配问题，
通过start/end指针预测找到schema字段在文本中对应的span。
"""
from core.utils.logger import get_logger
import os
import re
# 关闭 PaddlePaddle C++ 后端的冗长日志（必须在导入 paddle 前设置）
os.environ["GLOG_minloglevel"] = "2"  # 只输出 ERROR 级别
os.environ["FLAGS_minloglevel"] = "2"
os.environ["FLAGS_eager_delete_tensor_gb"] = "0"


import threading
from typing import Any, Dict, List, Optional

from core.services.data_ops.uie_schema import (
    EXTRACTION_SCHEMA,
    MEAL_TYPE_NORMALIZE,
    MOOD_NORMALIZE,
)

logger = get_logger("UIE_EXTRACTOR")

# 模型路径配置。不能依赖进程启动目录，否则从仓库外启动服务时会错误回退到用户缓存。
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_UIE_MODEL_DIR = os.path.join(_PROJECT_ROOT, "models", "UIE", "uie-mini")
_UIE_ONNX_PATH = os.path.join(_UIE_MODEL_DIR, "onnx", "model.onnx")
_UIE_VOCAB_PATH = os.path.join(_UIE_MODEL_DIR, "vocab.txt")

# 推理参数
_DEFAULT_PROB_THRESHOLD = 0.5  # start/end概率阈值
_MAX_SEQ_LENGTH = 256  # 最大序列长度


def _clean_decoded_span(text: str) -> str:
    """移除BERT tokenizer在中文与数字字符之间插入的无意义空格。"""
    return re.sub(r"(?<=[\u3400-\u9fff0-9])\s+(?=[\u3400-\u9fff0-9])", "", text).strip()


class UIEExtractor:
    """UIE信息抽取器单例。

    用法：
        extractor = UIEExtractor()
        result = extractor.extract("我今天早上7点起的，吃了碗面条")
        # result = {
        #     "起床时间": [{"text": "7点", "probability": 0.95, "start": 6, "end": 8}],
        #     "吃的食物": [{"text": "面条", "probability": 0.92, "start": 12, "end": 14}],
        #     ...
        # }
    """

    _instance: Optional["UIEExtractor"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "UIEExtractor":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._backend: Optional[str] = None
        self._backend_model_path: Optional[str] = None
        self._onnx_session = None
        self._tokenizer = None
        self._paddle_ie = None
        self._init_backend()

    def _init_backend(self):
        """初始化推理后端，优先ONNX，回退PaddleNLP。"""
        # 优先尝试ONNX后端
        onnx_path = _UIE_ONNX_PATH
        vocab_path = _UIE_VOCAB_PATH
        if os.path.exists(onnx_path) and os.path.exists(vocab_path):
            try:
                self._init_onnx_backend(onnx_path, vocab_path)
                self._backend = "onnx"
                self._backend_model_path = onnx_path
                logger.info("UIE后端: ONNX Runtime (路径=%s)", onnx_path)
                return
            except Exception as e:
                logger.warning("ONNX后端初始化失败，尝试PaddleNLP后端: %s", e)

        # 回退到PaddleNLP后端
        try:
            self._init_paddle_backend()
            self._backend = "paddle"
            logger.info(
                "UIE后端: Paddle Inference (路径=%s)",
                self._backend_model_path,
            )
            return
        except Exception as e:
            logger.error(
                "UIE初始化失败。请安装依赖: pip install paddlepaddle paddlenlp\n"
                "或运行转换脚本生成ONNX模型: python scripts/setup/setup_uie_model.py\n"
                "错误: %s",
                e,
            )
            self._backend = None

    def _init_onnx_backend(self, onnx_path: str, vocab_path: str):
        """初始化ONNX Runtime后端。"""
        import numpy as np
        import onnxruntime as ort
        from transformers import BertTokenizer

        # 加载tokenizer（ERNIE兼容BertTokenizer）
        self._tokenizer = BertTokenizer(vocab_file=vocab_path)

        # 创建ONNX推理session
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # [内存优化] 禁用 CPU 内存竞技场，防止 onnxruntime 预分配内存不释放
        sess_options.enable_cpu_mem_arena = False
        self._onnx_session = ort.InferenceSession(
            onnx_path,
            sess_options=sess_options,
            providers=["CPUExecutionProvider"],
        )
        self._np = np

    def _init_paddle_backend(self):
        """初始化PaddleNLP推理后端（使用.json+.pdiparams新格式）。"""
        # 查找模型缓存路径
        home = os.path.expanduser("~")
        cache_candidates = [
            _UIE_MODEL_DIR,
            os.path.join(home, ".paddlenlp", "taskflow", "information_extraction", "uie-mini"),
            os.path.join(home, ".cache", "paddlenlp", "taskflow", "information_extraction", "uie-mini"),
        ]

        json_path = None
        params_path = None
        vocab_path = None
        for cache_dir in cache_candidates:
            if os.path.exists(cache_dir):
                static_dir = os.path.join(cache_dir, "static")
                json_path = os.path.join(static_dir, "inference.json")
                params_path = os.path.join(static_dir, "inference.pdiparams")
                vocab_path = os.path.join(cache_dir, "vocab.txt")  # vocab.txt 在 cache_dir，不在 static
                if os.path.exists(json_path) and os.path.exists(params_path) and os.path.exists(vocab_path):
                    self._backend_model_path = json_path
                    break

        # 关键：在 import paddle 之前就检查模型文件是否存在
        # paddle 一旦 import 就无法卸载（libpaddle.pyd 99MB + mklml.dll 80MB 常驻），
        # 如果模型文件不存在却先 import paddle，会导致 paddle 库无谓加载到进程内存里
        if not json_path or not os.path.exists(json_path):
            raise RuntimeError(
                "UIE-mini模型未下载或转换失败。请先运行 Taskflow 触发下载:\n"
                "from paddlenlp import Taskflow\n"
                "Taskflow('information_extraction', schema=['测试'], model='uie-mini')\n"
                "注意：Windows下转换可能失败，如果失败请手动触发第二次转换。"
            )

        import paddle  # noqa: F401  触发 paddle 主包初始化（paddle.inference 子模块需要主包已加载）
        import paddle.inference as inference

        # 创建推理配置
        config = inference.Config(json_path, params_path)
        config.switch_ir_optim(False)  # 关闭 IR 优化避免问题
        config.disable_gpu()  # 使用 CPU 推理（不是 enable_cpu）

        # 创建预测器
        self._paddle_predictor = inference.create_predictor(config)

        # 加载 tokenizer（用 BertTokenizer，ERNIE 兼容）
        from transformers import BertTokenizer
        self._tokenizer = BertTokenizer(vocab_file=vocab_path)

        # 获取输入输出 tensor
        self._input_names = self._paddle_predictor.get_input_names()
        self._output_names = self._paddle_predictor.get_output_names()

        logger.info("UIE推理后端加载成功: %s", json_path)

    def extract(
        self,
        text: str,
        schema: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """从文本中提取结构化信息。

        Args:
            text: 用户输入文本
            schema: 自定义schema字段列表，为None时用默认EXTRACTION_SCHEMA

        Returns:
            每个schema字段对应的提取结果列表，每个结果是
            {"text": "提取的文本", "probability": 0.95, "start": 6, "end": 8}
        """
        if not self._backend:
            return {}

        text = str(text or "").strip()
        if not text:
            return {}

        schema = schema or EXTRACTION_SCHEMA

        if self._backend == "onnx":
            return self._extract_onnx(text, schema)
        elif self._backend == "paddle":
            return self._extract_paddle(text, schema)
        return {}

    def _extract_paddle(
        self,
        text: str,
        schema: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """PaddleNLP推理后端。"""
        import numpy as np

        all_results: Dict[str, List[Dict[str, Any]]] = {}

        # UIE 需要逐个 schema 字段推理
        for field in schema:
            # 构造输入: [CLS] field [SEP] text [SEP]
            encoded = self._tokenizer(
                text=field,
                text_pair=text,
                max_length=_MAX_SEQ_LENGTH,
                truncation=True,
                return_tensors="np",  # 返回 numpy array
            )

            # 转换为正确的 dtype (embedding 需要 INT64)
            input_ids = encoded["input_ids"].astype(np.int64)
            token_type_ids = encoded["token_type_ids"].astype(np.int64)
            attention_mask = encoded["attention_mask"].astype(np.float32)  # attention_mask 用 FLOAT32

            # 生成 position_ids (INT64)
            seq_len = input_ids.shape[1]
            position_ids = np.arange(seq_len, dtype=np.int64).reshape(1, -1)

            # 创建输入 tensor
            input_ids_tensor = self._paddle_predictor.get_input_handle(self._input_names[0])
            input_ids_tensor.copy_from_cpu(input_ids)

            token_type_tensor = self._paddle_predictor.get_input_handle(self._input_names[1])
            token_type_tensor.copy_from_cpu(token_type_ids)

            position_tensor = self._paddle_predictor.get_input_handle(self._input_names[2])
            position_tensor.copy_from_cpu(position_ids)

            attention_tensor = self._paddle_predictor.get_input_handle(self._input_names[3])
            attention_tensor.copy_from_cpu(attention_mask)

            # 推理
            self._paddle_predictor.run()

            # 获取输出
            start_output = self._paddle_predictor.get_output_handle(self._output_names[0])
            end_output = self._paddle_predictor.get_output_handle(self._output_names[1])

            start_logits = start_output.copy_to_cpu()[0]  # [seq_len]
            end_logits = end_output.copy_to_cpu()[0]  # [seq_len]

            # 解码 span
            spans = self._decode_spans_paddle(
                start_logits,
                end_logits,
                input_ids[0],
                text,
                field,
            )
            if spans:
                all_results[field] = spans

        return all_results

    def _decode_spans_paddle(
        self,
        start_logits: Any,
        end_logits: Any,
        input_ids: Any,
        text: str,
        schema_field: str,
    ) -> List[Dict[str, Any]]:
        """解码动态图推理的 start/end 指针。"""
        spans: List[Dict[str, Any]] = []

        # 找到 text 开始位置（第一个 SEP 之后）
        sep_id = self._tokenizer.sep_token_id or 102
        text_start_idx = None
        sep_count = 0
        for i, tid in enumerate(input_ids):
            if tid == sep_id:
                sep_count += 1
                if sep_count == 1:
                    text_start_idx = i + 1
                    break

        if text_start_idx is None:
            return spans

        # 找到 text 结束位置
        text_end_idx = len(input_ids)
        for i in range(text_start_idx, len(input_ids)):
            if input_ids[i] == sep_id or input_ids[i] == self._tokenizer.pad_token_id:
                text_end_idx = i
                break

        # 在 text 范围内找 start > 阈值的位置
        start_indices = []
        for i in range(text_start_idx, text_end_idx):
            if start_logits[i] > _DEFAULT_PROB_THRESHOLD:
                start_indices.append(i)

        # 对每个 start，找最近的 end > 阈值的位置
        for start_idx in start_indices:
            for end_idx in range(start_idx, text_end_idx):
                if end_logits[end_idx] > _DEFAULT_PROB_THRESHOLD:
                    token_ids = input_ids[start_idx : end_idx + 1]
                    extracted_text = _clean_decoded_span(
                        self._tokenizer.decode(
                            token_ids,
                            skip_special_tokens=True,
                        )
                    )

                    if extracted_text:
                        probability = float(
                            (start_logits[start_idx] + end_logits[end_idx]) / 2
                        )
                        spans.append(
                            {
                                "text": extracted_text,
                                "probability": probability,
                                "start": int(start_idx - text_start_idx),
                                "end": int(end_idx - text_start_idx),
                            }
                        )
                    break

        return spans

    def _extract_onnx(
        self,
        text: str,
        schema: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """ONNX后端推理。

        UIE的输入格式: [CLS] schema_text [SEP] content [SEP]
        UIE的输出: start_logits + end_logits（每个token两个概率值）
        解码: 找start>阈值的位置，找对应的end>阈值的最近位置
        """
        np = self._np
        all_results: Dict[str, List[Dict[str, Any]]] = {}

        # UIE需要逐个schema字段推理（每个字段是一个独立的抽取任务）
        for field in schema:
            # 构造输入: [CLS] field [SEP] text [SEP]
            encoded = self._tokenizer.encode_plus(
                text=field,
                text_pair=text,
                max_length=_MAX_SEQ_LENGTH,
                padding="max_length",
                truncation=True,
                return_tensors="np",
            )

            input_ids = encoded["input_ids"].astype(np.int64)
            attention_mask = encoded["attention_mask"].astype(np.int64)
            token_type_ids = encoded["token_type_ids"].astype(np.int64)

            # ONNX推理
            try:
                outputs = self._onnx_session.run(
                    ["start_logits", "end_logits"],
                    {
                        "input_ids": input_ids,
                        "attention_mask": attention_mask,
                        "token_type_ids": token_type_ids,
                    },
                )
            except Exception as e:
                logger.debug("ONNX推理失败(field=%s): %s", field, e)
                continue

            start_logits = outputs[0][0]  # [seq_len]
            end_logits = outputs[1][0]  # [seq_len]

            # 解码：找start>阈值的token，然后找对应的end
            spans = self._decode_spans(
                start_logits,
                end_logits,
                input_ids[0],
                text,
                field,
            )
            if spans:
                all_results[field] = spans

        return all_results

    def _decode_spans(
        self,
        start_logits: Any,
        end_logits: Any,
        input_ids: Any,
        text: str,
        schema_field: str,
    ) -> List[Dict[str, Any]]:
        """解码start/end指针，提取实体span。

        UIE的解码逻辑：
        1. 找所有start > 阈值的位置
        2. 对每个start，找其后最近的end > 阈值的位置
        3. 从input_ids中提取对应的token，解码为文本
        """
        spans: List[Dict[str, Any]] = []

        # schema_field在token_type_ids=0的部分，text在token_type_ids=1的部分
        # 我们只在text部分（token_type_ids=1）寻找实体
        # input_ids结构: [CLS] schema_tokens [SEP] text_tokens [SEP] [PAD]...
        # 找到第二个SEP的位置（text开始之前）
        sep_id = self._tokenizer.sep_token_id or 102
        text_start_idx = None
        sep_count = 0
        for i, tid in enumerate(input_ids):
            if tid == sep_id:
                sep_count += 1
                if sep_count == 1:
                    text_start_idx = i + 1
                    break

        if text_start_idx is None:
            return spans

        # 找到text结束位置（第二个SEP或PAD开始）
        text_end_idx = len(input_ids)
        for i in range(text_start_idx, len(input_ids)):
            if input_ids[i] == sep_id or input_ids[i] == self._tokenizer.pad_token_id:
                text_end_idx = i
                break

        # 在text范围内找start > 阈值的位置
        start_indices = []
        for i in range(text_start_idx, text_end_idx):
            if start_logits[i] > _DEFAULT_PROB_THRESHOLD:
                start_indices.append(i)

        # 对每个start，找最近的end > 阈值的位置
        for start_idx in start_indices:
            for end_idx in range(start_idx, text_end_idx):
                if end_logits[end_idx] > _DEFAULT_PROB_THRESHOLD:
                    # 提取token并解码为文本
                    token_ids = input_ids[start_idx : end_idx + 1]
                    extracted_text = _clean_decoded_span(
                        self._tokenizer.decode(
                            token_ids,
                            skip_special_tokens=True,
                        )
                    )

                    if extracted_text:
                        probability = float(
                            (start_logits[start_idx] + end_logits[end_idx]) / 2
                        )
                        spans.append(
                            {
                                "text": extracted_text,
                                "probability": probability,
                                "start": int(start_idx - text_start_idx),
                                "end": int(end_idx - text_start_idx),
                            }
                        )
                    break  # 只取最近的end

        return spans

    def extract_normalized(
        self,
        text: str,
        schema: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """提取并标准化结果。

        返回标准化的字段：
        - wakeup_time: 起床时间（如"7点"）
        - sleep_time: 睡觉时间（如"23:00"）
        - food: 吃的食物（如"面条"）
        - meal_type: 餐次标准化（breakfast/lunch/dinner/late_night/snack）
        - drink: 喝的饮料
        - study_content: 学习内容
        - activity: 活动内容
        - symptom: 健康症状
        - mood: 情绪标准化（happy/sad/anxious等）
        """
        raw = self.extract(text, schema)
        if not raw:
            return {}

        result: Dict[str, Any] = {}

        # 起床时间
        if "起床时间" in raw and raw["起床时间"]:
            result["wakeup_time"] = raw["起床时间"][0]["text"]

        # 睡觉时间
        if "睡觉时间" in raw and raw["睡觉时间"]:
            result["sleep_time"] = raw["睡觉时间"][0]["text"]

        # 吃的食物
        if "吃的食物" in raw and raw["吃的食物"]:
            result["food"] = raw["吃的食物"][0]["text"]

        # 餐次标准化
        if "餐次" in raw and raw["餐次"]:
            meal_text = raw["餐次"][0]["text"]
            for keyword, standard in MEAL_TYPE_NORMALIZE.items():
                if keyword in meal_text:
                    result["meal_type"] = standard
                    break
            else:
                result["meal_type"] = "unknown"

        # 喝的饮料
        if "喝的饮料" in raw and raw["喝的饮料"]:
            result["drink"] = raw["喝的饮料"][0]["text"]

        # 学习内容
        if "学习内容" in raw and raw["学习内容"]:
            result["study_content"] = raw["学习内容"][0]["text"]

        # 活动内容
        if "活动内容" in raw and raw["活动内容"]:
            result["activity"] = raw["活动内容"][0]["text"]

        # 健康症状
        if "健康症状" in raw and raw["健康症状"]:
            result["symptom"] = raw["健康症状"][0]["text"]

        # 情绪标准化
        if "情绪" in raw and raw["情绪"]:
            mood_text = raw["情绪"][0]["text"]
            for keyword, standard in MOOD_NORMALIZE.items():
                if keyword in mood_text:
                    result["mood"] = standard
                    break
            else:
                result["mood"] = mood_text  # 保留原文

        return result


# 单例获取函数
def get_uie_extractor() -> UIEExtractor:
    """获取UIE提取器单例。"""
    return UIEExtractor()
