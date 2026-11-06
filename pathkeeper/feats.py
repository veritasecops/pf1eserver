"""Archives of Nethys feat index and non-destructive catalog import."""
from functools import lru_cache
import json
from pathlib import Path

REVIEW_HINT = "See the reference for prerequisites and effects. Confirm eligibility with your GM."


@lru_cache
def table_feats():
    return json.loads((Path(__file__).parent / "data" / "feats.json").read_text())


def merge_feat_index(feats):
    existing = {name.casefold(): name for name in feats}
    merged = dict(feats)
    for name, metadata in table_feats().items():
        key = existing.get(name.casefold())
        if key is None:
            merged[name] = {"enabled": True, "hint": REVIEW_HINT, **metadata}
        else:
            provenance = {field: metadata[field] for field in ("mastery", "pfs_marked", "url") if field in metadata}
            merged[key] = {**provenance, **feats[key]}
            if not merged[key].get("url"):
                merged[key]["url"] = metadata["url"]
    return merged
