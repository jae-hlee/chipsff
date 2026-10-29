"""
Collect the predictions of one run (run_job.py output for one chipsff
version and one force field) into predictions.json.

Usage:
    python collect.py <out_dir> [predictions.json]

<out_dir> is OUT_ROOT/<run_name>/<calculator> as written by submit.sh. The
output defaults to <out_dir>/predictions.json and holds, per material:
a, b, c, vol (relaxed primitive cell), vol_eos (minimum of that job's E-V
fit), kv, c11, c44, form_en (conventional-cell job), surfaces {name: energy},
vacancies [[name, energy], ...] (kept as a
list: chipsff versions before the Wyckoff-letter names give several sites of
one element the same name), and each job's status and run time.
"""
import glob
import json
import os
import sys


def load_json(path):
    with open(path) as f:
        return json.load(f)


def cell_volume(lattice_mat):
    """Volume of the cell spanned by the three rows of lattice_mat."""
    (a1, a2, a3), (b1, b2, b3), (c1, c2, c3) = lattice_mat
    return abs(
        a1 * (b2 * c3 - b3 * c2) - a2 * (b1 * c3 - b3 * c1) + a3 * (b1 * c2 - b2 * c1)
    )


def main():
    out_dir = sys.argv[1]
    dest = sys.argv[2] if len(sys.argv) > 2 else os.path.join(out_dir, "predictions.json")
    predictions = {}
    for kind in ("full", "geom"):
        kind_dir = os.path.join(out_dir, kind)
        if not os.path.isdir(kind_dir):
            continue
        for jid in sorted(os.listdir(kind_dir)):
            work = os.path.join(kind_dir, jid)
            rec = predictions.setdefault(jid, {})
            done_file = os.path.join(work, "done.json")
            done = load_json(done_file) if os.path.exists(done_file) else {}
            rec[f"{kind}_returncode"] = done.get("returncode")
            rec[f"{kind}_seconds"] = done.get("seconds")
            info_files = glob.glob(os.path.join(work, "*", "*_job_info.json"))
            if not info_files:
                continue
            info = load_json(info_files[0])
            if kind == "geom":
                relaxed = info.get("relaxed_atoms") or {}
                abc = relaxed.get("abc") or [None] * 3
                lattice = relaxed.get("lattice_mat")
                rec.update(
                    a=abc[0], b=abc[1], c=abc[2],
                    vol=cell_volume(lattice) if lattice else None,
                    vol_eos=info.get("equilibrium_volume"),
                )
                continue
            elastic = info.get("elastic_tensor") or {}
            rec.update(
                kv=info.get("bulk_modulus"),
                c11=elastic.get("C_11"),
                c44=elastic.get("C_44"),
                form_en=info.get("formation_energy_per_atom"),
                surfaces={
                    s["surface_name"]: s["surf_en"]
                    for s in info.get("all_surfaces") or []
                },
                vacancies=[
                    [v["name"], v["vac_en"]] for v in info.get("all_vacancies") or []
                ],
            )
    with open(dest, "w") as f:
        json.dump(predictions, f, indent=1)
    failed = sorted(
        f"{kind}/{jid}"
        for jid, rec in predictions.items()
        for kind in ("full", "geom")
        if rec.get(f"{kind}_returncode") not in (0, None)
    )
    unfinished = sorted(
        f"{kind}/{jid}"
        for jid, rec in predictions.items()
        for kind in ("full", "geom")
        if f"{kind}_returncode" in rec and rec[f"{kind}_returncode"] is None
    )
    print(f"{len(predictions)} materials -> {dest}")
    if failed:
        print(f"{len(failed)} jobs failed: {' '.join(failed)}")
    if unfinished:
        print(f"{len(unfinished)} jobs have not finished: {' '.join(unfinished)}")


if __name__ == "__main__":
    main()
