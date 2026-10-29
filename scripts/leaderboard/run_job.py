"""
Run the CHIPS-FF leaderboard materials with one force field, one job per
material and kind.

Each material has two jobs:
  geom  primitive cell: relax and E-V curve, for a, b, c and volume (the
        benchmark lattice constants are those of the primitive cell)
  full  conventional cell: relax, E-V curve (bulk modulus), formation energy,
        elastic tensor, and the surfaces and vacancies the benchmark scores
        for that material

Subcommands:
  check  confirm which chipsff and ALIGNN are imported, load the model, and
         download the JARVIS datasets the jobs read (run once before submitting)
  count  print the number of jobs in the plan
  run    run job number --task (a SLURM array index)

chipsff is run from --chipsff_dir, so the same plan can be run with
different chipsff versions. Each job gets its own copy of the chemical
potentials file, so concurrent jobs never write to a shared file.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

RELAX = {"fmax": 0.05, "steps": 200}
# AlignnAtomwiseCalculator's default stress_wt differs between ALIGNN
# versions (0.05 in 2024.10.30, 1.0 later); 1.0 gives the stress that
# matches the models' energy derivative
CALCULATOR_SETTINGS = {"stress_wt": 1.0}
FILTER = "FrechetCellFilter"
BULK_SETTINGS = {
    "filter_type": FILTER,
    "relaxation_settings": dict(RELAX, constant_volume=False),
}
SURFACE_SETTINGS = {
    "layers": 4,
    "vacuum": 18,
    "filter_type": FILTER,
    "relaxation_settings": dict(RELAX, constant_volume=True),
}
DEFECT_SETTINGS = {
    "generate_settings": {
        "on_conventional_cell": True,
        "enforce_c_size": 8,
        "extend": 1,
    },
    "filter_type": FILTER,
    "relaxation_settings": dict(RELAX, constant_volume=True),
}


def load_plan(path):
    with open(path) as f:
        plan = json.load(f)
    # Full jobs first: they take longest
    plan["tasks"] = [(jid, "full") for jid in plan["jids"]] + [
        (jid, "geom") for jid in plan["jids"]
    ]
    return plan


def job_input(plan, jid, kind, calculator, model_path):
    """Return the chipsff input for one job."""
    settings = {
        "jid": jid,
        "calculator_type": calculator,
        "chemical_potentials_file": "chemical_potentials.json",
        "bulk_relaxation_settings": BULK_SETTINGS,
        "calculator_settings": {
            calculator: dict(CALCULATOR_SETTINGS, path=model_path)
        },
    }
    if kind == "geom":
        settings["use_conventional_cell"] = False
        settings["properties_to_calculate"] = [
            "relax_structure",
            "calculate_ev_curve",
        ]
        return settings
    properties = [
        "relax_structure",
        "calculate_ev_curve",
        "calculate_formation_energy",
        "calculate_elastic_tensor",
    ]
    settings["use_conventional_cell"] = True
    if jid in plan["surfaces"]:
        properties.append("analyze_surfaces")
        settings["surface_settings"] = dict(
            SURFACE_SETTINGS, indices_list=plan["surfaces"][jid]
        )
    if jid in plan["vacancies"]:
        properties.append("analyze_defects")
        settings["defect_settings"] = DEFECT_SETTINGS
    settings["properties_to_calculate"] = properties
    return settings


# Runs run_chipsff.py without plotly's fig.show(), which chipsff calls for
# every error scorecard and which blocks until a browser loads the page
# whenever Python finds a browser (or BROWSER is set), and without
# fig.write_image(), which needs kaleido and can hang. The scored results do
# not depend on either.
RUNNER_CODE = """
import runpy, sys
import plotly.basedatatypes
plotly.basedatatypes.BaseFigure.show = lambda self, *args, **kwargs: None
plotly.basedatatypes.BaseFigure.write_image = lambda self, *args, **kwargs: None
sys.argv = [sys.argv[1], "--input_file", "input.json"]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


def child_env(chipsff_dir):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (chipsff_dir, env.get("PYTHONPATH")) if p
    )
    env.setdefault("MPLBACKEND", "Agg")
    return env


CHECK_CODE = """
import json, sys
chipsff_dir, calculator, model_path, chem_file, settings = sys.argv[1:6]
import alignn, chipsff
from alignn.models.alignn_atomwise_pure import ALIGNNAtomWisePureConfig
fields = getattr(ALIGNNAtomWisePureConfig, "model_fields", None) or ALIGNNAtomWisePureConfig.__fields__
print("chipsff:", chipsff.__file__)
print("alignn: ", alignn.__file__)
if not chipsff.__file__.startswith(chipsff_dir):
    sys.exit(f"chipsff is imported from {chipsff.__file__}, not {chipsff_dir}")
if "element_embedding" not in fields:
    sys.exit("This ALIGNN has no element embedding; put a newer ALIGNN on PYTHONPATH")
from ase.build import bulk
from chipsff.calcs import setup_calculator
calc = setup_calculator(calculator, dict(json.loads(settings), path=model_path))
atoms = bulk("Cu", "fcc", a=3.63)
atoms.calc = calc
print(f"{calculator}: Cu fcc energy {atoms.get_potential_energy():.4f} eV/atom")
chem = json.load(open(chem_file))
missing = [el for el, v in chem.items() if f"energy_{calculator}" not in v]
print(f"element energies for {calculator}: {len(chem) - len(missing)}/{len(chem)}")
from jarvis.db.figshare import data
for name in ("dft_3d", "vacancydb", "surfacedb"):
    print(name, len(data(name)), "entries")
"""


def check(args):
    chipsff_dir = os.path.abspath(args.chipsff_dir)
    chem_file = os.path.join(chipsff_dir, "chipsff", "chemical_potentials.json")
    code = subprocess.run(
        [sys.executable, "-c", CHECK_CODE, chipsff_dir, args.calculator,
         os.path.abspath(args.model_path), chem_file, json.dumps(CALCULATOR_SETTINGS)],
        env=child_env(chipsff_dir),
    ).returncode
    sys.exit(code)


def run(args):
    plan = load_plan(args.plan)
    jid, kind = plan["tasks"][args.task]
    chipsff_dir = os.path.abspath(args.chipsff_dir)
    work = os.path.join(os.path.abspath(args.out_dir), kind, jid)
    done_file = os.path.join(work, "done.json")
    if os.path.exists(done_file):
        with open(done_file) as f:
            if json.load(f)["returncode"] == 0:
                print(f"{kind} {jid} already done")
                return
    os.makedirs(work, exist_ok=True)
    shutil.copy(args.chemical_potentials, os.path.join(work, "chemical_potentials.json"))
    settings = job_input(
        plan, jid, kind, args.calculator, os.path.abspath(args.model_path)
    )
    with open(os.path.join(work, "input.json"), "w") as f:
        json.dump(settings, f, indent=1)

    start = time.time()
    with open(os.path.join(work, "run.log"), "w") as log:
        returncode = subprocess.run(
            [sys.executable, "-c", RUNNER_CODE,
             os.path.join(chipsff_dir, "chipsff", "run_chipsff.py")],
            cwd=work, env=child_env(chipsff_dir), stdout=log, stderr=subprocess.STDOUT,
        ).returncode
    with open(done_file, "w") as f:
        json.dump(
            {"jid": jid, "kind": kind, "returncode": returncode,
             "seconds": round(time.time() - start, 1), "chipsff_dir": chipsff_dir,
             "calculator": args.calculator, "model_path": os.path.abspath(args.model_path)},
            f, indent=1,
        )
    print(f"{kind} {jid} finished with code {returncode} in {time.time() - start:.0f} s")
    sys.exit(returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check")
    p.add_argument("--chipsff_dir", required=True)
    p.add_argument("--calculator", required=True)
    p.add_argument("--model_path", required=True)
    p = sub.add_parser("count")
    p.add_argument("--plan", default=os.path.join(HERE, "plan.json"))
    p = sub.add_parser("run")
    p.add_argument("--plan", default=os.path.join(HERE, "plan.json"))
    p.add_argument("--task", type=int, required=True)
    p.add_argument("--chipsff_dir", required=True)
    p.add_argument("--calculator", required=True)
    p.add_argument("--model_path", required=True)
    p.add_argument("--chemical_potentials", required=True)
    p.add_argument("--out_dir", required=True)
    args = parser.parse_args()
    if args.command == "check":
        check(args)
    elif args.command == "count":
        print(len(load_plan(args.plan)["tasks"]))
    else:
        run(args)


if __name__ == "__main__":
    main()
