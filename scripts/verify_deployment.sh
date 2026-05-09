#!/usr/bin/env bash
# verify_deployment.sh — confirms the cortex plugin is correctly deployed in LXC 500.
#
# Checks:
#   A  Extension files exist at the correct path inside the container
#   B  Extension files contain our code (get_plugin_config), not the old env-var version
#   C  cortex_plugin package is importable from the AZ venv inside the container
#   D  (documented) How to verify WARNING-level logs appear after a session
#   E  Integration tests pass against a live Cortex API
#
# Usage:
#   bash scripts/verify_deployment.sh
#   CORTEX_URL=http://192.168.1.12:8001 CORTEX_API_KEY=<key> bash scripts/verify_deployment.sh
#
# Exit code: 0 if all checks pass, 1 if any fail.

set -euo pipefail

PROXMOX_HOST="${PROXMOX_HOST:-root@192.168.1.5}"
LXC_ID="${LXC_ID:-500}"
CORTEX_URL="${CORTEX_URL:-http://192.168.1.12:8001}"
CORTEX_API_KEY="${CORTEX_API_KEY:-}"

PASS=0
FAIL=0

_pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

_pct() {
    ssh "$PROXMOX_HOST" "pct exec $LXC_ID -- bash -c '$*' 2>&1"
}

# ---------------------------------------------------------------------------
echo ""
echo "=== Check A: Extension files at correct path ==="
EXT_FILES=(
    "/opt/agent-zero/data/extensions/python/monologue_start/_60_cortex_init.py"
    "/opt/agent-zero/data/extensions/python/monologue_end/_60_cortex_memorize.py"
    "/opt/agent-zero/data/extensions/python/message_loop_prompts_after/_60_cortex_recall.py"
)

all_present=true
for f in "${EXT_FILES[@]}"; do
    result=$(_pct "test -f '$f' && echo EXISTS || echo MISSING")
    if [[ "$result" == *"EXISTS"* ]]; then
        _pass "$f"
    else
        _fail "$f — not found (wrong path or not deployed)"
        all_present=false
    fi
done

# ---------------------------------------------------------------------------
echo ""
echo "=== Check B: Extension files contain our code (get_plugin_config) ==="
for f in "${EXT_FILES[@]}"; do
    result=$(_pct "grep -l get_plugin_config '$f' 2>/dev/null || echo MISSING")
    if [[ "$result" == *"$f"* ]]; then
        _pass "$f uses get_plugin_config"
    else
        _fail "$f — still has old env-var code (re-run cp + deploy steps)"
    fi
done

# ---------------------------------------------------------------------------
echo ""
echo "=== Check C: cortex_plugin importable in AZ venv ==="
result=$(_pct "docker exec agent-zero /opt/venv-a0/bin/python -c 'import cortex_plugin, dirtyjson; print(cortex_plugin.__file__)' 2>&1")
if echo "$result" | grep -q "cortex_plugin"; then
    _pass "cortex_plugin importable: $result"
else
    _fail "cortex_plugin not importable — run: docker exec agent-zero pip install -e /opt/agent-zero/data/usr/plugins/agent-zero-cortex"
    echo "         Output: $result"
fi

# ---------------------------------------------------------------------------
echo ""
echo "=== Check D: Log-level verification (manual) ==="
echo "  INFO  Run this command after triggering an AZ session to verify WARNING logs appear:"
echo "        ssh $PROXMOX_HOST \"pct exec $LXC_ID -- docker logs agent-zero --tail 50 2>&1\" | grep -E 'cortex\\.(init|memorize|recall)'"
echo "  Expected lines:"
echo "        cortex.init: session=<uuid> project=<slug>"
echo "        cortex.memorize: written=N failed=0 timed_out=False ms=NNN"
echo "        cortex.recall: results=N after_fence=N project=<slug> ms=NNN"

# ---------------------------------------------------------------------------
echo ""
echo "=== Check E: Integration tests ==="
if [[ -z "$CORTEX_API_KEY" ]]; then
    echo "  SKIP  CORTEX_API_KEY not set — skipping integration tests"
    echo "        To run: CORTEX_URL=<url> CORTEX_API_KEY=<key> bash scripts/verify_deployment.sh"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(dirname "$SCRIPT_DIR")"
    if CORTEX_URL="$CORTEX_URL" CORTEX_API_KEY="$CORTEX_API_KEY" \
        python -m pytest "$REPO_ROOT/tests/integration/" -m integration -q 2>&1; then
        _pass "integration tests"
    else
        _fail "integration tests — see output above"
    fi
fi

# ---------------------------------------------------------------------------
echo ""
echo "=== Summary ==="
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo ""

if [[ $FAIL -gt 0 ]]; then
    echo "RESULT: FAIL — $FAIL check(s) need attention"
    exit 1
else
    echo "RESULT: PASS — all checks passed"
    exit 0
fi
