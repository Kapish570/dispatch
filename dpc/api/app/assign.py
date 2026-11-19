"""Черга гарячої лінії (картка C30, частина DPC, ЛР1).

POST /v1/assignment-requests приймає запит у ОБМЕЖЕНУ чергу й одразу відповідає 202
(повна черга — 429 з Retry-After, запит не приймається). Пул із WORKERS обробників бере
запити з черги, виконує повільний виклик «зв'язок із командою» (200–900 мс) ПОЗА критичною
секцією, а потім змінює спільний ресурс — команди району (district_teams + team).

Примітив синхронізації черги — asyncio.Queue(maxsize=QUEUE_CAPACITY): обробник, якому
нема роботи, чекає в `await queue.get()` (асинхронна умовна змінна всередині черги),
не займаючи процесора й не блокуючи цикл подій.

Критична секція (RESOURCE_MODE=locked) — транзакція PostgreSQL із блокуванням рядка
district_teams (SELECT … FOR UPDATE у функції assign_team): перевірка «є вільна команда»
і зміна ресурсу виконуються атомарно. Те саме правило й та сама функція застосовуються
частиною Web, тож канали сайту й гарячої лінії не можуть призначити одну команду двічі.
RESOURCE_MODE=unprotected — дослід О1.4: читання й запис окремими командами без блокування.
"""

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from . import auth, config, db, metrics
from .jsonlog import log
from .problems import Problem

router = APIRouter(prefix="/v1", dependencies=[Depends(auth.require_token)])

FINAL = {"done", "rejected", "failed"}
SLOW_CALL_MS = (200, 900)  # картка: «зв'язок із командою», 200–900 мс
UNPROTECTED_GAP_S = 0.05  # мережевий проміжок між читанням і записом у режимі без захисту
ACCEPT_WINDOW = timedelta(minutes=10)


class AssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    district: str = Field(min_length=1, max_length=64)
    kind: Literal["medicine", "escort", "food", "other"]
    address: str = Field(default="дзвінок на гарячу лінію", min_length=3, max_length=300)


@dataclass
class Timing:
    """Позначки монотонного годинника (О1.5). first_read — перша видача кінцевого стану через GET."""

    arrived: float
    started: float | None = None
    finished: float | None = None
    first_read: float | None = None

    def intervals_ms(self) -> dict[str, float | None]:
        def span(a: float | None, b: float | None) -> float | None:
            return round((b - a) * 1000, 1) if a is not None and b is not None else None

        return {
            "queue_wait": span(self.arrived, self.started),
            "processing": span(self.started, self.finished),
            "delivery_wait": span(self.finished, self.first_read),
            "total": span(self.arrived, self.first_read),
        }

    def ordered(self) -> bool:
        marks = [m for m in (self.arrived, self.started, self.finished, self.first_read) if m is not None]
        return marks == sorted(marks)


@dataclass
class Item:
    request_id: str
    body: AssignmentCreate
    persisted: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())


class State:
    queue: asyncio.Queue[Item]
    workers: list[asyncio.Task] = []
    processing = 0
    rejected_full = 0  # відхилено через повну чергу (429)
    rejected_rule = 0  # відхилено за предметним правилом (немає вільної команди)
    timings: dict[str, Timing] = {}
    completed: deque[float] = deque(maxlen=2000)  # повний час arrived → finished, мс (вибірка для p50/p95/p99)


S = State()


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return round(ordered[k], 1)


def start() -> None:
    """Викликається в lifespan: створює обмежену чергу й рівно WORKERS обробників."""
    S.queue = asyncio.Queue(maxsize=config.QUEUE_CAPACITY)
    S.workers = [asyncio.create_task(worker(i), name=f"worker-{i}") for i in range(config.WORKERS)]
    metrics.gauge("queue_length", lambda: S.queue.qsize())
    metrics.gauge("queue_capacity", lambda: config.QUEUE_CAPACITY)
    metrics.gauge("workers", lambda: len(S.workers))
    metrics.gauge("processing", lambda: S.processing)
    metrics.gauge("rejected", lambda: S.rejected_full)
    metrics.gauge("rejected_by_rule", lambda: S.rejected_rule)
    # Інтервал: від надходження запиту до завершення оброблення (не час HTTP-відповіді!);
    # вибірка — останні 2000 завершених запитів цього процесу.
    metrics.gauge("full_ms_p50", lambda: _pct(list(S.completed), 0.50))
    metrics.gauge("full_ms_p95", lambda: _pct(list(S.completed), 0.95))
    metrics.gauge("full_ms_p99", lambda: _pct(list(S.completed), 0.99))
    log("queue.started", capacity=config.QUEUE_CAPACITY, workers=config.WORKERS, mode=config.RESOURCE_MODE)


async def stop() -> None:
    for task in S.workers:
        task.cancel()
    await asyncio.gather(*S.workers, return_exceptions=True)


@router.post("/assignment-requests", status_code=202)
async def accept(body: AssignmentCreate, response: Response) -> dict[str, Any]:
    arrived = time.monotonic()  # позначка надходження
    item = Item(body.request_id, body)
    try:
        # Перевірка місця й постановка в чергу — одна синхронна дія без await між ними:
        # у циклі подій її не перерве інша співпрограма.
        S.queue.put_nowait(item)
    except asyncio.QueueFull:
        S.rejected_full += 1
        raise Problem(429, "queue-full", "Queue is full", "Черга заповнена, повторіть пізніше",
                      headers={"Retry-After": "1"}) from None

    try:
        async with db.connection() as conn:
            cur = await conn.execute(
                """INSERT INTO assignment_request (id, district_id, kind, address, state, mode)
                   VALUES (%s, %s, %s, %s, 'queued', %s) ON CONFLICT (id) DO NOTHING RETURNING id""",
                (body.request_id, body.district, body.kind, body.address, config.RESOURCE_MODE),
            )
            inserted = await cur.fetchone()
    except Exception as exc:
        item.persisted.set_exception(exc)
        raise
    if inserted is None:
        item.persisted.set_result(False)  # дубль: обробник пропустить елемент
        raise Problem(409, "duplicate-request", "Request already accepted", f"Запит {body.request_id} уже прийнято")
    S.timings[body.request_id] = Timing(arrived=arrived)
    item.persisted.set_result(True)

    response.headers["Location"] = f"/v1/assignment-requests/{body.request_id}"
    return {"id": body.request_id, "state": "queued", "reason": None}


async def worker(index: int) -> None:
    while True:
        item = await S.queue.get()  # порожня черга: обробник чекає тут
        try:
            if not await item.persisted:
                continue
            await process(item)
        except Exception as exc:  # noqa: BLE001 — кожен прийнятий запит має дійти до кінцевого стану
            await finish(item.request_id, "failed", f"processing error: {type(exc).__name__}")
        finally:
            S.queue.task_done()


async def process(item: Item) -> None:
    S.processing += 1
    try:
        timing = S.timings.get(item.request_id)
        if timing:
            timing.started = time.monotonic()
        async with db.connection() as conn:
            await conn.execute("UPDATE assignment_request SET state = 'processing' WHERE id = %s", (item.request_id,))

        # Повільний виклик — ПОЗА критичною секцією; await не блокує інших обробників і приймання.
        await asyncio.sleep(random.uniform(*SLOW_CALL_MS) / 1000)

        if config.RESOURCE_MODE == "unprotected":
            await change_unprotected(item.body)
        else:
            await change_locked(item.body)
    finally:
        S.processing -= 1


async def change_locked(body: AssignmentCreate) -> None:
    """Критична секція: перевірка й зміна ресурсу та запис рішення в ОДНІЙ транзакції."""
    async with db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT now() AS now, assign_team(%s, 0) AS team_id", (body.district,))
            row = await cur.fetchone()
            team_id, now = row["team_id"], row["now"]
            if team_id is None:
                reason = "no free team in the district"
                await conn.execute(
                    "UPDATE assignment_request SET state = 'rejected', reason = %s, finished_at = now() WHERE id = %s",
                    (reason, body.request_id),
                )
            else:
                await conn.execute(
                    """INSERT INTO help_request (id, channel, district_id, address, kind, team_id, status,
                                                 created_at, accept_deadline)
                       VALUES (%s, 'hotline', %s, %s, %s, %s, 'assigned', %s, %s)""",
                    (body.request_id, body.district, body.address, body.kind, team_id, now, now + ACCEPT_WINDOW),
                )
                await conn.execute(
                    """UPDATE assignment_request SET state = 'done', team_id = %s, help_request_id = %s,
                              finished_at = now() WHERE id = %s""",
                    (team_id, body.request_id, body.request_id),
                )
    mark_finished(body.request_id, "done" if team_id else "rejected")
    log("assignment.finished", request=body.request_id, team=team_id, district=body.district)


async def change_unprotected(body: AssignmentCreate) -> None:
    """БЕЗ синхронізації (лише для досліду О1.4 на окремому районі test-unprotected):
    «перевірити» і «записати» — окремі команди, між ними інші обробники встигають прочитати
    той самий стан. Наслідок — одна команда на кількох заявках і втрачені оновлення лічильника."""
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT teams_total, busy FROM district_teams WHERE district_id = %s", (body.district,)
        )
        res = await cur.fetchone()
        cur = await conn.execute(
            "SELECT id FROM team WHERE district_id = %s AND status = 'free' ORDER BY id LIMIT 1", (body.district,)
        )
        team = await cur.fetchone()
        if res is None or team is None or res["busy"] >= res["teams_total"]:
            await conn.execute(
                "UPDATE assignment_request SET state = 'rejected', reason = %s, finished_at = now() WHERE id = %s",
                ("no free team in the district", body.request_id),
            )
            mark_finished(body.request_id, "rejected")
            return

        await asyncio.sleep(UNPROTECTED_GAP_S)  # проміжок між перевіркою й записом

        await conn.execute("UPDATE district_teams SET busy = %s WHERE district_id = %s", (res["busy"] + 1, body.district))
        await conn.execute("UPDATE team SET status = 'busy' WHERE id = %s", (team["id"],))
        await conn.execute(
            "UPDATE assignment_request SET state = 'done', team_id = %s, finished_at = now() WHERE id = %s",
            (team["id"], body.request_id),
        )
    mark_finished(body.request_id, "done")


def mark_finished(request_id: str, state: str) -> None:
    timing = S.timings.get(request_id)
    if timing:
        timing.finished = time.monotonic()
        S.completed.append((timing.finished - timing.arrived) * 1000)
    if state == "rejected":
        S.rejected_rule += 1


async def finish(request_id: str, state: str, reason: str) -> None:
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE assignment_request SET state = %s, reason = %s, finished_at = now() WHERE id = %s",
            (state, reason, request_id),
        )
    mark_finished(request_id, state)


@router.get("/assignment-requests/{request_id}")
async def get_state(request_id: str) -> dict[str, Any]:
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT id, state, reason, team_id, district_id FROM assignment_request WHERE id = %s", (request_id,)
        )
        row = await cur.fetchone()
    if row is None:
        raise Problem(404, "not-found", "Request not found")

    timing = S.timings.get(request_id)
    if timing and row["state"] in FINAL and timing.first_read is None:
        timing.first_read = time.monotonic()  # позначка видачі — лише після читання результату
    return {
        "id": row["id"],
        "state": row["state"],
        "reason": row["reason"],
        "team_id": row["team_id"],
        "district": row["district_id"],
        "timings_ms": timing.intervals_ms() if timing else None,
        "timings_ordered": timing.ordered() if timing else None,
    }


@router.get("/district-teams/{district}")
async def resource_state(district: str) -> dict[str, Any]:
    """Стан ресурсу й перевірка інваріанта «команда виконує одну заявку»."""
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT district_id, teams_total, busy FROM district_teams WHERE district_id = %s", (district,)
        )
        res = await cur.fetchone()
        if res is None:
            raise Problem(404, "not-found", "District not found")
        # Активні призначення: заявки Web і гарячої лінії + призначення режиму без захисту.
        cur = await conn.execute(
            """
            SELECT team_id, count(*) AS n FROM (
                SELECT team_id FROM help_request
                 WHERE district_id = %(d)s AND status IN ('assigned', 'on_way')
                UNION ALL
                SELECT team_id FROM assignment_request
                 WHERE district_id = %(d)s AND state = 'done' AND help_request_id IS NULL
            ) a GROUP BY team_id
            """,
            {"d": district},
        )
        per_team = await cur.fetchall()

    active = sum(r["n"] for r in per_team)
    doubled = [r["team_id"] for r in per_team if r["n"] > 1]
    ok = not doubled and active <= res["teams_total"] and active == res["busy"]
    return {
        "district": res["district_id"],
        "teams_total": res["teams_total"],
        "busy": res["busy"],
        "active_assignments": active,
        "teams_with_several_requests": doubled,
        "invariant_ok": ok,
    }
