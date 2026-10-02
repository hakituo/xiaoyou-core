"""P0-17 验证脚本：批量修复 4 个文件非原子 JSON 写入

验证 4 个目标模块（actor_manager / student_state / food_manager /
chat_history_store）的保存函数已迁移到 safe_json_dump，
且写入失败时不会截断原文件。
"""
import inspect
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


TARGET_MODULES = [
    ("actor_manager", "core.services.life_simulation.actor_manager",
     ["ActorManager._save_actor_states"]),
    ("student_state", "core.services.study.student_state",
     ["StudentStateManager.save"]),
    ("food_manager", "core.food.manager",
     ["FoodManager._record_self_meal"]),
    ("chat_history_store", "core.services.chat_history_store",
     ["ChatHistoryStore._write_day_index"]),
]


def _get_func_source(module_path, func_path):
    mod = __import__(module_path, fromlist=["*"])
    obj = mod
    for p in func_path.split("."):
        obj = getattr(obj, p)
    return inspect.getsource(obj)


def check_imports():
    issues = []
    for name, module, _ in TARGET_MODULES:
        try:
            mod = __import__(module, fromlist=["*"])
        except Exception as e:
            issues.append(f"[{name}] 导入失败: {e}")
            continue
        src = inspect.getsource(mod)
        if "from core.utils.atomic_io import" not in src:
            issues.append(f"[{name}] 未从 atomic_io 导入")
        elif "safe_json_dump" not in src:
            issues.append(f"[{name}] 未导入 safe_json_dump")
    return issues


def check_save_funcs_use_safe_json_dump():
    issues = []
    for name, module, funcs in TARGET_MODULES:
        for fp in funcs:
            try:
                src = _get_func_source(module, fp)
            except Exception as e:
                issues.append(f"[{name}::{fp}] 获取源码失败: {e}")
                continue
            if "safe_json_dump" not in src:
                issues.append(f"[{name}::{fp}] 未调用 safe_json_dump")
    return issues


def check_no_write_text_json():
    issues = []
    for name, module, funcs in TARGET_MODULES:
        for fp in funcs:
            try:
                src = _get_func_source(module, fp)
            except Exception:
                continue
            lines = src.splitlines()
            for i, line in enumerate(lines):
                if ".write_text(" in line and "json.dumps" in line:
                    issues.append(f"[{name}::{fp}] L{i+1} 仍用 write_text(json.dumps)")
                elif ".write_text(" in line and i + 1 < len(lines):
                    if "json.dumps" in lines[i + 1]:
                        issues.append(f"[{name}::{fp}] L{i+1}-{i+2} 多行调用残留")
                        break
    return issues


def check_safe_json_dump_basic():
    from core.utils.atomic_io import safe_json_dump, safe_json_load
    issues = []
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "d.json"
        data = {"k": "中", "n": [1, 2], "nest": {"a": 1}}
        safe_json_dump(data, fp, encoding="utf-8")
        if not fp.exists():
            issues.append("写入后文件不存在")
            return issues
        if json.loads(fp.read_text(encoding="utf-8")) != data:
            issues.append("写入内容不一致")
        if safe_json_load(fp) != data:
            issues.append("safe_json_load 读回不一致")
    return issues


def check_safe_json_dump_atomicity():
    from core.utils import atomic_io
    issues = []
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "a.json"
        orig = {"v": 1}
        fp.write_text(json.dumps(orig), encoding="utf-8")
        with patch.object(atomic_io, "_retry_os_replace",
                          side_effect=OSError("fail")):
            try:
                atomic_io.safe_json_dump({"v": 2}, fp, encoding="utf-8")
                issues.append("应在替换失败时抛异常")
            except OSError:
                pass
        try:
            actual = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            issues.append(f"原文件被损坏: {e}")
            return issues
        if actual != orig:
            issues.append(f"原子写入失败后原文件被改: 期望 {orig} 实际 {actual}")
        tmps = list(fp.parent.glob(f"{fp.name}.tmp_*"))
        if tmps:
            issues.append(f"残留临时文件: {tmps}")
    return issues


def check_safe_json_dump_concurrent():
    from core.utils.atomic_io import safe_json_dump
    issues = []
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "c.json"
        safe_json_dump({"init": True}, fp)
        N = 8
        ok = []

        def w(i):
            try:
                safe_json_dump({"w": i, "d": list(range(50))}, fp)
                ok.append(True)
            except Exception:
                ok.append(False)

        ts = [threading.Thread(target=w, args=(i,)) for i in range(N)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        if sum(ok) != N:
            issues.append(f"并发完成数异常: {sum(ok)}/{N}")
        try:
            final = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            issues.append(f"并发后文件损坏: {e}")
            return issues
        if "w" not in final or final.get("d") != list(range(50)):
            issues.append(f"并发后内容不完整: {final}")
        tmps = list(fp.parent.glob(f"{fp.name}.tmp_*"))
        if tmps:
            issues.append(f"并发后残留临时文件: {tmps}")
    return issues


def check_actor_manager_no_truncation():
    from core.services.life_simulation import actor_manager as am_mod
    issues = []
    with tempfile.TemporaryDirectory() as td:
        am = am_mod.ActorManager()
        am._actor_state_file = Path(td) / "as.json"
        am._actor_life_states = {"aveline": {"energy": 80.0}}
        am._actor_relationships = {"aveline|user": 75.0}
        am._save_actor_states()
        if not am._actor_state_file.exists():
            issues.append("前置条件失败：首次保存未生成文件")
            return issues
        orig = am._actor_state_file.read_text(encoding="utf-8")
        # patch 目标模块的 safe_json_dump 引用（from import 后的本地绑定）
        with patch.object(am_mod, "safe_json_dump",
                          side_effect=OSError("fail")):
            am._save_actor_states()
        after = am._actor_state_file.read_text(encoding="utf-8")
        if after != orig:
            issues.append("safe_json_dump 失败后 actor_states.json 被修改")
        try:
            json.loads(after)
        except Exception as e:
            issues.append(f"actor_states.json 被截断为非法 JSON: {e}")
    return issues


def check_student_state_no_truncation():
    from core.services.study import student_state as ss_mod
    from core.services.study.student_state import (
        StudentStateManager, StudentState, SubjectState,
    )
    issues = []
    with tempfile.TemporaryDirectory() as td:
        m = StudentStateManager()
        m._state_file = Path(td) / "ss.json"
        m._state = StudentState(
            subjects={"math": SubjectState(subject="math", total_sessions=5)},
            total_sessions=5,
            streak_days=3,
            created_at="2026-01-01T00:00:00",
        )
        m.save()
        if not m._state_file.exists():
            issues.append("前置条件失败")
            return issues
        orig = m._state_file.read_text(encoding="utf-8")
        with patch.object(ss_mod, "safe_json_dump",
                          side_effect=OSError("fail")):
            m.save()
        after = m._state_file.read_text(encoding="utf-8")
        if after != orig:
            issues.append("student_state.json 被修改")
        try:
            json.loads(after)
        except Exception as e:
            issues.append(f"student_state.json 被截断: {e}")
    return issues


def check_food_manager_no_truncation():
    from core.food import manager as food_mod
    from core.food.manager import FoodManager
    issues = []
    with tempfile.TemporaryDirectory() as td:
        fm = FoodManager()
        orig_norm = fm._normalize_persona_scope
        fm._normalize_persona_scope = lambda *a, **kw: "aveline"
        try:
            with patch("core.food.manager.get_aveline_life_records_dir",
                       return_value=Path(td)):
                fm._record_self_meal("正餐", "自主进食:米饭")
                files = list(Path(td).rglob("daily_record.json"))
                if len(files) != 1:
                    issues.append(f"前置失败：找不到 daily_record.json: {files}")
                    return issues
                tf = files[0]
                orig = tf.read_text(encoding="utf-8")
                with patch.object(food_mod, "safe_json_dump",
                                  side_effect=OSError("fail")):
                    try:
                        fm._record_self_meal("零食", "巧克力")
                    except Exception:
                        pass
                after = tf.read_text(encoding="utf-8")
                if after != orig:
                    issues.append("daily_record.json 被修改")
                try:
                    json.loads(after)
                except Exception as e:
                    issues.append(f"daily_record.json 被截断: {e}")
        finally:
            fm._normalize_persona_scope = orig_norm
    return issues


def check_chat_history_store_no_truncation():
    from core.services import chat_history_store as chs_mod
    from core.services.chat_history_store import ChatHistoryStore
    issues = []
    with tempfile.TemporaryDirectory() as td:
        bd = Path(td) / "ch"
        store = ChatHistoryStore(base_dir=bd)
        dd = bd / "2026" / "07" / "26"
        dd.mkdir(parents=True, exist_ok=True)
        (dd / "c.jsonl").write_text("d\n", encoding="utf-8")
        store._write_day_index(dd, bd)
        idx = dd / "index.json"
        if not idx.exists():
            issues.append("前置条件失败")
            return issues
        orig = idx.read_text(encoding="utf-8")
        with patch.object(chs_mod, "safe_json_dump",
                          side_effect=OSError("fail")):
            store._write_day_index(dd, bd)
        after = idx.read_text(encoding="utf-8")
        if after != orig:
            issues.append("index.json 被修改")
        try:
            json.loads(after)
        except Exception as e:
            issues.append(f"index.json 被截断: {e}")
    return issues


def check_actor_manager_e2e():
    from core.services.life_simulation.actor_manager import ActorManager
    issues = []
    with tempfile.TemporaryDirectory() as td:
        am = ActorManager()
        am._actor_state_file = Path(td) / "as.json"
        am._actor_life_states = {"aveline": {"energy": 75.0, "hunger": 60.0}}
        am._actor_relationships = {"aveline|user": 50.0}
        am._save_actor_states()
        if not am._actor_state_file.exists():
            issues.append("保存后文件不存在")
            return issues
        d = json.loads(am._actor_state_file.read_text(encoding="utf-8"))
        if d.get("life_states", {}).get("aveline", {}).get("energy") != 75.0:
            issues.append(f"life_states 不正确: {d.get('life_states')}")
        if d.get("relationships", {}).get("aveline|user") != 50.0:
            issues.append(f"relationships 不正确: {d.get('relationships')}")
        if "updated_at" not in d:
            issues.append("缺少 updated_at")
    return issues


def check_student_state_e2e():
    from core.services.study.student_state import (
        StudentStateManager, StudentState, SubjectState,
    )
    issues = []
    with tempfile.TemporaryDirectory() as td:
        m = StudentStateManager()
        m._state_file = Path(td) / "ss.json"
        m._state = StudentState(
            subjects={"math": SubjectState(
                subject="math", total_sessions=3,
                total_minutes=120, confidence=7.5,
            )},
            total_sessions=3, streak_days=2,
            created_at="2026-01-01T00:00:00",
        )
        m.save()
        if not m._state_file.exists():
            issues.append("保存后文件不存在")
            return issues
        d = json.loads(m._state_file.read_text(encoding="utf-8"))
        if d.get("total_sessions") != 3:
            issues.append(f"total_sessions 不正确: {d.get('total_sessions')}")
        if d.get("subjects", {}).get("math", {}).get("confidence") != 7.5:
            issues.append("subjects.math.confidence 不正确")
        if "updated_at" not in d:
            issues.append("缺少 updated_at")
    return issues


def check_chat_history_store_e2e():
    from core.services.chat_history_store import ChatHistoryStore
    issues = []
    with tempfile.TemporaryDirectory() as td:
        bd = Path(td) / "ch"
        store = ChatHistoryStore(base_dir=bd)
        dd = bd / "2026" / "07" / "26"
        dd.mkdir(parents=True, exist_ok=True)
        (dd / "c1.jsonl").write_text("d1\n", encoding="utf-8")
        (dd / "c2.jsonl").write_text("d2\n", encoding="utf-8")
        store._write_day_index(dd, bd)
        idx = dd / "index.json"
        if not idx.exists():
            issues.append("index.json 不存在")
            return issues
        d = json.loads(idx.read_text(encoding="utf-8"))
        files = d.get("files", [])
        if len(files) != 2:
            issues.append(f"index.json 文件数不正确: 期望 2 实际 {len(files)}")
        else:
            names = {f.get("name") for f in files}
            if names != {"c1.jsonl", "c2.jsonl"}:
                issues.append(f"index.json 文件名不正确: {names}")
    return issues


def main():
    print("=" * 70)
    print("P0-17 验证：批量修复 4 个文件非原子 JSON 写入")
    print("=" * 70)
    all_issues = []
    checks = [
        ("4 模块导入 safe_json_dump", check_imports),
        ("保存函数调用 safe_json_dump", check_save_funcs_use_safe_json_dump),
        ("保存函数不再用 write_text(json.dumps)", check_no_write_text_json),
        ("safe_json_dump 正常写入", check_safe_json_dump_basic),
        ("safe_json_dump 原子性", check_safe_json_dump_atomicity),
        ("safe_json_dump 并发安全", check_safe_json_dump_concurrent),
        ("ActorManager 失败不截断", check_actor_manager_no_truncation),
        ("StudentStateManager 失败不截断", check_student_state_no_truncation),
        ("FoodManager 失败不截断", check_food_manager_no_truncation),
        ("ChatHistoryStore 失败不截断", check_chat_history_store_no_truncation),
        ("ActorManager 端到端", check_actor_manager_e2e),
        ("StudentStateManager 端到端", check_student_state_e2e),
        ("ChatHistoryStore 端到端", check_chat_history_store_e2e),
    ]
    for name, fn in checks:
        print(f"\n[检查] {name}")
        try:
            issues = fn()
        except Exception as e:
            import traceback
            issues = [f"检查抛异常: {type(e).__name__}: {e}"]
            traceback.print_exc()
        if issues:
            for i in issues:
                print(f"  FAIL: {i}")
            all_issues.extend(issues)
        else:
            print("  PASS")
    print("\n" + "=" * 70)
    if all_issues:
        print(f"结果：失败（{len(all_issues)} 项问题）")
        return 1
    print("结果：通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
