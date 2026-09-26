"""Turn the cached wikitext in data/raw/ into clean CSVs.

Outputs (all in data/):
  episodes.csv  one row per master-list entry, with the combined fork score,
                live flag, and each host's individual rating
  ratings.csv   one row per rater per episode (hosts and guests)
  review.csv    episodes whose parsed ratings don't average to the wiki's
                fork score, or that have no parseable ratings; check by eye,
                then fix via data/overrides.csv

Every cleaned number keeps its raw wiki text alongside it. Values that can't
be parsed are left blank with a *_note explaining why.

Usage: uv run python -m scraper.parse
"""

import json
import re
from datetime import datetime

import pandas as pd

from scraper import DATA_DIR, RAW_DIR
from scraper.overrides import apply_overrides
from scraper.wikitable import master_rows, plain, table_rows

HOSTS = {"Nick Wiger": "nick", "Mike Mitchell": "mitch"}
SCALE = (0, 5)
NUM = r"-?\d*\.?\d+"

# ---------------------------------------------------------------- episodes


def episode_kind(number):
    n = number.rstrip("!").strip()
    if n.isdigit():
        return "main"
    for prefix, kind in (("DD", "double"), ("BC", "bread_cast"), ("SP", "snack_pack")):
        if n.startswith(prefix):
            return kind
    return "other"


def parse_date(text):
    text = re.sub(r"(\d)\.\s*(\d{4})", r"\1, \2", re.sub(r"\s+", " ", plain(text)))
    try:
        return datetime.strptime(text, "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def split_title(title):
    """'Taco Bell 2 with Jon Gabrus' -> ('Taco Bell', 'Jon Gabrus')."""
    title = re.sub(r"\s+", " ", title.replace("’", "'").replace("‘", "'"))
    restaurant, _, guests = title.partition(" with ")
    restaurant = re.sub(r"\s+\d+\b.*$", "", restaurant)  # drop visit number and subtitle
    guests = re.sub(r"\s*\((live|LIVE)[^)]*\)\s*$", "", guests)
    return restaurant.strip(), guests.strip()


def parse_fork_score(raw):
    text = plain(raw)
    if re.fullmatch(r"\d\.\d+", text):
        return float(text), ""
    if not text or text == "🔓":
        return None, "no score"
    if text.lower().startswith("winner"):
        return None, "competition: " + text
    return None, "unparseable"


def live_source(row, page_text):
    """Why this episode counts as live ('' if it doesn't)."""
    if "🎤" in row["accolades"]:
        return "🎤 accolade"
    if re.search(r"\blive\b", row["page"] or plain(row["title"]), re.I):
        return "title"
    if re.search(r"\blive\b", plain(row["notes"]), re.I):
        return "notes"
    if page_text and re.search(r"\b(recorded|taped) live\b", page_text, re.I):
        return "episode page"
    return ""


STATES = {
    "Alabama": "AL", "Arizona": "AZ", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Florida": "FL", "Georgia": "GA", "Illinois": "IL",
    "Iowa": "IA", "Massachusetts": "MA", "Mass": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Nebraska": "NE", "New Jersey": "NJ", "New York": "NY",
    "North Carolina": "NC", "Ohio": "OH", "Oregon": "OR", "Tennessee": "TN",
    "Texas": "TX", "Utah": "UT", "Washington": "WA", "Wisconsin": "WI",
    "British Columbia": "BC", "Ontario": "ON", "Saskatchewan": "SK",
}
# Bare names, nicknames and venues -> "City, ST".
CITY_ALIASES = {
    "Los Angeles": "Los Angeles, CA", "L.A.": "Los Angeles, CA", "LA": "Los Angeles, CA",
    "San Francisco": "San Francisco, CA", "SF": "San Francisco, CA",
    "SF Sketchfest": "San Francisco, CA", "New York City": "New York, NY",
    "New York City, NY": "New York, NY", "NYC": "New York, NY", "New York": "New York, NY",
    "Chicago": "Chicago, IL", "Boston": "Boston, MA", "Philadelphia": "Philadelphia, PA",
    "Washington": "Washington, DC", "Washington, D.C.": "Washington, DC",
    "Portland": "Portland, OR", "Seattle": "Seattle, WA", "Detroit": "Detroit, MI",
    "Denver": "Denver, CO", "Austin": "Austin, TX", "Vancouver": "Vancouver, BC",
    "Toronto": "Toronto, ON", "Brea Improv": "Brea, CA", "L.A. Podfest": "Los Angeles, CA",
}
WORDS = r"(?:[A-Z][\w.'’-]*\s?)+"
PLACE = rf"({WORDS}(?:in {WORDS})?(?:,\s*[A-Z][\w.]*(?:\s[A-Z][\w.]*)?)?)"


def normalize_city(place):
    place = re.sub(r"\s+", " ", place).strip(" .,;")
    if place not in CITY_ALIASES:
        place = re.split(r"\.\s+(?=[A-Z][a-z])", place)[0]  # "Philadelphia. Also with ..."
    place = re.sub(r"\s+(on|at|as|during)$", "", place)
    place = re.sub(r"^(the|a)\s+", "", place.split(" in ")[-1])  # "Festival in North Adams, MA"
    if place in CITY_ALIASES:
        return CITY_ALIASES[place]
    city, _, state = place.partition(",")
    state = state.strip(" .")
    state = STATES.get(state, state)
    return CITY_ALIASES.get(f"{city}, {state}", f"{city}, {state}" if state else city)


def live_type(row, page_text):
    """'watchalong', 'livestream' or 'in person' (only meaningful for live episodes)."""
    text = plain(row["notes"])
    if page_text:
        text += " " + " ".join(re.findall(r"[^.\n]*\brecorded\b[^.\n]*", page_text, re.I))
    if re.search(r"watchalong|live commentary", text, re.I):
        return "watchalong"
    if re.search(r"live ?stream|webstream|zoom|digital experience|twitch", text, re.I):
        return "livestream"
    return "in person"


def live_city(row, page_text):
    """Best guess at where a live episode was recorded, as 'City, ST' (or '')."""
    candidates = [plain(row["notes"]), row["page"] or ""]
    if page_text:
        body = re.sub(r"\{\{InfoboxEp.*?\}\}", "", page_text, flags=re.S)
        candidates += [plain(m) for m in re.findall(r"[Rr]ecorded[^.\n]{0,80}", body)]
    for text in candidates:
        m = re.search(rf"\b(?i:live) (?:in|from|at) {PLACE}", text)
        if m:
            place = re.split(r"\s(?:at|on|as|during)\s", m.group(1))[0]
            if place.strip(" .") in CITY_ALIASES or "," in place or text is candidates[0]:
                return normalize_city(place)
        m = re.search(rf"\bin {PLACE}", text) if text.startswith(("Recorded", "recorded")) else None
        if m:
            return normalize_city(re.split(r"\s(?:on|at)\s", m.group(1))[0])
    return ""


# ---------------------------------------------------------------- ratings


def rating_section(page_text):
    """The body of the first '== ... rating(s) ==' section, or None."""
    m = re.search(r"^==\s*[^=\n]*\bratings?\b[^=\n]*==\s*$(.*?)(?=^==[^=]|\Z)",
                  page_text, flags=re.S | re.M | re.I)
    return m.group(1) if m else None


def rating_column(headers):
    """Index of the column holding the overall rating, given lowercase headers."""
    for want in ("adjusted", "overall rating", "rating", "fork rating"):
        if want in headers:
            return headers.index(want)
    rated = [i for i, h in enumerate(headers) if "rating" in h]
    return rated[-1] if rated else len(headers) - 1


def clean_cell(raw):
    """Drop refs and struck-out text (old scores), then strip markup."""
    raw = re.sub(r"<ref[^>]*/>|<ref.*?</ref>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"<(s|del|strike|sup)>.*?</\1>", "", raw, flags=re.S | re.I)
    return re.sub(r"[ \t]+", " ", plain(raw)).strip()


def struck_value(raw):
    """The number in a cell's struck-out text (an earlier score), or None."""
    m = re.search(r"<(s|del|strike)>(.*?)</\1>", raw, flags=re.S | re.I)
    n = re.search(rf"(?<![\w.]){NUM}", m.group(2)) if m else None
    return float(n.group(0)) if n else None


def parse_rating(raw):
    """Raw rating cell -> (revised rating, original rating, note).

    The revised rating is the one the cell ends up at; the original is the
    struck-out or "revised to"-replaced score when the cell records one,
    otherwise the same value. Either may be None when unparseable.
    """
    value, note = _parse_rating_text(clean_cell(raw))
    original = struck_value(raw)
    m = re.search(rf"^\s*({NUM}).*revised to", clean_cell(raw), re.S | re.I)
    if m:
        original = float(m.group(1))
    return value, value if original is None else original, note


def _parse_rating_text(text):
    notes = []
    if "*" in text:
        text = text.replace("*", "").strip()
        notes.append("footnote")
    if not text:
        return None, "no rating"
    if text.strip("-? ") == "" or text.lower() == "incomplete":
        return None, "no rating: " + text

    m = re.search(rf"revised to ({NUM})", text, re.I)
    if m:
        value = float(m.group(1))
        notes.append("revised: " + text.split("\n")[0])
    elif m := re.search(rf"=\s*({NUM})\s*forks?", text, re.I):
        value = float(m.group(1))
        notes.append("converted: " + text)
    else:
        numbers = re.findall(rf"(?<![\w.]){NUM}", text)
        if not numbers:
            return None, "unparseable: " + text
        lines = [ln.strip(" *") for ln in text.split("\n") if re.search(r"\d", ln)]
        fork_lines = [ln for ln in lines if re.search(r"\bforks?\b", ln, re.I)]
        if len(lines) > 1 and len(fork_lines) == 1:  # e.g. "4 forks" + "3 dinner plates"
            notes.append("text: " + text.replace("\n", "; "))
            text, numbers = fork_lines[0], re.findall(rf"(?<![\w.]){NUM}", fork_lines[0])
        elif len(lines) > 1:
            return None, "multiple ratings: " + text.replace("\n", "; ")
        m = re.match(rf"\s*({NUM})\+?\s*(.*)", text, re.S)
        if not m:
            return None, "unparseable: " + text
        value = float(m.group(1))
        rest = m.group(2).strip()
        if not notes and (len(numbers) > 1 or not re.fullmatch(r"forks?", rest, re.I)):
            notes.append("text: " + text)
    return value, "; ".join(notes)


def parse_ratings(page_text):
    """Yield (rater, raw_cell) from an episode page's rating table."""
    section = rating_section(page_text or "")
    if not section:
        return
    table = re.search(r"^\{\|.*?^\|\}", section, flags=re.S | re.M)
    if not table:
        return
    headers = [plain(h).lower() for h in re.findall(r"^!(.*)$", table.group(0), re.M)]
    headers = [re.sub(r"\s+", " ", h).strip() for h in headers]
    col = rating_column(headers) if headers else None
    for cells in table_rows(table.group(0)):
        if col is None:
            col = len(cells) - 1
        rater = re.sub(r"\s+", " ", plain(cells[0])).strip()
        if not rater or rater.lower() == "shared" or col >= len(cells):
            continue
        yield rater, cells[col].strip()


def rescale_ten_point(ratings, episodes):
    """Halve ratings for episodes rated out of 10 (e.g. Grocery Store Month's
    "10 carts"), detected by the wiki's fork score being half their average."""
    score = episodes.dropna(subset=["fork_score"]).set_index("page").fork_score
    avg = ratings.groupby("page").rating.mean()
    target = score.reindex(avg.index)
    ten_point = avg.index[((avg / 2 - target).abs() <= 0.05) & ((avg - target).abs() > 0.05)]
    mask = ratings.page.isin(ten_point)
    ratings.loc[mask, ["rating", "rating_original"]] /= 2
    ratings.loc[mask, "rating_note"] = ("rescaled from 10-point scale; "
                                        + ratings.loc[mask, "rating_note"]).str.rstrip("; ")
    return ratings


def episode_summary(ratings, col, suffix):
    """Per-page nick, mitch, guest_avg and avg (all raters) from one rating column."""
    hosts = ratings[ratings.role != "guest"].pivot_table(
        index="page", columns="role", values=col, aggfunc="first", dropna=False)
    hosts = hosts.reindex(columns=["nick", "mitch"])
    guests = ratings[ratings.role == "guest"].groupby("page")[col].mean().rename("guest_avg")
    avg = ratings.groupby("page")[col].mean().rename("avg")
    out = hosts.join([guests, avg], how="outer")
    return out.add_suffix(suffix)


# ---------------------------------------------------------------- main


def build():
    master = (RAW_DIR / "Episodes.wiki").read_text("utf-8")
    pages = json.loads((RAW_DIR / "pages.json").read_text("utf-8"))

    episodes, ratings = [], []
    for order, row in enumerate(master_rows(master)):
        page_text = pages.get(row["page"]) if row["page"] else None
        title = plain(row["title"]).replace("’", "'").replace("‘", "'")
        restaurant, guests = split_title(title)
        score, score_note = parse_fork_score(row["fork_score"])
        number = row["number"].rstrip("!").strip()
        kind = episode_kind(number)
        episodes.append({
            "order": order,
            "number": number,
            "episode_num": int(number) if kind == "main" else None,
            "kind": kind,
            "title": title,
            "restaurant": restaurant,
            "guests": guests,
            "date": parse_date(row["date"]),
            "fork_score_raw": row["fork_score"],
            "fork_score": score,
            "fork_score_note": score_note,
            "live_source": live_source(row, page_text),
            "live_type": live_type(row, page_text),
            "live_city": live_city(row, page_text),
            "accolades": plain(row["accolades"]),
            "notes": plain(row["notes"]),
            "page": row["page"],
        })
        if score is None:  # individual ratings only matter for scored episodes
            continue
        for rater, raw in parse_ratings(page_text):
            value, original, note = parse_rating(raw)
            ratings.append({
                "page": row["page"],
                "rater": rater,
                "role": HOSTS.get(rater, "guest"),
                "rating_raw": raw,
                "rating_original": original,
                "rating": value,
                "rating_note": note,
            })

    episodes = pd.DataFrame(episodes).astype({"episode_num": "Int64"})
    ratings = rescale_ten_point(pd.DataFrame(ratings), episodes)
    episodes, ratings = apply_overrides(episodes, ratings, DATA_DIR / "overrides.csv")
    episodes["live"] = episodes["live_source"].fillna("") != ""
    episodes.loc[~episodes.live, ["live_type", "live_city"]] = ""

    # "rating" is the revised (current) score; "rating_original" what was given
    # on the episode. Both are kept so the app can switch between them.
    ratings["revised"] = ~((ratings.rating == ratings.rating_original)
                           | (ratings.rating.isna() & ratings.rating_original.isna()))
    ratings["off_scale"] = ratings.rating.notna() & ~ratings.rating.between(*SCALE)
    ratings["off_scale_original"] = (ratings.rating_original.notna()
                                     & ~ratings.rating_original.between(*SCALE))

    episodes = episodes.merge(episode_summary(ratings, "rating", ""), how="left",
                              left_on="page", right_index=True)
    episodes = episodes.merge(episode_summary(ratings, "rating_original", "_original"),
                              how="left", left_on="page", right_index=True)
    counts = ratings.groupby("page").agg(n_raters=("rater", "size"), n_parsed=("rating", "count"),
                                         revised=("revised", "any"))
    episodes = episodes.merge(counts, how="left", left_on="page", right_index=True)
    episodes["revised"] = episodes.revised.astype("boolean").fillna(False)

    # Sanity check against the wiki's combined score, which sometimes reflects
    # later revisions and sometimes doesn't, so either average may match.
    scored = episodes[episodes.fork_score.notna()]
    diff = pd.concat([(scored.avg - scored.fork_score).abs(),
                      (scored.avg_original - scored.fork_score).abs()], axis=1).min(axis=1)
    review = scored[scored.avg.isna() | (diff > 0.05)]
    review = review.assign(diff=diff[review.index].round(2))

    DATA_DIR.mkdir(exist_ok=True)
    episodes.drop(columns="order").to_csv(DATA_DIR / "episodes.csv", index=False)
    episode_cols = ["number", "restaurant", "date", "live", "live_type", "live_city"]
    ratings = ratings.merge(
        episodes.drop_duplicates("page").set_index("page")[episode_cols],
        how="left", left_on="page", right_index=True)
    ratings[["page", *episode_cols] + [c for c in ratings if c not in episode_cols and c != "page"]] \
        .to_csv(DATA_DIR / "ratings.csv", index=False)
    review[["number", "title", "fork_score", "avg", "avg_original", "diff", "n_raters", "n_parsed",
            "page"]] \
        .to_csv(DATA_DIR / "review.csv", index=False)

    print(f"{len(episodes)} episodes ({len(scored)} with a fork score, "
          f"{int(episodes.live.sum())} live), {len(ratings)} individual ratings")
    print(f"{len(review)} scored episodes flagged for review -> data/review.csv")


if __name__ == "__main__":
    build()
