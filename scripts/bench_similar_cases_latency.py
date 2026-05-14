"""测量 POST /api/recommendations/similar-cases 的端到端墙钟耗时（对标浏览器 Network 总时长）。

用法（需已启动后端，默认 http://127.0.0.1:8000）::

    python scripts/bench_similar_cases_latency.py

环境变量::

    SIMILAR_CASES_BASE_URL  默认 http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import urljoin

try:
    import httpx
except ImportError:
    print("需要 httpx: pip install httpx", file=sys.stderr)
    raise SystemExit(1) from None


def main() -> int:
    base = os.environ.get("SIMILAR_CASES_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    url = urljoin(base + "/", "api/recommendations/similar-cases")
    body = {
        "query_text": (
            "我们是一家烤肉店，最近客人老是抱怨上肉太慢。"
            "后台看是因为肉类腌制和切片都在客人点单后才开始，厨师忙不过来。怎么优化？"
        ),
        "top_k": 20,
    }
    print("POST", url)
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, json=body)
    except httpx.ConnectError as exc:
        print("连接失败（后端是否在运行？）:", exc, file=sys.stderr)
        return 2
    elapsed = time.perf_counter() - t0
    print(f"HTTP {resp.status_code} wall_total_s={elapsed:.3f}")
    try:
        preview = json.dumps(resp.json(), ensure_ascii=False)[:500]
    except Exception:
        preview = resp.text[:500]
    print("body_preview:", preview)
    return 0 if resp.status_code < 500 else 1


if __name__ == "__main__":
    raise SystemExit(main())
