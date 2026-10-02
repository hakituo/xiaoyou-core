import sys
import types

import numpy as np


def _reset_embedding_singleton():
    import memory.embedding_generator as embedding_module

    embedding_module._embedding_generator_instance = None
    embedding_module.EmbeddingGenerator._instance = None
    # 复位类级初始化标记，否则新实例 __init__ 会提前 return，
    # 导致 _model_loaded 等实例属性未初始化
    embedding_module.EmbeddingGenerator._initialized = False
    return embedding_module


def test_embedding_hash_fallback_dimension_and_batch(monkeypatch):
    embedding_module = _reset_embedding_singleton()

    fake_st = types.ModuleType("sentence_transformers")
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)
    monkeypatch.delenv("XIAOYOU_EMBEDDING_ONNX_MODEL_PATH", raising=False)
    monkeypatch.setenv("XIAOYOU_EMBEDDING_BACKEND", "auto")

    gen = embedding_module.get_embedding_generator()

    v = gen.generate_embedding("测试文本")
    assert isinstance(v, np.ndarray)
    assert v.shape == (embedding_module.EMBEDDING_DIMENSION,)

    vs = gen.generate_embeddings_batch(["a", "b", "c"])
    assert len(vs) == 3
    assert all(isinstance(x, np.ndarray) for x in vs)
    assert all(x.shape == (embedding_module.EMBEDDING_DIMENSION,) for x in vs)


def test_embedding_ort_provider_priority(monkeypatch, tmp_path):
    embedding_module = _reset_embedding_singleton()

    onnx_path = tmp_path / "model.onnx"
    onnx_path.write_bytes(b"dummy")

    tokenizer_dir = tmp_path / "tok"
    tokenizer_dir.mkdir(parents=True, exist_ok=True)
    (tokenizer_dir / "config.json").write_text("{}", encoding="utf-8")

    class _IO:
        def __init__(self, name):
            self.name = name

    class FakeSession:
        def __init__(self, model_path, sess_options=None, providers=None):
            self.model_path = model_path
            self.providers = providers

        def get_inputs(self):
            return [_IO("input_ids"), _IO("attention_mask")]

        def get_outputs(self):
            return [_IO("last_hidden_state")]

        def get_providers(self):
            names = []
            for p in self.providers or []:
                if isinstance(p, tuple):
                    names.append(p[0])
                else:
                    names.append(p)
            return names

        def run(self, output_names, input_feed):
            batch = int(input_feed["input_ids"].shape[0])
            seq = int(input_feed["input_ids"].shape[1])
            hidden = embedding_module.EMBEDDING_DIMENSION
            out = np.ones((batch, seq, hidden), dtype=np.float32)
            return [out]

    class FakeSessionOptions:
        def __init__(self):
            self.enable_mem_pattern = True
            self.enable_cpu_mem_arena = True

    fake_ort = types.SimpleNamespace(
        SessionOptions=FakeSessionOptions,
        InferenceSession=FakeSession,
        GraphOptimizationLevel=types.SimpleNamespace(ORT_ENABLE_ALL="enabled"),
        get_available_providers=lambda: ["CPUExecutionProvider", "DmlExecutionProvider"],
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    import transformers

    class FakeTokenizer:
        def __call__(
            self,
            texts,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors=None,
        ):
            assert return_tensors == "np"
            batch = len(texts)
            seq = 8
            return {
                "input_ids": np.ones((batch, seq), dtype=np.int64),
                "attention_mask": np.ones((batch, seq), dtype=np.int64),
            }

    monkeypatch.setattr(
        transformers.AutoTokenizer,
        "from_pretrained",
        lambda *args, **kwargs: FakeTokenizer(),
        raising=True,
    )

    monkeypatch.setenv("XIAOYOU_EMBEDDING_BACKEND", "ort")
    monkeypatch.setenv("XIAOYOU_EMBEDDING_ONNX_MODEL_PATH", str(onnx_path))
    monkeypatch.setenv("XIAOYOU_EMBEDDING_TOKENIZER_PATH", str(tokenizer_dir))

    gen = embedding_module.get_embedding_generator()
    v = gen.generate_embedding("hello")
    assert v.shape == (embedding_module.EMBEDDING_DIMENSION,)

    assert gen._ort_session is not None
    assert gen._ort_session.providers == ["DmlExecutionProvider", "CPUExecutionProvider"]


def test_embedding_ort_cast_int32_to_int64(monkeypatch, tmp_path):
    embedding_module = _reset_embedding_singleton()

    onnx_path = tmp_path / "model.onnx"
    onnx_path.write_bytes(b"dummy")

    tokenizer_dir = tmp_path / "tok"
    tokenizer_dir.mkdir(parents=True, exist_ok=True)
    (tokenizer_dir / "config.json").write_text("{}", encoding="utf-8")

    class _IO:
        def __init__(self, name):
            self.name = name

    class FakeSession:
        def __init__(self, model_path, sess_options=None, providers=None):
            self.model_path = model_path
            self.providers = providers

        def get_inputs(self):
            return [_IO("input_ids"), _IO("attention_mask")]

        def get_outputs(self):
            return [_IO("last_hidden_state")]

        def get_providers(self):
            return ["CPUExecutionProvider"]

        def run(self, output_names, input_feed):
            assert input_feed["input_ids"].dtype == np.int64
            assert input_feed["attention_mask"].dtype == np.int64

            batch = int(input_feed["input_ids"].shape[0])
            seq = int(input_feed["input_ids"].shape[1])
            hidden = embedding_module.EMBEDDING_DIMENSION
            out = np.ones((batch, seq, hidden), dtype=np.float32)
            return [out]

    class FakeSessionOptions:
        def __init__(self):
            self.enable_mem_pattern = True
            self.enable_cpu_mem_arena = True

    fake_ort = types.SimpleNamespace(
        SessionOptions=FakeSessionOptions,
        InferenceSession=FakeSession,
        get_available_providers=lambda: ["CPUExecutionProvider"],
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    import transformers

    class FakeTokenizer:
        def __call__(
            self,
            texts,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors=None,
        ):
            assert return_tensors == "np"
            batch = len(texts)
            seq = 8
            return {
                "input_ids": np.ones((batch, seq), dtype=np.int32),
                "attention_mask": np.ones((batch, seq), dtype=np.int32),
            }

    monkeypatch.setattr(
        transformers.AutoTokenizer,
        "from_pretrained",
        lambda *args, **kwargs: FakeTokenizer(),
        raising=True,
    )

    monkeypatch.setenv("XIAOYOU_EMBEDDING_BACKEND", "ort")
    monkeypatch.setenv("XIAOYOU_EMBEDDING_ONNX_MODEL_PATH", str(onnx_path))
    monkeypatch.setenv("XIAOYOU_EMBEDDING_TOKENIZER_PATH", str(tokenizer_dir))

    gen = embedding_module.get_embedding_generator()
    v = gen.generate_embedding("hello")
    assert v.shape == (embedding_module.EMBEDDING_DIMENSION,)
