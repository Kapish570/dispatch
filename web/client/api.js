// Звернення до системи лише через адресу nginx: базова адреса, X-User-Id (до ЛР3),
// Idempotency-Key, Problem Details.
// Запуск поза Compose:  python -m http.server 8081 --bind 127.0.0.1 --directory client

export const API = localStorage.getItem("api") ?? "http://localhost:8080";

export class Problem extends Error {
    constructor(status, body) {
        super(body?.title ?? `HTTP ${status}`);
        this.status = status;
        this.body = body;
    }
}

// До ЛР3 користувача визначає заголовок X-User-Id (заздалегідь створений користувач).
export const getUser = () => localStorage.getItem("userId") ?? "u-applicant-1";
export const setUser = (id) => localStorage.setItem("userId", id);

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
        throw new Problem(reply.status, typeof data === "object" ? data : {title: data});
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
