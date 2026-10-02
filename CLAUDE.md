# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Doughboy-lytics builds a scatterplot of the fork ratings Nick and Mitch give the restaurants covered on The Doughboys podcast (they asked for one on a recent episode). See README.md for the latest updates and context, and this conversation for the basic project plan: https://claude.ai/share/3fc93090-1789-4692-b4e9-2bbf62228e42

## Commands

Python 3.12 managed with uv (the system `python3` is 3.6, too old).

```bash
uv sync                          # install deps
uv run python -m scraper.fetch   # download wikitext into data/raw/ (cached; --refresh to redo)
uv run python -m scraper.parse   # data/raw/ + data/overrides.csv -> episodes.csv, ratings.csv, review.csv
uv run python -m scraper.transcripts  # download podscripts.co transcripts into data/transcripts/ (local only; about 1 hour)
uv run python -m scraper.phrases      # transcripts + data/phrases.csv -> phrase_counts.csv, phrase_candidates.csv (about 3 minutes; --no-candidates is faster)
uv run streamlit run app.py      # the app, at http://localhost:8501
```

- **Smoke test**: there's no test suite. `streamlit.testing.v1.AppTest.from_file("app.py").run()` catches exceptions, and `at.session_state["version"]` / `["live"]` exercise the keyed filters.
- **pyarrow pin and deployment**: `pyproject.toml` pins `pyarrow<21` only because this WSL machine has glibc 2.27, which newer pyarrow wheels don't support. Streamlit Community Cloud installs from `uv.lock` if the repo has one (before `requirements.txt`), and it runs Python 3.14, where pyarrow 20 has no wheel. So `uv.lock` is gitignored and Cloud uses the unpinned `requirements.txt`. Keep the two files in step when adding dependencies. Check a change with `uv pip compile requirements.txt --python-version 3.14 --python-platform x86_64-manylinux_2_28 --only-binary :all:`. Deploy logs go in the gitignored `temp/`.
- **Browser screenshots don't work here**: Playwright also needs a newer glibc. To look at a chart, take the figure spec from AppTest, decode the `{bdata, dtype}` arrays, and render it with `kaleido==0.2.1`'s `PlotlyScope`.

`parse` never touches the network, so iterate on parsing rules freely; only run `fetch` when new episodes drop.

## Pipeline

The work is staged so the scraped data can be checked by eye before building the app.

1. **Fetch** (`scraper/fetch.py`): uses the MediaWiki API, not the page HTML. It gets the `Episodes` master list, then every page linked from its Title column, 50 per `action=query` call. The master list only has the combined fork score, so each host's rating comes from the episode page's "... rating" section.
2. **Parse** (`scraper/parse.py`, `scraper/wikitable.py`):
   - The master list is two wikitables with six columns: #, Title, Fork Score, Date, Accolades, Notes.
   - The ratings table's heading and unit change with the episode's theme ("Spoon rating", "10 carts"). The rating column is chosen from the header (`adjusted` > `overall rating` > `rating`).
   - `wikitable.table_rows` expands `rowspan` cells.
   - Host detection (`host_roles()`): themed episodes rename the hosts in the ratings table ("Joker Wiger", "The Batspoonman", "Mr. Slice"). The real names win; otherwise `HOST_NICKNAMES` patterns apply (Wiger/Wigru/Wine-ger means Nick; Mitchell/Mitch/spoon/Mr. Slice means Mitch), but only when exactly one rater matches and the name doesn't start with "Mrs." (Mrs. Mitchell is a guest). Anything else gets a `role` override, e.g. "The Dread Podcaster" (Nick) in the pirate episodes. Rows whose name contains "shared" are shared orders with no score, and are skipped. Trailing `*` footnote marks are stripped from names.
   - Struck-out old scores and `<sup>` footnote markers are dropped.
   - Episodes rated out of 10 are detected because the wiki's score is half their average, and are halved.
3. **Overrides** (`scraper/overrides.py`, `data/overrides.csv`): keyed by wiki page title, because episode numbers repeat (445 Doubles are just "DD"). A blank `rater` fixes an episode field; otherwise it fixes that rater's row. Never edit the generated CSVs by hand.
4. **Categories** (`data/categories.csv`): hand-curated, one row per parsed restaurant name, with a `chain` (canonical name that merges variants like "Papa Johns"/"Papa John's" or "Popeyes Wings"/"Popeyes") and one food `category`. `parse` joins both into `episodes.csv` and prints any scored restaurant that's missing, so new episodes need a row added here. `check=yes` marks drafts the user hasn't confirmed. The wiki's own `[[Category:...]]` food tags describe what was ordered, not the restaurant type, so they weren't usable for this.
5. **Review** (`data/review.csv`): lists scored episodes whose parsed average is more than 0.05 away from the wiki's fork score. The usual causes are later score revisions the wiki's score reflects, joke units, and odd tables. Resolve them with overrides.
6. **Transcripts** (`scraper/transcripts.py`, `scraper/phrases.py`): podscripts.co has machine-made transcripts of about 580 main-feed episodes.
   - **Local only:** they're copyrighted, so they stay in the gitignored `data/transcripts/`. Only derived counts are committed: `transcript_episodes.csv`, `phrase_counts.csv` and `phrase_candidates.csv`.
   - **Rate limit:** podscripts allows 10 requests a minute (`X-RateLimit-Limit`); the fetcher waits 6.5 s between requests and backs off on 429.
   - **No speaker labels,** so counts are per episode, not per host.
   - **Coverage gap:** podscripts has nothing from about September 2025 to May 2026.
   - **Episode matching:** `match_episodes()` uses cleaned titles first (`title_keys()` strips "UNLOCKED!", "Doughboys Double NN -", theme prefixes before a colon, "(LIVE)" and "Alias aka Name" credits), then close titles, then the release date if the titles also share a real word. UNLOCKED re-releases are how 32 Doubles get transcripts. One transcript is kept per wiki episode, and the rest are marked `duplicate`.
   - **Boilerplate:** sentences of 6+ words that appear verbatim in 3+ episodes (ads, the Headgum intro, Patreon plugs) are dropped before anything is counted.
   - **Phrase list:** `data/phrases.csv` is user-editable (`phrase`, `"|"`-separated `variants`, `note`). Matching is whole-word and ignores case and punctuation. Variants matter because transcription garbles things: "platinum play club" is more common than "plate", and "this show sucks" also covers "the podcast is bad" and similar.
   - **Candidates:** `phrase_candidates.csv` lists words far more common than in general English (`wordfreq`) and phrases with high PMI that recur across episodes, ranked separately for each length (1–4 words), with ad copy and misspellings of Wiger/Doughboys filtered out. It's a menu for picking phrases, not ground truth.
7. **App** (`app.py`): Streamlit with Plotly. It reads `data/episodes.csv` for episode info and `data/ratings.csv` for scores. The hosting target is still undecided; Streamlit Community Cloud needs `app.py`, `requirements.txt` and `data/`.

## Data conventions

- **`episodes.csv`**: one row per master-list entry, including Doubles, Bread Cast and Snack Pack (`kind`). Contains:
  - `fork_score`: the wiki's combined score.
  - `nick` and `mitch`: each host's rating.
  - `guest_avg`: the guests' average rating.
  - `date`: the release date, in ISO format.
  - `live` and `live_source`: whether it was a live show, and why the parser thinks so (🎤 accolade, title, notes, or episode page).
  - `live_type`: `in person`, `livestream` or `watchalong`.
  - `live_city`: where it was recorded, as "City, ST". It comes from the notes ("live in …") or the page's "Recorded live … in …" line, and is normalized through `CITY_ALIASES` and `STATES` in `parse.py`. It is blank for livestreams, watchalongs, and the few in-person shows whose page gives no location.
- **`ratings.csv`**: one row per rater per episode, with `rating_raw` next to the cleaned numbers. It repeats the episode's number, restaurant, date and live columns, so it can be plotted without a join.
- **Original vs. revised scores**:
  - `rating_original` is the score given on the episode. Changes made during the episode itself count as original.
  - `rating` is the revised (current) score, and `revised` flags the rows where the two differ.
  - `episodes.csv` has `nick`, `mitch`, `guest_avg` and `avg` (revised), each with an `_original` twin, plus an episode-level `revised` flag.
  - Struck-out cells and "revised to X" are parsed automatically. Revisions mentioned only in prose are overrides: set `rating` when the cell shows the original, or `rating_original` when it shows the revised score. Use the `score` override field (which sets both) for parsing fixes that aren't revisions.
  - The wiki's `fork_score` is inconsistent: sometimes it reflects revisions and sometimes it doesn't, so `review.csv` accepts either average.
- **Food categories** (13, broad on purpose so each has enough episodes): Burgers & Hot Dogs, Pizza & Italian, Chicken, Mexican, Sandwiches & Subs, Asian, Mediterranean, Seafood, American & Casual Dining (including steakhouses, barbecue and sports bars), Breakfast & Diners, Coffee, Bakery & Sweets, Healthy & Juice (salads, bowls, juice, vegan), Other (grocery and convenience stores, theme parks, theaters, produce episodes, frozen food). Seafood (9 episodes) and Mediterranean (7) are small.
- **Unparseable values**: stay NaN, with a reason in `rating_note` or `fork_score_note` (e.g. "multiple ratings", "competition: Winner: X" for Munch Madness). Never use sentinels like -1.
- **Off-scale ratings**: `off_scale` and `off_scale_original` are true for ratings outside 0 to 5, including 6+ and Carrows' -1. The number itself is kept as given.
- **Live shows**: the app must be able to filter on `live`, and on `live_type` too, so livestreams can be counted as live or not.

## App

- **Filters**: one row above the charts.
  - Score version (Revised by default; it switches to the `_original` columns).
  - Year range.
  - Live: All, Live only or Studio only, plus a "count livestreams & watchalongs as live" toggle.
  - Episode types: All, Main episodes or Doubles, in the same button style as the live filter. Only main episodes and Doubles are loaded; the Bread Cast (one rated episode) and other side feeds are left out of the app, though they stay in the CSVs.
  - Food category: a popover checklist (`category_filter()`). The button reads "Categories: all / none / <one name> / N of 13". Inside are All and None buttons, then one checkbox per category, sorted by episode count with the count shown. State lives in `st.session_state["cat:<category>"]`, all on by default. The user specifically wanted checkboxes with All/None, not a multi-select dropdown.
  - Search: restaurant, chain and guest names, matched word by word after `normalize()`. That lowercases, strips accents and apostrophes, treats doughnut and donut as the same word, and drops a single plural "s", applied the same way to the query and the names. It is never a plain substring match: the user searched "Voodoo Donuts" and the wiki says "Voodoo Doughnut".
- **Tabs**:
  - **Nick vs. Mitch**: a square scatter, one dot per episode, jittered, with a y=x line and a "biggest disagreements" list beside it.
  - **Over time**: Nick, Mitch and guests, with 20-episode rolling averages.
  - **Words**: up to 5 phrases from `phrase_counts.csv`, shown as rate per 10k words per episode, with 25-episode rolling lines that break across coverage gaps of more than 60 days. A summary table shows total uses, share of episodes, first and peak year, r with the episode's average score, and the episode where it was used most. An expander lists the signature words and phrases. The tab respects all filters, and only shows episodes with a matched transcript.
  - **Table**: links to each episode's wiki page.
- **Caching**: every `@st.cache_data` loader takes `data_stamp()` (the CSVs' modification times) as an argument, so a running app reloads rebuilt CSVs. Keep passing it to any new cached function that reads the data.
- **Off-scale scores**: always capped at −1 and 6 (`CAP`), with no toggle. This is the user's call. Capping happens per rating, before averaging: the app builds its own per-episode scores from `ratings.csv` (`episode_scores()`), not from the precomputed averages in `episodes.csv`. The hover says what was capped (e.g. "Nicole Byer's 10 capped to 6"). In practice that's the only score beyond −1 and 6.
- **Hover notes**: `episode_scores()` builds them from `ratings.csv`: revisions ("✏️ Mitch: 5 on the episode → 3 later", or "→ thrown out later") and capping ("✂️ Nicole Byer's 10 capped to 6"). Don't fall back to the yes/no `revised` flag in `episodes.csv`.
- **Headline numbers**: two rows. First: episodes, Nick's, Mitch's and the guests' averages (the median and variance were tried and dropped as distracting). Second: one tile per pair (Nick & Mitch, Nick & guests, Mitch & guests) showing Pearson r and the exact-agreement rate. Guest comparisons pair each individual guest rating (`guest_ratings()`) with the host's score for that episode, never the episode's guest average, so agreement means the same thing as for the hosts. r shows "–" with fewer than 3 scores or no variation. Everything uses capped scores for the selected version.
- **Live shows**: in the Nick vs. Mitch scatter, colored red, with studio episodes violet (the user's choice over marker shapes). The pair was validated separately, so it doesn't clash with Nick's blue or Mitch's orange. The Over time chart keeps diamonds for live shows, because color there identifies Nick, Mitch and the guests (the user wants it that way). Two gray legend-only entries (● Studio episode, ◆ Live show) explain the shapes, and `legend_traceorder="normal"` keeps the legend on one row.
- **Grid lines**: Streamlit's chart theme hides vertical grid lines, so `style()` sets `showgrid=True` on x.
- **Color**: validated categorical slots 1-3 (blue for Nick, orange for Mitch, aqua for guests), with light and dark variants. Scatter forms only validate three all-pairs colors, so don't color by restaurant or chain (there are 415 restaurants); use filters instead.
- **Credit footer**: required, see below.

## Credit

The data comes from the Doughboys Wiki (https://doughboys.fandom.com), which is licensed CC BY-SA. The README credits and thanks its editors. Any app or chart must show visible credit with a link to the wiki, and the derived data stays CC BY-SA.

## Working in this repo

- Ask for clarification when in doubt. Asking is encouraged.
- Record major design decisions and other updates from each session in your memory file.
