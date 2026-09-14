"""
fetch_cities.py
---------------
Download the remaining city archives without tripping the provider's limits.

Each archive is six years of daily data for nine variables.  The Open-Meteo
free tier weighs a request by how much data it returns, so one of these costs
far more than an ordinary call, against a budget of roughly 5,000 units an hour
and 10,000 a day.  Fired back to back, a few dozen exhaust the hour and every
later request is refused - including the site's own live readings.

So this script spends the budget deliberately:

* at most PER_HOUR archives in any rolling hour and PER_DAY in any rolling day;
* one attempt per archive - a refused request is never retried in a tight loop;
* when refused, it reads the provider's reason and sleeps for exactly that
  window (a minute, to the next hour, or to the next UTC day) before resuming.

The largest states go first, so the most-used cities land earliest.  Archives
already on disk are skipped, so it is safe to stop and re-run at any time.
Only one copy should run at once; a lock file enforces that.

Usage:  python scripts/fetch_cities.py
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import time
from collections import deque
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import cities  # noqa: E402
import regions  # noqa: E402

PER_HOUR = 25
PER_DAY = 60
SPACING_SECONDS = 20

PRIORITY_STATES = ["maharashtra", "uttar-pradesh", "karnataka", "tamil-nadu",
                   "west-bengal", "gujarat", "rajasthan", "telangana", "kerala",
                   "madhya-pradesh", "punjab", "haryana", "bihar", "odisha"]

LOCK = ROOT / "data" / "cache" / ".fetch_cities.lock"


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def pending() -> list:
    rank = {s: i for i, s in enumerate(PRIORITY_STATES)}
    todo = [cid for cid in cities.catalogue() if not regions.cache_path(cid).exists()]
    return sorted(todo, key=lambda cid: (rank.get(cities.get(cid)["state_id"], len(rank)), cid))


def seconds_until(reason: str) -> int:
    """How long the provider told us to wait, from its 429 reason text."""
    now = dt.datetime.now(dt.timezone.utc)
    text = reason.lower()
    if "daily" in text:
        tomorrow = (now + dt.timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        return int((tomorrow - now).total_seconds())
    if "hourly" in text:
        next_hour = (now + dt.timedelta(hours=1)).replace(minute=2, second=0, microsecond=0)
        return int((next_hour - now).total_seconds())
    return 75                                          # minutely, or unknown


def acquire_lock() -> bool:
    try:
        if LOCK.exists():
            pid = int(LOCK.read_text().strip() or 0)
            if pid and pid != os.getpid():
                try:
                    os.kill(pid, 0)                    # raises if that process is gone
                    return False
                except (OSError, SystemError):
                    pass
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(str(os.getpid()))
        return True
    except Exception:
        return True


def main() -> int:
    if not acquire_lock():
        log(f"another fetch_cities.py is already running (lock: {LOCK}) - exiting")
        return 1

    # this script owns pacing and retries; switch off the module's own loop
    regions.MAX_ATTEMPTS = 1
    regions.MIN_SECONDS_BETWEEN_CALLS = 0

    hour_log, day_log = deque(), deque()
    total = len(cities.catalogue())

    try:
        while True:
            todo = pending()
            log(f"{total - len(todo)}/{total} city archives on disk, {len(todo)} to go")
            if not todo:
                log("all city archives fetched - rebuild and push to publish them")
                return 0

            now = time.time()
            while hour_log and now - hour_log[0] > 3600:
                hour_log.popleft()
            while day_log and now - day_log[0] > 86400:
                day_log.popleft()

            if len(day_log) >= PER_DAY:
                wait = int(86400 - (now - day_log[0])) + 60
                log(f"daily budget of {PER_DAY} used - sleeping {wait // 60} min")
                time.sleep(wait)
                continue
            if len(hour_log) >= PER_HOUR:
                wait = int(3600 - (now - hour_log[0])) + 30
                log(f"hourly budget of {PER_HOUR} used - sleeping {wait // 60} min")
                time.sleep(wait)
                continue

            cid = todo[0]
            rec = cities.get(cid)
            hour_log.append(now)
            day_log.append(now)
            try:
                df = regions.region_frame(cid)
                log(f"  + {rec['name']} ({rec['state_name']}): {len(df)} days")
                time.sleep(SPACING_SECONDS)
            except requests.HTTPError as exc:
                resp = exc.response
                reason = ""
                try:
                    reason = resp.json().get("reason", "")
                except Exception:
                    reason = resp.text[:120] if resp is not None else str(exc)
                if resp is not None and resp.status_code == 429:
                    wait = seconds_until(reason)
                    log(f"  refused ({reason or '429'}) - sleeping {wait // 60} min {wait % 60} s")
                    time.sleep(wait)
                else:
                    log(f"  ! {rec['name']}: {exc} - skipping for now")
                    time.sleep(SPACING_SECONDS)
            except Exception as exc:
                log(f"  ! {rec['name']}: {type(exc).__name__}: {exc} - retrying later")
                time.sleep(120)
    finally:
        try:
            LOCK.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
