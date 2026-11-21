"""Run the algorithm-engineering experiments from the command line.

    python scripts/run_benchmarks.py [--vrp-sizes 50 100 200] [--algorithms fifo clarke_wright_ls …]
                                     [--no-ortools] [--timeout 180]

Every experiment runs in its own process with a timeout. CSV + Markdown tables
are rewritten after EVERY experiment, so partial results survive interruptions.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_scenario  # noqa: E402
from app.services import benchmark  # noqa: E402


def write(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path.with_suffix(".csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, keys)
        w.writeheader()
        w.writerows(rows)
    lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    lines += ["| " + " | ".join(str(r.get(k, "")) for k in keys) + " |" for r in rows]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n")


def main() -> None:
    sc = get_scenario()
    bc = sc.section("benchmark")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--graph-sizes", nargs="*", default=[f"{r}x{c}" for r, c in bc["graph_sizes"]])
    ap.add_argument("--path-queries", type=int, default=bc["path_queries"])
    ap.add_argument("--vrp-sizes", nargs="*", type=int, default=bc["vrp_sizes"])
    ap.add_argument("--vehicles", type=int, default=bc["vrp_vehicles"])
    ap.add_argument("--ga-generations", type=int, default=bc["ga_generations"])
    ap.add_argument("--algorithms", nargs="*", default=bc["vrp_algorithms"], choices=list(benchmark.VRP_LABELS))
    ap.add_argument("--no-ortools", action="store_true")
    ap.add_argument("--timeout", type=float, default=bc["experiment_timeout_s"])
    ap.add_argument("--out", default=str(ROOT.parent / "results"))
    a = ap.parse_args()
    params = {"graph_sizes": [list(map(int, g.split("x"))) for g in a.graph_sizes], "path_queries": a.path_queries,
              "vrp_sizes": a.vrp_sizes, "vrp_vehicles": a.vehicles, "ga_generations": a.ga_generations,
              "vrp_algorithms": a.algorithms, "include_ortools": not a.no_ortools, "timeout_s": a.timeout}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    def save(res):
        write(res["shortest_path"], out / f"shortest_path_{stamp}")
        write(res["vrp"], out / f"vrp_{stamp}")
        print(f"  [{benchmark.STATUS['done']}/{benchmark.STATUS['total']}] {benchmark.STATUS['current']}", flush=True)

    res = benchmark.execute(sc, params, save)
    for f in res["failures"]:
        print(f"  ! {f['experiment']}: {f['status']} ({f['note']})")
    print(f"Results written to {out} (shortest_path_{stamp}.*, vrp_{stamp}.*)")


if __name__ == "__main__":
    main()
