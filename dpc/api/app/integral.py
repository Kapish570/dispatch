"""Розрахунок ЛР2 (картка C30): кількість заявок за перші T годин після події.

Інтенсивність надходження заявок λ(t) = A·t·e^(−t/τ) (заявок/год), t — години від події
(злива, морози). Інтеграл ∫₀ᵀ λ(t) dt — очікувана кількість заявок; поділена на зміну з урахуванням
середнього часу виконання заявки, дає потрібну кількість команд у зміні.
Первісна F(t) = −A·τ·(t + τ)·e^(−t/τ) — незалежний еталон.

Функції цього модуля виконуються в окремих процесах (ProcessPoolExecutor), тому вони
верхньорівневі й залежать лише від аргументів (і, для режимів спільної суми, від спільної
змінної, переданої ініціалізатором пулу).
"""

import math
import os
import time
from multiprocessing.sharedctypes import Synchronized

A = 40.0  # заявок/год² — масштаб хвилі
TAU = 3.0  # год — час спаду хвилі


def lam(t: float) -> float:
    return A * t * math.exp(-t / TAU)


def primitive(t: float) -> float:
    return -A * TAU * (t + TAU) * math.exp(-t / TAU)


def reference(a: float, b: float) -> float:
    return primitive(b) - primitive(a)


def split(n: int, parts: int) -> list[tuple[int, int]]:
    """Поділ індексів частин [0, n) на `parts` суміжних діапазонів без пропусків і перекриття."""
    return [(n * k // parts, n * (k + 1) // parts) for k in range(parts)]


# ---------- спільна сума (О2.4) ----------
_shared: Synchronized | None = None


def init_shared(value: Synchronized | None) -> None:
    """Ініціалізатор процесу пулу: запам'ятовує спільну змінну (multiprocessing.Value)."""
    global _shared
    _shared = value


def part_sum(a: float, b: float, n: int, lo: int, hi: int, method: str, order: str, mode: str) -> float:
    """Локальна сума по частинах з індексами [lo, hi) при кроці h = (b − a)/n.

    method: midpoint — середні прямокутники; trapezoid — трапеції; simpson — Сімпсон на кожній частині.
    order:  sequential — звичайне додавання; kahan — компенсоване (Кехена).
    mode:   local — повертає локальну суму (батьківський процес об'єднує);
            none  — кожен доданок одразу додається до спільної змінної БЕЗ синхронізації;
            lock  — те саме під блокуванням спільної змінної.
    """
    h = (b - a) / n
    exp = math.exp
    k = -1.0 / TAU
    total = 0.0
    comp = 0.0
    shared = _shared
    for i in range(lo, hi):
        x0 = a + i * h
        if method == "midpoint":
            x = x0 + 0.5 * h
            term = A * x * exp(k * x) * h
        elif method == "trapezoid":
            x1 = x0 + h
            term = 0.5 * h * (A * x0 * exp(k * x0) + A * x1 * exp(k * x1))
        else:  # simpson
            xm = x0 + 0.5 * h
            x1 = x0 + h
            term = h / 6.0 * (A * x0 * exp(k * x0) + 4.0 * A * xm * exp(k * xm) + A * x1 * exp(k * x1))

        if mode == "none":
            shared.value += term  # читання й запис — дві окремі дії: оновлення інших процесів губляться
        elif mode == "lock":
            with shared.get_lock():
                shared.value += term
        elif order == "kahan":
            y = term - comp
            t = total + y
            comp = (t - total) - y
            total = t
        else:
            total += term
    return total


def timed_part_sum(*args: object) -> tuple[float, float, float, int]:
    """part_sum + профіль частини: (сума, процесорний час, настінний час, pid процесу).
    Якщо процесорний час частини помітно менший за настінний — процес чекав на ядро."""
    w0, c0 = time.perf_counter(), time.process_time()
    value = part_sum(*args)  # type: ignore[arg-type]
    return value, time.process_time() - c0, time.perf_counter() - w0, os.getpid()
