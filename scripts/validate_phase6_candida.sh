#!/usr/bin/env bash
set -euo pipefail

# Phase 6 acceptance run for the real Candida albicans HiFi dataset.
# Run from anywhere:
#   mkdir -p results/Candida_albicans_phase6
#   nohup bash scripts/validate_phase6_candida.sh > results/Candida_albicans_phase6/nohup.log 2>&1 &

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAMPLE_ID="Candida_albicans"
READS="${ROOT_DIR}/Candida_albicans/Candida_albicans_HIFI.fastq"
REFERENCE="${ROOT_DIR}/Candida_albicans/Candida_albicans_gnome.fasta"
OUTDIR="${OUTDIR:-${ROOT_DIR}/results/Candida_albicans_phase6}"
THREADS="${THREADS:-480}"
MEMORY_GB="${MEMORY_GB:-960}"
EXPECTED_GENOME_SIZE="${EXPECTED_GENOME_SIZE:-14500000}"
KMER_K="${KMER_K:-21}"
CONDA_ENV="${CONDA_ENV:-hifiAgent}"

METADATA_DIR="${OUTDIR}/00_metadata"
LOG_DIR="${OUTDIR}/logs/phase6_validation"
CONFIG_FILE="${LOG_DIR}/candida_phase6_config.yaml"
NF_CONFIG_FILE="${LOG_DIR}/phase6_nextflow_override.config"
READS_MANIFEST="${METADATA_DIR}/hifi_reads.list"
BIN_REUSE_MANIFEST="${METADATA_DIR}/hifiasm_bin_reuse_candidates.tsv"
DRIVER_LOG="${LOG_DIR}/phase6_driver.log"
NF_STDOUT_LOG="${LOG_DIR}/nextflow.stdout.log"
NF_STDERR_LOG="${LOG_DIR}/nextflow.stderr.log"
COMMAND_FILE="${LOG_DIR}/nextflow_command.txt"
ENV_FILE="${LOG_DIR}/phase6_environment.txt"
CHECKLIST="${LOG_DIR}/phase6_acceptance_checklist.tsv"

mkdir -p "${METADATA_DIR}" "${LOG_DIR}"
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

write_acceptance_row() {
  local item="$1"
  local path="$2"
  local status="FAIL"
  if [[ -e "${path}" ]] || compgen -G "${path}" >/dev/null; then
    status="PASS"
  fi
  printf '%s\t%s\t%s\n' "${item}" "${status}" "${path}" >> "${CHECKLIST}"
}

echo "[$(timestamp)] Starting Phase 6 Candida validation setup"
echo "Root: ${ROOT_DIR}"
echo "Output: ${OUTDIR}"
echo "Threads: ${THREADS}"
echo "Memory: ${MEMORY_GB} GB"

require_file "${READS}"
require_file "${REFERENCE}"

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

cat > "${NF_CONFIG_FILE}" <<NFCONFIG
includeConfig '${ROOT_DIR}/workflow/nextflow.config'

profiles {
  phase6_candida {
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

printf '%s\n' "${READS}" > "${READS_MANIFEST}"
printf 'path\tsha256\tbytes\n' > "${BIN_REUSE_MANIFEST}"
if [[ -d "${OUTDIR}/02_assembly/baseline/bins" ]]; then
  for bin_path in "${OUTDIR}/02_assembly/baseline/bins/${SAMPLE_ID}.baseline"*.bin; do
    [[ -f "${bin_path}" ]] || continue
    printf '%s\t%s\t%s\n' \
      "${bin_path}" "$(sha256sum "${bin_path}" | awk '{print $1}')" "$(stat -c %s "${bin_path}")" \
      >> "${BIN_REUSE_MANIFEST}"
  done
fi

CONDA_PREFIX_PATH="$(conda run -n "${CONDA_ENV}" python -c 'import os; print(os.environ["CONDA_PREFIX"])' | tail -n 1)"
export PATH="${CONDA_PREFIX_PATH}/bin:${PATH}"

{
  echo "timestamp=$(timestamp)"
  echo "hostname=$(hostname)"
  echo "pwd=${ROOT_DIR}"
  echo "reads=${READS}"
  echo "reference=${REFERENCE}"
  echo "outdir=${OUTDIR}"
  echo "threads=${THREADS}"
  echo "memory_gb=${MEMORY_GB}"
  echo "conda_env=${CONDA_ENV}"
  echo "conda_prefix=${CONDA_PREFIX_PATH}"
  echo "path=${PATH}"
  echo "nextflow=$($(find_nextflow) -version 2>&1 | head -n 2 | tr '\n' ' ')"
} > "${ENV_FILE}"

echo "[$(timestamp)] Validating generated sample config"
conda run -n "${CONDA_ENV}" hifi-agent validate "${CONFIG_FILE}"

NEXTFLOW_BIN="$(find_nextflow)"
if [[ -x /home/gw/software/jdk21/bin/java ]]; then
  export JAVA_HOME=/home/gw/software/jdk21
  export JAVA_CMD=/home/gw/software/jdk21/bin/java
fi

COMMAND=(
  "${NEXTFLOW_BIN}"
  run "${ROOT_DIR}/workflow/main.nf"
  -c "${NF_CONFIG_FILE}"
  -profile phase6_candida
  -resume
  --sample_id "${SAMPLE_ID}"
  --reads_manifest "${READS_MANIFEST}"
  --validation_receipt "${METADATA_DIR}/validation_receipt.json"
  --bin_reuse_manifest "${BIN_REUSE_MANIFEST}"
  --outdir "${OUTDIR}"
  --expected_genome_size "${EXPECTED_GENOME_SIZE}"
  --kmer_k "${KMER_K}"
  --run_assembly true
  --run_post_qc false
)

printf '%q ' "${COMMAND[@]}" > "${COMMAND_FILE}"
printf '\n' >> "${COMMAND_FILE}"

echo "[$(timestamp)] Launching Nextflow Phase 6 validation"
echo "Command file: ${COMMAND_FILE}"
echo "Nextflow stdout: ${NF_STDOUT_LOG}"
echo "Nextflow stderr: ${NF_STDERR_LOG}"

"${COMMAND[@]}" > "${NF_STDOUT_LOG}" 2> "${NF_STDERR_LOG}"

echo "[$(timestamp)] Nextflow completed; checking Phase 6 acceptance outputs"
BASELINE_DIR="${OUTDIR}/02_assembly/baseline"
printf 'item\tstatus\tpath_pattern\n' > "${CHECKLIST}"
write_acceptance_row "primary_gfa" "${BASELINE_DIR}/gfa/${SAMPLE_ID}.baseline.bp.p_ctg.gfa"
write_acceptance_row "hap1_gfa" "${BASELINE_DIR}/gfa/${SAMPLE_ID}.baseline.bp.hap1.p_ctg.gfa"
write_acceptance_row "hap2_gfa" "${BASELINE_DIR}/gfa/${SAMPLE_ID}.baseline.bp.hap2.p_ctg.gfa"
write_acceptance_row "primary_fasta" "${BASELINE_DIR}/fasta/baseline.primary.fa"
write_acceptance_row "hap1_fasta" "${BASELINE_DIR}/fasta/baseline.hap1.fa"
write_acceptance_row "hap2_fasta" "${BASELINE_DIR}/fasta/baseline.hap2.fa"
write_acceptance_row "hifiasm_bins" "${BASELINE_DIR}/bins/${SAMPLE_ID}.baseline*.bin"
write_acceptance_row "hifiasm_stdout" "${BASELINE_DIR}/logs/hifiasm.stdout"
write_acceptance_row "hifiasm_stderr" "${BASELINE_DIR}/logs/hifiasm.stderr"
write_acceptance_row "hifiasm_time" "${BASELINE_DIR}/logs/hifiasm.time.txt"
write_acceptance_row "assembly_manifest" "${BASELINE_DIR}/metadata/assembly_manifest.json"

if grep -q $'\tFAIL\t' "${CHECKLIST}"; then
  echo "[$(timestamp)] Phase 6 acceptance check failed; see ${CHECKLIST}"
  exit 2
fi

echo "[$(timestamp)] Phase 6 acceptance check passed"
echo "Checklist: ${CHECKLIST}"
