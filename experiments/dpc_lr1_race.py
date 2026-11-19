"""DPC ЛР1, О1.4: 10 одночасних дзвінків гарячої лінії на 3 вільні команди району.

    # захищений режим (RESOURCE_MODE=locked), район test-race
    python experiments/dpc_lr1_race.py --district test-race
    # режим без синхронізації: перезапустити api з RESOURCE_MODE=unprotected, окремий район
    RESOURCE_MODE=unprotected docker compose up -d dpc-api
    python experiments/dpc_lr1_race.py --district test-unprotected

Очікування: locked — рівно 3 done, 7 rejected, invariant_ok = true;
unprotected — більше ніж 3 done, команди з кількома заявками, invariant_ok = false.
"""

import argparse
import asyncio
import time
import uuid

import httpx

from common import DPC, DPC_TOKEN, reset_district, save

FINAL = {"done", "rejected", "failed"}


async def one(client: httpx.AsyncClient, district: str, run: str, i: int) -> dict:
    rid = f"{run}-{i:02d}"
    reply = await client.post("/v1/assignment-requests", json={"request_id": rid, "district": district, "kind": "escort"})
    while True:
        state = (await client.get(f"/v1/assignment-requests/{rid}")).json()
        if state["state"] in FINAL:
            return {"id": rid, "accept_status": reply.status_code, **state}
        await asyncio.sleep(0.1)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--district", default="test-race")
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args()

    reset_district(args.district)
    run = f"race-{uuid.uuid4().hex[:6]}"
    headers = {"Authorization": f"Bearer {DPC_TOKEN}"}
    async with httpx.AsyncClient(base_url=DPC, headers=headers, timeout=30) as client:
        before = (await client.get(f"/v1/district-teams/{args.district}")).json()
        started = time.perf_counter()
        results = await asyncio.gather(*(one(client, args.district, run, i) for i in range(args.n)))
        wall = time.perf_counter() - started
        after = (await client.get(f"/v1/district-teams/{args.district}")).json()

    states: dict[str, int] = {}
    for r in results:
        states[r["state"]] = states.get(r["state"], 0) + 1
    teams = [r["team_id"] for r in results if r["state"] == "done"]
    summary = {
        "district": args.district,
        "requests": args.n,
        "states": states,
        "teams_assigned": teams,
        "resource_before": before,
        "resource_after": after,
        "wall_s": round(wall, 2),
    }
    print(f"район {args.district}: {args.n} запитів за {wall:.2f} с")
    print("стани:", states)
    print("призначені команди:", teams)
    print("ресурс після:", after)
    path = save(f"dpc-lr1/race-{args.district}", {"summary": summary, "requests": results})
    print("збережено:", path)


if __name__ == "__main__":
    asyncio.run(main())
