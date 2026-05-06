"""
One-shot in-cluster migration runner for db/migrations/04_supply_chain_seed.sql.

Connects with the same env vars + wallet that the supply-chain Deployment uses
(adb-credentials secret + adb-wallet secret + sovdefence-common configmap), so
no ADMIN credentials are needed: the app schema runs the MERGE itself.

The migration file uses SQL*Plus / SQLcl semantics — anonymous PL/SQL blocks
terminated by a standalone `/` on its own line. We split on that, strip
SQL*Plus directives that oracledb's thin mode doesn't understand
(WHENEVER / SET / etc.), and execute each remaining block via
cursor.execute(). DBMS_OUTPUT lines are pulled and echoed.
"""
from __future__ import annotations

import os
import sys

import oracledb


SQL_PATH = os.environ.get("MIGRATION_SQL_PATH", "/sql/migration.sql")


def _strip_sqlplus_directives(text: str) -> str:
    """Drop SQL*Plus directives that oracledb's thin mode rejects."""
    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        # Drop SQL*Plus session-control directives.
        if upper.startswith(("WHENEVER ", "SET ", "PROMPT ", "SHOW ", "EXIT")):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _split_blocks(text: str) -> list[str]:
    """
    Split on lines containing only `/`. Each block is then a complete
    PL/SQL anonymous block (DECLARE..BEGIN..END;) or a SQL statement.
    Trailing `;` on plain SQL is fine; oracledb tolerates it.
    """
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip() == "/":
            block = "\n".join(current).strip()
            if block:
                blocks.append(block)
            current = []
        else:
            current.append(line)
    tail = "\n".join(current).strip()
    if tail:
        blocks.append(tail)
    return blocks


def _enable_dbms_output(cur: oracledb.Cursor) -> None:
    cur.callproc("DBMS_OUTPUT.ENABLE", [None])


def _drain_dbms_output(cur: oracledb.Cursor) -> None:
    chunk_size = 100
    line_var = cur.var(str)
    status_var = cur.var(int)
    while True:
        cur.callproc("DBMS_OUTPUT.GET_LINE", [line_var, status_var])
        if status_var.getvalue() != 0:
            break
        line = line_var.getvalue() or ""
        print(f"  DBMS_OUTPUT> {line}")
        # break out if we've drained
        if chunk_size <= 0:
            break
        chunk_size -= 1


def main() -> int:
    user = os.environ["ORACLE_USER"]
    password = os.environ["ORACLE_PASSWORD"]
    dsn = os.environ.get("ORACLE_CONNECT_STRING", "sovdef26_tp")
    wallet_dir = os.environ.get("TNS_ADMIN", "/app/wallet")
    wallet_password = os.environ.get("WALLET_PASSWORD", "YourSecurePassword123#")

    with open(SQL_PATH, "r", encoding="utf-8") as fh:
        raw = fh.read()
    cleaned = _strip_sqlplus_directives(raw)
    blocks = _split_blocks(cleaned)
    print(f"[runner] file={SQL_PATH} blocks={len(blocks)} user={user} dsn={dsn}")

    with oracledb.connect(
        user=user,
        password=password,
        dsn=dsn,
        config_dir=wallet_dir,
        wallet_location=wallet_dir,
        wallet_password=wallet_password,
    ) as conn:
        for idx, block in enumerate(blocks, start=1):
            preview = block.strip().splitlines()[0][:80]
            print(f"[runner] -> block {idx}/{len(blocks)}: {preview}")
            with conn.cursor() as cur:
                _enable_dbms_output(cur)
                cur.execute(block)
                _drain_dbms_output(cur)
        conn.commit()
    print("[runner] migration applied successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
