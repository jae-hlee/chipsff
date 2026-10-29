#!/bin/bash
# Submit the CHIPS-FF leaderboard jobs for one chipsff checkout and one force
# field as a SLURM job array (one task per material and job kind).
#
# usage: submit.sh <run_name> <chipsff_dir> <calculator> <model_dir>
#   e.g. submit.sh fixed ~/chipsff-fixed alignn_ff_mptrj /data/me/alignn_ff_mptrj
#
# Results go to $OUT_ROOT/<run_name>/<calculator> (OUT_ROOT defaults to
# ./runs). Resubmitting skips the jobs that already finished.
#
# Optional environment variables:
#   PYTHON       python with chipsff's dependencies (default: python3)
#   ALIGNN_DIR   ALIGNN source tree with the element embedding, put on PYTHONPATH
#   SETUP        shell commands run before the check and at the start of each
#                job, e.g. "source ~/miniforge3/etc/profile.d/conda.sh; conda activate chipsff"
#   PARTITION, ACCOUNT, CPUS (4), MEM (16G), TIME (8:00:00)
#   MAX_RUNNING  limit on array tasks running at once
#   ARRAY        task indices to run instead of all, e.g. 12,24,128
set -euo pipefail

if [ $# -ne 4 ]; then
    sed -n '2,18p' "$0"
    exit 1
fi
HERE="$(cd "$(dirname "$0")" && pwd)"
RUN=$1
CHIPSFF_DIR="$(cd "$2" && pwd)"
CALC=$3
MODEL_DIR="$(cd "$4" && pwd)"
PYTHON=${PYTHON:-python3}
CPUS=${CPUS:-4}
OUT_ROOT="$(mkdir -p "${OUT_ROOT:-runs}" && cd "${OUT_ROOT:-runs}" && pwd)"
OUT="$OUT_ROOT/$RUN/$CALC"
JOB_PYTHONPATH="$CHIPSFF_DIR${ALIGNN_DIR:+:$ALIGNN_DIR}"

eval "${SETUP:-true}"
# Confirm the imports and the model, and download the JARVIS datasets once
# here instead of in every job
PYTHONPATH="$JOB_PYTHONPATH${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" "$HERE/run_job.py" check \
    --chipsff_dir "$CHIPSFF_DIR" --calculator "$CALC" --model_path "$MODEL_DIR"
N=$("$PYTHON" "$HERE/run_job.py" count)

mkdir -p "$OUT/logs"
cp "$CHIPSFF_DIR/chipsff/chemical_potentials.json" "$OUT/chemical_potentials.json"
{
    echo "chipsff $CHIPSFF_DIR $(git -C "$CHIPSFF_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "alignn ${ALIGNN_DIR:-installed} $(git -C "${ALIGNN_DIR:-.}" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "model $MODEL_DIR"
} > "$OUT/versions.txt"

sbatch <<EOT
#!/bin/bash
#SBATCH --job-name=cf_${RUN}_${CALC}
#SBATCH --array=${ARRAY:-0-$((N - 1))}${MAX_RUNNING:+%$MAX_RUNNING}
#SBATCH --cpus-per-task=$CPUS
#SBATCH --mem=${MEM:-16G}
#SBATCH --time=${TIME:-8:00:00}
#SBATCH --output=$OUT/logs/%a_%A.out
${PARTITION:+#SBATCH --partition=$PARTITION}
${ACCOUNT:+#SBATCH --account=$ACCOUNT}
${SETUP:-}
export OMP_NUM_THREADS=$CPUS MKL_NUM_THREADS=$CPUS OPENBLAS_NUM_THREADS=$CPUS
export CUDA_VISIBLE_DEVICES=""
export PYTHONPATH="$JOB_PYTHONPATH\${PYTHONPATH:+:\$PYTHONPATH}"
"$PYTHON" "$HERE/run_job.py" run --task \$SLURM_ARRAY_TASK_ID \\
    --chipsff_dir "$CHIPSFF_DIR" --calculator "$CALC" --model_path "$MODEL_DIR" \\
    --chemical_potentials "$OUT/chemical_potentials.json" --out_dir "$OUT"
EOT
echo "submitted tasks ${ARRAY:-0-$((N - 1))} of $N: $RUN / $CALC -> $OUT"
