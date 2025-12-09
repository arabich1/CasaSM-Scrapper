#!/usr/bin/env python3

"""
casablanca_scraper.py

Scraper for: https://www.casablanca-bourse.com/fr/live-market/marche-actions-groupement

Saves CSV rows: category, <all table columns...>, date, time, timestamp_iso

Dependencies:
  pip install requests beautifulsoup4 lxml certifi

Run once example:
  python casablanca_scraper.py --url "https://www.casablanca-bourse.com/fr/live-market/marche-actions-groupement" --output cse_groupement.csv --once
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


def find_category_for_table(tbl) -> str:
    for prev in tbl.find_all_previous():
        if prev.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            txt = cleanup_text(prev.get_text())
            if txt:
                return txt.replace(",", "")
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
    header = list(fieldnames) + ["date", "time", "timestamp_iso"]
    exists = os.path.isfile(path)
    enc = "utf-8-sig" if not exists else "utf-8"
    with open(path, "a", newline="", encoding=enc) as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(header)
        for r in rows:
            row = [r.get(fn, "") for fn in fieldnames]
            row.extend([local_date, local_time, ts_iso])
            writer.writerow(row)


def run_once(url: str, output: str, tz_name: Optional[str] = None, insecure: bool = False) -> int:
    html = fetch_html(url, insecure=insecure)
    soup = BeautifulSoup(html, "lxml")

    now_utc = datetime.now(timezone.utc)
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
        local_dt = now_utc.astimezone(timezone(timedelta(hours=1)))

    ts_iso = local_dt.isoformat()
    local_date = local_dt.strftime("%Y-%m-%d")
    local_time = local_dt.strftime("%H:%M:%S")

    extracted_rows: List[Dict[str, str]] = []
    fieldnames: List[str] = ["category"]

    header_keywords = ["dernier", "dernier cours", "last", "prix", "cours", "valeur"]
    tables = soup.find_all("table")
    for tbl in tables:
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
            continue

        category = find_category_for_table(tbl)

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

    write_dict_rows_to_csv(output, extracted_rows, fieldnames, ts_iso, local_date, local_time)
    print(f"[run_once] wrote {len(extracted_rows)} rows to {output} (timestamp {ts_iso})")
    return len(extracted_rows)


def main():
    parser = argparse.ArgumentParser(description="Scrape Casablanca Stock Exchange tables and append to CSV.")
    parser.add_argument("--url", required=True, help="URL of the market page to scrape")
    parser.add_argument("--output", default="cse_groupement.csv", help="CSV file to append data to")
    parser.add_argument("--once", action="store_true", help="Run once and exit (default mode)")
    parser.add_argument("--tz", help="Time zone name, e.g. 'Africa/Casablanca' (optional)")
    parser.add_argument("--fresh", action="store_true", help="Delete existing output file before first run (fresh scrape)")
    parser.add_argument("--insecure", action="store_true", help="Skip SSL verification (insecure).")
    args = parser.parse_args()

    if args.fresh and os.path.isfile(args.output):
        try:
            os.remove(args.output)
            print(f"[main] removed existing output file: {args.output}")
        except Exception as exc:
            print(f"[main] could not remove existing file {args.output}: {exc}")

    try:
        run_once(args.url, args.output, args.tz, args.insecure)
    except Exception as exc:
        print(f"[error] run failed: {exc}")
        sys.exit(2)


if __name__ == "__main__":
    main()
