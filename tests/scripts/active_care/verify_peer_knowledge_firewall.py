"""验证 Peer Chat 知识防火墙与相关改造是否成功。

覆盖本轮改造的校验点：
P0 ③ Knowledge Firewall（peer_knowledge.py）：
  1. filter_secret_lines 剔除含保密信号的整行，保留其余可分享内容
  2. build_knowledge_buckets 按信息权限分桶（shared / role.* / peer.*）
  3. validate_peer_script 能检出信息越权与隐私泄漏，放过合法剧本
P0/P1 决策输出收敛（decision_output_parser.py）：
  4. _parse_peer_chat_output 映射 trigger→situation、intent→opening_idea、
     conversation_seed→topic、avoid、reason_code；旧字段向后兼容
P0/P1 剧本 prompt（qq_peer_context.py + peer_chat_script_system.txt）：
  5. build_script_generation_prompt 在 knowledge 模式下分桶渲染，不出现旧合并渲染
  6. build_peer_chat_decision_prompt 明确硬门槛由代码层承担（决策 prompt 缩水）
  7. peer_chat_script_system.txt 含软化后的规则（4-24字 / 2-6轮 / 信息权限最高级 / 反剧本）
P1 实时私聊 Persona slicing（build_qq_peer_role_context）：
  8. 注入"我眼中的对方"，不注入用户专属 relationship layer

全部通过返回 0，否则非 0。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "venv_core" / "Lib" / "site-packages"))

FAILURES: list[str] = []


def _fail(msg: str) -> None:
    FAILURES.append(msg)
    sys.stderr.write(f"FAIL: {msg}\n")
    sys.stderr.flush()


def _check(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        _fail(f"{name} {detail}".strip())


# ── 1. filter_secret_lines ────────────────────────────────────
def check_secret_filter() -> None:
    from core.services.active_care.peer_chat.peer_knowledge import (
        filter_secret_lines,
    )

    raw = (
        "今天食堂的饭好难吃\n"
        "我偷偷在准备一个惊喜，别告诉Ling\n"
        "等会儿记得倒垃圾"
    )
    out = filter_secret_lines(raw)
    # 保密行被剔除
    _check("filter_secret_lines 剔除保密行", "别告诉Ling" not in out, out)
    _check("filter_secret_lines 保留可分享行", "食堂的饭好难吃" in out, out)
    _check("filter_secret_lines 保留日常行", "倒垃圾" in out, out)
    # 空输入
    _check("filter_secret_lines 空输入", filter_secret_lines("") == "")
    _check("filter_secret_lines None", filter_secret_lines(None) == "")


# ── 2. build_knowledge_buckets ────────────────────────────────
def check_knowledge_buckets() -> None:
    from core.services.active_care.peer_chat.peer_knowledge import (
        build_knowledge_buckets,
    )

    role_bio = {
        "life": {
            "energy": 10,
            "mood": "低落",
            "hunger": 90,
            "current_activity": "写实验报告",
        }
    }
    peer_bio = {
        "life": {
            "energy": 70,
            "mood": "烦躁",
            "hunger": 50,
            "current_activity": "睡觉",
        }
    }
    master_by_role = {
        "ye": "今天食堂的饭好难吃\n我偷偷在准备惊喜，别告诉Ling",
        "ling": "刚打完游戏",
    }
    k = build_knowledge_buckets(
        role_id="ye",
        peer_role_id="ling",
        role_name="Ye",
        peer_name="Ling",
        bio_state=role_bio,
        peer_bio_state=peer_bio,
        master_history_by_role=master_by_role,
        time_str="2026-09-04 00:20",
    )

    _check("分桶包含 shared_context", "当前时间" in k["shared_context"], k["shared_context"])
    # 活动是共同可观察的，进 shared
    _check("分桶 shared 含双方活动", "写实验报告" in k["shared_context"] and "睡觉" in k["shared_context"], k["shared_context"])
    # role.private_state 只有自己的内部状态
    _check("role.private_state 含自己疲惫", "很累" in k["role"]["private_state"], k["role"]["private_state"])
    _check("role.private_state 不含对方", "睡觉" not in k["role"]["private_state"], k["role"]["private_state"])
    # role.known_about_peer 是对方可观察部分
    _check("role.known_about_peer 是对方活动", "睡觉" in k["role"]["known_about_peer"], k["role"]["known_about_peer"])
    _check("role.known_about_peer 不含对方私有", "心情" not in k["role"]["known_about_peer"], k["role"]["known_about_peer"])
    # master_material 归属 + 保密过滤
    _check("role.master_material 归属自己并过滤保密", "食堂" in k["role"]["master_material"] and "别告诉Ling" not in k["role"]["master_material"], k["role"]["master_material"])
    _check("peer.master_material 归属对方", "游戏" in k["peer"]["master_material"], k["peer"]["master_material"])
    # 对称视角
    _check("peer.private_state 是对方内部", "心情烦躁" in k["peer"]["private_state"], k["peer"]["private_state"])


# ── 3. validate_peer_script ───────────────────────────────────
def check_script_validator() -> None:
    from core.services.active_care.peer_chat.peer_knowledge import (
        build_knowledge_buckets,
        validate_peer_script,
    )

    role_bio = {"life": {"energy": 10, "mood": "低落", "hunger": 90, "current_activity": "写实验报告"}}
    peer_bio = {"life": {"energy": 70, "mood": "烦躁", "hunger": 50, "current_activity": "睡觉"}}
    k = build_knowledge_buckets(
        role_id="ye", peer_role_id="ling",
        role_name="Ye", peer_name="Ling",
        bio_state=role_bio, peer_bio_state=peer_bio,
        master_history_by_role={"ye": "", "ling": ""},
        time_str="",
    )

    # 越权：Ye提到Ling私有状态（Ling neutral 心情在 peer.private_state，但不在 known 里）
    overreach = [
        {"role": "ye", "content": "你今天心情是不是很不好"},
        {"role": "ling", "content": "没有啊"},
    ]
    v = validate_peer_script(overreach, k, role_id="ye", peer_role_id="ling")
    _check("validator 检出越权", any("越权" in item for item in v), " | ".join(v))

    # 隐私泄漏：剧本里出现保密信号
    leak = [{"role": "ye", "content": "你先把这事保密啊"}]
    v = validate_peer_script(leak, k, role_id="ye", peer_role_id="ling")
    _check("validator 检出保密信号", any("隐私风险" in item for item in v), " | ".join(v))

    # 合法剧本：只聊共同可观察/自己已知的内容
    ok = [
        {"role": "ye", "content": "你居然还在睡"},
        {"role": "ling", "content": "昨晚打游戏到两点"},
        {"role": "ye", "content": "那你接着睡"},
    ]
    v = validate_peer_script(ok, k, role_id="ye", peer_role_id="ling")
    _check("validator 放过合法剧本", v == [], " | ".join(v))

    # 空剧本直接通过
    _check("validator 空剧本通过", validate_peer_script([], k) == [])


# ── 4. 决策输出收敛解析 ──────────────────────────────────────
def check_decision_output_convergence() -> None:
    from core.services.active_care.decision.decision_output_parser import (
        _parse_peer_chat_output,
    )

    # 新格式：trigger / intent / conversation_seed / avoid / reason_code
    raw_new = (
        '{"should_send": true, "reason_code": "recent_life_event", '
        '"reason": "刚结束实验，存在自然可分享事件", '
        '"trigger": "Ye刚结束实验回宿舍", '
        '"intent": "吐槽实验里的插曲", '
        '"conversation_seed": "离心机中途报错，折腾了十分钟", '
        '"avoid": ["不要问泛泛的你在干嘛"]}'
    )
    r = _parse_peer_chat_output(raw_new)
    _check("决策收敛: should_send", r["should_send"] is True, str(r))
    _check("决策收敛: reason_code", r["reason_code"] == "recent_life_event", r["reason_code"])
    _check("决策收敛: trigger→situation", r["situation"] == "Ye刚结束实验回宿舍", r["situation"])
    _check("决策收敛: intent→opening_idea", r["opening_idea"] == "吐槽实验里的插曲", r["opening_idea"])
    _check("决策收敛: seed→topic", r["topic"] == "离心机中途报错，折腾了十分钟", r["topic"])
    _check("决策收敛: avoid", "不要问泛泛的你在干嘛" in r["avoid"], str(r["avoid"]))
    _check("决策收敛: intent 路由标记", r["intent"] == "peer_chat", r["intent"])

    # 向后兼容旧格式 situation/opening_idea/topic
    raw_old = (
        '{"should_send": false, "thought": "没理由", '
        '"situation": "旧情境", "opening_idea": "旧动作", "topic": "旧话题"}'
    )
    r2 = _parse_peer_chat_output(raw_old)
    _check("决策兼容: 旧 situation", r2["situation"] == "旧情境", str(r2))
    _check("决策兼容: 旧 opening_idea", r2["opening_idea"] == "旧动作", str(r2))
    _check("决策兼容: 旧 topic", r2["topic"] == "旧话题", str(r2))
    _check("决策兼容: 旧 should_send", r2["should_send"] is False, str(r2))


# ── 5. 剧本 prompt 知识分桶渲染 ─────────────────────────────
def check_script_prompt_knowledge_render() -> None:
    from core.agents.chat_agent_components.persona_system.prompt.qq_peer_context import (
        build_script_generation_prompt,
    )

    knowledge = {
        "shared_context": "当前时间：2026-09-04 00:20，你看到Ling：在睡觉，Ling看到你：在写实验报告",
        "role": {
            "private_state": "很累，心情低落",
            "known_about_peer": "在睡觉",
            "master_material": "今天食堂的饭好难吃",
        },
        "peer": {
            "private_state": "",
            "known_about_peer": "在写实验报告",
            "master_material": "",
        },
    }
    result = build_script_generation_prompt(
        role_name="Ye",
        peer_name="Ling",
        role_id="ye",
        peer_role_id="ling",
        topic="离心机报错",
        situation="Ye刚结束实验回宿舍",
        opening_idea="吐槽实验里的插曲",
        recent_master_history="",
        recent_peer_scripts="",
        time_str="2026-09-04 00:20",
        bio_state=None,
        peer_bio_state=None,
        knowledge=knowledge,
        avoid=["不要问泛泛的你在干嘛"],
    )
    up = result.user_prompt
    _check("剧本 prompt 含共同可见", "共同可见的现状" in up, "")
    _check("剧本 prompt 含自己视角", "【Ye视角】" in up or "Ye的视角" in up, up[:200])
    _check("剧本 prompt 私有状态标注", "只有你自己知道" in up, "")
    _check("剧本 prompt 对方视角标注", "仅供判断对方可能知道什么" in up, "")
    _check("剧本 prompt 注入 avoid", "不要问泛泛的你在干嘛" in up, "")
    # 分桶模式不得出现旧的合并渲染提示语
    _check("剧本 prompt 不再出现旧合并素材块", "双方最近和主人Master的互动" not in up, "")


# ── 6. 决策 prompt 硬门槛下放 ───────────────────────────────
def check_decision_prompt_hard_gate() -> None:
    from core.agents.chat_agent_components.persona_system.prompt.qq_peer_context import (
        build_peer_chat_decision_prompt,
    )

    result = build_peer_chat_decision_prompt(
        role_name="Ye",
        peer_name="Ling",
        time_str="2026-09-04 00:20",
        energy=10.0,
        mood="低落",
        elapsed_seconds=600,
        recent_topics=[],
        social_events_hint="",
        bio_state={},
    )
    sys_p = result.system_prompt
    _check("决策 prompt 硬门槛由代码层判断", "代码层判断" in sys_p, "")
    _check("决策 prompt 不再纠结时间冷却", "不需要纠结这些" in sys_p, "")
    _check("决策 prompt 含收敛字段说明", "conversation_seed" in sys_p, "")
    _check("决策 prompt 不含 thought 输出要求", "thought" not in sys_p, "")


# ── 7. 剧本模板规则软化 ─────────────────────────────────────
def check_script_template_softened() -> None:
    import os

    from core.agents.chat_agent_components.persona_system.prompt import (
        qq_peer_context,
    )

    tpl_path = os.path.join(
        os.path.dirname(os.path.abspath(qq_peer_context.__file__)),
        "peer_chat_script_system.txt",
    )
    text = Path(tpl_path).read_text(encoding="utf-8")

    _check("模板: 长度分布化 4-24字", "4-24 个汉字" in text and "必要时允许更短或稍长" in text, "")
    _check("模板: 轮数无下限", "2-6 个 turn" in text and "不得为了达到轮数强行续聊" in text, "")
    _check("模板: 信息权限最高级", "信息权限（最高优先级）" in text, "")
    _check("模板: 反剧本规则", "不要把对话写成双方预先知道彼此接下来会说什么的剧本" in text, "")
    _check("模板: 真实语料仅学风格", "仅用于学习句长、接话节奏" in text, "")
    _check("模板: 口头禅改为概率式", "不要为了表现角色而刻意重复标志性词汇" in text, "")
    _check("模板: mention_reason", "mention_reason" in text, "")
    # 不应残留旧的硬性 5-20 字 / 必须 3-6 轮表述
    _check("模板: 无旧硬长度", "5-20" not in text and "5–20" not in text, "")
    _check("模板: 无旧必须3轮", "必须" not in text.split("字数与轮数")[1].split("信息权限")[0], text.split("字数与轮数")[1].split("信息权限")[0])


# ── 8. 实时私聊 Persona slicing ─────────────────────────────
def check_persona_slicing() -> None:
    from core.agents.chat_agent_components.persona_system.prompt.qq_peer_context import (
        build_qq_peer_role_context,
    )

    ctx = {
        "sender_role_name": "Ling",
        "recipient_role_name": "Ye",
        "sender_personality": "嘴硬但其实挺会照顾人",
        "sender_speaking_style": "说话直接",
        "sender_relationship": "室友，一起住了很久",
        "recipient_personality": "傲娇但心软",
        "recipient_speaking_style": "毒舌碎碎念",
        "recent_events": "",
    }
    out = build_qq_peer_role_context(ctx)
    _check("slicing: 声明不是跟主人聊", "不是跟主人" in out or "不是在跟主人" in out, "")
    _check("slicing: 我眼中的对方", "你眼中" in out or "你眼中的" in out, out[:200])
    _check("slicing: 室友语境", "室友语境" in out, "")
    # 不应注入 user-specific relationship layer 的措辞
    for bad in ("private overlay", "服从安排", "主人专属"):
        _check(f"slicing: 不含用户专属层 {bad}", bad not in out, "")


def main() -> int:
    check_secret_filter()
    check_knowledge_buckets()
    check_script_validator()
    check_decision_output_convergence()
    check_script_prompt_knowledge_render()
    check_decision_prompt_hard_gate()
    check_script_template_softened()
    check_persona_slicing()

    if FAILURES:
        sys.stderr.write(f"\n共 {len(FAILURES)} 处失败。\n")
        sys.stderr.flush()
        return 1
    sys.stderr.write("Peer Chat 知识防火墙验证全部通过。\n")
    sys.stderr.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
