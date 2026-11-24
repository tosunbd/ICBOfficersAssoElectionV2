"""Ballot entry: users, number ranges, one-by-one numbering, the null-vote rules, reports."""

import pytest

from tests.conftest import PASSWORDS

LEFT_COLUMN = ["13", "30", "74", "90", "124", "99", "126", "247", "174", "354", "323", "336", "20", "33", "35"]
RIGHT_COLUMN = ["12", "28", "40", "68", "70", "113", "144", "134", "283", "257", "345", "186", "76", "237", "431"]


async def enter(client, headers, ballot_no, candidate_ids, expect=201):
    response = await client.post("/api/entry/ballots", headers=headers, json={"ballot_no": ballot_no, "candidate_ids": candidate_ids})
    assert response.status_code == expect, response.text
    return response.json()


async def votes(client, headers, election_id) -> dict[str, int]:
    """voter_no -> counted votes."""
    data = (await client.get(f"/api/dashboard/results/{election_id}", headers=headers)).json()
    return {c["voter_no"]: c["vote_count"] for p in data["positions"] for c in p["candidates"]}


# ------------------------------------------------------------------ users
@pytest.mark.parametrize("username,role,span", [
    ("SA", "superadmin", (None, None)),
    ("Admin", "admin", (None, None)),
    ("EC1", "ec", (1, 150)),
    ("EC2", "ec", (151, 300)),
    ("EC3", "ec", (301, 455)),
])
async def test_the_five_users_can_sign_in(client, username, role, span):
    response = await client.post("/api/auth/login", json={"username": username, "password": PASSWORDS[username]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == role
    assert (body["ballot_from"], body["ballot_to"]) == span


async def test_username_is_not_case_sensitive_but_the_password_is(client):
    assert (await client.post("/api/auth/login", json={"username": "ec1", "password": "EC1"})).status_code == 200
    assert (await client.post("/api/auth/login", json={"username": "EC1", "password": "ec1"})).status_code == 401
    assert (await client.post("/api/auth/login", json={"username": "SA", "password": "admin"})).status_code == 401


async def test_seeded_election_matches_the_ballot_paper(election):
    assert election["title_bn"] == "আইসিবি কর্মকর্তা সমিতির ২০তম কার্যনির্বাহী পরিষদ নির্বাচন-২০২৬"
    assert election["total_voters"] == 455
    assert [p["max_selections"] for p in election["positions"]] == [1] * 12 + [3]
    assert election["positions"][12]["name_bn"] == "নির্বাহী সদস্য"
    assert len(election["candidates"]) == 30
    executive = [c["voter_no"] for c in election["candidates"] if c["position_id"] == election["positions"][12]["id"]]
    assert executive == ["20", "76", "33", "237", "35", "431"]  # left, right, left, right ... as printed


# ----------------------------------------------------- numbering and ranges
async def test_ballots_come_one_by_one(client, login, election, ids):
    ec1 = await login("EC1")
    state = (await client.get("/api/entry/state", headers=ec1)).json()
    desk = next(d for d in state["desks"] if d["username"] == "EC1")
    assert state["me"] == "EC1" and desk["next_ballot_no"] == 1 and desk["next_label"] == "000001" and desk["total"] == 150

    saved = await enter(client, ec1, 1, ids("13"))
    assert saved["ballot"]["label"] == "000001" and saved["desk"]["next_label"] == "000002" and saved["desk"]["entered"] == 1

    # not the next number, and a number already used
    skipped = await client.post("/api/entry/ballots", headers=ec1, json={"ballot_no": 3, "candidate_ids": []})
    assert skipped.status_code == 409 and "000002" in skipped.json()["detail"]
    again = await client.post("/api/entry/ballots", headers=ec1, json={"ballot_no": 1, "candidate_ids": []})
    assert again.status_code == 409 and "already entered" in again.json()["detail"]

    assert (await enter(client, ec1, 2, []))["desk"]["next_label"] == "000003"  # a blank paper is a ballot too


@pytest.mark.parametrize("username,first,outside", [("EC1", 1, 160), ("EC2", 151, 320), ("EC2", 151, 150), ("EC3", 301, 300), ("EC3", 301, 456)])
async def test_a_commissioner_cannot_enter_a_ballot_outside_the_range(client, login, election, username, first, outside):
    headers = await login(username)
    response = await client.post("/api/entry/ballots", headers=headers, json={"ballot_no": outside, "candidate_ids": []})
    assert response.status_code == 403, response.text
    assert "outside your range" in response.json()["detail"]
    await enter(client, headers, first, [])


async def test_three_desks_enter_at_the_same_time(client, login, election, ids):
    import asyncio

    headers = {name: await login(name) for name in ("EC1", "EC2", "EC3")}
    starts = {"EC1": 1, "EC2": 151, "EC3": 301}
    for offset in range(5):
        await asyncio.gather(*[
            enter(client, headers[name], starts[name] + offset, ids("13", "30")) for name in headers
        ])
    state = (await client.get("/api/entry/state", headers=await login("Admin"))).json()
    assert state["total_entered"] == 15 and state["total_ballots"] == 455
    assert {d["username"]: d["next_ballot_no"] for d in state["desks"]} == {"EC1": 6, "EC2": 156, "EC3": 306}
    counted = await votes(client, await login("Admin"), election["id"])
    assert counted["13"] == 15 and counted["30"] == 15


async def test_only_commissioners_enter_and_only_admins_administer(client, login, election):
    for name in ("SA", "Admin"):
        response = await client.post("/api/entry/ballots", headers=await login(name), json={"ballot_no": 1, "candidate_ids": []})
        assert response.status_code == 403
        assert (await client.get("/api/entry/state", headers=await login(name))).status_code == 200  # they can watch
    ec1 = await login("EC1")
    assert (await client.get(f"/api/reports/{election['id']}", headers=ec1)).status_code == 403
    assert (await client.get(f"/api/ballots?election_id={election['id']}", headers=ec1)).status_code == 403
    assert (await client.put(f"/api/admin/dashboard/{election['id']}/publish?publish=true", headers=ec1)).status_code == 403
    assert (await client.post("/api/entry/ballots", json={"ballot_no": 1, "candidate_ids": []})).status_code in (401, 403)
    # deleting ballots is for the Super Admin alone
    admin = await login("Admin")
    response = await client.post("/api/ballots/bulk-delete", headers=admin, json={"election_id": election["id"], "all_matching": True})
    assert response.status_code == 403


# ------------------------------------------------------------------- rules
async def test_one_mark_per_post_counts(client, login, election, ids):
    saved = await enter(client, await login("EC1"), 1, ids(*LEFT_COLUMN))  # "select all" on the left side
    assert saved["ballot"]["counted"] == 15 and saved["ballot"]["null_marks"] == 0
    counted = await votes(client, await login("Admin"), election["id"])
    assert all(counted[v] == 1 for v in LEFT_COLUMN) and all(counted[v] == 0 for v in RIGHT_COLUMN)


async def test_two_marks_for_one_post_is_a_null_vote_for_that_post_only(client, login, election, ids):
    saved = await enter(client, await login("EC1"), 1, ids("13", "12", "30"))  # both candidates for President
    ballot = saved["ballot"]
    assert ballot["counted"] == 1 and ballot["null_marks"] == 2
    assert sorted(ballot["null_candidate_ids"]) == sorted(ids("13", "12"))
    assert ballot["null_posts"] == [{"position_id": election["positions"][0]["id"], "name_en": "President", "name_bn": "সভাপতি", "marked": 2, "allowed": 1}]
    counted = await votes(client, await login("Admin"), election["id"])
    assert counted["13"] == 0 and counted["12"] == 0 and counted["30"] == 1


@pytest.mark.parametrize("marked,counts", [
    ([], 0),
    (["20"], 1),
    (["20", "76"], 2),
    (["20", "33", "35"], 3),            # three: the most allowed
    (["20", "76", "33", "237"], 0),     # four: every executive member vote of the ballot is null
    (["20", "76", "33", "237", "35"], 0),
    (["20", "76", "33", "237", "35", "431"], 0),
])
async def test_executive_member_allows_three_votes_more_is_null(client, login, election, ids, marked, counts):
    saved = await enter(client, await login("EC3"), 301, ids("13", *marked))
    assert saved["ballot"]["counted"] == counts + 1          # the President vote is never affected
    assert saved["ballot"]["null_marks"] == (len(marked) if counts == 0 else 0)
    counted = await votes(client, await login("Admin"), election["id"])
    assert counted["13"] == 1
    for voter_no in marked:
        assert counted[voter_no] == (1 if counts else 0)


async def test_every_box_marked_gives_no_vote_at_all(client, login, election, ids):
    saved = await enter(client, await login("EC2"), 151, ids(*LEFT_COLUMN, *RIGHT_COLUMN))  # "select all" on both sides
    assert saved["ballot"]["counted"] == 0 and saved["ballot"]["null_marks"] == 30 and len(saved["ballot"]["null_posts"]) == 13
    assert sum((await votes(client, await login("Admin"), election["id"])).values()) == 0


async def test_unknown_candidate_is_refused_and_nothing_is_saved(client, login, election):
    ec1 = await login("EC1")
    response = await client.post("/api/entry/ballots", headers=ec1, json={"ballot_no": 1, "candidate_ids": [999999]})
    assert response.status_code == 400
    state = (await client.get("/api/entry/state", headers=ec1)).json()
    assert state["desks"][0]["next_ballot_no"] == 1


# ------------------------------------------------- corrections and deletion
async def test_a_blank_ballot_is_counted_with_no_votes(client, login, election, ids):
    """A voter who votes for nobody: the paper is a counted ballot, no candidate gets a vote."""
    ec1, admin = await login("EC1"), await login("Admin")
    saved = await enter(client, ec1, 1, [])
    assert saved["ballot"]["counted"] == 0 and saved["ballot"]["null_marks"] == 0 and saved["ballot"]["candidate_ids"] == []
    assert saved["desk"]["next_label"] == "000002" and saved["desk"]["entered"] == 1
    await enter(client, ec1, 2, ids("13"))
    data = (await client.get(f"/api/dashboard/results/{election['id']}", headers=admin)).json()
    assert data["stats"]["counted_ballots"] == 2                     # the blank paper is a ballot
    assert sum(c["vote_count"] for p in data["positions"] for c in p["candidates"]) == 1
    report = (await client.get(f"/api/reports/{election['id']}", headers=admin)).json()
    assert [(b["ballot_paper_no"], b["candidate_ids"]) for b in report["ballots"]] == [("000001", []), ("000002", ids("13"))]
    assert report["stats"]["counted_ballots"] == 2 and report["total_votes"] == 1


async def test_a_correction_counts_only_after_approval(client, login, election, ids):
    ec1, ec2, admin, sa = await login("EC1"), await login("EC2"), await login("Admin"), await login("SA")
    await enter(client, ec1, 1, ids("13", "12"))                      # wrong entry: null vote for President

    # the desk asks for a correction: kept apart, nothing changes yet
    response = await client.put("/api/entry/ballots/1", headers=ec1, json={"candidate_ids": ids("13")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ballot"]["status"] == "processed" and body["ballot"]["candidate_ids"] == sorted(ids("13", "12"))
    pending = body["ballot"]["pending"]
    assert pending["status"] == "pending" and pending["requested_by"] == "EC1" and pending["candidate_ids"] == ids("13")
    assert (pending["previous_counted"], pending["previous_null_marks"], pending["counted"], pending["null_marks"]) == (0, 2, 1, 0)
    assert body["desk"]["pending_corrections"] == 1
    assert (await votes(client, admin, election["id"]))["13"] == 0   # dashboard and totals: unchanged
    report = (await client.get(f"/api/reports/{election['id']}", headers=admin)).json()
    assert report["total_votes"] == 0 and report["manual_ballots"] == 0

    # the Super Admin and the Admin see it waiting; a commissioner cannot approve, not even the own one
    state = (await client.get("/api/entry/state", headers=admin)).json()
    assert state["pending_corrections"] == 1
    waiting = (await client.get("/api/entry/corrections", headers=sa)).json()
    assert [(c["label"], c["requested_by"]) for c in waiting] == [("000001", "EC1")]
    assert (await client.get("/api/entry/corrections", headers=ec2)).json() == []  # not EC2's range
    for headers in (ec1, ec2):
        assert (await client.post(f"/api/entry/corrections/{pending['id']}/approve", headers=headers)).status_code == 403

    # approval: now the ballot and the totals change
    response = await client.post(f"/api/entry/corrections/{pending['id']}/approve", headers=admin)
    assert response.status_code == 200, response.text
    decided = response.json()
    assert decided["correction"]["status"] == "approved" and decided["correction"]["decided_by"] == "Admin"
    ballot = decided["ballot"]
    assert ballot["status"] == "reviewed" and ballot["corrected_by"] == "EC1" and ballot["approved_by"] == "Admin"
    assert ballot["candidate_ids"] == ids("13") and ballot["counted"] == 1 and ballot["pending"] is None
    counted = await votes(client, admin, election["id"])
    assert counted["13"] == 1 and counted["12"] == 0
    report = (await client.get(f"/api/reports/{election['id']}", headers=admin)).json()
    assert report["total_votes"] == 1 and report["manual_ballots"] == 1
    assert (await client.get("/api/entry/state", headers=admin)).json()["pending_corrections"] == 0
    # a decision is final
    assert (await client.post(f"/api/entry/corrections/{pending['id']}/reject", headers=sa)).status_code == 409

    # not somebody else's ballot, not by an admin, not a paper that does not exist yet, not "no change"
    assert (await client.put("/api/entry/ballots/1", headers=ec2, json={"candidate_ids": []})).status_code == 403
    assert (await client.put("/api/entry/ballots/1", headers=admin, json={"candidate_ids": []})).status_code == 403
    assert (await client.put("/api/entry/ballots/2", headers=ec1, json={"candidate_ids": []})).status_code == 404
    assert (await client.put("/api/entry/ballots/1", headers=ec1, json={"candidate_ids": ids("13")})).status_code == 400
    # everybody may look at it; a commissioner only inside the own range
    assert (await client.get("/api/entry/ballots/1", headers=admin)).json()["candidate_ids"] == ids("13")
    assert (await client.get("/api/entry/ballots/1", headers=ec2)).status_code == 403


async def test_a_rejected_or_withdrawn_correction_changes_nothing(client, login, election, ids):
    ec1, sa, admin = await login("EC1"), await login("SA"), await login("Admin")
    await enter(client, ec1, 1, ids("13"))
    first = (await client.put("/api/entry/ballots/1", headers=ec1, json={"candidate_ids": ids("12")})).json()["ballot"]["pending"]
    # asking again replaces the waiting request instead of adding a second one
    second = (await client.put("/api/entry/ballots/1", headers=ec1, json={"candidate_ids": ids("12", "30")})).json()["ballot"]["pending"]
    assert second["id"] == first["id"] and second["candidate_ids"] == sorted(ids("12", "30"))
    assert len((await client.get("/api/entry/corrections", headers=sa)).json()) == 1

    response = await client.post(f"/api/entry/corrections/{second['id']}/reject", headers=sa)
    assert response.status_code == 200 and response.json()["correction"]["status"] == "rejected"
    ballot = response.json()["ballot"]
    assert ballot["status"] == "processed" and ballot["candidate_ids"] == ids("13") and ballot["pending"] is None
    counted = await votes(client, admin, election["id"])
    assert (counted["13"], counted["12"], counted["30"]) == (1, 0, 0)

    # withdrawn by the desk before anybody decided
    third = (await client.put("/api/entry/ballots/1", headers=ec1, json={"candidate_ids": []})).json()["ballot"]["pending"]
    assert third["id"] != second["id"]
    assert (await client.delete(f"/api/entry/corrections/{third['id']}", headers=admin)).status_code == 403
    response = await client.delete(f"/api/entry/corrections/{third['id']}", headers=ec1)
    assert response.status_code == 200 and response.json()["ballot"]["pending"] is None and response.json()["desk"]["pending_corrections"] == 0
    assert (await client.post(f"/api/entry/corrections/{third['id']}/approve", headers=sa)).status_code == 409
    assert (await votes(client, admin, election["id"]))["13"] == 1
    history = (await client.get("/api/entry/corrections?status=all", headers=sa)).json()
    assert sorted(c["status"] for c in history) == ["rejected", "withdrawn"]

    # a deleted ballot takes its waiting correction with it
    fourth = (await client.put("/api/entry/ballots/1", headers=ec1, json={"candidate_ids": ids("12")})).json()["ballot"]
    assert (await client.delete(f"/api/ballots/{fourth['ballot_id']}", headers=sa)).status_code == 204
    assert (await client.get("/api/entry/corrections", headers=sa)).json() == []
    assert (await client.post(f"/api/entry/corrections/{fourth['pending']['id']}/approve", headers=sa)).status_code == 404


async def test_admins_edit_any_saved_ballot_directly(client, login, election, ids):
    ec1, ec3, admin, sa = await login("EC1"), await login("EC3"), await login("Admin"), await login("SA")
    await enter(client, ec1, 1, ids("13", "12"))                      # null vote for President
    await enter(client, ec3, 301, ids("30"))

    # the Admin edits a ballot of EC1's range: counted at once, no approval
    response = await client.put("/api/entry/ballots/1/edit", headers=admin, json={"candidate_ids": ids("13")})
    assert response.status_code == 200, response.text
    ballot = response.json()
    assert ballot["status"] == "reviewed" and ballot["corrected_by"] == "Admin" and ballot["approved_by"] is None
    assert ballot["candidate_ids"] == ids("13") and (ballot["counted"], ballot["null_marks"]) == (1, 0)
    counted = await votes(client, admin, election["id"])
    assert (counted["13"], counted["12"]) == (1, 0)

    # the Super Admin edits one of EC3's range, here to a blank ballot
    response = await client.put("/api/entry/ballots/301/edit", headers=sa, json={"candidate_ids": []})
    assert response.status_code == 200 and response.json()["corrected_by"] == "SA" and response.json()["counted"] == 0
    assert (await votes(client, admin, election["id"]))["30"] == 0
    report = (await client.get(f"/api/reports/{election['id']}", headers=admin)).json()
    assert report["total_votes"] == 1 and report["manual_ballots"] == 2

    # only on the admin side; only a saved ballot; a real change; a candidate of this ballot
    for headers in (ec1, ec3):
        assert (await client.put("/api/entry/ballots/1/edit", headers=headers, json={"candidate_ids": []})).status_code == 403
    assert (await client.put("/api/entry/ballots/2/edit", headers=admin, json={"candidate_ids": []})).status_code == 404
    assert (await client.put("/api/entry/ballots/1/edit", headers=admin, json={"candidate_ids": ids("13")})).status_code == 400
    assert (await client.put("/api/entry/ballots/1/edit", headers=admin, json={"candidate_ids": [999999]})).status_code == 400
    assert (await votes(client, admin, election["id"]))["13"] == 1   # the refused edits changed nothing
    # the desk still enters its next number
    await enter(client, ec1, 2, ids("12"))

    # a correction the desk has waiting: kept and compared against the new ticks ...
    pending = (await client.put("/api/entry/ballots/1", headers=ec1, json={"candidate_ids": ids("12")})).json()["ballot"]["pending"]
    ballot = (await client.put("/api/entry/ballots/1/edit", headers=sa, json={"candidate_ids": ids("13", "30")})).json()
    assert ballot["pending"]["id"] == pending["id"] and ballot["pending"]["previous_candidate_ids"] == sorted(ids("13", "30"))
    # ... and done when the edit saves exactly what it asked for
    ballot = (await client.put("/api/entry/ballots/1/edit", headers=admin, json={"candidate_ids": ids("12")})).json()
    assert ballot["pending"] is None and ballot["candidate_ids"] == ids("12")
    assert (await client.get("/api/entry/corrections", headers=sa)).json() == []
    counted = await votes(client, admin, election["id"])
    assert (counted["13"], counted["12"], counted["30"]) == (0, 2, 0)


async def test_a_deleted_ballot_is_the_next_one_to_enter_again(client, login, election, ids):
    ec1, sa = await login("EC1"), await login("SA")
    for number in (1, 2, 3):
        await enter(client, ec1, number, ids("13"))
    listing = (await client.get(f"/api/ballots?election_id={election['id']}&ballot_no=2", headers=sa)).json()
    assert listing["total"] == 1 and listing["ballots"][0]["entered_by"] == "EC1"
    assert (await client.delete(f"/api/ballots/{listing['ballots'][0]['id']}", headers=sa)).status_code == 204
    state = (await client.get("/api/entry/state", headers=ec1)).json()
    assert state["desks"][0]["next_ballot_no"] == 2 and state["desks"][0]["entered"] == 2
    assert (await votes(client, sa, election["id"]))["13"] == 2
    assert (await enter(client, ec1, 2, ids("12")))["desk"]["next_ballot_no"] == 4


async def test_paused_counting_blocks_saving(client, login, election, ids):
    admin, ec1 = await login("Admin"), await login("EC1")
    await client.put(f"/api/admin/counting/{election['id']}/pause?pause=true", headers=admin)
    response = await client.post("/api/entry/ballots", headers=ec1, json={"ballot_no": 1, "candidate_ids": ids("13")})
    assert response.status_code == 409 and "paused" in response.json()["detail"]
    await client.put(f"/api/admin/counting/{election['id']}/pause?pause=false", headers=admin)
    await enter(client, ec1, 1, ids("13"))


# ------------------------------------------------------- monitor and report
async def test_admins_see_the_desk_live(client, login, election, ids):
    ec2, admin = await login("EC2"), await login("Admin")
    await client.get("/api/entry/state", headers=ec2)
    response = await client.put("/api/entry/draft", headers=ec2, json={"ballot_no": 151, "candidate_ids": ids("13", "30")})
    assert response.status_code == 204
    desks = {d["username"]: d for d in (await client.get("/api/entry/state", headers=admin)).json()["desks"]}
    assert desks["EC2"]["online"] and desks["EC2"]["draft"]["label"] == "000151"
    assert desks["EC2"]["draft"]["candidate_ids"] == sorted(ids("13", "30"))
    assert not desks["EC1"]["online"] and desks["EC1"]["draft"] is None
    await enter(client, ec2, 151, ids("13", "30"))
    desks = {d["username"]: d for d in (await client.get("/api/entry/state", headers=admin)).json()["desks"]}
    assert desks["EC2"]["draft"] is None and desks["EC2"]["last_label"] == "000151"
    assert (await client.put("/api/entry/draft", headers=ec2, json={"ballot_no": 5, "candidate_ids": []})).status_code == 403


async def test_report_follows_every_saved_ballot(client, login, election, ids):
    ec1, ec3, admin = await login("EC1"), await login("EC3"), await login("Admin")
    await enter(client, ec3, 301, ids("12", "20", "76", "33"))
    await enter(client, ec1, 1, ids("13", "20", "76", "33", "237"))      # four executive members: null
    await enter(client, ec1, 2, ids("13", "12"))                          # two presidents: null
    report = (await client.get(f"/api/reports/{election['id']}", headers=admin)).json()
    assert report["stats"]["counted_ballots"] == 3 and report["total_voters"] == 455
    assert [b["ballot_paper_no"] for b in report["ballots"]] == ["000001", "000002", "000301"]  # in ballot number order
    assert report["total_votes"] == 5 and report["void_marks"] == 6 and report["manual_ballots"] == 0
    president = report["positions"][0]["candidates"]
    assert {c["voter_no"]: c["votes"] for c in president} == {"13": 1, "12": 1}
    assert all(c["outcome"] == "tie" for c in president)
    executive = {c["voter_no"]: (c["votes"], c["outcome"]) for c in report["positions"][12]["candidates"]}
    assert executive["20"] == (1, "elected") and executive["237"] == (0, "")
    # the tally rows are the same votes
    assert sum(len(b["candidate_ids"]) for b in report["ballots"]) == report["total_votes"]
    # the marks that are not counted, ballot by ballot
    assert [b["void_marks"] for b in report["ballots"]] == [4, 2, 0]
    # the public dashboard follows too; the Admin can hide the numbers
    public = (await client.get(f"/api/dashboard/results/{election['id']}")).json()
    assert public["stats"]["counted_ballots"] == 3 and len(public["positions"]) == 13  # published from the start
    await client.put(f"/api/admin/dashboard/{election['id']}/publish?publish=false", headers=admin)
    hidden = (await client.get(f"/api/dashboard/results/{election['id']}")).json()
    assert hidden["positions"] == [] and hidden["stats"]["counted_ballots"] == 3
    await client.put(f"/api/admin/dashboard/{election['id']}/publish?publish=true", headers=admin)
