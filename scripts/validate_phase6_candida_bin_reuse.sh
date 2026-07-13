#!/usr/bin/env bash
set -euo pipefail
trap 'echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: command failed at line ${LINENO}: ${BASH_COMMAND}" >&2' ERR

# Supplemental Phase 6 acceptance: prove hifiasm can reuse compatible .bin files.
# This creates a separate output directory and pre-seeds its baseline bins from a
# completed Phase 6 baseline run. Nextflow is intentionally run without -resume.
#
# Example:
#   nohup setsid bash scripts/validate_phase6_candida_bin_reuse.sh </dev/null \
#     > results/Candida_albicans_phase6_bin_reuse/launcher.log 2>&1 &

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAMPLE_ID="Candida_albicans"
READS="${ROOT_DIR}/Candida_albicans/Candida_albicans_HIFI.fastq"
REFERENCE="${ROOT_DIR}/Candida_albicans/Candida_albicans_gnome.fasta"
SOURCE_OUTDIR="${SOURCE_OUTDIR:-${ROOT_DIR}/results/Candida_albicans_phase6}"
OUTDIR="${OUTDIR:-${ROOT_DIR}/results/Candida_albicans_phase6_bin_reuse}"
THREADS="${THREADS:-480}"
MEMORY_GB="${MEMORY_GB:-960}"
EXPECTED_GENOME_SIZE="${EXPECTED_GENOME_SIZE:-14500000}"
KMER_K="${KMER_K:-21}"
CONDA_ENV="${CONDA_ENV:-hifiAgent}"
CONDA_BIN="${CONDA_BIN:-}"

SOURCE_BINS_DIR="${SOURCE_OUTDIR}/02_assembly/baseline/bins"
METADATA_DIR="${OUTDIR}/00_metadata"
BASELINE_DIR="${OUTDIR}/02_assembly/baseline"
PRESEEDED_BINS_DIR="${BASELINE_DIR}/bins"
LOG_DIR="${OUTDIR}/logs/phase6_bin_reuse_validation"
CONFIG_FILE="${LOG_DIR}/candida_phase6_bin_reuse_config.yaml"
NF_CONFIG_FILE="${LOG_DIR}/phase6_bin_reuse_nextflow_override.config"
READS_MANIFEST="${METADATA_DIR}/hifi_reads.list"
DRIVER_LOG="${LOG_DIR}/phase6_bin_reuse_driver.log"
NF_STDOUT_LOG="${LOG_DIR}/nextflow.stdout.log"
NF_STDERR_LOG="${LOG_DIR}/nextflow.stderr.log"
COMMAND_FILE="${LOG_DIR}/nextflow_command.txt"
ENV_FILE="${LOG_DIR}/phase6_bin_reuse_environment.txt"
CHECKLIST="${LOG_DIR}/phase6_bin_reuse_acceptance_checklist.tsv"
PRESEEDED_MANIFEST="${LOG_DIR}/preseeded_bins.tsv"

mkdir -p "${METADATA_DIR}" "${LOG_DIR}" "${PRESEEDED_BINS_DIR}"
exec >> "${DRIVER_LOG}" 2>&1

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

fail() {
  echo "[$(timestamp)] ERROR: $*" >&2
  exit 1
}

require_file() {
  local path="$1"
  [[ -f "${path}" ]] || fail "Required file not found: ${path}"
}

find_nextflow() {
  if command -v nextflow >/dev/null 2>&1; then
    command -v nextflow
  elif [[ -x /home/gw/software/nextflow ]]; then
    printf '%s\n' /home/gw/software/nextflow
  else
    fail "Nextflow executable not found"
  fi
}

find_conda() {
  if [[ -n "${CONDA_BIN}" && -x "${CONDA_BIN}" ]]; then
    printf '%s\n' "${CONDA_BIN}"
  elif command -v conda >/dev/null 2>&1; then
    command -v conda
  elif [[ -x /home/gw/miniconda3/bin/conda ]]; then
    printf '%s\n' /home/gw/miniconda3/bin/conda
  elif [[ -x /home/gw/miniconda3/condabin/conda ]]; then
    printf '%s\n' /home/gw/miniconda3/condabin/conda
  else
    fail "conda executable not found"
  fi
}

write_acceptance_row() {
  local item="$1"
  local path="$2"
  local status="FAIL"
  if [[ -e "${path}" ]] || compgen -G "${path}" >/dev/null; then
    status="PASS"
  fi
  printf '%s\t%s\t%s\n' "${item}" "${status}" "${path}" >> "${CHECKLIST}"
}

echo "[$(timestamp)] Starting Phase 6 bin reuse validation setup"
echo "Root: ${ROOT_DIR}"
echo "Source output: ${SOURCE_OUTDIR}"
echo "Reuse validation output: ${OUTDIR}"
echo "Threads: ${THREADS}"
echo "Memory: ${MEMORY_GB} GB"

require_file "${READS}"
require_file "${REFERENCE}"
require_file "${SOURCE_BINS_DIR}/${SAMPLE_ID}.baseline.ec.bin"
require_file "${SOURCE_BINS_DIR}/${SAMPLE_ID}.baseline.ovlp.reverse.bin"
require_file "${SOURCE_BINS_DIR}/${SAMPLE_ID}.baseline.ovlp.source.bin"

printf 'source\tpreseeded\tmethod\n' > "${PRESEEDED_MANIFEST}"
for bin_path in "${SOURCE_BINS_DIR}/${SAMPLE_ID}.baseline"*.bin; do
  target="${PRESEEDED_BINS_DIR}/$(basename "${bin_path}")"
  if [[ ! -e "${target}" ]]; then
    if ln "${bin_path}" "${target}" 2>/dev/null; then
      method="hardlink"
    else
      cp "${bin_path}" "${target}"
      method="copy"
    fi
  else
    method="already_present"
  fi
  printf '%s\t%s\t%s\n' "${bin_path}" "${target}" "${method}" >> "${PRESEEDED_MANIFEST}"
done
echo "[$(timestamp)] Preseeded hifiasm bin files: ${PRESEEDED_MANIFEST}"

cat > "${CONFIG_FILE}" <<YAML
sample_id: ${SAMPLE_ID}
hifi_reads:
  - ${READS}
outdir: ${OUTDIR}
species_name: Candida albicans
expected_genome_size: ${EXPECTED_GENOME_SIZE}
ploidy: 2
inbred: null
busco_lineage: saccharomycetes_odb12
kmer_reads: null
reference_genome: ${REFERENCE}
resources:
  max_threads: ${THREADS}
  max_memory_gb: ${MEMORY_GB}
agent:
  max_retry_rounds: 1
  max_candidates_per_round: 2
  objective: balanced
kmer:
  k: ${KMER_K}
YAML
echo "[$(timestamp)] Wrote sample config: ${CONFIG_FILE}"

cat > "${NF_CONFIG_FILE}" <<NFCONFIG
includeConfig '${ROOT_DIR}/workflow/nextflow.config'

profiles {
  phase6_bin_reuse {
    includeConfig '${ROOT_DIR}/workflow/conf/local.config'

    executor {
      name = 'local'
      cpus = ${THREADS}
      memory = '${MEMORY_GB} GB'
    }

    process {
      withLabel: medium {
        cpus = ${THREADS}
        memory = '${MEMORY_GB} GB'
        time = '24 h'
      }

      withLabel: assembly {
        cpus = ${THREADS}
        memory = '${MEMORY_GB} GB'
        time = '14 d'
      }

      withName: HIFIASM_BASELINE {
        cpus = ${THREADS}
        memory = '${MEMORY_GB} GB'
        time = '14 d'
      }
    }
  }
}
NFCONFIG
echo "[$(timestamp)] Wrote Nextflow override config: ${NF_CONFIG_FILE}"

printf '%s\n' "${READS}" > "${READS_MANIFEST}"
echo "[$(timestamp)] Wrote reads manifest: ${READS_MANIFEST}"

echo "[$(timestamp)] Resolving conda executable"
CONDA_RUN_BIN="$(find_conda)"
if [[ -d "/home/gw/miniconda3/envs/${CONDA_ENV}" ]]; then
  CONDA_PREFIX_PATH="/home/gw/miniconda3/envs/${CONDA_ENV}"
else
  CONDA_PREFIX_PATH="$("${CONDA_RUN_BIN}" run -n "${CONDA_ENV}" python -c 'import os; print(os.environ["CONDA_PREFIX"])' | tail -n 1)"
fi
export PATH="${CONDA_PREFIX_PATH}/bin:${PATH}"
echo "[$(timestamp)] Using conda executable: ${CONDA_RUN_BIN}"
echo "[$(timestamp)] Using conda prefix: ${CONDA_PREFIX_PATH}"
NEXTFLOW_BIN="$(find_nextflow)"
echo "[$(timestamp)] Using Nextflow executable: ${NEXTFLOW_BIN}"

printf 'timestamp\t%s\n' "$(timestamp)" > "${ENV_FILE}"
printf 'source_outdir\t%s\n' "${SOURCE_OUTDIR}" >> "${ENV_FILE}"
printf 'outdir\t%s\n' "${OUTDIR}" >> "${ENV_FILE}"
printf 'threads\t%s\n' "${THREADS}" >> "${ENV_FILE}"
printf 'memory_gb\t%s\n' "${MEMORY_GB}" >> "${ENV_FILE}"
printf 'conda_bin\t%s\n' "${CONDA_RUN_BIN}" >> "${ENV_FILE}"
printf 'conda_prefix\t%s\n' "${CONDA_PREFIX_PATH}" >> "${ENV_FILE}"
printf 'nextflow_executable\t%s\n' "${NEXTFLOW_BIN}" >> "${ENV_FILE}"
echo "[$(timestamp)] Wrote environment record: ${ENV_FILE}"

echo "[$(timestamp)] Validating generated sample config"
"${CONDA_RUN_BIN}" run -n "${CONDA_ENV}" hifi-agent validate "${CONFIG_FILE}"

if [[ -x /home/gw/software/jdk21/bin/java ]]; then
  export JAVA_HOME=/home/gw/software/jdk21
  export JAVA_CMD=/home/gw/software/jdk21/bin/java
fi

COMMAND=(
  "${NEXTFLOW_BIN}"
  run "${ROOT_DIR}/workflow/main.nf"
  -c "${NF_CONFIG_FILE}"
  -profile phase6_bin_reuse
  --sample_id "${SAMPLE_ID}"
  --reads_manifest "${READS_MANIFEST}"
  --outdir "${OUTDIR}"
  --expected_genome_size "${EXPECTED_GENOME_SIZE}"
  --kmer_k "${KMER_K}"
  --run_assembly true
  --run_post_qc false
)

printf '%q ' "${COMMAND[@]}" > "${COMMAND_FILE}"
printf '\n' >> "${COMMAND_FILE}"

echo "[$(timestamp)] Launching Nextflow Phase 6 bin reuse validation without -resume"
echo "Command file: ${COMMAND_FILE}"
echo "Nextflow stdout: ${NF_STDOUT_LOG}"
echo "Nextflow stderr: ${NF_STDERR_LOG}"

"${COMMAND[@]}" > "${NF_STDOUT_LOG}" 2> "${NF_STDERR_LOG}"

echo "[$(timestamp)] Nextflow completed; checking Phase 6 bin reuse outputs"
printf 'item\tstatus\tpath_pattern\n' > "${CHECKLIST}"
write_acceptance_row "primary_gfa" "${BASELINE_DIR}/gfa/${SAMPLE_ID}.baseline.bp.p_ctg.gfa"
write_acceptance_row "primary_fasta" "${BASELINE_DIR}/fasta/baseline.primary.fa"
write_acceptance_row "hifiasm_bins" "${BASELINE_DIR}/bins/${SAMPLE_ID}.baseline*.bin"
write_acceptance_row "hifiasm_stderr" "${BASELINE_DIR}/logs/hifiasm.stderr"
write_acceptance_row "assembly_manifest" "${BASELINE_DIR}/metadata/assembly_manifest.json"
write_acceptance_row "reused_bins_record" "${BASELINE_DIR}/metadata/reused_bins.tsv"

if grep -q $'\tFAIL\t' "${CHECKLIST}"; then
  echo "[$(timestamp)] Phase 6 bin reuse output check failed; see ${CHECKLIST}"
  exit 2
fi

reused_count="$(awk 'NR > 1 && $2 == "reused" { count++ } END { print count + 0 }' "${BASELINE_DIR}/metadata/reused_bins.tsv")"
if [[ "${reused_count}" -lt 3 ]]; then
  echo "[$(timestamp)] ERROR: Expected at least 3 reused hifiasm bin files, observed ${reused_count}"
  exit 3
fi

echo "[$(timestamp)] Phase 6 bin reuse acceptance check passed"
echo "Checklist: ${CHECKLIST}"
echo "Reused bin count: ${reused_count}"
