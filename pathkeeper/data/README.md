# Weapon catalog facts

`weapons.json` contains 486 records from the Archives of Nethys weapon index
and linked detail pages. Index membership supplies the proficiency filter.
The detail page supplies the category and its own proficiency when published.
These fields can differ, as with a One-Handed pistol listed under Firearms
whose detail page reports Exotic proficiency. The tri-bladed katar appears
under both Martial and Exotic.

The catalog records published cost, weight, damage, critical, range, damage
type, special qualities, sources, weapon groups, and additional statistics
such as misfire, capacity, crew, and load. Weapon descriptions are excluded.
Numeric costs use copper pieces and numeric weights use pounds. Variable
amounts keep their published text. Existing item IDs, composite Strength
variants, and both sawtooth sabre printings are retained.

`scripts/import_aon_weapons.py` converts cached detail pages using a manifest
that maps detail URLs to filenames and index memberships.
Migration 023 refreshes the live catalog and uses
`weapon_refresh_baseline.json` to distinguish changed source defaults from
local statistical overrides. The migration preserves character inventory and
creation snapshots.

`aon_reference_links.json` records verified replacements for 279 weapon/ammunition entries, 72 armor entries, and 23 class options. Destinations were checked against AoN indexes and item pages on November 4, 2026. Different names include Aldori dueling sword, Shoanti bolas, Varisian dancing scarves, Erutaki coat, and Alkenstar fortress plate. Unarmed strike links to the weapon descriptions in the AoN legacy Core Rulebook. Five shield boss variants share a description page containing all five variants. Omdura and Vampire Hunter were removed from the selectable classes in migration 014. The legacy URL paths support migration 013; they are not outbound application links.
