#!/usr/bin/env bash
set -euo pipefail

# Clean only the supplemental Phase 6 bin-reuse validation outputs.
# This does not remove the completed baseline acceptance output:
#   results/Candida_albicans_phase6
#
# Usage:
#   bash scripts/clean_phase6_bin_reuse.sh
#
# Optional:
#   OUTDIR=/path/to/phase6_bin_reuse bash scripts/clean_phase6_bin_reuse.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTDIR="${OUTDIR:-${ROOT_DIR}/results/Candida_albicans_phase6_bin_reuse}"

echo "Cleaning Phase 6 bin-reuse validation output:"
echo "  ${OUTDIR}"

if [[ "${OUTDIR}" == "/" || -z "${OUTDIR}" ]]; then
  echo "Refusing to clean unsafe OUTDIR: ${OUTDIR}" >&2
  exit 2
fi

case "${OUTDIR}" in
  "${ROOT_DIR}/results/Candida_albicans_phase6_bin_reuse"|\
  "${ROOT_DIR}"/results/Candida_albicans_phase6_bin_reuse_*)
    ;;
  *)
    echo "Refusing to clean unexpected OUTDIR: ${OUTDIR}" >&2
    echo "Expected under: ${ROOT_DIR}/results/Candida_albicans_phase6_bin_reuse" >&2
    exit 2
    ;;
esac

if [[ -d "${OUTDIR}" ]]; then
  find "${OUTDIR}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  echo "Cleaned: ${OUTDIR}"
else
  mkdir -p "${OUTDIR}"
  echo "Created empty output directory: ${OUTDIR}"
fi

echo "Done."
