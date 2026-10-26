"""Small API smoke/load generator; use only against systems you own.

Example:
  python scripts/load_test.py --url http://127.0.0.1:8000 --requests 500 --concurrency 20
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time
import uuid
from collections import Counter

import httpx


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="", help="Bearer key; do not pass production secrets on shared machines")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.requests < 1 or args.requests > 100_000 or args.concurrency < 1 or args.concurrency > 500:
        parser.error("requests must be 1..100000 and concurrency must be 1..500")
    headers = {"Accept": "application/json"}
    if args.api_key:
        headers["Authorization"] = "Bearer " + args.api_key
    semaphore = asyncio.Semaphore(args.concurrency)
    durations: list[float] = []
    outcomes: Counter[str] = Counter()
    async with httpx.AsyncClient(base_url=args.url.rstrip("/"), headers=headers, timeout=args.timeout) as client:
        async def send(index: int) -> None:
            async with semaphore:
                start = time.perf_counter()
                try:
                    response = await client.post(
                        "/api/jobs",
                        headers={"Idempotency-Key": f"load-{uuid.uuid4().hex}"},
                        json={"task_type": "echo", "queue": "default", "priority": 5,
                              "payload": {"load_test_index": index}},
                    )
                    outcomes[str(response.status_code)] += 1
                except httpx.HTTPError as exc:
                    outcomes[type(exc).__name__] += 1
                durations.append((time.perf_counter() - start) * 1000)
        begin = time.perf_counter()
        await asyncio.gather(*(send(i) for i in range(args.requests)))
        elapsed = time.perf_counter() - begin
    ordered = sorted(durations)
    percentile = lambda p: ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))] if ordered else 0.0
    print(f"URL: {args.url}\nRequests: {args.requests}  concurrency: {args.concurrency}  duration: {elapsed:.2f}s")
    print(f"Throughput: {args.requests / max(elapsed, 0.001):.1f} requests/s  outcomes: {dict(outcomes)}")
    print(f"Latency ms: p50={statistics.median(ordered):.1f} p95={percentile(.95):.1f} p99={percentile(.99):.1f} max={max(ordered, default=0):.1f}")
    return 0 if sum(v for k, v in outcomes.items() if k.isdigit() and 200 <= int(k) < 300) == args.requests else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
