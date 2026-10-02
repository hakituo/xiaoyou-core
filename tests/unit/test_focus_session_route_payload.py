# -*- coding: utf-8 -*-
"""FocusSession 跨端响应、计划项关联与正式会话禁探班契约。"""

import asyncio
import json
import time

from core.services.study.focus_session_models import FocusSession
from routers.v1 import study_focus
from routers.v1.study_focus import _live_session_payload


def test_live_session_payload_keeps_web_and_android_shapes():
    now = time.time()
    sess = FocusSession(
        session_id="route-contract",
        user_id="default",
        subject="物理·简谐运动",
        planned_minutes=25,
        plan_item_id="plan_shm",
        plan_date="2026-09-14",
        monitoring=False,
        status="active",
        created_at=now - 120,
        started_at=now - 120,
        last_resume_at=now - 120,
        accumulated_active_seconds=0.0,
    )

    payload = _live_session_payload(sess)

    assert payload["session_id"] == "route-contract"
    assert payload["subject"] == "物理·简谐运动"
    assert payload["plan_item_id"] == "plan_shm"
    assert payload["plan_date"] == "2026-09-14"

    assert payload["session"]["session_id"] == "route-contract"
    assert payload["session"]["plan_item_id"] == "plan_shm"
    assert payload["session"]["plan_date"] == "2026-09-14"
    assert "session" not in payload["session"]

    assert payload["effective_minutes"] >= 1.5
    assert 0 < payload["remaining_seconds"] < 25 * 60


def test_start_session_persists_optional_plan_link(monkeypatch):
    class FakeService:
        def start_session(
            self,
            user_id: str,
            subject: str,
            planned_minutes: int,
            mode: str,
            monitoring: bool,
            plan_item_id: str | None,
            plan_date: str | None,
        ):
            return FocusSession(
                session_id="linked-focus",
                user_id=user_id,
                subject=subject,
                planned_minutes=planned_minutes,
                plan_item_id=plan_item_id,
                plan_date=plan_date,
                mode=mode,
                monitoring=monitoring,
                status="active",
            )

    fake = FakeService()
    monkeypatch.setattr(study_focus, "_svc", lambda: fake)

    response = asyncio.run(
        study_focus.start_session(
            study_focus.StartSessionReq(
                subject="数学 · 指数对数",
                planned_minutes=50,
                plan_item_id="plan_math_exp_log",
                plan_date="2026-09-14",
            ),
            user_id="default",
        )
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["ok"] is True
    assert payload["data"]["plan_item_id"] == "plan_math_exp_log"
    assert payload["data"]["plan_date"] == "2026-09-14"


def test_live_session_payload_never_adds_raw_media_fields():
    now = time.time()
    sess = FocusSession(
        session_id="privacy-contract",
        user_id="default",
        subject="数学",
        planned_minutes=25,
        monitoring=False,
        status="paused",
        created_at=now,
        started_at=now,
        accumulated_active_seconds=60.0,
    )

    payload = _live_session_payload(sess)
    serialized_keys = set(payload) | set(payload["session"])
    assert not ({"image", "frame", "base64", "audio", "video"} & serialized_keys)


def test_formal_focus_nudge_endpoint_never_sends(monkeypatch):
    class FakeService:
        def get_current(self, user_id: str):
            return FocusSession(
                session_id="formal-focus",
                user_id=user_id,
                subject="数学",
                planned_minutes=25,
                status="active",
            )

        def maybe_nudge(self, user_id: str):  # pragma: no cover
            raise AssertionError("正式 FocusSession 不应评估/发送 focus_nudge")

    monkeypatch.setattr(study_focus, "_svc", lambda: FakeService())

    response = asyncio.run(
        study_focus.trigger_nudge("formal-focus", user_id="default")
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["ok"] is True
    assert payload["data"] == {
        "sent": False,
        "reason": "formal_focus_session_suppressed",
    }
