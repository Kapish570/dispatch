// О2.4: перевірка повторів клієнта в Node 22 (fetch вбудовано). Запуск із кореня проєкту:
//   node web/client/tests/retry.test.mjs        (система запущена; для сценарію аварії — прапорець відмови)
// 1) відповідь втрачено (аварія after_commit_before_response на одному екземплярі; nginx відповідає 502) —
//    клієнт повторює з тим самим ключем і отримує збережений результат;
// 2) сервер недоступний — після обмеженої кількості спроб «результат невідомий».
globalThis.API_URL = process.env.WEB_URL ?? "http://localhost:8080";
const api = await import("../api.js");
const body = {district_id: "center", address: "вул. Сумська, 10", kind: "food"};

const log = [];
const ok = await api.callWithRetry("POST", "/v1/requests", {body, onAttempt: (a) => log.push(a)});
console.log("сценарій 1:", log.map((a) => `спроба ${a.attempt}: ${a.status}`).join(", "),
            "| ключ однаковий:", new Set(log.map((a) => a.key)).size === 1,
            "| replayed:", ok.headers.get("idempotent-replayed"), "| id:", ok.data.id);

process.env.NODE_NO_WARNINGS = "1";
globalThis.API_URL = "http://localhost:9";  // нікого немає
const down = await import("../api.js?down");
const t = Date.now();
try {
    await down.callWithRetry("POST", "/v1/requests", {body, maxAttempts: 4, baseMs: 200,
        onAttempt: (a) => console.log(`  спроба ${a.attempt}: ${a.status} (+${Date.now() - t} мс)`)});
} catch (e) {
    console.log("сценарій 2:", e.message, `після ${e.attempts} спроб за ${Date.now() - t} мс`);
}
