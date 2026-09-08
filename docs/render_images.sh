#!/bin/sh
# Render every docs/diagrams/*.mmd to docs/images/<name>.svg with the Mermaid CLI (downloaded on first use by npx).
# Run from the project root: docs/render_images.sh
set -e
cd "$(dirname "$0")"
mkdir -p images
for src in diagrams/*.mmd; do
  name=$(basename "$src" .mmd)
  npx -y @mermaid-js/mermaid-cli -i "$src" -o "images/$name.svg" -b transparent >/dev/null
  echo "rendered images/$name.svg"
done
