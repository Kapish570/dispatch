#!/bin/sh
# Перевірка виконаних пунктів ЛР1–ЛР2 обох курсів однією командою (система запущена docker compose up).
#   sh experiments/run_all.sh
# Залежності: pip install httpx "psycopg[binary]"; Node.js 22 для тесту повторів клієнта.
# Досліди, що потребують інших режимів DPC (RESOURCE_MODE=unprotected, QUEUE_CAPACITY=5), запускайте
# окремо за README, розділ 7.
set -e
cd "$(dirname "$0")"
echo "== Web ЛР1: сценарій головної операції";  python web_lr1_scenario.py
echo "== Web ЛР2: 10 заявок на 3 команди";        python web_lr2_race.py --rounds 3
echo "== Web ЛР2: ідемпотентність і втрачена відповідь"; python web_lr2_idempotency.py
echo "== Web ЛР2: повтори клієнта (потрібен прапорець відмови)"
docker compose exec -T app-a touch /faults/after_commit_before_response
node ../web/client/tests/retry.test.mjs
echo "== DPC ЛР1: 10 дзвінків на 3 команди (locked)"; python dpc_lr1_race.py --district test-race
echo "== DPC ЛР2: точність";                        python dpc_lr2_accuracy.py
echo "== DPC ЛР2: спільна сума";                    python dpc_lr2_shared_sum.py
echo "== DPC ЛР2: прискорення";                     python dpc_lr2_speedup.py
echo "== Web: тести правила часу"; (cd ../web/server && python -m unittest discover -s tests)
