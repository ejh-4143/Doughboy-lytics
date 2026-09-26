"""Minimal wikitext table splitting for the Episodes master list."""

import re

import mwparserfromhell

MASTER_COLUMNS = ["number", "title", "fork_score", "date", "accolades", "notes"]


CELL_ATTRS = re.compile(r'^\s*((?:[a-z-]+\s*=\s*"[^"]*"\s*)+)\|(?!\|)', re.I)


def table_rows(wikitext):
    """Yield each data row of every {| ... |} table as a list of raw cell strings.

    Cells are one per line ("|cell"). Header rows ("!..." cells, or the
    "|#" row the second table uses) are skipped. Cell attributes such as
    rowspan="3" are stripped, and rowspanned cells are repeated into the
    rows they cover so columns stay aligned.
    """
    for table in re.findall(r"^\{\|.*?^\|\}", wikitext, flags=re.S | re.M):
        spans = {}  # column index -> [cell text, rows remaining]
        for block in re.split(r"^\|-.*$", table, flags=re.M)[1:]:
            lines = [ln for ln in block.strip("\n").split("\n") if ln and not ln.startswith("|}")]
            raw_cells = []
            for ln in lines:
                if ln.startswith(("|", "!")):
                    raw_cells.append(ln[1:])
                elif raw_cells:  # continuation of a multi-line cell
                    raw_cells[-1] += "\n" + ln
            cells = []
            for raw in raw_cells:
                while len(cells) in spans:
                    cells.append(_take_span(spans, len(cells)))
                m = CELL_ATTRS.match(raw)
                text = raw[m.end():] if m else raw
                span = re.search(r'rowspan\s*=\s*"(\d+)"', m.group(1)) if m else None
                if span and int(span.group(1)) > 1:
                    spans[len(cells)] = [text, int(span.group(1)) - 1]
                cells.append(text)
            while len(cells) in spans:
                cells.append(_take_span(spans, len(cells)))
            yield cells


def _take_span(spans, col):
    text, remaining = spans[col]
    if remaining <= 1:
        del spans[col]
    else:
        spans[col][1] -= 1
    return text


def master_rows(wikitext):
    """Yield dicts keyed by MASTER_COLUMNS, plus 'page' (the Title link target)."""
    for cells in table_rows(wikitext):
        if len(cells) < len(MASTER_COLUMNS):
            cells = cells + [""] * (len(MASTER_COLUMNS) - len(cells))
        row = {k: v.strip() for k, v in zip(MASTER_COLUMNS, cells)}
        links = mwparserfromhell.parse(row["title"]).filter_wikilinks()
        row["page"] = str(links[0].title).strip() if links else None
        yield row


def plain(text):
    """Wikitext -> display text (link labels, no markup)."""
    return mwparserfromhell.parse(text).strip_code().strip()
