"""End-to-end tests for `GET /diagrams/{id}/export`.

Covers all four formats plus the 404 path. The fixtures register a user,
build a small system_landscape diagram (User → API → DB), and exercise the
endpoint without exercising team-ACL — workspace-scoped diagrams visible
to their owner is the common case.
"""
import uuid


async def _register(client, tag: str = "exp"):
    email = f"{tag}-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": tag.title(), "password": "s3cret-pw!"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _workspace_id(client, token: str) -> str:
    r = await client.get(
        "/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


async def _build_landscape(client, auth: dict, ws_id: str) -> dict:
    """Create one diagram with three objects + two connections.

    Returns dict with diagram_id and the three object UUIDs keyed by name.
    """
    r = await client.post(
        "/api/v1/diagrams",
        json={"name": "Auth landscape", "type": "system_landscape"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    diagram_id = r.json()["id"]

    objects: dict[str, str] = {}
    for name, type_ in [("User", "actor"), ("API", "system"), ("DB", "store")]:
        r = await client.post(
            "/api/v1/objects",
            json={"name": name, "type": type_},
            headers=auth,
        )
        assert r.status_code == 201, r.text
        obj_id = r.json()["id"]
        objects[name] = obj_id
        await client.post(
            f"/api/v1/diagrams/{diagram_id}/objects",
            json={"object_id": obj_id, "position_x": 0, "position_y": 0},
            headers=auth,
        )

    # Connections: User → API (uses), API → DB (reads/writes)
    for src, tgt, label in [
        ("User", "API", "Logs in"),
        ("API", "DB", "Reads/writes"),
    ]:
        r = await client.post(
            "/api/v1/connections",
            json={
                "source_id": objects[src],
                "target_id": objects[tgt],
                "label": label,
            },
            headers=auth,
        )
        assert r.status_code == 201, r.text

    return {"diagram_id": diagram_id, "objects": objects}


async def test_export_mermaid(client):
    token = await _register(client, "mermaid")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    fixture = await _build_landscape(client, auth, ws_id)

    r = await client.get(
        f"/api/v1/diagrams/{fixture['diagram_id']}/export?format=mermaid",
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.text
    assert body.startswith("%% Exported from ArchFlow")
    assert "C4Context" in body
    assert 'Person(' in body and '"User"' in body
    assert 'System(' in body and '"API"' in body
    # On a system_landscape view STORE collapses to SystemDb (not ContainerDb,
    # which is only legal under C4Container).
    assert 'SystemDb(' in body and '"DB"' in body
    assert 'ContainerDb(' not in body
    assert 'Rel(' in body
    assert '"Logs in"' in body
    assert '"Reads/writes"' in body


async def test_export_plantuml(client):
    token = await _register(client, "puml")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    fixture = await _build_landscape(client, auth, ws_id)

    r = await client.get(
        f"/api/v1/diagrams/{fixture['diagram_id']}/export?format=plantuml",
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.text
    assert body.startswith("@startuml")
    assert body.rstrip().endswith("@enduml")
    assert "!include" in body and "C4-PlantUML" in body
    assert 'Person(' in body and '"User"' in body
    assert 'Rel(' in body and '"Logs in"' in body


async def test_export_structurizr(client):
    token = await _register(client, "stz")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    fixture = await _build_landscape(client, auth, ws_id)

    r = await client.get(
        f"/api/v1/diagrams/{fixture['diagram_id']}/export?format=structurizr",
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.text
    assert "workspace " in body and "model {" in body
    assert 'person "User"' in body
    assert 'softwareSystem "API"' in body
    assert 'container "DB"' in body
    assert '-> ' in body and '"Logs in"' in body


async def test_export_structurizr_round_trip(client):
    """Exporter output must parse cleanly through the importer."""
    from app.services.structurizr_service import parse

    token = await _register(client, "stz-rt")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    fixture = await _build_landscape(client, auth, ws_id)

    r = await client.get(
        f"/api/v1/diagrams/{fixture['diagram_id']}/export?format=structurizr",
        headers=auth,
    )
    objs, rels = parse(r.text)
    assert len(objs) == 3
    assert len(rels) == 2
    names = sorted(o["name"] for o in objs)
    assert names == ["API", "DB", "User"]


async def test_export_json(client):
    token = await _register(client, "expjson")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    fixture = await _build_landscape(client, auth, ws_id)

    r = await client.get(
        f"/api/v1/diagrams/{fixture['diagram_id']}/export?format=json",
        headers=auth,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["version"] == "1.0"
    assert data["diagram"]["id"] == fixture["diagram_id"]
    assert data["diagram"]["type"] == "system_landscape"
    assert len(data["objects"]) == 3
    assert len(data["connections"]) == 2
    # placement coords are merged onto each object row
    assert "position_x" in data["objects"][0]


async def test_export_default_format_is_mermaid(client):
    token = await _register(client, "expdef")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    fixture = await _build_landscape(client, auth, ws_id)

    r = await client.get(
        f"/api/v1/diagrams/{fixture['diagram_id']}/export", headers=auth
    )
    assert r.status_code == 200
    assert "C4Context" in r.text


async def test_export_unknown_diagram_returns_404(client):
    token = await _register(client, "exp404")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.get(
        f"/api/v1/diagrams/{uuid.uuid4()}/export", headers=auth
    )
    assert r.status_code == 404


async def test_export_anonymous_caller_blocked_on_workspace_diagram(client):
    """Codex H1: an unauthenticated caller must not be able to export a
    workspace-scoped diagram by guessing its UUID."""
    token = await _register(client, "anon")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    fixture = await _build_landscape(client, auth, ws_id)

    # Same URL, no Authorization header.
    r = await client.get(
        f"/api/v1/diagrams/{fixture['diagram_id']}/export?format=mermaid"
    )
    assert r.status_code == 401, r.text


async def test_export_non_member_blocked(client):
    """Codex H1: an authenticated user who isn't a member of the diagram's
    workspace must get 403, not the diagram contents."""
    owner_token = await _register(client, "owner")
    owner_ws = await _workspace_id(client, owner_token)
    owner_auth = {
        "Authorization": f"Bearer {owner_token}",
        "X-Workspace-ID": owner_ws,
    }
    fixture = await _build_landscape(client, owner_auth, owner_ws)

    # Second user — has their own workspace, no membership in `owner_ws`.
    outsider_token = await _register(client, "outsider")
    outsider_ws = await _workspace_id(client, outsider_token)
    outsider_auth = {
        "Authorization": f"Bearer {outsider_token}",
        "X-Workspace-ID": outsider_ws,
    }

    r = await client.get(
        f"/api/v1/diagrams/{fixture['diagram_id']}/export?format=mermaid",
        headers=outsider_auth,
    )
    assert r.status_code == 403, r.text


async def test_export_empty_diagram(client):
    """A diagram with zero placements still emits a valid header + body."""
    token = await _register(client, "expempty")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.post(
        "/api/v1/diagrams",
        json={"name": "Empty", "type": "container"},
        headers=auth,
    )
    diagram_id = r.json()["id"]

    r = await client.get(
        f"/api/v1/diagrams/{diagram_id}/export?format=mermaid", headers=auth
    )
    assert r.status_code == 200
    assert "C4Container" in r.text
    assert "objects: 0; connections: 0" in r.text


async def test_export_live_diagram_excludes_draft_connections(client):
    """Codex M1: a draft-scoped Connection that wires two live objects must
    not appear in the live diagram's export. Without the fix in
    diagram_service.get_diagram_payload, the connection set is built only
    from object IDs and ignores Connection.draft_id, leaking unmerged work
    into the live model."""
    token = await _register(client, "draftleak")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    fixture = await _build_landscape(client, auth, ws_id)

    # Fork the diagram so we have a real draft id to scope the rogue connection
    # to (Connection.draft_id has an FK on drafts.id).
    r = await client.post(
        f"/api/v1/drafts/from-diagram/{fixture['diagram_id']}",
        json={"name": "leak-feature"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    draft_id = r.json()["id"]

    # Wire a draft-scoped connection between two LIVE objects on this diagram.
    r = await client.post(
        f"/api/v1/connections?draft_id={draft_id}",
        json={
            "source_id": fixture["objects"]["User"],
            "target_id": fixture["objects"]["DB"],
            "label": "DRAFT-ONLY-LEAK",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text

    r = await client.get(
        f"/api/v1/diagrams/{fixture['diagram_id']}/export?format=mermaid",
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert "DRAFT-ONLY-LEAK" not in r.text, (
        "Draft-scoped connection leaked into live export"
    )

    # The same caller exporting as JSON sees connection counts that exclude
    # the draft-scoped row.
    r = await client.get(
        f"/api/v1/diagrams/{fixture['diagram_id']}/export?format=json",
        headers=auth,
    )
    assert r.status_code == 200
    assert len(r.json()["connections"]) == 2
