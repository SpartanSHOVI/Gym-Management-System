from flask import Flask, render_template, request, redirect, url_for, flash
import database as db
from datetime import date, timedelta

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Initialize DB
db.init_db()

@app.route('/')
def dashboard():
    conn = db.get_db_connection(db.DB_NAME)
    cursor = conn.cursor()

    # Total Members
    cursor.execute("SELECT COUNT(*) as count FROM members")
    total_members = cursor.fetchone()['count']

    # Active Subscriptions
    cursor.execute("SELECT COUNT(*) as count FROM subscriptions WHERE end_date >= date('now')")
    active_subscriptions = cursor.fetchone()['count']

    # Expiring Soon (in the next 7 days)
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM subscriptions 
        WHERE end_date BETWEEN date('now') AND date('now', '+7 days')
    """)
    expiring_soon = cursor.fetchone()['count']
    
    # Fetch recent members to display
    cursor.execute("SELECT * FROM members ORDER BY join_date DESC LIMIT 5")
    recent_members = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('index.html', 
                           total_members=total_members, 
                           active_subscriptions=active_subscriptions, 
                           expiring_soon=expiring_soon,
                           recent_members=recent_members)

@app.route('/add_member', methods=['GET', 'POST'])
def add_member():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        join_date = date.today().isoformat()

        conn = db.get_db_connection(db.DB_NAME)
        cursor = conn.cursor()
        query = "INSERT INTO members (name, phone, join_date) VALUES (?, ?, ?)"
        cursor.execute(query, (name, phone, join_date))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Member added successfully!')
        return redirect(url_for('dashboard'))

    return render_template('add_member.html')

@app.route('/assign_plan', methods=['GET', 'POST'])
def assign_plan():
    conn = db.get_db_connection(db.DB_NAME)
    cursor = conn.cursor()

    if request.method == 'POST':
        member_id = request.form['member_id']
        plan_id = request.form['plan_id']
        start_date = date.today()

        # Get plan duration
        cursor.execute("SELECT duration_days FROM plans WHERE id = ?", (plan_id,))
        plan = cursor.fetchone()
        duration = timedelta(days=plan['duration_days'])
        end_date = start_date + duration

        # Insert subscription
        query = "INSERT INTO subscriptions (member_id, plan_id, start_date, end_date) VALUES (?, ?, ?, ?)"
        cursor.execute(query, (member_id, plan_id, start_date.isoformat(), end_date.isoformat()))
        conn.commit()

        flash('Plan assigned successfully!')
        return redirect(url_for('dashboard'))

    # GET request: fetch members and plans for dropdowns
    cursor.execute("SELECT id, name FROM members WHERE status = 'Active'")
    members = cursor.fetchall()
    
    cursor.execute("SELECT id, name, price, duration_days FROM plans")
    plans = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('assign_plan.html', members=members, plans=plans)

@app.route('/update_status')
def update_status():
    conn = db.get_db_connection(db.DB_NAME)
    cursor = conn.cursor()

    # Find members whose latest subscription has expired
    query = """
        UPDATE members
        SET status = 'Inactive'
        WHERE id IN (
            SELECT member_id 
            FROM subscriptions 
            GROUP BY member_id 
            HAVING MAX(end_date) < date('now')
        )
    """
    cursor.execute(query)
    updated_count = cursor.rowcount # Get number of updated rows
    conn.commit()

    cursor.close()
    conn.close()

    flash(f'{updated_count} member(s) status updated to Inactive.')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
