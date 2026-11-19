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

