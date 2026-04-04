# ============================================================
# Smart Invoice & Expense Tracker - Main Flask Application
# ============================================================

import os
import functools
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, session)
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")
DATABASE = os.path.join(os.path.dirname(__file__), "invoice_tracker.db")


# ─────────────────────────────────────────────
# Database Helpers
# ─────────────────────────────────────────────

def get_db():
    """Open a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Create all tables and safely add any missing columns.
    This runs on every startup — safe to run multiple times.
    """
    conn = get_db()
    c = conn.cursor()

    # ── Users table (NEW) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT    NOT NULL,
            email    TEXT    NOT NULL UNIQUE,
            password TEXT    NOT NULL,
            created  TEXT    NOT NULL
        )
    """)

    # ── Customers ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 0,
            name    TEXT NOT NULL,
            email   TEXT,
            phone   TEXT,
            created TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # ── Invoices ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL DEFAULT 0,
            invoice_num TEXT,
            customer_id INTEGER NOT NULL,
            description TEXT    NOT NULL,
            amount      REAL    NOT NULL,
            date        TEXT    NOT NULL,
            due_date    TEXT,
            status      TEXT    NOT NULL DEFAULT 'unpaid',
            notes       TEXT,
            created     TEXT    NOT NULL,
            FOREIGN KEY (user_id)     REFERENCES users(id),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)

    # ── Expenses ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER NOT NULL DEFAULT 0,
            title    TEXT NOT NULL,
            amount   REAL NOT NULL,
            category TEXT NOT NULL,
            date     TEXT NOT NULL,
            notes    TEXT,
            created  TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # ── Safe migrations: add columns that may not exist in older DBs ──
    def add_col(table, col, col_def):
        """Add a column only if it doesn't already exist."""
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")

    add_col("invoices", "due_date",    "TEXT")
    add_col("invoices", "notes",       "TEXT")
    add_col("invoices", "invoice_num", "TEXT")
    add_col("invoices", "user_id",     "INTEGER NOT NULL DEFAULT 0")
    add_col("customers", "user_id",    "INTEGER NOT NULL DEFAULT 0")
    add_col("expenses",  "notes",      "TEXT")
    add_col("expenses",  "user_id",    "INTEGER NOT NULL DEFAULT 0")

    conn.commit()
    conn.close()


init_db()


# ─────────────────────────────────────────────
# Auth Helpers
# ─────────────────────────────────────────────

def login_required(view):
    """
    Decorator: if the user is not logged in, send them to the login page.
    Wrap any route with @login_required to protect it.
    """
    @functools.wraps(view)
    def wrapped(**kwargs):
        if "user_id" not in session:
            flash("Please log in to access that page.", "error")
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped


def current_user_id():
    """Return the logged-in user's ID from the session."""
    return session.get("user_id")


# ─────────────────────────────────────────────
# Business Logic Helpers
# ─────────────────────────────────────────────

def effective_status(invoice):
    """
    Compute the display status for an invoice:
      'paid'    → already paid
      'overdue' → unpaid and past its due date
      'unpaid'  → unpaid, not yet due
    """
    if invoice["status"] == "paid":
        return "paid"
    if invoice["due_date"]:
        try:
            if date.fromisoformat(invoice["due_date"]) < date.today():
                return "overdue"
        except ValueError:
            pass
    return "unpaid"


def next_invoice_number(conn, uid):
    """Generate the next sequential invoice number for this user, e.g. INV-007."""
    count = conn.execute(
        "SELECT COUNT(*) FROM invoices WHERE user_id = ?", (uid,)
    ).fetchone()[0]
    return f"INV-{count + 1:03d}"


# ─────────────────────────────────────────────
# Authentication Routes
# ─────────────────────────────────────────────

@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Create a new account."""
    # Already logged in → go to dashboard
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")

        # ── Validation ──
        if not name or not email or not password:
            flash("All fields are required.", "error")
            return redirect(url_for("signup"))

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return redirect(url_for("signup"))

        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("signup"))

        conn = get_db()
        # Check for duplicate email
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()

        if existing:
            flash("An account with that email already exists. Please log in.", "error")
            conn.close()
            return redirect(url_for("signup"))

        # Hash the password before storing it
        hashed = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (name, email, password, created) VALUES (?, ?, ?, ?)",
            (name, email, hashed, datetime.now().isoformat())
        )
        conn.commit()

        # Log the new user straight in
        user = conn.execute(
            "SELECT id, name FROM users WHERE email = ?", (email,)
        ).fetchone()
        session["user_id"]   = user["id"]
        session["user_name"] = user["name"]
        conn.close()

        flash(f"Welcome, {name}! Your account has been created.", "success")
        return redirect(url_for("dashboard"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log in to an existing account."""
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.", "error")
            return redirect(url_for("login"))

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        conn.close()

        # check_password_hash compares the plain text against the stored hash
        if not user or not check_password_hash(user["password"], password):
            flash("Invalid email or password. Please try again.", "error")
            return redirect(url_for("login"))

        # Store user info in the session
        session["user_id"]   = user["id"]
        session["user_name"] = user["name"]

        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    """Clear the session and redirect to login."""
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ─────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    """Home page: summary cards and recent activity for the logged-in user."""
    uid   = current_user_id()
    conn  = get_db()
    today = date.today().isoformat()

    # Financial totals — all scoped to this user
    total_income = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM invoices WHERE user_id=? AND status='paid'",
        (uid,)
    ).fetchone()[0]

    total_expenses = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE user_id=?", (uid,)
    ).fetchone()[0]

    pending_payments = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM invoices WHERE user_id=? AND status='unpaid'",
        (uid,)
    ).fetchone()[0]

    overdue_amount = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM invoices "
        "WHERE user_id=? AND status='unpaid' AND due_date IS NOT NULL AND due_date < ?",
        (uid, today)
    ).fetchone()[0]

    profit = total_income - total_expenses

    total_customers = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE user_id=?", (uid,)
    ).fetchone()[0]

    total_invoices = conn.execute(
        "SELECT COUNT(*) FROM invoices WHERE user_id=?", (uid,)
    ).fetchone()[0]

    # Recent invoices (last 5)
    recent_invoices_raw = conn.execute("""
        SELECT i.*, c.name as customer_name
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.user_id = ?
        ORDER BY i.created DESC
        LIMIT 5
    """, (uid,)).fetchall()

    recent_invoices = [
        {**dict(r), "eff_status": effective_status(r)} for r in recent_invoices_raw
    ]

    recent_expenses = conn.execute(
        "SELECT * FROM expenses WHERE user_id=? ORDER BY created DESC LIMIT 5", (uid,)
    ).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        total_income=total_income,
        total_expenses=total_expenses,
        pending_payments=pending_payments,
        overdue_amount=overdue_amount,
        profit=profit,
        total_customers=total_customers,
        total_invoices=total_invoices,
        recent_invoices=recent_invoices,
        recent_expenses=recent_expenses,
    )


# ─────────────────────────────────────────────
# Customer Routes
# ─────────────────────────────────────────────

@app.route("/customers")
@login_required
def customers():
    """Show this user's customers with per-customer invoice totals."""
    uid   = current_user_id()
    conn  = get_db()
    today = date.today().isoformat()

    all_customers = conn.execute(
        "SELECT * FROM customers WHERE user_id=? ORDER BY name ASC", (uid,)
    ).fetchall()

    enriched = []
    for cust in all_customers:
        cid = cust["id"]

        total_biz = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM invoices WHERE customer_id=? AND user_id=?",
            (cid, uid)
        ).fetchone()[0]

        pending = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM invoices "
            "WHERE customer_id=? AND user_id=? AND status='unpaid'",
            (cid, uid)
        ).fetchone()[0]

        overdue_count = conn.execute(
            "SELECT COUNT(*) FROM invoices "
            "WHERE customer_id=? AND user_id=? AND status='unpaid' "
            "AND due_date IS NOT NULL AND due_date < ?",
            (cid, uid, today)
        ).fetchone()[0]

        enriched.append({
            "id":            cust["id"],
            "name":          cust["name"],
            "email":         cust["email"],
            "phone":         cust["phone"],
            "created":       cust["created"],
            "total_biz":     total_biz,
            "pending":       pending,
            "overdue_count": overdue_count,
            "is_risky":      overdue_count >= 2,
        })

    conn.close()
    return render_template("customers.html", customers=enriched)


@app.route("/customers/add", methods=["GET", "POST"])
@login_required
def add_customer():
    """Form to add a new customer."""
    if request.method == "POST":
        name  = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name:
            flash("Customer name is required.", "error")
            return redirect(url_for("add_customer"))

        conn = get_db()
        conn.execute(
            "INSERT INTO customers (user_id, name, email, phone, created) VALUES (?,?,?,?,?)",
            (current_user_id(), name, email, phone, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

        flash(f"Customer '{name}' added successfully!", "success")
        return redirect(url_for("customers"))

    return render_template("add_customer.html")


@app.route("/customers/delete/<int:customer_id>", methods=["POST"])
@login_required
def delete_customer(customer_id):
    """Delete a customer (must belong to this user)."""
    uid  = current_user_id()
    conn = get_db()
    customer = conn.execute(
        "SELECT name FROM customers WHERE id=? AND user_id=?", (customer_id, uid)
    ).fetchone()

    if not customer:
        flash("Customer not found.", "error")
        conn.close()
        return redirect(url_for("customers"))

    conn.execute("DELETE FROM invoices WHERE customer_id=? AND user_id=?", (customer_id, uid))
    conn.execute("DELETE FROM customers WHERE id=? AND user_id=?",          (customer_id, uid))
    conn.commit()
    conn.close()

    flash(f"Customer '{customer['name']}' deleted.", "success")
    return redirect(url_for("customers"))


# ─────────────────────────────────────────────
# Invoice Routes
# ─────────────────────────────────────────────

@app.route("/invoices")
@login_required
def invoices():
    """Show this user's invoices."""
    uid  = current_user_id()
    conn = get_db()
    raw  = conn.execute("""
        SELECT i.*, c.name as customer_name
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.user_id = ?
        ORDER BY i.created DESC
    """, (uid,)).fetchall()
    conn.close()

    all_invoices = [
        {**dict(r), "eff_status": effective_status(r)} for r in raw
    ]
    return render_template("invoices.html", invoices=all_invoices)


@app.route("/invoices/add", methods=["GET", "POST"])
@login_required
def add_invoice():
    """Form to create a new invoice."""
    uid  = current_user_id()
    conn = get_db()
    all_customers = conn.execute(
        "SELECT id, name FROM customers WHERE user_id=? ORDER BY name ASC", (uid,)
    ).fetchall()

    if request.method == "POST":
        customer_id = request.form.get("customer_id")
        description = request.form.get("description", "").strip()
        amount      = request.form.get("amount", "").strip()
        inv_date    = request.form.get("date", "").strip()
        due_date    = request.form.get("due_date", "").strip() or None
        notes       = request.form.get("notes", "").strip() or None

        if not customer_id or not description or not amount or not inv_date:
            flash("Customer, description, amount, and date are all required.", "error")
            conn.close()
            return redirect(url_for("add_invoice"))

        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Amount must be a positive number.", "error")
            conn.close()
            return redirect(url_for("add_invoice"))

        invoice_num = next_invoice_number(conn, uid)

        conn.execute("""
            INSERT INTO invoices
                (user_id, invoice_num, customer_id, description, amount,
                 date, due_date, status, notes, created)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'unpaid', ?, ?)
        """, (uid, invoice_num, customer_id, description, amount,
              inv_date, due_date, notes, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        flash(f"Invoice {invoice_num} created successfully!", "success")
        return redirect(url_for("invoices"))

    conn.close()
    return render_template("add_invoice.html", customers=all_customers)


@app.route("/invoices/toggle/<int:invoice_id>", methods=["POST"])
@login_required
def toggle_invoice_status(invoice_id):
    """Toggle invoice between paid and unpaid (only for this user's invoices)."""
    uid  = current_user_id()
    conn = get_db()
    invoice = conn.execute(
        "SELECT status FROM invoices WHERE id=? AND user_id=?", (invoice_id, uid)
    ).fetchone()

    if not invoice:
        flash("Invoice not found.", "error")
        conn.close()
        return redirect(url_for("invoices"))

    new_status = "paid" if invoice["status"] != "paid" else "unpaid"
    conn.execute(
        "UPDATE invoices SET status=? WHERE id=? AND user_id=?", (new_status, invoice_id, uid)
    )
    conn.commit()
    conn.close()

    flash(f"Invoice marked as {new_status}.", "success")
    return redirect(url_for("invoices"))


@app.route("/invoices/delete/<int:invoice_id>", methods=["POST"])
@login_required
def delete_invoice(invoice_id):
    """Delete an invoice (only for this user)."""
    uid  = current_user_id()
    conn = get_db()
    conn.execute("DELETE FROM invoices WHERE id=? AND user_id=?", (invoice_id, uid))
    conn.commit()
    conn.close()
    flash("Invoice deleted.", "success")
    return redirect(url_for("invoices"))


# ─────────────────────────────────────────────
# Expense Routes
# ─────────────────────────────────────────────

@app.route("/expenses")
@login_required
def expenses():
    """Show this user's expenses."""
    uid  = current_user_id()
    conn = get_db()
    all_expenses = conn.execute(
        "SELECT * FROM expenses WHERE user_id=? ORDER BY created DESC", (uid,)
    ).fetchall()
    conn.close()
    return render_template("expenses.html", expenses=all_expenses)


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    """Form to add a new expense."""
    categories = ["Rent", "Food", "Travel", "Software", "Miscellaneous",
                  "Hardware", "Marketing", "Utilities", "Salaries", "Office Supplies"]

    if request.method == "POST":
        title    = request.form.get("title", "").strip()
        amount   = request.form.get("amount", "").strip()
        date_val = request.form.get("date", "").strip()
        notes    = request.form.get("notes", "").strip() or None
        category = request.form.get("category", "").strip()
        custom   = request.form.get("custom_category", "").strip()
        if category == "Other" and custom:
            category = custom

        if not title or not amount or not category or not date_val:
            flash("Title, amount, category, and date are required.", "error")
            return redirect(url_for("add_expense"))

        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Amount must be a positive number.", "error")
            return redirect(url_for("add_expense"))

        conn = get_db()
        conn.execute("""
            INSERT INTO expenses (user_id, title, amount, category, date, notes, created)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (current_user_id(), title, amount, category, date_val,
              notes, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        flash(f"Expense '{title}' added successfully!", "success")
        return redirect(url_for("expenses"))

    return render_template("add_expense.html", categories=categories)


@app.route("/expenses/delete/<int:expense_id>", methods=["POST"])
@login_required
def delete_expense(expense_id):
    """Delete an expense (only for this user)."""
    uid  = current_user_id()
    conn = get_db()
    conn.execute("DELETE FROM expenses WHERE id=? AND user_id=?", (expense_id, uid))
    conn.commit()
    conn.close()
    flash("Expense deleted.", "success")
    return redirect(url_for("expenses"))


# ─────────────────────────────────────────────
# Run the App
# ─────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
