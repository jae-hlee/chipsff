# CHIPS-FF leaderboard runs on SLURM

Scripts to run the 104 materials of the JARVIS-Leaderboard CHIPS-FF
benchmarks (`dft_3d_chipsff_*`) with one force field and one chipsff
version, and to score the results.

Each material has two jobs:

- `geom`: primitive cell, relax and E–V curve, for a, b, c and volume (the
  benchmark's lattice constants are those of the primitive cell)
- `full`: conventional cell, relax, E–V curve (bulk modulus), formation
  energy, elastic tensor, and the surfaces (85 on 46 materials) and vacancies
  (48 on 32 materials) the benchmark scores

All relaxations use FIRE with `FrechetCellFilter`, fmax 0.05 eV/Å and at
most 200 steps; slabs have 4 layers and 18 Å of vacuum; defect cells use
`enforce_c_size` 8 on the conventional cell. The settings are in
`run_job.py`.

## Files

- `plan.json`: the materials, and the surfaces and vacancies scored for each
  (written by `make_plan.py` from the benchmark files)
- `submit.sh`: submits one SLURM array (208 tasks) for one chipsff checkout and
  one model
- `run_job.py`: runs one task; `check` confirms the imports and the model
  first
- `collect.py`: gathers one run's results into `predictions.json`
- `score.py`: MAE against the benchmark test sets

## Running

1. Check out each chipsff version to compare, e.g. one on branch
   `alignn-ff-models` and one on `fix/benchmark-correctness`.
2. Use a Python environment with chipsff's dependencies and an ALIGNN that
   has the element embedding, either installed or as a source tree given in
   `ALIGNN_DIR`. `environment.yml` is not enough: its jarvis-tools
   (2024.10.30) lacks `jarvis.core.utils.get_cache_dir`, which the newer
   ALIGNN imports, and its conda builds are x86-64 only. These versions were
   tested together:

   ```bash
   conda create -y -n chipsff python=3.10
   conda activate chipsff
   pip install torch==2.2.1 numpy==1.26.4 jarvis-tools==2026.6.12 ase==3.26.0 \
       scipy==1.15.3 phonopy==4.8.1 elastic==5.2.5.3 plotly==6.9.0 \
       h5py==3.16.0 scikit-learn==1.7.2 pandas==2.3.2 pyyaml \
       pydantic==2.11.9 pydantic-settings==2.10.1 matplotlib==3.10.6 \
       spglib==2.6.0 lmdb==1.7.3 mpmath tqdm requests
   ```
3. Submit one array per chipsff checkout and model, for example:

   ```bash
   export PYTHON=~/miniforge3/envs/chipsff/bin/python
   export ALIGNN_DIR=/data/me/alignn_ff_models/code   # if not installed
   export PARTITION=main OUT_ROOT=/data/me/chipsff_runs
   for model in alignn_ff_mptrj alignn_ff_matpes_pbe alignn_ff_matpes_r2scan; do
       ./submit.sh original ~/chipsff-original $model /data/me/alignn_ff_models/$model
       ./submit.sh fixed ~/chipsff-fixed $model /data/me/alignn_ff_models/$model
   done
   ```

   `ARRAY=12,24,128 ./submit.sh ...` runs only those tasks, for a test.
   `submit.sh` first runs `run_job.py check` on the login node. The check
   shows which chipsff and ALIGNN are imported, loads the model, and downloads
   the JARVIS datasets once, so the jobs don't download them concurrently. It
   also writes `versions.txt` with the chipsff and ALIGNN commits. Jobs run on
   CPU. Resubmitting skips the tasks that finished.

4. Collect each run and score:

   ```bash
   python collect.py $OUT_ROOT/fixed/alignn_ff_mptrj
   python score.py <jarvis_leaderboard>/benchmarks/AI/SinglePropertyPrediction \
       <vacancydb.json.zip> fixed=$OUT_ROOT/fixed/alignn_ff_mptrj/predictions.json
   ```

   `score.py` also reads a leaderboard contribution folder in place of a
   `predictions.json`, to compare with existing entries.

## Notes

- Measured run times on one Apple M3 core with `alignn_ff_mptrj`: Si 22 s
  for `geom` and 1–1.5 min for `full`, ZrO2 18–20 min for `full` (two
  vacancy sites, among the larger cells). Expect roughly 10 core-hours for
  the 208 tasks of one run; the 8-hour default time limit is generous.
- Each job copies `chemical_potentials.json`, so concurrent jobs never write
  to one file. The file holds element energies for `alignn_ff_mptrj`,
  `alignn_ff_matpes_pbe` and `alignn_ff_matpes_r2scan`; other force fields
  compute theirs in each job.
- `run_job.py` runs chipsff with plotly's `show()` and `write_image()`
  turned off. chipsff shows each error scorecard with `show()`, which waits
  for a browser to load the page whenever Python finds one or `BROWSER` is
  set (as in earlier CHIPS-FF SLURM scripts), and kaleido can hang.
- Jobs pass `stress_wt` 1.0 to `AlignnAtomwiseCalculator`, since its default
  differs between ALIGNN versions.
- Vacancy names differ between chipsff versions (`JVASP-1029_Ti` or
  `JVASP-1029_Ti_a`). `score.py` matches both, and uses vacancydb to pick
  the reference site when an element has several.
