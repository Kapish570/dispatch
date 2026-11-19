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

