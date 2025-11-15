#!/usr/bin/env python3

"""
casablanca_scraper.py

Tailored scraper for: https://www.casablanca-bourse.com/fr/live-market/marche-actions-groupement

Saves CSV rows: category, <all table columns...>, date, time, timestamp_iso

Dependencies:
  pip install requests beautifulsoup4 lxml certifi

Run once example:
  python casablanca_scraper.py --url "https://www.casablanca-bourse.com/fr/live-market/marche-actions-groupement" --output cse_groupement.csv --once

Run continuously (every 15 minutes by default):
  python casablanca_scraper.py --url "https://www.casablanca-bourse.com/fr/live-market/marche-actions-groupement" --output cse_groupement.csv

"""

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

import requests
import certifi
from bs4 import BeautifulSoup

# zoneinfo for timezone handling (Python 3.9+)
try:
    from zoneinfo import ZoneInfo  # type: ignore
except Exception:
    ZoneInfo = None  # type: ignore

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/117.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 15


def fetch_html(url: str, max_retries: int = 3, backoff: float = 1.0, insecure: bool = False) -> str:
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    attempt = 0
    while True:
        try:
            verify_arg = False if insecure else certifi.where()
            resp = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT, verify=verify_arg)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            attempt += 1
            if attempt > max_retries:
                raise
            wait = backoff * (2 ** (attempt - 1))
            print(f"[fetch_html] attempt {attempt} failed: {exc}. retrying in {wait:.1f}s...")
            time.sleep(wait)


def cleanup_text(s: Optional[str]) -> str:
    if not s:
        return ""
    return " ".join(s.replace("\xa0", " ").strip().split())


def parse_price(raw: str) -> Optional[float]:
    if not raw:
        return None
    s = raw.strip()
    s = s.replace("\xa0", " ").strip()
    s = re.sub(r"[^\d,\.\-+]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    s = s.replace(" ", "")
    try:
        return float(s)
    except Exception:
        return None


def find_category_for_table(tbl) -> str:
    # look for the nearest preceding heading element
    for prev in tbl.find_all_previous():
        if prev.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            txt = cleanup_text(prev.get_text())
            if txt:
                    return txt.replace(",", "")
    # try parent search
    parent = tbl.parent
    for _ in range(3):
        if not parent:
            break
        heading = parent.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
        if heading:
            txt = cleanup_text(heading.get_text())
            if txt:
                    return txt.replace(",", "")
        parent = parent.parent
    return ""


def write_dict_rows_to_csv(path: str, rows: List[Dict[str, str]], fieldnames: List[str], ts_iso: str, local_date: str, local_time: str):
    # final header includes timestamp columns
    header = list(fieldnames) + ["date", "time", "timestamp_iso"]
    exists = os.path.isfile(path)
    # When creating a new file, write with UTF-8 BOM (utf-8-sig) so Excel/Windows shows accents correctly.
    # When appending, use plain utf-8 to avoid inserting a BOM in the middle of the file.
    enc = "utf-8-sig" if not exists else "utf-8"
    with open(path, "a", newline="", encoding=enc) as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(header)
        for r in rows:
            row = [r.get(fn, "") for fn in fieldnames]
            row.extend([local_date, local_time, ts_iso])
            writer.writerow(row)


def run_once(url: str, output: str,
             row_selector: Optional[str] = None,
             company_selector: Optional[str] = None,
             price_selector: Optional[str] = None,
             tz_name: Optional[str] = None,
             insecure: bool = False) -> int:
    html = fetch_html(url, insecure=insecure)
    soup = BeautifulSoup(html, "lxml")

    now_utc = datetime.now(timezone.utc)
    # Prefer explicit tz if provided. Otherwise use fixed GMT+1 (Casablanca local time as requested)
    if tz_name:
        if ZoneInfo is None:
            print("[warning] zoneinfo not available, using UTC for timestamp.")
            local_dt = now_utc
        else:
            try:
                local_dt = now_utc.astimezone(ZoneInfo(tz_name))
            except Exception as exc:
                print(f"[warning] invalid tz '{tz_name}': {exc}. Using UTC.")
                local_dt = now_utc
    else:
        # Use a fixed GMT+1 offset as requested
        from datetime import timedelta

        local_dt = now_utc.astimezone(timezone(timedelta(hours=1)))

    ts_iso = local_dt.isoformat()
    local_date = local_dt.strftime("%Y-%m-%d")
    local_time = local_dt.strftime("%H:%M:%S")

    extracted_rows: List[Dict[str, str]] = []
    # fieldnames starts with category and will grow as new columns are discovered
    fieldnames: List[str] = ["category"]

    if row_selector:
        rows = soup.select(row_selector)
        for r in rows:
            cells = [cleanup_text(td.get_text()) for td in r.find_all(["td", "th"])]
            # create auto headers if none yet
            if len(fieldnames) < 2:
                for i in range(len(cells)):
                    col = f"col{i+1}"
                    if col not in fieldnames:
                        fieldnames.append(col)
            rowdict: Dict[str, str] = {"category": ""}
            for i, v in enumerate(cells):
                key = fieldnames[1 + i] if 1 + i < len(fieldnames) else f"col{i+1}"
                if key not in fieldnames:
                    fieldnames.append(key)
                rowdict[key] = v
            extracted_rows.append(rowdict)
    else:
        header_keywords = ["dernier", "dernier cours", "last", "prix", "cours", "valeur"]
        tables = soup.find_all("table")
        for tbl in tables:
            # gather headers for this table
            headers: List[str] = []
            thead = tbl.find("thead")
            if thead:
                ths = thead.find_all("th")
                headers = [cleanup_text(th.get_text()) for th in ths]
            if not headers:
                first_tr = tbl.find("tr")
                if first_tr:
                    ths = first_tr.find_all(["th", "td"])
                    headers = [cleanup_text(th.get_text()) for th in ths]

            header_text = " | ".join(headers).lower()
            if not any(kw in header_text for kw in header_keywords):
                # skip tables that don't look like market tables
                continue

            category = find_category_for_table(tbl)

            # normalize headers; if empty create generic names
            norm_headers: List[str] = []
            if headers:
                for i, h in enumerate(headers):
                    hh = h if h else f"col{i+1}"
                    base = hh
                    idx = 1
                    while base in norm_headers:
                        idx += 1
                        base = f"{hh}_{idx}"
                    norm_headers.append(base)

            # iterate data rows
            for tr in tbl.find_all("tr"):
                tds = tr.find_all("td")
                if not tds:
                    continue
                cells = [cleanup_text(td.get_text()) for td in tds]
                if not norm_headers:
                    norm_headers = [f"col{i+1}" for i in range(len(cells))]
                for h in norm_headers:
                    if h not in fieldnames:
                        fieldnames.append(h)
                rowdict: Dict[str, str] = {"category": category}
                for i, v in enumerate(cells[: len(norm_headers)]):
                    rowdict[norm_headers[i]] = v
                extracted_rows.append(rowdict)

    # write results
    write_dict_rows_to_csv(output, extracted_rows, fieldnames, ts_iso, local_date, local_time)
    print(f"[run_once] wrote {len(extracted_rows)} rows to {output} (timestamp {ts_iso})")
    return len(extracted_rows)


def _time_from_hm(hm: str):
    """Return a time object from HH:MM string."""
    h, m = hm.split(":")
    return datetime.strptime(f"{int(h):02d}:{int(m):02d}", "%H:%M").time()


def generate_run_times_for_day(date_dt: datetime, start_hm: str, end_hm: str, interval_minutes: int = 15, offset_minutes: int = 1, tzinfo=None):
    """Generate datetime objects (tz-aware if tzinfo provided) for each quarter between start and end.

    Each returned time is the quarter mark + offset_minutes.
    """
    start_time = _time_from_hm(start_hm)
    end_time = _time_from_hm(end_hm)
    runs = []
    cur = datetime.combine(date_dt.date(), start_time)
    if tzinfo:
        cur = cur.replace(tzinfo=tzinfo)
    end_dt = datetime.combine(date_dt.date(), end_time)
    if tzinfo:
        end_dt = end_dt.replace(tzinfo=tzinfo)

    while cur <= end_dt:
        run_dt = cur + timedelta(minutes=offset_minutes)
        runs.append(run_dt)
        cur = cur + timedelta(minutes=interval_minutes)
    return runs


def main():
    parser = argparse.ArgumentParser(description="Scrape Casablanca Stock Exchange tables and append to CSV.")
    parser.add_argument("--url", required=True, help="URL of the market page to scrape")
    parser.add_argument("--output", default="casablanca.csv", help="CSV file to append data to")
    parser.add_argument("--row-selector", help="CSS selector for each row (optional)")
    parser.add_argument("--company-selector", help="CSS selector for company within the row (optional)")
    parser.add_argument("--price-selector", help="CSS selector for price within the row (optional)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval-minutes", type=int, default=15, help="Interval in minutes between runs when not using --once (default 15)")
    parser.add_argument("--tz", help="Time zone name, e.g. 'Africa/Casablanca' (optional)")
    parser.add_argument("--ramadan", action="store_true", help="Use Ramadan market hours window (earlier close)")
    parser.add_argument("--fresh", action="store_true", help="Delete existing output file before first run (fresh scrape)")
    parser.add_argument("--insecure", action="store_true", help="Skip SSL verification (insecure). Use only if needed to bypass certificate errors.")
    args = parser.parse_args()

    # If requested, delete the output file before the first run so we produce a fresh file with headers and correct encoding
    if args.fresh and os.path.isfile(args.output):
        try:
            os.remove(args.output)
            print(f"[main] removed existing output file: {args.output}")
        except Exception as exc:
            print(f"[main] could not remove existing file {args.output}: {exc}")

    # Run once or run through today's market window (quarters + 1 minute) then exit.
    if args.once:
        try:
            run_once(args.url, args.output, args.row_selector, args.company_selector, args.price_selector, args.tz, args.insecure)
        except Exception as exc:
            print(f"[error] run failed: {exc}")
            sys.exit(2)
        return

    # Choose market hours: normal vs Ramadan
    ramadan = getattr(args, "ramadan", False)
    # default market windows (HH:MM)
    if ramadan:
        nec_start = "10:00"  # approximate FO end in Ramadan
        nec_end = "13:20"
    else:
        nec_start = "09:16"
        nec_end = "16:01"

    # determine timezone to use for scheduling
    if args.tz and ZoneInfo is not None:
        tzinfo = ZoneInfo(args.tz)
    else:
        tzinfo = timezone(timedelta(hours=1))

    now_local = datetime.now(tzinfo)
    if now_local.weekday() >= 5:
        print("[main] Weekend detected; skipping scheduled runs.")
        return
    runs = generate_run_times_for_day(now_local, nec_start, nec_end, interval_minutes=max(1, args.interval_minutes), offset_minutes=1, tzinfo=tzinfo)
    # filter runs that are still in the future (or allow a small grace for immediate run)
    runs_to_do = [r for r in runs if r >= now_local]
    if not runs_to_do:
        print("[main] No remaining scheduled runs for today (market window passed). Exiting.")
        return

    print(f"[main] Scheduled runs for today: {len(runs_to_do)} runs, starting at {runs_to_do[0].isoformat()} until {runs_to_do[-1].isoformat()}")
    try:
        for run_dt in runs_to_do:
            now = datetime.now(tzinfo)
            wait_seconds = (run_dt - now).total_seconds()
            if wait_seconds > 0:
                print(f"[main] sleeping {int(wait_seconds)}s until next run at {run_dt.isoformat()}")
                time.sleep(wait_seconds)
            try:
                run_once(args.url, args.output, args.row_selector, args.company_selector, args.price_selector, args.tz, args.insecure)
            except Exception as exc:
                print(f"[error] run failed at {run_dt.isoformat()}: {exc}")
            # small sleep to avoid tight-loop misbehavior (shouldn't be needed)
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped by user.")


if __name__ == "__main__":
    main()
