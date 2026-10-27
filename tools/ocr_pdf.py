#!/usr/bin/env python3
"""Turn a scanned PDF into a searchable one (an invisible OCR text layer over the original page images), so ingest_papers.py can
find the questions on it exactly as it does for papers that already have a text layer. Needs poppler (pdftoppm) and tesseract.

    python3 tools/ocr_pdf.py archive/CS/2019_CS.pdf ocr/2019_CS.pdf        # paths relative to --pyq-dir (default ~/Downloads/GATE/pyq)

The OCR text is only used to LOCATE questions; students are shown the page image, never the OCR text. Questions from OCR'd papers
must pass the same strict checks against the official key as every other paper.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--pyq-dir", type=Path, default=Path.home() / "Downloads" / "GATE" / "pyq")
    ap.add_argument("--dpi", type=int, default=250)
    a = ap.parse_args()
    src, dst = a.pyq_dir / a.src, a.pyq_dir / a.dst
    if dst.exists():
        print(f"{dst} already exists; nothing to do"); return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", str(a.dpi), "-gray", "-png", str(src), f"{tmp}/p"], check=True)
        pages = sorted(Path(tmp).glob("p-*.png"))
        (Path(tmp) / "list.txt").write_text("\n".join(map(str, pages)))
        print(f"{len(pages)} pages rendered; running OCR (a few seconds per page)", flush=True)
        subprocess.run(["tesseract", str(Path(tmp) / "list.txt"), str(Path(tmp) / "out"), "-l", "eng", "--psm", "3", "pdf"], check=True, capture_output=True)
        (Path(tmp) / "out.pdf").replace(dst)
    print("wrote", dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
