from flask import Flask, render_template, request, redirect, send_file
from datetime import datetime, date
import io
import pandas as pd
import mysql.connector

app = Flask(__name__)

# --- Configure MySQL ---
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="kavusith_28.11.2004",
    database="restaurant_db"
)
cursor = db.cursor(dictionary=True)

# --- Helper: initialize sample data ---
def init_sample():
    # Menu
    cursor.execute("SELECT COUNT(*) AS count FROM menu")
    if cursor.fetchone()['count'] == 0:
        sample_menu = [
            ("Margherita Pizza", "Pizza", 8.99),
            ("Veggie Burger", "Burger", 6.50),
            ("Caesar Salad", "Salad", 5.00),
            ("Pasta Alfredo", "Pasta", 7.25)
        ]
        cursor.executemany("INSERT INTO menu (name, category, price) VALUES (%s, %s, %s)", sample_menu)
        db.commit()

    # Tables
    cursor.execute("SELECT COUNT(*) AS count FROM tables")
    if cursor.fetchone()['count'] == 0:
        sample_tables = [
            (1, 2, True, None, None),
            (2, 4, True, None, None),
            (3, 6, True, None, None)
        ]
        cursor.executemany(
            "INSERT INTO tables (table_no, seats, available, reserved_by, reserved_date) VALUES (%s, %s, %s, %s, %s)",
            sample_tables
        )
        db.commit()

init_sample()

# --- Routes ---
@app.route("/")
def home():
    return render_template("index.html")

# View menu
@app.route("/menu")
def menu():
    category = request.args.get("category")
    sort = request.args.get("sort")  # "price_asc", "price_desc", "name"
    
    query = "SELECT * FROM menu"
    params = []
    if category:
        query += " WHERE category=%s"
        params.append(category)
    cursor.execute(query, params)
    items = cursor.fetchall()

    if sort == "price_asc":
        items = sorted(items, key=lambda x: x["price"])
    elif sort == "price_desc":
        items = sorted(items, key=lambda x: x["price"], reverse=True)
    elif sort == "name":
        items = sorted(items, key=lambda x: x["name"])

    cursor.execute("SELECT DISTINCT category FROM menu")
    categories = [row['category'] for row in cursor.fetchall()]

    return render_template("menu.html", items=items, categories=categories, selected_category=category, sort=sort)

# Place an order
@app.route("/order", methods=["GET", "POST"])
def order():
    if request.method == "POST":
        customer = request.form["customer"]
        table_no = int(request.form["table_no"])
        items_selected = request.form.getlist("item")

        # Build order items list and calculate total
        order_items = []
        total = 0.0
        for item_name in items_selected:
            cursor.execute("SELECT * FROM menu WHERE name=%s", (item_name,))
            it = cursor.fetchone()
            if it:
                order_items.append({"name": it["name"], "price": it["price"]})
                total += float(it["price"])

        # Insert order
        cursor.execute(
            "INSERT INTO orders (customer, table_no, total, status, timestamp) VALUES (%s, %s, %s, %s, %s)",
            (customer, table_no, round(total, 2), "Placed", datetime.now())
        )
        db.commit()
        order_id = cursor.lastrowid

        # Insert order items
        for it in order_items:
            cursor.execute(
                "INSERT INTO order_items (order_id, item_name, item_price) VALUES (%s, %s, %s)",
                (order_id, it["name"], it["price"])
            )
        db.commit()

        # Mark table as unavailable
        cursor.execute("UPDATE tables SET available=False WHERE table_no=%s", (table_no,))
        db.commit()

        return redirect("/menu")

    # GET -> show form
    cursor.execute("SELECT * FROM menu")
    items = cursor.fetchall()
    cursor.execute("SELECT * FROM tables")
    tables = cursor.fetchall()
    return render_template("order.html", items=items, tables=tables)

# Reserve a table
@app.route("/reserve", methods=["GET", "POST"])
def reserve():
    if request.method == "POST":
        name = request.form["name"]
        table_no = int(request.form["table_no"])
        date_str = request.form["date"]

        cursor.execute(
            "UPDATE tables SET available=False, reserved_by=%s, reserved_date=%s WHERE table_no=%s",
            (name, date_str, table_no)
        )
        db.commit()
        return redirect("/reserve")

    cursor.execute("SELECT * FROM tables")
    tables = cursor.fetchall()
    return render_template("reserve.html", tables=tables)

# Staff panel
@app.route("/staff", methods=["GET", "POST"])
def staff():
    if request.method == "POST":
        if "order_id" in request.form:
            order_id = int(request.form["order_id"])
            new_status = request.form["status"]
            cursor.execute("UPDATE orders SET status=%s WHERE id=%s", (new_status, order_id))
            db.commit()
        elif "table_no" in request.form:
            table_no = int(request.form["table_no"])
            avail = request.form.get("available") == "on"
            if avail:
                cursor.execute(
                    "UPDATE tables SET available=True, reserved_by=NULL, reserved_date=NULL WHERE table_no=%s",
                    (table_no,)
                )
            else:
                cursor.execute("UPDATE tables SET available=False WHERE table_no=%s", (table_no,))
            db.commit()
        return redirect("/staff")

    status = request.args.get("status")
    query = "SELECT * FROM orders"
    params = []
    if status:
        query += " WHERE status=%s"
        params.append(status)
    cursor.execute(query, params)
    orders = cursor.fetchall()

    cursor.execute("SELECT * FROM tables")
    tables = cursor.fetchall()
    return render_template("staff.html", orders=orders, tables=tables, filter_status=status)

# Daily sales report
@app.route("/report", methods=["GET"])
def report():
    day = request.args.get("day")
    if not day:
        day = date.today().isoformat()
    start = f"{day} 00:00:00"
    end = f"{day} 23:59:59"

    cursor.execute("SELECT * FROM orders WHERE timestamp BETWEEN %s AND %s", (start, end))
    results = cursor.fetchall()

    rows = []
    for r in results:
        cursor.execute("SELECT * FROM order_items WHERE order_id=%s", (r["id"],))
        items = cursor.fetchall()
        rows.append({
            "order_id": r["id"],
            "customer": r.get("customer"),
            "table_no": r.get("table_no"),
            "total": r.get("total"),
            "status": r.get("status"),
            "timestamp": r.get("timestamp"),
            "items": ", ".join([it["item_name"] for it in items])
        })

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame([{"message": "No orders for this day"}])

    csv_io = io.StringIO()
    df.to_csv(csv_io, index=False)
    mem = io.BytesIO()
    mem.write(csv_io.getvalue().encode("utf-8"))
    mem.seek(0)
    filename = f"sales_report_{day}.csv"
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name=filename)

if __name__ == "__main__":
    app.run(debug=True)
