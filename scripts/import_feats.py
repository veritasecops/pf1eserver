"""Convert a saved AoN General Feats index into the catalog seed data."""
import argparse
import html
import json
from pathlib import Path
import re
from urllib.parse import quote

SOURCE = "https://www.aonprd.com/FeatDisplay.aspx?ItemName="
ROW = re.compile(
    r'<tr\b[^>]*>\s*<td[^>]*>\s*<a href="FeatDisplay\.aspx\?ItemName=([^"]+)">(.*?)</a>\s*</td>\s*<td[^>]*>(.*?)</td>',
    re.IGNORECASE | re.DOTALL,
)


def entries(page):
    feats = {}
    for name, label, prerequisites in ROW.findall(page):
        pfs_marked = 'title="PFS Legal"' in label
        name = html.unescape(name)
        label = html.unescape(re.sub(r"<[^>]*>", "", label)).strip()
        if label.rstrip("*⊤ ") != name or name.casefold() in feats:
            raise ValueError(f"Unexpected or duplicate feat row: {label}")
        marker = label[len(name):]
        mastery = {1: "armor", 2: "shield", 3: "weapon"}.get(marker.count("⊤"))
        requirements = {}
        plain = html.unescape(re.sub(r"<[^>]*>", "", prerequisites)).strip()
        for part in plain.split(","):
            ability = re.fullmatch(r"(Str|Dex|Con|Int|Wis|Cha) (\d+)", part.strip(), re.IGNORECASE)
            bab = re.fullmatch(r"base attack bonus \+(\d+)", part.strip(), re.IGNORECASE)
            if ability:
                requirements[ability[1].lower()] = int(ability[2])
            elif bab:
                requirements["bab"] = int(bab[1])
            else:
                requirements.clear()
                break
        feats[name.casefold()] = (name, {
            "url": SOURCE + quote(name, safe=""),
            **({"combat": True} if "*" in marker else {}),
            **({"mastery": mastery} if mastery else {}),
            **({"pfs_marked": True} if pfs_marked else {}),
            **requirements,
        })
    if not feats:
        raise ValueError("No feat rows found.")
    return dict(sorted(feats.values(), key=lambda entry: entry[0].casefold()))


def apply_categories(feats, directory):
    index = (directory / "General.html").read_text().split('id="MainContent_FeatLabel2"')[0]
    links = dict((label, href) for href, label in re.findall(
        r'href="(Feats\.aspx\?Category=[^"]*|CombatStamina\.aspx)"[^>]*>([^<]+)</a>', index
    ))
    table_row = r'<tr\b[^>]*>\s*<td\b[^>]*>\s*(?:<font\b[^>]*>\s*)?<a href="FeatDisplay\.aspx\?ItemName=([^"]+)"'
    related_feat = r'<b>Related Feat</b>\s*<u><a href="FeatDisplay\.aspx\?ItemName=([^"]+)"'
    for label in links:
        page = (directory / f"{label}.html").read_text()
        pattern = related_feat if label == "Combat Stamina" else table_row
        names = {html.unescape(name) for name in re.findall(pattern, page, re.IGNORECASE)}
        if not names or names - feats.keys():
            raise ValueError(f"Unexpected feat membership for {label}: {sorted(names - feats.keys())}")
        if label != "General":
            for name in names:
                feats[name].setdefault("categories", []).append(label)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--categories", type=Path, help="Directory of saved AoN category pages")
    args = parser.parse_args()
    result = entries(args.html.read_text())
    if args.categories:
        apply_categories(result, args.categories)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(result)} feats")
