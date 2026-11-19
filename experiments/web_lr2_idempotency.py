"""Web ЛР2, О2.2 і О2.3: механізм ідемпотентності та повтор після втраченої відповіді.

    python experiments/web_lr2_idempotency.py
    # О2.3 вимагає FAULTS=on (у compose.yaml увімкнено) і доступ до каталогу прапорців:
    #   у Docker прапорець ставить команда:  docker compose exec app-a touch /faults/after_commit_before_response
    #   локально — змінна FAULT_DIR (той самий каталог, що в сервера)

Кроки: без ключа — 400; повтор із тим самим тілом через інший екземпляр — та сама відповідь;
інше тіло — 422; ключ, який ще обробляє інша транзакція, — 409; 5 одночасних дублікатів — один ефект;
прострочені ключі прибираються порціями; аварія after_commit_before_response і повтор через app-b.
"""

import asyncio
import os
import subprocess
import time
import uuid

import httpx
import psycopg

from common import DATABASE_URL, save

APP_A = os.environ.get("APP_A_URL", "http://localhost:8001")
APP_B = os.environ.get("APP_B_URL", "http://localhost:8002")
FAULT_DIR = os.environ.get("FAULT_DIR")  # локальний запуск; інакше — docker compose exec
U = {"X-User-Id": "u-applicant-1"}
BODY = {"district_id": "center", "address": "вул. Сумська, 10, кв. 5", "kind": "medicine", "kits": 1}


def requests_with_key(key: str) -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute("SELECT response_body->>'id' FROM idempotency_key WHERE key = %s", (key,)).fetchone()
        if not row:
            return 0
        return conn.execute("SELECT count(*) FROM help_request WHERE id = %s", (row[0],)).fetchone()[0]


def arm_fault(name: str) -> None:
    if FAULT_DIR:
        open(os.path.join(FAULT_DIR, name), "w").close()
    else:
        subprocess.run(["docker", "compose", "exec", "-T", "app-a", "touch", f"/faults/{name}"], check=True)


async def main() -> None:
    out: dict = {}
    with httpx.Client(timeout=10) as c:
        r = c.post(f"{APP_A}/v1/requests", json=BODY, headers=U)
        out["no_key"] = r.status_code
        print("без ключа:", r.status_code, r.json()["title"])

        key = f"idem-{uuid.uuid4()}"
        r1 = c.post(f"{APP_A}/v1/requests", json=BODY, headers={**U, "Idempotency-Key": key})
        r2 = c.post(f"{APP_B}/v1/requests", json={**BODY, "priority": 2}, headers={**U, "Idempotency-Key": key})
        out["replay"] = {"first": [r1.status_code, r1.headers["x-instance"], r1.json()["id"]],
                         "repeat": [r2.status_code, r2.headers["x-instance"], r2.json()["id"]],
                         "same_body": r1.json() == r2.json(), "requests_in_db": requests_with_key(key)}
        print("повтор через інший екземпляр:", out["replay"])

        r3 = c.post(f"{APP_B}/v1/requests", json={**BODY, "kits": 3}, headers={**U, "Idempotency-Key": key})
        out["other_body"] = r3.status_code
        print("той самий ключ, інше тіло:", r3.status_code, r3.json()["title"])

    # ключ, який обробляє інша (незафіксована) транзакція -> 409
    busy_key = f"busy-{uuid.uuid4()}"
    holder = psycopg.connect(DATABASE_URL)
    holder.execute("INSERT INTO idempotency_key (user_id, operation, key, fingerprint, state, expires_at) "
                   "VALUES ('u-applicant-1', 'POST /v1/requests', %s, 'x', 'processing', now() + interval '1 hour')",
                   (busy_key,))
    t = time.perf_counter()
    with httpx.Client(timeout=10) as c:
        r4 = c.post(f"{APP_A}/v1/requests", json=BODY, headers={**U, "Idempotency-Key": busy_key})
    holder.rollback()
    holder.close()
    out["in_progress"] = {"status": r4.status_code, "retry_after": r4.headers.get("retry-after"),
                          "waited_s": round(time.perf_counter() - t, 2)}
    print("ключ ще обробляється:", out["in_progress"])

    # 5 одночасних дублікатів з одним ключем -> одна заявка
    dup_key = f"dup-{uuid.uuid4()}"
    async with httpx.AsyncClient(timeout=10) as ac:
        replies = await asyncio.gather(*(ac.post(f"{APP_A if i % 2 else APP_B}/v1/requests", json=BODY,
                                                 headers={**U, "Idempotency-Key": dup_key}) for i in range(5)))
    ids = {r.json().get("id") for r in replies if r.status_code == 201}
    out["concurrent_duplicates"] = {"statuses": [r.status_code for r in replies], "distinct_ids": len(ids),
                                    "requests_in_db": requests_with_key(dup_key)}
    print("5 одночасних дублікатів:", out["concurrent_duplicates"])

    # О2.3: аварія після фіксації, до відповіді; повтор з тим самим ключем через app-b
    lost_key = f"lost-{uuid.uuid4()}"
    arm_fault("after_commit_before_response")
    try:
        with httpx.Client(timeout=10) as c:
            c.post(f"{APP_A}/v1/requests", json=BODY, headers={**U, "Idempotency-Key": lost_key})
        first = "відповідь отримано (прапорець не спрацював)"
    except httpx.TransportError as exc:
        first = f"відповіді немає: {type(exc).__name__}"
    with httpx.Client(timeout=10) as c:
        r5 = c.post(f"{APP_B}/v1/requests", json=BODY, headers={**U, "Idempotency-Key": lost_key})
    out["lost_response"] = {"first_attempt": first, "retry_status": r5.status_code,
                            "retry_instance": r5.headers.get("x-instance"),
                            "replayed": r5.headers.get("idempotent-replayed"),
                            "request_id": r5.json().get("id"), "requests_in_db": requests_with_key(lost_key)}
    print("втрачена відповідь:", out["lost_response"])
    save("web-lr2/lost-response", out["lost_response"])

    # прибирання прострочених ключів порціями (500 за порцію)
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("INSERT INTO idempotency_key (user_id, operation, key, fingerprint, state, status_code, "
                     "response_body, expires_at) SELECT 'u-applicant-2', 'POST /v1/requests', 'expired-' || g, 'x', "
                     "'completed', 201, '{}'::jsonb, now() - interval '1 day' FROM generate_series(1, 1200) g")
    deadline = time.time() + 70
    left = 1200
    while time.time() < deadline:
        with psycopg.connect(DATABASE_URL) as conn:
            left = conn.execute("SELECT count(*) FROM idempotency_key WHERE expires_at < now()").fetchone()[0]
        if left == 0:
            break
        await asyncio.sleep(2)
    out["purge"] = {"inserted_expired": 1200, "left_after_wait": left}
    print("прибирання:", out["purge"])
    print("збережено:", save("web-lr2/idempotency", out))


if __name__ == "__main__":
    asyncio.run(main())
