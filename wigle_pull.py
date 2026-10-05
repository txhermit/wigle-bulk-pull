#!/usr/bin/env python3
"""
wigle_pull.py -- Bulk-pull YOUR OWN WiGLE networks via the v2 API.

Why this exists: the WiGLE Android app's "DB backup" exports the local
collection buffer, not your archive. Rows are pruned as data syncs upstream,
so every dump differs and contains pre-dedup noise. The server-side API is
the source of truth.

Usage:
    export WIGLE_AUTH="<base64 token from wigle.net account page, 'Encoded for Use'>"
    python3 wigle_pull.py --out my_networks.csv

    # resume an interrupted pull (state kept in <out>.state.json):
    python3 wigle_pull.py --out my_networks.csv --resume

    # incremental: only networks updated since a date:
    python3 wigle_pull.py --out new_since_oct.csv --since 2026-10-01

Stdlib only -- no pip installs, runs anywhere with Python 3.
"""

import argparse
import base64
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.wigle.net/api/v2/network/search"

# Columns moved to the front of the CSV when present; anything else the API
# returns is appended in the order first seen. Unknown keys are never dropped.
PREFERRED_ORDER = [
    "netid", "ssid", "trilat", "trilong", "qos", "type",
    "firsttime", "lasttime", "lastupdt", "transid", "name",
    "comment", "wep", "bcmode",
]


def build_auth():
    encoded = os.environ.get("WIGLE_AUTH")
    if encoded:
        return encoded.strip()
    name = os.environ.get("WIGLE_API_NAME")
    token = os.environ.get("WIGLE_API_TOKEN")
    if name and token:
        return base64.b64encode(("%s:%s" % (name, token)).encode()).decode()
    sys.exit(
        "Set WIGLE_AUTH to the 'Encoded for Use' token from wigle.net/account\n"
        "or set WIGLE_API_NAME + WIGLE_API_TOKEN and the script will encode them."
    )


def api_get(params, auth, timeout=30):
    """GET one API page. Retries rate-limits and transient failures."""
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": "Basic " + auth,
        "Accept": "application/json",
        "User-Agent": "wigle-bulk-pull/1.0",
    })
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", 60))
                print("[!] rate limited (429), sleeping %ds" % wait, file=sys.stderr)
                time.sleep(wait)
                continue
            if 500 <= e.code < 600:
                wait = 2 ** attempt
                print("[!] HTTP %d, retrying in %ds" % (e.code, wait), file=sys.stderr)
                time.sleep(wait)
                continue
            body = e.read().decode(errors="replace")[:500]
            sys.exit("HTTP %d: %s" % (e.code, body))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            wait = 2 ** attempt
            print("[!] network error (%s), retrying in %ds" % (e, wait), file=sys.stderr)
            time.sleep(wait)
    sys.exit("gave up after retries -- rerun with --resume")


def main():
    ap = argparse.ArgumentParser(description="Bulk-pull your WiGLE networks to CSV.")
    ap.add_argument("--out", required=True, help="output CSV path")
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help="incremental: only networks updated since this date")
    ap.add_argument("--resume", action="store_true",
                    help="resume from <out>.state.json instead of starting over")
    ap.add_argument("--delay", type=float, default=0.5,
                    help="seconds between requests (default 0.5)")
    ap.add_argument("--page-size", type=int, default=100,
                    help="results per request (default 100)")
    args = ap.parse_args()

    auth = build_auth()
    state_path = args.out + ".state.json"

    search_after, written = None, 0
    mode = "w"
    if args.resume and os.path.exists(state_path) and os.path.exists(args.out):
        st = json.load(open(state_path))
        search_after, written = st.get("searchAfter"), st.get("written", 0)
        mode = "a"
        print("[*] resuming: %d rows already in %s" % (written, args.out),
              file=sys.stderr)

    params = {"onlymine": "true", "resultsPerPage": args.page_size}
    if args.since:
        params["lastupdt"] = args.since.replace("-", "")
    if search_after:
        params["searchAfter"] = search_after

    writer, fieldnames, total = None, None, None
    seen_cursors = set()
    out_f = open(args.out, mode, newline="", encoding="utf-8")
    try:
        while True:
            data = api_get(params, auth)
            if not data.get("success", True):
                sys.exit("API error: %s" % data.get("message", data))
            results = data.get("results", [])
            if total is None:
                total = data.get("totalResults")
                print("[*] totalResults=%s" % total, file=sys.stderr)
                print("[*] compare against the 'discovered' count on your "
                      "WiGLE stats page", file=sys.stderr)
            if writer is None and results:
                keys = list(results[0].keys())
                fieldnames = ([k for k in PREFERRED_ORDER if k in keys]
                              + [k for k in keys if k not in PREFERRED_ORDER])
                writer = csv.DictWriter(out_f, fieldnames=fieldnames,
                                        extrasaction="ignore")
                if mode == "w":
                    writer.writeheader()
            for row in results:
                writer.writerow(row)
                written += 1
            out_f.flush()

            nxt = data.get("searchAfter") or data.get("search_after")
            json.dump({"searchAfter": nxt, "written": written,
                       "totalResults": total}, open(state_path, "w"))
            print("[*] %d/%s rows" % (written, total), file=sys.stderr)

            if not nxt or not results:
                break
            if nxt in seen_cursors:
                print("[!] pagination cursor repeated -- stopping to avoid a "
                      "loop. Inspect the last API response.", file=sys.stderr)
                break
            seen_cursors.add(nxt)
            params["searchAfter"] = nxt
            time.sleep(args.delay)
    finally:
        out_f.close()
    print("[+] done: %d rows -> %s" % (written, args.out), file=sys.stderr)


if __name__ == "__main__":
    main()
