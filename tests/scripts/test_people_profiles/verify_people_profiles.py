#!/usr/bin/env python
"""
人物档案系统验证脚本

验证内容：
1. 迁移档案文件存在性（9 个文件）
2. PersonProfile 序列化/反序列化
3. PeopleProfileManager 加载和查询
4. find_mentioned_people 匹配
5. build_mentioned_people_injection 注入
6. QueryPersonProfileTool 工具查询
7. PeopleProfileExtractor JSON 解析

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\test_people_profiles\\verify_people_profiles.py
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到 path
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# 迁移生成的 9 个档案文件
_EXPECTED_PROFILE_FILES = [
    "companion_data/user_data/person_profile.json",
    "companion_data/user_data/people_profiles/wang_ling.json",
    "companion_data/user_data/people_profiles/aveline.json",
    "companion_data/aveline_data/persona_data/profiles/Aveline_qi.json",
    "companion_data/aveline_data/persona_data/profiles/Aveline_ling.json",
    "companion_data/aveline_data/persona_data/profiles/Aveline_default.json",
    "companion_data/ling_data/persona_data/profiles/Ling_qi.json",
    "companion_data/ling_data/persona_data/profiles/Ling_aveline.json",
    "companion_data/ling_data/persona_data/profiles/Ling_default.json",
]

_passed = 0
_failed = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    """断言检查"""
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name} {detail}")


def test_profile_files_exist() -> None:
    """测试 1：迁移档案文件存在性"""
    print("\n=== 测试 1：迁移档案文件存在性 ===")
    for rel_path in _EXPECTED_PROFILE_FILES:
        full_path = _PROJECT_ROOT / rel_path
        _check(
            f"文件存在: {rel_path}",
            full_path.exists(),
            f"(路径: {full_path})",
        )


def test_model_serialization() -> None:
    """测试 2：PersonProfile 序列化/反序列化"""
    print("\n=== 测试 2：PersonProfile 序列化/反序列化 ===")
    from core.character.people import PersonProfile, ProfileType, ProfileTarget
    from core.character.people.models import KnownFact

    # 创建测试档案
    profile = PersonProfile(
        profile_id="test_person",
        profile_type=ProfileType.PERSON,
        name="测试人物",
        aliases=["测试", "test"],
        description="这是一个测试人物",
        source="test",
    )
    profile.add_known_fact(
        KnownFact(key="学校", value="测试大学", confidence=0.9, source="test")
    )

    # 序列化
    data = profile.to_dict()
    _check("序列化包含 profile_id", data.get("profile_id") == "test_person")
    _check("序列化包含 name", data.get("name") == "测试人物")
    _check("序列化包含 aliases", data.get("aliases") == ["测试", "test"])
    _check(
        "序列化包含 known_facts",
        isinstance(data.get("detailed", {}).get("known_facts"), list)
        and len(data["detailed"]["known_facts"]) == 1,
    )

    # 反序列化
    restored = PersonProfile.from_dict(data)
    _check("反序列化 name 正确", restored.name == "测试人物")
    _check("反序列化 profile_type 正确", restored.profile_type == ProfileType.PERSON)
    _check("反序列化 aliases 正确", restored.aliases == ["测试", "test"])
    _check("反序列化 known_facts 正确", len(restored.get_known_facts()) == 1)
    _check(
        "反序列化 fact value 正确",
        restored.get_known_facts()[0].value == "测试大学",
    )

    # matches_name 测试
    _check("matches_name 精确匹配", profile.matches_name("测试人物"))
    _check("matches_name 别名匹配", profile.matches_name("测试"))
    _check("matches_name 英文别名匹配", profile.matches_name("test"))
    _check("matches_name 不匹配", not profile.matches_name("不存在的名字"))


def test_manager_load_and_query() -> None:
    """测试 3：PeopleProfileManager 加载和查询"""
    print("\n=== 测试 3：PeopleProfileManager 加载和查询 ===")
    from core.character.people import get_people_profile_manager

    manager = get_people_profile_manager()

    # 查询用户自身档案（Master）
    self_profile = manager.get_user_self_profile()
    _check("用户自身档案存在", self_profile is not None)
    if self_profile:
        _check("用户自身档案名字正确", self_profile.name == "Master")

    # 查询人际关系档案（Ling）
    wang_ling = manager.query_profile_details("Ling")
    _check("查询Ling档案成功", wang_ling is not None)
    if wang_ling:
        _check("Ling档案名字正确", wang_ling.name == "Ling")

    # 查询不存在的人物
    nobody = manager.query_profile_details("不存在的人物XYZ")
    _check("查询不存在的人物返回 None", nobody is None)

    # 列出所有人际关系档案
    all_profiles = manager.list_all_people_profiles()
    _check("人际关系档案列表非空", len(all_profiles) >= 2)
    _check(
        "人际关系档案包含Ling",
        any(p.name == "Ling" for p in all_profiles),
    )


def test_find_mentioned_people() -> None:
    """测试 4：find_mentioned_people 匹配"""
    print("\n=== 测试 4：find_mentioned_people 匹配 ===")
    from core.character.people import get_people_profile_manager

    manager = get_people_profile_manager()

    # 提到Ling
    matched = manager.find_mentioned_people("今天和Ling一起去买东西")
    _check("提到Ling时匹配到人物", len(matched) >= 1)
    if matched:
        _check("匹配到的是Ling", matched[0].name == "Ling")

    # 没提到任何人
    no_match = manager.find_mentioned_people("今天天气真好")
    _check("没提到人物时返回空列表", len(no_match) == 0)

    # 空字符串
    empty_match = manager.find_mentioned_people("")
    _check("空字符串返回空列表", len(empty_match) == 0)


def test_injection() -> None:
    """测试 5：build_mentioned_people_injection 注入"""
    print("\n=== 测试 5：build_mentioned_people_injection 注入 ===")
    from core.agents.chat_agent_components.persona_system.prompt.components.people_profiles import (
        build_mentioned_people_injection,
    )

    # 提到Ling的消息
    result = build_mentioned_people_injection("今天和Ling一起吃饭了", "test_user")
    _check("提及人物时返回非空注入", bool(result))
    _check("注入包含Ling", "Ling" in result)
    _check("注入包含标题", "【提及的人物】" in result)

    # 没提到人物的消息
    result_empty = build_mentioned_people_injection("今天天气不错", "test_user")
    _check("无提及人物时返回空字符串", result_empty == "")

    # 空消息
    result_none = build_mentioned_people_injection("", "test_user")
    _check("空消息返回空字符串", result_none == "")


def test_tool_query() -> None:
    """测试 6：QueryPersonProfileTool 工具查询"""
    print("\n=== 测试 6：QueryPersonProfileTool 工具查询 ===")

    async def _run_tool_tests():
        from core.tools.person_profile_tool import QueryPersonProfileTool

        tool = QueryPersonProfileTool()

        # 查询Ling
        result = await tool._run("Ling")
        _check("工具查询Ling返回非空", bool(result))
        _check("工具结果包含详细档案标题", "详细档案" in result)
        _check("工具结果包含Ling名字", "Ling" in result)

        # 查询Master
        result_qi = await tool._run("Master")
        _check("工具查询Master返回非空", bool(result_qi))
        _check("工具结果包含Master名字", "Master" in result_qi)

        # 查询不存在的人物
        result_nobody = await tool._run("不存在的人XYZ")
        _check("工具查询不存在人物返回提示", "没有找到" in result_nobody)

    asyncio.run(_run_tool_tests())


def test_extractor_parsing() -> None:
    """测试 7：PeopleProfileExtractor JSON 解析"""
    print("\n=== 测试 7：PeopleProfileExtractor JSON 解析 ===")
    from core.character.people.extractor import PeopleProfileExtractor

    extractor = PeopleProfileExtractor()

    # 正常 JSON
    response1 = json.dumps({
        "people": [
            {
                "name": "张三",
                "aliases": ["小张"],
                "facts": [
                    {"key": "学校", "value": "清华"},
                    {"key": "性格", "value": "开朗"},
                ],
            }
        ]
    })
    result1 = extractor._parse_response(response1)
    _check("正常 JSON 解析返回 1 个人物", len(result1) == 1)
    if result1:
        _check("解析名字正确", result1[0]["name"] == "张三")
        _check("解析别名正确", result1[0]["aliases"] == ["小张"])
        _check("解析事实数量正确", len(result1[0]["facts"]) == 2)

    # 带 markdown 代码块的 JSON
    response2 = '```json\n{"people": [{"name": "李四", "aliases": [], "facts": []}]}\n```'
    result2 = extractor._parse_response(response2)
    _check("带代码块的 JSON 解析返回 1 个人物", len(result2) == 1)
    if result2:
        _check("代码块解析名字正确", result2[0]["name"] == "李四")

    # 空人物列表
    response3 = '{"people": []}'
    result3 = extractor._parse_response(response3)
    _check("空人物列表返回空列表", len(result3) == 0)

    # 无效 JSON
    response4 = "这不是 JSON"
    result4 = extractor._parse_response(response4)
    _check("无效 JSON 返回空列表", len(result4) == 0)

    # 空字符串
    result5 = extractor._parse_response("")
    _check("空字符串返回空列表", len(result5) == 0)


def main() -> int:
    """主入口"""
    print("=" * 60)
    print("人物档案系统验证脚本")
    print("=" * 60)

    try:
        test_profile_files_exist()
        test_model_serialization()
        test_manager_load_and_query()
        test_find_mentioned_people()
        test_injection()
        test_tool_query()
        test_extractor_parsing()
    except Exception as exc:
        print(f"\n[ERROR] 测试过程中发生异常: {exc}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "=" * 60)
    print(f"验证结果: {_passed} 通过, {_failed} 失败")
    print("=" * 60)

    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
