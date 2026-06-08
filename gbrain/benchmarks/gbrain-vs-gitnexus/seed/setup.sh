#!/bin/bash
# Setup Preact benchmark environment
set -euo pipefail

PREACT_REPO="${PREACT_REPO:-/tmp/preact-bench}"
PREACT_COMMIT="${PREACT_COMMIT:-main}"

echo "=== Setting up Preact benchmark environment ==="

if [ -d "$PREACT_REPO/.git" ]; then
  echo "Preact repo exists at $PREACT_REPO, updating..."
  cd "$PREACT_REPO"
  git fetch origin
  git checkout "$PREACT_COMMIT"
  git reset --hard "origin/$PREACT_COMMIT" 2>/dev/null || git reset --hard "$PREACT_COMMIT"
else
  echo "Cloning Preact to $PREACT_REPO..."
  git clone https://github.com/preactjs/preact.git "$PREACT_REPO"
  cd "$PREACT_REPO"
  git checkout "$PREACT_COMMIT"
fi

echo "Installing Preact dependencies..."
npm install 2>/dev/null || true

echo "Preact repo ready at commit: $(git rev-parse HEAD)"
echo ""
echo "Add to your shell environment:"
echo "  export PREACT_REPO=$PREACT_REPO"
echo "  export PREACT_COMMIT=$(git rev-parse HEAD)"
