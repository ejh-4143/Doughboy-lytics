"""Count words and phrases in the locally cached transcripts.

Reads data/transcripts/ (local only, see scraper/transcripts.py) and writes
derived, committable data:
  data/transcript_episodes.csv  each transcript matched to a wiki episode, with its word count
  data/phrase_counts.csv        per-episode counts for each phrase in data/phrases.csv
  data/phrase_candidates.csv    words and phrases unusually common on the show,
                                to help pick what goes in data/phrases.csv

data/phrases.csv columns: phrase (display name), variants ("|"-separated
alternative spellings, since the transcripts are machine-made), note.
Matching ignores case and punctuation and requires whole words.

Usage: uv run python -m scraper.phrases [--no-candidates]
"""

import gzip
import json
import math
import re
import sys
from collections import Counter
from functools import lru_cache

import pandas as pd

from scraper import DATA_DIR
from scraper.transcripts import INDEX, TEXT_DIR

STOPWORDS = set("""
a about after again all also am an and any are as at be because been but by can could did do
does doing don't for from get got had has have he her here him his how i i'm if in into is it
it's its just know like me more my no not now of on one or our out over really right so some
than that that's the their them then there they this to too up us very was we were what when
where which who will with would yeah you your oh okay yes uh um gonna wanna kind sort thing
things going go said say says mean well let's let because 's 're 've 'll 'd
""".split())


# Ad reads and show logistics that vary slightly between episodes, so the
# verbatim boilerplate filter misses them; kept out of the candidate list.
AD_LIKE = re.compile(
    r"\b(?:promo|code|com|slash|shipping|betterhelp|babbel|kinshipgoods|wildgrain|uber|"
    r"dietitian|trauma|coping|patreon|gmail|subscribe|sponsor\w*|offer|percent|"
    r"commission|renewable|calories|antioxidants|supermarket|sourdough|artisanal|"
    r"voicemail|email|headgum)\b|\d{3,}")
# The hosts' and show's names and nicknames. Transcription mangles them
# ("weiger", "wags" and "wikes" for Wiges, "doeboys"), so near matches count too.
HOST_NAMES = ("wiger", "wiges", "doughboys", "mitchell", "spoonman")
# Words that sit inside web and email addresses ("birdfuck com", "roastspoonman at gmail com").
ADDRESS_NEXT = re.compile(r"(?:\S+ )?(?:com|net|org|gmail|dot|tv)\b")  # used with .match(text, pos)


def name_tokens():
    """Distinctive name words of everyone who has rated or guested: hosts, guests,
    producers and themed aliases. Common English words ("the", "jack") are
    left out so phrases like "jack in the box" survive."""
    from wordfreq import zipf_frequency

    names = []
    ratings = DATA_DIR / "ratings.csv"
    if ratings.exists():
        names += pd.read_csv(ratings, usecols=["rater"]).rater.dropna().tolist()
    episodes = pd.read_csv(DATA_DIR / "episodes.csv", usecols=["guests"])
    names += [g for gs in episodes.guests.dropna() for g in re.split(r",|&|\band\b", gs)]
    pages = DATA_DIR / "raw" / "pages.json"  # local wiki cache: infoboxes list everyone on the episode
    if pages.exists():
        for text in json.loads(pages.read_text("utf-8")).values():
            for field in re.findall(r"\|\s*(?:guest|hosted_by)\s*=\s*([^|}]*)", text or ""):
                names += re.split(r",|&|\band\b", re.sub(r"\[\[|\]\]", "", field))
    tokens = {t.removesuffix("'s") for n in names for t in normalize(n).split()}
    return {t for t in tokens if len(t) > 2 and zipf_frequency(t, "en") < 3.5} | set(HOST_NAMES)


def restaurant_names():
    """Every run of words inside a restaurant or chain name ("taco", "taco bell",
    "carl's jr"), as a set for fast lookup."""
    eps = pd.read_csv(DATA_DIR / "episodes.csv", usecols=["restaurant", "chain"])
    runs = set()
    for name in pd.concat([eps.restaurant, eps.chain]).dropna():
        w = normalize(name).split()
        runs |= {" ".join(w[i:j]) for i in range(len(w)) for j in range(i + 1, len(w) + 1)}
    return runs


@lru_cache(maxsize=None)
def _zipf(word, lang="en"):
    from wordfreq import zipf_frequency
    return zipf_frequency(word, lang)


def is_noise(gram, names=frozenset(), restaurants=frozenset()):
    """Ad copy, a restaurant name, or a person's name/nickname (or a mangled
    transcription of one, e.g. "weigher" or "doe boys")."""
    from difflib import SequenceMatcher

    zipf_frequency = _zipf

    def host_like(w):
        # Only rare words can be mangled names; ordinary ones ("where", "spoon") are exempt.
        return (zipf_frequency(w, "en") < 3.5
                and any(SequenceMatcher(None, w, h).ratio() >= 0.65 for h in HOST_NAMES))

    if AD_LIKE.search(gram):
        return True
    if gram in restaurants:
        return True
    words = [w.removesuffix("'s") for w in gram.split()]
    if any(w in names for w in words):
        return True
    pairs = ["".join(words[i:i + 2]) for i in range(len(words) - 1)]  # "doe boys" -> "doeboys"
    if any(host_like(w) for w in words if len(w) > 3) or any(host_like(p) for p in pairs):
        return True
    if len(words) == 1:
        w = words[0]
        return zipf_frequency(w, "en") < 3.5 and any(
            SequenceMatcher(None, w, n).ratio() >= 0.8 for n in names if abs(len(n) - len(w)) <= 2)
    return False


def address_share(word, texts):
    """Share of a word's uses that are part of a web or email address."""
    total = inside = 0
    for text in texts.values():
        for m in re.finditer(rf"\b{re.escape(word)}\b ?", text):
            total += 1
            inside += bool(ADDRESS_NEXT.match(text, m.end()))
    return inside / total if total else 0


def normalize(text):
    """Lowercase, straighten apostrophes, keep only words separated by single spaces."""
    text = text.lower().replace("’", "'").replace("‘", "'")
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text))


def load_texts(min_words=6, min_episodes=3):
    """{slug: normalized full text} for every cached transcript, minus boilerplate.

    Ad reads, the Headgum intro and Patreon plugs repeat word for word across
    episodes and would otherwise swamp both the phrase counts and the
    candidate list. Any sentence of min_words+ words that appears verbatim in
    min_episodes+ episodes is treated as boilerplate and dropped.
    """
    sentences = {}
    for path in sorted(TEXT_DIR.glob("*.txt.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            sentences[path.name[:-len(".txt.gz")]] = [
                normalize(line.split("\t", 1)[-1]) for line in f]
    seen_in = Counter(s for sents in sentences.values() for s in set(sents)
                      if len(s.split()) >= min_words)
    boilerplate = {s for s, n in seen_in.items() if n >= min_episodes}
    texts = {slug: " ".join(s for s in sents if s not in boilerplate)
             for slug, sents in sentences.items()}
    dropped = sum(len(s.split()) for sents in sentences.values() for s in sents if s in boilerplate)
    total = sum(len(s.split()) for sents in sentences.values() for s in sents)
    print(f"dropped {len(boilerplate):,} repeated boilerplate sentences "
          f"({dropped / total:.1%} of words)", file=sys.stderr)
    return texts


# ---------------------------------------------------------------- episode matching


PREFIX = re.compile(r"^(?:unlocked\s*|doughboys double\s*\d*\s*|minisode\s*|\d+\s+)+")
NOISE = {"with", "and", "the", "doughboys", "live", "unlocked", "double", "special"}


def title_keys(title):
    """Normalized variants of an episode title for matching: without re-release
    prefixes ("UNLOCKED!", "Doughboys Double 88 -"), "(LIVE)", pirate-style
    "Alias aka Real Name" credits, and with or without a theme prefix before a colon."""
    t = re.sub(r"\((?:live)[^)]*\)", " ", title, flags=re.I)
    # "with Evil No Handerson aka Eva Anderson" -> "with Eva Anderson"
    t = re.sub(r"(\bwith\s+|,\s*|&\s*|\band\s+)[^,&]*?\baka\s+", r"\1", t, flags=re.I)
    parts = [t] + [t.split(":", i)[-1] for i in range(1, t.count(":") + 1)]
    keys = []
    for part in parts:
        key = PREFIX.sub("", normalize(part)).strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def match_episodes(index, episodes):
    """Match podscripts entries to wiki episodes.

    In order: identical cleaned title, near-identical title (fuzzy), or same
    release date (within a day) when the titles also share a real word.
    Re-releases mean several transcripts can match one wiki episode; the best
    match (then the earliest) is kept and the rest are marked "duplicate".
    """
    from difflib import get_close_matches

    eps = episodes.dropna(subset=["page"]).assign(day=pd.to_datetime(episodes.date))
    key_to_page = {}
    for row in eps.itertuples():
        for key in title_keys(row.title) + title_keys(row.page):
            key_to_page.setdefault(key, row.page)
    page_words = {row.page: {w for k in title_keys(row.title) for w in k.split()
                             if len(w) > 3 and w not in NOISE} for row in eps.itertuples()}

    rows = []
    for e in index:
        keys = title_keys(e["title"])
        page, how = None, ""
        for key in keys:
            if key in key_to_page:
                page, how = key_to_page[key], "title"
                break
        if page is None:
            for key in keys:
                close = get_close_matches(key, key_to_page, n=1, cutoff=0.88)
                if close:
                    page, how = key_to_page[close[0]], "fuzzy"
                    break
        if page is None and e["date"]:
            words = {w for k in keys for w in k.split() if len(w) > 3 and w not in NOISE}
            near = eps[(eps.day - pd.Timestamp(e["date"])).abs() <= pd.Timedelta(days=1)]
            near = near[[bool(words & page_words[p]) for p in near.page]]
            if len(near) == 1:
                page, how = near.page.iloc[0], "date"
        rows.append({"slug": e["slug"], "podscripts_title": e["title"], "date": e["date"],
                     "page": page, "matched_by": how})
    df = pd.DataFrame(rows).drop_duplicates("slug")
    number = eps.drop_duplicates("page").set_index("page").number
    df["number"] = df.page.map(number)
    # One transcript per wiki episode: best method first, then earliest release.
    rank = df.matched_by.map({"title": 0, "fuzzy": 1, "date": 2})
    order = df.assign(rank=rank).sort_values(["rank", "date"])
    dupes = order[order.page.notna() & order.duplicated("page")].index
    df.loc[dupes, "matched_by"] = "duplicate"
    df.loc[dupes, ["page", "number"]] = None
    return df[["slug", "podscripts_title", "date", "page", "number", "matched_by"]]


# ---------------------------------------------------------------- phrase counts


def phrase_patterns(phrases):
    """{display phrase: compiled regex} matching any variant as whole words."""
    out = {}
    for row in phrases.itertuples():
        variants = [row.phrase] + [v for v in str(row.variants or "").split("|") if v.strip()]
        alts = sorted({normalize(v) for v in variants if normalize(v)}, key=len, reverse=True)
        out[row.phrase] = re.compile(r"\b(?:" + "|".join(re.escape(a) for a in alts) + r")\b")
    return out


def count_phrases(texts, patterns):
    rows = []
    for slug, text in texts.items():
        for phrase, pattern in patterns.items():
            n = len(pattern.findall(text))
            if n:
                rows.append({"slug": slug, "phrase": phrase, "count": n})
    return pd.DataFrame(rows, columns=["slug", "phrase", "count"])


# ---------------------------------------------------------------- candidates


def phrase_years(texts, dates, phrases, max_n):
    """{phrase: Counter(year -> uses)} for just the given phrases."""
    years = {}
    for slug, text in texts.items():
        year = (dates.get(slug) or "")[:4]
        if not year:
            continue
        words = text.split()
        for n in range(1, max_n + 1):
            for i in range(len(words) - n + 1):
                g = " ".join(words[i:i + n])
                if g in phrases:
                    years.setdefault(g, Counter())[year] += 1
    return years


def candidates(texts, dates, max_n=4, top_per_length=120, names=frozenset(),
               restaurants=frozenset()):
    """Words and phrases that are unusually common on this show.

    Single words: how many times more frequent than in general English
    (wordfreq). Multi-word phrases: how much more often the words occur
    together than their separate frequencies predict (PMI), weighted by how
    many episodes use it, so recurring bits beat one-off sentences.
    """
    from wordfreq import word_frequency

    n_eps = len(texts)
    counts = {n: Counter() for n in range(1, max_n + 1)}
    docs = {n: Counter() for n in range(1, max_n + 1)}
    total = 0
    for text in texts.values():
        words = text.split()
        total += len(words)
        for n in range(1, max_n + 1):
            c = Counter(" ".join(words[i:i + n]) for i in range(len(words) - n + 1))
            counts[n].update(c)
            docs[n].update(c.keys())
    unigram_p = {w: c / total for w, c in counts[1].items()}
    min_docs = max(8, n_eps // 25)
    # Free everything below the thresholds before the slower scoring pass.
    for n in range(1, max_n + 1):
        docs[n] = Counter({g: d for g, d in docs[n].items() if d >= min_docs})
        counts[n] = Counter({g: counts[n][g] for g in docs[n] if counts[n][g] >= 2 * min_docs})

    rows = []
    for n in range(1, max_n + 1):
        for gram, c in counts[n].items():
            d = docs[n][gram]
            if d < min_docs or c < 2 * min_docs:
                continue
            words = gram.split()
            if all(w in STOPWORDS for w in words) or words[0] in STOPWORDS and words[-1] in STOPWORDS:
                continue
            rate = c / total
            if n == 1:
                general = word_frequency(gram, "en") or 1e-9
                score = math.log2(rate / general)
                if score < 3:  # at least 8x more common than in general English
                    continue
            else:
                pmi = math.log2(rate / math.prod(unigram_p[w] for w in words))
                if pmi < 6:
                    continue
                score = pmi
            if is_noise(gram, names, restaurants):  # slow, so only for phrases that scored well
                continue
            rows.append({
                "phrase": gram, "words": n, "count": c, "episodes": d,
                "share_of_episodes": round(d / n_eps, 3), "score": round(score, 2),
            })
    df = pd.DataFrame(rows)
    years = phrase_years(texts, dates, set(df.phrase), max_n)
    df["first_year"] = df.phrase.map(lambda g: min(years[g]) if years.get(g) else None)
    df["peak_year"] = df.phrase.map(lambda g: max(years[g], key=years[g].get) if years.get(g) else None)
    df["rank_score"] = df.score * df.episodes.map(math.log)
    # Drop a phrase when a longer phrase containing it is used almost as often.
    df = df.sort_values("rank_score", ascending=False)
    keep, kept = [], []
    for r in df.itertuples():
        if any(r.phrase in k.phrase and k.count >= 0.8 * r.count for k in kept):
            continue
        kept.append(r)
        keep.append(r.Index)
    df = df.loc[keep]
    # Drop single words that mostly live inside web/email addresses.
    single = df[df.words == 1].head(3 * top_per_length)
    addresses = [i for i, w in zip(single.index, single.phrase) if address_share(w, texts) >= 0.25]
    df = df.drop(index=addresses)
    # Rank each phrase length separately: long phrases score far higher on PMI
    # and would otherwise crowd out single words.
    return (df.groupby("words", group_keys=False).head(top_per_length)
            .sort_values(["words", "rank_score"], ascending=[True, False])
            .drop(columns="rank_score"))


# ---------------------------------------------------------------- main


def main():
    texts = load_texts()
    index = json.loads(INDEX.read_text("utf-8"))
    episodes = pd.read_csv(DATA_DIR / "episodes.csv")

    matched = match_episodes(index, episodes)
    words = {slug: len(t.split()) for slug, t in texts.items()}
    matched["words"] = matched.slug.map(words).astype("Int64")
    matched = matched[matched.words.notna()]
    matched.to_csv(DATA_DIR / "transcript_episodes.csv", index=False)
    how = matched.matched_by.replace("", "unmatched").value_counts().to_dict()
    print(f"{len(texts)} transcripts, {matched.page.notna().sum()} matched to wiki episodes: {how}",
          file=sys.stderr)

    phrases = pd.read_csv(DATA_DIR / "phrases.csv", dtype=str, keep_default_na=False)
    counts = count_phrases(texts, phrase_patterns(phrases))
    counts.to_csv(DATA_DIR / "phrase_counts.csv", index=False)
    print(f"{len(phrases)} phrases counted -> data/phrase_counts.csv", file=sys.stderr)

    if "--no-candidates" not in sys.argv:
        dates = dict(zip(matched.slug, matched.date))
        cands = candidates(texts, dates, names=name_tokens(), restaurants=restaurant_names())
        cands.to_csv(DATA_DIR / "phrase_candidates.csv", index=False)
        print(f"{len(cands)} candidate words/phrases -> data/phrase_candidates.csv", file=sys.stderr)


if __name__ == "__main__":
    main()
