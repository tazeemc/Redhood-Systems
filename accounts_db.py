"""
RedHood Insights - Twitter Accounts Database
=============================================
SQLite store for managing tracked X/Twitter accounts.

Usage:
    python accounts_db.py                  # init DB and seed defaults
    python accounts_db.py --list           # list all accounts
    python accounts_db.py --add handle     # add an account
    python accounts_db.py --remove handle  # remove an account
    python accounts_db.py --toggle handle  # toggle active/inactive
"""

import sqlite3
import os
import argparse
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'redhood.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS twitter_accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    handle      TEXT    NOT NULL UNIQUE,
    added_at    TEXT    NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    category    TEXT,
    notes       TEXT
);
"""

DEFAULT_ACCOUNTS = [
    ('unusual_whales',  'market',  'Options flow and dark pool alerts'),
    ('FirstSquawk',     'news',    'Real-time macro and geopolitical headlines'),
    ('AutismCapital',   'macro',   'Macro intelligence and geopolitical signals'),
    ('Mayhem4Markets',  'market',  'Market structure and volatility commentary'),
    ('BasedBiohacker',  'bio',     'Biotech and health sector signals'),
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create schema and seed default accounts if not already present."""
    conn = get_connection()
    conn.execute(SCHEMA)
    conn.commit()

    now = datetime.utcnow().isoformat()
    for handle, category, notes in DEFAULT_ACCOUNTS:
        conn.execute(
            """INSERT OR IGNORE INTO twitter_accounts (handle, added_at, category, notes)
               VALUES (?, ?, ?, ?)""",
            (handle, now, category, notes)
        )
    conn.commit()
    conn.close()
    print(f"Database initialised: {DB_PATH}")


def list_accounts():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, handle, active, category, notes, added_at FROM twitter_accounts ORDER BY id"
    ).fetchall()
    conn.close()

    print(f"\n{'ID':<4} {'Handle':<22} {'Active':<8} {'Category':<12} {'Notes'}")
    print("-" * 80)
    for r in rows:
        status = 'yes' if r['active'] else 'no'
        print(f"{r['id']:<4} @{r['handle']:<21} {status:<8} {r['category'] or '':<12} {r['notes'] or ''}")
    print(f"\n{len(rows)} account(s) total.\n")


def add_account(handle: str, category: str = None, notes: str = None):
    handle = handle.lstrip('@')
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO twitter_accounts (handle, added_at, category, notes) VALUES (?, ?, ?, ?)",
            (handle, datetime.utcnow().isoformat(), category, notes)
        )
        conn.commit()
        print(f"Added @{handle}")
    except sqlite3.IntegrityError:
        print(f"@{handle} already exists")
    finally:
        conn.close()


def remove_account(handle: str):
    handle = handle.lstrip('@')
    conn = get_connection()
    cursor = conn.execute("DELETE FROM twitter_accounts WHERE handle = ?", (handle,))
    conn.commit()
    conn.close()
    if cursor.rowcount:
        print(f"Removed @{handle}")
    else:
        print(f"@{handle} not found")


def toggle_account(handle: str):
    handle = handle.lstrip('@')
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE twitter_accounts SET active = 1 - active WHERE handle = ?", (handle,)
    )
    conn.commit()
    if cursor.rowcount:
        row = conn.execute("SELECT active FROM twitter_accounts WHERE handle = ?", (handle,)).fetchone()
        status = 'active' if row['active'] else 'inactive'
        print(f"@{handle} is now {status}")
    else:
        print(f"@{handle} not found")
    conn.close()


def get_active_handles() -> list:
    """Return list of active handles for use by the aggregator."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT handle FROM twitter_accounts WHERE active = 1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [r['handle'] for r in rows]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RedHood Twitter Accounts DB')
    parser.add_argument('--list',   action='store_true',  help='List all accounts')
    parser.add_argument('--add',    metavar='HANDLE',     help='Add an account')
    parser.add_argument('--remove', metavar='HANDLE',     help='Remove an account')
    parser.add_argument('--toggle', metavar='HANDLE',     help='Toggle active/inactive')
    parser.add_argument('--category', metavar='CAT',      help='Category for --add')
    parser.add_argument('--notes',    metavar='TEXT',     help='Notes for --add')
    args = parser.parse_args()

    init_db()

    if args.list:
        list_accounts()
    elif args.add:
        add_account(args.add, args.category, args.notes)
        list_accounts()
    elif args.remove:
        remove_account(args.remove)
        list_accounts()
    elif args.toggle:
        toggle_account(args.toggle)
        list_accounts()
    else:
        list_accounts()
