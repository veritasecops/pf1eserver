from hashlib import sha256
from string import ascii_uppercase

from pathkeeper.monsters import monsters
from scripts.import_aon_monsters import detail_sections, index_entries


def test_monster_snapshot_covers_each_letter_and_stat_block():
    entries = monsters()
    assert len(entries) == 3017
    assert {row["letter"] for entry in entries.values() for row in entry["rows"]} == set(ascii_uppercase)
    for entry in entries.values():
        assert entry["url"].startswith("https://www.aonprd.com/MonsterDisplay.aspx?ItemName=")
        assert {"Defense", "Offense", "Statistics"} <= {section["heading"] for section in entry["sections"]}
    spider = entries[sha256(b"Scarlet Spider").hexdigest()]
    assert {row["letter"] for row in spider["rows"]} == {"F", "S"}


def test_monster_import_keeps_fields_and_additional_headings():
    index = """
    <tr><td><font><a href="MonsterDisplay.aspx?ItemName=Test%20Beast">Beast, Test</a></font></td>
    <td>1/2</td><td>animal</td><td>temperate forest</td></tr>
    """
    assert list(index_entries(index, "B")) == [
        ("Test Beast", {"letter": "B", "name": "Beast, Test", "cr": "1/2", "type": "animal",
                        "environment": "temperate forest"})
    ]
    detail = """
    <td><span id="MainContent_DataListFeats_Label1_0">
      <h1>Beast, Test</h1><h2>Test Beast CR 1/2</h2><b>XP</b> 200
      <h3>Defense</h3><b>AC</b> 12<br><b>hp</b> 9 (2d8)
      <h3>Special Abilities</h3><b>Power (Su)</b> The beast can use this power once every 3 rounds.
      <h3>Description</h3>A long descriptive paragraph about the fictional creature.
      <h1>Related Rules</h1><b>Duration</b> 1 hour
    </span></td>
    """
    sections = detail_sections(detail)
    assert [section["heading"] for section in sections] == [
        "Beast, Test", "Test Beast CR 1/2", "Defense", "Special Abilities", "Description", "Related Rules",
    ]
    assert sections[2]["fields"] == [["AC", "12"], ["hp", "9 (2d8)"]]
    assert sections[3]["fields"] == [["Power (Su)", "3 rounds"]]
    assert sections[4]["fields"] == [] and sections[4]["source_detail"]


def test_admin_monster_browsing_and_details(env):
    path = "/administration/monsters"
    key = sha256(b"Akata").hexdigest()
    detail_path = f"{path}/{key}"
    player = env.login(env.player)
    assert player.get(path).status_code == 403
    assert player.get(detail_path).status_code == 403

    admin = env.login(env.admin)
    catalog = admin.get("/administration/catalog").text
    assert 'href="/administration/monsters" >Monsters</a>' in catalog
    assert 'kind=monsters">Monsters</a>' not in catalog
    all_monsters = admin.get(path)
    assert all_monsters.status_code == 200
    active_tab = 'href="/administration/monsters" class="active" aria-current="page">Monsters</a>'
    assert active_tab in all_monsters.text
    assert 'aria-label="Catalog lists"' not in all_monsters.text
    assert "3017 monsters" in all_monsters.text and "Page 1 of 61" in all_monsters.text
    for letter in ascii_uppercase:
        assert f"letter={letter}&amp;q=" in all_monsters.text
    listing = admin.get(path, params={"letter": "a", "q": "akata"})
    assert "1 monster" in listing.text
    assert f'href="{detail_path}?letter=A&amp;q=akata&amp;page=1"' in listing.text
    wrong_letter = admin.get(path, params={"letter": "B", "q": "akata"})
    assert "No matching monsters." in wrong_letter.text

    detail = admin.get(detail_path, params={"letter": "A", "q": "akata", "page": 2})
    assert detail.status_code == 200
    assert active_tab in detail.text
    for section in ("Defense", "Offense", "Statistics", "Ecology", "Special Abilities", "Description", "Void Zombie"):
        assert section in detail.text
    assert "15 (2d8+6)" in detail.text
    assert "https://www.aonprd.com/MonsterDisplay.aspx?ItemName=Akata" in detail.text
    assert f'{path}?letter=A&amp;q=akata&amp;page=2' in detail.text
    assert admin.get(f"{path}/missing").status_code == 404

    old_list = admin.get("/administration/catalog", params={"kind": "monsters", "letter": "A", "q": "akata"})
    assert old_list.status_code == 303 and old_list.headers["location"] == f"{path}?letter=A&q=akata"
    old_detail = admin.get(f"/administration/catalog/monsters/{key}", params={"letter": "A"})
    assert old_detail.status_code == 303 and old_detail.headers["location"] == f"{detail_path}?letter=A"
