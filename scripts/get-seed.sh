#!/usr/bin/env bash
# Copy the ERP seed (data/seed/, git-ignored: too big and private) from the team zip into ./data/seed.
#
#   ./scripts/get-seed.sh                      → looks for the team zip in this folder, ~/Downloads, ~/Desktop, ~
#   ./scripts/get-seed.sh path/to/team.zip     → that zip
#   make seed ZIP=path/to/team.zip             → same, via make
#
# A team zip is any .zip that contains .../data/seed/meta.json (e.g. voice-erp-kit/data/seed/meta.json).
# `make setup` runs this automatically when ./data/seed is missing. Safe to re-run (overwrites ./data/seed).
set -euo pipefail
cd "$(dirname "$0")/.."

DEST="${DEST:-./data}"
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# Prints the path of meta.json inside the zip, or nothing.
seed_in_zip() {
  if command -v unzip >/dev/null; then
    unzip -Z1 "$1" 2>/dev/null | grep -m1 -E '(^|/)data/seed/meta\.json$' || true
  else
    python3 -c 'import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
print(next((n for n in names if n == "data/seed/meta.json" or n.endswith("/data/seed/meta.json")), ""))' "$1" 2>/dev/null || true
  fi
}

ZIP="${1:-${ZIP:-}}"
if [[ -z "$ZIP" ]]; then
  for dir in . "$HOME/Downloads" "$HOME/Desktop" "$HOME"; do
    [[ -d "$dir" ]] || continue
    while IFS= read -r -d '' candidate; do
      if [[ -n "$(seed_in_zip "$candidate")" ]]; then ZIP="$candidate"; break 2; fi
    done < <(find "$dir" -maxdepth 1 -name '*.zip' -print0 2>/dev/null)
  done
fi
[[ -n "$ZIP" ]] || fail "team zip not found in this folder, ~/Downloads, ~/Desktop or ~. Run: make seed ZIP=/path/to/your-team.zip"
[[ -f "$ZIP" ]] || fail "no such file: $ZIP"

META="$(seed_in_zip "$ZIP")"
[[ -n "$META" ]] || fail "$ZIP has no data/seed/meta.json: is it the team zip?"
PREFIX="${META%meta.json}"   # e.g. voice-erp-kit/data/seed/

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
if command -v unzip >/dev/null; then
  unzip -q "$ZIP" "${PREFIX}*" -d "$TMP"
else
  python3 -c 'import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
z.extractall(sys.argv[3], [n for n in z.namelist() if n.startswith(sys.argv[2])])' "$ZIP" "$PREFIX" "$TMP"
fi
mkdir -p "$DEST"
rm -rf "$DEST/seed"
cp -R "$TMP/${PREFIX%/}" "$DEST/seed"
[[ -f "$DEST/seed/meta.json" ]] || fail "copy failed: $DEST/seed/meta.json missing"
ok "seed copied from $ZIP → $DEST/seed ($(ls "$DEST/seed" | wc -l | tr -d ' ') files)"
