from copy import deepcopy
import json
import re
import secrets

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from pathkeeper.character_rules import calculate, clean, defaults
from pathkeeper.database import engine
from pathkeeper.models import Character, CharacterDraft, DiceRoll, SchemaMigration
from .test_workspace import seed_campaign, seed_character


def start(env, account=None):
    c = env.login(account or env.player)
    response = c.get("/characters/new")
    assert response.status_code == 200
    with Session(engine()) as db:
        draft = db.scalar(select(CharacterDraft).where(CharacterDraft.actor_id == (account or env.player).id,CharacterDraft.mode == "create"))
        return c,draft.id,draft.version,deepcopy(draft.data)


def fighter(data):
    data.update(name="Seren Ashfall",class_id="fighter",skills={"climb":1,"perception":1,"ride":1},
                feats=[{"name":"Improved Initiative"},{"name":"Toughness"}],bonus_feat={"name":"Combat Reflexes"},
                equipment={"longsword":1,"leather":1,"heavy-shield":1,"backpack":1,"outfit":1},
                weapon="longsword",armor="leather",shield="heavy-shield")
    return data


def save(env,c,draft_id,version,data,step=12):
    return env.post(c,f"/api/character-drafts/{draft_id}/save",{"version":version,"payload":json.dumps(data),"step":step})


def roll(env,c,draft_id,**values):
    return env.post(c,f"/api/character-drafts/{draft_id}/roll",{"request_id":secrets.token_hex(16),"purpose":"free","sides":20,"count":1,"modifier":0,**values})


def finish(env,c,draft_id,version):
    return env.post(c,f"/api/character-drafts/{draft_id}/finish",{"version":version})


def test_add_character_resumes_persistent_private_draft_without_creating_character(env):
    c,draft_id,version,data = start(env)
    data["name"] = "A saved idea"
    saved = save(env,c,draft_id,version,data,3)
    assert saved.status_code == 200
    response = c.get("/characters/new")
    assert "A saved idea" in response.text and '"step": 3' in response.text
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(CharacterDraft)) == 1
        assert db.scalar(select(func.count()).select_from(Character)) == 0
    assert "Add character" in c.get("/characters").text


def test_wizard_ability_assignment_order_is_explicit_despite_sorted_json(env):
    c,_,_,_=start(env)
    page=c.get("/characters/new")
    boot=json.loads(re.search(r'<script type="application/json" id="pw-bootstrap">(.*?)</script>',page.text,re.S).group(1))
    assert boot["ability_order"]==["str","dex","con","int","wis","cha"]


def test_wizard_starts_at_sheet_with_abilities_fourth_and_no_dice_step(env):
    client,draft_id,version,data = start(env)
    page = client.get("/characters/new")
    boot = json.loads(re.search(r'<script type="application/json" id="pw-bootstrap">(.*?)</script>',page.text,re.S).group(1))
    assert boot["step"] == boot["step_order"][0]
    assert [boot["steps"][str(key)] for key in boot["step_order"]] == [
        "Character sheet", "Race", "Class", "Ability scores", "Skill ranks", "Feats",
        "Hit points", "Equipment", "Combat values", "Description", "Starting spells", "Review",
    ]
    # A save from an already-open legacy Dice page resumes at Character sheet.
    assert save(env,client,draft_id,version,data,step=0).status_code == 200
    with Session(engine()) as db:
        assert db.get(CharacterDraft,draft_id).step == boot["step_order"][0]


@pytest.mark.parametrize("saved_step,title,number", [
    (0,"Character sheet",1), (2,"Ability scores",4), (3,"Race",2), (4,"Class",3), (12,"Review",12),
])
def test_reordered_wizard_resumes_existing_drafts_at_the_same_section(env,saved_step,title,number):
    client,draft_id,_,_ = start(env)
    with Session(engine()) as db:
        draft = db.get(CharacterDraft,draft_id)
        draft.step = saved_step
        draft.data = {**draft.data,"name":"Keep my draft"}
        db.commit()
    page = client.get("/characters/new")
    boot = json.loads(re.search(r'<script type="application/json" id="pw-bootstrap">(.*?)</script>',page.text,re.S).group(1))
    assert boot["steps"][str(boot["step"])] == title
    assert boot["step_order"].index(boot["step"]) + 1 == number
    assert boot["data"]["name"] == "Keep my draft"


@pytest.mark.parametrize("account",["player2","gm","admin"])
def test_other_accounts_cannot_read_save_roll_or_finalize_private_draft(env,account):
    _,draft_id,version,data = start(env)
    other = env.login(getattr(env,account))
    for action,values in (("save",{"version":version,"payload":json.dumps(data),"step":0}),
                          ("roll",{"request_id":secrets.token_hex(16),"sides":20,"count":1,"modifier":0}),
                          ("finish",{"version":version}),("discard",{})):
        assert env.post(other,f"/api/character-drafts/{draft_id}/{action}",values).status_code == 404


def test_draft_requires_csrf_and_rejects_stale_window(env):
    c,draft_id,version,data = start(env)
    assert c.post(f"/api/character-drafts/{draft_id}/save",data={"version":version,"payload":json.dumps(data),"step":0}).status_code == 403
    assert save(env,c,draft_id,version,data).status_code == 200
    assert save(env,c,draft_id,version,data).status_code == 409


@pytest.mark.parametrize("sides",[4,6,8,10,12,20,100])
def test_supported_dice_return_bounded_server_results_and_total(env,sides):
    c,draft_id,_,_ = start(env)
    response = roll(env,c,draft_id,sides=sides,count=20,modifier=-7)
    assert response.status_code == 200
    result = response.json()["result"]
    assert len(result["dice"]) == 20 and all(1 <= value <= sides for value in result["dice"])
    assert result["total"] == sum(result["dice"])-7
    if sides == 100:
        assert all((pair["tens"]+pair["ones"] or 100)==value for pair,value in zip(result["percentile"],result["dice"]))


def test_percentile_zero_zero_means_100(env,monkeypatch):
    from pathkeeper import character_wizard
    c,draft_id,_,_ = start(env)
    monkeypatch.setattr(character_wizard.secrets,"randbelow",lambda sides:sides-1)
    result = roll(env,c,draft_id,sides=100).json()["result"]
    assert result["dice"] == [100] and result["percentile"] == [{"tens":0,"ones":0}]


def test_roll_retry_is_idempotent_and_saved(env):
    c,draft_id,_,_ = start(env)
    key = secrets.token_hex(16)
    first = roll(env,c,draft_id,request_id=key)
    second = roll(env,c,draft_id,request_id=key)
    assert first.json() == second.json()
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(DiceRoll)) == 1


@pytest.mark.parametrize("values",[{"sides":5},{"count":21},{"count":0},{"modifier":1001},{"purpose":"forged"},{"request_id":"invalid"}])
def test_dice_reject_unsupported_or_unbounded_requests(env,values):
    c,draft_id,_,_ = start(env)
    assert roll(env,c,draft_id,**values).status_code == 422


def test_standard_abilities_drop_one_lowest_die_and_cannot_be_forged(env,monkeypatch):
    from pathkeeper import character_wizard
    c,draft_id,version,data = start(env)
    sequence = iter([0,1,2,3]*6)
    monkeypatch.setattr(character_wizard.secrets,"randbelow",lambda sides:next(sequence))
    rolled = roll(env,c,draft_id,purpose="ability",method="standard").json()
    assert all(group == {"dice":[1,2,3,4],"dropped":0,"total":9} for group in rolled["result"]["groups"])
    data.update(method="standard",ability_roll=rolled["id"],abilities={key:30 for key in data["abilities"]})
    result = save(env,c,draft_id,version,data).json()["computed"]
    assert result["base"] == {key:9 for key in data["abilities"]}
    data["ability_roll"] = "f"*32
    with Session(engine()) as db: version=db.get(CharacterDraft,draft_id).version
    result = save(env,c,draft_id,version,data).json()["computed"]
    assert any(error["step"]==2 for error in result["errors"])


def test_creation_sheet_math_persistence_and_idempotent_completion(env):
    c,draft_id,version,data = start(env)
    saved = save(env,c,draft_id,version,fighter(data))
    assert saved.status_code == 200
    computed = saved.json()["computed"]
    assert not computed["errors"] and computed["hp"] == 14 and computed["ac"] == 14
    assert computed["initiative"] == 4 and computed["remaining_cp"] == 14100
    # Rank + class training + Strength, minus the equipped heavy shield's ACP.
    assert computed["skill_totals"]["climb"] == 3 and computed["skill_totals"]["perception"] == 1
    completed = finish(env,c,draft_id,saved.json()["version"])
    assert completed.status_code == 200
    assert finish(env,c,draft_id,saved.json()["version"]).json() == completed.json()
    path=completed.json()["location"]
    page=c.get(path)
    assert page.status_code == 200 and "Seren Ashfall" in page.text and "First-level character sheet" in page.text
    with Session(engine()) as db:
        records=list(db.scalars(select(Character)))
        assert len(records)==1 and records[0].sheet_data["computed"]["hp"]==14 and records[0].owner_id==env.player.id


def test_finalization_blocks_bad_budgets_prerequisites_and_rank_limits(env):
    c,draft_id,version,data=start(env)
    data=fighter(data)
    data["abilities"]={key:18 for key in data["abilities"]}
    data["equipment"]["longbow"]=100
    data["skills"]={"climb":1}
    response=save(env,c,draft_id,version,data)
    assert response.status_code==200
    errors=response.json()["computed"]["errors"]
    assert {2,5,8}.issubset({error["step"] for error in errors})
    assert finish(env,c,draft_id,response.json()["version"]).status_code==422
    data["skills"]["climb"]=2
    assert save(env,c,draft_id,response.json()["version"],data).status_code==422


def test_wizard_uses_existing_campaign_and_character_permissions(env):
    campaign=seed_campaign(env.gm,members=[env.player])
    c,draft_id,version,data=start(env,env.gm)
    data=fighter(data)
    data.update(owner_id=env.player.id,campaign_id=campaign.id)
    saved=save(env,c,draft_id,version,data)
    result=finish(env,c,draft_id,saved.json()["version"])
    assert result.status_code==200
    with Session(engine()) as db:
        character=db.get(Character,int(result.json()["location"].rsplit('/',1)[1]))
        assert character.owner_id==env.player.id and character.campaign_id==campaign.id
    # Another GM cannot view that sheet or begin an editing draft.
    other=env.login(env.gm2)
    assert other.get(result.json()["location"]+"/sheet/edit").status_code==404


def test_gm_cannot_create_for_an_unjoined_owner(env):
    campaign=seed_campaign(env.gm)
    c,draft_id,version,data=start(env,env.gm)
    data=fighter(data)
    data.update(owner_id=env.player.id,campaign_id=campaign.id)
    saved=save(env,c,draft_id,version,data)
    assert finish(env,c,draft_id,saved.json()["version"]).status_code==403


def test_player_cannot_forge_character_owner(env):
    c,draft_id,version,data=start(env)
    data=fighter(data)
    data["owner_id"]=env.admin.id
    saved=save(env,c,draft_id,version,data)
    result=finish(env,c,draft_id,saved.json()["version"])
    assert result.status_code==200
    with Session(engine()) as db:
        character=db.scalar(select(Character))
        assert character.owner_id==env.player.id and character.sheet_data["input"]["owner_id"]==env.player.id


def test_wealth_roll_is_bound_to_class_and_ability_assignment_is_unique(env):
    c,draft_id,version,data=start(env)
    wealth=roll(env,c,draft_id,purpose="wealth",class_id="fighter").json()
    ability=roll(env,c,draft_id,purpose="ability",method="classic").json()
    data.update(class_id="wizard",wealth_method="rolled",wealth_roll=wealth["id"],method="classic",ability_roll=ability["id"],assignments=[0]*6)
    result=save(env,c,draft_id,version,data).json()["computed"]
    assert {2,8}.issubset({error["step"] for error in result["errors"]})


def test_switching_to_average_wealth_does_not_label_old_roll_as_used(env):
    c,draft_id,version,data=start(env)
    old=roll(env,c,draft_id,purpose="wealth",class_id="fighter").json()
    data=fighter(data)
    data.update(wealth_method="average",wealth_roll=old["id"])
    saved=save(env,c,draft_id,version,data)
    assert finish(env,c,draft_id,saved.json()["version"]).status_code==200
    with Session(engine()) as db:
        character=db.scalar(select(Character))
        assert character.sheet_data["computed"]["gold_cp"]==17500
        assert character.sheet_data["rolls"]==[]


def test_wizard_edit_preserves_sheet_and_detects_stale_character(env):
    c,draft_id,version,data=start(env)
    saved=save(env,c,draft_id,version,fighter(data))
    path=finish(env,c,draft_id,saved.json()["version"]).json()["location"]
    assert c.get(path+"/sheet/edit").status_code==200
    with Session(engine()) as db:
        editing=db.scalar(select(CharacterDraft).where(CharacterDraft.mode=="edit"))
        edit_id,edit_version=editing.id,editing.version
        character=db.scalar(select(Character))
        character.notes="Another window changed this record"
        db.commit()
    assert finish(env,c,edit_id,edit_version).status_code==409


@pytest.mark.parametrize("override",[{"abilities":[]},{"armor":[]},{"extra_class_skills":[{}]},{"adaptability":[]},{"point_budget":15.0},{"class_id":"armiger"},{"scores":{"str":99}}])
def test_malformed_or_third_party_draft_inputs_are_rejected(env,override):
    c,draft_id,version,data=start(env)
    data.update(override)
    assert save(env,c,draft_id,version,data).status_code==422


def test_racial_adjustments_and_first_level_spellbook_requirements(env):
    data=defaults(env.player.id)
    data.update(name="Elven wizard",race="elf",class_id="wizard",skills={"spellcraft":1,"knowledge-arcana":1,"perception":1},
                feats=[{"name":"Iron Will"}],spells=["Mage Armor","Magic Missile","Shield","Sleep"])
    result=calculate(clean(data,env.player.id),{})
    assert not result["errors"] and result["scores"]["int"]==12 and result["scores"]["con"]==8
    assert result["hp"]==6 and result["saves"]["will"]==4 and result["spell_count"]==4
    data["spells"]=[]
    assert any(error["step"]==11 for error in calculate(clean(data,env.player.id),{})["errors"])


def test_first_level_feat_prerequisites_are_enforced(env):
    data=fighter(defaults(env.player.id))
    data["feats"][0]={"name":"Power Attack"}
    # The human +2 bonus defaults to Strength: 12 is still short of 13.
    assert any("Strength 13" in error["message"] for error in calculate(clean(data,env.player.id),{})["errors"])


def test_vigilante_bab_uses_explicit_specialization_not_freeform_notes(env):
    data=defaults(env.player.id)
    data.update(class_id="vigilante",class_notes="Stalker, not an avenger.")
    assert calculate(clean(data,env.player.id),{})["bab"]==0
    data["vigilante_specialization"]="avenger"
    assert calculate(clean(data,env.player.id),{})["bab"]==1


def test_draft_discard_preserves_existing_characters(env):
    existing=seed_character(env.player)
    c,draft_id,_,_=start(env)
    roll(env,c,draft_id)
    assert env.post(c,f"/api/character-drafts/{draft_id}/discard").status_code==200
    with Session(engine()) as db:
        assert db.get(Character,existing.id) and not db.get(CharacterDraft,draft_id)
        assert db.scalar(select(func.count()).select_from(DiceRoll))==0


def test_wizard_migration_preserves_existing_characters(env,isolated_database):
    from pathkeeper.migrations import migrate
    character=seed_character(env.player,name="A legacy hero")
    with isolated_database.begin() as connection:
        connection.execute(text("ALTER TABLE characters DROP COLUMN sheet_data"))
        connection.execute(text("DELETE FROM schema_migrations WHERE version=3"))
    migrate(isolated_database)
    migrate(isolated_database)
    with Session(engine()) as db:
        restored=db.get(Character,character.id)
        assert restored.name=="A legacy hero" and restored.sheet_data is None
        assert db.get(SchemaMigration,3)
