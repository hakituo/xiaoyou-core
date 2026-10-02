# -*- coding: utf-8 -*-
"""``config/patch_qwen_tts.py`` 的单元测试。

该模块是给 qwen_tts 打文本补丁的脚本：模块级只做路径推导（无落盘副作用），
真正的写文件全部发生在 :func:`main` 内。

因此本测试文件的原则是：
1. 所有会写盘的调用都把 ``MODELING_FILE`` / ``TOKENIZER_FILE`` 指向 ``tmp_path``，
   **绝不触碰真实 venv 里的 site-packages**；
2. ``__main__`` 入口用 ``runpy`` 以 ``__main__`` 身份重跑源码，
   并通过改写 ``sys.executable`` 把推导出的路径导流到临时目录。
"""
from __future__ import annotations

import runpy
import sys
import warnings

import pytest

from config import patch_qwen_tts as mod

# --------------------------------------------------------------------------
# 被测源码里的原始片段（必须与 patch_qwen_tts.py 中的字符串逐字符一致）
# --------------------------------------------------------------------------

# 补丁 1a：modeling 文件 mask_kwargs 旧块（12 空格缩进）
MODELING_OLD_A = '''            mask_kwargs = {
                "config": self.config,
                "inputs_embeds": inputs_embeds,
                "attention_mask": attention_mask,
                "past_key_values": past_key_values,
            }'''

# 补丁 1b：modeling 文件直接传参旧块（8 空格缩进）
MODELING_OLD_B = '''        causal_mask = mask_function(
            config=self.config,
            inputs_embeds=inputs_embeds,
            attention_mask=attention_mask,
            past_key_values=past_key_values,
            position_ids=text_position_ids,
        )'''

# 补丁 2a：tokenizer 文件 mask_kwargs 旧块（比 1a 多一行 position_ids）
TOKENIZER_OLD_A = '''            mask_kwargs = {
                "config": self.config,
                "inputs_embeds": inputs_embeds,
                "attention_mask": attention_mask,
                "past_key_values": past_key_values,
                "position_ids": position_ids,
            }'''

# 补丁 2b：装饰器旧写法
TOKENIZER_OLD_B = "    @check_model_inputs\n    @auto_docstring"


def _modeling_source() -> str:
    """构造一份「补丁 1a/1b 都还没打」的 modeling 文件内容。"""
    return (
        "# modeling_qwen3_tts.py\n"
        "class Qwen3TTS:\n"
        "    def forward(self):\n"
        + MODELING_OLD_A
        + "\n"
        "        # 内部会调用 create_causal_mask\n"
        + MODELING_OLD_B
        + "\n"
    )


def _tokenizer_source() -> str:
    """构造一份「补丁 2a/2b 都还没打」的 tokenizer 文件内容。"""
    return (
        "# modeling_qwen3_tts_tokenizer_v2.py\n"
        "class Tokenizer:\n"
        + TOKENIZER_OLD_B
        + "\n"
        "    def forward(self):\n"
        + TOKENIZER_OLD_A
        + "\n"
    )


def _point_to_tmp(monkeypatch, tmp_path, modeling_text: str | None, tokenizer_text: str | None):
    """把模块级两个目标路径改到 tmp_path，并按需写入初始内容。

    返回 (modeling_path, tokenizer_path)。``None`` 表示故意不创建该文件。
    """
    modeling = tmp_path / "qwen_tts" / "core" / "models" / "modeling_qwen3_tts.py"
    tokenizer = (
        tmp_path / "qwen_tts" / "core" / "tokenizer_12hz"
        / "modeling_qwen3_tts_tokenizer_v2.py"
    )
    for path, text in ((modeling, modeling_text), (tokenizer, tokenizer_text)):
        if text is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    monkeypatch.setattr(mod, "MODELING_FILE", str(modeling))
    monkeypatch.setattr(mod, "TOKENIZER_FILE", str(tokenizer))
    return modeling, tokenizer


# --------------------------------------------------------------------------
# patch_file
# --------------------------------------------------------------------------


def test_patch_file_missing_file_returns_false(tmp_path, capsys):
    """文件不存在时返回 False，并打印「跳过」。"""
    missing = tmp_path / "nope.py"

    assert mod.patch_file(str(missing), "old", "new", "描述") is False

    out = capsys.readouterr().out
    assert "[跳过]" in out
    assert str(missing) in out
    # 不得凭空创建文件
    assert not missing.exists()


def test_patch_file_already_patched_returns_true(tmp_path, capsys):
    """new 已在文件中 → 判定「已修复」，返回 True，且不重复写入。"""
    target = tmp_path / "a.py"
    target.write_text("prefix\nNEW_MARK\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    assert mod.patch_file(str(target), "OLD_MARK", "NEW_MARK", "描述A") is True

    out = capsys.readouterr().out
    assert "[已修复]" in out
    assert "描述A" in out
    # 幂等：文件内容保持不变
    assert target.read_text(encoding="utf-8") == before


def test_patch_file_old_not_found_returns_true(tmp_path, capsys):
    """既无 new 也无 old（新版已自行修好）→ 返回 True，内容不变。"""
    target = tmp_path / "b.py"
    target.write_text("完全无关的内容\n", encoding="utf-8")

    assert mod.patch_file(str(target), "OLD_MARK", "NEW_MARK", "描述B") is True

    out = capsys.readouterr().out
    assert "[无需修复]" in out
    assert "描述B" in out
    assert target.read_text(encoding="utf-8") == "完全无关的内容\n"


def test_patch_file_empty_file_hits_not_found_branch(tmp_path, capsys):
    """空文件属于边界：old 必然找不到，走「无需修复」分支。"""
    target = tmp_path / "empty.py"
    target.write_text("", encoding="utf-8")

    assert mod.patch_file(str(target), "OLD_MARK", "NEW_MARK", "描述C") is True

    assert "[无需修复]" in capsys.readouterr().out
    assert target.read_text(encoding="utf-8") == ""


def test_patch_file_applies_replacement_and_writes(tmp_path, capsys):
    """old 命中时真正落盘替换，且只替换一次。"""
    target = tmp_path / "c.py"
    target.write_text("head\nOLD_MARK\nOLD_MARK\n", encoding="utf-8")

    assert mod.patch_file(str(target), "OLD_MARK", "NEW_MARK", "描述D") is True

    out = capsys.readouterr().out
    assert "[已修复]" in out
    content = target.read_text(encoding="utf-8")
    assert content == "head\nNEW_MARK\nNEW_MARK\n"
    assert "OLD_MARK" not in content


def test_patch_file_prefers_already_patched_over_replacing(tmp_path, capsys):
    """当 new 与 old 同时存在时，先判 new 命中 → 直接返回、不替换 old。

    这里固化的是当前实现的行为（记录为已知局限：此时 old 会残留），
    并非认定该行为正确，源码未做改动。
    """
    target = tmp_path / "d.py"
    target.write_text("NEW_MARK\nOLD_MARK\n", encoding="utf-8")

    assert mod.patch_file(str(target), "OLD_MARK", "NEW_MARK", "描述E") is True

    assert "[已修复]" in capsys.readouterr().out
    # 因为提前返回，文件原样保留（OLD_MARK 残留）
    assert target.read_text(encoding="utf-8") == "NEW_MARK\nOLD_MARK\n"


def test_patch_file_uses_utf8_for_non_ascii_content(tmp_path, capsys):
    """非 ASCII 内容能正确读回，确认读写都显式用了 utf-8。"""
    target = tmp_path / "e.py"
    target.write_text("# 中文注释\n旧代码\n", encoding="utf-8")

    assert mod.patch_file(str(target), "旧代码", "新代码", "中文描述") is True

    out = capsys.readouterr().out
    assert "中文描述" in out
    assert target.read_text(encoding="utf-8") == "# 中文注释\n新代码\n"


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def test_main_applies_all_four_patches_and_is_idempotent(tmp_path, monkeypatch, capsys):
    """正常路径：四个补丁全部生效，验证通过，二次运行仍为「已修复」。"""
    modeling, tokenizer = _point_to_tmp(
        monkeypatch, tmp_path, _modeling_source(), _tokenizer_source()
    )

    assert mod.main() == 0

    out = capsys.readouterr().out
    assert "共处理 4 处" in out
    assert "所有补丁已正确应用！" in out
    assert "[警告]" not in out

    m_text = modeling.read_text(encoding="utf-8")
    t_text = tokenizer.read_text(encoding="utf-8")
    assert '"input_embeds": inputs_embeds,' in m_text
    assert '"cache_position": cache_position,' in m_text
    assert '"inputs_embeds": inputs_embeds,' not in m_text
    assert "input_embeds=inputs_embeds," in m_text
    assert "cache_position=cache_position," in m_text
    assert "@check_model_inputs()" in t_text
    assert "\n    @check_model_inputs\n" not in t_text

    # 幂等：再跑一次，仍然是 4 处「已修复」，且文件内容不再变化
    assert mod.main() == 0
    out2 = capsys.readouterr().out
    assert "共处理 4 处" in out2
    assert "所有补丁已正确应用！" in out2
    assert modeling.read_text(encoding="utf-8") == m_text
    assert tokenizer.read_text(encoding="utf-8") == t_text


def test_main_warns_when_old_code_remains(tmp_path, monkeypatch, capsys):
    """残留未修复代码且文件里出现 create_causal_mask → 走 [警告] 分支。"""
    # 用不同缩进的 inputs_embeds 行，使 1a/1b 的 old 都匹配不上
    modeling_src = (
        "# modeling_qwen3_tts.py\n"
        "def f():\n"
        '        "inputs_embeds": inputs_embeds,\n'
        "        # 调用了 create_causal_mask\n"
    )
    tokenizer_src = "# tokenizer\nclass T:\n    pass\n"
    modeling, _ = _point_to_tmp(monkeypatch, tmp_path, modeling_src, tokenizer_src)

    assert mod.main() == 0

    out = capsys.readouterr().out
    assert "[警告]" in out
    assert "仍有未修复的 inputs_embeds" in out
    assert str(modeling) in out
    assert "所有补丁已正确应用！" not in out
    # 匹配不上时不做任何修改
    assert modeling.read_text(encoding="utf-8") == modeling_src


def test_main_no_warning_when_causal_mask_absent(tmp_path, monkeypatch, capsys):
    """有残留 inputs_embeds 但文件里没有 create_causal_mask → 验证不报错。

    覆盖校验条件里 ``and`` 的短路分支。
    """
    modeling_src = (
        "# modeling_qwen3_tts.py\n"
        "def f():\n"
        '        "inputs_embeds": inputs_embeds,\n'
    )
    _point_to_tmp(monkeypatch, tmp_path, modeling_src, "# tokenizer\n")

    assert mod.main() == 0

    out = capsys.readouterr().out
    assert "所有补丁已正确应用！" in out
    assert "[警告]" not in out


def test_main_missing_files_reports_errors(tmp_path, monkeypatch, capsys):
    """两个目标文件都不存在 → 计数为 0，并列出两条「文件不存在」。"""
    modeling, tokenizer = _point_to_tmp(monkeypatch, tmp_path, None, None)

    assert mod.main() == 0

    out = capsys.readouterr().out
    assert "共处理 0 处" in out
    assert "[警告]" in out
    assert out.count("文件不存在") >= 2
    assert str(modeling) in out
    assert str(tokenizer) in out
    assert not modeling.exists()
    assert not tokenizer.exists()


def test_main_one_file_missing_partial_patch(tmp_path, monkeypatch, capsys):
    """只有 modeling 存在：它被修好，tokenizer 缺失只报错。"""
    modeling, tokenizer = _point_to_tmp(
        monkeypatch, tmp_path, _modeling_source(), None
    )

    assert mod.main() == 0

    out = capsys.readouterr().out
    assert "共处理 2 处" in out
    assert "[警告]" in out
    assert f"文件不存在: {tokenizer}" in out
    assert "所有补丁已正确应用！" not in out
    assert '"input_embeds": inputs_embeds,' in modeling.read_text(encoding="utf-8")


def test_main_empty_files_are_treated_as_nothing_to_patch(tmp_path, monkeypatch, capsys):
    """空文件边界：old 找不到 → 每处都按「无需修复」计入处理数，校验通过且不报错。"""
    _point_to_tmp(monkeypatch, tmp_path, "", "")

    assert mod.main() == 0

    out = capsys.readouterr().out
    # 注意：patch_file 在「无需修复」时同样返回 True，故计数为 4 而非 0
    assert out.count("[无需修复]") == 4
    assert "共处理 4 处" in out
    assert "所有补丁已正确应用！" in out
    assert "[警告]" not in out


# --------------------------------------------------------------------------
# __main__ 入口（runpy 重跑源码）
# --------------------------------------------------------------------------


def _run_as_main(monkeypatch, fake_executable):
    """以 __main__ 身份执行模块源码，返回捕获到的 SystemExit。"""
    monkeypatch.setattr(sys, "executable", str(fake_executable))
    monkeypatch.setattr(sys, "argv", ["patch_qwen_tts.py"])
    with warnings.catch_warnings():
        # runpy 对「模块已在 sys.modules 中」固定发 RuntimeWarning，忽略即可
        warnings.simplefilter("ignore", RuntimeWarning)
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module("config.patch_qwen_tts", run_name="__main__")
    return excinfo.value


def test_run_as_main_windows_layout_patches_and_exits_zero(tmp_path, monkeypatch, capsys):
    """Windows 布局（Lib/site-packages 存在）下走 __main__，补丁生效且退出码为 0。"""
    fake_exe = tmp_path / "fakevenv" / "bin" / "python.exe"
    site = tmp_path / "fakevenv" / "Lib" / "site-packages"
    modeling = site / "qwen_tts" / "core" / "models" / "modeling_qwen3_tts.py"
    tokenizer = (
        site / "qwen_tts" / "core" / "tokenizer_12hz"
        / "modeling_qwen3_tts_tokenizer_v2.py"
    )
    modeling.parent.mkdir(parents=True, exist_ok=True)
    tokenizer.parent.mkdir(parents=True, exist_ok=True)
    modeling.write_text(_modeling_source(), encoding="utf-8")
    tokenizer.write_text(_tokenizer_source(), encoding="utf-8")

    exc = _run_as_main(monkeypatch, fake_exe)

    assert exc.code == 0
    out = capsys.readouterr().out
    assert "qwen_tts 兼容性补丁" in out
    assert "共处理 4 处" in out
    assert "所有补丁已正确应用！" in out
    assert '"input_embeds": inputs_embeds,' in modeling.read_text(encoding="utf-8")
    assert "@check_model_inputs()" in tokenizer.read_text(encoding="utf-8")


def test_run_as_main_falls_back_to_posix_layout(tmp_path, monkeypatch, capsys):
    """没有 Lib/site-packages 时回落到 Linux/Mac 路径分支，并同样完成补丁。"""
    fake_exe = tmp_path / "fakevenv2" / "bin" / "python.exe"
    pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site = tmp_path / "fakevenv2" / "lib" / pyver / "site-packages"
    modeling = site / "qwen_tts" / "core" / "models" / "modeling_qwen3_tts.py"
    tokenizer = (
        site / "qwen_tts" / "core" / "tokenizer_12hz"
        / "modeling_qwen3_tts_tokenizer_v2.py"
    )
    modeling.parent.mkdir(parents=True, exist_ok=True)
    tokenizer.parent.mkdir(parents=True, exist_ok=True)
    modeling.write_text(_modeling_source(), encoding="utf-8")
    tokenizer.write_text(_tokenizer_source(), encoding="utf-8")
    # 明确确认 Windows 布局不存在，从而强制走回落分支
    assert not (tmp_path / "fakevenv2" / "Lib" / "site-packages").exists()

    exc = _run_as_main(monkeypatch, fake_exe)

    assert exc.code == 0
    out = capsys.readouterr().out
    assert f"lib/{pyver}/site-packages" in out.replace("\\", "/")
    assert "共处理 4 处" in out
    assert "所有补丁已正确应用！" in out
    assert "cache_position=cache_position," in modeling.read_text(encoding="utf-8")
