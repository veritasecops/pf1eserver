## Three instance-wide roles

Every account has exactly one role: Player, Game Master, or Admin. A role applies across the instance. Campaign ownership and membership narrow the records that the role can access. Hiding a navigation link is not the permission check; every server request checks access again.

Public sign-up always creates a Player. An Admin assigns higher roles through Administration. The first public registration has no special privileges.

## Player

Players have full create, read, update, and delete access to their own characters. They can join campaigns through invitations and assign their characters to campaigns they own or have joined. In normal use Players do not own campaigns.

Players cannot create or modify campaigns, invite or remove members, manage users, see the activity log, or access another user's character. A player's campaign page displays their own assigned characters rather than exposing everyone else's records.

## Game Master

Game Masters can create, read, edit, and delete their own campaigns, and manage those campaigns' invitations and members. They retain full access to their own characters.

After another user joins one of their campaigns, a GM can read or update that user's characters assigned there. Only a character's owner or an Admin can delete it. The GM cannot access the user's standalone characters or characters in unrelated campaigns. Removing the member detaches those assigned characters and ends the GM's campaign-based access.

A GM cannot move another user's existing character between campaigns or transfer its ownership. Character owners can move their own records; Admins can manage ownership and assignment across the instance. Joining someone else's campaign does not make a GM the owner of that other campaign.

## Admin

Admins can manage every user, campaign, and character, including editing, disabling/deleting users, campaign ownership transfers, and character owner changes. New characters always belong to the Admin creating them. They can create and revoke invitations and remove members in any campaign.

Admins require TOTP. Sensitive account changes require current-password and factor confirmation. The last active Admin is protected against deletion, disabling, and demotion. These protections prevent accidental administrative lockout while preserving management of the remaining accounts.

## Assignment and deletion

Campaign deletion detaches surviving characters rather than deleting other users' work. User deletion deletes that user's owned characters and owned campaigns. Admins may assign a character to a campaign even when its owner is not a member; that assignment alone does not grant the campaign GM access to a nonmember's character. Invite that owner when GM management is intended.
