"""验证UIE优先从项目models目录加载，而不是依赖用户缓存。"""

import os
import sys


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def main() -> int:
    """检查本地模型完整性、实际加载路径与基础抽取能力。"""
    model_dir = os.path.join(PROJECT_ROOT, "models", "UIE", "uie-mini")
    required_files = [
        os.path.join(model_dir, "vocab.txt"),
        os.path.join(model_dir, "static", "inference.json"),
        os.path.join(model_dir, "static", "inference.pdiparams"),
    ]
    missing = [path for path in required_files if not os.path.isfile(path)]
    if missing:
        print(f"[FAIL] 项目目录缺少UIE模型文件: {missing}")
        return 1

    from core.services.data_ops.uie_extractor import get_uie_extractor

    extractor = get_uie_extractor()
    backend_path = os.path.abspath(str(extractor._backend_model_path or ""))
    if extractor._backend != "paddle":
        print(f"[FAIL] 预期Paddle后端，实际为: {extractor._backend}")
        return 1
    if os.path.commonpath([backend_path, model_dir]) != os.path.abspath(model_dir):
        print(f"[FAIL] UIE仍从项目外加载: {backend_path}")
        return 1

    result = extractor.extract("我今天早上7点起的", ["起床时间"])
    spans = result.get("起床时间") or []
    if not spans:
        print(f"[FAIL] 项目内模型加载成功，但基础抽取失败: {result}")
        return 1
    extracted_text = str(spans[0].get("text") or "")
    if extracted_text != "今天早上7点":
        print(f"[FAIL] 中文span仍含异常空格或内容错误: {extracted_text!r}")
        return 1

    print(f"[OK] backend={extractor._backend}")
    print(f"[OK] model_path={backend_path}")
    print(f"[OK] extraction={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
