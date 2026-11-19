# Вимоги Web - «Обмін даними у Web-застосунках»

Джерело: методичка 2026 і комплект курсу. Тема C30 «Диспетчерська допомоги».
Статуси: `not_started` → `in_progress` → `done` (лише з фактичною перевіркою в Evidence).
Пункти ЛР3-ЛР6 не виконувалися й тут не перелічені.

## ЛР1

| Lab | ID | Тип | Опис | Файли | Тести | Evidence | Status |
|---|---|---|---|---|---|---|---|
| ЛР1 | О1.1 | О | Модель області | README §6.1, docs/decisions.md | - | діаграма станів, ER, інваріанти, параметри | done |
| ЛР1 | О1.2 | О | Схема бази даних | migrations/001_core.sql, 900_seed.sql | - | міграції з нуля; PK/FK, CHECK, частковий унікальний індекс | done |
| ЛР1 | О1.3 | О | Контракт API | web/openapi.yaml | redocly lint | valid (results/web-lr1/) | done |
| ЛР1 | О1.4 | О | Головна операція | web/server/app/requests_api.py | experiments/web_lr1_scenario.py | 14/14: 201+Location, 400/422/404/409 (results/web-lr1/scenario.json) | done |
| ЛР1 | О1.5 | О | Список із курсором | requests_api.py | experiments/web_lr1_scenario.py | сторінки без пропусків і повторів, пошкоджений курсор - 400 | done |
| ЛР1 | О1.6 | О | Система, `/health`, журнал | compose.yaml, configs/nginx/, middleware.py | - | `/health` на обох екземплярах, JSON-журнал, X-Request-ID | done |
| ЛР1 | О1.7 | О | Клієнт | web/client/ | вручну в браузері | знімки results/web-lr1/*.png | done |
| ЛР1 | Д1.1 | Д | Правило за часом - чиста функція | web/server/app/timerules.py | web/server/tests/test_timerules.py | 5 тестів: межа строку, зона | done |

## ЛР2

| Lab | ID | Тип | Опис | Файли | Тести | Evidence | Status |
|---|---|---|---|---|---|---|---|
| ЛР2 | О2.1 | О | Інваріант за одночасних запитів | migrations/001_core.sql (`assign_team`) | experiments/web_lr2_race.py | 5 раундів 10 заявок на 3 команди через app-a й app-b: 3×201, 7×409 (results/web-lr2/race.json) | done |
| ЛР2 | О2.2 | О | Механізм ідемпотентності | web/server/app/idempotency.py, migrations/003_idempotency.sql | experiments/web_lr2_idempotency.py | 400 / повтор / 422 / 409 / одна заявка на 5 дублікатів; очищення порціями (results/web-lr2/idempotency.json) | done |
| ЛР2 | О2.3 | О | Повтор після втраченої відповіді | fault `after_commit_before_response` | experiments/web_lr2_idempotency.py | повтор через app-b - збережений 201, заявка одна (results/web-lr2/lost-response.json) | done |
| ЛР2 | О2.4 | О | Повторні спроби в клієнті | web/client/api.js | web/client/tests/retry.test.mjs | 502 → 201 з тим самим ключем; «результат невідомий» (results/web-lr2/client-retry.txt) | done |

