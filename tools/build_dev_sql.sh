#!/bin/sh
# Regenerate the SQL for a development database from the real papers (needs the PDFs, poppler and Python 3.12).
#   tools/build_dev_sql.sh ~/Downloads/GATE            # writes build/dev/{keys,tax,ingest,tags}.sql and the question page images
set -e
GATE="${1:-$HOME/Downloads/GATE}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/dev"; mkdir -p "$OUT"
python3 -I "$ROOT/tools/import_keys.py"   --keys-dir "$GATE/pyq" --dump-json "$OUT/keys.json" 2>/dev/null > "$OUT/keys.sql"
python3 -I "$ROOT/tools/load_taxonomy.py" --syllabus "$GATE/CS_GATE2027_Syllabus.pdf" 2>/dev/null > "$OUT/tax.sql"
# scanned papers are made searchable first (OCR; skipped when the file already exists)
for f in 2019_CS 2017_CS1 2017_CS2; do python3 -I "$ROOT/tools/ocr_pdf.py" "archive/CS/$f.pdf" "ocr/$f.pdf" --pyq-dir "$GATE/pyq" >/dev/null; done
python3 -I "$ROOT/tools/ingest_papers.py" --pyq-dir "$GATE/pyq" --out-dir "$GATE/pyq/ingest" --key-json "$OUT/keys.json" 2>/dev/null > "$OUT/ingest.sql"
python3 -I "$ROOT/tools/load_tags.py"     --key-json "$OUT/keys.json" 2>/dev/null > "$OUT/tags.sql"
echo "wrote $OUT (crops in $GATE/pyq/ingest)"; wc -l "$OUT"/*.sql
