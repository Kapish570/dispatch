# Вимоги DPC - «Розподілені та паралельні обчислення»

Джерело: методичка 2026 і комплект курсу. Тема C30 «Диспетчерська допомоги».
Статуси: `not_started` → `in_progress` → `done` (лише з фактичною перевіркою в Evidence).
Пункти ЛР3-ЛР6 не виконувалися й тут не перелічені.

## ЛР1

| Lab | ID | Тип | Опис | Файли | Тести | Evidence | Status |
|---|---|---|---|---|---|---|---|
| ЛР1 | О1.1 | О | Приймання запитів | dpc/api/app/assign.py, migrations/002_dpc_queue.sql | experiments/dpc_lr1_race.py | 202 до завершення; стани queued → processing → done / rejected / failed | done |
| ЛР1 | О1.2 | О | Обмежена черга й перевантаження | assign.py (`put_nowait`) | experiments/dpc_lr1_queue_full.py | 429 з Retry-After, черга ≤ 5, p95 `/health` 23,6 мс (results/dpc-lr1/queue-full.json) | done |
| ЛР1 | О1.3 | О | Пул обробників | assign.py (`start`, `worker`) | experiments/dpc_lr1_queue_full.py | рівно `WORKERS` задач; повільний виклик не блокує приймання | done |
| ЛР1 | О1.4 | О | Захист спільного ресурсу | assign.py (`change_locked`, `change_unprotected`) | experiments/dpc_lr1_race.py | locked: 3 done / 7 rejected; unprotected: 4-8 done на 3 команди (results/dpc-lr1/) | done |
| ЛР1 | О1.5 | О | Час виконання й метрики | assign.py (`Timing`), `/metrics` | experiments/dpc_lr1_queue_full.py | `queue_wait / processing / delivery_wait`, `queue_length`, `rejected`, перцентилі | done |

## ЛР2

| Lab | ID | Тип | Опис | Файли | Тести | Evidence | Status |
|---|---|---|---|---|---|---|---|
| ЛР2 | О2.1 | О | Паралельне інтегрування | dpc/api/app/integral.py, compute.py | experiments/dpc_lr2_accuracy.py | n = 10⁷: 327,0318500003, похибка ≤ 2,1·10⁻¹¹ < 10⁻⁶ для 1, 2, 4 процесів | done |
| ЛР2 | О2.2 | О | Дослідження точності | experiments/dpc_lr2_accuracy.py | - | відношення похибок n і 2n: 4,00 (прямокутники, трапеції), 16,0 (Сімпсон) (results/dpc-lr2/accuracy.json) | done |
| ЛР2 | О2.3 | О | Прискорення й причина обмеження | experiments/dpc_lr2_speedup.py | py-spy | 2 vCPU: S2 = 1,83, S4 = 1,85; 99 % часу в `part_sum` (results/dpc-lr2/speedup.json, pyspy-*.txt) | done |
| ЛР2 | О2.4 | О | Спільна сума й локальні результати | integral.py (`mode`) | experiments/dpc_lr2_shared_sum.py | none: 193-279 замість 327,03; lock і local - похибка 1,6·10⁻⁹ (results/dpc-lr2/shared-sum.json) | done |

