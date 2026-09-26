"""Download raw wikitext from the Doughboys fandom wiki via the MediaWiki API.

Saves the Episodes master list and every episode page it links to into
data/raw/, so parsing can be re-run without hitting the wiki again.

Usage: uv run python -m scraper.fetch [--refresh]
  --refresh  re-download pages that are already cached
"""

import json
import sys
import time

import requests

from scraper import RAW_DIR
from scraper.wikitable import master_rows

API = "https://doughboys.fandom.com/api.php"
HEADERS = {"User-Agent": "Doughboy-lytics/0.1 (fan project; github.com/rthunder27)"}
BATCH = 50  # MediaWiki's max titles per query for anonymous users


def api_get(session, **params):
    params.update(format="json", formatversion=2)
    for attempt in range(3):
        resp = session.get(API, params=params, headers=HEADERS, timeout=30)
        if resp.ok:
            return resp.json()
        time.sleep(2 ** attempt)
    resp.raise_for_status()


def fetch_master(session):
    data = api_get(session, action="parse", page="Episodes", prop="wikitext")
    return data["parse"]["wikitext"]


def linked_titles(master_wikitext):
    """Episode page titles, in master-list order, from the Title column links."""
    titles = []
    for row in master_rows(master_wikitext):
        if row["page"] and row["page"] not in titles:
            titles.append(row["page"])
    return titles


def fetch_pages(session, titles):
    """Return {requested title: wikitext or None}, following redirects."""
    pages = {}
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        data = api_get(session, action="query", prop="revisions", rvprop="content",
                       rvslots="main", redirects=1, titles="|".join(chunk))
        query = data["query"]
        # Map requested titles through normalization and redirects to final titles.
        alias = {t: t for t in chunk}
        for step in ("normalized", "redirects"):
            for m in query.get(step, []):
                for req, cur in alias.items():
                    if cur == m["from"]:
                        alias[req] = m["to"]
        content = {}
        for p in query["pages"]:
            if "revisions" in p:
                content[p["title"]] = p["revisions"][0]["slots"]["main"]["content"]
        for req in chunk:
            pages[req] = content.get(alias[req])
        print(f"  fetched {min(i + BATCH, len(titles))}/{len(titles)}", file=sys.stderr)
        time.sleep(1)
    return pages


def main():
    refresh = "--refresh" in sys.argv
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    master = fetch_master(session)
    (RAW_DIR / "Episodes.wiki").write_text(master, encoding="utf-8")

    cache_path = RAW_DIR / "pages.json"
    cache = {} if refresh or not cache_path.exists() else json.loads(cache_path.read_text("utf-8"))
    wanted = [t for t in linked_titles(master) if t not in cache]
    print(f"{len(wanted)} pages to fetch ({len(cache)} cached)", file=sys.stderr)
    cache.update(fetch_pages(session, wanted))
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")

    missing = [t for t, w in cache.items() if w is None]
    print(f"done: {len(cache)} pages, {len(missing)} missing on wiki", file=sys.stderr)


if __name__ == "__main__":
    main()
