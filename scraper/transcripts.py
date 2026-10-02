"""Download Doughboys transcripts from podscripts.co into a local cache.

The transcripts are the show's copyrighted content (machine-transcribed by
podscripts.co), so they stay on this machine: data/transcripts/ is
gitignored. Only derived counts (see scraper/phrases.py) get committed.

Saves:
  data/transcripts/index.json        [{slug, title, date}] from the listing pages
  data/transcripts/text/<slug>.txt.gz  one "HH:MM:SS<TAB>sentence" line per sentence

Already-downloaded transcripts are skipped, so re-running only fetches new
episodes. There are no speaker labels in the source.

Fetching is throttled to podscripts' limit of 10 requests a minute, so a
full download takes about an hour.

Usage: uv run python -m scraper.transcripts [--refresh-index]
"""

import gzip
import html
import json
import re
import sys
import time
from datetime import datetime

import requests

from scraper import DATA_DIR

BASE = "https://podscripts.co"
LISTING = BASE + "/podcasts/doughboys/"
HEADERS = {"User-Agent": "Doughboy-lytics/0.1 (fan project; github.com/rthunder27)"}
# podscripts allows 10 requests per minute (X-RateLimit-Limit), so stay under it.
DELAY = 6.5  # seconds between requests
BACKOFF = 65  # seconds to wait after a 429 Too Many Requests

TRANSCRIPTS = DATA_DIR / "transcripts"
TEXT_DIR = TRANSCRIPTS / "text"
INDEX = TRANSCRIPTS / "index.json"

ENTRY = re.compile(
    r'<h3><a href="/podcasts/doughboys/([^"]+)">(.*?)</a></h3>\s*'
    r'<span class="episode_date">Episode Date:\s*([^<]+)</span>', re.S)
PIECE = re.compile(
    r'<span class="pod_timestamp_indicator">Starting point is ([\d:]+)</span>'
    r'|<span id="sentenceid_\d+" class="[^"]*transcript-text[^"]*">(.*?)</span>', re.S)


def get(session, url):
    for attempt in range(5):
        resp = session.get(url, headers=HEADERS, timeout=60, allow_redirects=False)
        if resp.status_code == 200:
            if resp.headers.get("X-RateLimit-Remaining") == "0":
                time.sleep(BACKOFF)
            return resp.text
        if resp.status_code in (301, 302, 404):
            return None  # podscripts redirects unknown episodes to its home page
        wait = int(resp.headers.get("Retry-After", BACKOFF * (attempt + 1)))
        print(f"  {resp.status_code} on {url}; waiting {wait}s", file=sys.stderr)
        time.sleep(wait)
    resp.raise_for_status()


def fetch_index(session):
    """All (slug, title, date) entries across the paginated listing."""
    entries, page = [], 1
    while True:
        text = get(session, LISTING + (f"?page={page}" if page > 1 else ""))
        found = ENTRY.findall(text or "")
        if not found:
            break
        for slug, title, date in found:
            title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            try:
                date = datetime.strptime(date.strip(), "%B %d, %Y").date().isoformat()
            except ValueError:
                date = None
            entries.append({"slug": slug, "title": title, "date": date})
        print(f"  listing page {page}: {len(found)} episodes", file=sys.stderr)
        page += 1
        time.sleep(DELAY)
    return entries


def extract(page_html):
    """Transcript page -> list of (timestamp, sentence)."""
    lines, stamp = [], "00:00:00"
    for ts, sentence in PIECE.findall(page_html):
        if ts:
            stamp = ts
        else:
            text = html.unescape(re.sub(r"<[^>]+>", "", sentence))
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                lines.append((stamp, text))
    return lines


def main():
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    if "--refresh-index" in sys.argv or not INDEX.exists():
        entries = fetch_index(session)
        INDEX.write_text(json.dumps(entries, indent=1, ensure_ascii=False), "utf-8")
    entries = json.loads(INDEX.read_text("utf-8"))

    todo = [e for e in entries if not (TEXT_DIR / f"{e['slug']}.txt.gz").exists()]
    print(f"{len(entries)} episodes listed, {len(todo)} transcripts to fetch", file=sys.stderr)
    failed = []
    for n, e in enumerate(todo, 1):
        page = get(session, f"{LISTING}{e['slug']}")
        lines = extract(page) if page else []
        if not lines:
            failed.append(e["slug"])
        else:
            with gzip.open(TEXT_DIR / f"{e['slug']}.txt.gz", "wt", encoding="utf-8") as f:
                f.writelines(f"{ts}\t{text}\n" for ts, text in lines)
        if n % 25 == 0 or n == len(todo):
            print(f"  fetched {n}/{len(todo)}", file=sys.stderr)
        time.sleep(DELAY)
    if failed:
        print(f"{len(failed)} with no transcript: {', '.join(failed[:10])}"
              + (" ..." if len(failed) > 10 else ""), file=sys.stderr)


if __name__ == "__main__":
    main()
