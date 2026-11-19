"""DPC ЛР2, О2.2: дослідження точності — похибки для n і 2n.

    python experiments/dpc_lr2_accuracy.py

На малих n похибка методу значно більша за похибку округлення (~1e-13), тому видно порядок
збіжності: для середніх прямокутників і трапецій похибка зменшується ≈ у 4 рази при подвоєнні n
(O(h²)), для Сімпсона — ≈ у 16 разів (O(h⁴)). Функція λ(t) = A·t·e^(−t/τ) не є многочленом,
тож жоден із методів не інтегрує її точно.
"""

import httpx

from common import DPC, DPC_TOKEN, save


def main() -> None:
    rows = []
    with httpx.Client(base_url=DPC, headers={"Authorization": f"Bearer {DPC_TOKEN}"}, timeout=120) as c:
        for method in ("midpoint", "trapezoid", "simpson"):
            prev = None
            for n in (25, 50, 100, 200, 400):
                r = c.post("/v1/compute", json={"n": n, "workers": 1, "method": method, "order": "kahan"}).json()["result"]
                ratio = round(prev / abs(r["error"]), 2) if prev else None
                rows.append({"method": method, "n": n, "error": r["error"], "ratio_prev_over_this": ratio})
                print(f"{method:9s} n={n:4d} похибка={r['error']: .3e} відношення={ratio}")
                prev = abs(r["error"])
    print("збережено:", save("dpc-lr2/accuracy", rows))


if __name__ == "__main__":
    main()
