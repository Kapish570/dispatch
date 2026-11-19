"""Правила часу області (Д1.1): чисті функції, поточний час передається параметром.

Картка C30: команда підтверджує призначення за 10 хв; заявка рівно на межі строку
переходить іншій команді. Інтервал підтвердження — [created_at, accept_deadline).
"""

from datetime import datetime, timedelta

ACCEPT_WINDOW = timedelta(minutes=10)


def accept_deadline(created_at: datetime) -> datetime:
    """Момент, до якого (не включно) команда має підтвердити призначення."""
    if created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    return created_at + ACCEPT_WINDOW


def is_accept_expired(deadline: datetime, now: datetime) -> bool:
    """True, якщо строк сплив. Рівно на межі (now == deadline) — уже сплив: заявка переходить
    іншій команді. Порівнюються моменти, а не рядки, тому зміщення зони не впливає."""
    if deadline.tzinfo is None or now.tzinfo is None:
        raise ValueError("moments must be timezone-aware")
    return now >= deadline
