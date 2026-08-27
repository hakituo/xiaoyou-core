"""文本与名称处理工具。

从 status_renderer.py 拆分而来，集中管理文本截断、可选值格式化、
模型名称清洗与"当前激活值"令牌化等纯函数工具。
"""

import os
import re


def _safe_text(s: str, limit: int = 32) -> str:
    """安全截断文本，超长时以省略号结尾。"""
    s = str(s or "").strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


def _fmt_optional(v, placeholder: str = "—") -> str:
    """格式化可选值：None 或空字符串返回占位符，否则转为字符串。"""
    if v is None:
        return placeholder
    if isinstance(v, str):
        s = v.strip()
        return s if s else placeholder
    return str(v)


def _to_active_tokens(current_value) -> set[str]:
    """将"当前激活值"（字典/列表/标量）归一化为字符串令牌集合。

    用于在列表图中判断某个条目是否为当前激活项。
    """
    tokens = set()

    def _add(value):
        s = str(value or "").strip()
        if s:
            tokens.add(s)

    if isinstance(current_value, dict):
        provider = str(current_value.get("provider") or "").strip()
        model = str(current_value.get("model") or "").strip()
        path = str(current_value.get("path") or "").strip()
        name = str(current_value.get("name") or "").strip()
        model_id = str(current_value.get("id") or "").strip()
        _add(provider)
        _add(model)
        _add(path)
        _add(name)
        _add(model_id)
        if provider and model:
            _add(f"{provider}:{model}")
            _add(f"cloud:{provider}:{model}")
    elif isinstance(current_value, (list, tuple, set)):
        for item in current_value:
            _add(item)
    else:
        _add(current_value)

    return tokens


def _display_name_only(value: str | None) -> str:
    """从模型路径/文件名中提取干净的显示名称。

    会去除路径、常见模型扩展名以及量化/版本标签（如 -Q4_K_M、_v1.2）。
    """
    v = str(value or "").strip()
    if not v:
        return ""
    if "/" in v or "\\" in v:
        vv = v.replace("\\", "/")
        v = os.path.basename(vv)

    # 去除常见模型扩展名
    for ext in [".gguf", ".bin", ".pt", ".pth", ".ckpt", ".safetensors", ".onnx"]:
        if v.lower().endswith(ext):
            v = v[: -len(ext)]
            break

    # 去除量化/版本标签（大小写不敏感）
    # 匹配 -Q4_K_M、.q4_0、_v1.2 等模式
    v = re.sub(r"[-._]q[0-9][a-z0-9_]*", "", v, flags=re.IGNORECASE)
    v = re.sub(r"[-._]v[0-9]+[a-z0-9.]*", "", v, flags=re.IGNORECASE)

    return v.strip()
