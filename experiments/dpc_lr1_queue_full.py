"""DPC ЛР1, О1.2: заповнена черга — 429 з Retry-After і p95 /health під навантаженням.

    QUEUE_CAPACITY=5 WORKERS=2 docker compose up -d dpc-api
    python experiments/dpc_lr1_queue_full.py --clients 30 --seconds 10

Клієнти без пауз подають дзвінки в район center; окремий клієнт що 20 мс опитує /health,
ще один — /metrics (довжина черги не має перевищити місткість).
"""

import argparse
import asyncio
import time
import uuid

import httpx

from common import DPC, DPC_TOKEN, pct, save


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clients", type=int, default=30)
    ap.add_argument("--seconds", type=float, default=10)
    args = ap.parse_args()

    headers = {"Authorization": f"Bearer {DPC_TOKEN}"}
    stop_at = time.perf_counter() + args.seconds
    statuses: dict[int, int] = {}
    no_retry_after = 0
    health_ms: list[float] = []
    queue_seen: list[int] = []
    run = uuid.uuid4().hex[:6]
    limits = httpx.Limits(max_connections=args.clients + 10)

    async with httpx.AsyncClient(base_url=DPC, headers=headers, timeout=10, limits=limits) as client:
        metrics0 = (await client.get("/metrics")).json()

        async def submitter(c: int) -> None:
            nonlocal no_retry_after
            i = 0
            while time.perf_counter() < stop_at:
                body = {"request_id": f"q-{run}-{c}-{i}", "district": "center", "kind": "food"}
                r = await client.post("/v1/assignment-requests", json=body)
                statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
                if r.status_code == 429:
                    if "retry-after" not in r.headers:
                        no_retry_after += 1
                    await asyncio.sleep(0.01)
                i += 1

        async def health() -> None:
            async with httpx.AsyncClient(base_url=DPC, timeout=5) as hc:
                while time.perf_counter() < stop_at:
                    t = time.perf_counter()
                    await hc.get("/health")
                    health_ms.append((time.perf_counter() - t) * 1000)
                    await asyncio.sleep(0.02)

        async def watch() -> None:
            async with httpx.AsyncClient(base_url=DPC, timeout=5) as mc:
                while time.perf_counter() < stop_at:
                    queue_seen.append((await mc.get("/metrics")).json()["queue_length"])
                    await asyncio.sleep(0.05)

        await asyncio.gather(*(submitter(c) for c in range(args.clients)), health(), watch())
        await asyncio.sleep(3)
        metrics1 = (await client.get("/metrics")).json()

    summary = {
        "clients": args.clients,
        "seconds": args.seconds,
        "queue_capacity": metrics1.get("queue_capacity"),
        "workers": metrics1.get("workers"),
        "statuses": statuses,
        "responses_429_without_retry_after": no_retry_after,
        "max_queue_length_seen": max(queue_seen) if queue_seen else None,
        "health_samples": len(health_ms),
        "health_p50_ms": pct(health_ms, 0.50),
        "health_p95_ms": pct(health_ms, 0.95),
        "health_max_ms": round(max(health_ms), 2) if health_ms else None,
        "rejected_counter_delta": metrics1["rejected"] - metrics0["rejected"],
        "full_ms_p50_p95_p99": [metrics1["full_ms_p50"], metrics1["full_ms_p95"], metrics1["full_ms_p99"]],
    }
    for k, v in summary.items():
        print(f"{k}: {v}")
    print("збережено:", save("dpc-lr1/queue-full", summary))


if __name__ == "__main__":
    asyncio.run(main())
