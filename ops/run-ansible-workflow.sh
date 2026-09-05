#!/usr/bin/env bash

set -euo pipefail

branch="$(git branch --show-current)"

if [[ -z "$branch" ]]; then
  echo "Unable to determine the current branch (detached HEAD)." >&2
  exit 1
fi

gh workflow run ansible.yml --ref "$branch"
gh run watch --exit-status
