"""UIE-mini模型下载和ONNX转换脚本。

使用步骤：
1. 安装依赖（在venv_core虚拟环境中）:
   pip install paddlepaddle paddlenlp paddle2onnx transformers

2. 运行本脚本:
   python scripts/setup/setup_uie_model.py

脚本会自动：
- 下载uie-mini模型（PaddleNLP会先写入用户缓存）
- 把完整Paddle模型复制到项目models目录
- 转换为ONNX格式
- 保存到 models/UIE/uie-mini/ 目录
- 提取vocab.txt供BertTokenizer使用
"""
import os
import shutil
import sys


def find_paddle_model_cache() -> str:
    """查找PaddleNLP的uie-mini模型缓存路径。"""
    # PaddleNLP默认缓存在 ~/.paddlenlp/taskflow/information_extraction/uie-mini/
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".paddlenlp", "taskflow", "information_extraction", "uie-mini"),
        os.path.join(home, ".cache", "paddlenlp", "taskflow", "information_extraction", "uie-mini"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def download_model():
    """用PaddleNLP Taskflow触发模型下载（不强制转 inference model）。"""
    print("[1/4] 下载uie-mini模型（首次运行会下载~200MB）...")
    try:
        from paddlenlp import Taskflow
    except ImportError:
        print("错误: 请先安装依赖: pip install paddlepaddle paddlenlp")
        sys.exit(1)

    # 触发下载（用 use_inference=False 避免静态图转换失败）
    try:
        ie = Taskflow(
            "information_extraction",
            schema=["测试"],
            model="uie-mini",
            use_inference=False,  # 直接用动态图，跳过 inference model 转换
        )
        ie("测试文本")
        print("  模型下载完成（动态图模式，无需 inference model）。")
    except Exception as e:
        print(f"  模型下载失败: {e}")
        sys.exit(1)


def find_model_files() -> dict:
    """查找模型文件路径。"""
    cache_path = find_paddle_model_cache()
    if not cache_path:
        print("错误: 找不到uie-mini模型缓存，请先运行下载步骤")
        sys.exit(1)

    print(f"  模型缓存路径: {cache_path}")

    # 查找模型文件
    model_files = {"cache_dir": cache_path}
    for root, dirs, files in os.walk(cache_path):
        for f in files:
            if f.endswith(".pdparams") or f.endswith(".pdmodel"):
                if "model" not in model_files:
                    model_files["model"] = os.path.join(root, f)
            elif f == "vocab.txt":
                model_files["vocab"] = os.path.join(root, f)
            elif f == "model_config.json":
                model_files["config"] = os.path.join(root, f)

    # 查找推理模型（ inference_model 目录）
    inference_dir = os.path.join(cache_path, "inference_model")
    if os.path.exists(inference_dir):
        for root, dirs, files in os.walk(inference_dir):
            for f in files:
                if f == "__model__":
                    model_files["pdmodel"] = os.path.join(root, f)
                elif f == "__params__":
                    model_files["pdparams"] = os.path.join(root, f)
                elif f == "vocab.txt":
                    model_files["vocab"] = os.path.join(root, f)

    return model_files


def convert_to_onnx(model_files: dict, output_dir: str):
    """将PaddlePaddle模型转换为ONNX格式（可选，失败时跳过）。"""
    print("[3/4] 转换为ONNX格式（可选）...")

    pdmodel = model_files.get("pdmodel")
    pdparams = model_files.get("pdparams") or model_files.get("model")

    if not pdmodel:
        print("  警告: inference.pdmodel 不存在（静态图转换失败），跳过 ONNX 转换")
        print("  提示: 将使用 PaddleNLP 动态图后端，推理速度稍慢但功能完全可用")
        return False

    try:
        import paddle2onnx
    except ImportError:
        print("  警告: paddle2onnx 未安装，跳过 ONNX 转换")
        print("  提示: pip install paddle2onnx 后可尝试转换")
        return False

    # ONNX输出路径
    onnx_dir = os.path.join(output_dir, "onnx")
    os.makedirs(onnx_dir, exist_ok=True)
    onnx_path = os.path.join(onnx_dir, "model.onnx")

    print(f"  输入: {pdmodel}")
    print(f"  输出: {onnx_path}")

    try:
        paddle2onnx.export(
            model_file=pdmodel,
            params_file=pdparams,
            save_file=onnx_path,
            opset_version=13,
        )
        print(f"  ONNX转换成功: {onnx_path}")
        return True
    except Exception as e:
        print(f"  ONNX转换失败: {e}")
        print("  将使用 PaddleNLP 动态图后端")
        return False


def copy_paddle_model(model_files: dict, output_dir: str) -> bool:
    """把Paddle模型完整复制到项目目录，避免运行时依赖个人缓存。"""
    print("[2/4] 复制Paddle模型到项目目录...")
    cache_dir = model_files.get("cache_dir")
    if not cache_dir or not os.path.isdir(cache_dir):
        print("  错误: 找不到可复制的Paddle模型缓存")
        return False

    shutil.copytree(cache_dir, output_dir, dirs_exist_ok=True)
    required_files = [
        os.path.join(output_dir, "vocab.txt"),
        os.path.join(output_dir, "static", "inference.json"),
        os.path.join(output_dir, "static", "inference.pdiparams"),
    ]
    missing = [path for path in required_files if not os.path.isfile(path)]
    if missing:
        print(f"  错误: 项目目录缺少Paddle推理文件: {missing}")
        return False

    print(f"  Paddle模型已复制: {output_dir}")
    return True


def verify(output_dir: str, onnx_success: bool) -> bool:
    """验证模型是否可用（ONNX 或 PaddleNLP）。"""
    print("[4/4] 验证模型...")

    if onnx_success:
        # 验证 ONNX 模型
        onnx_path = os.path.join(output_dir, "onnx", "model.onnx")
        vocab_path = os.path.join(output_dir, "vocab.txt")

        if not os.path.exists(onnx_path):
            print(f"  错误: ONNX模型不存在: {onnx_path}")
            return False

        if not os.path.exists(vocab_path):
            print(f"  错误: vocab.txt不存在: {vocab_path}")
            return False

        try:
            import onnxruntime as ort
            sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
            inputs = sess.get_inputs()
            outputs = sess.get_outputs()
            print("  ONNX模型加载成功")
            print(f"  输入: {[{'name': i.name, 'shape': i.shape} for i in inputs]}")
            print(f"  输出: {[{'name': o.name, 'shape': o.shape} for o in outputs]}")
            return True
        except Exception as e:
            print(f"  ONNX模型验证失败: {e}")
            return False
    else:
        # 验证项目目录内的Paddle静态图后端
        print("  ONNX不可用，验证项目目录内的Paddle Inference后端...")
        try:
            import paddle.inference as inference

            json_path = os.path.join(output_dir, "static", "inference.json")
            params_path = os.path.join(output_dir, "static", "inference.pdiparams")
            vocab_path = os.path.join(output_dir, "vocab.txt")
            for required_path in (json_path, params_path, vocab_path):
                if not os.path.isfile(required_path):
                    print(f"  Paddle推理文件不存在: {required_path}")
                    return False

            config = inference.Config(json_path, params_path)
            config.disable_gpu()
            inference.create_predictor(config)
            print(f"  项目内Paddle模型加载成功: {json_path}")
            return True
        except Exception as e:
            print(f"  Paddle Inference后端验证失败: {e}")
            return False


def main():
    print("=" * 60)
    print("UIE-mini模型下载脚本")
    print("=" * 60)

    # 输出目录
    output_dir = os.path.join(os.getcwd(), "models", "UIE", "uie-mini")
    os.makedirs(output_dir, exist_ok=True)
    print(f"输出目录: {output_dir}\n")

    # 1. 下载模型（动态图模式）
    download_model()

    # 2. 查找模型文件
    model_files = find_model_files()
    print(f"\n找到的模型文件: {model_files}\n")

    # 3. 把Paddle模型复制到项目目录，避免正式运行依赖个人缓存
    paddle_copy_success = copy_paddle_model(model_files, output_dir)

    # 4. 尝试转换ONNX（可选，失败时跳过）
    onnx_success = convert_to_onnx(model_files, output_dir)

    # 5. 验证
    success = paddle_copy_success and verify(output_dir, onnx_success)

    print("\n" + "=" * 60)
    if success:
        if onnx_success:
            print("UIE-mini模型设置完成（ONNX后端）！")
            print(f"模型路径: {output_dir}")
            print("\nONNX推理更快，优先使用。")
        else:
            print("UIE-mini模型设置完成（Paddle Inference后端）！")
            print(f"模型路径: {output_dir}")
            print("\n项目运行不再依赖用户目录中的PaddleNLP缓存。")
        print("\n现在可以在代码中使用:")
        print("  from core.services.data_ops.uie_extractor import get_uie_extractor")
        print("  extractor = get_uie_extractor()")
        print('  result = extractor.extract("我今天早上7点起的，吃了碗面条")')
    else:
        print("设置未完全成功，请检查上述错误信息。")
    print("=" * 60)


if __name__ == "__main__":
    main()
