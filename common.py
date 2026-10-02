"""Shared data loading, filters and chart styling for the app's pages."""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "episodes.csv"
RATINGS = ROOT / "data" / "ratings.csv"
# Phrase counts derived from podscripts.co transcripts (scraper/phrases.py). The
# transcripts themselves stay local; the app only ever sees counts.
TRANSCRIPT_EPS = ROOT / "data" / "transcript_episodes.csv"
PHRASE_COUNTS = ROOT / "data" / "phrase_counts.csv"
PHRASE_CANDIDATES = ROOT / "data" / "phrase_candidates.csv"
PHRASES = ROOT / "data" / "phrases.csv"
PODSCRIPTS = "https://podscripts.co/podcasts/doughboys/"
WIKI = "https://doughboys.fandom.com/wiki/Doughboys_Wikia"
SCALE = (0, 5)
CAP = (-1, 6)  # the hosts' own joke extremes; anything wilder (Nicole Byer's 10) is pulled in

# Validated categorical slots 1-3 (all-pairs safe for scatter), per theme.
# Studio/live use violet and red (slots 7 and 8), validated as their own pair,
# so they don't read as Nick's blue or Mitch's orange.
PALETTE = {
    "light": {"nick": "#2a78d6", "mitch": "#eb6834", "guests": "#1baf7a",
              "studio": "#4a3aa7", "live": "#e34948",
              "ink": "#52514e", "grid": "#e6e5e0", "ring": "#fcfcfb"},
    "dark": {"nick": "#3987e5", "mitch": "#d95926", "guests": "#199e70",
             "studio": "#9085e9", "live": "#e66767",
             "ink": "#c3c2b7", "grid": "#383835", "ring": "#1a1a19"},
}
# Only main episodes and Doubles carry fork ratings worth plotting (the Bread
# Cast has a single rated episode; other side feeds have none).
KINDS = {"All": ["main", "double"], "Main episodes": ["main"], "Doubles": ["double"]}


# ---------------------------------------------------------------- loading


def data_stamp():
    """Modification times of the CSVs. Passed to every cached loader so a
    running app picks up rebuilt data instead of serving its old cache."""
    return tuple(p.stat().st_mtime if p.exists() else 0
                 for p in (DATA, RATINGS, TRANSCRIPT_EPS, PHRASE_COUNTS, PHRASE_CANDIDATES,
                           PHRASES))


@st.cache_data
def load(stamp):
    df = pd.read_csv(DATA, keep_default_na=False, na_values=[""])
    df = df[(df.avg.notna() | df.nick.notna() | df.mitch.notna())
            & df.kind.isin(KINDS["All"])].copy()
    df["date"] = pd.to_datetime(df.date)
    for col in ("live", "revised"):
        df[col] = df[col].astype(str).str.lower() == "true"
    df["live_type"] = df.live_type.fillna("")
    df["live_city"] = df.live_city.fillna("")
    df["category"] = df.category.fillna("Other")
    df["label"] = np.where(df.kind == "main", "Ep. " + df.number.astype(str), df.number)
    # Deterministic jitter so identical scores don't hide behind each other.
    rng = np.random.default_rng(7)
    df["jx"] = rng.uniform(-0.09, 0.09, len(df))
    df["jy"] = rng.uniform(-0.09, 0.09, len(df))
    return df


@st.cache_data
def load_ratings(stamp):
    return pd.read_csv(RATINGS, usecols=["page", "rater", "role", "rating", "rating_original"])


@st.cache_data
def episode_scores(version, stamp):
    """Per-page nick, mitch, guest and all-rater scores for one score version.

    Scores are capped to CAP per rating, before averaging, so a single wild
    guest score can't skew an episode's guest average. `capped` and `revisions`
    describe any capping and later score changes for the hover text.
    """
    r = load_ratings(stamp)
    who = r.role.map({"nick": "Nick", "mitch": "Mitch"}).fillna(r.rater)
    changed = r.rating_original.notna() & (r.rating != r.rating_original)
    later = r.rating.map(lambda v: "thrown out" if pd.isna(v) else f"{v:g}")
    revision = (who + ": " + r.rating_original.map(lambda v: f"{v:g}", na_action="ignore")
                + " on the episode → " + later + " later").where(changed, "")
    raw = r["rating" if version == "Revised" else "rating_original"]
    value = raw.clip(*CAP)
    note = np.where(value != raw, r.rater + "'s " + raw.map("{:g}".format)
                    + " capped to " + value.map("{:g}".format), "")
    r = r.assign(value=value, capped=np.where(raw.notna(), note, ""), revision=revision)
    hosts = r[r.role != "guest"].pivot_table(index="page", columns="role", values="value",
                                              aggfunc="first").reindex(columns=["nick", "mitch"])
    return pd.DataFrame({
        "nick_v": hosts.nick, "mitch_v": hosts.mitch,
        "guests_v": r[r.role == "guest"].groupby("page").value.mean(),
        "avg_v": r.groupby("page").value.mean(),
        "capped": r[r.capped != ""].groupby("page").capped.agg("; ".join),
        "revisions": r[r.revision != ""].groupby("page").revision.agg("<br>✏️ ".join),
    })


@st.cache_data
def guest_ratings(version, stamp):
    """One row per guest rating (page, value), capped like all other scores."""
    r = load_ratings(stamp)
    r = r[r.role == "guest"]
    value = r["rating" if version == "Revised" else "rating_original"].clip(*CAP)
    return pd.DataFrame({"page": r.page, "value": value}).dropna()


@st.cache_data
def load_words(stamp):
    """(transcript episodes, phrase counts, candidates), or None before the
    transcripts have been processed."""
    if not (TRANSCRIPT_EPS.exists() and PHRASE_COUNTS.exists()):
        return None
    eps = pd.read_csv(TRANSCRIPT_EPS).dropna(subset=["page"])
    counts = pd.read_csv(PHRASE_COUNTS)
    cands = pd.read_csv(PHRASE_CANDIDATES) if PHRASE_CANDIDATES.exists() else None
    if cands is not None and PHRASES.exists():
        cands = fold_candidates(cands, counts, eps)
    return eps, counts, cands


def _words(text):
    """Same normalization as scraper/phrases.py: lowercase words, straight apostrophes."""
    import re
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", str(text).lower().replace("’", "'"))


def fold_candidates(cands, counts, eps):
    """Merge signature-list entries that are spellings of a tracked phrase.

    An entry folds into a phrase from data/phrases.csv when it is that phrase,
    one of its variants, or a whole-word part of one ("jemmy's", "uncar",
    "plutt"), and matches no other tracked phrase. The merged row gets the
    tracked phrase's exact stats from phrase_counts.csv instead.
    """
    phrases = pd.read_csv(PHRASES, dtype=str, keep_default_na=False)
    spellings = {}
    for row in phrases.itertuples():
        variants = [row.phrase] + [v for v in row.variants.split("|") if v.strip()]
        spellings[row.phrase] = [" " + " ".join(_words(v)) + " " for v in variants]

    def owner(entry):
        e = " " + " ".join(w.removesuffix("'s") for w in _words(entry)) + " "
        hits = [p for p, vs in spellings.items() if any(e in v for v in vs)]
        return hits[0] if len(hits) == 1 else None

    cands = cands.assign(owner=cands.phrase.map(owner))
    folded = [p for p in cands.owner.dropna().unique() if p in set(counts.phrase)]
    if not folded:
        return cands.drop(columns="owner")
    dates = eps.set_index("slug").date
    rows = []
    for p in folded:
        c = counts[counts.phrase == p]
        by_year = c.groupby(c.slug.map(dates).str[:4])["count"].sum()
        rows.append({"phrase": p, "words": len(p.split()), "count": int(c["count"].sum()),
                     "episodes": c.slug.nunique(),
                     "first_year": int(by_year.index.min()), "peak_year": int(by_year.idxmax())})
    kept = cands[cands.owner.isna() | ~cands.owner.isin(folded)].drop(columns="owner")
    # Place each merged phrase where its best-ranked spelling was.
    merged = pd.DataFrame(rows).set_index("phrase")
    first_pos = cands.reset_index().groupby("owner")["index"].min()
    out = pd.concat([kept, merged.reset_index()], ignore_index=True)
    out["_pos"] = list(kept.index) + [first_pos[p] - 0.5 for p in merged.index]
    return out.sort_values("_pos").drop(columns="_pos").reset_index(drop=True)


# ---------------------------------------------------------------- helpers


def normalize(text):
    """Lowercase, strip accents and apostrophes, and fold spelling variants so
    a search like "Voodoo Donuts" finds "Voodoo Doughnut"."""
    text = (text.str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii")
            .str.lower().str.replace(r"['’`.]", "", regex=True)
            .str.replace(r"[^a-z0-9]+", " ", regex=True))
    text = text.str.replace(r"doughnut", "donut", regex=True)
    return text.str.replace(r"\b(\w{2,}[^s\W])s\b", r"\1", regex=True)  # tacos -> taco


def theme():
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except AttributeError:
        return "light"


def colors():
    return PALETTE[theme()]


def correlation(a, b):
    """Pearson r between two aligned series, or None if it's undefined."""
    if len(a) < 3 or a.nunique() < 2 or b.nunique() < 2:
        return None
    return a.corr(b)


def style(fig, x_title, y_title, height=560):
    c = colors()
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, title=None),
        hoverlabel=dict(align="left"), font=dict(color=c["ink"]),
    )
    # Streamlit's chart theme hides vertical grid lines, so turn them on explicitly.
    fig.update_xaxes(title=x_title, showgrid=True, gridcolor=c["grid"], zeroline=False)
    fig.update_yaxes(title=y_title, gridcolor=c["grid"], zeroline=False)
    return fig


# ---------------------------------------------------------------- filters


def category_filter(by_size):
    """Popover checklist of food categories, sorted by episode count, with All/None.

    Each checkbox's state lives in st.session_state["cat:<category>"] (all on by
    default); returns the checked categories.
    """
    keys = {c: f"cat:{c}" for c in by_size.index}
    for key in keys.values():
        st.session_state.setdefault(key, True)

    def set_all(on):
        for key in keys.values():
            st.session_state[key] = on

    chosen = [c for c, key in keys.items() if st.session_state[key]]
    summary = ("all" if len(chosen) == len(keys) else "none" if not chosen
               else chosen[0] if len(chosen) == 1 else f"{len(chosen)} of {len(keys)}")
    st.markdown("**Food category**", help="One hand-assigned category per restaurant "
                "(data/categories.csv). Numbers are rated episodes in each.")
    with st.popover(f"Categories: {summary}", width="stretch"):
        b1, b2 = st.columns(2)
        b1.button("All", on_click=set_all, args=(True,), width="stretch")
        b2.button("None", on_click=set_all, args=(False,), width="stretch")
        for c, key in keys.items():
            st.checkbox(f"{c} ({by_size[c]})", key=key)
    return chosen


FILTER_KEYS = ("version", "years", "live", "streams_live", "kind", "search")


def keep_filter_state():
    """Carry filter choices across pages. Streamlit discards a widget's state
    when the page that drew it isn't shown; re-assigning the keys each run
    marks them as plain session state, which survives page switches."""
    for key in list(st.session_state.keys()):
        if key in FILTER_KEYS or str(key).startswith("cat:"):
            st.session_state[key] = st.session_state[key]


def filter_bar(df, stamp, scores=True):
    """Render the filter row and return (filtered episodes with scores, score version).

    scores=False hides the Revised/Original control (the Words page has no use
    for it) and uses revised scores.
    """
    keep_filter_state()
    years = (int(df.date.dt.year.min()), int(df.date.dt.year.max()))
    # Defaults live in session state, not in the widget calls: a widget given
    # both a default and a session-state value makes Streamlit warn.
    for key, default in (("version", "Revised"), ("years", years), ("live", "All"),
                         ("streams_live", True), ("kind", "All"), ("search", "")):
        st.session_state.setdefault(key, default)
    cols = st.columns([1.1, 1.6, 1.3, 1.6] if scores else [1.6, 1.3, 1.6])
    version = "Revised"
    if scores:
        with cols[0]:
            version = st.segmented_control(
                "Scores", ["Revised", "Original"], key="version",
                help="Revised uses the hosts' later changes (e.g. Mitch dropping In-N-Out to 3 "
                     "forks in ep. 47). Original uses the score given on the episode.") or "Revised"
    c_years, c_live, c_kind = cols[-3:]
    with c_years:
        year_range = st.slider("Years", *years, key="years")
        categories = category_filter(df.category.value_counts())
    with c_live:
        live_choice = st.segmented_control(
            "Live shows", ["All", "Live only", "Studio only"], key="live") or "All"
        streams_live = st.checkbox("Count livestreams & watchalongs as live", key="streams_live")
    with c_kind:
        kind_choice = st.segmented_control(
            "Episode types", list(KINDS), key="kind") or "All"
        search = st.text_input("Search", placeholder="Restaurant or guest, e.g. Taco Bell",
                               key="search",
                               help="Matches restaurant, chain and guest names. Ignores case, "
                                    "accents and apostrophes; plurals and donut/doughnut match.")

    view = df.join(episode_scores(version, stamp), on="page")
    view["capped"] = view.capped.fillna("")
    view["revisions"] = view.revisions.fillna("")
    view["is_live"] = view.live & (streams_live | (view.live_type == "in person"))
    mask = view.date.dt.year.between(*year_range) & view.kind.isin(KINDS[kind_choice])
    if live_choice == "Live only":
        mask &= view.is_live
    elif live_choice == "Studio only":
        mask &= ~view.is_live
    mask &= view.category.isin(categories)
    if search:
        haystack = normalize(view.restaurant + " " + view.chain.fillna("") + " "
                             + view.guests.fillna(""))
        for word in normalize(pd.Series([search])).iloc[0].split():
            mask &= haystack.str.contains(word, regex=False)
    return view[mask].copy(), version
