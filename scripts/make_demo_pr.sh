#!/usr/bin/env bash
# Creates the demo pull request branch: Peach's prompt goes on a "diet".
# Push it and open a PR to watch the eval gate comment and block the merge.
set -euo pipefail
cd "$(dirname "$0")/.."

git checkout -b prompt-diet
cp demo/peach/prompts/peach_system_tweak.txt demo/peach/prompts/peach_system.txt
git commit -am "Trim Peach system prompt to cut token cost"
echo
echo "Now: git push -u origin prompt-diet   and open a pull request."
