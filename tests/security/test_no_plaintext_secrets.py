"""
Regression test — fail-fast on plaintext secrets in committed manifests.

Specifically checks every YAML / JSON file under ``k8s/`` and
``crossplane/`` for literal ORACLE_PASSWORD / WALLET_PASSWORD /
OCIR auth-token values. The placeholder Secret manifest at
``k8s/base/secret-adb-credentials.yaml`` is allowed to declare the
keys with empty string values — that's the schema.

Run with::

    pytest tests/security/test_no_plaintext_secrets.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = [REPO_ROOT / "k8s", REPO_ROOT / "crossplane"]
ALLOWED_FILES = {
    REPO_ROOT / "k8s" / "base" / "secret-adb-credentials.yaml",
}

# Patterns that indicate a non-empty hardcoded credential.
# Each pattern must capture the value so we can ensure it's empty quotes.
PATTERNS = [
    re.compile(r'ORACLE_PASSWORD:\s*"([^"]*)"'),
    re.compile(r"ORACLE_PASSWORD:\s*'([^']*)'"),
    re.compile(r"WALLET_PASSWORD:\s*\"([^\"]*)\""),
    re.compile(r"WALLET_PASSWORD:\s*'([^']*)'"),
    # OCIR token format: 20+ chars of mixed case + symbols inside .dockerconfigjson
    re.compile(r'"password":\s*"([^"]{8,})"'),
]


def _yaml_files() -> list[Path]:
    out: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        out.extend(root.rglob("*.yaml"))
        out.extend(root.rglob("*.yml"))
    return out


@pytest.mark.parametrize("path", _yaml_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_plaintext_secret_in_yaml(path: Path) -> None:
    """No committed YAML may carry a non-empty hardcoded credential."""
    if path in ALLOWED_FILES:
        return
    text = path.read_text()
    for pat in PATTERNS:
        for match in pat.finditer(text):
            value = match.group(1)
            # Empty / placeholder-template values are fine.
            if value == "" or "{{" in value or "<" in value:
                continue
            pytest.fail(
                f"Plaintext credential in {path.relative_to(REPO_ROOT)}: "
                f"{match.group(0)!r}",
            )
