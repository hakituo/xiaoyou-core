from __future__ import annotations

from core.agents.chat_agent_components.study import observe_learning_message
from core.services.study.signal_detector import LearningIntent, detect_learning_signal


def _write_registry(root) -> None:
    subjects = root / "Subjects"
    subjects.mkdir(parents=True, exist_ok=True)
    (subjects / "registry.yaml").write_text(
        """schema_version: 1
subjects:
  - id: philosophy
    name: 哲学
    aliases: [哲学, 认识论, 形而上学, 伦理学]
  - id: psychology
    name: 心理学
    aliases: [心理学, 认知失调, 认知心理]
  - id: geography
    name: 地理
    aliases: [地理, 地理学, 洋流, 地貌]
  - id: history
    name: 历史
    aliases: [历史, 历史学]
""",
        encoding="utf-8",
    )


def test_real_chat_science_and_engineering_subjects(study_sandbox) -> None:
    _write_registry(study_sandbox)
    cases = [
        ("为什么 F = -kx 里面有负号？", "physics"),
        ("为什么 v = v0 + at？", "physics"),
        ("2d 轨道和 2f 轨道存在吗？", "chemistry"),
        ("DNA 半保留复制是什么意思？", "biology"),
        ("任何振动是不是都可以用简谐表示，傅里叶呢？", "physics"),
        ("SYN 和 ACK 是什么？", "computer_networks"),
        ("GPU 的 SM 是不是类似 CPU 核数？", "computer_systems"),
        ("Gradle 为什么一直卡住？", "programming"),
    ]
    for message, subject in cases:
        signal = detect_learning_signal(message)
        assert signal.is_learning, message
        assert signal.subject == subject, (message, signal)


def test_real_technical_queries_are_recordable_without_manual_study_mode(
    study_sandbox,
) -> None:
    _write_registry(study_sandbox)
    for message, subject in (
        ("SYN 和 ACK 是什么？", "computer_networks"),
        ("GPU 的 SM 是不是类似 CPU 核数？", "computer_systems"),
        ("Gradle 为什么一直卡住？", "programming"),
    ):
        signal = detect_learning_signal(message)
        assert signal.concepts, (message, signal)
        result = observe_learning_message(message)
        assert result["status"] == "recorded", (message, result)
        assert result["subject"] == subject


def test_real_chat_humanities_registry_and_domain_hints(study_sandbox) -> None:
    _write_registry(study_sandbox)
    cases = [
        ("认识论是什么？", "philosophy"),
        ("认知失调是什么？", "psychology"),
        ("希腊文和拉丁文有什么区别？", "linguistics"),
        ("耶稣这句话原文是什么语言？", "religion"),
    ]
    for message, subject in cases:
        signal = detect_learning_signal(message)
        assert signal.intent == LearningIntent.TEACHING_REQUEST
        assert signal.subject == subject, (message, signal)
        assert signal.is_learning


def test_unknown_but_explicit_knowledge_query_is_kept_as_general(study_sandbox) -> None:
    _write_registry(study_sandbox)
    signal = detect_learning_signal("维基解密是什么？")
    assert signal.is_learning
    assert signal.subject == "general"
    assert "维基解密" in signal.concepts
    assert "open_domain_general" in signal.evidence

    result = observe_learning_message("维基解密是什么？")
    assert result["status"] == "recorded"
    assert result["subject"] == "general"


def test_non_learning_chatter_stays_out(study_sandbox) -> None:
    _write_registry(study_sandbox)
    assert detect_learning_signal("为什么你今天不开心").is_learning is False
    assert detect_learning_signal("请好好看你人设是什么样的").is_learning is False
