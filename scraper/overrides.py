"""Manual corrections, kept separate from scraped data so re-scrapes keep them.

data/overrides.csv columns:
  page    wiki page title (the unique key; episode numbers repeat, e.g. "DD")
  rater   blank for an episode-level fix; otherwise the rater's name as it
          appears in ratings.csv (a new name adds a rating row)
  field   column to set, e.g. rating (the revised score), rating_original
          (the score given on the episode), rating_note, live_source,
          live_city, restaurant. "score" sets both rating and
          rating_original: use it to fix a parsing mistake rather than to
          record a later revision.
  value   new value; blank means missing (NaN / empty)
  reason  free text, for humans
"""

import pandas as pd

HOSTS = {"Nick Wiger": "nick", "Mike Mitchell": "mitch"}


def _coerce(value, series):
    if pd.isna(value) or value == "":
        return None if series.dtype == object else float("nan")
    if series.dtype == bool:
        return str(value).strip().lower() in ("true", "1", "yes")
    if pd.api.types.is_numeric_dtype(series.dtype):
        return float(value)
    return value


def apply_overrides(episodes, ratings, path):
    if not path.exists():
        return episodes, ratings
    fixes = pd.read_csv(path, dtype=str, keep_default_na=False, comment="#")
    unmatched = []
    for fix in fixes.itertuples():
        if not fix.rater:
            target, mask = episodes, episodes.page == fix.page
        else:
            mask = (ratings.page == fix.page) & (ratings.rater == fix.rater)
            if not mask.any() and (episodes.page == fix.page).any():
                ratings.loc[len(ratings)] = {
                    "page": fix.page, "rater": fix.rater, "role": HOSTS.get(fix.rater, "guest"),
                    "rating_raw": "", "rating_original": float("nan"),
                    "rating": float("nan"), "rating_note": "added by override"}
                mask = (ratings.page == fix.page) & (ratings.rater == fix.rater)
            target = ratings
        if not mask.any():
            unmatched.append(f"{fix.page} / {fix.rater or '-'} / {fix.field}")
            continue
        fields = ["rating", "rating_original"] if fix.field == "score" else [fix.field]
        for field in fields:
            target.loc[mask, field] = _coerce(fix.value, target[field])
    if unmatched:
        print("overrides that matched nothing:\n  " + "\n  ".join(unmatched))
    return episodes, ratings
