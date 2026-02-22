import json
import os
from datetime import date, timedelta
from functools import wraps
from types import SimpleNamespace

from flask import (Flask, flash, redirect, render_template,
                   request, session, url_for)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

import database as db

app = Flask(__name__)

# ── Security ────────────────────────────────────────────────────────────────
_secret = os.environ.get('SECRET_KEY')
if not _secret:
    import warnings
    warnings.warn(
        "SECRET_KEY environment variable is not set. "
        "Using a random key — all sessions and CSRF tokens will be invalidated on restart. "
        "Set SECRET_KEY in production.",
        stacklevel=1,
    )
    _secret = os.urandom(32)
app.secret_key = _secret
csrf = CSRFProtect(app)

# ── DB init ─────────────────────────────────────────────────────────────────
db.init_db()

# ── Jinja2 helpers ──────────────────────────────────────────────────────────
@app.template_filter('dateformat')
def dateformat(value, fmt='%b %d, %Y'):
    """Format an ISO date string (YYYY-MM-DD) for display."""
    if not value:
        return ''
    try:
        from datetime import datetime
        return datetime.strptime(str(value), '%Y-%m-%d').strftime(fmt)
    except (ValueError, TypeError):
        return value


@app.context_processor
def inject_user():
    return dict(
        current_user_role=session.get('role'),
        current_username=session.get('username'),
        current_user_id=session.get('user_id'),
        server_date=date.today().strftime('%A, %B %d, %Y'),
    )


# ── Auth decorators ──────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('dashboard_dispatch'))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── Validation helpers ───────────────────────────────────────────────────────
def _validate_member_fields(name, phone, email, password=None):
    """Returns an error message string or None if valid."""
    if not name or len(name.strip()) == 0:
        return 'Name is required.'
    if len(name) > 100:
        return 'Name must be 100 characters or fewer.'
    if phone and len(phone) > 30:
        return 'Phone must be 30 characters or fewer.'
    if email and len(email) > 200:
        return 'Email must be 200 characters or fewer.'
    if password is not None:
        if len(password) < 8:
            return 'Password must be at least 8 characters.'
        if len(password) > 200:
            return 'Password is too long.'
    return None


# ── Auth routes ──────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Username and password are required.', 'error')
            return render_template('login.html')

        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id']   = user['id']
            session['username']  = user['username']
            session['role']      = user['role']
            session['member_id'] = user['member_id']
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard_dispatch'))

        flash('Invalid username or password.', 'error')

    return render_template('login.html')


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


# ── Public homepage ──────────────────────────────────────────────────────────
@app.route('/')
def homepage():
    if 'user_id' in session:
        return redirect(url_for('dashboard_dispatch'))
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM plans ORDER BY price ASC")
        plans = cursor.fetchall()
    return render_template('homepage.html', plans=plans)


# ── Dashboard ────────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard_dispatch():
    role = session.get('role')
    if role == 'Admin':
        return redirect(url_for('dashboard_admin'))
    elif role == 'Owner':
        return redirect(url_for('dashboard_owner'))
    elif role == 'Participant':
        return redirect(url_for('dashboard_participant'))
    flash('Unknown role. Please log in again.', 'error')
    return redirect(url_for('login'))


@app.route('/dashboard/admin')
@login_required
@roles_required('Admin')
def dashboard_admin():
    with db.get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) AS count FROM users")
        total_users = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) AS count FROM members WHERE archived = 0")
        total_members = cursor.fetchone()['count']

        # Revenue: sum of plan prices for subscriptions started in the current calendar month
        cursor.execute("""
            SELECT COALESCE(SUM(p.price), 0) AS revenue
            FROM subscriptions s
            JOIN plans p ON s.plan_id = p.id
            WHERE strftime('%Y-%m', s.start_date) = strftime('%Y-%m', 'now')
        """)
        monthly_revenue = cursor.fetchone()['revenue']

        # All-time revenue
        cursor.execute("""
            SELECT COALESCE(SUM(p.price), 0) AS revenue
            FROM subscriptions s
            JOIN plans p ON s.plan_id = p.id
        """)
        total_revenue = cursor.fetchone()['revenue']

        # User list for management panel
        cursor.execute("""
            SELECT u.id, u.username, u.role, m.name AS member_name, u.member_id
            FROM users u
            LEFT JOIN members m ON u.member_id = m.id
            ORDER BY u.role, u.username
        """)
        all_users = cursor.fetchall()

        # Last 6 months revenue by month
        cursor.execute("""
            SELECT strftime('%Y-%m', s.start_date) AS month,
                   COALESCE(SUM(p.price), 0) AS revenue
            FROM subscriptions s JOIN plans p ON s.plan_id = p.id
            WHERE s.start_date >= date('now', '-5 months', 'start of month')
            GROUP BY month ORDER BY month ASC
        """)
        revenue_rows = {row['month']: float(row['revenue']) for row in cursor.fetchall()}

        # Last 6 months new member signups
        cursor.execute("""
            SELECT strftime('%Y-%m', join_date) AS month, COUNT(*) AS count
            FROM members WHERE archived = 0
              AND join_date >= date('now', '-5 months', 'start of month')
            GROUP BY month ORDER BY month ASC
        """)
        signups_rows = {row['month']: row['count'] for row in cursor.fetchall()}

    # Build a full 6-month list (fill gaps with 0)
    today = date.today()
    months = []
    for i in range(5, -1, -1):
        # go back i months from the first of this month
        first_of_month = (today.replace(day=1) - timedelta(days=i * 28))
        # normalise to the 1st of the correct month
        first_of_month = date(today.year, today.month, 1)
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        months.append(date(y, m, 1).strftime('%Y-%m'))

    chart_revenue_labels = [m for m in months]
    chart_revenue_values = [revenue_rows.get(m, 0) for m in months]
    chart_signups_labels = [m for m in months]
    chart_signups_values = [signups_rows.get(m, 0) for m in months]

    return render_template(
        'dashboard_admin.html',
        total_users=total_users,
        total_members=total_members,
        monthly_revenue=monthly_revenue,
        total_revenue=total_revenue,
        all_users=all_users,
        chart_revenue_labels=chart_revenue_labels,
        chart_revenue_values=chart_revenue_values,
        chart_signups_labels=chart_signups_labels,
        chart_signups_values=chart_signups_values,
    )


@app.route('/dashboard/owner')
@login_required
@roles_required('Owner')
def dashboard_owner():
    with db.get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) AS count FROM members WHERE archived = 0")
        total_members = cursor.fetchone()['count']

        cursor.execute(
            "SELECT COUNT(DISTINCT member_id) AS count FROM subscriptions WHERE end_date >= date('now')"
        )
        active_subscriptions = cursor.fetchone()['count']

        cursor.execute("""
            SELECT COUNT(DISTINCT member_id) AS count FROM subscriptions
            WHERE end_date > date('now') AND end_date <= date('now', '+7 days')
        """)
        expiring_soon = cursor.fetchone()['count']

        cursor.execute(
            "SELECT * FROM members WHERE archived = 0 ORDER BY join_date DESC LIMIT 5"
        )
        recent_members = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) AS count FROM plans")
        total_plans = cursor.fetchone()['count']

        # Active vs Inactive member counts for doughnut chart
        cursor.execute("""
            SELECT status, COUNT(*) AS cnt FROM members
            WHERE archived = 0 GROUP BY status
        """)
        status_rows = {row['status']: row['cnt'] for row in cursor.fetchall()}
        active_count   = status_rows.get('Active', 0)
        inactive_count = status_rows.get('Inactive', 0)

    return render_template(
        'dashboard_owner.html',
        total_members=total_members,
        active_subscriptions=active_subscriptions,
        expiring_soon=expiring_soon,
        total_plans=total_plans,
        recent_members=recent_members,
        chart_status_labels=['Active', 'Inactive'],
        chart_status_values=[active_count, inactive_count],
    )


@app.route('/dashboard/participant')
@login_required
@roles_required('Participant')
def dashboard_participant():
    member_id = session.get('member_id')
    with db.get_db() as conn:
        member = db.get_member_by_id(conn, member_id)
        # member may be None if the linked member record was archived or deleted.
        # Still fetch subscriptions so history is visible if any exist.
        subscriptions = db.get_subscriptions_for_member(conn, member_id) if member_id else []
    return render_template(
        'dashboard_participant.html',
        member=member,
        subscriptions=subscriptions,
    )


# ── Members ──────────────────────────────────────────────────────────────────
PER_PAGE = 10


@app.route('/members')
@login_required
@roles_required('Admin', 'Owner')
def members():
    q      = request.args.get('q', '').strip()
    status = request.args.get('status', 'all')
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    with db.get_db() as conn:
        cursor = conn.cursor()

        conditions = ["m.archived = 0"]
        params: list = []

        if q:
            conditions.append("(m.name LIKE ? OR m.phone LIKE ? OR m.email LIKE ?)")
            like = f"%{q}%"
            params += [like, like, like]

        if status in ('Active', 'Inactive'):
            conditions.append("m.status = ?")
            params.append(status)

        where = " AND ".join(conditions)

        cursor.execute(f"SELECT COUNT(*) AS cnt FROM members m WHERE {where}", params)
        total = cursor.fetchone()['cnt']

        offset = (page - 1) * PER_PAGE
        cursor.execute(
            f"SELECT * FROM members m WHERE {where} ORDER BY m.name ASC LIMIT ? OFFSET ?",
            params + [PER_PAGE, offset],
        )
        all_members = cursor.fetchall()

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return render_template(
        'members.html',
        members=all_members,
        q=q,
        status=status,
        page=page,
        total=total,
        total_pages=total_pages,
        per_page=PER_PAGE,
    )


@app.route('/member/<int:id>')
@login_required
def member_detail(id):
    role = session.get('role')
    # Participants can only view their own profile
    if role == 'Participant' and session.get('member_id') != id:
        flash('You do not have permission to view that profile.', 'error')
        return redirect(url_for('dashboard_dispatch'))

    with db.get_db() as conn:
        member = db.get_member_by_id(conn, id)
        if not member:
            flash('Member not found.', 'error')
            return redirect(url_for('members') if role != 'Participant' else url_for('dashboard_dispatch'))
        subscriptions = db.get_subscriptions_for_member(conn, id)

    return render_template('member_detail.html', member=member, subscriptions=subscriptions)


@app.route('/member/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@roles_required('Admin', 'Owner')
def edit_member(id):
    with db.get_db() as conn:
        member = db.get_member_by_id(conn, id)
        if not member:
            flash('Member not found.', 'error')
            return redirect(url_for('members'))

        if request.method == 'POST':
            name   = request.form.get('name', '').strip()
            phone  = request.form.get('phone', '').strip()
            email  = request.form.get('email', '').strip()
            status = request.form.get('status', 'Active')

            err = _validate_member_fields(name, phone, email)
            if err:
                flash(err, 'error')
                return render_template('edit_member.html', member=member)

            if status not in ('Active', 'Inactive'):
                status = 'Active'

            cursor = conn.cursor()
            cursor.execute(
                "UPDATE members SET name=?, phone=?, email=?, status=? WHERE id=?",
                (name, phone, email, status, id),
            )
            conn.commit()
            flash('Member updated successfully!', 'success')
            return redirect(url_for('member_detail', id=id))

    return render_template('edit_member.html', member=member)


@app.route('/add_member', methods=['GET', 'POST'])
@login_required
@roles_required('Admin', 'Owner')
def add_member():
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        phone    = request.form.get('phone', '').strip()
        email    = request.form.get('email', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        def _redisplay(msg):
            flash(msg, 'error')
            form_data = SimpleNamespace(name=name, phone=phone, email=email, username=username)
            return render_template('add_member.html', form_data=form_data)

        if not username or len(username) > 80:
            return _redisplay('Username is required and must be 80 characters or fewer.')

        err = _validate_member_fields(name, phone, email, password)
        if err:
            return _redisplay(err)

        join_date = date.today().isoformat()

        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                return _redisplay('Username already exists. Please choose another.')

            cursor.execute(
                "INSERT INTO members (name, phone, email, join_date) VALUES (?, ?, ?, ?)",
                (name, phone, email, join_date),
            )
            member_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO users (username, password_hash, role, member_id) VALUES (?, ?, 'Participant', ?)",
                (username, generate_password_hash(password), member_id),
            )
            conn.commit()

        flash('Member and user account added successfully!', 'success')
        return redirect(url_for('member_detail', id=member_id))

    return render_template('add_member.html')


@app.route('/member/<int:id>/archive', methods=['POST'])
@login_required
@roles_required('Admin', 'Owner')
def archive_member(id):
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM members WHERE id = ? AND archived = 0", (id,))
        member = cursor.fetchone()
        if not member:
            flash('Member not found.', 'error')
            return redirect(url_for('members'))
        cursor.execute("UPDATE members SET archived = 1, status = 'Inactive' WHERE id = ?", (id,))
        conn.commit()

    flash(f'Member "{member["name"]}" has been archived.', 'success')
    return redirect(url_for('members'))


# ── Plans ────────────────────────────────────────────────────────────────────
@app.route('/plans')
@login_required
@roles_required('Admin', 'Owner')
def plans():
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM plans ORDER BY price ASC")
        all_plans = cursor.fetchall()
    return render_template('plans.html', plans=all_plans)


@app.route('/plan/add', methods=['GET', 'POST'])
@login_required
@roles_required('Admin', 'Owner')
def add_plan():
    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price_raw    = request.form.get('price', '')
        duration_raw = request.form.get('duration_days', '')

        def _redisplay_add(msg):
            flash(msg, 'error')
            plan = SimpleNamespace(name=name, description=description,
                                   price=price_raw, duration_days=duration_raw)
            return render_template('plan_form.html', plan=plan, action='Add')

        if not name or len(name) > 100:
            return _redisplay_add('Plan name is required and must be 100 characters or fewer.')
        if len(description) > 500:
            return _redisplay_add('Description must be 500 characters or fewer.')
        try:
            price    = float(price_raw)
            duration = int(duration_raw)
        except (ValueError, TypeError):
            return _redisplay_add('Price must be a valid number and duration must be a whole number of days.')
        if price < 0:
            return _redisplay_add('Price cannot be negative.')
        if duration < 1:
            return _redisplay_add('Duration must be at least 1 day.')

        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO plans (name, price, duration_days, description) VALUES (?, ?, ?, ?)",
                (name, price, duration, description),
            )
            conn.commit()

        flash('Plan created successfully!', 'success')
        return redirect(url_for('plans'))

    return render_template('plan_form.html', action='Add')


@app.route('/plan/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@roles_required('Admin', 'Owner')
def edit_plan(id):
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM plans WHERE id = ?", (id,))
        plan = cursor.fetchone()
        if not plan:
            flash('Plan not found.', 'error')
            return redirect(url_for('plans'))

        if request.method == 'POST':
            name        = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            price_raw    = request.form.get('price', '')
            duration_raw = request.form.get('duration_days', '')

            def _redisplay_edit(msg):
                flash(msg, 'error')
                draft = SimpleNamespace(id=plan['id'], name=name, description=description,
                                        price=price_raw, duration_days=duration_raw)
                return render_template('plan_form.html', plan=draft, action='Edit')

            if not name or len(name) > 100:
                return _redisplay_edit('Plan name is required and must be 100 characters or fewer.')
            if len(description) > 500:
                return _redisplay_edit('Description must be 500 characters or fewer.')
            try:
                price    = float(price_raw)
                duration = int(duration_raw)
            except (ValueError, TypeError):
                return _redisplay_edit('Price must be a valid number and duration must be a whole number of days.')
            if price < 0:
                return _redisplay_edit('Price cannot be negative.')
            if duration < 1:
                return _redisplay_edit('Duration must be at least 1 day.')

            cursor.execute(
                "UPDATE plans SET name=?, price=?, duration_days=?, description=? WHERE id=?",
                (name, price, duration, description, id),
            )
            conn.commit()
            flash('Plan updated successfully!', 'success')
            return redirect(url_for('plans'))

    return render_template('plan_form.html', plan=plan, action='Edit')


@app.route('/plan/<int:id>/delete', methods=['POST'])
@login_required
@roles_required('Admin', 'Owner')
def delete_plan(id):
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS count FROM subscriptions WHERE plan_id = ?", (id,))
        usage_count = cursor.fetchone()['count']

        if usage_count > 0:
            flash(
                f'Cannot delete plan — it is associated with {usage_count} subscription(s).',
                'error',
            )
        else:
            cursor.execute("DELETE FROM plans WHERE id = ?", (id,))
            conn.commit()
            flash('Plan deleted successfully!', 'success')

    return redirect(url_for('plans'))


# ── Assign plan ───────────────────────────────────────────────────────────────
@app.route('/assign_plan', methods=['GET', 'POST'])
@login_required
@roles_required('Admin', 'Owner')
def assign_plan():
    with db.get_db() as conn:
        cursor = conn.cursor()

        if request.method == 'POST':
            try:
                member_id = int(request.form['member_id'])
                plan_id   = int(request.form['plan_id'])
            except (ValueError, KeyError, TypeError):
                flash('Invalid member or plan selection.', 'error')
                return redirect(url_for('assign_plan'))

            # Validate both entities exist
            cursor.execute("SELECT id FROM members WHERE id = ? AND archived = 0", (member_id,))
            if not cursor.fetchone():
                flash('Selected member does not exist.', 'error')
                return redirect(url_for('assign_plan'))

            cursor.execute("SELECT duration_days FROM plans WHERE id = ?", (plan_id,))
            plan = cursor.fetchone()
            if not plan:
                flash('Selected plan does not exist.', 'error')
                return redirect(url_for('assign_plan'))

            start_date = date.today()
            end_date   = start_date + timedelta(days=plan['duration_days'])

            cursor.execute(
                "INSERT INTO subscriptions (member_id, plan_id, start_date, end_date) VALUES (?, ?, ?, ?)",
                (member_id, plan_id, start_date.isoformat(), end_date.isoformat()),
            )
            cursor.execute(
                "UPDATE members SET status = 'Active' WHERE id = ?", (member_id,)
            )
            conn.commit()

            flash('Plan assigned successfully!', 'success')
            return redirect(url_for('member_detail', id=member_id))

        cursor.execute("SELECT id, name FROM members WHERE archived = 0 ORDER BY name ASC")
        all_members = cursor.fetchall()

        cursor.execute("SELECT id, name, price, duration_days, description FROM plans ORDER BY price ASC")
        all_plans = cursor.fetchall()

    preselect_member = request.args.get('member_id', '')
    return render_template(
        'assign_plan.html',
        members=all_members,
        plans=all_plans,
        preselect_member=preselect_member,
    )


# ── Sync statuses ────────────────────────────────────────────────────────────
@app.route('/update_status', methods=['POST'])
@login_required
@roles_required('Admin', 'Owner')
def update_status():
    with db.get_db() as conn:
        cursor = conn.cursor()

        # Mark Inactive: members whose newest subscription has expired
        cursor.execute("""
            UPDATE members
            SET status = 'Inactive'
            WHERE archived = 0
              AND id IN (
                  SELECT member_id FROM subscriptions
                  GROUP BY member_id
                  HAVING MAX(end_date) < date('now')
              )
        """)
        inactivated = cursor.rowcount

        # Mark Active: members who have at least one current subscription
        cursor.execute("""
            UPDATE members
            SET status = 'Active'
            WHERE archived = 0
              AND id IN (
                  SELECT member_id FROM subscriptions
                  WHERE end_date >= date('now')
              )
        """)
        activated = cursor.rowcount
        conn.commit()

    flash(
        f'Sync complete — {activated} activated, {inactivated} deactivated.',
        'success',
    )
    return redirect(url_for('dashboard_dispatch'))


# ── Admin: delete user ────────────────────────────────────────────────────────
@app.route('/admin/user/<int:id>/delete', methods=['POST'])
@login_required
@roles_required('Admin')
def delete_user(id):
    if id == session.get('user_id'):
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('dashboard_admin'))

    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username, role FROM users WHERE id = ?", (id,))
        user = cursor.fetchone()
        if not user:
            flash('User not found.', 'error')
            return redirect(url_for('dashboard_admin'))
        cursor.execute("DELETE FROM users WHERE id = ?", (id,))
        conn.commit()

    flash(f'User "{user["username"]}" deleted.', 'success')
    return redirect(url_for('dashboard_admin'))


# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port  = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug, host='0.0.0.0', port=port)
