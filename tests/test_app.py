"""End-to-end tests for the consent-based location tracer."""


# --------------------------------------------------------------------------- #
# Pages & session creation
# --------------------------------------------------------------------------- #
def test_home_page_loads(client):
    assert client.get("/").status_code == 200


def test_create_session_returns_links(make_session):
    data = make_session()
    assert data["share_url"].endswith("/t/" + data["share_token"])
    assert "key=" in data["dashboard_url"]
    assert data["qr_url"].endswith(f"/t/{data['share_token']}/qr.svg")
    assert data["expires_at"]


def test_empty_label_rejected(client):
    assert client.post("/api/sessions", json={"label": "   "}).status_code == 400


def test_share_page_shows_label(client, make_session):
    data = make_session(label="Dad checking in")
    resp = client.get(f"/t/{data['share_token']}")
    assert resp.status_code == 200
    assert b"Dad checking in" in resp.data


def test_unknown_share_token_404(client):
    assert client.get("/t/nope").status_code == 404


# --------------------------------------------------------------------------- #
# Owner-key authorization
# --------------------------------------------------------------------------- #
def test_dashboard_requires_key(client, make_session):
    data = make_session()
    assert client.get(f"/dashboard/{data['share_token']}").status_code == 403
    assert client.get(f"/dashboard/{data['share_token']}?key=wrong").status_code == 403
    ok = client.get(f"/dashboard/{data['share_token']}?key={data['owner_key']}")
    assert ok.status_code == 200


def test_locations_requires_key(client, make_session):
    data = make_session()
    assert client.get(f"/api/sessions/{data['share_token']}/locations").status_code == 403


# --------------------------------------------------------------------------- #
# Members & the join cap
# --------------------------------------------------------------------------- #
def test_join_returns_member_token(client, make_session, join_member):
    token = make_session()["share_token"]
    r = join_member(token, name="Alex")
    assert r.status_code == 200
    body = r.get_json()
    assert body["member_token"]
    assert body["name"] == "Alex"
    assert body["member_count"] == 1


def test_join_is_idempotent_with_token(client, make_session, join_member):
    token = make_session(max_members=1)["share_token"]
    first = join_member(token, name="Alex").get_json()
    # Re-joining with the same token does not consume another slot.
    again = join_member(token, member_token=first["member_token"]).get_json()
    assert again["member_token"] == first["member_token"]
    assert again["member_count"] == 1


def test_member_cap_enforced(client, make_session, join_member):
    token = make_session(max_members=5)["share_token"]
    for i in range(5):
        assert join_member(token, name=f"P{i}").status_code == 200
    # Sixth distinct device is refused.
    full = join_member(token, name="P6")
    assert full.status_code == 409
    assert "full" in full.get_json()["error"].lower()


def test_blank_name_defaults_to_guest(client, make_session, join_member):
    token = make_session()["share_token"]
    assert join_member(token, name="   ").get_json()["name"] == "Guest"


# --------------------------------------------------------------------------- #
# Pings & retrieval
# --------------------------------------------------------------------------- #
def test_ping_requires_membership(client, make_session):
    token = make_session()["share_token"]
    # No member_token -> rejected.
    r = client.post(f"/api/sessions/{token}/ping", json={"lat": 1, "lng": 1})
    assert r.status_code == 403
    # Bogus member_token -> rejected.
    r = client.post(f"/api/sessions/{token}/ping",
                    json={"member_token": "nope", "lat": 1, "lng": 1})
    assert r.status_code == 403


def test_ping_then_visible_to_owner_per_member(client, make_session, join_member):
    data = make_session()
    token, key = data["share_token"], data["owner_key"]
    mt = join_member(token, name="Alex").get_json()["member_token"]

    body = client.get(f"/api/sessions/{token}/locations?key={key}").get_json()
    assert body["member_count"] == 1
    assert body["members"][0]["latest"] is None  # joined but no fix yet

    r = client.post(f"/api/sessions/{token}/ping",
                    json={"member_token": mt, "lat": 17.385, "lng": 78.4867, "accuracy": 22.5})
    assert r.status_code == 200

    members = client.get(f"/api/sessions/{token}/locations?key={key}").get_json()["members"]
    assert members[0]["name"] == "Alex"
    assert abs(members[0]["latest"]["lat"] - 17.385) < 1e-6
    assert members[0]["trail"][-1] == [17.385, 78.4867]


def test_two_members_tracked_separately(client, make_session, join_member):
    data = make_session(max_members=2)
    token, key = data["share_token"], data["owner_key"]
    a = join_member(token, name="Alex").get_json()["member_token"]
    b = join_member(token, name="Bo").get_json()["member_token"]

    client.post(f"/api/sessions/{token}/ping", json={"member_token": a, "lat": 10, "lng": 10})
    client.post(f"/api/sessions/{token}/ping", json={"member_token": b, "lat": 20, "lng": 20})

    members = client.get(f"/api/sessions/{token}/locations?key={key}").get_json()["members"]
    by_name = {m["name"]: m for m in members}
    assert abs(by_name["Alex"]["latest"]["lat"] - 10) < 1e-6
    assert abs(by_name["Bo"]["latest"]["lat"] - 20) < 1e-6


def test_out_of_range_coords_rejected(client, make_session, join_member):
    token = make_session()["share_token"]
    mt = join_member(token).get_json()["member_token"]
    assert client.post(f"/api/sessions/{token}/ping",
                       json={"member_token": mt, "lat": 999, "lng": 0}).status_code == 400
    assert client.post(f"/api/sessions/{token}/ping",
                       json={"member_token": mt, "lat": 0, "lng": 999}).status_code == 400


def test_missing_coords_rejected(client, make_session, join_member):
    token = make_session()["share_token"]
    mt = join_member(token).get_json()["member_token"]
    assert client.post(f"/api/sessions/{token}/ping",
                       json={"member_token": mt, "accuracy": 5}).status_code == 400


# --------------------------------------------------------------------------- #
# Stop flow
# --------------------------------------------------------------------------- #
def test_stop_blocks_further_pings(client, make_session, join_member):
    data = make_session()
    token, key = data["share_token"], data["owner_key"]
    mt = join_member(token).get_json()["member_token"]
    assert client.post(f"/api/sessions/{token}/stop").status_code == 200
    assert client.post(f"/api/sessions/{token}/ping",
                       json={"member_token": mt, "lat": 1, "lng": 1}).status_code == 409
    assert client.get(f"/api/sessions/{token}/locations?key={key}").get_json()["active"] is False


# --------------------------------------------------------------------------- #
# Expiry
# --------------------------------------------------------------------------- #
def test_expiry_is_clamped(make_session):
    # Below the 5-minute floor gets clamped up (session still valid in future).
    data = make_session(expiry_minutes=1)
    assert data["expires_at"] > "2026"


def test_expired_session_rejects_ping(client, make_session, expire_session):
    data = make_session()
    token, key = data["share_token"], data["owner_key"]
    expire_session(token)

    r = client.post(f"/api/sessions/{token}/ping", json={"lat": 1, "lng": 1})
    assert r.status_code == 409
    assert "expired" in r.get_json()["error"].lower()

    body = client.get(f"/api/sessions/{token}/locations?key={key}").get_json()
    assert body["active"] is False
    assert body["expired"] is True


def test_expired_share_page_shows_notice(client, make_session, expire_session):
    data = make_session()
    expire_session(data["share_token"])
    resp = client.get(f"/t/{data['share_token']}")
    assert b"expired" in resp.data.lower()


# --------------------------------------------------------------------------- #
# QR code
# --------------------------------------------------------------------------- #
def test_qr_returns_svg(client, make_session):
    token = make_session()["share_token"]
    resp = client.get(f"/t/{token}/qr.svg")
    assert resp.status_code == 200
    assert resp.mimetype == "image/svg+xml"
    assert b"<svg" in resp.data


def test_qr_unknown_token_404(client):
    assert client.get("/t/nope/qr.svg").status_code == 404
