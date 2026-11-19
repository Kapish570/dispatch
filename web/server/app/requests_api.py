"""Заявки на допомогу (картка C30, частина Web): головна операція й список із курсором.

POST /v1/requests — подати заявку й одразу призначити вільну команду району (О1.4).
GET  /v1/requests — мої заявки від найновіших, курсор за парою (created_at, id) (О1.5).
GET  /v1/requests/{id} — одна заявка; чужа й відсутня дають однаковий 404.

До ЛР3 користувача визначає заголовок X-User-Id (ідентифікатор заздалегідь створеного
користувача). Власника беремо з нього, а не з тіла запиту.
"""

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from . import db, timerules
from .jsonlog import log
from .problems import Problem

router = APIRouter(prefix="/v1")

Kind = Literal["medicine", "escort", "food", "other"]


class RequestCreate(BaseModel):
    """Тіло головної операції. Невідомі поля відхиляються (422)."""

    model_config = ConfigDict(extra="forbid")

    district_id: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=3, max_length=300)
    kind: Kind
    priority: int = Field(default=2, ge=1, le=3)
    kits: int = Field(default=0, ge=0, le=20, description="кількість наборів допомоги")


async def current_user(x_user_id: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    """Хто виконує запит (до ЛР3 — заголовок X-User-Id)."""
    if not x_user_id:
        raise Problem(401, "unauthorized", "User required", "Заголовок X-User-Id обов'язковий")
    async with db.connection() as conn:
        cur = await conn.execute("SELECT id, name, role FROM app_user WHERE id = %s", (x_user_id,))
        user = await cur.fetchone()
    if user is None:
        raise Problem(401, "unauthorized", "Unknown user", "Користувача з таким X-User-Id немає")
    return user


User = Annotated[dict[str, Any], Depends(current_user)]


def to_json(row: dict[str, Any]) -> dict[str, Any]:
    """Подання заявки в API: ідентифікатори — рядки, моменти — ISO 8601 зі зміщенням."""
    return {
        "id": row["id"],
        "district_id": row["district_id"],
        "address": row["address"],
        "kind": row["kind"],
        "priority": row["priority"],
        "kits": row["kits"],
        "team_id": row["team_id"],
        "status": row["status"],
        "channel": row["channel"],
        "version": row["version"],
        "created_at": row["created_at"].isoformat(),
        "accept_deadline": row["accept_deadline"].isoformat() if row["accept_deadline"] else None,
    }


def etag(row: dict[str, Any]) -> str:
    return f'"v{row["version"]}"'


@router.get("/me")
async def me(user: User) -> dict[str, Any]:
    return user


@router.post("/requests", status_code=201)
async def create_request(body: RequestCreate, user: User, response: Response) -> dict[str, Any]:
    """Головна операція. Перевірка й зміна ресурсу (команда, лічильник району) та запис заявки —
    одна транзакція; відповідь 201 надсилається лише після фіксації."""
    request_id = str(uuid.uuid4())

    async with db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT now() AS now FROM district WHERE id = %s", (body.district_id,))
            found = await cur.fetchone()
            if found is None:
                raise Problem(404, "district-not-found", "District not found", f"Району {body.district_id} немає")

            cur = await conn.execute("SELECT assign_team(%s, %s) AS team_id", (body.district_id, body.kits))
            team_id = (await cur.fetchone())["team_id"]
            if team_id is None:
                # Problem усередині блока transaction() — відкат усієї транзакції
                raise Problem(409, "no-free-team", "No free team", "У районі немає вільної команди з потрібними наборами")

            created_at: datetime = found["now"]  # now() — час початку транзакції
            cur = await conn.execute(
                """
                INSERT INTO help_request (id, user_id, channel, district_id, address, kind, priority, kits,
                                          team_id, status, created_at, accept_deadline)
                VALUES (%s, %s, 'web', %s, %s, %s, %s, %s, %s, 'assigned', %s, %s)
                RETURNING *
                """,
                (
                    request_id, user["id"], body.district_id, body.address, body.kind, body.priority, body.kits,
                    team_id, created_at, timerules.accept_deadline(created_at),
                ),
            )
            row = await cur.fetchone()
        # тут транзакцію вже зафіксовано

    log("request.assigned", request=request_id, team=team_id, district=body.district_id)
    response.headers["Location"] = f"/v1/requests/{request_id}"
    response.headers["ETag"] = etag(row)
    return to_json(row)


def encode_cursor(row: dict[str, Any]) -> str:
    raw = json.dumps({"t": row["created_at"].isoformat(), "id": row["id"]}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(data["t"]), str(data["id"])
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise Problem(400, "bad-cursor", "Malformed cursor", "Курсор пошкоджено") from exc


@router.get("/requests")
async def list_requests(
    user: User,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Лише власні заявки, від найновіших; порядок за парою (created_at, id)."""
    params: list[Any] = [user["id"]]
    where = "user_id = %s"
    if cursor:
        moment, last_id = decode_cursor(cursor)
        where += " AND (created_at, id) < (%s, %s)"
        params += [moment, last_id]

    async with db.connection() as conn:
        cur = await conn.execute(
            f"SELECT * FROM help_request WHERE {where} ORDER BY created_at DESC, id DESC LIMIT %s",
            (*params, limit + 1),
        )
        rows = await cur.fetchall()

    page = rows[:limit]
    next_cursor = encode_cursor(page[-1]) if len(rows) > limit else None
    return {"items": [to_json(r) for r in page], "next_cursor": next_cursor}


@router.get("/requests/{request_id}")
async def get_request(request_id: str, user: User, response: Response) -> dict[str, Any]:
    """Власник перевіряється в самому запиті до бази: чужа й відсутня заявка — однаковий 404."""
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT * FROM help_request WHERE id = %s AND user_id = %s", (request_id, user["id"])
        )
        row = await cur.fetchone()
    if row is None:
        raise Problem(404, "not-found", "Request not found")
    response.headers["ETag"] = etag(row)
    return to_json(row)
