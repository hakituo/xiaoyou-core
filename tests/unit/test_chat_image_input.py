from __future__ import annotations

import asyncio
import base64

import core.image.chat_image_input as chat_image_input


def test_split_chat_image_message_extracts_caption_and_path():
    text, image_ref = chat_image_input.split_chat_image_message(
        "[图片: /output/image/uploads/a.jpg]\n帮我看看这张图"
    )

    assert text == "帮我看看这张图"
    assert image_ref == "/output/image/uploads/a.jpg"


def test_split_chat_image_message_uses_placeholder_for_image_only():
    text, image_ref = chat_image_input.split_chat_image_message(
        "[图片: /output/image/uploads/a.png]"
    )

    assert text == "（用户发送了一张图片）"
    assert image_ref == "/output/image/uploads/a.png"


def test_split_chat_image_message_rejects_non_upload_path():
    original = "[图片: /etc/passwd]"
    text, image_ref = chat_image_input.split_chat_image_message(original)

    assert text == original
    assert image_ref is None


def test_load_uploaded_image_data_url_reads_only_upload_directory(tmp_path, monkeypatch):
    raw = b"fake-png-bytes"
    uploads = tmp_path / "output" / "image" / "uploads"
    uploads.mkdir(parents=True)
    image_path = uploads / "sample.png"
    image_path.write_bytes(raw)

    monkeypatch.setattr(chat_image_input, "get_project_root", lambda: tmp_path)

    data_url = asyncio.run(
        chat_image_input.load_uploaded_image_data_url(
            "/output/image/uploads/sample.png"
        )
    )

    assert data_url is not None
    prefix, encoded = data_url.split(",", 1)
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded) == raw

    outside = tmp_path / "output" / "image" / "secret.png"
    outside.write_bytes(raw)
    rejected = asyncio.run(
        chat_image_input.load_uploaded_image_data_url(
            "/output/image/uploads/../secret.png"
        )
    )
    assert rejected is None
