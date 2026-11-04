## Open and resume the wizard

Select **Add character** in Characters, the workspace, or a campaign to start a new draft. To resume an unfinished character, open its **Draft** card on the Characters page. The wizard creates a first-level PC in twelve steps: character sheet, race, class, ability scores, skills, feats, HP, equipment, combat, description, starting spells, and review. The dice tray is available throughout the wizard. Third-party class links are excluded.

Your draft saves after changes and when switching steps. **Draft saved** confirms persistence. **Save & exit** returns to Characters, where your unfinished characters appear under **Draft characters**. You can keep multiple drafts and resume each independently, including its saved step and dice history. Drafts remain private to their creator. Refreshing a draft's page reopens that same draft. A draft becomes a character only after **Create character** on Review; its Draft card then disappears. Separate editing drafts may exist for saved sheets.

## Dice tray

Choose d4, d6, d8, d10, d12, d20, or d100. Set one to twenty dice and an optional whole-number modifier, then roll. Results come from the server's secure random generator. The browser animates polyhedral dice, and the result is saved with the draft. The server validates die type, counts, and limits. Free rolls are practice rolls and do not automatically alter the sheet.

Percentile rolls use tens and units dice. A tens result of 00 with units 0 represents 100; otherwise add tens and units. d100 results range from 1 through 100. Reduced-motion preferences remove tumbling movement. Screen-reader users receive the result as text.

Ability generation and starting wealth use dedicated buttons that save their provenance. Recent rolls remain available in the dice history. Your GM decides which generation methods and rerolls are permitted. A retry with the same request identifier returns the original result rather than rolling again. The tray permits 120 roll requests per user every fifteen minutes.

## Sheet and ability scores

The signed-in user automatically owns every new character, including characters created by GMs and Admins. Choose an optional campaign. Campaign access is checked again when the character is finalized.

Ability methods include point buy with 10, 15, 20, or 25 points; standard 4d6 dropping one lowest die; classic 3d6; heroic 2d6 plus 6; and GM-approved manual scores. Point-buy scores range from 7 to 18 before race adjustments. The wizard blocks overspending and reports unused points.

Rolled methods generate six scores. Assign each score once. Changing the browser's score fields cannot change the stored server result. Race adjustments are applied after generation. Ability modifiers use the final adjusted scores.

## Race, class, and favored class

The seven core races provide standard ability adjustments, size, speed, basic language information, and trait notes. Human, half-elf, and half-orc choices can place their flexible +2 bonus in one ability. Half-elf adaptability provides a separate Skill Focus choice.

Class choices include the outline's core and base classes plus Ninja and Samurai, which appear in its main creation tables. The wizard uses first-level Hit Dice, skill ranks, base attack, saves, and starting wealth. No third-party class catalogs or steps beneath their links are imported. Class reference links point to the selected class itself.

Vigilantes explicitly choose Stalker or Avenger; the Avenger's first-level base attack bonus is applied from that choice rather than inferred from notes.

Choose +1 HP, +1 skill rank, or another/not-favored-class benefit. Custom favored-class benefits require GM review. Record these benefits, domains, schools, bloodlines, mysteries, companions, talents, orders, and other class choices in Character notes under Description. These are saved choices, not an automated companion or archetype builder.

The source outline's Samurai wealth table differs from the official legacy PRD. The wizard uses the official Samurai starting wealth of 5d6 × 10 gp, average 175 gp.

## Skills and feats

The skill budget includes the class base, Intelligence modifier with the minimum class allotment, the human bonus rank, and the chosen favored-class rank. Allocate all available ranks. Each listed skill can have at most one rank at first level. Trained class skills add +3. Select any catalog skill by assigning a rank. Every class can assign ranks to any catalog skill. The selected class determines the fixed class-skill list; assigning ranks does not change that list. Multiclassing is not implemented.

Craft, Perform, and Profession specialties and conditional bonuses are recorded in skill notes. Their additional independent specialties, conditional racial benefits, archetypes, and other special cases need GM review. The displayed totals include standard ability modifiers, class training, supported racial bonuses and feats, and equipped armor check penalties.

Choose the first-level general feat and, for humans, a second feat. Class bonus feats and automatic class feats are tracked separately. Suggested feats check common ability, base attack, and prerequisite-feat requirements. Monk bonus feats use the first-level permitted list and waive their normal prerequisites. Custom, teamwork, and technique feat choices are recorded for GM review; their effects are not automatically interpreted.

Supported numerical feat effects include Improved Initiative, Toughness, Great Fortitude, Iron Will, Lightning Reflexes, Dodge, Alertness, Skill Focus, Weapon Focus, and eligible Weapon Finesse attacks. Conditional effects, such as Power Attack or Point-Blank Shot, are handled during play rather than added permanently.

## HP, gear, and combat

First-level player-character HP uses the maximum Hit Die, Constitution, favored-class HP if selected, and supported feat effects. It does not roll the first Hit Die.

Choose class-average wealth, roll the class wealth dice, or enter GM-approved starting gold. Buy from the starter catalog, then choose which owned weapon, armor, and shield are equipped. A free starting outfit is available once. Other gear, free class items, and purchases go in equipment notes, with additional costs recorded separately. Costs are stored in copper pieces to avoid rounding errors. Spending beyond the starting amount is blocked.

The combat step displays base AC, touch AC, flat-footed AC, saves, initiative, base attack, melee/ranged attack bonuses, CMB, CMD, weapon damage, speed, and recorded inventory weight. It includes standard size and ability adjustments, equipped armor/shield bonuses, armor Dexterity caps, and supported feats.

Confirm proficiencies, arcane spell failure, encumbrance, armor material restrictions, natural attacks, conditional abilities, special class features, and custom effects with your GM. These are not fully automated by this first-level builder. The catalog is a starter list, not every Pathfinder item.

## Description, spells, and review

Enter the final name, alignment, age, gender/pronouns, deity, languages, appearance, personality/background, and notes. Standard alignment restrictions are checked for Paladin, Monk, Barbarian, Druid, and Shifter. Other class or deity restrictions require review.

Caster steps record starting first-level spells/formulae, cantrips/orisons, prepared spells, and restrictions. Supported class starting counts are checked, including wizard, magus, witch, and alchemist initial book/familiar/formula choices and common spontaneous-caster known spell counts. Oracle and Omdura free cure/inflict spells belong in the additional spell notes. Check spell names, class lists, levels, school restrictions, and extra domain/mystery choices with your GM. The spell suggestions combine several lists and do not imply that every class can select every suggestion.

Review shows unfinished choices and lets you jump back to them. Server validation repeats before the character is created. Double-clicking or retrying completion does not create duplicate characters. The finished character page displays the saved sheet, creation rolls, gear, skills, feats, story, and spell choices.

## Editing and conflicts

**Edit creation sheet** opens a resumable editing draft for a first-level wizard-built character. The original character remains unchanged until you save the completed draft. Existing permission rules still apply. If the source character changes in another window, the editing draft is rejected rather than overwriting newer data.

**Edit character** manages identity, notes, and permitted campaign/owner changes. Wizard-built race, class, and level fields are read-only in that basic editor to prevent the calculated sheet from becoming stale. Legacy basic records retain their existing editor. Advancement, multiclassing, archetype automation, full spell/feat validation, and higher-level character generation are outside this first-level creation workflow.

Discarding a draft removes its unfinished data and dice history. A saved character survives discarding its editing draft. Character deletion still requires the normal separate confirmation. Drafts are private to their creator, including editing drafts; Admins retain full management of saved characters.

## Server upgrade and sources

Migration 004 removes the retired class-notes and additional-class-skill data from drafts and sheets, and recalculates saved sheets with fixed class skills. Back up and stop the application before migrating. Migration 003 adds the nullable character sheet field, private draft table, and dice-roll table. Existing users, campaigns, email settings, and basic character records are preserved. Apply `sudo .venv/bin/python -m pathkeeper.manage migrate` before restarting Uvicorn. No new runtime package or external graphics service is required.

References: the d20PFSRD Character Creation Outline, its core/base class and race references, and the official legacy Pathfinder Reference Document for ability generation, races, classes, skills, equipment, feats, and combat. The wizard uses rules facts and original help text rather than reproducing class chapters. The main outline is https://www.d20pfsrd.com/basics-ability-scores/character-creation/ and the legacy rules are https://legacy.aonprd.com/coreRulebook/gettingStarted.html.
