"""
Write plan.json, the list of CHIPS-FF leaderboard materials and the surfaces
and vacancies each one is scored on.

The test sets are the dft_3d_chipsff benchmarks of JARVIS-Leaderboard
(jarvis_leaderboard/benchmarks/AI/SinglePropertyPrediction).

Usage:
    python make_plan.py <benchmark_dir> [plan.json]
"""
import json
import os
import sys
import zipfile


def load_test_set(benchmark_dir, prop):
    name = f"dft_3d_chipsff_{prop}.json"
    with zipfile.ZipFile(os.path.join(benchmark_dir, f"{name}.zip")) as z:
        return json.loads(z.read(name))["test"]


def main():
    benchmark_dir = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "plan.json"
    jids = sorted(load_test_set(benchmark_dir, "a"), key=lambda j: int(j[6:]))

    surfaces = {}
    for name in load_test_set(benchmark_dir, "surf_en"):
        jid, miller = name.split("Surface-")[1].split("_miller_")
        surfaces.setdefault(jid, []).append([int(i) for i in miller.split("_")])

    vacancies = {}
    for name in load_test_set(benchmark_dir, "vac_en"):
        jid, element = name.rsplit("_", 1)
        vacancies.setdefault(jid, []).append(element)

    missing = (set(surfaces) | set(vacancies)) - set(jids)
    if missing:
        raise ValueError(f"Surface/vacancy materials not in the jid list: {missing}")
    plan = {"jids": jids, "surfaces": surfaces, "vacancies": vacancies}
    with open(out, "w") as f:
        json.dump(plan, f, indent=1)
    print(
        f"{len(jids)} materials, {sum(map(len, surfaces.values()))} surfaces "
        f"on {len(surfaces)}, {sum(map(len, vacancies.values()))} vacancies "
        f"on {len(vacancies)} -> {out}"
    )


if __name__ == "__main__":
    main()
