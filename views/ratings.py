"""Fork ratings page: Nick vs. Mitch, ratings over time, and the episode table."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common import (SCALE, correlation, data_stamp, filter_bar, guest_ratings, load, colors,
                    style)

SERIES = {"nick": "Nick", "mitch": "Mitch", "guests": "Guests (avg)"}
SYMBOLS = {False: "circle", True: "diamond"}

stamp = data_stamp()
df = load(stamp)
c = colors()

st.title("🍴 Fork ratings")
st.caption("Every fork rating Nick Wiger and Mike Mitchell have given on *Doughboys*, "
           "as they requested on the pod.")

view, version = filter_bar(df, stamp)

# ---------------------------------------------------------------- headline numbers

both = view.dropna(subset=["nick_v", "mitch_v"])


def mean(s):
    return f"{s.mean():.2f}" if s.notna().any() else "–"


def pair_stats(a, b):
    """(correlation, exact-agreement share) for aligned score series."""
    return correlation(a, b), ((a == b).mean() if len(a) else None)


def pair_text(stats):
    r, agree = stats
    if agree is None:
        return "–"
    return ("r –" if r is None else f"r = {r:.2f}") + f" · {agree:.0%} agree"


# Guest comparisons pair each individual guest rating with the host's score for
# that episode, so agreement means the same thing as it does for Nick vs. Mitch.
guests = guest_ratings(version, stamp)
guests = guests[guests.page.isin(view.page)].merge(
    view.drop_duplicates("page")[["page", "nick_v", "mitch_v"]], on="page")
nick_guest = guests.dropna(subset=["nick_v"])
mitch_guest = guests.dropna(subset=["mitch_v"])
nick_mitch = pair_stats(both.nick_v, both.mitch_v)
r_value = nick_mitch[0]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Episodes", f"{len(view):,}")
m2.metric("Nick's average", mean(view.nick_v))
m3.metric("Mitch's average", mean(view.mitch_v))
m4.metric("Guests' average", mean(guests.value),
          help="Average of every individual guest rating in these episodes.")
PAIR_HELP = ("Correlation (Pearson's r, needs 3+ scores): 1 means the scores rise and fall "
             "together perfectly, 0 means no relationship. Agreement: share of scores that "
             "are exactly the same.")
p1, p2, p3 = st.columns(3)
p1.metric("Nick & Mitch", pair_text(nick_mitch),
          help=PAIR_HELP + " Compared across episodes both hosts rated.")
p2.metric("Nick & guests", pair_text(pair_stats(nick_guest.nick_v, nick_guest.value)),
          help=PAIR_HELP + " Each guest's rating is compared with Nick's for that episode.")
p3.metric("Mitch & guests", pair_text(pair_stats(mitch_guest.mitch_v, mitch_guest.value)),
          help=PAIR_HELP + " Each guest's rating is compared with Mitch's for that episode.")


def hover(frame):
    """Per-point tooltip text."""
    def fmt(v):
        return "–" if pd.isna(v) else f"{v:g}"
    rows = []
    for r in frame.itertuples():
        where = f"<br>🎤 Live{' in ' + r.live_city if r.live_city else ''} ({r.live_type})" \
            if r.is_live else ""
        rev = f"<br>✏️ {r.revisions}" if r.revisions else ""
        if r.capped:
            rev += f"<br>✂️ {r.capped} (scores are capped at −1 and 6)"
        rows.append(f"<b>{r.restaurant}</b> · {r.category}<br>{r.label} · {r.date:%b %d, %Y}<br>"
                    f"Nick {fmt(r.nick_v)} · Mitch {fmt(r.mitch_v)} · "
                    f"Guests {fmt(r.guests_v)}{where}{rev}")
    return rows


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
            line=dict(color=c["ink"], width=1, dash="dot"), hoverinfo="skip"))
        for is_live, part in both.groupby("is_live"):
            fig.add_trace(go.Scatter(
                x=part.nick_v + part.jx, y=part.mitch_v + part.jy, mode="markers",
                name="Live show" if is_live else "Studio episode",
                marker=dict(size=9, color=c["live" if is_live else "studio"],
                            opacity=0.75,
                            line=dict(width=1.5, color=c["ring"])),
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
                    marker=dict(symbol=SYMBOLS[is_live], size=8, color=c[key],
                                opacity=0.45 if smooth else 0.8,
                                line=dict(width=1, color=c["ring"])),
                    text=hover(sub), hovertemplate="%{text}<extra></extra>"))
            if smooth and len(part) >= 5:
                fig.add_trace(go.Scatter(
                    x=part.date, y=part[col].rolling(20, min_periods=5).mean(),
                    mode="lines", name=f"{name}, rolling avg", legendgroup=key,
                    showlegend=False, line=dict(color=c[key], width=2.5),
                    hovertemplate=f"{name} 20-ep avg: %{{y:.2f}}<extra></extra>"))
        # Legend-only key for marker shape, in neutral ink so it doesn't read as a host.
        for is_live, label in ((False, "Studio episode"), (True, "Live show")):
            fig.add_trace(go.Scatter(
                x=[None], y=[None], mode="markers", name=label, legendgroup="shape",
                marker=dict(symbol=SYMBOLS[is_live], size=9, color=c["ink"])))
        style(fig, None, "Forks")
        fig.update_layout(legend_traceorder="normal")  # one row, no gaps between groups
        st.plotly_chart(fig, width="stretch", theme="streamlit")
        st.caption("Color shows who gave the score; shape shows where: ● studio, ◆ live show. "
                   "Lines are 20-episode rolling averages.")

# ---------------------------------------------------------------- table

with tab_table:
    table = view.sort_values("date", ascending=False)[[
        "label", "date", "restaurant", "category", "guests", "nick_v", "mitch_v", "guests_v",
        "avg_v", "is_live", "live_city", "revised", "page"]]
    table = table.assign(page="https://doughboys.fandom.com/wiki/"
                         + table.page.str.replace(" ", "_"))
    st.dataframe(
        table, hide_index=True, width="stretch", height=560,
        column_config={
            "label": "Episode", "date": st.column_config.DateColumn("Date"),
            "restaurant": "Restaurant", "category": "Category", "guests": "Guests",
            "nick_v": st.column_config.NumberColumn("Nick", format="%.2f"),
            "mitch_v": st.column_config.NumberColumn("Mitch", format="%.2f"),
            "guests_v": st.column_config.NumberColumn("Guests", format="%.2f"),
            "avg_v": st.column_config.NumberColumn("All raters", format="%.2f"),
            "is_live": "Live", "live_city": "City", "revised": "Revised",
            "page": st.column_config.LinkColumn("Wiki", display_text="wiki page"),
        })
