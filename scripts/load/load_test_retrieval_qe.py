#!/usr/bin/env python3
"""
Gov-Grade Query Expansion — Locust Benchmark Script
Measures retrieval latency P50/P95/P99 across 4 query scenarios.

Usage:
  # Quick smoke run (2 users, 10s)
  locust -f scripts/load/load_test_retrieval_qe.py --headless -u 2 -r 1 --run-time 10s

  # Full benchmark (10 users, 60s, CSV export)
  locust -f scripts/load/load_test_retrieval_qe.py --headless -u 10 -r 2 --run-time 60s --csv=benchmark_qe

  # Phase comparison (run twice: QE off vs QE on)
  ENABLE_QUERY_EXPANSION=0 docker compose up -d backend
  locust ... --csv=benchmark_qe_OFF
  ENABLE_QUERY_EXPANSION=1 docker compose up -d backend
  locust ... --csv=benchmark_qe_ON

Config via env:
  BASE_URL      default http://localhost:8000
  AUTH_TOKEN     API key / Bearer token (if required)
  AGENT_ID      default gov_assistant
  TENANT_ID     default test-tenant
"""
from __future__ import annotations

import os
import random

from locust import HttpUser, task, between, tag


# ──────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────

AGENT_ID = os.getenv("AGENT_ID", "gov_assistant")
TENANT_ID = os.getenv("TENANT_ID", "test-tenant")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")

ENDPOINT = "/api/chat"

# ──────────────────────────────────────────────────────────────────
# Query Pools (4 scenarios from Epic Closeout)
# ──────────────────────────────────────────────────────────────────

CITIZEN_QUERIES = [
    "thủ tục đăng ký khai sinh",
    "quy trình cấp sổ đỏ",
    "hướng dẫn đăng ký tạm trú",
    "điều kiện xin cấp giấy phép xây dựng",
    "cách đăng ký kết hôn online",
    "thời gian giải quyết hồ sơ hộ khẩu",
    "quy trình cấp lại giấy khai sinh bị mất",
    "yêu cầu giấy tờ chứng minh nhân dân",
    "đăng ký giấy phép kinh doanh hộ gia đình",
    "thủ tục xin visa du lịch",
]

CODE_QUERIES = [
    "nghị định 43/2014/NĐ-CP",
    "thông tư 24/2014/TT-BTNMT",
    "luật đất đai 2013 điều 62",
    "nghị quyết 1024/NQ-UBTVQH13",
    "thông tư 36/2014/TT-NHNN",
    "quyết định 1956/QĐ-TTg",
    "nghị định 01/2017/NĐ-CP điều 5",
    "luật doanh nghiệp 2020 khoản 3",
]

PII_QUERIES = [
    "thủ tục cấp lại CCCD số 001234567890",
    "tra cứu hồ sơ Nguyễn Văn A sinh 01/01/1990",
    "liên hệ hotline 0987654321 để hỗ trợ",
    "email nguyen.van.a@gmail.com đã đăng ký chưa",
    "số BHXH 0012345678 của tôi bị lỗi",
]

ADVERSARIAL_QUERIES = [
    "'; DROP TABLE documents; --",
    "UNION SELECT * FROM users WHERE 1=1",
    "a" * 500,  # Max-length query
    "<script>alert('xss')</script>",
    "{{constructor.constructor('return this')()}}",
    "thủ tục" + " rất" * 100,  # Repetition attack
]

ALL_POOLS = {
    "citizen": CITIZEN_QUERIES,
    "code": CODE_QUERIES,
    "pii": PII_QUERIES,
    "adversarial": ADVERSARIAL_QUERIES,
}


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _build_payload(query: str) -> dict:
    return {
        "message": query,
        "agent_id": AGENT_ID,
        "stream": False,  # Blocking mode for stable latency measurement
    }


def _headers() -> dict:
    h = {
        "Content-Type": "application/json",
        "X-Tenant-Id": TENANT_ID,
    }
    if AUTH_TOKEN:
        h["Authorization"] = f"Bearer {AUTH_TOKEN}"
    return h


# ──────────────────────────────────────────────────────────────────
# Locust User
# ──────────────────────────────────────────────────────────────────

class QEBenchmarkUser(HttpUser):
    """
    Load test user that exercises 4 query categories.
    Weight distribution: citizen 50%, code 25%, PII 15%, adversarial 10%.
    """
    wait_time = between(0.5, 2.0)
    host = os.getenv("BASE_URL", "http://localhost:8000")

    @tag("citizen")
    @task(5)
    def citizen_query(self):
        q = random.choice(CITIZEN_QUERIES)
        self.client.post(
            ENDPOINT,
            json=_build_payload(q),
            headers=_headers(),
            name="[citizen] /api/chat",
        )

    @tag("code")
    @task(3)
    def code_query(self):
        q = random.choice(CODE_QUERIES)
        self.client.post(
            ENDPOINT,
            json=_build_payload(q),
            headers=_headers(),
            name="[code] /api/chat",
        )

    @tag("pii")
    @task(2)
    def pii_query(self):
        q = random.choice(PII_QUERIES)
        self.client.post(
            ENDPOINT,
            json=_build_payload(q),
            headers=_headers(),
            name="[pii] /api/chat",
        )

    @tag("adversarial")
    @task(1)
    def adversarial_query(self):
        q = random.choice(ADVERSARIAL_QUERIES)
        self.client.post(
            ENDPOINT,
            json=_build_payload(q),
            headers=_headers(),
            name="[adversarial] /api/chat",
        )
