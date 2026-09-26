"""Doughboy-lytics: Nick and Mitch's fork ratings, plotted.

Run locally: uv run streamlit run app.py
Reads data/episodes.csv and data/ratings.csv, built by `uv run python -m scraper.parse`.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA = Path(__file__).parent / "data" / "episodes.csv"
RATINGS = Path(__file__).parent / "data" / "ratings.csv"
WIKI = "https://doughboys.fandom.com/wiki/Doughboys_Wikia"
SCALE = (0, 5)
CAP = (-1, 6)  # the hosts' own joke extremes; anything wilder (Nicole Byer's 10) is pulled in

# Validated categorical slots 1-3 (all-pairs safe for scatter), per theme.
PALETTE = {
    "light": {"nick": "#2a78d6", "mitch": "#eb6834", "guests": "#1baf7a",
              "ink": "#52514e", "grid": "#e6e5e0", "ring": "#fcfcfb"},
    "dark": {"nick": "#3987e5", "mitch": "#d95926", "guests": "#199e70",
             "ink": "#c3c2b7", "grid": "#383835", "ring": "#1a1a19"},
}
SERIES = {"nick": "Nick", "mitch": "Mitch", "guests": "Guests (avg)"}
SYMBOLS = {False: "circle", True: "diamond"}
KINDS = {"main": "Main episodes", "double": "Doughboys Doubles",
         "bread_cast": "The Bread Cast", "snack_pack": "Snack Pack", "other": "Other"}

st.set_page_config(page_title="Doughboy-lytics", page_icon="🍴", layout="wide")


@st.cache_data
def load():
    df = pd.read_csv(DATA, keep_default_na=False, na_values=[""])
    df = df[df.avg.notna() | df.nick.notna() | df.mitch.notna()].copy()
    df["date"] = pd.to_datetime(df.date)
    for col in ("live", "revised"):
        df[col] = df[col].astype(str).str.lower() == "true"
    df["live_type"] = df.live_type.fillna("")
    df["live_city"] = df.live_city.fillna("")
    df["label"] = np.where(df.kind == "main", "Ep. " + df.number.astype(str), df.number)
    # Deterministic jitter so identical scores don't hide behind each other.
    rng = np.random.default_rng(7)
    df["jx"] = rng.uniform(-0.09, 0.09, len(df))
    df["jy"] = rng.uniform(-0.09, 0.09, len(df))
    return df


@st.cache_data
def load_ratings():
    return pd.read_csv(RATINGS, usecols=["page", "rater", "role", "rating", "rating_original"])


@st.cache_data
def episode_scores(version):
    """Per-page nick, mitch, guest and all-rater scores for one score version.

    Scores are capped to CAP per rating, before averaging, so a single wild
    guest score can't skew an episode's guest average. `capped` describes
    any capping for the hover text ("" if none).
    """
    r = load_ratings()
    raw = r["rating" if version == "Revised" else "rating_original"]
    value = raw.clip(*CAP)
    note = np.where(value != raw, r.rater + "'s " + raw.map("{:g}".format)
                    + " capped to " + value.map("{:g}".format), "")
    r = r.assign(value=value, capped=np.where(raw.notna(), note, ""))
    hosts = r[r.role != "guest"].pivot_table(index="page", columns="role", values="value",
                                              aggfunc="first").reindex(columns=["nick", "mitch"])
    return pd.DataFrame({
        "nick_v": hosts.nick, "mitch_v": hosts.mitch,
        "guests_v": r[r.role == "guest"].groupby("page").value.mean(),
        "avg_v": r.groupby("page").value.mean(),
        "capped": r[r.capped != ""].groupby("page").capped.agg("; ".join),
    })


def theme():
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except AttributeError:
        return "light"


df = load()
colors = PALETTE[theme()]

st.title("🍴 Doughboy-lytics")
st.caption("Every fork rating Nick Wiger and Mike Mitchell have given on *Doughboys*, "
           "as they requested on the pod. Data from the "
           f"[Doughboys Wiki]({WIKI}), with thanks to its editors.")

# ---------------------------------------------------------------- filters (one row)

c1, c2, c3, c4 = st.columns([1.1, 1.6, 1.3, 1.6])
with c1:
    version = st.segmented_control(
        "Scores", ["Revised", "Original"], default="Revised", key="version",
        help="Revised uses the hosts' later changes (e.g. Mitch dropping In-N-Out to 3 "
             "forks in ep. 47). Original uses the score given on the episode.") or "Revised"
with c2:
    years = (int(df.date.dt.year.min()), int(df.date.dt.year.max()))
    year_range = st.slider("Years", *years, value=years)
with c3:
    live_choice = st.segmented_control(
        "Live shows", ["All", "Live only", "Studio only"], default="All", key="live") or "All"
    streams_live = st.checkbox("Count livestreams & watchalongs as live", value=True)
with c4:
    kinds_present = [k for k in KINDS if k in set(df.kind)]
    kinds = st.multiselect("Episode types", kinds_present, default=["main", "double"],
                           format_func=KINDS.get)
    search = st.text_input("Restaurant", placeholder="Search, e.g. Taco Bell")

# ---------------------------------------------------------------- apply filters

view = df.join(episode_scores(version), on="page")
view["capped"] = view.capped.fillna("")
view["is_live"] = view.live & (streams_live | (view.live_type == "in person"))
mask = (view.date.dt.year.between(*year_range)) & view.kind.isin(kinds)
if live_choice == "Live only":
    mask &= view.is_live
elif live_choice == "Studio only":
    mask &= ~view.is_live
if search:
    mask &= view.restaurant.str.contains(search, case=False, regex=False)
view = view[mask].copy()

# ---------------------------------------------------------------- headline numbers

both = view.dropna(subset=["nick_v", "mitch_v"])


def mean_median(s):
    return f"{s.mean():.2f} / {s.median():g}" if s.notna().any() else "–"


def correlation(frame):
    """Pearson r between Nick's and Mitch's scores, or None if it's undefined."""
    if len(frame) < 3 or frame.nick_v.nunique() < 2 or frame.mitch_v.nunique() < 2:
        return None
    return frame.nick_v.corr(frame.mitch_v)


r_value = correlation(both)
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Episodes", f"{len(view):,}")
m2.metric("Nick · mean / median", mean_median(view.nick_v))
m3.metric("Mitch · mean / median", mean_median(view.mitch_v))
m4.metric("Nick & Mitch agree exactly",
          f"{(both.nick_v == both.mitch_v).mean():.0%}" if len(both) else "–",
          help="Share of episodes where both hosts gave the same score.")
m5.metric("Nick–Mitch correlation", "–" if r_value is None else f"{r_value:.2f}",
          help="Pearson's r across episodes both hosts rated: 1 means their scores rise and "
               "fall together perfectly, 0 means no relationship. Needs at least 3 episodes.")


def hover(frame):
    """Per-point tooltip text."""
    def fmt(v):
        return "–" if pd.isna(v) else f"{v:g}"
    rows = []
    for r in frame.itertuples():
        where = f"<br>🎤 Live{' in ' + r.live_city if r.live_city else ''} ({r.live_type})" \
            if r.is_live else ""
        rev = "<br>✏️ Includes a later score revision" if r.revised else ""
        if r.capped:
            rev += f"<br>✂️ {r.capped} (scores are capped at −1 and 6)"
        rows.append(f"<b>{r.restaurant}</b><br>{r.label} · {r.date:%b %d, %Y}<br>"
                    f"Nick {fmt(r.nick_v)} · Mitch {fmt(r.mitch_v)} · "
                    f"Guests {fmt(r.guests_v)}{where}{rev}")
    return rows


def style(fig, x_title, y_title, height=560):
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, title=None),
        hoverlabel=dict(align="left"), font=dict(color=colors["ink"]),
    )
    fig.update_xaxes(title=x_title, gridcolor=colors["grid"], zeroline=False)
    fig.update_yaxes(title=y_title, gridcolor=colors["grid"], zeroline=False)
    return fig


tab_vs, tab_time, tab_table = st.tabs(["Nick vs. Mitch", "Over time", "Table"])

# ---------------------------------------------------------------- Nick vs. Mitch

with tab_vs:
    if both.empty:
        st.info("No episodes with both hosts' scores match these filters.")
    else:
        chart_col, side_col = st.columns([3, 2], gap="large")
        lo = min(SCALE[0], both.nick_v.min(), both.mitch_v.min()) - 0.3
        hi = max(SCALE[1], both.nick_v.max(), both.mitch_v.max()) + 0.3
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[lo, hi], y=[lo, hi], mode="lines", name="Nick = Mitch",
            line=dict(color=colors["ink"], width=1, dash="dot"), hoverinfo="skip"))
        for is_live, part in both.groupby("is_live"):
            fig.add_trace(go.Scatter(
                x=part.nick_v + part.jx, y=part.mitch_v + part.jy, mode="markers",
                name="Live show" if is_live else "Studio episode",
                marker=dict(symbol=SYMBOLS[is_live], size=10 if is_live else 9,
                            color=colors["nick"], opacity=0.75,
                            line=dict(width=1.5, color=colors["ring"])),
                text=hover(part), hovertemplate="%{text}<extra></extra>"))
        style(fig, "Nick's forks", "Mitch's forks", height=620)
        fig.update_xaxes(range=[lo, hi], dtick=1, constrain="domain")
        fig.update_yaxes(range=[lo, hi], dtick=1, scaleanchor="x", scaleratio=1,
                         constrain="domain")
        above = (both.mitch_v > both.nick_v).sum()
        below = (both.mitch_v < both.nick_v).sum()
        with chart_col:
            st.plotly_chart(fig, width="stretch", theme="streamlit")
            st.caption(f"Each dot is an episode (slightly jittered so ties stay visible). "
                       f"Above the dotted line Mitch liked it more ({above} episodes); "
                       f"below it Nick did ({below})."
                       + ("" if r_value is None else f" Correlation r = {r_value:.2f}."))
        with side_col:
            st.subheader("Biggest disagreements")
            gap = both.assign(gap=both.mitch_v - both.nick_v)
            gap = gap.reindex(gap.gap.abs().sort_values(ascending=False).index).head(8)
            for r in gap.itertuples():
                fan = "Mitch" if r.gap > 0 else "Nick"
                st.markdown(f"**{r.restaurant}** · {r.label}  \n"
                            f"Nick {r.nick_v:g} · Mitch {r.mitch_v:g} "
                            f"({fan} +{abs(r.gap):g})")

# ---------------------------------------------------------------- over time

with tab_time:
    if view.empty:
        st.info("No episodes match these filters.")
    else:
        smooth = st.checkbox("Show 20-episode rolling average", value=True)
        fig = go.Figure()
        ordered = view.sort_values("date")
        for key, name in SERIES.items():
            col = f"{key}_v"
            part = ordered.dropna(subset=[col])
            for is_live, sub in part.groupby("is_live"):
                fig.add_trace(go.Scatter(
                    x=sub.date, y=sub[col] + sub.jy / 2, mode="markers",
                    name=name, legendgroup=key, showlegend=not is_live,
                    marker=dict(symbol=SYMBOLS[is_live], size=8, color=colors[key],
                                opacity=0.45 if smooth else 0.8,
                                line=dict(width=1, color=colors["ring"])),
                    text=hover(sub), hovertemplate="%{text}<extra></extra>"))
            if smooth and len(part) >= 5:
                fig.add_trace(go.Scatter(
                    x=part.date, y=part[col].rolling(20, min_periods=5).mean(),
                    mode="lines", name=f"{name}, rolling avg", legendgroup=key,
                    showlegend=False, line=dict(color=colors[key], width=2.5),
                    hovertemplate=f"{name} 20-ep avg: %{{y:.2f}}<extra></extra>"))
        style(fig, None, "Forks")
        st.plotly_chart(fig, width="stretch", theme="streamlit")
        st.caption("◆ diamonds are live shows. Lines are 20-episode rolling averages.")

# ---------------------------------------------------------------- table

with tab_table:
    table = view.sort_values("date", ascending=False)[[
        "label", "date", "restaurant", "guests", "nick_v", "mitch_v", "guests_v", "avg_v",
        "is_live", "live_city", "revised", "page"]]
    table = table.assign(page="https://doughboys.fandom.com/wiki/"
                         + table.page.str.replace(" ", "_"))
    st.dataframe(
        table, hide_index=True, width="stretch", height=560,
        column_config={
            "label": "Episode", "date": st.column_config.DateColumn("Date"),
            "restaurant": "Restaurant", "guests": "Guests",
            "nick_v": st.column_config.NumberColumn("Nick", format="%.2f"),
            "mitch_v": st.column_config.NumberColumn("Mitch", format="%.2f"),
            "guests_v": st.column_config.NumberColumn("Guests", format="%.2f"),
            "avg_v": st.column_config.NumberColumn("All raters", format="%.2f"),
            "is_live": "Live", "live_city": "City", "revised": "Revised",
            "page": st.column_config.LinkColumn("Wiki", display_text="wiki page"),
        })

# ---------------------------------------------------------------- credit

st.divider()
st.markdown(
    f"**Data source:** the [Doughboys Wiki]({WIKI}) on Fandom. Huge thanks to its "
    "editors, who have logged every episode, order and fork rating since 2015. "
    "Spotted a mistake? Please fix it on the wiki. Wiki content is licensed "
    "[CC BY-SA](https://www.fandom.com/licensing), and so is the data shown here. "
    "Fan project, not affiliated with *Doughboys* or Headgum.")
