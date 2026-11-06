"""
Bosaso Homes - Real Estate & Land Marketplace (Flask + SQLite)

Local:   python app.py                 -> http://127.0.0.1:5000
Render:  gunicorn app:app --workers 1 --threads 4   (see render.yaml)
"""
import os
import re
import secrets
import sqlite3
import time
import uuid
from collections import defaultdict, deque
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, send_from_directory, session,
                   url_for)
from PIL import Image, ImageOps
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from i18n import JS_KEYS, LANGS, tr

# --------------------------------------------------------------------------
# Configuration (everything sensitive comes from environment variables)
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_PROD = bool(os.environ.get("RENDER"))          # Render sets RENDER=true

# DATA_DIR holds the database + uploaded photos.
# On Render, point it at the persistent disk mount path (e.g. /var/data).
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
DB_PATH = os.path.join(DATA_DIR, "bosaso_realestate.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

BRAND_NAME = os.environ.get("BRAND_NAME", "Bosaso Homes")
ADMIN_WHATSAPP = re.sub(r"\D", "", os.environ.get("ADMIN_WHATSAPP", ""))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    MAX_CONTENT_LENGTH=24 * 1024 * 1024,           # max request size (24 MB)
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PROD,
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,  # 30 days
)
# Render terminates HTTPS in front of us; trust its forwarded headers.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

BOSASO_CENTER = (11.2842, 49.1816)
LAT_RANGE = (11.0, 11.6)
LNG_RANGE = (48.9, 49.5)

TYPES = ("Rent", "Sale")
CATEGORIES = ("House", "Land", "Apartment")
NEIGHBORHOODS = ["Bander Ziada", "Baalade", "Suweyto", "Horseed", "Shabelle",
                 "Waaberi", "Galkacyo Road", "Other"]
STATUSES = ("pending", "approved", "rejected", "closed")

MAX_IMAGES = 6
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    phone         TEXT,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS properties (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    description     TEXT,
    price           REAL    NOT NULL,
    type            TEXT    NOT NULL CHECK (type IN ('Rent','Sale')),
    category        TEXT    NOT NULL CHECK (category IN ('House','Land','Apartment')),
    neighborhood    TEXT    NOT NULL,
    latitude        REAL    NOT NULL,
    longitude       REAL    NOT NULL,
    whatsapp_number TEXT    NOT NULL,
    is_verified     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    owner_id        INTEGER,
    status          TEXT    NOT NULL DEFAULT 'approved'
                    CHECK (status IN ('pending','approved','rejected','closed'))
);

CREATE TABLE IF NOT EXISTS property_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL,
    image_url   TEXT    NOT NULL,
    FOREIGN KEY (property_id) REFERENCES properties (id) ON DELETE CASCADE
);
"""

SAMPLE_PROPERTIES = [
    {
        "title": "Modern 4-Bedroom Villa in Bander Ziada",
        "description": "Spacious villa with a walled compound, 3 bathrooms, "
                       "generator room and water tank. Quiet street, close to "
                       "the main road and the port.",
        "price": 185000, "type": "Sale", "category": "House",
        "neighborhood": "Bander Ziada", "latitude": 11.2905, "longitude": 49.1960,
        "whatsapp_number": "252907000001", "is_verified": 1,
        "images": ["https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=800"],
    },
    {
        "title": "3-Bedroom House for Rent in Baalade",
        "description": "Clean family house with tiled floors, kitchen, "
                       "2 bathrooms and a small yard. Available immediately.",
        "price": 350, "type": "Rent", "category": "House",
        "neighborhood": "Baalade", "latitude": 11.2788, "longitude": 49.1792,
        "whatsapp_number": "252907000002", "is_verified": 1,
        "images": ["https://images.unsplash.com/photo-1568605114967-8130f3a36994?w=800"],
    },
    {
        "title": "600 m² Residential Land in Suweyto",
        "description": "Flat, ready-to-build plot with clear ownership "
                       "documents. Close to the main road. Ideal for a family "
                       "home or small apartment block.",
        "price": 42000, "type": "Sale", "category": "Land",
        "neighborhood": "Suweyto", "latitude": 11.2660, "longitude": 49.1715,
        "whatsapp_number": "252907000003", "is_verified": 0,
        "images": ["https://images.unsplash.com/photo-1500382017468-9049fed747ef?w=800"],
    },
    {
        "title": "2-Bedroom Apartment near the Port",
        "description": "Second-floor apartment with sea breeze, balcony, "
                       "reliable water supply and secure entrance. "
                       "Perfect for small families or professionals.",
        "price": 280, "type": "Rent", "category": "Apartment",
        "neighborhood": "Bander Ziada", "latitude": 11.2872, "longitude": 49.1858,
        "whatsapp_number": "252907000004", "is_verified": 1,
        "images": ["https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800"],
    },
]


def _migrate(db):
    """Upgrade a database created by the first MVP version."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(properties)")}
    if "owner_id" not in cols:
        db.execute("ALTER TABLE properties ADD COLUMN owner_id INTEGER")
    if "status" not in cols:
        db.execute("ALTER TABLE properties ADD COLUMN status TEXT NOT NULL DEFAULT 'approved'")


def _ensure_admin(db):
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    explicit = bool(password)
    if not IS_PROD and not password:      # local development convenience only
        email = email or "admin@bosaso.local"
        password = "admin123"
        print("[dev] Admin login -> admin@bosaso.local / admin123")
    if not email or not password:
        print("[warn] ADMIN_EMAIL / ADMIN_PASSWORD not set: no admin account created.")
        return
    row = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    try:
        if row is None:
            db.execute(
                "INSERT INTO users (name, email, password_hash, is_admin) VALUES (?,?,?,1)",
                ("Admin", email, generate_password_hash(password)))
        else:
            db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (row[0],))
            if explicit:                  # env var is the source of truth
                db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                           (generate_password_hash(password), row[0]))
    except sqlite3.IntegrityError:
        pass


def init_db():
    with sqlite3.connect(DB_PATH, timeout=10) as db:
        db.executescript(SCHEMA)
        _migrate(db)
        _ensure_admin(db)
        count = db.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        if count == 0 and os.environ.get("SEED_SAMPLES", "1") != "0":
            for p in SAMPLE_PROPERTIES:
                cur = db.execute(
                    """INSERT INTO properties
                       (title, description, price, type, category, neighborhood,
                        latitude, longitude, whatsapp_number, is_verified, status)
                       VALUES (?,?,?,?,?,?,?,?,?,?, 'approved')""",
                    (p["title"], p["description"], p["price"], p["type"],
                     p["category"], p["neighborhood"], p["latitude"],
                     p["longitude"], p["whatsapp_number"], p["is_verified"]))
                for url in p["images"]:
                    db.execute("INSERT INTO property_images (property_id, image_url) VALUES (?,?)",
                               (cur.lastrowid, url))
            print(f"Seeded {len(SAMPLE_PROPERTIES)} sample properties.")


# --------------------------------------------------------------------------
# Language, CSRF, auth helpers
# --------------------------------------------------------------------------
def current_lang():
    lang = session.get("lang")
    if lang in LANGS:
        return lang
    return request.accept_languages.best_match(list(LANGS)) or "en"


def flash_t(key, category="error", **kw):
    flash(tr(current_lang(), key, **kw), category)


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.context_processor
def inject_globals():
    lang = current_lang()
    return dict(
        t=lambda key, **kw: tr(lang, key, **kw),
        lang=lang,
        brand=BRAND_NAME,
        current_user=g.get("user"),
        js_t={k: tr(lang, k) for k in JS_KEYS},
        admin_whatsapp=ADMIN_WHATSAPP,
        neighborhoods=NEIGHBORHOODS,
        center=BOSASO_CENTER,
    )


@app.before_request
def load_user_and_check_csrf():
    g.user = None
    if request.endpoint in (None, "static", "uploads"):
        return
    uid = session.get("user_id")
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if g.user is None:
            session.pop("user_id", None)
    if request.method == "POST":
        token = session.get("_csrf", "")
        sent = request.form.get("_csrf", "")
        if not token or not secrets.compare_digest(token, sent):
            abort(400)


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp


def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if g.user is None:
            flash_t("flash_need_login", "error")
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        if not g.user["is_admin"]:
            abort(403)
        return view(*a, **kw)
    return wrapper


_attempts = defaultdict(deque)


def rate_limited(key, limit=10, window=600):
    now = time.time()
    q = _attempts[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("dashboard")


# --------------------------------------------------------------------------
# Property helpers
# --------------------------------------------------------------------------
def clean_whatsapp(raw):
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def fetch_properties(where="", params=(), order="p.id DESC", limit=None):
    db = get_db()
    sql = ("SELECT p.*, u.name AS owner_name, u.email AS owner_email "
           "FROM properties p LEFT JOIN users u ON u.id = p.owner_id ")
    if where:
        sql += "WHERE " + where + " "
    sql += "ORDER BY " + order
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = db.execute(sql, params).fetchall()
    images = {}
    if rows:
        ids = [r["id"] for r in rows]
        marks = ",".join("?" * len(ids))
        for img in db.execute(
            f"SELECT id, property_id, image_url FROM property_images "
            f"WHERE property_id IN ({marks}) ORDER BY id", ids):
            images.setdefault(img["property_id"], []).append(
                {"id": img["id"], "url": img["image_url"]})
    result = []
    for r in rows:
        d = dict(r)
        d["is_verified"] = bool(d["is_verified"])
        d["image_list"] = images.get(r["id"], [])
        d["images"] = [i["url"] for i in d["image_list"]]
        result.append(d)
    return result


def get_property_or_404(pid):
    rows = fetch_properties("p.id = ?", (pid,))
    if not rows:
        abort(404)
    return rows[0]


def can_manage(prop):
    return g.user is not None and (g.user["is_admin"] or prop["owner_id"] == g.user["id"])


class ImageError(Exception):
    def __init__(self, key):
        super().__init__(key)
        self.key = key


def save_images(files):
    """Validate, resize and store uploads. Returns list of '/uploads/..' URLs."""
    saved = []
    try:
        for f in files:
            ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED_EXT:
                raise ImageError("e_images_type")
            try:
                img = Image.open(f.stream)
                img = ImageOps.exif_transpose(img).convert("RGB")
            except Exception:
                raise ImageError("e_images_bad")
            img.thumbnail((1400, 1400))
            name = uuid.uuid4().hex + ".jpg"
            img.save(os.path.join(UPLOAD_DIR, name), "JPEG", quality=82, optimize=True)
            saved.append("/uploads/" + name)
    except ImageError:
        for url in saved:
            remove_upload(url)
        raise
    return saved


def remove_upload(url):
    if url and url.startswith("/uploads/"):
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(url)))
        except OSError:
            pass


def parse_property_form(form, is_admin):
    errors, data = [], {}

    title = form.get("title", "").strip()
    if not title or len(title) > 120:
        errors.append("e_title")
    data["title"] = title

    desc = form.get("description", "").strip()
    if len(desc) > 2000:
        errors.append("e_desc_long")
    data["description"] = desc

    try:
        price = float(form.get("price", ""))
        if not 0 < price < 1e10:
            raise ValueError
    except ValueError:
        errors.append("e_price")
        price = None
    data["price"] = price

    if form.get("type") not in TYPES:
        errors.append("e_type")
    data["type"] = form.get("type")
    if form.get("category") not in CATEGORIES:
        errors.append("e_category")
    data["category"] = form.get("category")

    area = form.get("neighborhood", "").strip()
    if not area or len(area) > 60:
        errors.append("e_area")
    data["neighborhood"] = area

    try:
        lat, lng = float(form.get("latitude", "")), float(form.get("longitude", ""))
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LNG_RANGE[0] <= lng <= LNG_RANGE[1]):
            raise ValueError
    except ValueError:
        errors.append("e_coords")
        lat = lng = None
    data["latitude"], data["longitude"] = lat, lng

    wa = clean_whatsapp(form.get("whatsapp_number"))
    if not 8 <= len(wa) <= 15 or wa.startswith("0"):
        errors.append("e_whatsapp")
    data["whatsapp_number"] = wa

    data["is_verified"] = 1 if (is_admin and form.get("is_verified")) else None
    return data, errors


def _form_values(prop):
    price = prop["price"]
    return {
        "title": prop["title"], "description": prop["description"] or "",
        "price": int(price) if price == int(price) else price,
        "type": prop["type"], "category": prop["category"],
        "neighborhood": prop["neighborhood"], "latitude": prop["latitude"],
        "longitude": prop["longitude"], "whatsapp_number": prop["whatsapp_number"],
        "is_verified": "1" if prop["is_verified"] else "",
    }


# --------------------------------------------------------------------------
# Public pages + API
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/properties")
def api_properties():
    where, params = ["p.status = 'approved'"], []
    ptype = request.args.get("type", "").strip()
    if ptype in TYPES:
        where.append("p.type = ?")
        params.append(ptype)
    category = request.args.get("category", "").strip()
    if category in CATEGORIES:
        where.append("p.category = ?")
        params.append(category)
    area = request.args.get("neighborhood", "").strip()
    if area:
        where.append("p.neighborhood = ?")
        params.append(area)
    for key, op in (("min_price", ">="), ("max_price", "<=")):
        raw = request.args.get(key, "").strip()
        if raw:
            try:
                params.append(float(raw))
                where.append(f"p.price {op} ?")
            except ValueError:
                pass
    rows = fetch_properties(" AND ".join(where), params,
                            order="p.is_verified DESC, p.created_at DESC, p.id DESC")
    public = []
    for d in rows:      # never expose owner e-mail etc. publicly
        d.pop("owner_email", None)
        d.pop("owner_name", None)
        d.pop("image_list", None)
        public.append(d)
    return jsonify(public)


@app.route("/property/<int:pid>")
def property_detail(pid):
    prop = get_property_or_404(pid)
    if prop["status"] != "approved" and not can_manage(prop):
        abort(404)
    return render_template("property.html", p=prop, manageable=can_manage(prop))


@app.route("/lang/<code>")
def set_lang(code):
    if code in LANGS:
        session["lang"] = code
    ref = request.referrer or ""
    if ref.startswith(request.host_url):
        return redirect(ref)
    return redirect(url_for("index"))


@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename, max_age=60 * 60 * 24 * 365)


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/robots.txt")
def robots():
    body = ("User-agent: *\nDisallow: /admin\nDisallow: /dashboard\nDisallow: /add\n"
            f"Sitemap: {url_for('sitemap', _external=True)}\n")
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    urls = [url_for("index", _external=True)]
    for p in fetch_properties("p.status = 'approved'"):
        urls.append(url_for("property_detail", pid=p["id"], _external=True))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
    return Response(xml, mimetype="application/xml")


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard"))
    form = {}
    if request.method == "POST":
        form = request.form.to_dict()
        if rate_limited("auth:" + (request.remote_addr or "")):
            flash_t("e_rate")
            return render_template("register.html", form=form), 429
        errors = []
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        phone = clean_whatsapp(form.get("phone"))
        password = form.get("password", "")
        if not name or len(name) > 80:
            errors.append("e_name")
        if not EMAIL_RE.match(email) or len(email) > 120:
            errors.append("e_email")
        if len(password) < 8 or len(password) > 200:
            errors.append("e_password_short")
        if phone and not 8 <= len(phone) <= 15:
            errors.append("e_whatsapp")
        db = get_db()
        if not errors and db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            errors.append("e_email_taken")
        if errors:
            for e in errors:
                flash_t(e)
        else:
            cur = db.execute(
                "INSERT INTO users (name, email, phone, password_hash) VALUES (?,?,?,?)",
                (name, email, phone, generate_password_hash(password)))
            db.commit()
            session.clear()
            session["user_id"] = cur.lastrowid
            session.permanent = True
            flash_t("flash_welcome", "success")
            return redirect(safe_next(request.args.get("next")))
    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    form = {}
    if request.method == "POST":
        form = request.form.to_dict()
        if rate_limited("auth:" + (request.remote_addr or "")):
            flash_t("e_rate")
            return render_template("login.html", form=form), 429
        email = form.get("email", "").strip().lower()
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], form.get("password", "")):
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            flash_t("flash_logged_in", "success")
            return redirect(safe_next(request.args.get("next") or form.get("next")))
        flash_t("e_login")
    return render_template("login.html", form=form)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash_t("flash_logged_out", "success")
    return redirect(url_for("index"))


# --------------------------------------------------------------------------
# Owner area: dashboard, add, edit, delete, close/reopen
# --------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    props = fetch_properties("p.owner_id = ?", (g.user["id"],))
    return render_template("dashboard.html", props=props)


@app.route("/add", methods=["GET", "POST"])
@app.route("/add/", methods=["GET", "POST"])
@app.route("/add-property", methods=["GET", "POST"])
@app.route("/add_property", methods=["GET", "POST"])
@login_required
def add_property():
    form = {"whatsapp_number": g.user["phone"] or ""}
    if request.method == "POST":
        form = request.form.to_dict()
        is_admin = bool(g.user["is_admin"])
        data, errors = parse_property_form(request.form, is_admin)
        files = [f for f in request.files.getlist("images") if f and f.filename]
        if len(files) > MAX_IMAGES:
            errors.append("e_images_count")
        urls = []
        if not errors:
            try:
                urls = save_images(files)
            except ImageError as e:
                errors.append(e.key)
        if errors:
            for e in errors:
                flash_t(e)
        else:
            status = "approved" if is_admin else "pending"
            db = get_db()
            cur = db.execute(
                """INSERT INTO properties
                   (title, description, price, type, category, neighborhood,
                    latitude, longitude, whatsapp_number, is_verified, owner_id, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (data["title"], data["description"], data["price"], data["type"],
                 data["category"], data["neighborhood"], data["latitude"],
                 data["longitude"], data["whatsapp_number"],
                 data["is_verified"] or 0, g.user["id"], status))
            for url in urls:
                db.execute("INSERT INTO property_images (property_id, image_url) VALUES (?,?)",
                           (cur.lastrowid, url))
            db.commit()
            flash_t("flash_added" if is_admin else "flash_added_pending", "success")
            return redirect(url_for("dashboard"))
    return render_template("add_property.html", form=form, editing=False,
                           images=[], pid=None)


@app.route("/edit/<int:pid>", methods=["GET", "POST"])
@login_required
def edit_property(pid):
    prop = get_property_or_404(pid)
    if not can_manage(prop):
        abort(403)
    is_admin = bool(g.user["is_admin"])
    form = _form_values(prop)
    if request.method == "POST":
        form = request.form.to_dict()
        data, errors = parse_property_form(request.form, is_admin)
        existing = {i["id"]: i["url"] for i in prop["image_list"]}
        to_delete = set()
        for raw in request.form.getlist("delete_image"):
            if raw.isdigit() and int(raw) in existing:
                to_delete.add(int(raw))
        files = [f for f in request.files.getlist("images") if f and f.filename]
        if len(existing) - len(to_delete) + len(files) > MAX_IMAGES:
            errors.append("e_images_count")
        urls = []
        if not errors:
            try:
                urls = save_images(files)
            except ImageError as e:
                errors.append(e.key)
        if errors:
            for e in errors:
                flash_t(e)
        else:
            if is_admin:
                new_status, verified = prop["status"], (data["is_verified"] or 0)
            else:
                # owner edits go back to review (closed listings stay closed)
                new_status = "closed" if prop["status"] == "closed" else "pending"
                verified = 0 if new_status == "pending" else int(prop["is_verified"])
            db = get_db()
            db.execute(
                """UPDATE properties SET title=?, description=?, price=?, type=?,
                   category=?, neighborhood=?, latitude=?, longitude=?,
                   whatsapp_number=?, is_verified=?, status=? WHERE id=?""",
                (data["title"], data["description"], data["price"], data["type"],
                 data["category"], data["neighborhood"], data["latitude"],
                 data["longitude"], data["whatsapp_number"], verified,
                 new_status, pid))
            for img_id in to_delete:
                db.execute("DELETE FROM property_images WHERE id = ?", (img_id,))
                remove_upload(existing[img_id])
            for url in urls:
                db.execute("INSERT INTO property_images (property_id, image_url) VALUES (?,?)",
                           (pid, url))
            db.commit()
            flash_t("flash_updated", "success")
            return redirect(url_for("dashboard") if not is_admin else url_for("admin"))
    return render_template("add_property.html", form=form, editing=True,
                           images=prop["image_list"], pid=pid)


@app.route("/delete/<int:pid>", methods=["POST"])
@login_required
def delete_property(pid):
    prop = get_property_or_404(pid)
    if not can_manage(prop):
        abort(403)
    db = get_db()
    db.execute("DELETE FROM property_images WHERE property_id = ?", (pid,))
    db.execute("DELETE FROM properties WHERE id = ?", (pid,))
    db.commit()
    for url in prop["images"]:
        remove_upload(url)
    flash_t("flash_deleted", "success")
    return redirect(request.form.get("back") if request.form.get("back") in
                    (url_for("admin"), url_for("dashboard")) else url_for("dashboard"))


@app.route("/status/<int:pid>", methods=["POST"])
@login_required
def change_status(pid):
    prop = get_property_or_404(pid)
    if not can_manage(prop):
        abort(403)
    action = request.form.get("action")
    db = get_db()
    if action == "close" and prop["status"] == "approved":
        db.execute("UPDATE properties SET status='closed' WHERE id=?", (pid,))
    elif action == "reopen" and prop["status"] == "closed":
        db.execute("UPDATE properties SET status='approved' WHERE id=?", (pid,))
    else:
        abort(400)
    db.commit()
    flash_t("flash_status", "success")
    return redirect(url_for("dashboard"))


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin():
    props = fetch_properties(order="CASE p.status WHEN 'pending' THEN 0 ELSE 1 END, p.id DESC")
    pending = [p for p in props if p["status"] == "pending"]
    return render_template("admin.html", props=props, pending=pending)


@app.route("/admin/action/<int:pid>", methods=["POST"])
@admin_required
def admin_action(pid):
    get_property_or_404(pid)
    action = request.form.get("action")
    db = get_db()
    if action == "approve":
        db.execute("UPDATE properties SET status='approved' WHERE id=?", (pid,))
    elif action == "reject":
        db.execute("UPDATE properties SET status='rejected' WHERE id=?", (pid,))
    elif action == "verify":
        db.execute("UPDATE properties SET is_verified=1 WHERE id=?", (pid,))
    elif action == "unverify":
        db.execute("UPDATE properties SET is_verified=0 WHERE id=?", (pid,))
    else:
        abort(400)
    db.commit()
    flash_t("flash_status", "success")
    return redirect(url_for("admin"))


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
def _error(code, key):
    return render_template("error.html", code=code, message_key=key), code


@app.errorhandler(400)
def err400(_e):
    return _error(400, "err_400")


@app.errorhandler(403)
def err403(_e):
    return _error(403, "err_403")


@app.errorhandler(404)
def err404(_e):
    return _error(404, "err_404")


@app.errorhandler(413)
def err413(_e):
    return _error(413, "err_413")


@app.errorhandler(500)
def err500(_e):
    return _error(500, "err_500")


# Create tables / admin / samples on import so gunicorn works too.
init_db()

if __name__ == "__main__":
    app.run(debug=not IS_PROD, port=int(os.environ.get("PORT", 5000)))
