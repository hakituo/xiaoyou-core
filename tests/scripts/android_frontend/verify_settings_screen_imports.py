"""验证 SettingsScreenV2 使用的 Compose 尺寸扩展已正确导入。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/"
    "com/aveline/ai/mobile/presentation/settings/SettingsScreenV2.kt"
)


def main() -> None:
    """检查 padding 与 dp 的导入及调用，防止相同编译错误回归。"""
    source = SOURCE.read_text(encoding="utf-8")
    required = (
        "import androidx.compose.foundation.layout.padding",
        "import androidx.compose.ui.unit.dp",
        ".padding(horizontal = 16.dp)",
    )
    missing = [fragment for fragment in required if fragment not in source]
    if missing:
        raise AssertionError(f"SettingsScreenV2 缺少必要实现: {missing}")
    print("PASS: SettingsScreenV2 的 padding 与 dp 导入完整。")


if __name__ == "__main__":
    main()
