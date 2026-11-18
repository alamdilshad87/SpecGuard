def _project_with_versions(client, spec_v1, spec_v2):
    project = client.post("/projects", json={"name": "Bookstore"}).json()
    v1 = client.post(f"/projects/{project['id']}/versions", json={"label": "v1", "content": spec_v1}).json()
    v2 = client.post(
        f"/projects/{project['id']}/versions/upload",
        data={"label": "v2"},
        files={"file": ("bookstore-v2.yaml", spec_v2.encode(), "application/yaml")},
    ).json()
    return project, v1, v2


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_project_and_version_flow(client, spec_v1, spec_v2):
    project, v1, v2 = _project_with_versions(client, spec_v1, spec_v2)
    assert v1["operation_count"] == 4 and v2["operation_count"] == 4

    detail = client.get(f"/projects/{project['id']}").json()
    assert [v["label"] for v in detail["versions"]] == ["v1", "v2"]

    version = client.get(f"/versions/{v1['id']}").json()
    assert version["servers"] == ["http://localhost:9000"]
    assert {o["key"] for o in version["operations"]} >= {"GET /books", "POST /books"}


def test_docs_tests_and_diff_endpoints(client, spec_v1, spec_v2):
    _, v1, v2 = _project_with_versions(client, spec_v1, spec_v2)

    docs = client.get(f"/versions/{v1['id']}/docs").json()
    assert docs["content"].startswith("# Bookstore API")

    tests = client.get(f"/versions/{v1['id']}/tests").json()
    assert len(tests) > 10

    diff = client.get("/diff", params={"from": v1["id"], "to": v2["id"]}).json()
    assert diff["is_breaking"] is True
    assert diff["from_label"] == "v1" and diff["to_label"] == "v2"


def test_stateless_diff(client, spec_v1, spec_v2):
    response = client.post("/analyze/diff", json={"old": spec_v1, "new": spec_v2})
    assert response.status_code == 200
    assert response.json()["summary"]["breaking"] > 0


def test_validation_errors(client, spec_v1):
    project = client.post("/projects", json={"name": "Dupes"}).json()
    assert client.post("/projects", json={"name": "Dupes"}).status_code == 409

    bad = client.post(f"/projects/{project['id']}/versions", json={"label": "x", "content": "swagger: '2.0'"})
    assert bad.status_code == 422

    client.post(f"/projects/{project['id']}/versions", json={"label": "v1", "content": spec_v1})
    dup = client.post(f"/projects/{project['id']}/versions", json={"label": "v1", "content": spec_v1})
    assert dup.status_code == 409

    assert client.get("/versions/9999").status_code == 404
