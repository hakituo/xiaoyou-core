"""校验 .env.example 与代码真实读取的环境变量一致。

守住的约定（2026-09-24 校正）：
1) 模板里每个键都必须有读取点 —— 历史上模板 43 个键里有 29 个是死键，
   照它配会以为生效了、其实没生效；
2) 必需键不能从模板里消失，否则新环境照模板配会漏掉关键项；
3) 本机 .env 里出现的键都应在模板中登记（发现漂移时给出告警，不阻断）。

判定「有读取点」的三条依据（与 config/README.md 的命名约定对应）：
- 代码里出现 os.getenv / os.environ.get / os.environ[] / set "X=" / $env:X；
- config/yaml/** 里出现 ${X}；
- 以 config/*.py 里声明的 env_prefix 开头（pydantic 前缀式配置）。
"""

from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 读取环境变量的代码位置
CODE_DIRS = (
    "core",
    "config",
    "routers",
    "services",
    "memory",
    "maintenance",
    "scripts",
    "clients",
    "training",
    "tools",
    "multimodal",
    "cpp_modules",
)
CODE_GLOBS = ("*.py", "*.ps1", "*.bat", "*.sh")

CODE_PATTERNS = (
    re.compile(r"""(?:getenv|environ\.get|environ\[|putenv)\s*\(\s*["']([A-Z][A-Z0-9_]+)["']"""),
    re.compile(r"""environ\s*\[\s*["']([A-Z][A-Z0-9_]+)["']\s*\]"""),
    re.compile(r"""set\s+"([A-Z][A-Z0-9_]+)="""),
    re.compile(r"""\$env:([A-Z][A-Z0-9_]+)"""),
)
YAML_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]+)\}")
ENV_PREFIX_PATTERN = re.compile(r"""env_prefix\s*=\s*["']([A-Z0-9_]+)["']""")
# 模板里允许出现 #注释行 与 KEY= 两种写法
TEMPLATE_LINE = re.compile(r"^\s*#?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
# 代码按角色/别名动态拼出来的键（静态扫描看不到字面量）。
# 别名后缀允许大小写混写：DEEPSEEK_API_KEY_Yeye → 别名 yeye（统一转小写）。
DYNAMIC_KEY_PATTERNS = (
    re.compile(r"^[A-Z][A-Z0-9_]*_API_KEY_[A-Za-z0-9_]+$"),  # <PROVIDER>_API_KEY_<别名>
    re.compile(r"^XIAOYOU_QQ_BOT_NUMBER(_[A-Z]+)?$"),  # 多 QQ 号按角色拼
)

# env 名写在配置里、由代码按配置值去读的间接引用（getenv 的字面量是变量）
INDIRECT_KEYS = {
    # config/model_config.py 的 web_search.providers.<x>.api_key_env，
    # 由 core/tools/implementations.py 的 os.environ.get(api_key_env) 读取
    "SERPER_API_KEY",
    "BOCHA_API_KEY",
}

# 新环境照模板配置时必须能看到的键
REQUIRED_KEYS = (
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "SILICONFLOW_API_KEY",
    "VOLC_APPID",
    "VOLC_API_KEY",
    "QWEATHER_API_HOST",
    "QWEATHER_CREDENTIAL_ID",
    "QWEATHER_PROJECT_ID",
    "QWEATHER_PRIVATE_KEY_PATH",
    "XIAOYOU_QQ_MASTER_ID",
)


def collect_code_keys() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    candidates: list[Path] = list(PROJECT_ROOT.glob("*.py"))  # main.py / launcher.py 等入口
    for sub in CODE_DIRS:
        base = PROJECT_ROOT / sub
        if not base.is_dir():
            continue
        for glob in CODE_GLOBS:
            candidates.extend(base.rglob(glob))

    for path in candidates:
        if "__pycache__" in path.parts or "node_modules" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in CODE_PATTERNS:
            for name in pattern.findall(text):
                found.setdefault(name, set()).add(
                    str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                )
    return found


def collect_yaml_keys() -> set[str]:
    keys: set[str] = set()
    for path in (PROJECT_ROOT / "config" / "yaml").rglob("*.yaml"):
        keys |= set(YAML_PATTERN.findall(path.read_text(encoding="utf-8")))
    return keys


def collect_env_prefixes() -> set[str]:
    prefixes: set[str] = set()
    for path in (PROJECT_ROOT / "config").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        prefixes |= set(ENV_PREFIX_PATTERN.findall(text))
    return prefixes


def read_template_keys() -> list[str]:
    keys = []
    for line in (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        match = TEMPLATE_LINE.match(line)
        if match:
            keys.append(match.group(1))
    return keys


def read_dotenv_keys() -> list[str]:
    path = PROJECT_ROOT / ".env"
    if not path.exists():
        return []
    keys = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match:
            keys.append(match.group(1))
    return keys


def has_reader(key: str, code_keys: set[str], yaml_keys: set[str], prefixes: set[str]) -> bool:
    if key in code_keys or key in yaml_keys or key in INDIRECT_KEYS:
        return True
    if key.startswith("XIAOYOU_") and prefixes:
        # 前缀式键由 pydantic 读取；静态扫描只能校验前缀合法
        return any(key.startswith(prefix) for prefix in prefixes)
    return any(pattern.match(key) for pattern in DYNAMIC_KEY_PATTERNS)


def verify_no_dead_keys() -> None:
    code = collect_code_keys()
    yaml_keys = collect_yaml_keys()
    prefixes = collect_env_prefixes()
    template_keys = read_template_keys()

    dead = [
        key
        for key in template_keys
        if not has_reader(key, set(code), yaml_keys, prefixes)
    ]
    assert not dead, (
        "这些键写在 .env.example 里但代码/yaml 没有任何读取点（死键，"
        "照它配不会生效）：\n    " + "\n    ".join(sorted(set(dead)))
    )
    print(f"  模板 {len(template_keys)} 个键（去重后 {len(set(template_keys))}）全部有读取点")


def verify_required_keys_present() -> None:
    template_keys = set(read_template_keys())
    missing = [key for key in REQUIRED_KEYS if key not in template_keys]
    assert not missing, (
        "必需键从 .env.example 丢失（新环境照模板配会漏）：\n    "
        + "\n    ".join(missing)
    )
    print(f"  必需键 {len(REQUIRED_KEYS)} 个全部在模板中")


def warn_about_local_drift() -> None:
    template_keys = set(read_template_keys())
    dotenv_keys = read_dotenv_keys()
    if not dotenv_keys:
        print("  未发现 .env（跳过本机漂移检查）")
        return
    drift = sorted(set(dotenv_keys) - template_keys)
    if drift:
        print(
            f"  [告警] .env 中有 {len(drift)} 个键未登记进 .env.example："
            + ", ".join(drift)
        )
    else:
        print(f"  .env 的 {len(dotenv_keys)} 个键都已在模板中登记")


def main() -> None:
    print("1/3 校验 .env.example 无死键")
    verify_no_dead_keys()
    print("2/3 校验必需键未从模板丢失")
    verify_required_keys_present()
    print("3/3 校验本机 .env 与模板无漂移")
    warn_about_local_drift()
    print("环境变量模板验证通过")


if __name__ == "__main__":
    main()
