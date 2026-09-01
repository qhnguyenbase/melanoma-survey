"""Make reportlab render Vietnamese in the generated explanation PDFs.

reportlab's built-in Helvetica is a Latin-1 font, so every Vietnamese diacritic
in the explanation reports would come out as a black box. The vendor model code
asks for "Helvetica" in dozens of places, so rather than editing each call site
this registers a Unicode TTF *under the built-in names*: reportlab resolves font
names through its own registry, so the existing setFont("Helvetica", ...) and
FONTNAME "Helvetica-Bold" calls transparently pick up the new face.

Call install() once before any PDF is generated -- precompute.py and utils.py
both do, so it applies whether the artifacts are built from the cache script or
from a local live-inference run.

matplotlib needs no equivalent: its default DejaVu Sans already covers
Vietnamese.
"""

from __future__ import annotations

from pathlib import Path

# (regular, bold) pairs, best first. DejaVu comes from matplotlib, which the
# models already depend on, so it is the one that is always present.
_FALLBACK_CANDIDATES: list[tuple[str, str]] = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]

# The built-in names the vendor code asks for, mapped to regular or bold.
_ALIASES: dict[str, str] = {
    "Helvetica": "regular",
    "Helvetica-Oblique": "regular",
    "Helvetica-Bold": "bold",
    "Helvetica-BoldOblique": "bold",
}

_installed: bool | None = None


def _matplotlib_dejavu() -> tuple[str, str] | None:
    try:
        import matplotlib
    except ImportError:
        return None
    ttf_dir = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
    regular, bold = ttf_dir / "DejaVuSans.ttf", ttf_dir / "DejaVuSans-Bold.ttf"
    return (str(regular), str(bold)) if regular.is_file() and bold.is_file() else None


def install() -> bool:
    """Point reportlab's Helvetica names at a Vietnamese-capable font.

    Idempotent and safe to call from anywhere; returns True once a font is in
    place. Never raises: a PDF with the wrong glyphs is a better failure than an
    inference run that dies.
    """
    global _installed
    if _installed is not None:
        return _installed

    _installed = False
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return _installed

    candidates = list(_FALLBACK_CANDIDATES)
    dejavu = _matplotlib_dejavu()
    if dejavu:
        candidates.insert(0, dejavu)

    for regular, bold in candidates:
        if not (Path(regular).is_file() and Path(bold).is_file()):
            continue
        try:
            for alias, weight in _ALIASES.items():
                pdfmetrics.registerFont(TTFont(alias, regular if weight == "regular" else bold))
            pdfmetrics.registerFontFamily(
                "Helvetica",
                normal="Helvetica",
                bold="Helvetica-Bold",
                italic="Helvetica-Oblique",
                boldItalic="Helvetica-BoldOblique",
            )
        except Exception:
            continue
        _installed = True
        return _installed

    return _installed
