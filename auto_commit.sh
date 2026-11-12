#!/bin/bash
# Auto-commit script for special-doodle repository
# This script copies Maple-Pro test files and updates HANDOFF.md

REPO="special-doodle"
LOCAL_DIR="/home/igor/ia-sh/pc-sala-agent"

cd "$LOCAL_DIR"

# Files to copy/add to special-doodle
FILES=(
    "RELATORIO_MAPLE_PRO_TESTES.md"
    "HANDOFF.md"
    "tests/test_maple_pro_deep.py"
    "tests/test_maple_pro_round2.py"
    "tests/test_maple_pro_round2b.py"
    "tests/test_maple_pro_round2c.py"
    "tests/test_maple_pro_round3_concorrencia.py"
    "tests/test_ctx_needle_final.py"
    "tests/test_ctx_direct.py"
    "tests/test_context_limit.py"
    "tests/test_maple_context_long.py"
)

# Add and commit files
git add "${FILES[@]}" 2>/dev/null

# Check if there are changes
if git diff --cached --quiet; then
    echo "Nenhuma alteração para commitar"
    exit 0
fi

# Commit with timestamp
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
git commit -m "automated: update Maple-Pro test results $(TIMESTAMP)"

# Push to special-doodle
git push special-doodle main 2>&1 | tail -3

echo "Auto-commit completed at $(date -u)"
