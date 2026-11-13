"""Pathfinder 1e advancement thresholds from Core Rulebook Table 3–1."""
from bisect import bisect_right
from decimal import Decimal, InvalidOperation

XP_TRACKS = {
    "slow": (0, 3000, 7500, 14000, 23000, 35000, 53000, 77000, 115000, 160000,
             235000, 330000, 475000, 665000, 955000, 1350000, 1900000, 2700000, 3850000, 5350000),
    "medium": (0, 2000, 5000, 9000, 15000, 23000, 35000, 51000, 75000, 105000,
               155000, 220000, 315000, 445000, 635000, 890000, 1300000, 1800000, 2550000, 3600000),
    "fast": (0, 1300, 3300, 6000, 10000, 15000, 23000, 34000, 50000, 71000,
             105000, 145000, 210000, 295000, 425000, 600000, 850000, 1200000, 1700000, 2400000),
}
XP_SOURCE = "https://www.aonprd.com/Rules.aspx?ID=85"


def track(campaign):
    return campaign.xp_speed if campaign else "slow"


def level_for(xp, speed):
    return bisect_right(XP_TRACKS[speed], xp)


def saved_xp(character, speed):
    raw = (character.play_data or {}).get("experience")
    try:
        xp = Decimal(str(raw))
        if xp.is_finite() and 0 <= xp <= 1000000000 and xp == xp.to_integral_value():
            return int(xp)
    except InvalidOperation:
        pass
    thresholds = XP_TRACKS[speed]
    return thresholds[min(max(character.level, 1), len(thresholds)) - 1]


def apply_advancement(values, speed):
    xp = int(Decimal(values["experience"] or "0"))
    level = int(values["level"])
    thresholds = XP_TRACKS[speed]
    values.update(experience=str(xp),
                  next_level=str(thresholds[level]) if level < len(thresholds) else "")


def preserve_xp(character, old_speed):
    xp = saved_xp(character, old_speed)
    character.play_data = {**(character.play_data or {}), "experience": str(xp)}


def remove_campaign_characters(db, campaign, owner_id=None):
    from sqlalchemy import select
    from .models import Character

    query = select(Character).where(Character.campaign_id == campaign.id)
    if owner_id is not None:
        query = query.where(Character.owner_id == owner_id, Character.is_npc.is_(False))
    for character in db.scalars(query.order_by(Character.id).with_for_update()):
        if character.is_npc:
            db.delete(character)
            continue
        preserve_xp(character, campaign.xp_speed)
        character.campaign_id = None


def eligible(character, campaign):
    return level_for(saved_xp(character, track(campaign)), track(campaign)) > character.level
