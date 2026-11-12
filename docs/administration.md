## Open Administration

Only an active Admin who has completed TOTP enrollment can open Administration. The directory supports name/email search, role and status filters, and pages of 25 users. Counts show total users, active accounts, Admins, and enabled authenticators.

Use the **Email Configuration** tab to connect Brevo or an SMTP relay and send a test. See [email setup](/help/email) for credentials, sender identity, test results, and delivery troubleshooting.

## Create a user

Public sign-up creates Player accounts only. An Admin can promote a registered Player by editing their role, or create an account directly below.

Select **Create user**. Enter display name, unique email, temporary password, and Player, Game Master, or Admin role. Choose whether the account is enabled and whether TOTP is required. Admins always require TOTP, regardless of the checkbox.

With email configured, enabled new accounts receive a one-use password setup link and choose their own password. Temporary passwords are never emailed. If delivery is unavailable, share the temporary password privately; the user must replace it at sign-in. The temporary password is not displayed again after saving. See [account email and recovery](/help/account-email).

## Edit, disable and enable

Open **Manage** next to a user. Edit their details, role, Account enabled setting, or TOTP requirement. Confirm your own Admin password and a fresh authenticator or unused recovery code before saving.

Disabling the account revokes every session immediately. Re-enabling permits a new login with the existing password and authenticator. It does not restore old sessions or erase campaign data. Normal edits revoke the target's other sessions so changed access takes effect promptly.

At least one active Admin must remain. The last active Admin cannot be disabled, deleted, or demoted. Before changing a campaign owner to Player, transfer or delete their owned campaigns; Players cannot own campaigns through normal management.

## Password and authenticator recovery

**Reset password** sets a temporary password, forces a change at sign-in, and revokes sessions. It preserves any existing TOTP authenticator.

**Reset a lost authenticator** removes that authenticator, all recovery codes, and sessions. Type the target email and confirm your own password and second factor. The user must enroll a new authenticator next time. This process does not reveal the old secret.

Each accepted authenticator code works once. Wait for another code or use an unused recovery code for the next sensitive action.

## Delete a user

Deletion requires the target email, your current Admin password, and a fresh factor. It permanently removes the account, its owned characters, and its owned campaigns. Other users' characters in deleted campaigns survive but become unassigned. Memberships and invitations belonging to deleted campaigns disappear.

There is no in-app undo. Disabling is the appropriate choice when you want to suspend access while retaining the user's records.

## Activity log

The Admin-only Activity log shows the latest 100 security and management events. It records actions without passwords, TOTP secrets, recovery codes, or readable invitation tokens. Deleting an account retains audit descriptions while removing the deleted actor reference.

## Rules catalog

**Class Abilities** lists progression features for all supported classes. Search by ability name, filter by class or level, and open the Archives of Nethys reference. Scaling features share one entry with each level of progression. The list follows the current Character Classes definitions; edit those definitions to change the catalog. Individual selectable powers, such as hexes and rage powers, are outside this list.

Administrators can open **Administration → Rules catalog** (`/administration/catalog`) to search, add, edit, and archive the feat, skill, and weapon lists used by the character wizard. All writes require an authenticated Admin and CSRF protection, use a catalog version to prevent overwriting another administrator's changes, and record an audit event. Migration 009 creates the versioned database catalog using the existing built-in values.

Feat forms expose combat and first-level monk eligibility, ability/BAB/feat prerequisites, skill or weapon selection, repeatability by distinct choice, numerical HP/initiative/save/dodge/skill/weapon-attack modifiers, and the finesse effect. Conditional rules belong in the description and require manual handling during play. The same feat and choice do not stack. Prerequisite cycles and incompatible selection modifiers are rejected.

Skill forms expose the governing ability, armor-check-penalty flag, trained-only marker, catalog bonus, and each class's fixed class-skill membership. Every class may rank every available skill; investing at least one rank grants +3 for a class skill. Racial and size bonuses remain part of race rules and are described alongside the editor. The trained marker does not simulate individual skill actions. Skills support 75 entries, feats 200, and weapons 1,000.

Weapon forms expose copper-piece cost, pound weight, Medium/Small damage dice, proficiency group, ranged/bow/two-handed/finesse flags. Proficiency, critical hits, range, and situational combat effects remain manual. Weapon entries are also available in the equipment catalog and selected-weapon feat lists.

Stable identifiers cannot be renamed or deleted. Archive an entry to stop offering it for new selections. An unfinished draft using an archived entry must replace it before completion. Reload open wizards after catalog edits so their lists match the server's current rules.

When a character is completed, its rules catalog is saved with the creation snapshot. Existing character sheets keep their original modifiers and skill definitions, including during autosave and live recalculation. Older characters without an explicit catalog retain the original built-in rules. Reopening and completing the creation wizard intentionally applies the current catalog. Catalog edits do not silently rewrite existing characters or their manual sheet edits.

### Expanded weapon tables

Migration 010 loads 243 Simple, Martial, and Exotic weapons and 36 associated ammunition entries from the d20PFSRD weapon tables. Filter by proficiency/category or search by name. Weapon editors expose the table columns, reference URL, calculation flags, composite Strength rating, aliases, and notes. Damage fields accept double-weapon values, flat damage, `—`, and `see text`. A blank numeric cost/weight preserves an adjudicated value alongside its published qualifier. Ammo is carried as equipment and is excluded from weapon feat selections. The weapon catalog supports 1,000 entries.

Individual weapon reference links appear in the catalog and next to weapon names on character sheets. Editing a reference URL changes the link on existing sheets without changing their saved combat statistics. Renaming a weapon retains its former name as an alias. Character-sheet weapon names and statistics are read-only and populated through Add weapons; Notes remain editable. Unmatched legacy custom names have no reference link. Only HTTP/HTTPS links without embedded credentials are accepted. New sheets seed critical, range, damage type, special qualities, and notes from the catalog. Existing manual fields remain intact.

Migration 013 replaces d20PFSRD reference links with verified Archives of Nethys destinations in the catalog and existing character records. It preserves custom names, statistics, and links to other sites. Reference URLs remain editable.

Feats, Skills, and Deities show individual reference links in their catalog rows and editors. Feat and skill reference URLs are editable. Migration 015 adds verified AoN links for 21 feats, 35 skills, and 90 deities. Knowledge specialties link to AoN's Knowledge skill page. Unmatched deities retain their existing description links, and custom reference URLs are preserved.
