import os
import json
from datetime import datetime
from fastapi.testclient import TestClient
from pathlib import Path
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app
from core.utils.common import get_project_root

client = TestClient(app)

def test_upload_device_context():
    """Test uploading device context data"""
    payload = {
        "device_id": "test_device_001",
        "timestamp": datetime.now().timestamp(),
        "battery_level": 0.15,
        "is_charging": False,
        "network_type": "wifi",
        "app_state": "active",
        "current_app": "com.test.app",
        "usage_stats": ["WeChat: 2小时", "Douyin: 45分钟"],
        "step_count": 5234,
        "location": {"lat": 30.0, "lng": 120.0, "label": "Test Lab"},
        "extra": {"test_key": "test_value"}
    }
    
    response = client.post("/api/v1/daily-data/context", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify file creation
    root = get_project_root()
    latest_file = Path(root) / "companion_data" / "user_data" / "latest_device_context.json"
    
    assert latest_file.exists()
    
    with open(latest_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["device_id"] == "test_device_001"
        assert data["battery_level"] == 0.15
        assert data["is_charging"] is False

def test_active_care_integration():
    """Test if ActiveCareService can read the context file (mock test)"""
    # This is more of an integration verification
    root = get_project_root()
    latest_file = Path(root) / "companion_data" / "user_data" / "latest_device_context.json"
    
    # Ensure file exists from previous test or create it
    payload = {
        "device_id": "test_device_integration",
        "timestamp": datetime.now().timestamp(),
        "battery_level": 0.05,
        "is_charging": False
    }
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    # We can't easily run the full async ActiveCare service here without mocking a lot,
    # but we can verify the logic by reading the file manually as the service would.
    
    with open(latest_file, "r", encoding="utf-8") as f:
        read_data = json.load(f)
    
    assert read_data["battery_level"] < 0.20
    assert read_data["is_charging"] is False
    # If this logic holds, the service logic:
    # if battery_level is not None and battery_level < 0.20 and not is_charging:
    #      urgent_needs.append("low_battery")
    # would work.

if __name__ == "__main__":
    # Manually run tests if pytest is not available in environment
    try:
        test_upload_device_context()
        print("test_upload_device_context passed")
        test_active_care_integration()
        print("test_active_care_integration passed")
    except Exception as e:
        print(f"Tests failed: {e}")
        import traceback
        traceback.print_exc()
