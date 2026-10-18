#!/usr/bin/env bash
# Build the submission zip for the NYLP AI Hackathon 2026.
#
#   bash scripts/make_submission_zip.sh
#
# Produces dist/ScamLens-NYLP-AI-Hackathon-2026.zip containing the complete source tree
# with no virtualenvs, node_modules, caches, training data downloads, databases or dotfiles —
# a judge can unzip it and run `make setup && make train && make dev`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# NOTE: the output directory must be one that survives workspace snapshots. `dist/` is a
# build-output name that gets excluded, which is why an earlier archive was not downloadable.
OUT_DIR="$ROOT/submission"
STAGE="$OUT_DIR/ScamLens"
ZIP="$OUT_DIR/ScamLens-NYLP-AI-Hackathon-2026.zip"

rm -rf "$STAGE" "$ZIP"
mkdir -p "$STAGE"

echo "Copying source …"
# python3 does the copying so the script has no dependency beyond a shell + zip.
ROOT="$ROOT" STAGE="$STAGE" python3 - <<'PY'
import os, shutil
from pathlib import Path

root, stage = Path(os.environ["ROOT"]), Path(os.environ["STAGE"])
SKIP_DIRS = {".git", "node_modules", "dist", "build", "out", "target", "coverage", ".venv",
             "venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".vite",
             ".cache", "uploads", ".arena", ".local", "submission"}
SKIP_FILES = {".env", ".DS_Store", "scamlens.db", "scamlens.db-shm", "scamlens.db-wal",
              "tsconfig.tsbuildinfo"}
copied = 0
for src in sorted(root.rglob("*")):
    rel = src.relative_to(root)
    if any(part in SKIP_DIRS for part in rel.parts):
        continue
    if rel.parts[:2] == ("data", "raw"):
        continue                      # re-downloadable datasets: see data/raw/README.md
    if src.is_dir():
        (stage / rel).mkdir(parents=True, exist_ok=True)
        continue
    if src.name in SKIP_FILES or src.suffix == ".pyc" or src.name.endswith((".db-shm", ".db-wal")):
        continue
    (stage / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, stage / rel)
    copied += 1
print(f"  {copied} files copied")
PY

# Keep the empty data/raw directory (the download script writes into it) and a note so the
# zip is self-explanatory about the one thing it deliberately does not contain.
mkdir -p "$STAGE/data/raw"
cat > "$STAGE/data/raw/README.md" <<'EOF'
# Raw datasets are not shipped in the zip

They are large and freely re-downloadable, so the archive excludes them. Recreate them with:

    make data          # ml/download_data.sh — UCI SMS Spam, SpamAssassin, PhiUSIIL

`make setup` then installs dependencies and `make train` rebuilds the models.
See ../README.md for licences and provenance.
EOF

echo "Writing MANIFEST.txt …"
{
  echo "ScamLens — NYLP AI Hackathon 2026 submission archive"
  echo "Built: $(date -u '+%Y-%m-%d %H:%M UTC')"
  echo "Commit state: $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo 'no git metadata in archive')"
  echo
  echo "Included: full source tree, curated synthetic data, trained model artifacts"
  echo "          (ml/artifacts/*.joblib, *.json) and docs/screenshots/*.png."
  echo "Excluded: raw dataset downloads (re-create with 'make data'), node_modules,"
  echo "          virtualenvs, caches, databases and any .env file."
  echo
  echo "Contents:"
  (cd "$STAGE" && find . -type f | sed 's|^\./||' | sort)
} > "$STAGE/MANIFEST.txt"

mkdir -p "$OUT_DIR"
echo "Zipping …"
(cd "$OUT_DIR" && zip -qr9 "$(basename "$ZIP")" ScamLens)

SIZE=$(du -h "$ZIP" | cut -f1)
FILES=$(cd "$STAGE" && find . -type f | wc -l | tr -d ' ')
echo
echo "✓ $ZIP"
echo "  $FILES files, $SIZE"
