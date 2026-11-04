import html
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from .config import ROOT
from .ui import templates

router = APIRouter()
GUIDES = [
    ("getting-started", "Getting started", "Accounts, your workspace, and the first Admin.", "Start here"),
    ("signup", "Create a Player account", "Sign up, choose a password, and join your first campaign.", "Start here"),
    ("two-factor", "Authenticator & recovery codes", "Enroll TOTP, sign in, replace codes, and recover access.", "Using Pathkeeper"),
    ("profile", "Login & profile", "Passwords, profiles, sessions, and account access.", "Using Pathkeeper"),
    ("administration", "Administration", "Create, edit, disable, and delete users safely.", "Administration"),
    ("email", "Email configuration & delivery", "Connect Brevo or SMTP, protect credentials, and test delivery.", "Administration"),
    ("account-email", "Account emails & password recovery", "Welcome, email verification, setup links, and password recovery.", "Using Pathkeeper"),
    ("roles", "Roles & permissions", "Player, Game Master, Admin, and campaign boundaries.", "Administration"),
    ("invitations", "Campaign invitations", "Email-bound, expiring links and member removal.", "Using Pathkeeper"),
    ("campaigns", "Campaign management", "Create, edit, transfer, and delete campaigns.", "Using Pathkeeper"),
    ("characters", "Character management", "Ownership, campaign assignment, editing, and deletion.", "Using Pathkeeper"),
    ("character-wizard", "Character wizard & visual dice", "Create a first-level sheet, save drafts, and roll polyhedral dice.", "Using Pathkeeper"),
    ("installation", "Install a new instance", "uv-managed Python, MariaDB, Uvicorn, and the system service.", "Server administration"),
    ("hosting", "Hosting & configuration", "Reverse proxy, TLS, encrypted secrets, and server files.", "Server administration"),
    ("maintenance", "Backups, recovery & maintenance", "Protect data and keys, inspect logs, and recover an Admin.", "Server administration"),
    ("troubleshooting", "Troubleshooting", "Sign-in errors, code problems, permissions, and service failures.", "Reference"),
]


def articles():
    return [{"slug": slug, "title": title, "summary": summary, "category": category,
             "text": (ROOT / "docs" / f"{slug}.md").read_text()} for slug, title, summary, category in GUIDES]


def inline(value):
    value = html.escape(value)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    return re.sub(r"\[([^\]]+)\]\((/help/[a-z-]+)\)", r'<a href="\2">\1</a>', value)


def markdown(value):
    result, toc, paragraph, code, used = [], [], [], None, {}
    in_list = False

    def flush():
        if paragraph:
            result.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    for line in value.splitlines():
        if line.startswith("```"):
            flush()
            if in_list:
                result.append("</ul>")
                in_list = False
            if code is None:
                code = []
            else:
                result.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
                code = None
            continue
        if code is not None:
            code.append(line)
            continue
        if line.startswith("- "):
            flush()
            if not in_list:
                result.append("<ul>")
                in_list = True
            result.append("<li>" + inline(line[2:]) + "</li>")
            continue
        if in_list:
            result.append("</ul>")
            in_list = False
        if line.startswith("## "):
            flush()
            title = line[3:]
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "section"
            used[slug] = used.get(slug, 0) + 1
            anchor = slug + (f"-{used[slug]}" if used[slug] > 1 else "")
            result.append(f'<h2 id="{anchor}">{inline(title)}</h2>')
            toc.append((anchor, title))
        elif not line.strip():
            flush()
        else:
            paragraph.append(line.strip())
    flush()
    if in_list:
        result.append("</ul>")
    if code is not None:
        result.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
    return "\n".join(result), toc


def public_help(request, **data):
    return templates.TemplateResponse(request=request, name="help.html", context={
        "user": None, "csrf": "", "flash": None, "limited": False, "path": request.url.path,
        "title": "Help & guides", "guides": articles(), "guide": None, "query": "", **data})


@router.get("/help")
async def help_index(request: Request):
    query = request.query_params.get("q", "")[:100].strip()
    guides = articles()
    if query:
        terms = re.findall(r"\w+", query.casefold())
        ranked = []
        for article in guides:
            haystack = (article["title"] + " " + article["summary"] + " " + article["text"]).casefold()
            hits = sum(term in haystack for term in terms)
            if hits:
                score = hits + (100 if hits == len(terms) else 0) + sum(10 for term in terms if term in article["title"].casefold())
                ranked.append((score, article))
        guides = [article for _, article in sorted(ranked, key=lambda pair: -pair[0])]
    return public_help(request, title="Help & guides", results=guides, query=query)


@router.get("/help/manual.md")
async def manual():
    content = "# Pathkeeper administration & authentication manual\n\n"
    content += "\n\n---\n\n".join(f'# {article["title"]}\n\n{article["text"]}' for article in articles())
    return PlainTextResponse(content, headers={"Content-Disposition": 'attachment; filename="pathkeeper-manual.md"'})


@router.get("/help/print")
async def manual_print(request: Request):
    return public_help(request, title="Pathkeeper manual", manual=[(article, markdown(article["text"])[0]) for article in articles()])


@router.get("/help/{slug}")
async def help_article(slug: str, request: Request):
    article = next((article for article in articles() if article["slug"] == slug), None)
    if not article:
        raise HTTPException(404, "Help article not found.")
    body, toc = markdown(article["text"])
    return public_help(request, title=article["title"], guide=article, body=body, toc=toc)
