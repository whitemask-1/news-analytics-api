import requests
import time
from typing import Dict, Any
import json

BASE_URL = "http://localhost:8000"

class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'

def print_header(text: str):
    print(f"\n{Colors.BLUE}{'='*50}{Colors.NC}")
    print(f"{Colors.BLUE}{text}{Colors.NC}")
    print(f"{Colors.BLUE}{'='*50}{Colors.NC}\n")

def print_test(name: str):
    print(f"{Colors.YELLOW}{name}{Colors.NC}")

def print_result(passed: bool):
    if passed:
        print(f"{Colors.GREEN}✓ PASS{Colors.NC}\n")
    else:
        print(f"{Colors.RED}✗ FAIL{Colors.NC}\n")

def test_health_check():
    print_test("Test 1: Health Check")
    response = requests.get(f"{BASE_URL}/api/v1/health")
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    print_result(response.status_code == 200)

def test_root_endpoint():
    print_test("Test 2: Root Endpoint")
    response = requests.get(f"{BASE_URL}/")
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    print_result(response.status_code == 200)

def test_ingest_single():
    print_test("Test 3: Ingest Single Article")
    response = requests.post(
        f"{BASE_URL}/api/v1/ingest",
        json={"query": "technology", "limit": 1}
    )
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Count: {data.get('count')}")
    print(f"Message: {data.get('message')}")
    print_result(response.status_code == 200 and data.get('count') >= 0)

def test_ingest_multiple():
    print_test("Test 4: Ingest Multiple Articles")
    response = requests.post(
        f"{BASE_URL}/api/v1/ingest",
        json={"query": "climate change", "limit": 5}
    )
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Count: {data.get('count')}")
    if data.get('articles_preview'):
        article = data['articles_preview'][0]
        print(f"Sample Article:")
        print(f"  Source: {article.get('source')}")
        print(f"  Title: {article.get('title')}")
    print_result(response.status_code == 200)

def test_different_queries():
    print_test("Test 5: Different Query Topics")
    topics = ["artificial intelligence", "bitcoin", "sports", "healthcare"]
    
    for topic in topics:
        response = requests.post(
            f"{BASE_URL}/api/v1/ingest",
            json={"query": topic, "limit": 2}
        )
        if response.status_code == 200:
            count = response.json().get('count', 0)
            print(f"  {topic}: {Colors.GREEN}✓ Success (fetched {count} articles){Colors.NC}")
        else:
            print(f"  {topic}: {Colors.RED}✗ Failed (HTTP {response.status_code}){Colors.NC}")
    print()

def test_validation_empty_query():
    print_test("Test 6: Validation - Empty Query")
    response = requests.post(
        f"{BASE_URL}/api/v1/ingest",
        json={"query": "", "limit": 1}
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 422:
        print("Validation error (expected):")
        print(json.dumps(response.json(), indent=2))
    print_result(response.status_code == 422)

def test_validation_limit_too_high():
    print_test("Test 7: Validation - Limit > 100")
    response = requests.post(
        f"{BASE_URL}/api/v1/ingest",
        json={"query": "test", "limit": 150}
    )
    print(f"Status: {response.status_code}")
    print_result(response.status_code == 422)

def test_rate_limiting():
    print_test("Test 8: Rate Limiting (10 requests/minute)")
    
    # Wait for rate limit window to reset
    print(f"{Colors.YELLOW}Waiting 60 seconds for rate limit to reset...{Colors.NC}")
    time.sleep(60)
    
    print("Sending 12 rapid requests...")
    
    success_count = 0
    rate_limited_count = 0
    
    for i in range(1, 13):
        response = requests.post(
            f"{BASE_URL}/api/v1/ingest",
            json={"query": "ratelimittest", "limit": 1}
        )
        
        if response.status_code == 200:
            success_count += 1
            print(f"  Request {i}: {Colors.GREEN}200 OK{Colors.NC}")
        elif response.status_code == 429:
            rate_limited_count += 1
            print(f"  Request {i}: {Colors.YELLOW}429 Rate Limited{Colors.NC}")
        else:
            print(f"  Request {i}: {Colors.RED}{response.status_code}{Colors.NC}")
        
        time.sleep(0.2)  # Small delay to prevent exact timing issues
    
    print(f"\nResults:")
    print(f"  Successful: {success_count}")
    print(f"  Rate Limited: {rate_limited_count}")
    
    # More lenient check (allow 9-10 successes)
    if success_count >= 9 and rate_limited_count >= 2:
        print_result(True)
    else:
        print(f"{Colors.YELLOW}⚠ Expected ~10 success, ~2 rate limited{Colors.NC}")
        print_result(False)

def test_response_schema():
    print_test("Test 9: Response Schema Validation")
    
    # Make sure we can make a request first
    print("Waiting 60 seconds to avoid rate limiting...")
    time.sleep(60)
    
    response = requests.post(
        f"{BASE_URL}/api/v1/ingest",
        json={"query": "schematest", "limit": 1}
    )
    
    print(f"Status: {response.status_code}")
    
    if response.status_code != 200:
        print(f"{Colors.RED}Got HTTP {response.status_code}, cannot test schema{Colors.NC}")
        print(f"Response: {response.text}")
        print_result(False)
        return
    
    data = response.json()
    
    required_fields = ["status", "count", "articles_preview", "message"]
    all_present = True
    
    for field in required_fields:
        if field in data:
            print(f"  Field '{field}': {Colors.GREEN}✓ Present{Colors.NC}")
        else:
            print(f"  Field '{field}': {Colors.RED}✗ Missing{Colors.NC}")
            all_present = False
    
    print_result(all_present)

def test_article_schema():
    print_test("Test 10: Article Schema Validation")
    
    response = requests.post(
        f"{BASE_URL}/api/v1/ingest",
        json={"query": "technology", "limit": 1}
    )
    
    print(f"Status: {response.status_code}")
    
    if response.status_code != 200:
        print(f"{Colors.RED}Got HTTP {response.status_code}, cannot test schema{Colors.NC}")
        print(f"Response: {response.text}")
        print_result(False)
        return
    
    data = response.json()
    
    if not data.get('articles_preview'):
        print(f"{Colors.RED}No articles in response{Colors.NC}")
        print(f"Full response: {json.dumps(data, indent=2)}")
        print_result(False)
        return
    
    article = data['articles_preview'][0]
    required_fields = ["source", "title", "url", "published_at", "topic"]
    all_present = True
    
    for field in required_fields:
        if field in article:
            print(f"  Field '{field}': {Colors.GREEN}✓ Present{Colors.NC}")
        else:
            print(f"  Field '{field}': {Colors.RED}✗ Missing{Colors.NC}")
            all_present = False
    
    print_result(all_present)

def main():
    print_header("News Analytics API - Test Suite")
    
    print(f"{Colors.YELLOW}NOTE: This test suite includes wait times to avoid rate limiting.{Colors.NC}")
    print(f"{Colors.YELLOW}Total runtime: ~3 minutes{Colors.NC}\n")
    
    try:
        test_health_check()
        test_root_endpoint()
        test_ingest_single()
        test_ingest_multiple()
        test_different_queries()
        test_validation_empty_query()
        test_validation_limit_too_high()
        test_rate_limiting()
        test_response_schema()
        test_article_schema()
        
        print_header("Test Suite Complete")
        print("\nCheck API documentation at:")
        print(f"  {BASE_URL}/docs\n")
        
    except requests.exceptions.ConnectionError:
        print(f"{Colors.RED}Error: Cannot connect to {BASE_URL}{Colors.NC}")
        print("Make sure the server is running:")
        print("  uvicorn app.main:app --reload")
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Test suite interrupted by user{Colors.NC}")

if __name__ == "__main__":
    main()