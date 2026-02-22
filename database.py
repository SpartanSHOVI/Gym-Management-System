import sqlite3
from contextlib import contextmanager
from werkzeug.security import generate_password_hash

DB_NAME = 'gym_db.sqlite'


def get_db_connection(db_name=None):
    """Establishes a connection to a SQLite database with FK enforcement."""
    conn = sqlite3.connect(db_name or DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db(db_name=None):
    """Context manager — commits on clean exit, rolls back and closes on exception."""
    conn = get_db_connection(db_name)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_subscriptions_for_member(conn, member_id):
    """Return all subscriptions for a member, newest first."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.*, p.name AS plan_name, p.price
        FROM subscriptions s
        JOIN plans p ON s.plan_id = p.id
        WHERE s.member_id = ?
        ORDER BY s.end_date DESC
        """,
        (member_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    return rows


def get_member_by_id(conn, member_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM members WHERE id = ? AND archived = 0", (member_id,))
    row = cursor.fetchone()
    cursor.close()
    return row


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db():
    """Initialises the database, creates tables, seeds default data."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # ---- tables ----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS members (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                phone      TEXT,
                email      TEXT,
                join_date  DATE    NOT NULL,
                status     TEXT    DEFAULT 'Active' CHECK(status IN ('Active', 'Inactive')),
                archived   INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                price         REAL    NOT NULL,
                duration_days INTEGER NOT NULL,
                description   TEXT    DEFAULT ''
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id  INTEGER,
                plan_id    INTEGER,
                start_date DATE NOT NULL,
                end_date   DATE NOT NULL,
                FOREIGN KEY (member_id) REFERENCES members(id),
                FOREIGN KEY (plan_id)   REFERENCES plans(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    UNIQUE NOT NULL,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL CHECK(role IN ('Admin', 'Owner', 'Participant')),
                member_id     INTEGER,
                FOREIGN KEY (member_id) REFERENCES members(id)
            )
        """)

        # ---- migrate existing tables (add new columns if they don't exist) ----
        _add_column_if_missing(cursor, "members",  "email",       "TEXT")
        _add_column_if_missing(cursor, "members",  "archived",    "INTEGER DEFAULT 0")
        _add_column_if_missing(cursor, "plans",    "description", "TEXT DEFAULT ''")

        # ---- indexes ----
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_member_id ON subscriptions(member_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_end_date  ON subscriptions(end_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_members_status          ON members(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_members_archived        ON members(archived)")

        # ---- seed default plans ----
        cursor.execute("SELECT COUNT(*) FROM plans")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO plans (name, price, duration_days, description) VALUES (?, ?, ?, ?)",
                ('1 Month', 50.00, 30, 'Full gym access for 30 days.'),
            )
            cursor.execute(
                "INSERT INTO plans (name, price, duration_days, description) VALUES (?, ?, ?, ?)",
                ('3 Months', 130.00, 90, 'Full gym access for 90 days at a discounted rate.'),
            )
            cursor.execute(
                "INSERT INTO plans (name, price, duration_days, description) VALUES (?, ?, ?, ?)",
                ('1 Year', 500.00, 365, 'Full gym access for a full year — best value.'),
            )
            print("Inserted default plans.")

        # ---- seed default users ----
        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            admin_pw  = generate_password_hash('admin123')
            owner_pw  = generate_password_hash('owner123')
            member_pw = generate_password_hash('member123')

            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ('admin', admin_pw, 'Admin'),
            )
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ('owner', owner_pw, 'Owner'),
            )
            cursor.execute(
                "INSERT INTO members (name, phone, join_date) VALUES (?, ?, date('now', '-10 days'))",
                ('John Participant', '555-0100'),
            )
            member_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO users (username, password_hash, role, member_id) VALUES (?, ?, ?, ?)",
                ('member', member_pw, 'Participant', member_id),
            )
            cursor.execute(
                "INSERT INTO subscriptions (member_id, plan_id, start_date, end_date) "
                "VALUES (?, 1, date('now', '-10 days'), date('now', '+20 days'))",
                (member_id,),
            )
            print("Inserted default users (admin, owner, member).")

        conn.commit()
        print("Database initialised.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _add_column_if_missing(cursor, table, column, col_type):
    """Adds a column to an existing table if it doesn't already exist (migration helper)."""
    cursor.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cursor.fetchall()]
    if column not in cols:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        print(f"Migrated: added column '{column}' to '{table}'.")


if __name__ == '__main__':
    init_db()
