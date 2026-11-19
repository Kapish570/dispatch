"""Web ЛР1: основний сценарій головної операції, коди помилок і читання всіх сторінок списку.

    python experiments/web_lr1_scenario.py            # через nginx (WEB_URL, типово :8080)

Перевіряє: 201 + Location (О1.4), 400/422/404/409/401 у форматі Problem Details,
X-Request-ID у кожній відповіді (О1.6), список із курсором без пропусків і повторів (О1.5),
чужа заявка — 404.
"""

import uuid

import httpx

from common import WEB, reset_district, save

U1 = {"X-User-Id": "u-applicant-1"}
U2 = {"X-User-Id": "u-applicant-2"}


def row(name: str, r: httpx.Response, expect: int) -> dict:
    body = r.json() if "json" in r.headers.get("content-type", "") else r.text
    ok = r.status_code == expect and "x-request-id" in r.headers
    if r.status_code >= 400:
        ok = ok and r.headers.get("content-type", "").startswith("application/problem+json")
    print(f"{'OK ' if ok else 'BAD'} {name}: {r.status_code} (очікувано {expect}) "
          f"{(body.get('title') if isinstance(body, dict) else '')}")
    return {"case": name, "status": r.status_code, "expected": expect, "ok": ok,
            "instance": r.headers.get("x-instance"), "location": r.headers.get("location"), "body": body}


def main() -> None:
    reset_district("saltivka")
    cases = []
    def add_key(req: httpx.Request) -> None:
        # з ЛР2 головна операція вимагає Idempotency-Key: новий ключ для кожного POST сценарію
        if req.method == "POST" and "idempotency-key" not in req.headers:
            req.headers["Idempotency-Key"] = str(uuid.uuid4())

    with httpx.Client(base_url=WEB, timeout=10, event_hooks={"request": [add_key]}) as c:
        normal = {"district_id": "center", "address": "вул. Сумська, 10, кв. 5", "kind": "medicine",
                  "priority": 1, "kits": 2}
        r = c.post("/v1/requests", json=normal, headers=U1)
        cases.append(row("головна операція (center)", r, 201))
        created = r.json()
        cases.append(row("читання за Location", c.get(r.headers["location"], headers=U1), 200))
        cases.append(row("чужа заявка", c.get(r.headers["location"], headers=U2), 404))
        cases.append(row("пошкоджений JSON", c.post("/v1/requests", content=b"{bad", headers={
            **U1, "Content-Type": "application/json"}), 400))
        cases.append(row("неправильні дані", c.post("/v1/requests", json={**normal, "kind": "pizza"}, headers=U1), 422))
        cases.append(row("невідоме поле", c.post("/v1/requests", json={**normal, "owner": "u-applicant-2"}, headers=U1), 422))
        cases.append(row("немає району", c.post("/v1/requests", json={**normal, "district_id": "no-such-district"},
                                                headers=U1), 404))
        cases.append(row("без X-User-Id", c.post("/v1/requests", json=normal), 401))
        scarce = {"district_id": "saltivka", "address": "пр. Тракторобудівників, 1", "kind": "escort"}
        for i in range(3):
            cases.append(row(f"saltivka #{i + 1}", c.post("/v1/requests", json=scarce, headers=U1), 201))
        cases.append(row("saltivka #4 — команд немає", c.post("/v1/requests", json=scarce, headers=U1), 409))

        # список: усі сторінки по 2 елементи
        seen, cursor, pages = [], None, 0
        while True:
            params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
            page = c.get("/v1/requests", params=params, headers=U1).json()
            seen += [(i["created_at"], i["id"]) for i in page["items"]]
            pages += 1
            cursor = page["next_cursor"]
            if not cursor:
                break
        ordered = seen == sorted(seen, reverse=True)
        cases.append(row("пошкоджений курсор", c.get("/v1/requests", params={"cursor": "%%%"}, headers=U1), 400))
        cases.append(row("limit = 51", c.get("/v1/requests", params={"limit": 51}, headers=U1), 422))

    listing = {"pages": pages, "items": len(seen), "unique": len(set(seen)), "ordered_newest_first": ordered}
    print("список:", listing)
    passed = sum(1 for x in cases if x["ok"])
    print(f"пройдено {passed} з {len(cases)}")
    print("збережено:", save("web-lr1/scenario", {"created": created, "cases": cases, "listing": listing}))


if __name__ == "__main__":
    main()
