"""Phase 0 spike — THROWAWAY. Measures the natural (unwrapped) width of strings in mm.

    docker compose -f compose.dev.yml run --rm tests python spike/measure_widths.py
"""

import html
import json
from pathlib import Path

from weasyprint import HTML

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "app" / "assets"
PX_PER_MM = 96 / 25.4

FACES = "".join(
    f'@font-face {{ font-family: "{fam}"; font-weight: {w}; src: url("fonts/{f}.ttf"); }}'
    for fam, w, f in [
        ("Noto Sans Arabic", 400, "NotoSansArabic-Regular"), ("Noto Sans Arabic", 700, "NotoSansArabic-Bold"),
        ("Noto Naskh Arabic", 400, "NotoNaskhArabic-Regular"), ("Noto Naskh Arabic", 700, "NotoNaskhArabic-Bold"),
        ("Noto Sans", 400, "NotoSans-Regular"), ("Noto Sans", 700, "NotoSans-Bold"),
    ]
)

NUMBERS = {
    "money max (regular)": ("999,999,999.99", 400),
    "money max (bold footer)": ("999,999,999.99", 700),
    "price max": ("10,000,000.00", 400),
    "qty widest": ("999,999.999", 400),
    "qty max int": ("1,000,000", 400),
    "discount widest": ("99.99%", 400),
}


def widths(strings: list[tuple[str, int]], stack: str, pt: float) -> list[float]:
    spans = "".join(
        f'<div><span style="font-weight:{w}">{html.escape(s)}</span></div>' for s, w in strings
    )
    doc = HTML(
        string=f'<html dir="rtl"><style>{FACES} @page {{ size: 2000mm 4000mm; margin: 0 }}'
        f' body {{ font-family: {stack}; font-size: {pt}pt; white-space: nowrap; margin: 0 }}'
        f' span {{ font-variant-numeric: tabular-nums }}</style><body>{spans}</body></html>',
        base_url=str(ASSETS) + "/",
    ).render()
    out = []
    for box in doc.pages[0]._page_box.descendants():
        if type(box).__name__ == "LineBox":
            out.append(sum(c.width for c in box.children) / PX_PER_MM)
    return out


def main() -> None:
    names = [it["name"] for it in json.loads(
        (ROOT / "tests/fixtures/items_45.json").read_text(encoding="utf-8"))["items"]]
    names += ["مكيف شارب 1.5 حصان بارد ساخن مع تركيب مجان"[:40], "ششششششششششششششششششششششششششششششششششششش"[:40]]
    stacks = {
        "sans": '"Noto Sans Arabic", "Noto Sans", sans-serif',
        "naskh": '"Noto Naskh Arabic", "Noto Sans", sans-serif',
        "latin-first": '"Noto Sans", "Noto Sans Arabic", sans-serif',
    }
    for pt in (9.5, 9, 8.5):
        print(f"\n===== {pt}pt =====")
        for key in ("sans", "naskh"):
            w = widths([(n, 400) for n in names], stacks[key], pt)
            ranked = sorted(zip(w, names), reverse=True)
            print(f"[{key}] names: widest 6 of {len(names)}:")
            for width, n in ranked[:6]:
                print(f"    {width:5.1f}mm  len={len(n):2d}  {n}")
            forty = [width for width, n in ranked if len(n) == 40 and not n.isascii()]
            print(f"    -> widest 40-char Arabic name: {max(forty):.1f}mm")
        for key in ("sans", "latin-first", "naskh"):
            w = widths(list(NUMBERS.values()), stacks[key], pt)
            print(f"[{key}] numbers: " + ", ".join(f"{k}={v:.1f}" for k, v in zip(NUMBERS, w)))


if __name__ == "__main__":
    main()
