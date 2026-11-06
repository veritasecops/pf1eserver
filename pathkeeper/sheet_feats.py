"""Removal of feats recorded on the play sheet or during advancement."""
from collections import Counter
from decimal import Decimal

from fastapi import HTTPException

from . import level_up
from .feature_links import feature_targets, normalized
from .rule_catalog import character_catalog


def removable_rows(character, values, catalog, ability_blocks):
    computed = (character.sheet_data or {}).get("computed", {})
    fixed = {
        normalized(entry["name"] + (f" ({entry['choice']})" if entry.get("choice") else ""))
        for entry in computed.get("feats", [])
    }
    fixed.update(normalized(name) for name in computed.get("automatic_feats", []))
    feat_names = {normalized(name): name for name in catalog["feats"]}
    feat_names.update({normalized(name): name for name in character_catalog(character)["feats"]})
    rows = {}
    for row in range(56):
        if row in ability_blocks["slots"]:
            continue
        label = normalized(values[f"feature.{row}"])
        if label in fixed:
            continue
        name = feat_names.get(label)
        if not name and label.endswith(")") and " (" in label:
            name = feat_names.get(label.rsplit(" (", 1)[0])
        if name:
            rows[row] = name
    return rows


def remove_feat(character, values, catalog, row, name):
    data = dict(character.play_data or {})
    history = data.get("advancement_history", [])
    feats = {**catalog["feats"], **character_catalog(character)["feats"]}
    targets = feature_targets(catalog)
    label = values[f"feature.{row}"]
    matches = []
    for record_index, record in enumerate(history):
        for choice_index, choice in enumerate(record["choices"]):
            if "feat" not in choice["feature"].casefold() or normalized(choice["choice"]) != normalized(name):
                continue
            display = choice["choice"]
            if target := choice.get("target"):
                kind = feats.get(name, {}).get("choice")
                display += f" ({targets.get(kind, {}).get(target, target)})"
            matches.append((record_index, choice_index, choice, normalized(display) == normalized(label)))

    rules = level_up.sheet_feat_context(character, catalog, values)
    copies = sum(normalized(feat) == normalized(name) for feat, _ in rules["owned_feats"])
    if copies <= 1:
        dependent = next((feat for feat, _ in rules["owned_feats"]
                          if normalized(feats.get(feat, {}).get("requires", "")) == normalized(name)), None)
        if dependent:
            raise HTTPException(422, f"Remove {dependent} first. It requires {name}.")

    found = next((match for match in matches if match[3]), None)
    if found:
        record_index, choice_index, choice, _ = found
        record = history[record_index]
        updated = {**record, "choices": [item for i, item in enumerate(record["choices"]) if i != choice_index]}
        later = history[record_index + 1:]
        applied = choice.get("sheet_adjustments")
        if applied is None and found == matches[0]:
            applied = level_up.feat_adjustments(feats.get(name, {}), choice, record["level"])
        if applied is not None:
            adjustments = Counter()
            for key, amount in applied:
                adjustments[key] += amount
            updated["hp"] -= adjustments["hp.total"]
            if normalized(name) == "toughness" and adjustments["hp.total"]:
                growth = sum(item["level"] > 3 for item in later)
                adjustments["hp.total"] += growth
                adjustments["hp.current"] += growth
                later = [{**item, "hp": item["hp"] - 1} if item["level"] > 3 else item for item in later]
            for key, amount in adjustments.items():
                if amount and key in values:
                    data[key] = str(Decimal(values[key] or 0) - amount)
        if found == matches[0]:
            # The wizard only applied modifiers to the first copy of a feat.
            later = [{**item, "choices": [
                {**entry, "sheet_adjustments": []}
                if "feat" in entry["feature"].casefold() and normalized(entry["choice"]) == normalized(name)
                and "sheet_adjustments" not in entry else entry
                for entry in item["choices"]
            ]} for item in later]
        data["advancement_history"] = [*history[:record_index], updated, *later]
    data[f"feature.{row}"] = ""
    character.play_data = data
