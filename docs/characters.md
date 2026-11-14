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

The character's owner or an Admin can select **Delete character** at the bottom of the character page to open a confirmation dialog, type its name, and confirm. Cancel or Escape closes the dialog. Manage character is also at the bottom; ownership, campaign information, and navigation share the compact toolbar below the character name. A GM can delete their own characters, but cannot delete another user's character through campaign management access. Deletion is permanent; there is no trash or undo. An Admin deleting the user account also deletes all characters owned by that user.

Character notes are visible to anyone permitted to manage that character. There is no separate private-note visibility field or export/import workflow in this foundation. Concurrent changes are protected by record versions; reload and reapply your changes if a conflict appears.

## Deluxe character sheet

Use **Add Class Ability** to choose a progression feature from the character’s class catalog. The picker shows Archives of Nethys links and the class levels for reference. **Remove** saves the removal; use the picker to restore an ability. Free-form choice text remains editable and survives removal and restoration. Supported bonuses update while manual modifiers and advancement history are preserved.

Open a created character to edit the four sheet sections: combat and identity; feats, class and racial abilities and skills; spells; gear and notes. The layout follows pages 2–5 of the supplied deluxe sheet. Edits save automatically after a short typing pause or when leaving a field. The save status reports saving, successful saves, validation failures, and conflicts. Leaving before a successful save prompts before discarding edits. Network retries reuse the same request identifier so a lost response cannot duplicate a save. Saves run in order and preserve newer typing while an earlier request completes. Print opens the browser's print dialog.

Existing creation values populate the sheet. Player and Character class are read-only on the sheet. Player always shows the owning account. Alignment uses the same nine choices as the creation wizard. Other character values are editable, including current HP, temporary ability scores, saves, AC components, attacks, armor, resistances, spells at levels 0–9, used spell slots, 56 gear entries, carrying capacity, coins, faction points, and notes. Calculated totals and copied ability modifiers are read-only and recompute as you type using the same server rules as automatic saves, including temporary ability modifiers, initiative, saves, CMB/CMD, AC, skills, skill points, and spell-list counts. Editable ranks and miscellaneous bonuses feed these totals. AC has a separate Dodge input so flat-footed AC excludes dodge and positive Dexterity. Armor-limited AC Dexterity remains an input. Class save bonuses are read-only when the character’s class and level match a Level Progression row. Custom classes without a matching row can enter their class save bonuses manually. First-level wizard HP, BAB, and base skill points are read-only. Characters requiring manual advancement can edit those three fields. Weapon and armor statistics come from inventory. Spell DCs, casting adjustments, speed modifiers, wealth, and individual gear weights remain editable. Total carried weight is calculated from named gear rows and stays blank when an item has an unknown weight. Class-skill markers include skills from every class. Class skills receive +3 when ranked; every class can rank every skill.

The character's name, race, class, level, and notes use the existing database fields. Migration 005 adds `characters.play_data`, a validated JSON record for the additional fields and overrides. Unchanged creation values continue to come from `sheet_data`; saving play values preserves the creation snapshot and roll history. The first-level creation wizard remains available for first-level characters.

Owners, administrators, and the assigned campaign's authorized Game Master retain their existing access. Saving requires CSRF validation and the latest record version. A stale form cannot overwrite another edit. Validation errors preserve entered values for correction. Campaign text on the sheet is a descriptive label; Manage character controls actual ownership and campaign membership.

## Multiclass advancement

When the character reaches the next XP threshold, open **Level Up** and choose **Class to advance**. Pick an existing class to gain its next level, or choose a new class to take its first level. The wizard uses that class’s Hit Die, skill ranks, and features. Overall character level determines XP thresholds, general feats, ability increases, and the maximum ranks per skill. The sheet adds each class’s base attack and saving throw bonuses and grants one +3 bonus to each trained skill that belongs to any of the character’s classes.

The **Class Levels** block lists each class and its current level. **Manage Class Levels** lets you enter an existing class breakdown for a legacy character or NPC with no creation or advancement history. Enter levels that add up to the existing total and keep the first casting class if it already has spell data. Characters with recorded progression gain classes through **Level Up**.

The creation wizard records a favored class, with a second choice for half-elves. Existing characters default to their starting class until a favored class is recorded. The +1 HP or +1 skill rank reward applies when the class being advanced is favored.

Each casting class has its own spell list and used slots. Select **Add Spells** under that class to open its spell picker. The advancement and spell displays use each class’s own progression. Record options such as specialist school slots and GM-adjudicated class feature effects in the sheet’s notes.

## Character image

Choose the image beside the character name to upload a JPG, PNG, or WebP portrait. Images save immediately, separately from text autosave. Use Remove image to clear the portrait. The browser resizes files up to 10 MB before upload; the server validates and re-encodes them as bounded JPEG images. The existing proxy request limit remains unchanged.

Portraits are private and use the same access rules as the character. The creation wizard keeps its image with the private draft, displays it beside the name and in the preview, and carries it to the completed character. Discarding a draft leaves an existing character's image unchanged. An editing wizard only replaces the saved portrait when its image was explicitly changed.

Migration 007 adds portrait blobs to characters and drafts. Portraits are included in normal database backups. Uploading an image does not change the text-edit revision or interrupt automatic saving.

## Header background

The saved character's header starts with the same citadel image as Overview. The character owner can choose Change header background to upload a JPG, PNG, or WebP, or Use default background to restore the original. Other users who can access the character can view its background; editing the background requires ownership, including for administrators and campaign Game Masters.

Backgrounds save independently of the portrait and text autosave. Custom images are resized and stored privately in the database; migration 008 adds the optional header background column. Existing characters automatically use the default without copying image data into every record.

Calculated sheet values show their formula on hover or keyboard focus. The tooltip explains ability modifier rounding, temporary scores, saves, Armor Class, combat maneuvers, skill ranks/class bonuses, first-level class values, spell counts, managed weapon attacks/damage, armor weight, and the treasure total. Catalog-backed or legacy fields explain their saved source rather than claiming to recalculate. Formula descriptions follow autosaves and equipment purchases. Escape dismisses the tooltip; tooltips stay within the viewport and are excluded from print.

The Deities administration catalog stores a stable identifier, display name, description URL, and availability for each deity or belief. Migration 012 adds 157 deduplicated entries from the requested PathfinderWiki Deity sections, including individual members of the linked regional pantheons, the ascended deities, and Atheism. It imports names and URLs only. Administrators can add, rename, edit links, or archive entries. Renames retain aliases; existing selections and legacy custom beliefs remain available on their characters. Archived entries cannot be newly selected.

The wizard's Description step and the character sheet's identity section use the current deity catalog in their Deity or belief / Deity dropdowns. A Description link opens the selected entry's article. Blank means unspecified; Atheism is an explicit belief without a deity. Deity choices do not add mechanical bonuses or alter a character's frozen combat rules.

Base speed is read-only and comes from the wizard's selected race, or the matching ancestry on legacy records. Its tooltip names the race and racial land speed before movement adjustments. Earlier manual base-speed overrides no longer replace a known racial value. Unknown legacy races retain their recorded base speed. Other speed fields remain editable.

Weapons, armor/shields, and every Gear row have an editable Equipped checkbox that autosaves. The wizard's equipped weapon, armor, and shield seed these markers. Purchased items begin unequipped; buying additional copies preserves an existing marker. Managed weapon/armor markers stay synchronized with the matching Gear entry. Custom gear can be marked independently, and blank rows cannot be equipped. Equipping armor or a shield applies its armor/shield bonus, Dexterity cap, check penalties, and movement adjustment. Unequipping, removing, or selling it reverses those effects. Only one suit of armor and one shield can be equipped; checking another switches the matching slot. Supported monk armor restrictions and barbarian/dwarf movement rules are included. Manual modifier offsets are preserved, and temporary ability scores update equipment-dependent values. Equipped catalog weapons recalculate attack and damage using current abilities and supported feats. Conditional effects and proficiency rulings remain manual.

A floating d20 Dice button opens the character sheet’s Dice Tray modal. It reuses the wizard's tray markup, animated polyhedra, supported dice (d4/d6/d8/d10/d12/d20/d100), 1–20 dice, and −1,000 to +1,000 modifiers. Rolls are generated on the server with the same free-roll helper used by the wizard, require character access and CSRF, and do not change character values or its version. The modal retains the latest 12 rolls while this page is open. Close or Escape returns focus to the floating button; the tray is hidden when printing.

Weapon and armor rows provide **− Remove** and **$ Sell** actions. Both remove the entire row quantity, notes, equipped marker, and matching linked gear row. An independently renamed gear row is retained. Remove does not refund treasure. Sell asks for total agreed proceeds in PP, GP, SP, and CP and credits those exact denominations once. Retrying a lost response cannot duplicate a sale. Empty row slots become available for new purchases. Carried weight and supported equipment effects update automatically. Inventory actions flush pending edits and protect against stale character versions.

Equipment contributions are recorded separately from manual modifier offsets in the play record. Rapid autosaves carry the equipment baseline actually displayed in the browser, so switching equipment while a save is in flight cannot count modifiers twice. Character creation snapshots remain unchanged.
