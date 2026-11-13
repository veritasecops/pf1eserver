"""Build the PF1 monster catalog from cached Archives of Nethys HTML.

The input directory contains A.html through Z.html and details/<sha256>.html,
where the hash is of the decoded ItemName. Store stat-block fields and rule
references. Source links cover descriptive prose and artwork.
"""
import argparse
from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re
from string import ascii_uppercase
from urllib.parse import quote, unquote


BASE = "https://www.aonprd.com/"
MONSTER_LINK = re.compile(r'<a\b[^>]*href="MonsterDisplay\.aspx\?ItemName=([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
BLOCK = re.compile(r'<span id="MainContent_DataListFeats_Label1_\d+"[^>]*>(.*?)(?=</span>\s*</td>)', re.S | re.I)
HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.S | re.I)
BOLD = re.compile(r"<b\b[^>]*>(.*?)</b>", re.S | re.I)
LINES = re.compile(r"<br\s*/?>|</(?:p|li|tr)>", re.I)
STAT_SECTIONS = {
    "overview", "defense", "offense", "statistics", "ecology", "base statistics", "environment",
}
MECHANICS = re.compile(
    r"\b(?:DC\s*\d+|[+-]?\d+d\d+(?:[+-]\d+)?|\d+(?:/\d+)?/(?:day|round|week)"
    r"|\d+(?:[-–]\d+)?\s+(?:ft\b|rounds?\b|minutes?\b|hours?\b|days?\b|gp\b|hp\b))", re.I
)


def plain(html):
    html = re.sub(r'<img\b[^>]*\balt="([^"]*)"[^>]*>', r"\1", html, flags=re.I)
    html = LINES.sub(" ", html)
    return " ".join(unescape(re.sub(r"<[^>]*>", "", html)).split())


def index_entries(html, letter):
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S | re.I)
        if len(cells) != 4 or not (link := MONSTER_LINK.search(cells[0])):
            continue
        item = unquote(unescape(link[1]))
        name = plain(link[2])
        cr, creature_type, environment = map(plain, cells[1:])
        yield item, {"letter": letter, "name": name, "cr": cr, "type": creature_type,
                     "environment": environment}


def field(label, value, section):
    if not value:
        return [label, ""]
    if label == "Source" or section in STAT_SECTIONS or len(value.split()) <= 5:
        return [label, value]
    facts = list(dict.fromkeys(MECHANICS.findall(value)))
    if facts or label:
        return [label, " · ".join(facts)]
    return None


def section_fields(html, section):
    if section.startswith('creatures in "') and section.endswith('" category'):
        return [[plain(name), plain(cr)] for name, cr in re.findall(
            r"<td\b[^>]*>\s*<a\b[^>]*>(.*?)</a>\s*</td>\s*<td\b[^>]*>(.*?)</td>", html, re.S | re.I)]
    fields = []
    # Nested headings and table columns remain individually readable.
    html = re.sub(r"</t[dh]>\s*<t[dh]\b[^>]*>", " | ", html, flags=re.I)
    for line in LINES.split(html):
        labels = list(BOLD.finditer(line))
        if labels:
            leading = plain(line[:labels[0].start()])
            if leading and (entry := field("", leading, section)):
                fields.append(entry)
            for index, label in enumerate(labels):
                end = labels[index + 1].start() if index + 1 < len(labels) else len(line)
                value = plain(line[label.end():end]).rstrip(";, ")
                if entry := field(plain(label[1]), value, section):
                    fields.append(entry)
        elif (value := plain(line)) and (entry := field("", value, section)):
            fields.append(entry)
    return fields


def detail_sections(html):
    sections = []
    for block in BLOCK.findall(html):
        headings = list(HEADING.finditer(block))
        for index, heading in enumerate(headings):
            title = plain(heading[2])
            if not title:
                continue
            end = headings[index + 1].start() if index + 1 < len(headings) else len(block)
            body = block[heading.end():end]
            group = "overview" if heading[1] == "2" and re.search(r"\bCR\s", title) else title.casefold()
            sections.append({"heading": title, "level": int(heading[1]), "fields": section_fields(body, group),
                             **({"source_detail": True} if group not in STAT_SECTIONS else {})})
    return sections


def convert(directory):
    entries = {}
    for letter in ascii_uppercase:
        rows = list(index_entries((directory / f"{letter}.html").read_text(encoding="utf-8"), letter))
        if not rows:
            raise ValueError(f"No monster rows in letter {letter}")
        for item, row in rows:
            key = sha256(item.encode()).hexdigest()
            record = entries.setdefault(key, {
                "url": BASE + "MonsterDisplay.aspx?ItemName=" + quote(item, safe=""),
                "rows": [],
            })
            if row not in record["rows"]:
                record["rows"].append(row)

    for key, record in entries.items():
        path = directory / "details" / f"{key}.html"
        sections = detail_sections(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else []
        record["sections"] = sections
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    entries = convert(args.cache)
    missing = [record["url"] for record in entries.values() if not record["sections"]]
    args.output.write_text(
        "{\n" + ",\n".join(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
                            for key, value in entries.items()) + "\n}\n", encoding="utf-8"
    )
    print(f"{len(entries)} monsters, {len(missing)} without parsed details")
    for url in missing:
        print(url)


if __name__ == "__main__":
    main()
