## Create a character

Open Characters and select **Add character** to start a new draft. The [character wizard](/help/character-wizard) guides you through a first-level sheet with visual dice, ability scores, race, class, skills, feats, HP, gear, combat values, description, and spells. Your drafts save as you go and appear with a **Draft** badge under **Draft characters** on the Characters page. Click a draft to continue editing it. You can keep multiple unfinished characters; Add character always starts a new one. Drafts remain private to their creator. Existing basic records remain supported.

Every new character belongs to the signed-in creator, including Game Masters and Admins. Choose an optional campaign during creation.

## Own records and GM access

You always have full management access to your own characters. A Game Master gains management access to another user's character only when that user is a joined member and the character is assigned to a campaign owned by that GM.

Joining a campaign alone does not expose all the player's characters. A GM does not gain access to the member's standalone or other-campaign records. Admins can manage every character.

## Edit, move and transfer

Open a character and select **Edit character** for identity, notes, and permitted assignment changes. Wizard-built first-level sheets also offer **Edit creation sheet** for game choices. Their race, class, and level are read-only in the basic editor to protect calculated data. Legacy records retain basic class/level editing. The owner can move an existing character between joined campaigns or choose No campaign. A GM editing someone else's character cannot change its campaign or owner. Admins can change both.

A character assigned to a GM's campaign remains its owner's record. If the player is removed from the campaign, the character detaches and the GM loses access. Campaign deletion also detaches characters rather than deleting them.

## Delete

The character's owner or an Admin can select **Delete character** at the top of the character page, type its name, and confirm. A GM can delete their own characters, but cannot delete another user's character through campaign management access. Deletion is permanent; there is no trash or undo. An Admin deleting the user account also deletes all characters owned by that user.

Character notes are visible to anyone permitted to manage that character. There is no separate private-note visibility field or export/import workflow in this foundation. Concurrent changes are protected by record versions; reload and reapply your changes if a conflict appears.

## Deluxe character sheet

Open a created character to edit the four sheet sections: combat and identity; feats, class and racial abilities and skills; spells; gear and notes. The layout follows pages 2–5 of the supplied deluxe sheet. Save sheet stores the entire form. The save status marks unsaved edits, and leaving the page prompts before discarding them. Print opens the browser's print dialog.

Existing creation values populate the sheet. All displayed character values are editable, including current HP, temporary ability scores, saves, AC components, attacks, armor, resistances, spells at levels 0–9, used spell slots, 56 gear entries, carrying capacity, coins, faction points, and notes. Totals are recorded values: update totals when changing components or equipment. Class-skill markers come from the character's single class. Class skills receive +3 when ranked; every class can rank every skill.

The character's name, race, class, level, and notes use the existing database fields. Migration 005 adds `characters.play_data`, a validated JSON record for the additional fields and overrides. Unchanged creation values continue to come from `sheet_data`; saving play values preserves the creation snapshot and roll history. Manual play edits can record level progression without implementing automatic advancement or multiclassing. The first-level creation wizard remains available for first-level characters.

Owners, administrators, and the assigned campaign's authorized Game Master retain their existing access. Saving requires CSRF validation and the latest record version. A stale form cannot overwrite another edit. Validation errors preserve entered values for correction. Player and campaign text on the sheet are descriptive labels; Manage character controls actual ownership and campaign membership.
