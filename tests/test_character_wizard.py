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
    response = c.get("/characters/new",follow_redirects=True)
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


def test_drafts_are_listed_and_add_character_creates_an_independent_draft(env):
    c,draft_id,version,data = start(env)
    data["name"] = "A saved idea"
    saved = save(env,c,draft_id,version,data,3)
    assert saved.status_code == 200
    response = c.get(f"/characters/drafts/{draft_id}")
    assert "A saved idea" in response.text and '"step": 3' in response.text
    listing = c.get("/characters")
    assert "A saved idea" in listing.text and "Draft" in listing.text
    assert f'href="/characters/drafts/{draft_id}"' in listing.text
    created = c.get("/characters/new")
    assert created.status_code == 303
    new_path = created.headers["location"]
    assert new_path != f"/characters/drafts/{draft_id}"
    for _ in range(2):
        page = c.get(new_path)
        assert page.status_code == 200
        boot = json.loads(re.search(r'<script type="application/json" id="pw-bootstrap">(.*?)</script>',page.text,re.S).group(1))
        assert boot["data"]["name"] == "" and boot["step"] == 1
    with Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(CharacterDraft)) == 2
        assert db.scalar(select(func.count()).select_from(Character)) == 0
        assert db.get(CharacterDraft,draft_id).data["name"] == "A saved idea"
    listing = c.get("/characters")
    assert "Unnamed character" in listing.text and "Add character" in listing.text
    assert f'href="{new_path}"' in listing.text


def test_wizard_ability_assignment_order_is_explicit_despite_sorted_json(env):
    c,draft_id,_,_=start(env)
    page=c.get(f"/characters/drafts/{draft_id}")
    boot=json.loads(re.search(r'<script type="application/json" id="pw-bootstrap">(.*?)</script>',page.text,re.S).group(1))
    assert boot["ability_order"]==["str","dex","con","int","wis","cha"]


def test_character_search_includes_draft_names_and_classes(env):
    client,draft_id,version,data = start(env)
    data.update(name="Unfinished knight",class_id="fighter")
    assert save(env,client,draft_id,version,data).status_code == 200
    second = client.get("/characters/new")
    second_id = second.headers["location"].rsplit("/",1)[1]
    second_data = defaults(env.player.id)
    second_data.update(name="Moon scholar",class_id="wizard")
    assert save(env,client,second_id,1,second_data).status_code == 200
    for query,visible,hidden in [("UNFINISHED","Unfinished knight","Moon scholar"),
                                 ("wizard","Moon scholar","Unfinished knight")]:
        listing = client.get("/characters",params={"q":query})
        assert visible in listing.text and hidden not in listing.text
    assert "A hero waiting to happen." in client.get("/characters",params={"q":"no such hero"}).text
    assert "Unfinished knight" in client.get(f"/characters/drafts/{draft_id}").text


def test_new_draft_keeps_requested_campaign_despite_an_existing_draft(env):
    client,draft_id,_,_ = start(env,env.gm)
    campaign = seed_campaign(env.gm)
    response = client.get("/characters/new",params={"campaign_id":campaign.id})
    assert response.status_code == 303
    new_id = response.headers["location"].rsplit("/",1)[1]
    with Session(engine()) as db:
        assert new_id != draft_id
        assert db.get(CharacterDraft,new_id).data["campaign_id"] == campaign.id
        assert db.get(CharacterDraft,draft_id).data["campaign_id"] is None


def test_wizard_starts_at_sheet_with_abilities_fourth_and_no_dice_step(env):
    client,draft_id,version,data = start(env)
    page = client.get(f"/characters/drafts/{draft_id}")
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
    page = client.get(f"/characters/drafts/{draft_id}")
    boot = json.loads(re.search(r'<script type="application/json" id="pw-bootstrap">(.*?)</script>',page.text,re.S).group(1))
    assert boot["steps"][str(boot["step"])] == title
    assert boot["step_order"].index(boot["step"]) + 1 == number
    assert boot["data"]["name"] == "Keep my draft"


@pytest.mark.parametrize("account",["player2","gm","admin"])
def test_other_accounts_cannot_read_save_roll_or_finalize_private_draft(env,account):
    owner,draft_id,version,data = start(env)
    data["name"] = "A private unfinished hero"
    assert save(env,owner,draft_id,version,data).status_code == 200
    other = env.login(getattr(env,account))
    assert other.get(f"/characters/drafts/{draft_id}").status_code == 404
    listing = other.get("/characters")
    assert draft_id not in listing.text and data["name"] not in listing.text
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
    assert page.status_code == 200 and "Seren Ashfall" in page.text and "Deluxe Character Sheet" in page.text
    assert f'href="/characters/drafts/{draft_id}"' not in c.get("/characters").text
    assert c.get(f"/characters/drafts/{draft_id}").headers["location"] == path
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
        assert character.owner_id==env.gm.id and character.campaign_id==campaign.id
    # Another GM cannot view that sheet or begin an editing draft.
    other=env.login(env.gm2)
    assert other.get(result.json()["location"]+"/sheet/edit").status_code==404


@pytest.mark.parametrize("actor", ["gm", "admin"])
def test_legacy_creation_draft_cannot_assign_another_owner(env,actor):
    account = getattr(env,actor)
    client,draft_id,_,data = start(env,account)
    data = fighter(data)
    data["owner_id"] = env.player2.id
    with Session(engine()) as db:
        draft = db.get(CharacterDraft,draft_id)
        draft.data = data
        db.commit()
        version = draft.version
    page = client.get(f"/characters/drafts/{draft_id}")
    boot = json.loads(re.search(r'<script type="application/json" id="pw-bootstrap">(.*?)</script>',page.text,re.S).group(1))
    assert boot["data"]["owner_id"] == account.id and "owners" not in boot
    response = finish(env,client,draft_id,version)
    assert response.status_code == 200
    with Session(engine()) as db:
        character = db.get(Character,int(response.json()["location"].rsplit("/",1)[1]))
        assert character.owner_id == account.id
        assert character.sheet_data["input"]["owner_id"] == account.id


@pytest.mark.parametrize("actor", ["player", "gm", "admin"])
def test_new_character_always_belongs_to_its_creator(env,actor):
    account = getattr(env,actor)
    c,draft_id,version,data=start(env,account)
    data=fighter(data)
    data["owner_id"]=env.player2.id
    saved=save(env,c,draft_id,version,data)
    with Session(engine()) as db:
        assert db.get(CharacterDraft,draft_id).data["owner_id"] == account.id
    result=finish(env,c,draft_id,saved.json()["version"])
    assert result.status_code==200
    with Session(engine()) as db:
        character=db.scalar(select(Character))
        assert character.owner_id==account.id and character.sheet_data["input"]["owner_id"]==account.id


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


@pytest.mark.parametrize("override",[{"abilities":[]},{"armor":[]},{"extra_class_skills":["perception"]},{"class_notes":"Legacy class notes"},{"adaptability":[]},{"point_budget":15.0},{"class_id":"armiger"},{"scores":{"str":99}}])
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


def test_any_catalog_skill_can_receive_a_rank_without_changing_class_skills(env):
    data = fighter(defaults(env.player.id))
    data["skills"] = {"climb":1,"perception":1,"knowledge-arcana":1}
    result = calculate(clean(data,env.player.id),{})
    assert not result["errors"]
    assert "climb" in result["class_skills"]
    assert "perception" not in result["class_skills"]
    assert "knowledge-arcana" not in result["class_skills"]
    # Climb includes +1 rank, +1 Strength, +3 class skill, and -2 shield penalty.
    assert result["skill_totals"]["climb"] == 3
    assert result["skill_totals"]["perception"] == 1
    assert result["skill_totals"]["knowledge-arcana"] == 1
    data["skills"] = {"climb":0,"perception":1,"knowledge-arcana":1,"ride":1}
    untrained = calculate(clean(data,env.player.id),{})
    assert not untrained["errors"]
    assert untrained["class_skills"] == result["class_skills"]
    assert untrained["skill_totals"]["climb"] == -1


def test_vigilante_bab_uses_explicit_specialization(env):
    data = defaults(env.player.id)
    data["class_id"] = "vigilante"
    assert calculate(clean(data,env.player.id),{})["bab"] == 0
    data["vigilante_specialization"] = "avenger"
    assert calculate(clean(data,env.player.id),{})["bab"] == 1


def test_draft_discard_preserves_existing_characters(env):
    existing=seed_character(env.player)
    c,draft_id,_,_=start(env)
    roll(env,c,draft_id)
    assert env.post(c,f"/api/character-drafts/{draft_id}/discard").status_code==200
    assert f'href="/characters/drafts/{draft_id}"' not in c.get("/characters").text
    assert c.get(f"/characters/drafts/{draft_id}").status_code == 404
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


def test_migration_removes_retired_fields_and_recalculates_fixed_class_skills(env,isolated_database):
    from pathkeeper.migrations import migrate
    from pathkeeper.pf1_data import CLASSES

    client,completed_draft_id,version,data = start(env)
    data = fighter(data)
    data["notes"] = "Keep this character's story."
    saved = save(env,client,completed_draft_id,version,data)
    character_path = finish(env,client,completed_draft_id,saved.json()["version"]).json()["location"]
    character_id = int(character_path.rsplit("/",1)[1])
    pending_id,current_edit_id,stale_edit_id = [secrets.token_hex(16) for _ in range(3)]
    with Session(engine()) as db:
        character = db.get(Character,character_id)
        old_input = {**character.sheet_data["input"],"class_notes":"Remove this source note.",
                     "extra_class_skills":["perception"]}
        old_computed = deepcopy(character.sheet_data["computed"])
        old_computed["class_skills"].append("perception")
        old_computed["skill_totals"]["perception"] += 3
        character.sheet_data = {**character.sheet_data,"input":old_input,"computed":old_computed}
        completed = db.get(CharacterDraft,completed_draft_id)
        completed.data = old_input
        db.flush()
        old_character_version = character.version
        db.add_all([
            CharacterDraft(id=pending_id,actor_id=env.player.id,data=old_input,step=5),
            CharacterDraft(id=current_edit_id,actor_id=env.player.id,data=old_input,step=5,mode="edit",
                           editing_id=character_id,existing_version=old_character_version),
            CharacterDraft(id=stale_edit_id,actor_id=env.player.id,data=old_input,step=5,mode="edit",
                           editing_id=character_id,existing_version=old_character_version-1),
        ])
        db.flush()
        db.add(DiceRoll(id=secrets.token_hex(16),draft_id=pending_id,actor_id=env.player.id,
                       request_id=secrets.token_hex(16),purpose="free",result={"sides":6,"dice":[4],"total":4,"modifier":0}))
        db.commit()
    migrate(isolated_database)
    with Session(engine()) as db:
        character = db.get(Character,character_id)
        assert "class_notes" not in character.sheet_data["input"]
        assert "extra_class_skills" not in character.sheet_data["input"]
        assert character.sheet_data["computed"]["class_skills"] == sorted(CLASSES["fighter"]["skills"])
        assert character.sheet_data["computed"]["skill_totals"]["perception"] == 1
        assert character.sheet_data["input"]["skills"] == data["skills"]
        assert character.notes == data["notes"]
        for draft in db.scalars(select(CharacterDraft)):
            assert "class_notes" not in draft.data and "extra_class_skills" not in draft.data
        pending = db.get(CharacterDraft,pending_id)
        assert pending.step == 5 and pending.data["name"] == data["name"]
        assert db.scalar(select(func.count()).select_from(DiceRoll).where(DiceRoll.draft_id==pending_id)) == 1
        assert db.get(CharacterDraft,completed_draft_id).completed_id == character_id
        assert db.get(CharacterDraft,current_edit_id).existing_version == character.version
        assert db.get(CharacterDraft,stale_edit_id).existing_version == old_character_version-1
        versions = (character.version,pending.version)
        assert db.get(SchemaMigration,4)
    assert save(env,client,pending_id,1,old_input,5).status_code == 409
    assert client.get(f"/characters/drafts/{pending_id}").status_code == 200
    migrate(isolated_database)
    with Session(engine()) as db:
        assert (db.get(Character,character_id).version,db.get(CharacterDraft,pending_id).version) == versions
