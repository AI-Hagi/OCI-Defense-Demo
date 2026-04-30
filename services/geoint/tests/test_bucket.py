"""
Unit tests for app.bucket — the OCI Object Storage upload helper.

Mock-only: no oci SDK is installed in CI, so we monkey-patch sys.modules
with a fake oci.* tree before importing the helper.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


def _install_fake_oci(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a minimal fake oci.* package and return the put_object mock."""
    put_mock = MagicMock(name="put_object")

    object_storage = types.ModuleType("oci.object_storage")
    client_cls = MagicMock()
    client_cls.return_value.put_object = put_mock
    object_storage.ObjectStorageClient = client_cls

    auth = types.ModuleType("oci.auth")
    signers = types.ModuleType("oci.auth.signers")
    signers.InstancePrincipalsSecurityTokenSigner = MagicMock(name="signer")
    auth.signers = signers

    oci_mod = types.ModuleType("oci")
    oci_mod.object_storage = object_storage
    oci_mod.auth = auth

    monkeypatch.setitem(sys.modules, "oci", oci_mod)
    monkeypatch.setitem(sys.modules, "oci.object_storage", object_storage)
    monkeypatch.setitem(sys.modules, "oci.auth", auth)
    monkeypatch.setitem(sys.modules, "oci.auth.signers", signers)
    return put_mock


def test_returns_none_when_namespace_unset(monkeypatch):
    monkeypatch.delenv("OCI_BUCKET_NAMESPACE", raising=False)
    from app.bucket import upload_scene_image

    assert upload_scene_image("T001", b"\xff", "ship.jpg") is None


def test_uploads_with_expected_object_name(monkeypatch):
    monkeypatch.setenv("OCI_BUCKET_NAMESPACE", "ns0")
    monkeypatch.setenv("OCI_BUCKET_NAME", "imgs")
    monkeypatch.setenv("OCI_BUCKET_PREFIX", "scenes")
    put_mock = _install_fake_oci(monkeypatch)

    # Re-import to re-evaluate the lazy `import oci` paths.
    from app.bucket import upload_scene_image
    obj = upload_scene_image("T002", b"\xff\xd8\xff", "ship.jpg",
                             content_type="image/jpeg")

    assert obj is not None
    assert obj.startswith("scenes/tenant=T002/")
    assert obj.endswith("-ship.jpg")
    put_mock.assert_called_once()
    kwargs = put_mock.call_args.kwargs
    assert kwargs["namespace_name"] == "ns0"
    assert kwargs["bucket_name"] == "imgs"
    assert kwargs["object_name"] == obj
    assert kwargs["content_type"] == "image/jpeg"
    assert kwargs["put_object_body"] == b"\xff\xd8\xff"


def test_returns_none_on_oci_failure(monkeypatch):
    monkeypatch.setenv("OCI_BUCKET_NAMESPACE", "ns0")
    put_mock = _install_fake_oci(monkeypatch)
    put_mock.side_effect = RuntimeError("simulated network error")

    from app.bucket import upload_scene_image
    assert upload_scene_image("T001", b"\xff", "ship.jpg") is None


def test_sanitises_filename_path_traversal(monkeypatch):
    monkeypatch.setenv("OCI_BUCKET_NAMESPACE", "ns0")
    put_mock = _install_fake_oci(monkeypatch)

    from app.bucket import upload_scene_image
    obj = upload_scene_image("T001", b"\xff", "../../etc/passwd")
    assert obj is not None
    # Only the basename is preserved; no leading "../".
    assert "/.." not in obj
    assert obj.endswith("-passwd")
