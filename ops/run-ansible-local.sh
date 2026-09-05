#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/.." && pwd)"
env_file="$script_dir/.env"
mode="${1:-check}"
check_arg=""

usage() {
  cat <<'EOF'
Usage: ./ops/run-ansible-local.sh [check|run]

  check  Run Ansible in check mode (default; no remote changes).
  run    Apply the playbook to the remote host.
EOF
}

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi

case "$mode" in
  check)
    check_arg="--check"
    ;;
  run)
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [[ ! -f "$env_file" ]]; then
  echo "Missing $env_file. Copy ops/.env.example to ops/.env and fill it in." >&2
  exit 1
fi

# The local .env file is user-controlled and must not be committed.
# shellcheck disable=SC1090
source "$env_file"

: "${DEPLOY_HOST:?Set DEPLOY_HOST in ops/.env}"
: "${DEPLOY_USER:?Set DEPLOY_USER in ops/.env}"
: "${DEPLOY_SSH_KEY:?Set DEPLOY_SSH_KEY in ops/.env}"

if [[ ! -r "$DEPLOY_SSH_KEY" ]]; then
  echo "SSH key is not readable: $DEPLOY_SSH_KEY" >&2
  exit 1
fi

echo "Running Ansible in $mode mode against $DEPLOY_USER@$DEPLOY_HOST"

exec ansible-playbook \
  -i "${DEPLOY_HOST}," \
  -u "$DEPLOY_USER" \
  --private-key "$DEPLOY_SSH_KEY" \
  --ssh-common-args="-o StrictHostKeyChecking=accept-new" \
  ${check_arg:+"$check_arg"} \
  "$repo_dir/ansible/playbook.yml"
