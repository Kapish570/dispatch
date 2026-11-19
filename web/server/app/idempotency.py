"""Ключі ідемпотентності головної операції (Web ЛР2, О2.2).

Вимоги методички:
  * заголовок Idempotency-Key обов'язковий (немає — 400);
  * зберігаються користувач, операція, ключ, відбиток тіла, стан, відповідь і строк —
    в ОДНІЙ транзакції з предметною зміною;
  * повтор із тим самим тілом — та сама відповідь; з іншим тілом — 422; ключ ще обробляється — 409;
  * прострочені ключі прибираються порціями.

Як досягається атомарність. Першим кроком транзакції вставляється рядок ключа
(INSERT … ON CONFLICT DO NOTHING) — окремої перевірки «чи є ключ» перед вставкою немає.
Якщо інша транзакція щойно вставила той самий ключ і ще не зафіксувалася, наш INSERT чекає
на унікальному індексі. Після її фіксації бачимо готовий рядок і повертаємо збережену
відповідь; якщо очікування довше IN_PROGRESS_WAIT — 409 «ключ ще обробляється».
Якщо предметна операція завершується помилкою (404, 409), транзакція відкочується разом
із ключем: ефекту не було, тож повтор виконає операцію знову.
"""

import asyncio
import hashlib
import json
from typing import Any

import psycopg
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from . import db
from .jsonlog import log
from .problems import Problem

TTL = "24 hours"
IN_PROGRESS_WAIT = "1s"
PURGE_BATCH = 500
PURGE_EVERY_S = 60


def fingerprint(body: dict[str, Any]) -> str:
    """Відбиток тіла: канонічний JSON (відсортовані ключі, без пробілів) після перевірки моделі,
    тому перестановка полів чи явне значення за замовчуванням відбитка не змінюють."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def require_key(key: str | None) -> str:
    if not key:
        raise Problem(400, "idempotency-key-required", "Idempotency-Key required",
                      "Для головної операції заголовок Idempotency-Key обов'язковий")
    if not 8 <= len(key) <= 128:
        raise Problem(400, "idempotency-key-invalid", "Invalid Idempotency-Key", "Довжина ключа — 8–128 символів")
    return key


async def begin(conn: AsyncConnection, user_id: str, operation: str, key: str, fp: str) -> dict[str, Any] | None:
    """Викликати ПЕРШИМ усередині транзакції. None — ключ новий, виконуйте операцію;
    інакше — збережена відповідь для повтору."""
    await conn.execute(f"SET LOCAL lock_timeout = '{IN_PROGRESS_WAIT}'")
    try:
        cur = await conn.execute(
            f"""INSERT INTO idempotency_key (user_id, operation, key, fingerprint, state, expires_at)
                VALUES (%s, %s, %s, %s, 'processing', now() + interval '{TTL}')
                ON CONFLICT (user_id, operation, key) DO NOTHING
                RETURNING key""",
            (user_id, operation, key, fp),
        )
        inserted = await cur.fetchone()
    except psycopg.errors.LockNotAvailable:
        raise Problem(409, "idempotency-key-in-progress", "Request with this key is in progress",
                      "Запит із цим ключем ще обробляється, повторіть пізніше", headers={"Retry-After": "1"}) from None
    await conn.execute("SET LOCAL lock_timeout = 0")  # далі — звичайні очікування (statement_timeout)
    if inserted is not None:
        return None

    cur = await conn.execute(
        "SELECT fingerprint, state, status_code, response_body, response_headers FROM idempotency_key "
        "WHERE user_id = %s AND operation = %s AND key = %s",
        (user_id, operation, key),
    )
    saved = await cur.fetchone()
    if saved["fingerprint"] != fp:
        raise Problem(422, "idempotency-key-reused", "Idempotency-Key reused with another body",
                      "Цей ключ уже використано з іншим тілом запиту")
    if saved["state"] != "completed":  # рядок зафіксовано без відповіді — не повинно траплятися
        raise Problem(409, "idempotency-key-in-progress", "Request with this key is in progress",
                      headers={"Retry-After": "1"})
    return saved


async def complete(conn: AsyncConnection, user_id: str, operation: str, key: str,
                   status: int, body: dict[str, Any], headers: dict[str, str]) -> None:
    """Зберегти відповідь у тій самій транзакції, що й предметна зміна."""
    await conn.execute(
        """UPDATE idempotency_key SET state = 'completed', status_code = %s, response_body = %s, response_headers = %s
           WHERE user_id = %s AND operation = %s AND key = %s""",
        (status, Jsonb(body), Jsonb(headers), user_id, operation, key),
    )


async def purge_once() -> int:
    """Одна порція прострочених ключів; SKIP LOCKED — екземпляри не заважають один одному."""
    async with db.connection() as conn:
        cur = await conn.execute(
            """DELETE FROM idempotency_key WHERE ctid IN (
                   SELECT ctid FROM idempotency_key WHERE expires_at < now()
                   LIMIT %s FOR UPDATE SKIP LOCKED)""",
            (PURGE_BATCH,),
        )
        return cur.rowcount


async def purge_loop() -> None:
    while True:
        try:
            total = 0
            while (n := await purge_once()) > 0:
                total += n
                if n < PURGE_BATCH:
                    break
            if total:
                log("idempotency.purged", rows=total)
        except (psycopg.Error, OSError, RuntimeError) as exc:
            log("idempotency.purge_failed", error=type(exc).__name__)
        await asyncio.sleep(PURGE_EVERY_S)
