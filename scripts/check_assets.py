"""
check_assets.py
---------------
Guard against a broken CDN reference in the page.

Every external <script src> / <link href> in frontend/index.html is requested;
a non-200 fails the check.  This exists because a Chart.js URL pinned to a
version cdnjs does not host returned 404, which left `Chart` undefined and
stopped app.js before it could load any data or bind any control - the page
rendered as an empty shell with dead buttons.

Usage:  python scripts/check_assets.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
URL_PATTERN = re.compile(r'(?:src|href)="(https?://[^"]+)"')


def main() -> int:
    html = INDEX.read_text(encoding="utf-8")
    urls = sorted(set(URL_PATTERN.findall(html)))
    if not urls:
        print("no external assets referenced")
        return 0

    failures = []
    for url in urls:
        try:
            res = requests.get(url, timeout=30, stream=True)
            status = res.status_code
            res.close()
        except Exception as exc:  # network error is a failure too
            status, exc_text = None, str(exc)
            print(f"  FAIL  {url}\n        {exc_text}")
            failures.append(url)
            continue

        mark = "ok  " if status == 200 else "FAIL"
        print(f"  {mark}  {status}  {url}")
        if status != 200:
            failures.append(url)

    print(f"\n{len(urls) - len(failures)}/{len(urls)} external assets reachable")
    if failures:
        print("broken references:")
        for url in failures:
            print(f"  - {url}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
