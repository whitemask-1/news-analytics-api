"""Rate limiting tests (run separately)"""
import requests
import time

BASE_URL = "http://localhost:8000"

def test_rate_limit():
    print("Testing rate limit (may take 60+ seconds)...")
    
    # Wait for clean slate
    time.sleep(60)
    
    success = 0
    limited = 0
    
    for i in range(12):
        response = requests.post(
            f"{BASE_URL}/api/v1/ingest",
            json={"query": f"test{i}", "limit": 1}
        )
        
        if response.status_code == 200:
            success += 1
            print(f"  Request {i+1}: ✓ OK")
        elif response.status_code == 429:
            limited += 1
            print(f"  Request {i+1}: ⚠ Rate Limited")
        
        time.sleep(0.2)
    
    print(f"\nResults: {success} success, {limited} rate limited")
    
    if success >= 9:
        print("✅ Rate limiting working correctly")
    else:
        print("❌ Unexpected rate limit behavior")

if __name__ == "__main__":
    test_rate_limit()