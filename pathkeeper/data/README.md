# Weapon table facts

`weapons.json` contains the Simple, Martial, and Exotic tables from
https://www.d20pfsrd.com/equipment/weapons, inspected November 4, 2026.

The 279 rows comprise 243 weapon entries and 36 ammunition entries:

| Proficiency | Weapons | Ammunition |
| --- | ---: | ---: |
| Simple | 42 | 8 |
| Martial | 90 | 21 |
| Exotic | 111 | 7 |

Each reference URL is the link attached to the weapon name in its source row,
including links to ammunition, armor, and tool pages where the original table
uses them. Other weapon lists (firearms, Eastern weapons, historical lists,
third-party lists) and example weapons elsewhere on the page are excluded.
No weapon-description prose is copied.

All source columns are retained: name, cost, Small/Medium damage, critical,
range, weight, damage type, special qualities, and publication code. Footnote
markers distinguish the AA1 and AG sawtooth sabre printings. Double-weapon
values, flat damage, em-dash entries, and `see text` values are preserved.

Numeric costs use copper pieces; numeric weights use pounds. `cost_text` and
`weight_text` retain the published qualifiers. A null numeric value means the
source requires an actual price or weight to be adjudicated. A published dash
means zero cost or negligible weight. Compound prices and additional costs are
not converted to a guessed number. Ammunition remains equipment and is excluded
from weapon feat choices.

Category and flags describe supported calculations. Melee weapons with a
thrown range retain their melee default attack. Ranged thrown weapons and
slings add Strength to damage. Composite bow ratings cap positive Strength
bonuses and impose the mismatch attack penalty. Conditional special qualities,
proficiency, individual ends of double weapons, and per-use ammunition effects
remain manual.

Existing identifiers for the original weapons and common arrows/bolts are
preserved. Aliases connect earlier names such as `Shortsword` and `Light
crossbow` to their current table entries. Migration 010 adds new entries and
source facts while preserving administrative overrides and custom entries;
it does not replace character snapshots. Reference links use live catalog URLs.

`scripts/import_weapon_tables.py` builds this JSON from a DOM table export
containing cell text, footnotes, and anchor URLs. It accepts only headers for
the three requested proficiencies and rejects duplicate identifiers or columns.
