"""Vendoring the two front-end libraries, for working offline.

The page loads Cytoscape and KaTeX from a CDN by default, and prefers a local
copy under ``static/vendor/`` when one exists. ``bp ui --vendor`` puts one there.

This exists because the deterministic half of this system works with no network
at all — ``bp check``, ``bp why``, ``bp render``, and every agent call under
``--replay`` — and it would be a poor joke if the interface to it did not. A
mathematician on a train should be able to read their own proof graph.

Only ``.woff2`` fonts are fetched. Every browser released in the last decade
takes them, and the ``.woff``/``.ttf`` fallbacks would triple the download for
no living user.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

CYTOSCAPE_VERSION = "3.30.2"
KATEX_VERSION = "0.16.11"
CDN = "https://cdn.jsdelivr.net/npm"

KATEX_FONTS = [
    "KaTeX_AMS-Regular",
    "KaTeX_Caligraphic-Bold",
    "KaTeX_Caligraphic-Regular",
    "KaTeX_Fraktur-Bold",
    "KaTeX_Fraktur-Regular",
    "KaTeX_Main-Bold",
    "KaTeX_Main-BoldItalic",
    "KaTeX_Main-Italic",
    "KaTeX_Main-Regular",
    "KaTeX_Math-BoldItalic",
    "KaTeX_Math-Italic",
    "KaTeX_SansSerif-Bold",
    "KaTeX_SansSerif-Italic",
    "KaTeX_SansSerif-Regular",
    "KaTeX_Script-Regular",
    "KaTeX_Size1-Regular",
    "KaTeX_Size2-Regular",
    "KaTeX_Size3-Regular",
    "KaTeX_Size4-Regular",
    "KaTeX_Typewriter-Regular",
]


def vendor_dir() -> Path:
    return Path(__file__).parent / "static" / "vendor"


def is_vendored() -> bool:
    directory = vendor_dir()
    return (directory / "katex.min.js").exists() and (
        directory / "cytoscape.min.js"
    ).exists()


def plan() -> list[tuple[str, str]]:
    """``(url, relative path)`` for everything the page needs."""
    items = [
        (f"{CDN}/cytoscape@{CYTOSCAPE_VERSION}/dist/cytoscape.min.js", "cytoscape.min.js"),
        (f"{CDN}/katex@{KATEX_VERSION}/dist/katex.min.js", "katex.min.js"),
        (f"{CDN}/katex@{KATEX_VERSION}/dist/katex.min.css", "katex.min.css"),
    ]
    for font in KATEX_FONTS:
        items.append(
            (
                f"{CDN}/katex@{KATEX_VERSION}/dist/fonts/{font}.woff2",
                f"fonts/{font}.woff2",
            )
        )
    return items


def download(force: bool = False, log=print) -> int:
    """Fetch everything into ``static/vendor/``. Returns the number written."""
    directory = vendor_dir()
    written = 0
    for url, relative in plan():
        target = directory / relative
        if target.exists() and not force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"could not fetch {url}: {exc}") from exc
        target.write_bytes(data)
        written += 1
        log(f"  {relative}  ({len(data) // 1024} KiB)")
    return written
