"""REST API endpoints, end-to-end through the FastAPI TestClient.

Enqueue endpoints persist jobs to the (isolated) DB; the worker subprocess is
never started, so nothing is actually printed. The printer/status path runs
against the fake connection.
"""

import io
import uuid

import pytest
from PIL import Image

from labeljetty.config import AuthToken, Config
from labeljetty.core.db import PrintJob, get_session
from labeljetty.web import api as api_mod
from labeljetty.web import auth as auth_mod
from sqlmodel import select


# --------------------------------------------------------------------------- #
#  Enqueue (parameter jobs)
# --------------------------------------------------------------------------- #
def test_print_text_enqueues(client, worker_running):
    resp = client.post("/api/print/text", json={"text": "Hello", "copies": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_type"] == "text"
    assert body["params"]["text"] == "Hello"
    assert body["copies"] == 2


@pytest.mark.parametrize(
    "endpoint,payload,job_type",
    [
        ("/api/print/markdown", {"text": "# Hi"}, "markdown"),
        ("/api/print/barcode", {"data": "12345678"}, "barcode"),
        ("/api/print/qrcode", {"data": "https://x"}, "qrcode"),
    ],
)
def test_print_param_endpoints(client, worker_running, endpoint, payload, job_type):
    resp = client.post(endpoint, json=payload)
    assert resp.status_code == 200
    assert resp.json()["job_type"] == job_type


def test_print_requires_running_worker(client):
    # No worker_running fixture → service reports not_started → 503.
    resp = client.post("/api/print/text", json={"text": "x"})
    assert resp.status_code == 503


# --------------------------------------------------------------------------- #
#  Enqueue (file jobs)
# --------------------------------------------------------------------------- #
def test_print_png_upload(client, worker_running):
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, "PNG")
    buf.seek(0)
    resp = client.post(
        "/api/print/png",
        files={"file": ("label.png", buf, "image/png")},
        data={"fit": "fit", "copies": "1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_type"] == "png"
    assert body["input_file_name"].endswith(".png")


def test_print_pdf_upload(client, worker_running):
    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buf, "PDF")
    buf.seek(0)
    resp = client.post(
        "/api/print/pdf",
        files={"file": ("doc.pdf", buf, "application/pdf")},
        data={"page": "0"},
    )
    assert resp.status_code == 200
    assert resp.json()["job_type"] == "pdf"


# --------------------------------------------------------------------------- #
#  Jobs
# --------------------------------------------------------------------------- #
def test_list_jobs(client, worker_running):
    client.post("/api/print/text", json={"text": "a"})
    client.post("/api/print/text", json={"text": "b"})
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_job_by_id(client, worker_running):
    job_id = client.post("/api/print/text", json={"text": "a"}).json()["id"]
    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["job"]["id"] == job_id
    assert resp.json()["status"] == "queued"


def test_get_job_404(client):
    resp = client.get(f"/api/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
#  Status endpoints
# --------------------------------------------------------------------------- #
def test_worker_status(client):
    resp = client.get("/api/worker/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_started"


def test_printer_status_reachable(client, patch_printer_connection):
    resp = client.get("/api/printer/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is True
    assert body["status_supported"] is True
    assert body["status"]["ready"] is True


def test_printer_status_unreachable(client):
    # No fake connection patched → real USB lookup for vid:0000 fails → 503.
    resp = client.get("/api/printer/status")
    assert resp.status_code == 503


# --------------------------------------------------------------------------- #
#  Homebox push label-service endpoint
# --------------------------------------------------------------------------- #
def test_homebox_label_disabled_404(client, monkeypatch):
    monkeypatch.setattr(api_mod.config, "HOMEBOX_ENABLED", False)
    resp = client.get("/api/homebox/label", params={"TitleText": "X"})
    assert resp.status_code == 404


def test_homebox_label_returns_png_and_autoprints(client, worker_running, monkeypatch):
    monkeypatch.setattr(api_mod.config, "HOMEBOX_ENABLED", True)
    monkeypatch.setattr(api_mod.config, "HOMEBOX_LABEL_SERVICE_AUTOPRINT", True)
    resp = client.get(
        "/api/homebox/label",
        params={"TitleText": "Widget", "URL": "https://box/item/1"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
    # Autoprint enqueued exactly one qrcode job.
    with get_session() as s:
        jobs = s.exec(select(PrintJob)).all()
    assert len(jobs) == 1
    assert jobs[0].job_type == "qrcode"


# --------------------------------------------------------------------------- #
#  Auth enforcement (protected mode)
# --------------------------------------------------------------------------- #
@pytest.fixture
def protected(monkeypatch):
    cfg = Config(
        _env_file=None,
        PRINTER_USB="vid:0000:pid:0000",
        AUTH_MODE="protected",
        AUTH_TOKENS=[AuthToken(name="ci", token="s3cr3t")],
    )
    monkeypatch.setattr(auth_mod, "config", cfg)
    return cfg


def test_protected_api_rejects_without_token(client, protected):
    assert client.get("/api/jobs").status_code == 401


def test_protected_api_accepts_token(client, protected):
    resp = client.get("/api/jobs", headers={"Authorization": "Bearer s3cr3t"})
    assert resp.status_code == 200
