./publish.sh#!/usr/bin/env bash
# Run on the owner's machine inside the extracted repository folder.
set -euo pipefail
cd "$(dirname "$0")"
REMOTE="https://github.com/18650Engineer/rosegarden-umbrel-app-store.git"
if [ ! -d .git ]; then
  git init
fi
git branch -M main
git add .
if ! git diff --cached --quiet; then
  git commit -m "Initial Rose Garden Umbrel Community App Store"
fi
if git remote get-url origin >/dev/null 2>&1; then
  existing="$(git remote get-url origin)"
  if [[ "$existing" != "$REMOTE" && "$existing" != 'git@github.com:18650Engineer/rosegarden-umbrel-app-store.git' ]]; then
    echo "Refusing unexpected origin remote: $existing" >&2
    exit 1
  fi
else
  git remote add origin "$REMOTE"
fi
echo "Pushing to $REMOTE"
git push -u origin main
