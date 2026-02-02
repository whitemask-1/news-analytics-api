"""Basic functionality tests (no rate limiting concerns)"""
import requests
import json

BASE_URL = "http://localhost:8000"

def test_health():
    response = requests.get(f"{BASE_URL}/api/v1/health")
    assert response.status_code == 200
    print("✓ Health check passed")

def test_ingest():
    response = requests.post(
        f"{BASE_URL}/api/v1/ingest",
        json={"query": "test", "limit": 1}
    )
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "count" in data
    print("✓ Ingest endpoint passed")

if __name__ == "__main__":
    test_health()
    test_ingest()
    print("\n✅ All basic tests passed!")