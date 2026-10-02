r"""验证 auto_commit_push 能正确处理非 ASCII 路径。

背景：本仓库有中文名脚本（如 `start_scripts\启动Cloudflare_Tunnel.bat`）。
git 默认 `core.quotepath=true`，会把非 ASCII 路径转义成
`"start_scripts/\345\220\257..."` 形式输出。auto_commit_push 如果直接拿这串
去做 `--only` 范围匹配，中文名文件就会被静默排除：既进不了提交清单，
也进不了敏感扫描；`git show --name-only` 的重复提交保护同样会失效。

本脚本验证：扫描与重复保护都关掉了 quotepath，且中文路径能被正确匹配。

运行：
    D:\projects\xiaoyou\venv_core\Scripts\python.exe -m tests.scripts.git.verify_auto_commit_quotepath
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

_FAILED: list[str] = []

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.git.auto_commit_push import (  # noqa: E402
    _is_duplicate_of_last_commit,
    get_changed_files,
)

CN_BAT = "start_scripts/启动Cloudflare_Tunnel.bat"
CN_PS1 = "start_scripts/start_cloudflared_tunnel.ps1"


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    _FAILED.append(msg)


def test_scan_commands_disable_quotepath() -> None:
    print("\n=== 测试 1: 扫描用的 git 命令都关掉了 core.quotepath ===")
    seen: list[list[str]] = []

    def _run(cmd, cwd=None, timeout=30, env=None):
        seen.append(list(cmd))
        if "diff" in cmd:
            return 0, f"{CN_PS1}\nUPDATES.md\n", ""
        if "ls-files" in cmd:
            return 0, f"{CN_BAT}\n", ""
        return 0, "", ""

    with patch("scripts.git.auto_commit_push.run_cmd", side_effect=_run):
        get_changed_files()

    missing = [
        " ".join(cmd)
        for cmd in seen
        if cmd[:2] != ["git", "-c"] or "core.quotepath=false" not in cmd
    ]
    if not missing:
        _ok(f"{len(seen)} 条扫描命令均带 -c core.quotepath=false")
    else:
        _fail("以下扫描命令没关 quotepath: " + " | ".join(missing))


def test_scope_matches_chinese_path() -> None:
    print("\n=== 测试 2: --only 范围能匹配中文路径（不再被静默排除）===")

    def _run(cmd, cwd=None, timeout=30, env=None):
        if "diff" in cmd:
            return 0, f"{CN_PS1}\nUPDATES.md\n", ""
        if "ls-files" in cmd:
            return 0, f"{CN_BAT}\n", ""
        return 0, "", ""

    with patch("scripts.git.auto_commit_push.run_cmd", side_effect=_run):
        scoped = get_changed_files([CN_BAT, CN_PS1])

    if sorted(scoped) == sorted([CN_BAT, CN_PS1]):
        _ok(f"中文名文件在范围内被保留: {scoped}")
    else:
        _fail(f"中文名文件被漏掉: {scoped}")


def test_duplicate_guard_sees_chinese_path() -> None:
    print("\n=== 测试 3: 重复提交保护能看见中文路径 ===")

    def _run(cmd, cwd=None, timeout=30, env=None):
        if "log" in cmd:
            return 0, "同一句说明", ""
        if "show" in cmd:
            return 0, f"{CN_BAT}\n{CN_PS1}\n", ""
        return 0, "", ""

    with patch("scripts.git.auto_commit_push.run_cmd", side_effect=_run):
        dup = _is_duplicate_of_last_commit("同一句说明", [CN_BAT])

    if dup:
        _ok("中文路径参与子集判定，重跑被识别")
    else:
        _fail("中文路径未参与判定，重跑未被识别")


def test_real_git_flag_behaviour() -> None:
    print("\n=== 测试 4: 真跑 git，确认该 flag 确实把中文路径还原成原样 ===")
    git = shutil.which("git")
    if not git:
        _ok("未找到 git，跳过（不影响其余检查）")
        return

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        subprocess.run([git, "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "启动脚本.bat").write_text("x", encoding="utf-8")

        def _ls(extra: list[str]) -> str:
            result = subprocess.run(
                [git] + extra + ["ls-files", "--others", "--exclude-standard"],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            return result.stdout.strip()

        escaped = _ls([])
        raw = _ls(["-c", "core.quotepath=false"])

    if escaped.startswith('"') and "\\" in escaped:
        _ok(f"默认输出确实被转义: {escaped}")
    else:
        _fail(f"默认输出未被转义，测试前提不成立: {escaped}")

    if raw == "启动脚本.bat":
        _ok(f"关掉 quotepath 后输出原样: {raw}")
    else:
        _fail(f"关掉 quotepath 后仍异常: {raw}")


def main() -> int:
    print("=" * 64)
    print("auto_commit_push 非 ASCII 路径处理验证")
    print("=" * 64)
    test_scan_commands_disable_quotepath()
    test_scope_matches_chinese_path()
    test_duplicate_guard_sees_chinese_path()
    test_real_git_flag_behaviour()
    print("=" * 64)
    if _FAILED:
        print(f"失败 {len(_FAILED)} 项：" + "、".join(_FAILED))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
