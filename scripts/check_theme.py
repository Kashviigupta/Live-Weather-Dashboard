"""
check_theme.py
--------------
Guard the light theme against drift.

The markup is written with dark utility classes (bg-space-900, text-slate-400,
border-slate-800 ...) and the light theme remaps each one under html.light in
the <style id="theme-light"> block of frontend/index.html.  A colour class
added to the markup or to app.js without a matching light rule would render as
a dark island on the light page, so this script collects every colour utility
in use and fails if any lacks a rule.

Gradient stops (from-/via-/to-) are deliberately excluded: they only colour
accent bars and legends, which read the same on either background.

Usage:  python scripts/check_theme.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"
APP = ROOT / "frontend" / "app.js"

COLOURS = ("space|slate|cyan|blue|violet|emerald|amber|rose|sky|indigo|yellow|orange|"
           "red|green|white|black|cyanGlow|electric|violetGlow|amberGlow|emeraldGlow")

CLASS_PATTERN = re.compile(
    r"(?<![\w-])((?:hover:|focus:)?(?:bg|text|border|ring|shadow|placeholder)-"
    rf"(?:{COLOURS})(?:-\d{{2,3}})?(?:/\d{{1,3}})?)(?![\w/-])"
)

# Solid mid-tone accents that work on both backgrounds (legend chips, dots).
THEME_NEUTRAL = {"bg-slate-400", "bg-slate-500", "bg-slate-600", "text-space-950"}


def css_selector(cls: str) -> str:
    """How Tailwind spells a class as a CSS selector: ':' and '/' escaped."""
    escaped = cls.replace(":", r"\:").replace("/", r"\/")
    if cls.startswith(("hover:", "focus:")):
        escaped += ":" + cls.split(":", 1)[0]
    if cls.startswith("placeholder-"):
        escaped += "::placeholder"
    return "." + escaped


def main() -> int:
    html = INDEX.read_text(encoding="utf-8")
    js = APP.read_text(encoding="utf-8")

    block = re.search(r'<style id="theme-light">(.*?)</style>', html, re.S)
    if not block:
        print("FAIL: no <style id=\"theme-light\"> block in frontend/index.html")
        return 1
    light_css = block.group(1)

    # classes in the markup proper, plus every class app.js writes into the DOM
    markup = html.replace(block.group(0), "")
    used = sorted(set(CLASS_PATTERN.findall(markup + js)) - THEME_NEUTRAL)

    missing = [c for c in used if f"html.light {css_selector(c)}" not in light_css]

    print(f"{len(used)} colour classes in use, {len(used) - len(missing)} covered by the light theme")
    if missing:
        print("classes with no html.light rule:")
        for c in missing:
            print(f"  - {c}   (selector: html.light {css_selector(c)})")
        return 1
    print("OK - every colour class has a light-theme rule")
    return 0


if __name__ == "__main__":
    sys.exit(main())
