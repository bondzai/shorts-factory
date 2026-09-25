"""Bulk work from the console: a file or JSON rows, checked by the same
service as the CLI and MCP. A dry run writes nothing; a real run queues."""

import json

import pytest
from fastapi.testclient import TestClient

from factory import db, tasks, web

from test_batch import ch  # noqa: F401  (the Gravity Lab channel with a season)


@pytest.fixture
def client(ch):  # noqa: F811
    web.JOB.name = None
    with TestClient(web.app) as c:
        yield c


def queued():
    with db.connect() as conn:
        return [tasks.as_dict(r) for r in db.tasks(conn, "main", None)]


def batches():
    with db.connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0]


def upload(client, name, text, **form):
    data = {k: str(v).lower() if isinstance(v, bool) else v for k, v in {"channel": "main", **form}.items()}
    return client.post("/api/tasks/import", files={"file": (name, text.encode(), "application/octet-stream")}, data=data)


def test_a_dry_run_import_says_what_would_happen_and_writes_nothing(client):
    r = upload(client, "jobs.csv", "stage,count,ref\nzigzag,2,a\n", dry_run=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] and body["batch_id"] is None and body["accepted"] == 1
    assert body["source"] == "jobs.csv"
    assert queued() == [] and batches() == 0


def test_import_is_a_dry_run_unless_told_otherwise(client):
    body = upload(client, "jobs.csv", "stage\nzigzag\n").json()
    assert body["dry_run"] and queued() == []


def test_a_real_import_queues_every_row(client):
    text = json.dumps({"jobs": [{"stage": "zigzag", "ref": "wk-a"}, {"level": "L01..L02", "ref": "wk"}]})
    body = upload(client, "week.json", text, dry_run=False).json()
    assert body["batch_id"] and body["accepted"] == 3 and body["refused"] == 0
    assert len(queued()) == 3 and batches() == 1


def test_one_bad_row_queues_nothing_unless_partial(client):
    text = "stage,ref\nzigzag,a\nnope,b\n"
    body = upload(client, "jobs.csv", text, dry_run=False).json()
    assert body["batch_id"] is None and body["refused"] == 1 and queued() == []
    body = upload(client, "jobs.csv", text, dry_run=False, partial=True).json()
    assert body["batch_id"] and body["accepted"] == 1 and len(queued()) == 1


def test_a_file_with_an_unknown_extension_is_refused(client):
    r = upload(client, "jobs.txt", "stage\nzigzag\n", dry_run=False)
    assert r.status_code == 400 and ".txt" in r.json()["detail"]
    assert queued() == []


def test_a_malformed_file_is_a_400_not_a_crash(client):
    r = upload(client, "jobs.json", "{not json", dry_run=True)
    assert r.status_code == 400 and "jobs.json" in r.json()["detail"]


def test_json_rows_dry_run_then_queue(client):
    rows = [{"stage": "zigzag", "count": 3}]
    dry = client.post("/api/tasks/batch", json={"channel": "main", "jobs": rows}).json()
    assert dry["dry_run"] and dry["accepted"] == 1 and queued() == []
    real = client.post("/api/tasks/batch", json={"channel": "main", "jobs": rows, "dry_run": False}).json()
    assert real["batch_id"] and len(queued()) == 3


def test_json_rows_refused_say_why(client):
    body = client.post("/api/tasks/batch", json={"channel": "main", "jobs": [{"stage": "nope"}], "dry_run": False}).json()
    assert body["batch_id"] is None and "nope" in body["rows"][0]["reason"]


def test_brains_say_whether_qc_is_on(client):
    assert isinstance(client.get("/api/brains").json()["qc_enabled"], bool)
