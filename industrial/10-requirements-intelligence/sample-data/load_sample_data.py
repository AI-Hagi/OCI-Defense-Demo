#!/usr/bin/env python3
"""
UC10 sample-data loader — bypasses load_sample_data.sql.

The SQL path uses BFILENAME(...) against an Oracle DIRECTORY object that
ATP can't expose against the dev-VM filesystem. This script reads the
synthetic.json that generate.py produced and INSERTs the rows directly
via python-oracledb. Idempotent via MERGE-equivalent INSERT...IGNORE
semantics (we use ON CONFLICT do-nothing in PL/SQL).

Usage:
  python3 load_sample_data.py            # picks creds from .env
  python3 load_sample_data.py --json /path/to/synthetic.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import oracledb


def env(key: str, default: str | None = None) -> str:
    val = os.environ.get(key, default)
    if val is None:
        raise SystemExit(f"required env var {key} is not set")
    return val


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def connect(cfg_dir: str, user: str, pwd: str, dsn: str, wallet_pwd: str | None):
    kwargs = {
        "user": user, "password": pwd, "dsn": dsn,
        "config_dir": cfg_dir, "wallet_location": cfg_dir,
    }
    if wallet_pwd:
        kwargs["wallet_password"] = wallet_pwd
    return oracledb.connect(**kwargs)


PROGRAMS_INSERT = """
MERGE INTO programs p USING (SELECT :program_id AS program_id FROM dual) s
ON (p.program_id = s.program_id)
WHEN NOT MATCHED THEN INSERT
  (program_id, name, domain, security_class, customer_country,
   start_year, status, clearance_required, releasable_to)
VALUES (:program_id, :name, :domain, :security_class, :customer_country,
        :start_year, :status, 'RESTRICTED', 'NATO')
"""

REQS_INSERT = """
MERGE INTO requirements r USING (SELECT :req_id AS req_id FROM dual) s
ON (r.req_id = s.req_id)
WHEN NOT MATCHED THEN INSERT
  (req_id, program_id, req_text, req_type, category, status,
   clearance_required, releasable_to)
VALUES (:req_id, :program_id, :req_text, :req_type, :category, :status,
        :clearance_required, :releasable_to)
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--json",
        default=str(Path(__file__).parent / "synthetic.json"),
        help="Path to synthetic.json (default: sibling of this script)",
    )
    ap.add_argument(
        "--dotenv",
        default=str(Path(__file__).resolve().parents[3] / ".env"),
        help="Repo .env path (default: <repo>/.env)",
    )
    args = ap.parse_args()

    load_dotenv(Path(args.dotenv))

    user       = env("DB_APP_USER")
    pwd        = env("DB_APP_PWD")
    dsn        = env("ADB_TNS_ALIAS")
    cfg_dir    = env("ADB_WALLET_PATH", "/home/ubuntu/wallet")
    wallet_pwd = os.environ.get("WALLET_PASSWORD")

    payload: dict[str, Any] = json.loads(Path(args.json).read_text())
    if not payload.get("header", {}).get("synthetic"):
        raise SystemExit("Refusing to load: header.synthetic must be true")

    print(f"Loading {Path(args.json).name} (run_id="
          f"{payload['header'].get('run_id', '?')})")

    with connect(cfg_dir, user, pwd, dsn, wallet_pwd) as conn:
        with conn.cursor() as cur:
            programs = payload.get("programs", [])
            cur.executemany(PROGRAMS_INSERT, [
                {
                    "program_id":       p["program_id"],
                    "name":             p["name"],
                    "domain":           p.get("domain"),
                    "security_class":   p["security_class"],
                    "customer_country": p.get("customer_country"),
                    "start_year":       p.get("start_year"),
                    "status":           p.get("status"),
                }
                for p in programs
            ])
            print(f"  programs inserted/merged:     {len(programs)}")

            reqs = payload.get("requirements", [])
            cur.executemany(REQS_INSERT, [
                {
                    "req_id":             r["req_id"],
                    "program_id":         r["program_id"],
                    "req_text":           r["req_text"],
                    "req_type":           r.get("req_type"),
                    "category":           r.get("category"),
                    "status":             r.get("status"),
                    "clearance_required": r.get("clearance_required", "RESTRICTED"),
                    "releasable_to":      r.get("releasable_to", "NATO"),
                }
                for r in reqs
            ])
            print(f"  requirements inserted/merged: {len(reqs)}")
            conn.commit()
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
