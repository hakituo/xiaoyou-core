"""``core/models/message.py`` 单元测试。

覆盖：MessageType 枚举取值、MessageResource / UnifiedMessage 的默认值与
default_factory 隔离、add_image / add_audio 的资源追加与元数据拼装、
to_frontend_dict 的全部可选字段分支与资源平铺分支、以及 dataclass 生成的
__eq__ / __repr__ 协议方法。

全部用例均为纯内存对象操作，不依赖时钟、随机数与外部资源。
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict

from core.models.message import MessageResource, MessageType, UnifiedMessage

# uuid4 的规范文本形态（第 3 组以 4 开头、第 4 组以 8/9/a/b 开头）
_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


# --------------------------------------------------------------------------- #
# MessageType
# --------------------------------------------------------------------------- #
def test_message_type_values_are_stable():
    """枚举成员名与字符串值必须与前端约定的字面量一致。"""
    assert MessageType.TEXT.value == "text"
    assert MessageType.IMAGE.value == "image"
    assert MessageType.VOICE.value == "voice"
    assert MessageType.SYSTEM.value == "system"
    assert MessageType.REACTION.value == "reaction"
    assert MessageType.RETRACTION.value == "retraction"
    assert MessageType.ERROR.value == "error"
    assert len(MessageType) == 7


def test_message_type_is_str_enum():
    """继承 str 的枚举可直接与字符串比较，也能按值反查成员。"""
    assert MessageType.TEXT == "text"
    assert MessageType("image") is MessageType.IMAGE
    assert isinstance(MessageType.VOICE, str)


# --------------------------------------------------------------------------- #
# MessageResource
# --------------------------------------------------------------------------- #
def test_message_resource_defaults_and_metadata_isolation():
    """可选字段默认 None，metadata 由 default_factory 提供且互不共享。"""
    r1 = MessageResource(type="image")
    r2 = MessageResource(type="image")

    assert r1.url is None
    assert r1.base64 is None
    assert r1.path is None
    assert r1.metadata == {}
    # 两个实例的 metadata 必须是不同的 dict，否则会跨对象串数据
    assert r1.metadata is not r2.metadata
    r1.metadata["k"] = "v"
    assert r2.metadata == {}


def test_message_resource_eq_and_repr():
    """dataclass 自动生成的 __eq__ / __repr__ 行为。"""
    a = MessageResource(type="audio", url="u", metadata={"duration": 1.5})
    b = MessageResource(type="audio", url="u", metadata={"duration": 1.5})
    c = MessageResource(type="audio", url="other")

    assert a == b
    assert a != c
    # 与其它类型比较应返回 NotImplemented -> False，而不是抛异常
    assert a != "audio"
    text = repr(a)
    assert text.startswith("MessageResource(")
    assert "type='audio'" in text
    # asdict 可正常深拷贝出普通 dict（前端序列化常见用法）
    assert asdict(a) == {
        "type": "audio",
        "url": "u",
        "base64": None,
        "path": None,
        "metadata": {"duration": 1.5},
    }


# --------------------------------------------------------------------------- #
# UnifiedMessage 默认值
# --------------------------------------------------------------------------- #
def test_unified_message_defaults():
    """仅传 content 时的全部默认值。"""
    before = time.time()
    msg = UnifiedMessage(content="hello")
    after = time.time()

    assert msg.content == "hello"
    assert msg.message_type is MessageType.TEXT
    assert msg.conversation_id == "default"
    assert msg.sender_id == "system"
    assert msg.emotion is None
    assert msg.emotion_internal is None
    assert msg.resources == []
    assert msg.request_id is None
    assert msg.status == "created"
    # id 必须是 uuid4 文本
    assert _UUID4_RE.match(msg.id) is not None
    # 时间戳取自 time.time()：夹在调用前后取到的值之间（不依赖真实耗时）
    assert before <= msg.timestamp <= after


def test_unified_message_ids_and_timestamps_are_unique():
    """default_factory 每次调用都要产出新值，不能是共享的类级常量。"""
    m1 = UnifiedMessage(content="a")
    m2 = UnifiedMessage(content="b")

    assert m1.id != m2.id
    assert m1.resources is not m2.resources


def test_unified_message_explicit_fields_override_defaults():
    """显式传入的字段必须覆盖默认值。"""
    msg = UnifiedMessage(
        content="pic",
        message_type=MessageType.IMAGE,
        id="fixed-id",
        timestamp=1234.5,
        conversation_id="conv-1",
        sender_id="user",
        emotion="happy",
        emotion_internal={"label": "joy", "score": 0.9},
        resources=[MessageResource(type="image", url="http://x/1.png")],
        request_id="req-1",
        status="sent",
    )

    assert msg.message_type is MessageType.IMAGE
    assert msg.id == "fixed-id"
    assert msg.timestamp == 1234.5
    assert msg.conversation_id == "conv-1"
    assert msg.sender_id == "user"
    assert msg.emotion == "happy"
    assert msg.emotion_internal == {"label": "joy", "score": 0.9}
    assert len(msg.resources) == 1
    assert msg.request_id == "req-1"
    assert msg.status == "sent"


def test_unified_message_eq_and_repr():
    """相同字段值相等；任一字段不同则不相等；repr 含类名与内容。"""
    kwargs = dict(content="hi", id="same-id", timestamp=1.0)
    assert UnifiedMessage(**kwargs) == UnifiedMessage(**kwargs)

    assert UnifiedMessage(**kwargs) != UnifiedMessage(content="bye", id="same-id", timestamp=1.0)
    assert UnifiedMessage(**kwargs) != UnifiedMessage(content="hi", id="other-id", timestamp=1.0)
    # resources 参与相等性比较
    with_res = UnifiedMessage(content="hi", id="same-id", timestamp=1.0)
    with_res.resources.append(MessageResource(type="image", url="u"))
    assert UnifiedMessage(**kwargs) != with_res

    text = repr(UnifiedMessage(**kwargs))
    assert text.startswith("UnifiedMessage(")
    assert "content='hi'" in text
    assert "message_type=<MessageType.TEXT: 'text'>" in text


# --------------------------------------------------------------------------- #
# add_image
# --------------------------------------------------------------------------- #
def test_add_image_with_all_sources():
    """三种来源（url / base64 / path）全部写入同一条 image 资源。"""
    msg = UnifiedMessage(content="")
    msg.add_image(url="http://a/1.png", base64_data="QUJD", path="C:/tmp/1.png")

    assert len(msg.resources) == 1
    res = msg.resources[0]
    assert res.type == "image"
    assert res.url == "http://a/1.png"
    assert res.base64 == "QUJD"
    assert res.path == "C:/tmp/1.png"
    assert res.metadata == {}


def test_add_image_without_arguments_records_empty_resource():
    """不传参数时仍然追加一条资源，且三个来源字段均为 None。"""
    msg = UnifiedMessage(content="")
    msg.add_image()

    assert len(msg.resources) == 1
    res = msg.resources[0]
    assert (res.type, res.url, res.base64, res.path) == ("image", None, None, None)


def test_add_image_appends_in_order():
    """多次调用按顺序追加，不会互相覆盖。"""
    msg = UnifiedMessage(content="")
    msg.add_image(url="u1")
    msg.add_image(base64_data="b2")

    assert [r.url for r in msg.resources] == ["u1", None]
    assert [r.base64 for r in msg.resources] == [None, "b2"]


# --------------------------------------------------------------------------- #
# add_audio
# --------------------------------------------------------------------------- #
def test_add_audio_with_duration():
    """duration 为真值时写入 metadata['duration']。"""
    msg = UnifiedMessage(content="")
    msg.add_audio(url="http://a/1.mp3", base64_data="QUJD", path="C:/tmp/1.mp3", duration=2.5)

    assert len(msg.resources) == 1
    res = msg.resources[0]
    assert res.type == "audio"
    assert res.url == "http://a/1.mp3"
    assert res.base64 == "QUJD"
    assert res.path == "C:/tmp/1.mp3"
    assert res.metadata == {"duration": 2.5}


def test_add_audio_without_duration_omits_key():
    """duration 缺省（None）时不产生 duration 键。"""
    msg = UnifiedMessage(content="")
    msg.add_audio(url="u")

    assert msg.resources[0].metadata == {}


def test_add_audio_zero_duration_is_falsy_and_omitted():
    """duration=0.0 被 `if duration` 判为假，因此不写入 metadata（记录现状）。"""
    msg = UnifiedMessage(content="")
    msg.add_audio(url="u", duration=0.0)

    assert "duration" not in msg.resources[0].metadata


# --------------------------------------------------------------------------- #
# to_frontend_dict —— 基础字段与可选字段分支
# --------------------------------------------------------------------------- #
def test_to_frontend_dict_minimal():
    """无资源、无可选字段时的最小输出，且可选键必须缺席。"""
    msg = UnifiedMessage(content="hi", id="m1", timestamp=100.0, conversation_id="c1")
    data = msg.to_frontend_dict()

    assert data == {
        "type": "message",
        "subtype": "response",
        "message_id": "m1",
        "timestamp": 100.0,
        "conversation_id": "c1",
        "content": "hi",
        "messageType": "text",
    }


def test_to_frontend_dict_includes_optional_fields_when_truthy():
    """request_id / emotion / emotion_internal 为真值时才出现。"""
    msg = UnifiedMessage(
        content="hi",
        request_id="req-9",
        emotion="sad",
        emotion_internal={"label": "sadness", "score": 0.7},
    )
    data = msg.to_frontend_dict()

    assert data["request_id"] == "req-9"
    assert data["emotion"] == "sad"
    assert data["emotion_internal"] == {"label": "sadness", "score": 0.7}


def test_to_frontend_dict_omits_empty_optional_fields():
    """空字符串 / 空字典同样被当作假值而省略（记录现状）。"""
    msg = UnifiedMessage(content="hi", request_id="", emotion="", emotion_internal={})
    data = msg.to_frontend_dict()

    assert "request_id" not in data
    assert "emotion" not in data
    assert "emotion_internal" not in data


def test_to_frontend_dict_serializes_message_type_value():
    """messageType 取枚举的 .value，而非枚举对象本身。"""
    msg = UnifiedMessage(content="x", message_type=MessageType.ERROR)
    data = msg.to_frontend_dict()

    assert data["messageType"] == "error"
    assert isinstance(data["messageType"], str)


# --------------------------------------------------------------------------- #
# to_frontend_dict —— 资源平铺
# --------------------------------------------------------------------------- #
def test_to_frontend_dict_flattens_image_resource():
    """图片资源的三个来源平铺成 imageUrl / imageBase64 / imagePath。"""
    msg = UnifiedMessage(content="")
    msg.add_image(url="http://a/1.png", base64_data="QUJD", path="C:/tmp/1.png")
    data = msg.to_frontend_dict()

    assert data["imageUrl"] == "http://a/1.png"
    assert data["imageBase64"] == "QUJD"
    assert data["imagePath"] == "C:/tmp/1.png"


def test_to_frontend_dict_skips_falsy_image_sources():
    """图片资源里为 None 的来源不产生对应键。"""
    msg = UnifiedMessage(content="")
    msg.add_image(url="only-url")
    data = msg.to_frontend_dict()

    assert data["imageUrl"] == "only-url"
    assert "imageBase64" not in data
    assert "imagePath" not in data


def test_to_frontend_dict_flattens_audio_resource_with_voice_id():
    """音频资源平铺成 audio* 键，metadata.voice_id 提升为顶层 voiceId。"""
    msg = UnifiedMessage(content="")
    msg.resources.append(
        MessageResource(
            type="audio",
            url="http://a/1.mp3",
            base64="QUJD",
            path="C:/tmp/1.mp3",
            metadata={"duration": 1.2, "voice_id": "voice-7"},
        )
    )
    data = msg.to_frontend_dict()

    assert data["audioUrl"] == "http://a/1.mp3"
    assert data["audioBase64"] == "QUJD"
    assert data["audioPath"] == "C:/tmp/1.mp3"
    assert data["voiceId"] == "voice-7"


def test_to_frontend_dict_omits_voice_id_when_missing_or_empty():
    """没有 voice_id（或为空串）时不产生 voiceId 键。"""
    msg = UnifiedMessage(content="")
    msg.add_audio(url="u", duration=1.0)
    data = msg.to_frontend_dict()
    assert "voiceId" not in data

    msg2 = UnifiedMessage(content="")
    msg2.resources.append(MessageResource(type="audio", metadata={"voice_id": ""}))
    assert "voiceId" not in msg2.to_frontend_dict()


def test_to_frontend_dict_ignores_unknown_resource_type():
    """type 既非 image 也非 audio 的资源被静默忽略，不影响基础字段。"""
    msg = UnifiedMessage(content="hi")
    msg.resources.append(MessageResource(type="video", url="http://a/1.mp4"))
    data = msg.to_frontend_dict()

    assert "videoUrl" not in data
    assert data["content"] == "hi"
    assert data["type"] == "message"


def test_to_frontend_dict_multiple_images_last_one_wins():
    """多张图片时平铺键被后一张覆盖（前端扁平字段只能承载一张，记录现状）。"""
    msg = UnifiedMessage(content="")
    msg.add_image(url="u1")
    msg.add_image(url="u2")
    data = msg.to_frontend_dict()

    assert data["imageUrl"] == "u2"
    # 资源列表本身仍是完整的，未丢数据
    assert len(msg.resources) == 2


def test_to_frontend_dict_voice_message_branch_is_noop():
    """VOICE 类型走完空分支后输出与普通消息结构一致（仅 messageType 不同）。"""
    msg = UnifiedMessage(content="", message_type=MessageType.VOICE)
    data = msg.to_frontend_dict()

    assert data["messageType"] == "voice"
    assert set(data) == {
        "type",
        "subtype",
        "message_id",
        "timestamp",
        "conversation_id",
        "content",
        "messageType",
    }


def test_to_frontend_dict_does_not_mutate_message():
    """序列化是只读操作，重复调用结果一致且不改动源对象。"""
    msg = UnifiedMessage(content="hi", id="m1", timestamp=1.0, emotion="happy")
    msg.add_image(url="u")
    before = (msg.id, msg.timestamp, msg.content, msg.emotion, len(msg.resources))

    first = msg.to_frontend_dict()
    second = msg.to_frontend_dict()

    assert first == second
    assert (msg.id, msg.timestamp, msg.content, msg.emotion, len(msg.resources)) == before
    # 返回的是新 dict，改动它不影响后续调用
    first["content"] = "tampered"
    assert msg.to_frontend_dict()["content"] == "hi"
