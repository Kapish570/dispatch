"""Web ЛР2, О2.1: 10 одночасних заявок на 3 вільні команди району через обидва екземпляри.

    python experiments/web_lr2_race.py --rounds 5

Половина запитів іде напряму на app-a, половина — на app-b (а також можна через nginx: --via-nginx).
Перед кожним раундом район saltivka повертається до початкового стану (3 вільні команди).
Очікування: у кожному раунді 3 × 201, 7 × 409; у БД 3 активні заявки на 3 різні команди, busy = 3.
"""

import argparse
import asyncio
import os
import uuid

import httpx
import psycopg

from common import DATABASE_URL, WEB, reset_district, save

APP_A = os.environ.get("APP_A_URL", "http://localhost:8001")
APP_B = os.environ.get("APP_B_URL", "http://localhost:8002")
BODY = {"district_id": "saltivka", "address": "пр. Тракторобудівників, 1", "kind": "escort"}


async def round_(n: int, via_nginx: bool) -> dict:
    reset_district("saltivka")
    users = ["u-applicant-1", "u-applicant-2"]
    async with httpx.AsyncClient(timeout=10) as c:
        barrier = asyncio.Event()

        async def send(i: int) -> tuple[int, str | None]:
            base = WEB if via_nginx else (APP_A if i % 2 == 0 else APP_B)
            await barrier.wait()
            r = await c.post(f"{base}/v1/requests", json=BODY,
                             headers={"X-User-Id": users[i % 2], "Idempotency-Key": f"race-{uuid.uuid4()}"})
            return r.status_code, r.headers.get("x-instance")

        tasks = [asyncio.create_task(send(i)) for i in range(n)]
        await asyncio.sleep(0.05)
        barrier.set()
        replies = await asyncio.gather(*tasks)

    with psycopg.connect(DATABASE_URL) as conn:
        active = conn.execute("SELECT team_id FROM help_request WHERE district_id = 'saltivka' "
                              "AND status IN ('assigned','on_way')").fetchall()
        busy = conn.execute("SELECT busy, teams_total FROM district_teams WHERE district_id = 'saltivka'").fetchone()
    teams = [t[0] for t in active]
    return {
        "201": sum(1 for s, _ in replies if s == 201),
        "409": sum(1 for s, _ in replies if s == 409),
        "other": [s for s, _ in replies if s not in (201, 409)],
        "instances": sorted({i for _, i in replies if i}),
        "active_requests": len(teams),
        "distinct_teams": len(set(teams)),
        "busy": busy[0],
        "teams_total": busy[1],
        "invariant_ok": len(teams) == len(set(teams)) == busy[0] <= busy[1],
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--via-nginx", action="store_true")
    args = ap.parse_args()
    rounds = []
    for k in range(args.rounds):
        r = await round_(args.n, args.via_nginx)
        rounds.append(r)
        print(f"раунд {k + 1}: 201={r['201']} 409={r['409']} інші={r['other']} екземпляри={r['instances']} "
              f"активних={r['active_requests']} різних команд={r['distinct_teams']} busy={r['busy']} "
              f"інваріант={'OK' if r['invariant_ok'] else 'ПОРУШЕНО'}")
    print("збережено:", save("web-lr2/race", {"n": args.n, "rounds": rounds}))


if __name__ == "__main__":
    asyncio.run(main())
