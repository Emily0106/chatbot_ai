import json
import time
import asyncio
import requests
import statistics
import os
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv("env/dev.env")

API_URL = "http://localhost:8000/api/chat"
GOLDEN_FILE = "tests/golden_rag.jsonl"
REPORT_FILE = "reports/rag_eval.md"

def call_rag_api(query: str, agent_id: str = "citizen") -> Dict[str, Any]:
    """Call the RAG API."""
    try:
        resp = requests.post(
            API_URL,
            json={"agent_id": agent_id, "message": query},
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"API call failed: {e}")
        return {}

def check_hit(expected_chunk_id: str, citations: List[Dict[str, Any]], top_k: int = 3) -> bool:
    """Check if expected chunk is in top K citations."""
    if not citations:
        return False
    
    # Citations are usually ordered by score.
    # We check the first K citations.
    for i, cit in enumerate(citations[:top_k]):
        # Check chunk_id (or similar identifier)
        # Citation format: {"chunk_id": "...", "document_id": "...", ...}
        if str(cit.get("chunk_id")) == str(expected_chunk_id):
            return True
    return False

def check_must_contain(answer: str, must_contain: List[str]) -> bool:
    """Check if answer contains required keywords."""
    if not answer or not must_contain:
        return False
    
    answer_lower = answer.lower()
    for phrase in must_contain:
        if phrase.lower() not in answer_lower:
            return False
    return True

async def main():
    print("Running RAG Evaluation...")
    
    try:
        with open(GOLDEN_FILE, "r", encoding="utf-8") as f:
            golden_data = [json.loads(line) for line in f]
    except FileNotFoundError:
        print(f"Golden dataset not found at {GOLDEN_FILE}. Please run gen_golden_dataset.py first.")
        return

    results = []
    latencies = []
    
    print(f"Loaded {len(golden_data)} test cases.")
    
    for i, item in enumerate(golden_data):
        query = item["question"]
        expected_chunk_id = item.get("expected_chunk_id")
        must_contain = item.get("must_contain", [])
        
        print(f"[{i+1}/{len(golden_data)}] Testing: {query}")
        
        t0 = time.perf_counter()
        resp = call_rag_api(query)
        latency = (time.perf_counter() - t0) * 1000
        latencies.append(latency)
        
        citations = resp.get("citations", [])
        answer = resp.get("answer", "")
        
        hit_1 = check_hit(expected_chunk_id, citations, top_k=1)
        hit_3 = check_hit(expected_chunk_id, citations, top_k=3)
        content_match = check_must_contain(answer, must_contain)
        
        results.append({
            "id": item.get("id"),
            "hit_1": hit_1,
            "hit_3": hit_3,
            "content_match": content_match,
            "latency": latency,
            "fallback": "rerank_fallback" in resp.get("meta", {}).get("used_tools", [])
        })
        
        # Optional: Print failure details
        if not hit_3:
            print(f"  ❌ Missed Top-3. Expected: {expected_chunk_id}")
        
    # Calculate metrics
    total = len(results)
    if total == 0:
        print("No results.")
        return

    hit_1_rate = sum(1 for r in results if r["hit_1"]) / total
    hit_3_rate = sum(1 for r in results if r["hit_3"]) / total
    content_match_rate = sum(1 for r in results if r["content_match"]) / total
    fallback_rate = sum(1 for r in results if r["fallback"]) / total
    
    avg_latency = statistics.mean(latencies)
    p50_latency = statistics.median(latencies)
    p95_latency = statistics.quantiles(latencies, n=20)[-1] if len(latencies) >= 20 else max(latencies)

    report = f"""# RAG Evaluation Report
**Date:** {time.strftime("%Y-%m-%d %H:%M:%S")}
**Dataset:** {GOLDEN_FILE} (N={total})

## Metrics
*   **Hit@1:** {hit_1_rate:.2%}
*   **Hit@3:** {hit_3_rate:.2%}
*   **Content Match:** {content_match_rate:.2%}
*   **Rerank Fallback:** {fallback_rate:.2%}

## Latency
*   **Avg:** {avg_latency:.0f}ms
*   **P50:** {p50_latency:.0f}ms
*   **P95:** {p95_latency:.0f}ms

## Failures (Missed Top-3)
"""
    for r in results:
        if not r["hit_3"]:
            report += f"- {r['id']}: Missed Top-3 (Latency: {r['latency']:.0f}ms)\n"

    # Save report
    os.makedirs("reports", exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report)
        
    print("\n" + report)
    print(f"Report saved to {REPORT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
