// Звернення до системи лише через адресу nginx: базова адреса, X-User-Id (до ЛР3),
// Idempotency-Key, Problem Details.
// Запуск поза Compose:  python -m http.server 8081 --bind 127.0.0.1 --directory client

const store = globalThis.localStorage ?? {getItem: () => null, setItem: () => {}};  // і для Node (тести)
export const API = store.getItem("api") ?? globalThis.API_URL ?? "http://localhost:8080";

export class Problem extends Error {
    constructor(status, body) {
        super(body?.title ?? `HTTP ${status}`);
        this.status = status;
        this.body = body;
    }
}

// До ЛР3 користувача визначає заголовок X-User-Id (заздалегідь створений користувач).
export const getUser = () => store.getItem("userId") ?? "u-applicant-1";
export const setUser = (id) => store.setItem("userId", id);

export async function call(method, path, {body, idempotencyKey, headers = {}} = {}) {
    const reply = await fetch(API + path, {
        method,
        headers: {
            ...(body !== undefined ? {"Content-Type": "application/json"} : {}),
            "X-User-Id": getUser(),
            ...(idempotencyKey ? {"Idempotency-Key": idempotencyKey} : {}),
            ...headers,
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    const type = reply.headers.get("content-type") ?? "";
    const data = type.includes("json") ? await reply.json() : await reply.text();
    if (!reply.ok) {
        const problem = new Problem(reply.status, typeof data === "object" ? data : {title: data});
        problem.retryAfter = Number(reply.headers.get("retry-after")) || 0;
        throw problem;
    }

    return {status: reply.status, headers: reply.headers, data};
}

export const newKey = () => crypto.randomUUID();

// Читає всі сторінки списку за next_cursor (О1.5, О1.7).
export async function listAll(path, limit = 20) {
    const items = [];
    let cursor = null;
    let pages = 0;
    do {
        const query = new URLSearchParams({limit: String(limit)});
        if (cursor) query.set("cursor", cursor);
        const {data} = await call("GET", `${path}?${query}`);
        items.push(...data.items);
        cursor = data.next_cursor ?? null;
        pages += 1;
    } while (cursor);
    return {items, pages};
}

// ---------- ЛР2, О2.4: повторні спроби ----------
// Результат невідомий: відповіді так і не отримано (обрив з'єднання, 5xx), тож запит міг бути
// виконаний. Повтор із тим самим ключем безпечний — сервер поверне збережений результат.
export class UnknownResult extends Error {
    constructor(attempts, last) {
        super("Результат невідомий");
        this.attempts = attempts;
        this.last = last;
    }
}

const RETRYABLE = new Set([429, 502, 503, 504]);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Змінювальний запит із повторами: ОДИН ключ ідемпотентності на всі спроби; пауза — експоненційна
// з випадковим розсіюванням (full jitter), не менша за Retry-After; обмежені кількість спроб і загальний час.
export async function callWithRetry(method, path, {body, key = newKey(), maxAttempts = 5, maxTotalMs = 15_000,
                                                   baseMs = 250, capMs = 4_000, onAttempt} = {}) {
    const started = Date.now();
    let last = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        let retryAfterMs = 0;
        try {
            const reply = await call(method, path, {body, idempotencyKey: key});
            onAttempt?.({attempt, status: reply.status, key});
            return {...reply, attempts: attempt, key};
        } catch (error) {
            const inProgress = error instanceof Problem && error.status === 409 &&
                String(error.body?.type ?? "").endsWith("idempotency-key-in-progress");
            const retryable = !(error instanceof Problem) || RETRYABLE.has(error.status) || inProgress;
            onAttempt?.({attempt, status: error instanceof Problem ? error.status : "мережа", key});
            if (!retryable) throw error;          // 4xx за змістом (404, 409 «немає команди», 422) — не повторюємо
            last = error;
            if (error.retryAfter) retryAfterMs = error.retryAfter * 1000;
        }
        const backoff = Math.random() * Math.min(capMs, baseMs * 2 ** (attempt - 1));
        const pause = Math.max(backoff, retryAfterMs);
        if (attempt === maxAttempts || Date.now() - started + pause > maxTotalMs) break;
        await sleep(pause);
    }
    throw new UnknownResult(maxAttempts, last);
}
