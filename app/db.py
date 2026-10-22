import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://ledger:ledger@ledger:5432/ledger")

def get_pg_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
        conn.autocommit = True
        return conn
    except Exception:
        return None

def init_sqlite_db():
    conn = sqlite3.connect("ledger.sqlite3", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                sandbox_name TEXT NOT NULL,
                problem_id TEXT NOT NULL,
                state TEXT NOT NULL,
                execution_target TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        # Insert seed row idempotently
        cursor = conn.cursor()
        cursor.execute("SELECT run_id FROM runs WHERE run_id = 'run-seed0001'")
        if not cursor.fetchone():
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at)
                VALUES ('run-seed0001', 'sbx-seeddemo1', 'issue-repro-seed-problem', 'deleted', 'celesto_sandbox', ?, ?)
            """, (now_iso, now_iso))
    return conn

# Lazy connection holder for SQLite fallback
_sqlite_conn = None

def get_db():
    pg = get_pg_connection()
    if pg:
        return ("pg", pg)
    global _sqlite_conn
    if _sqlite_conn is None:
        _sqlite_conn = init_sqlite_db()
    return ("sqlite", _sqlite_conn)

def fetch_all_runs() -> List[Dict[str, Any]]:
    backend, conn = get_db()
    if backend == "pg":
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at FROM runs ORDER BY created_at ASC")
            rows = cur.fetchall()
            # Convert datetime to string
            result = []
            for r in rows:
                item = dict(r)
                if isinstance(item.get("created_at"), datetime):
                    item["created_at"] = item["created_at"].isoformat()
                if isinstance(item.get("updated_at"), datetime):
                    item["updated_at"] = item["updated_at"].isoformat()
                result.append(item)
            return result
    else:
        cursor = conn.cursor()
        cursor.execute("SELECT run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at FROM runs ORDER BY created_at ASC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

def insert_run(run_id: str, sandbox_name: str, problem_id: str, state: str, execution_target: str) -> Dict[str, Any]:
    backend, conn = get_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    if backend == "pg":
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (run_id) DO UPDATE SET
                    sandbox_name = EXCLUDED.sandbox_name,
                    problem_id = EXCLUDED.problem_id,
                    state = EXCLUDED.state,
                    execution_target = EXCLUDED.execution_target,
                    updated_at = NOW()
                RETURNING run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at;
            """, (run_id, sandbox_name, problem_id, state, execution_target))
            row = dict(cur.fetchone())
            if isinstance(row.get("created_at"), datetime):
                row["created_at"] = row["created_at"].isoformat()
            if isinstance(row.get("updated_at"), datetime):
                row["updated_at"] = row["updated_at"].isoformat()
            return row
    else:
        with conn:
            conn.execute("""
                INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    sandbox_name=excluded.sandbox_name,
                    problem_id=excluded.problem_id,
                    state=excluded.state,
                    execution_target=excluded.execution_target,
                    updated_at=excluded.updated_at;
            """, (run_id, sandbox_name, problem_id, state, execution_target, now_iso, now_iso))
        return {
            "run_id": run_id,
            "sandbox_name": sandbox_name,
            "problem_id": problem_id,
            "state": state,
            "execution_target": execution_target,
            "created_at": now_iso,
            "updated_at": now_iso
        }
