"""
Unit tests for pure helpers in app/routers/upload.py.

Gaps covered (none of these had tests before):
  - _chunk_text()         — empty input, single token, exact-chunk-size, overlap,
                            multi-chunk, whitespace-only, very-large-input
  - _to_oracle_vector()   — type, length, element values
  - OLS_LEVELS mapping    — all canonical keys present, legacy alias alignment
  - DB_CLASSIFICATION_CODE — keys cover OLS_LEVELS, short-code round-trips
  - upload_document()     — invalid classification (400), unsupported content-type (415),
                            oversized file (413), non-UTF-8 bytes (400),
                            empty document (400), happy path (200 shape),
                            DB exception → 500, tenant fallback
"""
from __future__ import annotations

import array
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Module-level fixture — import pure helpers once
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def upload_mod():
    try:
        from app.routers import upload as mod  # type: ignore
        return mod
    except ImportError:
        pytest.skip("doc-intelligence app.routers.upload not importable")


# ---------------------------------------------------------------------------
# _chunk_text()
# ---------------------------------------------------------------------------

class TestChunkText:
    @pytest.fixture(autouse=True)
    def _load(self, upload_mod):
        self.fn = upload_mod._chunk_text

    def test_empty_string_returns_empty_list(self):
        assert self.fn("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert self.fn("   \t\n  ") == []

    def test_single_token_returns_one_chunk(self):
        assert self.fn("hello") == ["hello"]

    def test_fewer_tokens_than_chunk_size_returns_one_chunk(self):
        text = " ".join(["word"] * 10)
        result = self.fn(text, chunk_tokens=500, overlap=50)
        assert len(result) == 1

    def test_chunk_contains_correct_token_count(self):
        # 10 tokens, chunk_tokens=5, overlap=1 → step=4
        # chunks: [0..5), [4..9), [8..10)
        tokens = [str(i) for i in range(10)]
        text = " ".join(tokens)
        result = self.fn(text, chunk_tokens=5, overlap=1)
        # First chunk must have 5 tokens.
        assert len(result[0].split()) == 5

    def test_overlap_shares_tokens_between_chunks(self):
        tokens = [str(i) for i in range(20)]
        text = " ".join(tokens)
        result = self.fn(text, chunk_tokens=10, overlap=3)
        # Last tokens of chunk n must appear at start of chunk n+1.
        if len(result) >= 2:
            tail_tokens = result[0].split()[-3:]
            head_tokens = result[1].split()[:3]
            assert tail_tokens == head_tokens

    def test_no_duplicate_last_chunk(self):
        # If the last window aligns exactly, must not produce a duplicate.
        tokens = [str(i) for i in range(6)]
        text = " ".join(tokens)
        result = self.fn(text, chunk_tokens=3, overlap=0)
        assert len(result) == 2
        assert result[0] != result[1]

    def test_large_text_produces_multiple_chunks(self):
        text = " ".join(["word"] * 1200)
        result = self.fn(text, chunk_tokens=500, overlap=50)
        assert len(result) >= 2

    def test_all_tokens_appear_in_chunks(self):
        tokens = [str(i) for i in range(30)]
        text = " ".join(tokens)
        result = self.fn(text, chunk_tokens=10, overlap=0)
        all_text = " ".join(result)
        for t in tokens:
            assert t in all_text


# ---------------------------------------------------------------------------
# _to_oracle_vector()
# ---------------------------------------------------------------------------

class TestToOracleVector:
    @pytest.fixture(autouse=True)
    def _load(self, upload_mod):
        self.fn = upload_mod._to_oracle_vector

    def test_returns_array_type(self):
        result = self.fn([1.0, 2.0, 3.0])
        assert isinstance(result, array.ArrayType)

    def test_typecode_is_float(self):
        result = self.fn([0.0])
        assert result.typecode == "f"

    def test_values_preserved(self):
        vec = [0.1, 0.2, 0.3]
        result = self.fn(vec)
        assert len(result) == 3
        for original, stored in zip(vec, result):
            assert abs(original - stored) < 1e-5

    def test_empty_input_returns_empty_array(self):
        result = self.fn([])
        assert len(result) == 0

    def test_1024_dim_length(self):
        vec = [0.0] * 1024
        result = self.fn(vec)
        assert len(result) == 1024


# ---------------------------------------------------------------------------
# OLS_LEVELS and DB_CLASSIFICATION_CODE dictionaries
# ---------------------------------------------------------------------------

class TestOlsMappings:
    def test_ols_levels_has_all_canonical_keys(self, upload_mod):
        required = {"OFFEN", "INTERN", "NFD", "GEHEIM"}
        assert required.issubset(upload_mod.OLS_LEVELS)

    def test_ols_levels_legacy_aliases_match_canonical(self, upload_mod):
        m = upload_mod.OLS_LEVELS
        assert m["U"] == m["OFFEN"]
        assert m["R"] == m["INTERN"]
        assert m["C"] == m["NFD"]
        assert m["S"] == m["GEHEIM"]

    def test_vs_nfd_alias_maps_to_nfd(self, upload_mod):
        assert upload_mod.OLS_LEVELS["VS-NFD"] == upload_mod.OLS_LEVELS["NFD"]

    def test_db_classification_code_covers_all_ols_keys(self, upload_mod):
        for key in upload_mod.OLS_LEVELS:
            assert key in upload_mod.DB_CLASSIFICATION_CODE, f"Missing DB code for {key}"

    def test_db_classification_code_geheim_maps_to_s(self, upload_mod):
        assert upload_mod.DB_CLASSIFICATION_CODE["GEHEIM"] == "S"

    def test_db_classification_code_nfd_maps_to_vs_nfd(self, upload_mod):
        assert upload_mod.DB_CLASSIFICATION_CODE["NFD"] == "VS-NFD"


# ---------------------------------------------------------------------------
# upload_document() endpoint tests — via FastAPI TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def _stub_embed(monkeypatch):
    """Replace ml.embed with a zero-vector stub — no model loading."""
    try:
        from app.routers import upload as mod  # type: ignore
        monkeypatch.setattr(mod, "embed", lambda text: [0.0] * 1024)
    except ImportError:
        pytest.skip("upload mod not importable")


@pytest.fixture
def _stub_db(monkeypatch):
    """Stub get_conn and set_tenant_identifier so no Oracle pool is needed."""
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    doc_id_var = MagicMock()
    doc_id_var.getvalue.return_value = ["DOC-001"]
    chunk_id_var = MagicMock()
    chunk_id_var.getvalue.return_value = ["CHUNK-001"]
    cursor.bindvars = {"doc_id": doc_id_var, "chunk_id": chunk_id_var}

    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.commit.return_value = None
    conn.rollback.return_value = None

    try:
        from app import db as db_mod  # type: ignore
        monkeypatch.setattr(db_mod, "set_tenant_identifier", lambda c, t: None)
        monkeypatch.setattr(db_mod, "tenant_from_header", lambda h: h or "T001")

        def _override():
            yield conn

        return conn, _override
    except ImportError:
        pytest.skip("app.db not importable")


@pytest.fixture
def upload_client(_stub_embed, _stub_db, app_module):
    from fastapi.testclient import TestClient
    from app.db import get_conn  # type: ignore

    _, override = _stub_db
    app_module.app.dependency_overrides[get_conn] = override
    with TestClient(app_module.app) as c:
        yield c
    app_module.app.dependency_overrides.clear()


class TestUploadEndpointValidation:
    """Validate HTTP-level error responses — no DB needed for most."""

    def _post(self, client, content: bytes, filename: str = "doc.txt",
              content_type: str = "text/plain", classification: str = "INTERN",
              title: str = "Test Doc") -> Any:
        return client.post(
            "/upload",
            data={"title": title, "classification": classification},
            files={"file": (filename, content, content_type)},
        )

    def test_invalid_classification_returns_400(self, upload_client):
        resp = self._post(upload_client, b"hello world", classification="TOP_SECRET")
        assert resp.status_code == 400
        assert "classification" in resp.json()["detail"].lower()

    def test_unsupported_content_type_returns_415(self, upload_client):
        resp = self._post(upload_client, b"%PDF-1.4", content_type="application/pdf")
        assert resp.status_code == 415

    def test_empty_file_returns_400(self, upload_client):
        resp = self._post(upload_client, b"")
        assert resp.status_code == 400

    def test_whitespace_only_file_returns_400(self, upload_client):
        resp = self._post(upload_client, b"   \n\t  ")
        assert resp.status_code == 400

    def test_non_utf8_bytes_returns_400(self, upload_client):
        resp = self._post(upload_client, b"\xff\xfe invalid")
        assert resp.status_code == 400
        assert "utf-8" in resp.json()["detail"].lower()

    def test_oversized_file_returns_413(self, upload_client):
        big = b"word " * (1024 * 1024 + 1)  # > 5 MB
        resp = self._post(upload_client, big)
        assert resp.status_code == 413

    def test_classification_case_insensitive(self, upload_client):
        resp = self._post(upload_client, b"Some document content here", classification="intern")
        # Should normalise to INTERN and succeed (200) or at least not 400 from classification check.
        assert resp.status_code != 400 or "classification" not in resp.json().get("detail", "")

    def test_missing_title_returns_422(self, upload_client):
        resp = upload_client.post(
            "/upload",
            data={"classification": "INTERN"},
            files={"file": ("doc.txt", b"hello world", "text/plain")},
        )
        assert resp.status_code == 422


class TestUploadEndpointHappyPath:
    def test_successful_upload_returns_expected_keys(self, upload_client):
        resp = upload_client.post(
            "/upload",
            data={"title": "Doktrin Alpha", "classification": "NFD"},
            files={"file": ("alpha.txt", b"Dies ist ein Testdokument mit genuegend Inhalt.", "text/plain")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "doc_id" in body
        assert "chunk_count" in body
        assert body["chunk_count"] >= 1
        assert "ols_label" in body

    def test_ols_label_matches_classification(self, upload_client):
        resp = upload_client.post(
            "/upload",
            data={"title": "Geheim Dok", "classification": "GEHEIM"},
            files={"file": ("g.txt", b"Geheimes Dokument.", "text/plain")},
        )
        assert resp.status_code == 200
        assert resp.json()["ols_label"] == 70  # GEHEIM → 70

    def test_tenant_id_header_accepted(self, upload_client):
        resp = upload_client.post(
            "/upload",
            headers={"X-Tenant-Id": "TENANT_GOV_PRIMARY"},
            data={"title": "Tenant Doc", "classification": "INTERN"},
            files={"file": ("t.txt", b"Tenant-spezifisches Dokument.", "text/plain")},
        )
        assert resp.status_code == 200

    def test_json_content_type_accepted(self, upload_client):
        resp = upload_client.post(
            "/upload",
            data={"title": "JSON Doc"},
            files={"file": ("data.json", b'{"key": "value"}', "application/json")},
        )
        assert resp.status_code == 200

    def test_octet_stream_accepted(self, upload_client):
        resp = upload_client.post(
            "/upload",
            data={"title": "Octet Doc"},
            files={"file": ("readme.md", b"# Title\n\nContent.", "application/octet-stream")},
        )
        assert resp.status_code == 200


class TestUploadEndpointDbFailure:
    def test_db_exception_returns_500(self, _stub_embed, app_module, monkeypatch):
        from fastapi.testclient import TestClient
        from app.db import get_conn  # type: ignore

        broken_conn = MagicMock()
        broken_conn.cursor.side_effect = RuntimeError("DB unavailable")
        broken_conn.rollback.return_value = None

        def _override():
            yield broken_conn

        try:
            from app import db as db_mod  # type: ignore
            monkeypatch.setattr(db_mod, "set_tenant_identifier", lambda c, t: None)
            monkeypatch.setattr(db_mod, "tenant_from_header", lambda h: h or "T001")
        except ImportError:
            pytest.skip("app.db not importable")

        app_module.app.dependency_overrides[get_conn] = _override
        with TestClient(app_module.app) as client:
            resp = client.post(
                "/upload",
                data={"title": "Broken"},
                files={"file": ("b.txt", b"some content here for chunking", "text/plain")},
            )
        app_module.app.dependency_overrides.clear()
        assert resp.status_code == 500
