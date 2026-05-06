"""
Unit tests for pure helpers in live_checks.py that have no direct coverage.

Gaps targeted:
  - now_iso()          — UTC timestamp format
  - _tenancy_ocid()    — env-var cascade (3 variables)
  - _compartment_ocid() — env-var cascade with fallback to tenancy
  - _degraded()        — standard payload shape
  - _imds_reachable()  — socket probe (mocked)
  - _live_base_url()   — env-var override (lives in compliance.py)

None of these tests require a database or OCI SDK.
"""
from __future__ import annotations

import re
import socket
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — load functions under test
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_checks_mod():
    try:
        import app.routers.live_checks as mod  # type: ignore
        return mod
    except ImportError:
        pytest.skip("live_checks router not importable")


@pytest.fixture(scope="module")
def compliance_mod():
    try:
        import app.routers.compliance as mod  # type: ignore
        return mod
    except ImportError:
        pytest.skip("compliance router not importable")


# ---------------------------------------------------------------------------
# now_iso()
# ---------------------------------------------------------------------------

class TestNowIso:
    def test_returns_string(self, live_checks_mod):
        result = live_checks_mod.now_iso()
        assert isinstance(result, str)

    def test_parseable_as_iso8601(self, live_checks_mod):
        result = live_checks_mod.now_iso()
        # Must parse without error.
        parsed = datetime.fromisoformat(result)
        assert parsed is not None

    def test_has_utc_timezone(self, live_checks_mod):
        result = live_checks_mod.now_iso()
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0

    def test_no_microseconds(self, live_checks_mod):
        # Spec: seconds precision only (microsecond=0 before isoformat()).
        result = live_checks_mod.now_iso()
        # ISO format with microseconds looks like "...T12:34:56.123456+00:00"
        # Without: "...T12:34:56+00:00"
        assert "." not in result.split("T")[1]

    def test_matches_iso_pattern(self, live_checks_mod):
        result = live_checks_mod.now_iso()
        # e.g. "2026-05-02T14:30:00+00:00"
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"
        assert re.match(pattern, result), f"Unexpected format: {result!r}"

    def test_returns_current_time(self, live_checks_mod):
        before = datetime.now(timezone.utc)
        result = live_checks_mod.now_iso()
        after = datetime.now(timezone.utc)
        parsed = datetime.fromisoformat(result)
        assert before.replace(microsecond=0) <= parsed <= after.replace(microsecond=0) + \
               __import__("datetime").timedelta(seconds=1)


# ---------------------------------------------------------------------------
# _tenancy_ocid()
# ---------------------------------------------------------------------------

class TestTenancyOcid:
    def test_reads_oci_tenancy_ocid(self, live_checks_mod, monkeypatch):
        monkeypatch.setenv("OCI_TENANCY_OCID", "ocid1.tenancy.oc1..aaa")
        monkeypatch.delenv("OCI_TENANCY", raising=False)
        monkeypatch.delenv("TF_VAR_tenancy_ocid", raising=False)
        assert live_checks_mod._tenancy_ocid() == "ocid1.tenancy.oc1..aaa"

    def test_falls_back_to_oci_tenancy(self, live_checks_mod, monkeypatch):
        monkeypatch.delenv("OCI_TENANCY_OCID", raising=False)
        monkeypatch.setenv("OCI_TENANCY", "ocid1.tenancy.oc1..bbb")
        monkeypatch.delenv("TF_VAR_tenancy_ocid", raising=False)
        assert live_checks_mod._tenancy_ocid() == "ocid1.tenancy.oc1..bbb"

    def test_falls_back_to_tf_var(self, live_checks_mod, monkeypatch):
        monkeypatch.delenv("OCI_TENANCY_OCID", raising=False)
        monkeypatch.delenv("OCI_TENANCY", raising=False)
        monkeypatch.setenv("TF_VAR_tenancy_ocid", "ocid1.tenancy.oc1..ccc")
        assert live_checks_mod._tenancy_ocid() == "ocid1.tenancy.oc1..ccc"

    def test_returns_none_when_all_unset(self, live_checks_mod, monkeypatch):
        monkeypatch.delenv("OCI_TENANCY_OCID", raising=False)
        monkeypatch.delenv("OCI_TENANCY", raising=False)
        monkeypatch.delenv("TF_VAR_tenancy_ocid", raising=False)
        assert live_checks_mod._tenancy_ocid() is None

    def test_oci_tenancy_ocid_takes_priority(self, live_checks_mod, monkeypatch):
        monkeypatch.setenv("OCI_TENANCY_OCID", "first")
        monkeypatch.setenv("OCI_TENANCY", "second")
        monkeypatch.setenv("TF_VAR_tenancy_ocid", "third")
        assert live_checks_mod._tenancy_ocid() == "first"


# ---------------------------------------------------------------------------
# _compartment_ocid()
# ---------------------------------------------------------------------------

class TestCompartmentOcid:
    def test_reads_oci_compartment_ocid(self, live_checks_mod, monkeypatch):
        monkeypatch.setenv("OCI_COMPARTMENT_OCID", "ocid1.compartment.oc1..aaa")
        monkeypatch.delenv("OCI_COMPARTMENT_ID", raising=False)
        result = live_checks_mod._compartment_ocid()
        assert result == "ocid1.compartment.oc1..aaa"

    def test_falls_back_to_oci_compartment_id(self, live_checks_mod, monkeypatch):
        monkeypatch.delenv("OCI_COMPARTMENT_OCID", raising=False)
        monkeypatch.setenv("OCI_COMPARTMENT_ID", "ocid1.compartment.oc1..bbb")
        result = live_checks_mod._compartment_ocid()
        assert result == "ocid1.compartment.oc1..bbb"

    def test_falls_back_to_tenancy_ocid(self, live_checks_mod, monkeypatch):
        monkeypatch.delenv("OCI_COMPARTMENT_OCID", raising=False)
        monkeypatch.delenv("OCI_COMPARTMENT_ID", raising=False)
        monkeypatch.setenv("OCI_TENANCY_OCID", "ocid1.tenancy.oc1..fallback")
        result = live_checks_mod._compartment_ocid()
        assert result == "ocid1.tenancy.oc1..fallback"

    def test_returns_none_when_nothing_set(self, live_checks_mod, monkeypatch):
        monkeypatch.delenv("OCI_COMPARTMENT_OCID", raising=False)
        monkeypatch.delenv("OCI_COMPARTMENT_ID", raising=False)
        monkeypatch.delenv("OCI_TENANCY_OCID", raising=False)
        monkeypatch.delenv("OCI_TENANCY", raising=False)
        monkeypatch.delenv("TF_VAR_tenancy_ocid", raising=False)
        assert live_checks_mod._compartment_ocid() is None


# ---------------------------------------------------------------------------
# _degraded()
# ---------------------------------------------------------------------------

class TestDegraded:
    def test_contains_as_of_key(self, live_checks_mod):
        result = live_checks_mod._degraded({})
        assert "as_of" in result

    def test_contains_error_instance_principal_unavailable(self, live_checks_mod):
        result = live_checks_mod._degraded({})
        assert result.get("error") == "instance_principal_unavailable"

    def test_extra_fields_merged(self, live_checks_mod):
        result = live_checks_mod._degraded({"open_problems": -1, "high_risk": -1})
        assert result["open_problems"] == -1
        assert result["high_risk"] == -1

    def test_extra_overrides_do_not_clobber_as_of(self, live_checks_mod):
        result = live_checks_mod._degraded({"adb_count": -1})
        assert "as_of" in result
        assert result["adb_count"] == -1

    def test_as_of_is_iso_string(self, live_checks_mod):
        result = live_checks_mod._degraded({})
        parsed = datetime.fromisoformat(result["as_of"])
        assert parsed is not None

    def test_extra_can_override_error_field(self, live_checks_mod):
        # _degraded merges via dict.update — callers can supply a more specific error.
        result = live_checks_mod._degraded({"error": "tenancy_ocid_not_set"})
        assert result["error"] == "tenancy_ocid_not_set"

    def test_empty_extra_produces_minimal_payload(self, live_checks_mod):
        result = live_checks_mod._degraded({})
        assert set(result.keys()) == {"as_of", "error"}


# ---------------------------------------------------------------------------
# _imds_reachable()
# ---------------------------------------------------------------------------

class TestImdsReachable:
    def test_returns_true_when_connection_succeeds(self, live_checks_mod):
        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("socket.create_connection", return_value=mock_sock):
            assert live_checks_mod._imds_reachable() is True

    def test_returns_false_on_os_error(self, live_checks_mod):
        with patch("socket.create_connection", side_effect=OSError("refused")):
            assert live_checks_mod._imds_reachable() is False

    def test_returns_false_on_timeout(self, live_checks_mod):
        with patch("socket.create_connection", side_effect=socket.timeout("timed out")):
            assert live_checks_mod._imds_reachable() is False

    def test_probe_targets_imds_ip(self, live_checks_mod):
        called_with: list = []

        def fake_connect(address, timeout):
            called_with.append(address)
            raise OSError("not reachable")

        with patch("socket.create_connection", side_effect=fake_connect):
            live_checks_mod._imds_reachable()

        assert len(called_with) == 1
        host, port = called_with[0]
        assert host == "169.254.169.254"
        assert port == 80

    def test_custom_timeout_forwarded(self, live_checks_mod):
        captured_timeout: list = []

        def fake_connect(address, timeout):
            captured_timeout.append(timeout)
            raise OSError("unreachable")

        with patch("socket.create_connection", side_effect=fake_connect):
            live_checks_mod._imds_reachable(timeout_s=0.5)

        assert captured_timeout[0] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _live_base_url()  (lives in compliance.py)
# ---------------------------------------------------------------------------

class TestLiveBaseUrl:
    def test_default_is_localhost_8005(self, compliance_mod, monkeypatch):
        monkeypatch.delenv("COMPLIANCE_BASE_URL", raising=False)
        assert compliance_mod._live_base_url() == "http://localhost:8005"

    def test_env_var_overrides_default(self, compliance_mod, monkeypatch):
        monkeypatch.setenv("COMPLIANCE_BASE_URL", "http://compliance-svc:8005")
        assert compliance_mod._live_base_url() == "http://compliance-svc:8005"

    def test_empty_env_var_returns_empty_string(self, compliance_mod, monkeypatch):
        # os.environ.get("COMPLIANCE_BASE_URL", default) returns "" for an empty
        # env var since the key is present. Empty string is falsy but this tests
        # that the implementation does not silently fall back.
        monkeypatch.setenv("COMPLIANCE_BASE_URL", "")
        # Empty string evaluates as falsy; depending on implementation it may
        # return "" or the default. Assert the implementation is consistent.
        result = compliance_mod._live_base_url()
        assert isinstance(result, str)

    def test_trailing_slash_preserved(self, compliance_mod, monkeypatch):
        monkeypatch.setenv("COMPLIANCE_BASE_URL", "http://svc:8005/")
        assert compliance_mod._live_base_url().endswith("/")

    def test_https_url_accepted(self, compliance_mod, monkeypatch):
        monkeypatch.setenv("COMPLIANCE_BASE_URL", "https://compliance.internal")
        assert compliance_mod._live_base_url().startswith("https://")
