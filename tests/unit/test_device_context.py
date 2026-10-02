import asyncio
import json
from datetime import datetime

from routers.v1 import context_device


def test_upload_device_context_writes_daily_and_latest_files(tmp_path, monkeypatch):
    daily_dir = tmp_path / "daily"
    latest_file = tmp_path / "latest_device_context.json"
    daily_dir.mkdir(parents=True)
    monkeypatch.setattr(context_device, "_ensure_daily_dir", lambda: daily_dir)
    monkeypatch.setattr(
        context_device,
        "get_user_latest_device_context_file",
        lambda: latest_file,
    )

    payload = context_device.DeviceContext(
        device_id="test_device_001",
        timestamp=datetime.now().timestamp(),
        battery_level=0.15,
        is_charging=False,
        network_type="wifi",
        app_state="active",
        current_app="com.test.app",
        usage_stats=["WeChat: 2小时", "Douyin: 45分钟"],
        step_count=5234,
        location={"lat": 30.0, "lng": 120.0, "label": "Test Lab"},
        extra={"test_key": "test_value"},
    )

    response = asyncio.run(context_device.upload_device_context(payload))

    assert response["status"] == "success"
    assert latest_file.exists()
    data = json.loads(latest_file.read_text(encoding="utf-8"))
    assert data["device_id"] == "test_device_001"
    assert data["battery_level"] == 0.15
    assert data["is_charging"] is False
    assert (daily_dir / "device_context.jsonl").exists()
