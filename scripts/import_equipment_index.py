"""Build the admin equipment index from saved Archives of Nethys pages."""
import argparse
import html
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, quote, unquote, urlsplit

ROOT = "https://www.aonprd.com/"
GROUPS = {
    "EquipmentWeapons": "Weapons", "EquipmentArmor": "Armor",
    "SpecialMaterials": "Special Materials", "EquipmentMisc": "Miscellaneous",
}
ROW = re.compile(r"<tr\b[^>]*>((?:(?!<tr\b).)*?)</tr>", re.I | re.S)
CELL = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.I | re.S)
ITEM = re.compile(r'href="((?:Equipment(?:Weapons|Armor|Misc)Display|SpellbookDisplay|Vehicles)\.aspx\?ItemName=[^"]+)"', re.I)
MISC_BRANCHES = {"AlchemicalReagents.aspx", "FungalGrafts.aspx", "Spellbooks.aspx", "Vehicles.aspx?ItemName=All"}
HEADING = re.compile(r'<span id="MainContent_DataListTypes_LabelName_\d+"><h2\b[^>]*>(.*?)</h2>(.*?)(?=<span id="MainContent_DataListTypes_LabelName_|\Z)', re.S)


def clean(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def entry_key(group, name):
    return re.sub(r"[^a-z0-9]+", "-", f"{group}-{name}".lower()).strip("-")


def add(entries, item):
    key = entry_key(item["group"], item["name"])
    if key in entries and entries[key]["url"] != item["url"]:
        suffix = entry_key("", unquote(urlsplit(item["url"]).query or urlsplit(item["url"]).fragment))
        key = f"{key}-{suffix}"
    if key in entries:
        if entries[key]["url"] != item["url"]:
            raise ValueError(f"Conflicting entry: {item}")
        previous = entries[key]
        previous["categories"] = list(dict.fromkeys(previous["categories"] + item["categories"]))
        for field in ("cost_text", "weight_text", "details"):
            if not previous[field]:
                previous[field] = item[field]
    else:
        entries[key] = item


def table_entries(page, group, category):
    headers = []
    for row in ROW.findall(page):
        cells = CELL.findall(row)
        if not cells:
            continue
        if re.search(r"<th\b", row, re.I):
            headers = [clean(cell) for cell in cells]
        link = ITEM.search(cells[0])
        if not link:
            continue
        href = html.unescape(link[1])
        values = dict(zip(headers[1:], (clean(cell) for cell in cells[1:])))
        cost = values.pop("Cost", values.pop("Price", ""))
        weight = values.pop("Weight", "")
        details = "\n".join(f"{key}: {value}" for key, value in values.items() if key and value)
        yield dict(name=clean(cells[0]), url=ROOT + quote(href, safe="/?=&%"), group=group,
                   categories=[category], cost_text=cost, weight_text=weight, details=details)


def heading_entries(page, group, category, source):
    headings = HEADING.findall(page)
    if source == "FungalGrafts.aspx":
        headings = re.findall(r'<h2 class="title">([^<]+)</h2>(.*?)</span>', page, re.S)
    for heading, body in headings:
        name = clean(heading)
        price = re.search(r"<b>Price</b>\s*([^;<]+)", body)
        weight = re.search(r"<b>Weight</b>\s*([^<]+)", body)
        # These pages publish the descriptions inline without individual URLs.
        url = f"{ROOT}{source}#:~:text={quote(name, safe='')}"
        cost = clean(price[1]) if price else ""
        if group == "Special Materials":
            rows = [[clean(cell) for cell in CELL.findall(row)] for row in ROW.findall(body)]
            cost = "; ".join(f"{label} {amount}" for label, amount in rows
                             if re.match(r"^[+×]?[\d.,]", amount)) if rows and all(len(row) == 2 for row in rows) else ""
        yield dict(name=name, url=url, group=group, categories=[category],
                   cost_text=cost, weight_text=clean(weight[1]) if weight else "", details="")


def load(directory):
    entries = {}
    for file, group in GROUPS.items():
        index = (directory / f"{file}.html").read_text()
        if file == "SpecialMaterials":
            for item in heading_entries(index, group, group, "SpecialMaterials.aspx"):
                add(entries, item)
            continue
        for href, label in re.findall(r'href="([^"]+)"[^>]*><b>([^<]+)</b></a>', index):
            if not href.startswith(file + ".aspx?") and (file != "EquipmentMisc" or href not in MISC_BRANCHES):
                continue
            category = html.unescape(label)
            page = (directory / f"{file}--{category.replace('/', '_')}.html").read_text()
            items = list(heading_entries(page, group, category, href) if href in {"AlchemicalReagents.aspx", "FungalGrafts.aspx"}
                         else table_entries(page, group, category))
            if not items:
                raise ValueError(f"No entries found for {group} / {category}")
            print(f"{group} / {category}: {len(items)} rows")
            for item in items:
                if category == "Vehicles":
                    name = parse_qs(urlsplit(item["url"]).query)["ItemName"][0]
                    detail = directory / "vehicle-details" / f"{name}.html"
                    if detail.exists():
                        price = re.search(r"<b>Cost</b>\s*([^<]+)", detail.read_text())
                        if price:
                            item["cost_text"] = clean(price[1])
                add(entries, item)
    return dict(sorted(entries.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    entries = load(args.directory)
    args.output.write_text("{\n" + ",\n".join(f"  {json.dumps(key)}: {json.dumps(item, ensure_ascii=False)}"
                                                 for key, item in entries.items()) + "\n}\n")
    print(f"{len(entries)} unique catalog entries")
