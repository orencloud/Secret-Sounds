"""Preserve saved themes while introducing newly shipped themes and cues."""

from copy import deepcopy


def freeze(themes, triggers, fallback):
    """Store the actual clips behind today's implicit defaults before updating."""
    result = deepcopy(themes)
    for theme in result:
        operations = theme["operations"]
        for key in triggers:
            entry = operations.setdefault(key, {"clips": ["@default"], "enabled": True})
            entry["clips"] = [fallback[key] if clip == "@default" else clip for clip in entry["clips"]]
    return result


def merge(themes, known, bundled, triggers, fallback):
    result = deepcopy(themes)
    names = {theme["name"].casefold() for theme in result}
    incoming = {theme["name"].casefold(): theme for theme in bundled}
    new_keys = set(triggers) - set(known["triggers"])
    for theme in result:
        name = theme["name"].casefold()
        default = incoming.get(name, bundled[0])
        for key in new_keys:
            entry = default["operations"].get(key, {"clips": [fallback[key]], "enabled": True})
            theme["operations"].setdefault(key, deepcopy(entry))
    for name, theme in incoming.items():
        if name not in names and name not in known["themes"]:
            result.append(deepcopy(theme))
    return result


def inventory(bundled, triggers, previous=None):
    return {
        "themes": sorted(set((previous or {}).get("themes", ())) | {t["name"].casefold() for t in bundled}),
        "triggers": sorted(set((previous or {}).get("triggers", ())) | set(triggers)),
    }
