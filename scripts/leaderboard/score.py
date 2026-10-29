"""
Mean absolute errors against the dft_3d_chipsff test sets of JARVIS-Leaderboard.

Usage:
    python score.py <benchmark_dir> <vacancydb.json.zip> LABEL=PATH [LABEL=PATH ...]

Each PATH is a predictions.json written by collect.py or a JARVIS-Leaderboard
contribution folder (AI-SinglePropertyPrediction-<prop>-dft_3d_chipsff-test-mae.csv.zip
files). vacancydb is used to find which site a vacancy reference belongs to
when the element has several. Prints one table row per property with the
MAE and the number of test entries predicted.
"""
import csv
import io
import json
import math
import os
import sys
import zipfile

PROPS = ["a", "b", "c", "vol", "kv", "c11", "c44", "form_en", "surf_en", "vac_en"]
UNITS = {
    "a": "Å", "b": "Å", "c": "Å", "vol": "Å³", "kv": "GPa", "c11": "GPa",
    "c44": "GPa", "form_en": "eV/atom", "surf_en": "J/m²", "vac_en": "eV",
}
BULK_PROPS = PROPS[:8]


def is_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def load_refs(benchmark_dir):
    refs = {}
    for prop in PROPS:
        name = f"dft_3d_chipsff_{prop}.json"
        with zipfile.ZipFile(os.path.join(benchmark_dir, f"{name}.zip")) as z:
            refs[prop] = {k: float(v) for k, v in json.loads(z.read(name))["test"].items()}
    return refs


def load_vacancy_sites(vacancydb_zip):
    """Map (jid, element) to [(Wyckoff letter, formation energy), ...]."""
    with zipfile.ZipFile(vacancydb_zip) as z:
        entries = json.loads(z.read(z.namelist()[0]))
    sites = {}
    for e in entries:
        jid, element, letter = e["id"].rsplit("_", 2)
        sites.setdefault((jid, element), []).append((letter, e["ef"]))
    return sites


def from_contribution(folder):
    preds = {}
    for prop in PROPS:
        name = f"AI-SinglePropertyPrediction-{prop}-dft_3d_chipsff-test-mae.csv"
        path = os.path.join(folder, f"{name}.zip")
        if not os.path.exists(path):
            preds[prop] = {}
            continue
        with zipfile.ZipFile(path) as z:
            rows = csv.DictReader(io.StringIO(z.read(name).decode()))
            preds[prop] = {r["id"]: float(r["prediction"]) for r in rows}
    return preds, {}


def from_predictions(path, refs, vacancy_sites):
    with open(path) as f:
        records = json.load(f)
    preds = {prop: {} for prop in PROPS}
    notes = {"vacancy sites guessed": []}
    for jid, rec in records.items():
        for prop in BULK_PROPS:
            if is_number(rec.get(prop)):
                preds[prop][jid] = rec[prop]
        for name, value in (rec.get("surfaces") or {}).items():
            if is_number(value):
                preds["surf_en"][name] = value
    for ref_id, ref_value in refs["vac_en"].items():
        jid, element = ref_id.rsplit("_", 1)
        # "<jid>_<el>" (older chipsff) or "<jid>_<el>_<Wyckoff letter>"
        candidates = [
            (name, value)
            for name, value in (records.get(jid, {}).get("vacancies") or [])
            if is_number(value) and (name == ref_id or name.startswith(ref_id + "_"))
        ]
        if not candidates:
            continue
        if len(candidates) == 1:
            preds["vac_en"][ref_id] = candidates[0][1]
            continue
        # Several sites of this element: use the one whose vacancydb entry
        # is the reference value
        letters = {
            letter
            for letter, ef in vacancy_sites.get((jid, element), [])
            if abs(ef - ref_value) < 1e-6
        }
        exact = [v for n, v in candidates if n != ref_id and n.rsplit("_", 1)[1] in letters]
        if len(exact) == 1:
            preds["vac_en"][ref_id] = exact[0]
        else:
            # Same-name sites: keep the last, as a name -> value mapping would
            preds["vac_en"][ref_id] = candidates[-1][1]
            notes["vacancy sites guessed"].append(ref_id)
    failed = [
        f"{kind}/{jid}"
        for jid, rec in records.items()
        for kind in ("full", "geom")
        if rec.get(f"{kind}_returncode") not in (0, None)
    ]
    if failed:
        notes["failed jobs"] = failed
    return preds, notes


def main():
    benchmark_dir, vacancydb_zip, *runs = sys.argv[1:]
    refs = load_refs(benchmark_dir)
    vacancy_sites = load_vacancy_sites(vacancydb_zip)
    labels, results, all_notes = [], {}, {}
    for run in runs:
        label, path = run.split("=", 1)
        if os.path.isdir(path):
            preds, notes = from_contribution(path)
        else:
            preds, notes = from_predictions(path, refs, vacancy_sites)
        labels.append(label)
        all_notes[label] = {k: v for k, v in notes.items() if v}
        for prop in PROPS:
            errors = [abs(v - refs[prop][k]) for k, v in preds[prop].items() if k in refs[prop]]
            results[label, prop] = (
                sum(errors) / len(errors) if errors else float("nan"),
                len(errors),
                len(refs[prop]),
            )

    width = max(18, *(len(label) + 2 for label in labels))
    print("property (unit)".ljust(18) + "".join(label.rjust(width) for label in labels))
    for prop in PROPS:
        cells = []
        for label in labels:
            mae, n, total = results[label, prop]
            cells.append(f"{mae:.3f} ({n}/{total})".rjust(width))
        print(f"{prop} ({UNITS[prop]})".ljust(18) + "".join(cells))
    for label, notes in all_notes.items():
        for key, items in notes.items():
            print(f"{label}: {key}: {' '.join(items)}")
    with open("scores.json", "w") as f:
        json.dump(
            {label: {prop: dict(zip(("mae", "n", "n_test"), results[label, prop]))
                     for prop in PROPS} for label in labels},
            f, indent=1,
        )


if __name__ == "__main__":
    main()
