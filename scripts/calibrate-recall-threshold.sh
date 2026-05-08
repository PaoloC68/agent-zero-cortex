#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CORTEX_URL="${CORTEX_URL:-http://192.168.1.12:8001}"
OUTPUT_DIR="${REPO_ROOT}/.sisyphus/evidence/calibration"

if [[ -z "${CORTEX_API_KEY:-}" ]]; then
    echo "ERROR: CORTEX_API_KEY not set" >&2
    exit 1
fi

mkdir -p "${OUTPUT_DIR}"

exec python3 "${SCRIPT_DIR}/calibrate_recall_threshold.py" \
    --url "${CORTEX_URL}" \
    --api-key "${CORTEX_API_KEY}" \
    --queries "${SCRIPT_DIR}/golden-queries.json" \
    --output-dir "${OUTPUT_DIR}"
