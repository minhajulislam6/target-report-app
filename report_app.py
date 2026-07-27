import json
import os
from flask import Flask, render_template_string, request, redirect, url_for, flash, session
import openpyxl

app = Flask(__name__)
app.secret_key = "dev-secret-key"  # সেশন ও flash মেসেজের জন্য দরকার — পাবলিশ করার আগে এটা বদলে ফেলুন

# লগইন পাসওয়ার্ড — চাইলে এখানে সরাসরি বদলাতে পারেন,
# অথবা এনভায়রনমেন্ট ভ্যারিয়েবল APP_PASSWORD সেট করে দিতে পারেন (হোস্টিং সাইটে এটা বেশি নিরাপদ)
APP_PASSWORD = os.environ.get("APP_PASSWORD", "12345678")

LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <title>লগইন</title>
    <style>
        body { font-family: Arial, sans-serif; background: #f4f4f9; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .box { background: white; padding: 35px 40px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); width: 300px; }
        h2 { text-align: center; color: #2c3e50; margin-top: 0; }
        input { width: 100%; padding: 10px; margin-bottom: 12px; border: 1px solid #ccc; border-radius: 5px; font-size: 14px; box-sizing: border-box; }
        button { width: 100%; padding: 10px; background: #3498db; color: white; border: none; border-radius: 5px; font-size: 15px; cursor: pointer; }
        button:hover { background: #2980b9; }
        .error { color: #e74c3c; text-align: center; font-size: 13px; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="box">
        <h2>🔒 লগইন করুন</h2>
        {% if error %}<p class="error">{{ error }}</p>{% endif %}
        <form method="POST">
            <input type="password" name="password" placeholder="পাসওয়ার্ড দিন" required autofocus>
            <button type="submit">প্রবেশ করুন</button>
        </form>
    </div>
</body>
</html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("home"))
        error = "পাসওয়ার্ড ভুল হয়েছে, আবার চেষ্টা করুন।"
    return render_template_string(LOGIN_PAGE, error=error)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


@app.before_request
def require_login():
    # লগইন ও স্ট্যাটিক ফাইল ছাড়া বাকি সব পেজের আগে লগইন চেক করা হচ্ছে
    if request.endpoint in ("login", "static") or session.get("logged_in"):
        return None
    return redirect(url_for("login"))


DATA_FILE = "reports.json"


def load_reports():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_reports(reports):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)


reports = load_reports()

PAGE = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <title>টার্গেট বনাম অ্যাচিভমেন্ট রিপোর্ট</title>
    <style>
        body { font-family: Arial, sans-serif; background: #f4f4f9; padding: 30px; }
        .container { max-width: 1100px; margin: 0 auto; }
        h1 { color: #2c3e50; text-align: center; }
        .card { background: white; padding: 20px 25px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.08); margin-bottom: 25px; }
        label { font-size: 13px; color: #555; display: block; margin-bottom: 3px; }
        input, select { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 5px; font-size: 14px; box-sizing: border-box; }
        button { padding: 10px 20px; background: #3498db; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 15px; margin-top: 12px; }
        button:hover { background: #2980b9; }
        .filter-bar { display: flex; gap: 10px; flex-wrap: wrap; align-items: end; }
        .filter-bar > div { flex: 1; min-width: 150px; }
        table { width: 100%; border-collapse: collapse; background: white; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #eee; font-size: 13px; }
        th { background: #2c3e50; color: white; }
        tr:hover { background: #f9f9f9; }
        .ach-good { color: #27ae60; font-weight: bold; }
        .ach-bad { color: #e74c3c; font-weight: bold; }
        .empty { text-align: center; color: #999; padding: 20px; }
        .delete-link { color: #e74c3c; text-decoration: none; font-size: 13px; }
        .clear-link { display: inline-block; margin-top: 8px; font-size: 13px; color: #666; }
    </style>
</head>
<body>
<div class="container">
    <h1>📊 টার্গেট বনাম অ্যাচিভমেন্ট রিপোর্ট</h1>
    <p style="text-align:right;"><a href="/logout" style="font-size:13px; color:#666;">🔓 লগআউট</a></p>

    <div class="card">
        <h3>📁 এক্সেল ফাইল থেকে আপলোড করুন</h3>
        <p style="font-size:13px; color:#666;">
            এক্সেল ফাইলের গঠন এমন হতে হবে —<br>
            <b>সারি ১:</b> A1 ঘরে একটা লেবেল (যেমন "CLP Name"), B1 ঘরে তার মান (যেমন "Dosti JULY 2026")<br>
            <b>সারি ২:</b> কলাম হেডার — Town Name, Outlet Code, Outlet Name, Section Name, SR Name, FSE Name, MAX TGT, MIN TGT, ACH<br>
            <b>সারি ৩ থেকে:</b> আসল ডেটা<br>
            (GAP ও ACH% কলাম থাকলেও সমস্যা নেই, সেগুলো নিজে থেকে হিসাব করা হয়)
        </p>
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for m in messages %}
                <p style="color: {{ '#27ae60' if 'সফলভাবে' in m else '#e74c3c' }}; font-weight:bold;">{{ m }}</p>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST" action="/upload" enctype="multipart/form-data">
            <input type="file" name="excel_file" accept=".xlsx,.xls" required>
            <button type="submit">আপলোড করুন</button>
        </form>
    </div>

    <div class="card">
        <h3>ফিল্টার করুন</h3>
        <form method="GET" action="/">
            <div class="filter-bar">
                <div><label>{{ clp_label }}</label>
                    <select name="clp">
                        <option value="">সব</option>
                        {% for c in clp_values %}
                        <option value="{{ c }}" {{ 'selected' if c == filters.clp }}>{{ c }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div><label>Town Name</label>
                    <select name="town">
                        <option value="">সব</option>
                        {% for t in towns %}
                        <option value="{{ t }}" {{ 'selected' if t == filters.town }}>{{ t }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div><label>Section Name</label>
                    <select name="section">
                        <option value="">সব</option>
                        {% for s in sections %}
                        <option value="{{ s }}" {{ 'selected' if s == filters.section }}>{{ s }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div><label>SR Name</label>
                    <select name="sr_name">
                        <option value="">সব</option>
                        {% for s in sr_names %}
                        <option value="{{ s }}" {{ 'selected' if s == filters.sr_name }}>{{ s }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div><label>FSE Name</label>
                    <select name="fse_name">
                        <option value="">সব</option>
                        {% for f in fse_names %}
                        <option value="{{ f }}" {{ 'selected' if f == filters.fse_name }}>{{ f }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div><button type="submit">ফিল্টার করুন</button></div>
            </div>
        </form>
        <a class="clear-link" href="/">✕ ফিল্টার মুছুন</a>
    </div>

    <div class="card">
        <h3>রিপোর্ট ({{ rows|length }} টি এন্ট্রি)</h3>
        {% if rows %}
        <table>
            <tr>
                <th>{{ clp_label }}</th><th>Town</th><th>Outlet Code</th><th>Outlet Name</th><th>Section</th>
                <th>SR</th><th>FSE</th><th>MAX TGT</th><th>MIN TGT</th><th>ACH</th>
                <th>GAP</th><th>ACH %</th><th></th>
            </tr>
            {% for r in rows %}
            <tr>
                <td>{{ r.extra_value }}</td>
                <td>{{ r.town }}</td>
                <td>{{ r.outlet_code }}</td>
                <td>{{ r.outlet_name }}</td>
                <td>{{ r.section }}</td>
                <td>{{ r.sr_name }}</td>
                <td>{{ r.fse_name }}</td>
                <td>{{ "{:,.0f}".format(r.max_tgt) }}</td>
                <td>{{ "{:,.0f}".format(r.min_tgt) }}</td>
                <td>{{ "{:,.0f}".format(r.ach) }}</td>
                <td>{{ "{:,.0f}".format(r.gap) }}</td>
                <td class="{{ 'ach-good' if r.ach_pct >= 100 else 'ach-bad' }}">{{ r.ach_pct }}%</td>
                <td><a class="delete-link" href="/delete/{{ r.id }}">🗑</a></td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
        <p class="empty">কোনো এন্ট্রি নেই।</p>
        {% endif %}
    </div>
</div>
</body>
</html>
"""


def enrich(r):
    """GAP এবং ACH% হিসাব করে ডিকশনারিতে যোগ করে দেয়।"""
    r = dict(r)
    r["gap"] = r["min_tgt"] - r["ach"]
    r["ach_pct"] = round((r["ach"] / r["min_tgt"] * 100), 1) if r["min_tgt"] else 0
    return r


@app.route("/")
def home():
    town = request.args.get("town", "")
    section = request.args.get("section", "")
    sr_name = request.args.get("sr_name", "")
    fse_name = request.args.get("fse_name", "")
    clp = request.args.get("clp", "")

    filtered = reports
    if clp:
        filtered = [r for r in filtered if r.get("extra_value") == clp]
    if town:
        filtered = [r for r in filtered if r["town"] == town]
    if section:
        filtered = [r for r in filtered if r["section"] == section]
    if sr_name:
        filtered = [r for r in filtered if r["sr_name"] == sr_name]
    if fse_name:
        filtered = [r for r in filtered if r["fse_name"] == fse_name]

    rows = [enrich(r) for r in filtered]

    # সবশেষ আপলোড হওয়া ফাইলের A1 লেবেলটাকে ফিল্টারের নাম হিসেবে দেখানো হচ্ছে
    clp_label = reports[-1]["extra_label"] if reports and reports[-1].get("extra_label") else "CLP Name"

    return render_template_string(
        PAGE,
        rows=rows,
        towns=sorted({r["town"] for r in reports}),
        sections=sorted({r["section"] for r in reports}),
        sr_names=sorted({r["sr_name"] for r in reports}),
        fse_names=sorted({r["fse_name"] for r in reports}),
        clp_values=sorted({r["extra_value"] for r in reports if r.get("extra_value")}),
        clp_label=clp_label,
        filters={"town": town, "section": section, "sr_name": sr_name, "fse_name": fse_name, "clp": clp},
    )


# এক্সেলের কলাম নাম -> আমাদের ডেটার ফিল্ড নাম
COLUMN_MAP = {
    "town name": "town",
    "outlet code": "outlet_code",
    "outlet name": "outlet_name",
    "section name": "section",
    "sr name": "sr_name",
    "fse name": "fse_name",
    "max tgt": "max_tgt",
    "min tgt": "min_tgt",
    "ach": "ach",
}


def to_number(value):
    """এক্সেলের সেল থেকে সংখ্যা বের করে (কমা থাকলেও, যেমন '14,528')।"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def process_sheet(sheet, existing_by_key, new_id):
    """একটা শীট পড়ে এন্ট্রি যোগ/আপডেট করে। রিটার্ন করে (updated_count, added_count, new_id, error_message)।"""
    rows_iter = sheet.iter_rows(values_only=True)

    # সারি ১: A1 = ফিল্টারের লেবেল (যেমন "CLP Name"), B1 = তার মান (যেমন "Dosti JULY 2026")
    info_row = next(rows_iter, None)
    if not info_row or len(info_row) < 2:
        return 0, 0, new_id, f"শীট '{sheet.title}': প্রথম সারিতে A1 ও B1 ঘরে তথ্য পাওয়া যায়নি, বাদ দেওয়া হলো।"
    extra_label = str(info_row[0] or "").strip() or "CLP Name"
    extra_value = str(info_row[1] or "").strip()
    if not extra_value:
        return 0, 0, new_id, f"শীট '{sheet.title}': B1 ঘরে কোনো মান পাওয়া যায়নি, বাদ দেওয়া হলো।"

    # সারি ২: আসল কলাম হেডার
    header_row = next(rows_iter, None)
    if not header_row:
        return 0, 0, new_id, f"শীট '{sheet.title}': ২য় সারিতে কলাম হেডার পাওয়া যায়নি, বাদ দেওয়া হলো।"

    header_index = {}
    for idx, col_name in enumerate(header_row):
        if col_name:
            key = str(col_name).strip().lower()
            if key in COLUMN_MAP:
                header_index[COLUMN_MAP[key]] = idx

    required_fields = ["town", "outlet_code", "outlet_name", "section", "sr_name", "fse_name", "max_tgt", "min_tgt", "ach"]
    missing = [f for f in required_fields if f not in header_index]
    if missing:
        return 0, 0, new_id, f"শীট '{sheet.title}': এই কলামগুলো পাওয়া যায়নি ({', '.join(missing)}), বাদ দেওয়া হলো।"

    updated_count = 0
    added_count = 0

    # সারি ৩ থেকে আসল ডেটা শুরু হয়
    for row in rows_iter:
        if row is None or all(cell is None for cell in row):
            continue  # খালি সারি বাদ দেওয়া হচ্ছে

        outlet_code = str(row[header_index["outlet_code"]] or "").strip()
        if not outlet_code:
            continue  # Outlet Code ছাড়া সারি বাদ দেওয়া হচ্ছে

        new_values = {
            "town": str(row[header_index["town"]] or "").strip(),
            "outlet_code": outlet_code,
            "outlet_name": str(row[header_index["outlet_name"]] or "").strip(),
            "section": str(row[header_index["section"]] or "").strip(),
            "sr_name": str(row[header_index["sr_name"]] or "").strip(),
            "fse_name": str(row[header_index["fse_name"]] or "").strip(),
            "max_tgt": to_number(row[header_index["max_tgt"]]),
            "min_tgt": to_number(row[header_index["min_tgt"]]),
            "ach": to_number(row[header_index["ach"]]),
            "extra_label": extra_label,
            "extra_value": extra_value,
        }

        key = (outlet_code, extra_value)
        if key in existing_by_key:
            existing_by_key[key].update(new_values)
            updated_count += 1
        else:
            new_values["id"] = new_id
            reports.append(new_values)
            existing_by_key[key] = new_values
            new_id += 1
            added_count += 1

    return updated_count, added_count, new_id, None


@app.route("/upload", methods=["POST"])
def upload_excel():
    file = request.files.get("excel_file")
    if not file or file.filename == "":
        flash("কোনো ফাইল বাছাই করা হয়নি।")
        return redirect(url_for("home"))

    try:
        workbook = openpyxl.load_workbook(file, data_only=True)
    except Exception:
        flash("ফাইলটি পড়া যায়নি। এটি একটি সঠিক .xlsx ফাইল কিনা যাচাই করুন।")
        return redirect(url_for("home"))

    existing_by_key = {(r["outlet_code"], r.get("extra_value")): r for r in reports}
    new_id = (max([r["id"] for r in reports], default=0)) + 1

    total_updated = 0
    total_added = 0
    sheet_errors = []
    processed_sheets = 0

    # ফাইলের প্রতিটা শীট আলাদাভাবে প্রসেস করা হচ্ছে
    for sheet in workbook.worksheets:
        updated, added, new_id, error = process_sheet(sheet, existing_by_key, new_id)
        if error:
            sheet_errors.append(error)
            continue
        total_updated += updated
        total_added += added
        processed_sheets += 1

    save_reports(reports)

    summary = f"মোট {processed_sheets} টি শীট থেকে {total_updated} টি এন্ট্রি আপডেট এবং {total_added} টি নতুন এন্ট্রি যোগ হয়েছে।"
    flash(summary)
    for err in sheet_errors:
        flash(err)

    return redirect(url_for("home"))


@app.route("/delete/<int:report_id>")
def delete_report(report_id):
    global reports
    reports = [r for r in reports if r["id"] != report_id]
    save_reports(reports)
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)
