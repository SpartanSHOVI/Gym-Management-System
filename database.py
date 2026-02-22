import sqlite3

DB_NAME = 'gym_db.sqlite'

def get_db_connection(db_name=None):
    """Establishes a connection to a SQLite database."""
    # Use the specific db_name if provided, otherwise default to DB_NAME
    conn = sqlite3.connect(db_name or DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database and tables."""
    conn = get_db_connection()
    cursor = conn.cursor()

    tables = {
        "members": """
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                join_date DATE NOT NULL,
                status TEXT DEFAULT 'Active' CHECK(status IN ('Active', 'Inactive'))
            )
        """,
        "plans": """
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                duration_days INTEGER NOT NULL
            )
        """,
        "subscriptions": """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER,
                plan_id INTEGER,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                FOREIGN KEY (member_id) REFERENCES members(id),
                FOREIGN KEY (plan_id) REFERENCES plans(id)
            )
        """
    }

    for table_name, table_sql in tables.items():
        cursor.execute(table_sql)
        print(f"Table '{table_name}' created or already exists.")
        
    # Insert default plans if none exist so the app is usable immediately
    cursor.execute("SELECT COUNT(*) FROM plans")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO plans (name, price, duration_days) VALUES ('1 Month', 50.00, 30)")
        cursor.execute("INSERT INTO plans (name, price, duration_days) VALUES ('3 Months', 130.00, 90)")
        cursor.execute("INSERT INTO plans (name, price, duration_days) VALUES ('1 Year', 500.00, 365)")
        print("Inserted default plans.")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
