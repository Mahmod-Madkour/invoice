"""Render every fixture in tests/fixtures/ to samples/<name>.pdf and samples/<name>-<page>.png.

Development tool only (the server never writes PDFs to disk). Run inside the dev container:

    docker compose -f compose.dev.yml run --rm tests python scripts/render_samples.py
    docker compose -f compose.dev.yml run --rm tests python scripts/render_samples.py items_1 items_81
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pdf.renderer import InvoicePdfRenderer  # noqa: E402
from app.pdf.viewmodel import build_invoice_view  # noqa: E402
from tests.support import FIXTURES_DIR, fixture_invoice  # noqa: E402

SAMPLES_DIR = ROOT / "samples"
PNG_DPI = "110"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="fixture names (default: all)")
    parser.add_argument("--no-png", action="store_true", help="skip the pdftoppm PNG step")
    args = parser.parse_args()

    names = args.names or sorted(p.stem for p in FIXTURES_DIR.glob("*.json"))
    if not args.no_png and shutil.which("pdftoppm") is None:
        parser.error("pdftoppm not found (install poppler-utils, or use --no-png)")

    SAMPLES_DIR.mkdir(exist_ok=True)
    renderer = InvoicePdfRenderer()
    for name in names:
        invoice = fixture_invoice(name)
        started = time.perf_counter()
        view = build_invoice_view(invoice)
        pdf = renderer.render_pdf(view)
        elapsed = time.perf_counter() - started

        pdf_path = SAMPLES_DIR / f"{name}.pdf"
        pdf_path.write_bytes(pdf)
        if not args.no_png:
            for old in SAMPLES_DIR.glob(f"{name}-*.png"):
                old.unlink()
            subprocess.run(["pdftoppm", "-r", PNG_DPI, "-png", str(pdf_path), str(SAMPLES_DIR / name)], check=True)
        print(f"{name:12s} {len(invoice.items):4d} items  {len(view.pages):2d} page(s)  "
              f"grand total {view.grand_total:>16s}  {len(pdf) // 1024:4d} KB  {elapsed:5.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
