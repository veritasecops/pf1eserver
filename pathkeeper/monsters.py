"""The bundled Archives of Nethys Pathfinder First Edition monster catalog."""
from functools import lru_cache
import json
from pathlib import Path
import re
from string import ascii_uppercase
from urllib.parse import urlencode


@lru_cache(maxsize=1)
def monsters():
    return json.loads((Path(__file__).parent / "data" / "monsters.json").read_text(encoding="utf-8"))


def monster_catalog_filters(params):
    letter = params.get("letter", "").upper()
    letter = letter if len(letter) == 1 and letter in ascii_uppercase else ""
    search = params.get("q", "").strip()[:100]
    raw_page = params.get("page", "")
    page = int(raw_page) if re.fullmatch(r"[1-9][0-9]{0,5}", raw_page) else 1
    return letter, search, page


def monster_catalog_context(params):
    letter, search, page = monster_catalog_filters(params)
    term = search.casefold()
    items = []
    for key, monster in monsters().items():
        matches = [row for row in monster["rows"] if (not letter or row["letter"] == letter)
                   and term in " ".join((row["name"], row["type"], row["environment"])).casefold()]
        if matches:
            items.append((key, matches[0]))
    items.sort(key=lambda entry: (entry[1]["name"].casefold(), entry[0]))
    total = len(items)
    pages = max(1, (total + 49) // 50)
    page = min(page, pages)
    query = urlencode({"letter": letter, "q": search})
    letter_links = [
        (label or "All", "?" + urlencode({"letter": label, "q": search}))
        for label in ("", *ascii_uppercase)
    ]
    return {
        "letter": letter, "letter_links": letter_links, "selected_letter": letter or "All", "search": search,
        "items": items[(page - 1) * 50:page * 50], "total": total, "page": page, "pages": pages,
        "query": query, "back_query": urlencode({"letter": letter, "q": search, "page": page}),
    }
