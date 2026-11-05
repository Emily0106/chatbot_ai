#!/usr/bin/env python3
"""
Production Load Test Script
Tests blocking and streaming chat endpoints under load.
"""
import argparse
import asyncio
import json
import sys
import time
import statistics
from dataclasses import dataclass, field
from typing import List, Optional
import httpx

@dataclass
class Stats:
    total: int = 0
    success: int = 0
    http_4xx: int = 0
    http_5xx: int = 0
    errors: int = 0
    latencies: List[float] = field(default_factory=list)
    ttfe_list: List[float] = field(default_factory=list)  # Time to first event
    stream_events: int = 0
    
    def add_latency(self, lat: float):
        self.latencies.append(lat)
    
    def get_percentile(self, p: float) -> float:
        if not self.latencies:
            return 0.0
        return statistics.quantiles(sorted(self.latencies), n=100)[int(p)-1] if len(self.latencies) > 1 else self.latencies[0]

async def blocking_request(client: httpx.AsyncClient, url: str, headers: dict, stats: Stats):
    """Execute a single blocking request"""
    payload = {"message": "ping", "agent_id": "gov_assistant", "stream": False}
    
    start = time.time()
    try:
        resp = await client.post(url, json=payload, headers=headers, timeout=30.0)
        latency = time.time() - start
        
        stats.total += 1
        stats.add_latency(latency)
        
        if 200 <= resp.status_code < 300:
            stats.success += 1
        elif 400 <= resp.status_code < 500:
            stats.http_4xx += 1
        elif 500 <= resp.status_code < 600:
            stats.http_5xx += 1
    except Exception as e:
        stats.total += 1
        stats.errors += 1
        print(f"Request error: {e}")

async def streaming_request(client: httpx.AsyncClient, url: str, headers: dict, stats: Stats, max_events: int = 10):
    """Execute a single streaming request"""
    payload = {"message": "ping", "agent_id": "gov_assistant", "stream": True}
    
    start = time.time()
    first_event_time = None
    events_received = 0
    
    try:
        async with client.stream('POST', url, json=payload, headers=headers, timeout=60.0) as resp:
            stats.total += 1
            
            if resp.status_code >= 400:
                if 400 <= resp.status_code < 500:
                    stats.http_4xx += 1
                else:
                    stats.http_5xx += 1
                return
            
            async for line in resp.aiter_lines():
                if not line or not line.startswith('data:'):
                    continue
                
                if first_event_time is None:
                    first_event_time = time.time()
                    ttfe = first_event_time - start
                    stats.ttfe_list.append(ttfe)
                
                events_received += 1
                stats.stream_events += 1
                
                if events_received >= max_events:
                    break
            
            latency = time.time() - start
            stats.add_latency(latency)
            stats.success += 1
            
    except Exception as e:
        stats.total += 1
        stats.errors += 1
        print(f"Streaming error: {e}")

async def worker(client: httpx.AsyncClient, url: str, headers: dict, stats: Stats, 
                mode: str, end_time: float, sleep_interval: float, stream_events: int):
    """Worker coroutine that sends requests until end_time"""
    while time.time() < end_time:
        if mode == "blocking":
            await blocking_request(client, url, headers, stats)
        elif mode == "streaming":
            await streaming_request(client, url, headers, stats, stream_events)
        
        # Check for fail-fast condition
        total = stats.total
        if total > 50:  # After warmup
            error_rate = (stats.http_5xx + stats.errors) / total
            if error_rate > 0.05:
                print(f"\n⚠️  ERROR RATE > 5% ({error_rate*100:.1f}%) - STOPPING")
                return
        
        await asyncio.sleep(sleep_interval)

async def run_load_test(args):
    """Main load test orchestrator"""
    url = f"{args.base_url}/api/chat"
    headers = {"X-API-Key": args.api_key}
    
    # Configure SSL
    if args.insecure_tls:
        verify = False
    else:
        verify = True
    
    stats = Stats()
    
    # Calculate sleep interval per worker to achieve target RPS
    if args.mode == "blocking" and args.rps:
        sleep_interval = args.concurrency / args.rps
    else:
        sleep_interval = 0.1  # Streaming: minimal throttle
    
    end_time = time.time() + args.duration_s
    
    print(f"🚀 Starting {args.mode} load test")
    print(f"   Base URL: {args.base_url}")
    print(f"   Mode: {args.mode}")
    print(f"   Concurrency: {args.concurrency}")
    if args.rps:
        print(f"   Target RPS: {args.rps}")
    print(f"   Duration: {args.duration_s}s")
    print(f"   Workers sleep: {sleep_interval:.2f}s\n")
    
    async with httpx.AsyncClient(verify=verify) as client:
        workers = [
            worker(client, url, headers, stats, args.mode, end_time, sleep_interval, args.stream_events)
            for _ in range(args.concurrency)
        ]
        
        await asyncio.gather(*workers, return_exceptions=True)
    
    # Print results
    print("\n" + "="*60)
    print("LOAD TEST RESULTS")
    print("="*60)
    print(f"Total Requests:  {stats.total}")
    print(f"Success (2xx):   {stats.success}")
    print(f"Client 4xx:      {stats.http_4xx}")
    print(f"Server 5xx:      {stats.http_5xx}")
    print(f"Errors:          {stats.errors}")
    
    if stats.latencies:
        print(f"\nLatency (seconds):")
        print(f"  p50:  {stats.get_percentile(50):.3f}s")
        print(f"  p95:  {stats.get_percentile(95):.3f}s")
        print(f"  p99:  {stats.get_percentile(99):.3f}s")
    
    if args.mode == "streaming":
        print(f"\nStreaming Stats:")
        print(f"  Events received: {stats.stream_events}")
        if stats.ttfe_list:
            print(f"  TTFE p50: {statistics.median(stats.ttfe_list):.3f}s")
    
    # Evaluate pass/fail
    error_rate = (stats.http_5xx + stats.errors) / stats.total if stats.total > 0 else 0
    print(f"\nError Rate: {error_rate*100:.2f}%")
    
    if error_rate > 0.02:
        print("❌ FAIL: Error rate > 2%")
        return 1
    
    print("✅ PASS: Load test successful")
    return 0

def main():
    parser = argparse.ArgumentParser(description="Production Load Test")
    parser.add_argument("--base-url", required=True, help="Base URL (e.g., https://localhost:8443)")
    parser.add_argument("--api-key", required=True, help="API key for authentication")
    parser.add_argument("--mode", required=True, choices=["blocking", "streaming", "mixed"], help="Test mode")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent workers")
    parser.add_argument("--rps", type=int, help="Target requests per second (blocking only)")
    parser.add_argument("--duration-s", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--stream-events", type=int, default=10, help="Events to read per stream")
    parser.add_argument("--insecure-tls", action="store_true", help="Skip TLS verification")
    
    args = parser.parse_args()
    
    if args.mode == "mixed":
        print("❌ Mixed mode not yet implemented")
        return 1
    
    exit_code = asyncio.run(run_load_test(args))
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
