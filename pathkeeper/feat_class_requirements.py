"""Check AoN class prerequisites against the advancement being planned."""
import re
from functools import lru_cache

from .feats import table_feats
from .class_catalog import class_profile
from .pf1_data import CLASSES

CLASS_LEVEL = re.compile(r"(.+?) level (\d+)(?:st|nd|rd|th)")
BAB = re.compile(r"base attack bonus \+(\d+)")
NEGATIVE = re.compile(r"(?:you have )?no levels in a class that has the (.+)")
FEATURE_SUFFIX = re.compile(r"\s+(?:\+?\d.*|\(ex\)|\(su\)|\(sp\))$")
DISCOVERY = re.compile(r"(.+?) (alchemist )?discovery")


def normalized(text):
    return " ".join(text.casefold().replace("’", "'").strip(" .").split())


@lru_cache
def indexed_requirements():
    return {name.casefold(): tuple(item["class_requirements"])
            for name, item in table_feats().items() if item.get("class_requirements")}


def class_feat_gate(character, catalog, classes, bab, owned_feats):
    features = set()
    levels_by_name = {}
    for key, count in classes.items():
        profile = class_profile(catalog, key)
        for name in (profile["name"], CLASSES[key]["name"], CLASSES[key.removesuffix("-unchained")]["name"]):
            levels_by_name[normalized(name)] = max(count, levels_by_name.get(normalized(name), 0))
        for level in profile["levels"][:count]:
            for feature in re.split(r",\s*(?![^()]*\))", level["features"]):
                name = normalized(feature)
                features.update((name, FEATURE_SUFFIX.sub("", name)))
    history = (character.play_data or {}).get("advancement_history", ())
    discoveries = {normalized(choice["choice"]) for entry in history for choice in entry["choices"]
                   if choice["feature"].casefold() == "discovery"}
    owned = {normalized(name) for name, _ in owned_feats}

    def matches(option):
        option = option.removeprefix("the ").removesuffix(" feat")
        option, feature_required = re.subn(r"\s*class\s*feature$", "", option)
        if match := CLASS_LEVEL.fullmatch(option):
            return levels_by_name.get(match[1], 0) >= int(match[2])
        if match := BAB.fullmatch(option):
            return bab >= int(match[1])
        if match := DISCOVERY.fullmatch(option):
            return (not match[2] or "alchemist" in classes) and match[1] in discoveries
        return option in features or (not feature_required and option in owned)

    def meets(clause):
        clause = normalized(clause)
        if negative := NEGATIVE.fullmatch(clause):
            return not matches(negative[1])
        return any(matches(option) for option in re.split(r"\s+or\s+", clause))

    return {name for name, clauses in indexed_requirements().items() if not all(map(meets, clauses))}
