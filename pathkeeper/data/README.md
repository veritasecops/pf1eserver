# Weapon table facts

`weapons.json` contains the Simple, Martial, and Exotic tables from
the d20PFSRD weapon tables, inspected November 4, 2026.

The 279 rows comprise 243 weapon entries and 36 ammunition entries:

| Proficiency | Weapons | Ammunition |
| --- | ---: | ---: |
| Simple | 42 | 8 |
| Martial | 90 | 21 |
| Exotic | 111 | 7 |

Reference URLs now point to the corresponding Archives of Nethys entries,
including its miscellaneous equipment pages for alchemical ammunition and armor
extras. Other weapon lists (firearms, Eastern weapons, historical lists,
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

`aon_reference_links.json` records verified replacements for 279 weapon/ammunition entries, 72 armor entries, and 23 class options. Destinations were checked against AoN indexes and item pages on November 4, 2026. Different names include Aldori dueling sword, Shoanti bolas, Varisian dancing scarves, Erutaki coat, and Alkenstar fortress plate. Unarmed strike links to the weapon descriptions in the AoN legacy Core Rulebook. Five shield boss variants share a description page containing all five variants. Omdura and Vampire Hunter were removed from the selectable classes in migration 014. The legacy URL paths support migration 013; they are not outbound application links.
