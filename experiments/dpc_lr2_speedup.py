"""DPC ЛР2, О2.1 + О2.3: перевірка еталона для 1, 2, 4 процесів і прискорення.

    python experiments/dpc_lr2_speedup.py --n 10000000 --repeats 3
    # профілювання (окремо, не під час вимірювань):
    #   docker compose exec dpc-api py-spy top --pid 1 --subprocesses

Для кожного p — щонайменше 3 вимірювання; медіана, розкид (min–max), Sp = T1/Tp, Ep = Sp/p.
T — compute_s (лише паралельна частина) і wall_s (увесь розрахунок разом із запуском пулу).
Крок гіпотези: ті самі 4 частини на пулі з 2 процесів (змінюється один параметр — processes).
"""

import argparse
import statistics

import httpx

from common import DPC, DPC_TOKEN, save


def measure(c: httpx.Client, n: int, workers: int, processes: int | None, repeats: int) -> dict:
    runs = []
    for _ in range(repeats):
        body = {"n": n, "workers": workers, "method": "midpoint"}
        if processes:
            body["processes"] = processes
        r = c.post("/v1/compute", json=body).json()["result"]
        runs.append(r)
    comp = [r["compute_s"] for r in runs]
    wall = [r["wall_s"] for r in runs]
    return {
        "workers": workers,
        "processes": runs[0]["processes"],
        "compute_s": comp,
        "wall_s": wall,
        "median_compute_s": round(statistics.median(comp), 4),
        "median_wall_s": round(statistics.median(wall), 4),
        "spread_compute_s": round(max(comp) - min(comp), 4),
        "pool_start_s_median": round(statistics.median(r["pool_start_s"] for r in runs), 4),
        "max_abs_error": max(r["abs_error"] for r in runs),
        "all_within_tolerance": all(r["within_tolerance"] for r in runs),
        "value": runs[-1]["value"],
        "reference": runs[-1]["reference"],
        "parts_profile_last": runs[-1]["parts_profile"],
        "cores_available": runs[-1]["cores_available"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10_000_000)
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    with httpx.Client(base_url=DPC, headers={"Authorization": f"Bearer {DPC_TOKEN}"}, timeout=600) as c:
        rows = [measure(c, args.n, p, None, args.repeats) for p in (1, 2, 4)]
        hypothesis = measure(c, args.n, 4, 2, args.repeats)

    t1c, t1w = rows[0]["median_compute_s"], rows[0]["median_wall_s"]
    for r in rows + [hypothesis]:
        p = r["processes"]
        r["S_compute"] = round(t1c / r["median_compute_s"], 3)
        r["E_compute"] = round(r["S_compute"] / p, 3)
        r["S_wall"] = round(t1w / r["median_wall_s"], 3)
        r["E_wall"] = round(r["S_wall"] / p, 3)
        cpu_share = [round(x["cpu_s"] / x["wall_s"], 2) for x in r["parts_profile_last"]]
        r["cpu_share_of_parts"] = cpu_share
        print(f"частин={r['workers']} процесів={p}: compute медіана {r['median_compute_s']} с "
              f"(розкид {r['spread_compute_s']}), wall {r['median_wall_s']} с, запуск пулу {r['pool_start_s_median']} с, "
              f"S={r['S_compute']}, E={r['E_compute']}, частка ЦП частин={cpu_share}, "
              f"|похибка|≤{r['max_abs_error']:.2e}, допуск OK={r['all_within_tolerance']}")
    print("збережено:", save("dpc-lr2/speedup", {"n": args.n, "repeats": args.repeats, "rows": rows,
                                                 "hypothesis_4parts_2processes": hypothesis}))


if __name__ == "__main__":
    main()
