"""POST /v1/compute — паралельне чисельне інтегрування (DPC ЛР2, О2.1, О2.3, О2.4).

Схема розрахунку:
  1. (послідовно) перевірка параметрів, поділ [0, n) на `workers` суміжних діапазонів;
  2. (послідовно) запуск пулу процесів ProcessPoolExecutor і прогрів (кожен процес стартує);
  3. (паралельно) кожен процес обчислює локальну суму своєї частини;
  4. (послідовно) об'єднання локальних сум у порядку номерів частин, порівняння з еталоном.
Кроки 1, 2 і 4 — послідовна частина, її час повертається окремо (pool_start_s, combine_s).

Розрахунок виконується в окремому потоці (asyncio.to_thread), тому цикл подій — /health і
черга гарячої лінії — не блокується. Одночасно виконується один розрахунок (семафор), щоб
вимірювання не заважали одне одному.
"""

import asyncio
import multiprocessing as mp
import os
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import auth, integral
from .jsonlog import log
from .problems import Problem

router = APIRouter(prefix="/v1", dependencies=[Depends(auth.require_token)])

TOLERANCE = 1e-6  # допуск порівняння з еталоном (обґрунтування — README, О2.2)
MAX_PROCESSES = int(os.environ.get("COMPUTE_PROCESSES", "4"))
_one_at_a_time = asyncio.Semaphore(1)
_jobs: dict[str, dict[str, Any]] = {}


class ComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    a: float = 0.0
    b: float = 12.0
    n: int = Field(default=10_000_000, ge=1, le=500_000_000, description="кількість частин поділу")
    workers: Literal[1, 2, 4] = 4  # кількість частин (і процесів, якщо processes не задано)
    processes: int | None = Field(default=None, ge=1, le=4, description="розмір пулу; за замовчуванням = workers")
    method: Literal["midpoint", "trapezoid", "simpson"] = "midpoint"
    order: Literal["sequential", "kahan"] = "sequential"
    mode: Literal["local", "lock", "none"] = "local"
    start_method: Literal["forkserver", "spawn", "fork"] = "forkserver"
    async_: bool = Field(default=False, alias="async")

    @model_validator(mode="after")
    def check(self) -> "ComputeRequest":
        if not self.b > self.a:
            raise ValueError("b must be greater than a")
        if self.mode != "local" and self.n > 5_000_000:
            raise ValueError("modes none/lock update a shared value per term: n <= 5 000 000")
        return self


def physical_cores() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 1


def run(req: ComputeRequest) -> dict[str, Any]:
    """Синхронний розрахунок (виконується в окремому потоці)."""
    t0 = time.perf_counter()
    workers = req.workers
    processes = min(req.processes or workers, MAX_PROCESSES)
    parts = integral.split(req.n, workers)
    shared = mp.get_context(req.start_method).Value("d", 0.0, lock=req.mode == "lock") if req.mode != "local" else None

    ctx = mp.get_context(req.start_method)
    with ProcessPoolExecutor(max_workers=processes, mp_context=ctx,
                             initializer=integral.init_shared, initargs=(shared,)) as pool:
        # прогрів: кожен процес пулу запускається до вимірювання обчислення
        list(pool.map(integral.lam, [0.0] * processes))
        t1 = time.perf_counter()
        futures = [pool.submit(integral.timed_part_sum, req.a, req.b, req.n, lo, hi, req.method, req.order, req.mode)
                   for lo, hi in parts]
        done = [f.result() for f in futures]  # у порядку номерів частин — детермінований підсумок
        local = [d[0] for d in done]
        t2 = time.perf_counter()

    value = sum(local) if req.mode == "local" else shared.value
    ref = integral.reference(req.a, req.b)
    t3 = time.perf_counter()
    error = value - ref
    return {
        "value": value,
        "reference": ref,
        "error": error,
        "abs_error": abs(error),
        "tolerance": TOLERANCE,
        "within_tolerance": abs(error) <= TOLERANCE,
        "workers": workers,
        "processes": processes,
        "parts": [[lo, hi] for lo, hi in parts],
        "method": req.method,
        "order": req.order,
        "mode": req.mode,
        "n": req.n,
        "wall_s": round(t3 - t0, 4),
        "pool_start_s": round(t1 - t0, 4),
        "compute_s": round(t2 - t1, 4),
        "combine_s": round(t3 - t2, 6),
        "cores_available": physical_cores(),
        "parts_profile": [{"cpu_s": round(d[1], 4), "wall_s": round(d[2], 4), "pid": d[3]} for d in done],
        "start_method": req.start_method,
    }


async def execute(job_id: str, req: ComputeRequest) -> None:
    job = _jobs[job_id]
    try:
        async with _one_at_a_time:
            job["state"] = "running"
            job["active_parts"] = req.workers
            job["result"] = await asyncio.to_thread(run, req)
            job["state"] = "done"
            log("compute.done", id=job_id, workers=req.workers, n=req.n, wall_s=job["result"]["wall_s"])
    except Exception as exc:  # noqa: BLE001
        job["state"] = "failed"
        job["error"] = type(exc).__name__
    finally:
        job["active_parts"] = 0


@router.post("/compute")
async def start_compute(req: ComputeRequest, response: Response) -> Any:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"id": job_id, "state": "queued", "active_parts": 0, "result": None, "params": req.model_dump()}
    if req.async_:
        asyncio.create_task(execute(job_id, req))
        return JSONResponse(_jobs[job_id], status_code=202, headers={"Location": f"/v1/compute/{job_id}"})
    await execute(job_id, req)
    job = _jobs[job_id]
    if job["state"] == "failed":
        raise Problem(500, "compute-failed", "Computation failed", job.get("error"))
    response.headers["Location"] = f"/v1/compute/{job_id}"
    return job


@router.get("/compute/{job_id}")
async def get_compute(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if job is None:
        raise Problem(404, "not-found", "Computation not found")
    return job
