"""Спільне для сценаріїв дослідів: адреси, скидання тестового району, збереження результатів.

Залежності: pip install httpx "psycopg[binary]"  (або uv run --with httpx --with psycopg[binary])
Адреси за замовчуванням — опубліковані порти compose.yaml (Web через nginx :8080, DPC :8000).
"""

import json
import os
from pathlib import Path

import psycopg

WEB = os.environ.get("WEB_URL", "http://localhost:8080")
DPC = os.environ.get("DPC_URL", "http://localhost:8000")
DPC_TOKEN = os.environ.get("API_TOKEN", "dev-token")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/app")
RESULTS = Path(__file__).resolve().parent.parent / "results"


def reset_district(district: str, kits: int = 10) -> None:
    """Повертає тестовий район до початкового стану: усі команди вільні, заявок немає."""
    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        conn.execute("DELETE FROM assignment_request WHERE district_id = %s", (district,))
        conn.execute("DELETE FROM help_request WHERE district_id = %s", (district,))
        conn.execute("UPDATE team SET status = 'free', kits_available = %s WHERE district_id = %s", (kits, district))
        conn.execute(
            "UPDATE district_teams SET busy = 0, teams_total = "
            "(SELECT count(*) FROM team WHERE district_id = %s AND status <> 'off') WHERE district_id = %s",
            (district, district),
        )
        conn.commit()


def save(name: str, data: object) -> Path:
    path = RESULTS / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[max(0, min(len(s) - 1, round(q * (len(s) - 1))))], 2)
