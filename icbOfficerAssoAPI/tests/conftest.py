"""Test fixtures.

Every test session gets its own temporary SQLite file, so tests never touch
the real `data/` directory.  The environment must be set BEFORE `app.config`
is imported, which is why this happens at module level.
"""

import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="icb-election-v2-tests-"))
os.environ.update({
    "DATABASE_URL": f"sqlite+aiosqlite:///{(TMP / 'test{Year}.db').as_posix()}",
    "ELECTION_YEAR": "2026",
    "DATABASE_SETTINGS_FILE": str(TMP / "database_settings.json"),
    "ENTRY_RANGES": "EC1:1-150,EC2:151-300,EC3:301-455",
    "BALLOT_NUMBER_DIGITS": "3",
    "JWT_SECRET_KEY": "test-secret",
})

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.routers.entry import reset_live_state  # noqa: E402
from app.seed import ensure_election, ensure_users  # noqa: E402

PASSWORDS = {"SA": "sadmin", "Admin": "admin", "EC1": "EC1", "EC2": "EC2", "EC3": "EC3"}


@pytest.fixture(scope="session", autouse=True)
async def _database():
    await init_db()
    await ensure_users()
    await ensure_election()
    yield


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def login(client):
    """login("EC1") -> Authorization header of that user."""
    cache: dict[str, dict] = {}

    async def _login(username: str) -> dict:
        if username not in cache:
            response = await client.post("/api/auth/login", json={"username": username, "password": PASSWORDS[username]})
            assert response.status_code == 200, response.text
            cache[username] = {"Authorization": f"Bearer {response.json()['access_token']}"}
        return cache[username]

    return _login


@pytest.fixture
async def election(client, login):
    """The seeded 2026 election, emptied of ballots, active and not paused."""
    sa = await login("SA")
    active = (await client.get("/api/dashboard/active")).json()
    response = await client.post("/api/ballots/bulk-delete", headers=sa, json={"election_id": active["id"], "all_matching": True})
    assert response.status_code == 200, response.text
    await client.put(f"/api/admin/counting/{active['id']}/pause?pause=false", headers=sa)
    reset_live_state()
    detail = (await client.get(f"/api/elections/{active['id']}")).json()
    candidates = (await client.get(f"/api/candidates/election/{active['id']}")).json()
    by_voter = {c["voter_no"]: c["id"] for c in candidates}
    return {**detail, "candidates": candidates, "by_voter": by_voter}


@pytest.fixture
def ids(election):
    """ids("13", "30") -> candidate ids of those voter numbers."""
    return lambda *voter_nos: [election["by_voter"][v] for v in voter_nos]
