import json
import os
import time
from flask import Flask, render_template_string, request, redirect, url_for, flash, session
import openpyxl

app = Flask(__name__)
app.secret_key = "dev-secret-key"  # সেশন ও flash মেসেজের জন্য দরকার — পাবলিশ করার আগে এটা বদলে ফেলুন

# দুই ধরনের পাসওয়ার্ড — একটা অ্যাডমিনের জন্য, একটা সাধারণ ভিউয়ারের জন্য
# চাইলে এখানে সরাসরি বদলাতে পারেন, অথবা Render-এ Environment Variable হিসেবে সেট করতে পারেন (বেশি নিরাপদ)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
VIEWER_PASSWORD = os.environ.get("VIEWER_PASSWORD", "view123")

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
        entered = request.form.get("password")
        if entered == ADMIN_PASSWORD:
            session["role"] = "admin"
            return redirect(url_for("home"))
        elif entered == VIEWER_PASSWORD:
            session["role"] = "viewer"
            return redirect(url_for("home"))
        error = "পাসওয়ার্ড ভুল হয়েছে, আবার চেষ্টা করুন।"
    return render_template_string(LOGIN_PAGE, error=error)


@app.route("/logout")
def logout():
    session.pop("role", None)
    return redirect(url_for("login"))


@app.before_request
def require_login():
    # লগইন ও স্ট্যাটিক ফাইল ছাড়া বাকি সব পেজের আগে লগইন চেক করা হচ্ছে
    if request.endpoint in ("login", "static") or session.get("role") in ("admin", "viewer"):
        return None
    return redirect(url_for("login"))


@app.before_request
def auto_refresh():
    # হোমপেজ খোলার সময় ডাটাবেস থেকে সর্বশেষ ডেটা নিয়ে আসা হয় (প্রতি ৩০ সেকেন্ডে একবার)
    if request.endpoint == "home":
        refresh_reports()


def require_admin():
    """অ্যাডমিন-অনলি রুটের শুরুতে কল করতে হবে। অ্যাডমিন না হলে হোমপেজে পাঠিয়ে দেয়।"""
    if session.get("role") != "admin":
        flash("এই কাজটি করার অনুমতি নেই — শুধু অ্যাডমিন পারবেন।")
        return redirect(url_for("home"))
    return None


DATABASE_URL = os.environ.get("DATABASE_URL")

# ডাটাবেস থেকে ডেটা কতক্ষণ মেমোরিতে রাখা হবে (সেকেন্ড) — এরপর আবার ডাটাবেস থেকে নতুন করে পড়া হয়
CACHE_SECONDS = 30

reports = []            # মেমোরিতে থাকা বর্তমান রিপোর্ট ডেটা
db_loaded_ok = False    # ডাটাবেস থেকে সফলভাবে ডেটা পড়া গেছে কিনা
last_db_error = None    # সর্বশেষ ডাটাবেস এরর (থাকলে)
last_load_time = 0      # সর্বশেষ কখন ডাটাবেস থেকে পড়া হয়েছে


def get_db_connection():
    """Supabase (PostgreSQL) ডাটাবেসের সাথে একটা নতুন সংযোগ তৈরি করে।"""
    import psycopg2
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)


def refresh_reports(force=False):
    """
    ডাটাবেস থেকে রিপোর্ট পড়ে মেমোরিতে আপডেট করে। সফল হলে True, ব্যর্থ হলে False।
    ব্যর্থ হলে মেমোরির পুরনো ডেটা অক্ষত থাকে (খালি করে ফেলা হয় না)।
    """
    global reports, db_loaded_ok, last_db_error, last_load_time

    if not DATABASE_URL:
        last_db_error = "DATABASE_URL সেট করা নেই — ডেটা স্থায়ীভাবে সেভ হবে না।"
        return False

    if not force and db_loaded_ok and (time.time() - last_load_time) < CACHE_SECONDS:
        return True

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # টেবিল না থাকলে নিজে থেকেই তৈরি করে নেবে
        cur.execute("CREATE TABLE IF NOT EXISTS app_data (key text PRIMARY KEY, value text)")
        conn.commit()
        cur.execute("SELECT value FROM app_data WHERE key = %s", ("reports",))
        row = cur.fetchone()
        cur.close()
        conn.close()

        reports = json.loads(row[0]) if row and row[0] else []
        db_loaded_ok = True
        last_db_error = None
        last_load_time = time.time()
        return True
    except Exception as e:
        last_db_error = str(e)
        print("ডাটাবেস থেকে লোড করতে সমস্যা হয়েছে:", e)
        return False


def save_reports(data):
    """সব রিপোর্ট ডাটাবেসে সেভ করে। সফল হলে True, ব্যর্থ হলে False রিটার্ন করে।"""
    global last_db_error, last_load_time

    if not DATABASE_URL:
        last_db_error = "DATABASE_URL সেট করা নেই — ডেটা স্থায়ীভাবে সেভ হবে না।"
        return False

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS app_data (key text PRIMARY KEY, value text)")
        cur.execute(
            """
            INSERT INTO app_data (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            ("reports", json.dumps(data, ensure_ascii=False)),
        )
        conn.commit()
        cur.close()
        conn.close()
        last_db_error = None
        last_load_time = time.time()
        return True
    except Exception as e:
        last_db_error = str(e)
        print("ডাটাবেসে সেভ করতে সমস্যা হয়েছে:", e)
        return False


# অ্যাপ চালু হওয়ার সময় একবার ডাটাবেস থেকে ডেটা লোড করা হচ্ছে
refresh_reports(force=True)

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
        .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; }
        .summary-box { background: #f8f9fb; border-radius: 8px; padding: 15px; text-align: center; }
        .summary-box .label { font-size: 12px; color: #888; margin-bottom: 5px; }
        .summary-box .value { font-size: 22px; font-weight: bold; color: #2c3e50; }
        .summary-box.pct-good .value { color: #27ae60; }
        .summary-box.pct-bad .value { color: #e74c3c; }
        .chart-wrap { margin-top: 10px; }
        .bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
        .bar-label { width: 220px; font-size: 13px; color: #333; text-align: right; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .bar-track { flex: 1; background: #eef1f5; border-radius: 4px; height: 22px; position: relative; overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
        .bar-fill.good { background: #27ae60; }
        .bar-fill.bad { background: #e74c3c; }
        .bar-value { width: 60px; font-size: 13px; font-weight: bold; text-align: left; flex-shrink: 0; }
        .program-list { display: flex; flex-wrap: wrap; gap: 8px; }
        .program-chip { padding: 7px 14px; border-radius: 20px; background: #eef2f7; color: #2c3e50; text-decoration: none; font-size: 13px; border: 1px solid #dde3ea; }
        .program-chip:hover { background: #dbe6f5; }
        .program-chip.active { background: #3498db; color: white; border-color: #3498db; }
    </style>
</head>
<body>
<div class="container">
    <h1>📊 টার্গেট বনাম অ্যাচিভমেন্ট রিপোর্ট</h1>
    <p style="text-align:right; font-size:13px; color:#888;">
        {{ 'অ্যাডমিন হিসেবে লগইন আছেন' if is_admin else 'ভিউয়ার হিসেবে লগইন আছেন' }}
        {% if is_admin %}&nbsp;|&nbsp; <a href="/status" style="color:#666;">🩺 ডাটাবেস স্ট্যাটাস</a>{% endif %}
        &nbsp;|&nbsp; <a href="/logout" style="color:#666;">🔓 লগআউট</a>
    </p>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
        <div class="card">
            {% for cat, m in messages %}
            <p style="color: {{ '#27ae60' if cat == 'ok' else '#e74c3c' }}; font-weight:bold; margin:5px 0;">{{ m }}</p>
            {% endfor %}
        </div>
        {% endif %}
    {% endwith %}

    {% if is_admin and db_warning %}
    <div class="card" style="border-left: 5px solid #e74c3c;">
        <p style="color:#e74c3c; font-weight:bold; margin:0;">⚠️ ডাটাবেস সমস্যা: {{ db_warning }}</p>
        <p style="font-size:13px; color:#666; margin:6px 0 0;">এই অবস্থায় ডেটা স্থায়ীভাবে সেভ নাও হতে পারে। বিস্তারিত দেখতে <a href="/status">স্ট্যাটাস পেজ</a> খুলুন।</p>
    </div>
    {% endif %}

    {% if is_admin %}
    <div class="card">
        <h3>📁 এক্সেল ফাইল থেকে আপলোড করুন</h3>
        <p style="font-size:13px; color:#666;">
            এক্সেল ফাইলের গঠন এমন হতে হবে —<br>
            <b>সারি ১:</b> A1 ঘরে একটা লেবেল (যেমন "CLP Name"), B1 ঘরে তার মান (যেমন "Dosti JULY 2026")<br>
            <b>সারি ২:</b> কলাম হেডার — Town Name, Outlet Code, Outlet Name, Section Name, SR Name, FSE Name, MAX TGT, MIN TGT, ACH<br>
            <b>সারি ৩ থেকে:</b> আসল ডেটা<br>
            (GAP ও ACH% কলাম থাকলেও সমস্যা নেই, সেগুলো নিজে থেকে হিসাব করা হয়)
        </p>
        <form method="POST" action="/upload" enctype="multipart/form-data">
            <input type="file" name="excel_file" accept=".xlsx,.xls" required>
            <button type="submit">আপলোড করুন</button>
        </form>
        <form method="POST" action="/delete-all" style="margin-top:15px;"
              onsubmit="return confirm('আপনি কি নিশ্চিত? এতে সমস্ত রিপোর্ট ডেটা স্থায়ীভাবে মুছে যাবে!');">
            <button type="submit" style="background:#e74c3c;">🗑 সব পুরোনো ডেটা মুছে ফেলুন</button>
        </form>
    </div>
    {% endif %}

    <div class="card">
        <h3>📈 সারসংক্ষেপ {% if filters.town or filters.section or filters.sr_name or filters.fse_name or filters.clp %}(বর্তমান ফিল্টার অনুযায়ী){% endif %}</h3>
        <div class="summary-grid">
            <div class="summary-box">
                <div class="label">মোট আউটলেট</div>
                <div class="value">{{ summary.count }}</div>
            </div>
            <div class="summary-box">
                <div class="label">মোট MAX TGT</div>
                <div class="value">{{ "{:,.0f}".format(summary.max_tgt) }}</div>
            </div>
            <div class="summary-box">
                <div class="label">মোট MIN TGT</div>
                <div class="value">{{ "{:,.0f}".format(summary.min_tgt) }}</div>
            </div>
            <div class="summary-box">
                <div class="label">মোট ACH</div>
                <div class="value">{{ "{:,.0f}".format(summary.ach) }}</div>
            </div>
            <div class="summary-box">
                <div class="label">মোট GAP</div>
                <div class="value">{{ "{:,.0f}".format(summary.gap) }}</div>
            </div>
            <div class="summary-box {{ 'pct-good' if summary.ach_pct >= 100 else 'pct-bad' }}">
                <div class="label">সার্বিক ACH %</div>
                <div class="value">{{ summary.ach_pct }}%</div>
            </div>
        </div>
    </div>

    {% if program_links %}
    <div class="card">
        <h3>📋 প্রোগ্রাম লিস্ট ({{ clp_label }})</h3>
        <div class="program-list">
            <a class="program-chip {{ 'active' if not filters.clp }}" href="{{ clear_clp_url }}">সব প্রোগ্রাম</a>
            {% for p in program_links %}
            <a class="program-chip {{ 'active' if p.active }}" href="{{ p.url }}">{{ p.value }}</a>
            {% endfor %}
        </div>
    </div>
    {% endif %}

    {% if chart_data %}
    <div class="card">
        <h3>🧑‍💼 SR-ভিত্তিক ACH % তুলনা (ভালো থেকে খারাপ ক্রমে)</h3>
        <div class="chart-wrap">
            {% for item in chart_data %}
            <div class="bar-row">
                <div class="bar-label" title="{{ item.label }}">{{ item.label }}</div>
                <div class="bar-track">
                    <div class="bar-fill {{ 'good' if item.value >= 100 else 'bad' }}" style="width: {{ item.width_pct }}%;"></div>
                </div>
                <div class="bar-value">{{ item.value }}%</div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}

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
                <th>GAP</th><th>ACH %</th>{% if is_admin %}<th></th>{% endif %}
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
                {% if is_admin %}<td><a class="delete-link" href="/delete/{{ r.id }}">🗑</a></td>{% endif %}
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

    # সারসংক্ষেপ (সামারি) হিসাব করা হচ্ছে — বর্তমান ফিল্টার করা রো-গুলোর ওপর ভিত্তি করে
    total_max = sum(r["max_tgt"] for r in rows)
    total_min = sum(r["min_tgt"] for r in rows)
    total_ach = sum(r["ach"] for r in rows)
    summary = {
        "count": len(rows),
        "max_tgt": total_max,
        "min_tgt": total_min,
        "ach": total_ach,
        "gap": total_min - total_ach,
        "ach_pct": round((total_ach / total_min * 100), 1) if total_min else 0,
    }

    # SR অনুযায়ী গ্রুপ করে ACH% হিসাব করা হচ্ছে (চার্টের জন্য) — সবচেয়ে ভালো থেকে খারাপ ক্রমে সাজানো
    sr_totals = {}
    for r in rows:
        s = r["sr_name"]
        if s not in sr_totals:
            sr_totals[s] = {"min_tgt": 0, "ach": 0}
        sr_totals[s]["min_tgt"] += r["min_tgt"]
        sr_totals[s]["ach"] += r["ach"]

    sr_pct_list = [
        (s, round((sr_totals[s]["ach"] / sr_totals[s]["min_tgt"] * 100), 1) if sr_totals[s]["min_tgt"] else 0)
        for s in sr_totals
    ]
    sr_pct_list.sort(key=lambda x: x[1], reverse=True)  # ভালো পারফরম্যান্স আগে

    # প্রতিটা বারের প্রস্থ (%) হিসাব করা হচ্ছে — সবচেয়ে বেশি মান বা ১০০%, যেটা বড় সেটার সাপেক্ষে
    scale_max = max([p for _, p in sr_pct_list] + [100]) if sr_pct_list else 100
    chart_data = [
        {"label": s, "value": p, "width_pct": round(min(p / scale_max * 100, 100), 1)}
        for s, p in sr_pct_list
    ]

    # প্রোগ্রাম (CLP) লিস্ট — ক্লিক করলে সেই প্রোগ্রামের ডেটা অনুযায়ী পুরো পেজ ফিল্টার হবে
    from urllib.parse import urlencode
    all_clp_values = sorted({r["extra_value"] for r in reports if r.get("extra_value")})
    program_links = []
    for c in all_clp_values:
        args = {"town": town, "section": section, "sr_name": sr_name, "fse_name": fse_name, "clp": c}
        args = {k: v for k, v in args.items() if v}
        program_links.append({"value": c, "url": "/?" + urlencode(args), "active": c == clp})

    # "সব প্রোগ্রাম" লিংক — clp ফিল্টার সরিয়ে বাকি ফিল্টার রেখে দেখাবে
    clear_clp_args = {k: v for k, v in {"town": town, "section": section, "sr_name": sr_name, "fse_name": fse_name}.items() if v}
    clear_clp_url = "/?" + urlencode(clear_clp_args) if clear_clp_args else "/"

    return render_template_string(
        PAGE,
        rows=rows,
        towns=sorted({r["town"] for r in reports}),
        sections=sorted({r["section"] for r in reports}),
        sr_names=sorted({r["sr_name"] for r in reports}),
        fse_names=sorted({r["fse_name"] for r in reports}),
        clp_values=all_clp_values,
        clp_label=clp_label,
        program_links=program_links,
        clear_clp_url=clear_clp_url,
        filters={"town": town, "section": section, "sr_name": sr_name, "fse_name": fse_name, "clp": clp},
        is_admin=(session.get("role") == "admin"),
        db_warning=last_db_error,
        summary=summary,
        chart_data=chart_data,
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
    guard = require_admin()
    if guard:
        return guard

    file = request.files.get("excel_file")
    if not file or file.filename == "":
        flash("কোনো ফাইল বাছাই করা হয়নি।")
        return redirect(url_for("home"))

    # আপলোডের আগে ডাটাবেস থেকে সর্বশেষ ডেটা আনা হচ্ছে — না পারলে আপলোড বাতিল (পুরনো ডেটা সুরক্ষিত রাখতে)
    if not refresh_reports(force=True):
        flash(f"⚠️ ডাটাবেসের সাথে সংযোগ করা যায়নি, তাই আপলোড বাতিল করা হয়েছে। কারণ: {last_db_error}")
        return redirect(url_for("home"))

    try:
        workbook = openpyxl.load_workbook(file, data_only=True, read_only=True)
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

    workbook.close()  # read_only মোডে ফাইল বন্ধ করে মেমোরি খালি করে দেওয়া হচ্ছে

    if save_reports(reports):
        flash(f"মোট {processed_sheets} টি শীট থেকে {total_updated} টি এন্ট্রি আপডেট এবং {total_added} টি নতুন এন্ট্রি যোগ হয়েছে এবং ডাটাবেসে সেভ হয়েছে।", "ok")
    else:
        flash(f"❌ ডেটা ডাটাবেসে সেভ হয়নি! সার্ভার রিস্টার্ট হলে এই ডেটা হারিয়ে যাবে। কারণ: {last_db_error}")
    for err in sheet_errors:
        flash(err)

    return redirect(url_for("home"))


@app.route("/delete/<int:report_id>")
def delete_report(report_id):
    guard = require_admin()
    if guard:
        return guard

    if not refresh_reports(force=True):
        flash(f"⚠️ ডাটাবেসের সাথে সংযোগ করা যায়নি, তাই মোছা হয়নি। কারণ: {last_db_error}")
        return redirect(url_for("home"))

    global reports
    reports = [r for r in reports if r["id"] != report_id]
    if save_reports(reports):
        flash("এন্ট্রি মুছে ফেলা হয়েছে।", "ok")
    else:
        flash(f"❌ ডাটাবেসে সেভ হয়নি। কারণ: {last_db_error}")
    return redirect(url_for("home"))


@app.route("/delete-all", methods=["POST"])
def delete_all_reports():
    guard = require_admin()
    if guard:
        return guard

    if not refresh_reports(force=True):
        flash(f"⚠️ ডাটাবেসের সাথে সংযোগ করা যায়নি, তাই মোছা হয়নি। কারণ: {last_db_error}")
        return redirect(url_for("home"))

    global reports
    reports = []
    if save_reports(reports):
        flash("সব পুরোনো ডেটা মুছে ফেলা হয়েছে।", "ok")
    else:
        flash(f"❌ ডাটাবেসে সেভ হয়নি। কারণ: {last_db_error}")
    return redirect(url_for("home"))


STATUS_PAGE = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <title>ডাটাবেস স্ট্যাটাস</title>
    <style>
        body { font-family: Arial, sans-serif; background: #f4f4f9; padding: 30px; }
        .box { max-width: 700px; margin: 0 auto; background: white; padding: 25px 30px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.08); }
        h2 { color: #2c3e50; margin-top: 0; }
        td { padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 14px; vertical-align: top; }
        td:first-child { color: #666; width: 45%; }
        .ok { color: #27ae60; font-weight: bold; }
        .bad { color: #e74c3c; font-weight: bold; word-break: break-word; }
    </style>
</head>
<body>
<div class="box">
    <h2>🩺 ডাটাবেস স্ট্যাটাস</h2>
    <table>
        {% for label, value, good in rows %}
        <tr><td>{{ label }}</td><td class="{{ 'ok' if good else 'bad' }}">{{ value }}</td></tr>
        {% endfor %}
    </table>
    <p><a href="/">← হোমপেজে ফিরুন</a></p>
</div>
</body>
</html>
"""


@app.route("/status")
def status():
    guard = require_admin()
    if guard:
        return guard

    from urllib.parse import urlparse
    rows = []
    has_url = bool(DATABASE_URL)
    rows.append(("DATABASE_URL সেট আছে?", "হ্যাঁ" if has_url else "না — Render-এ Environment Variable যোগ করুন", has_url))

    if has_url:
        try:
            host = urlparse(DATABASE_URL).hostname
        except Exception:
            host = "(পড়া যায়নি)"
        rows.append(("ডাটাবেস হোস্ট", host or "(পড়া যায়নি)", True))

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS app_data (key text PRIMARY KEY, value text)")
            conn.commit()
            cur.execute("SELECT value FROM app_data WHERE key = %s", ("reports",))
            row = cur.fetchone()
            cur.close()
            conn.close()
            stored = json.loads(row[0]) if row and row[0] else []
            rows.append(("ডাটাবেসে সংযোগ", "সফল ✅", True))
            rows.append(("ডাটাবেসে সেভ করা এন্ট্রি", str(len(stored)), True))
            size_kb = round(len(row[0]) / 1024, 1) if row and row[0] else 0
            rows.append(("ডাটাবেসে সেভ করা ডেটার আকার", f"{size_kb} KB", True))
        except Exception as e:
            rows.append(("ডাটাবেসে সংযোগ", f"ব্যর্থ ❌ — {e}", False))

    rows.append(("এই মুহূর্তে মেমোরিতে থাকা এন্ট্রি", str(len(reports)), True))
    rows.append(("সর্বশেষ ডাটাবেস এরর", last_db_error or "নেই", last_db_error is None))

    return render_template_string(STATUS_PAGE, rows=rows)


if __name__ == "__main__":
    app.run(debug=True)
