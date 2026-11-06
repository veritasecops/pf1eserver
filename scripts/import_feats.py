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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = entries(args.html.read_text())
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(result)} feats")
