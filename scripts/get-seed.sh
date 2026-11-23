#!/usr/bin/env bash
# Bring the team kit's files into this clone: .env (keys) if the clone has none, and data/seed/ (the ERP data) if missing.
# data/seed/ is committed in this repo, so usually only .env is copied; .env is never in git (the repo is public).
#
#   ./scripts/get-seed.sh                  → finds the team kit by itself (see below)
#   ./scripts/get-seed.sh <folder-or-zip>  → that unpacked kit folder (…/voice-erp-kit) or team zip
#   make seed [FROM=<folder-or-zip>]       → same, via make
#
# Where it looks: this folder's parent, ~/Downloads, ~/Desktop, ~/Documents, ~ — for an unpacked kit folder
# (any …/data/seed/meta.json, e.g. ~/Downloads/voice-erp-kit) or a .zip that contains one.
# `make setup` runs it when data/seed or .env is missing. Never overwrites an existing .env.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd -P)"

DEST="${DEST:-./data}"
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# path of …/data/seed/meta.json inside a zip, or nothing
zip_meta() {
  if command -v unzip >/dev/null; then
    unzip -Z1 "$1" 2>/dev/null | grep -m1 -E '(^|/)data/seed/meta\.json$' || true
  else
    python3 -c 'import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
print(next((n for n in names if n == "data/seed/meta.json" or n.endswith("/data/seed/meta.json")), ""))' "$1" 2>/dev/null || true
  fi
}

# kit root (the folder holding data/seed) of an unpacked kit under $1, not this clone itself
kit_dir_in() {
  local meta root
  while IFS= read -r meta; do
    root="$(cd "$(dirname "$meta")/../.." && pwd -P)"
    [[ "$root" != "$REPO" ]] && { echo "$root"; return; }
  done < <(find "$1" -maxdepth 4 -path '*/data/seed/meta.json' -not -path '*/node_modules/*' 2>/dev/null)
  return 0  # nothing found (or only this clone): empty output, not an error (set -e would end the script)
}

SRC="${1:-${FROM:-${ZIP:-}}}"
if [[ -z "$SRC" ]]; then
  for dir in "$REPO/.." "$HOME/Downloads" "$HOME/Desktop" "$HOME/Documents" "$HOME"; do
    [[ -d "$dir" ]] || continue
    SRC="$(kit_dir_in "$dir")"; [[ -n "$SRC" ]] && break
    while IFS= read -r -d '' z; do
      if [[ -n "$(zip_meta "$z")" ]]; then SRC="$z"; break; fi
    done < <(find "$dir" -maxdepth 1 -name '*.zip' -print0 2>/dev/null)
    [[ -n "$SRC" ]] && break
  done
fi
if [[ -z "$SRC" && -f "$DEST/seed/meta.json" ]]; then
  warn "no team kit found for .env: make setup creates one from .env.example (mock providers) — paste your keys into it"
  exit 0
fi
[[ -n "$SRC" ]] || fail "team kit not found (looked in ~/Downloads, ~/Desktop, ~/Documents, ~). Run: make seed FROM=/path/to/voice-erp-kit (folder or .zip)"
[[ -e "$SRC" ]] || fail "no such file or folder: $SRC"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
if [[ -d "$SRC" ]]; then
  KIT="$(cd "$SRC" && pwd -P)"
  [[ -f "$KIT/data/seed/meta.json" ]] || KIT="$(kit_dir_in "$KIT")"
  [[ -n "$KIT" && -f "$KIT/data/seed/meta.json" ]] || fail "$SRC has no data/seed/meta.json: is it the team kit folder?"
else
  META="$(zip_meta "$SRC")"
  [[ -n "$META" ]] || fail "$SRC has no data/seed/meta.json: is it the team zip?"
  PREFIX="${META%data/seed/meta.json}"   # e.g. voice-erp-kit/
  if command -v unzip >/dev/null; then
    unzip -q "$SRC" "${PREFIX}data/seed/*" -d "$TMP"
    unzip -q "$SRC" "${PREFIX}.env" -d "$TMP" 2>/dev/null || true
  else
    python3 -c 'import sys, zipfile
z = zipfile.ZipFile(sys.argv[1]); p = sys.argv[2]
z.extractall(sys.argv[3], [n for n in z.namelist() if n.startswith(p + "data/seed/") or n == p + ".env"])' "$SRC" "$PREFIX" "$TMP"
  fi
  KIT="$TMP/${PREFIX%/}"
fi

# 1. the ERP data
if [[ ! -f "$DEST/seed/meta.json" || -n "${FORCE:-}" || $# -gt 0 ]]; then
  mkdir -p "$DEST"
  rm -rf "$DEST/seed"
  cp -R "$KIT/data/seed" "$DEST/seed"
  [[ -f "$DEST/seed/meta.json" ]] || fail "copy failed: $DEST/seed/meta.json missing"
  ok "data/seed copied from $SRC ($(ls "$DEST/seed" | wc -l | tr -d ' ') files)"
else
  ok "data/seed already there (kept)"
fi

# 2. the keys: only when this clone has no .env (never overwrite one)
if [[ -f .env ]]; then
  ok ".env already there (kept)"
elif [[ -f "$KIT/.env" ]]; then
  cp "$KIT/.env" .env && ok ".env copied from $SRC"
else
  warn "no .env in $SRC: make setup creates one from .env.example (mock providers) — paste your keys into it"
fi
