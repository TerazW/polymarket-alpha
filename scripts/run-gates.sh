#!/bin/bash
# run-gates.sh - Run CI gates locally before push
#
# Usage:
#   ./scripts/run-gates.sh          # Run all gates
#   ./scripts/run-gates.sh --quick  # Skip slow tests
#   ./scripts/run-gates.sh --gate determinism  # Run specific gate

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
QUICK=false
GATE=""

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --quick) QUICK=true ;;
        --gate) GATE="$2"; shift ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

echo "=========================================="
echo " Market Sensemaking - CI Gates"
echo "=========================================="
echo ""

run_gate() {
    local name=$1
    local command=$2

    echo -e "${YELLOW}Running: $name${NC}"
    echo "Command: $command"
    echo ""

    if eval "$command"; then
        echo -e "${GREEN}[PASSED]${NC} $name"
        echo ""
        return 0
    else
        echo -e "${RED}[FAILED]${NC} $name"
        echo ""
        return 1
    fi
}

FAILED=0

# Run specific gate or all gates
if [ -n "$GATE" ]; then
    case $GATE in
        determinism)
            run_gate "Determinism" "python -m pytest tests/adversarial/test_determinism.py tests/adversarial/test_belief_state_replay.py -v" || FAILED=1
            ;;
        adversarial)
            run_gate "Adversarial" "python -m pytest tests/adversarial/ -v" || FAILED=1
            ;;
        security)
            run_gate "Security" "python -m pytest tests/test_security.py tests/test_reactor_api.py::TestEventInjection -v" || FAILED=1
            ;;
        unit)
            run_gate "Unit Tests" "python -m pytest tests/ --ignore=tests/adversarial -v" || FAILED=1
            ;;
        *)
            echo "Unknown gate: $GATE"
            echo "Available gates: determinism, adversarial, security, unit"
            exit 1
            ;;
    esac
else
    # Run all gates
    echo "Running all gates..."
    echo ""

    # Gate 1: Unit Tests
    run_gate "Unit Tests" "python -m pytest tests/ --ignore=tests/adversarial -v --tb=short" || FAILED=1

    # Gate 2: Determinism
    run_gate "Determinism Gate" "python -m pytest tests/adversarial/test_determinism.py tests/adversarial/test_belief_state_replay.py -v --tb=short" || FAILED=1

    # Gate 3: Adversarial
    run_gate "Adversarial Gate" "python -m pytest tests/adversarial/ -v --tb=short" || FAILED=1

    # Gate 4: Security
    run_gate "Security Gate" "python -m pytest tests/test_security.py tests/test_reactor_api.py::TestEventInjection -v --tb=short" || FAILED=1
fi

echo ""
echo "=========================================="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}ALL GATES PASSED${NC}"
    echo "=========================================="
    echo ""
    echo "Ready to push!"
    exit 0
else
    echo -e "${RED}SOME GATES FAILED${NC}"
    echo "=========================================="
    echo ""
    echo "Please fix failing tests before pushing."
    exit 1
fi
