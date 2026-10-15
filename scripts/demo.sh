#!/usr/bin/env bash
# The whole story in one command, offline:
#   1. baseline: Peach's full policy prompt
#   2. "prompt diet": a shorter prompt that saves ~19% on cost
#   3. evalgate blocks it, because fraud over $1,000 no longer reaches a human
set -uo pipefail
cd "$(dirname "$0")/.."

echo "== 1. Baseline: the full policy prompt =="
pytest -q --evalgate-update-baseline --evalgate-baseline .evalgate/demo-baseline.json

echo
echo "== 2. The pull request: a 'harmless' cost-cutting prompt tweak =="
before=demo/peach/prompts/peach_system.txt; after=demo/peach/prompts/peach_system_tweak.txt
echo "Prompt length: $(wc -w < $before) words -> $(wc -w < $after) words"
echo "Rule 8 before: $(grep '^8\.' $before)"
echo "Rule 8 after:  $(grep '^8\.' $after)"

echo
echo "== 3. The gate =="
PEACH_PROMPT_FILE=demo/peach/prompts/peach_system_tweak.txt \
  pytest -q --evalgate-baseline .evalgate/demo-baseline.json --evalgate-report .evalgate/demo-report.md
status=$?

echo
echo "pytest exit code: $status (non-zero blocks the merge)"
echo "PR comment written to .evalgate/demo-report.md"
