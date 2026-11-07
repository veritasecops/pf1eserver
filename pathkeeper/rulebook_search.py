"""Role-filtered page search and escaped excerpts."""
import re
from urllib.parse import urlencode

from markupsafe import Markup, escape
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import match

from .models import RULEBOOK_ROLE_BITS, Rulebook, RulebookIndex, RulebookPage
from .rulebook_indexer import normalize
from .ui import render


def query_terms(query):
    expressions, highlights = [], []
    for token in re.finditer(r'"([^"]+)"|(\w+)', normalize(query)):
        words = re.findall(r"\w+", token[1] or token[2], re.UNICODE)
        if any(not 2 <= len(word) <= 84 for word in words):
            raise ValueError("Search terms must contain 2 to 84 letters or digits.")
        phrase = " ".join(words)
        expressions.append('+"' + phrase + '"' if token[1] else "+" + phrase)
        highlights.append(phrase)
    if not expressions or len(expressions) > 12:
        raise ValueError("Enter between 1 and 12 search terms. Use quotes around a phrase.")
    return " ".join(expressions), highlights


def excerpt(text, terms):
    text = " ".join(text.split())
    pattern = re.compile("|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True)), re.IGNORECASE)
    first = pattern.search(text)
    start = max(0, first.start() - 100) if first else 0
    snippet = text[start:start + 360]
    parts, previous = [], 0
    for hit in pattern.finditer(snippet):
        parts.extend((escape(snippet[previous:hit.start()]), Markup("<mark>"), escape(hit[0]), Markup("</mark>")))
        previous = hit.end()
    parts.append(escape(snippet[previous:]))
    return Markup("… " if start else "") + Markup("").join(parts) + Markup(" …" if start + 360 < len(text) else "")


def search_page(ctx, categories, book=None):
    params = ctx.request.query_params
    query = params.get("q", "").strip()[:200]
    category = params.get("category", "")
    category = category if category in categories else ""
    allowed = [Rulebook.access_mask.bitwise_and(RULEBOOK_ROLE_BITS[ctx.user.role]) != 0]
    if category:
        allowed.append(Rulebook.category == category)
    if book:
        allowed.append(Rulebook.id == book.id)
    raw_page = params.get("page", "")
    page = int(raw_page) if re.fullmatch(r"[1-9][0-9]{0,5}", raw_page) else 1
    rows, titles, total, pages, error = [], [], 0, 1, ""
    if query:
        try:
            boolean, terms = query_terms(query)
            title_query = select(Rulebook).where(*allowed, Rulebook.title.contains(query.strip('"'), autoescape=True))
            titles = ctx.db.scalars(title_query.order_by(Rulebook.title).limit(20)).all() if not book else []
            rank = match(RulebookPage.search_text, against=" ".join(terms))
            found = match(RulebookPage.search_text, against=boolean).in_boolean_mode()
            base = (select(Rulebook, RulebookPage, rank.label("rank"))
                    .join(RulebookPage, RulebookPage.book_id == Rulebook.id)
                    .join(RulebookIndex, (RulebookIndex.book_id == Rulebook.id) &
                          (RulebookIndex.active_generation == RulebookPage.generation))
                    .where(*allowed, found > 0))
            total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
            pages = max(1, (total + 49) // 50)
            page = min(page, pages)
            for result_book, result_page, _ in ctx.db.execute(
                base.order_by(rank.desc(), Rulebook.id, RulebookPage.page).offset((page - 1) * 50).limit(50)
            ):
                rows.append({"book": result_book, "page": result_page.page,
                             "snippet": excerpt(result_page.body, terms), "ocr": result_page.method == "ocr"})
        except ValueError as failure:
            error = str(failure)
    pending = ctx.db.scalar(select(func.count()).select_from(Rulebook).outerjoin(RulebookIndex)
                            .where(*allowed, (RulebookIndex.book_id.is_(None)) |
                                   (RulebookIndex.status != "ready")))
    url_query = urlencode({"q": query, "category": category, "book": book.id if book else ""})
    return render(ctx, "rulebook_search.html", title="Search rulebooks", query=query, category=category,
                  categories=categories, book=book, results=rows, title_matches=titles,
                  total=total, page=page, pages=pages, pagination_query=url_query, pending=pending, error=error)
