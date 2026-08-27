"""
将 bge-small-zh-v1.5 导出为 ONNX 格式（支持动态 batch）
"""
import os
import numpy as np

MODEL_DIR = os.path.join("models", "BERT", "bge-small-zh-v1.5")
ONNX_OUTPUT_DIR = os.path.join(MODEL_DIR, "onnx")

def export_onnx():
    from transformers import BertModel, BertTokenizer
    import onnxruntime as ort
    import torch

    print(f"加载模型: {MODEL_DIR}")
    tokenizer = BertTokenizer.from_pretrained(MODEL_DIR)
    model = BertModel.from_pretrained(MODEL_DIR)
    model.eval()

    os.makedirs(ONNX_OUTPUT_DIR, exist_ok=True)
    onnx_path = os.path.join(ONNX_OUTPUT_DIR, "model.onnx")

    texts = ["这是一个测试句子", "另一个测试句子"]
    dummy_input = tokenizer(
        texts, return_tensors="pt", padding=True, truncation=True, max_length=128
    )

    print("导出 ONNX（动态 batch + 动态 seq_len）...")
    with torch.no_grad():
        torch.onnx.export(
            model,
            (dummy_input["input_ids"], dummy_input["attention_mask"]),
            onnx_path,
            input_names=["input_ids", "attention_mask"],
            output_names=["last_hidden_state", "pooler_output"],
            dynamic_axes={
                "input_ids": {0: "batch_size", 1: "seq_len"},
                "attention_mask": {0: "batch_size", 1: "seq_len"},
                "last_hidden_state": {0: "batch_size", 1: "seq_len"},
                "pooler_output": {0: "batch_size"},
            },
            opset_version=14,
            do_constant_folding=False,
        )

    print(f"ONNX 导出完成: {onnx_path}")

    print("验证单条推理...")
    sess_options = ort.SessionOptions()
    sess_options.intra_op_num_threads = 4
    session = ort.InferenceSession(onnx_path, sess_options=sess_options, providers=["CPUExecutionProvider"])

    single = tokenizer("单条测试", return_tensors="np", padding=True, truncation=True, max_length=128)
    out = session.run(["last_hidden_state"], {
        "input_ids": single["input_ids"].astype(np.int64),
        "attention_mask": single["attention_mask"].astype(np.int64),
    })
    print(f"  单条 shape: {out[0].shape}")

    print("验证 batch=32 推理...")
    batch_texts = [f"测试句子{i}" for i in range(32)]
    batch_input = tokenizer(batch_texts, return_tensors="np", padding=True, truncation=True, max_length=128)
    out = session.run(["last_hidden_state"], {
        "input_ids": batch_input["input_ids"].astype(np.int64),
        "attention_mask": batch_input["attention_mask"].astype(np.int64),
    })
    print(f"  batch=32 shape: {out[0].shape}")

    print("验证精度...")
    with torch.no_grad():
        pt_out = model(**dummy_input)
    ort_out = session.run(["last_hidden_state"], {
        "input_ids": dummy_input["input_ids"].numpy().astype(np.int64),
        "attention_mask": dummy_input["attention_mask"].numpy().astype(np.int64),
    })
    diff = np.abs(pt_out.last_hidden_state.numpy() - ort_out[0]).max()
    print(f"  PyTorch vs ONNX 最大差异: {diff:.8f}")

    if diff < 1e-5:
        print("✓ ONNX 导出验证通过！")
    else:
        print("⚠ 精度差异偏大，但通常可接受")

    file_size_mb = os.path.getsize(onnx_path) / (1024 * 1024)
    data_path = os.path.join(ONNX_OUTPUT_DIR, "model.onnx.data")
    data_mb = os.path.getsize(data_path) / (1024 * 1024) if os.path.exists(data_path) else 0
    print(f"  model.onnx: {file_size_mb:.1f} MB")
    print(f"  model.onnx.data: {data_mb:.1f} MB")
    print(f"  总计: {file_size_mb + data_mb:.1f} MB")

if __name__ == "__main__":
    export_onnx()
