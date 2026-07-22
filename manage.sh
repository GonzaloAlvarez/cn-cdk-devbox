#!/usr/bin/env bash
# Manual driver for the devbox stacks. Day-to-day use goes through the
# `clouddevbox` CLI (cn-cli-devbox), which also handles the tailscale
# preauth-key handoff; this script only wraps cdk for base maintenance,
# synth inspection and emergencies.
set -euo pipefail

COMMAND="${1:-}"
BOX="${2:-}"

usage() {
  echo "Usage: $0 <deploy|destroy|synth|test> [boxname]"
  echo "  deploy            deploy/update DevboxBase only"
  echo "  deploy <box>      deploy DevboxBase + Devbox-<box> (no authkey handoff!)"
  echo "  destroy           destroy DevboxBase (fails while any box exists)"
  echo "  destroy <box>     destroy Devbox-<box>"
  echo "  synth [box]       synthesize templates"
  echo "  test              run the pytest suite"
  exit 1
}

[[ "$COMMAND" == "deploy" || "$COMMAND" == "destroy" || "$COMMAND" == "synth" || "$COMMAND" == "test" ]] || usage

# Homebrew asdf >= 0.16 is a Go binary with no asdf.sh to source; anything
# that puts `node` on PATH (asdf shims, brew, nvm) is fine.
if ! command -v node >/dev/null 2>&1; then
  echo "Error: node not found on PATH (install via asdf/brew)." >&2
  exit 1
fi

cleanup() {
  rm -rf .venv .npm
}
trap cleanup EXIT

python3 -m venv .venv
source .venv/bin/activate
pip install --quiet -r requirements.txt

if [[ "$COMMAND" == "test" ]]; then
  pip install --quiet -r requirements-dev.txt
  pytest -q
  exit 0
fi

npm install --prefix .npm --silent aws-cdk

if [[ -z "${AWS_PROFILE:-}" ]]; then
  read -rp "AWS Profile: " AWS_PROFILE
fi
export AWS_PROFILE

if [[ -z "${AWS_ACCOUNT_ID:-}" ]]; then
  echo "Discovering AWS account ID for profile '$AWS_PROFILE'..."
  AWS_ACCOUNT_ID=$(.venv/bin/python3 -c "import boto3; print(boto3.client('sts').get_caller_identity()['Account'])")
fi
export AWS_ACCOUNT_ID

CDK=.npm/node_modules/.bin/cdk
CTX=()
[[ -n "$BOX" ]] && CTX=(-c "box=$BOX")

case "$COMMAND" in
  deploy)
    if [[ -n "$BOX" ]]; then
      $CDK deploy DevboxBase "Devbox-$BOX" "${CTX[@]}" --require-approval never
    else
      $CDK deploy DevboxBase --require-approval never
    fi
    ;;
  destroy)
    if [[ -n "$BOX" ]]; then
      $CDK destroy "Devbox-$BOX" "${CTX[@]}" --force
    else
      $CDK destroy DevboxBase --force
    fi
    ;;
  synth)
    $CDK synth "${CTX[@]}"
    ;;
esac
