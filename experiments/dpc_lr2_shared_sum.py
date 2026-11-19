"""DPC ЛР2, О2.4: спільна сума без синхронізації, з блокуванням і з локальними сумами.

    python experiments/dpc_lr2_shared_sum.py --n 400000 --repeats 3

mode=none — кожен процес додає кожен доданок до спільної multiprocessing.Value без блокування
(читання й запис — окремі дії, оновлення губляться); lock — під блокуванням; local — локальні суми.
"""

import argparse

import httpx

from common import DPC, DPC_TOKEN, save


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400_000)
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    rows = []
    with httpx.Client(base_url=DPC, headers={"Authorization": f"Bearer {DPC_TOKEN}"}, timeout=600) as c:
        for mode in ("none", "lock", "local"):
            for k in range(args.repeats):
                r = c.post("/v1/compute", json={"n": args.n, "workers": 4, "mode": mode}).json()["result"]
                rows.append({"mode": mode, "run": k + 1, "value": r["value"], "reference": r["reference"],
                             "error": r["error"], "within_tolerance": r["within_tolerance"], "compute_s": r["compute_s"]})
                print(f"{mode:5s} запуск {k + 1}: значення={r['value']:.6f} еталон={r['reference']:.6f} "
                      f"похибка={r['error']: .3e} допуск={'OK' if r['within_tolerance'] else 'НІ'} час={r['compute_s']} с")
    print("збережено:", save("dpc-lr2/shared-sum", {"n": args.n, "workers": 4, "rows": rows}))


if __name__ == "__main__":
    main()
