"""
Bosaso Homes - Real Estate & Land Marketplace (Flask + SQLAlchemy)

Local:   python app.py                 -> http://127.0.0.1:5000
Render:  gunicorn app:app --workers 1 --threads 4   (see render.yaml)

Storage modes (chosen automatically from environment variables):
  DATABASE_URL    set -> PostgreSQL (production)   | not set -> SQLite file (local)
  CLOUDINARY_URL  set -> photos on Cloudinary      | not set -> photos in ./uploads

Models live in models.py:  User, Property, Image (one-to-many), Favorite.
"""
import io
import math
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
from PIL import Image as PILImage
from PIL import ImageOps
from sqlalchemy import case, event, func, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from i18n import JS_KEYS, LANGS, tr
from models import Favorite, Image, Property, User, db

# --------------------------------------------------------------------------
# Configuration (everything sensitive comes from environment variables)
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_PROD = bool(os.environ.get("RENDER"))          # Render sets RENDER=true

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = bool(DATABASE_URL)
USE_CLOUD = bool(os.environ.get("CLOUDINARY_URL", "").strip())

if USE_CLOUD:
    import cloudinary
    import cloudinary.uploader
    cloudinary.config(secure=True)      # credentials are read from CLOUDINARY_URL

# DATA_DIR is only used in local mode (SQLite file + ./uploads folder).
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
DB_PATH = os.path.join(DATA_DIR, "bosaso_realestate.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

BRAND_NAME = os.environ.get("BRAND_NAME", "Bosaso Homes")
ADMIN_WHATSAPP = re.sub(r"\D", "", os.environ.get("ADMIN_WHATSAPP", ""))


def _database_uri():
    url = DATABASE_URL
    if not url:
        return "sqlite:///" + DB_PATH
    # Render / Heroku style URLs -> SQLAlchemy + psycopg 3
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    MAX_CONTENT_LENGTH=24 * 1024 * 1024,           # max request size (24 MB)
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PROD,
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,  # 30 days
    SQLALCHEMY_DATABASE_URI=_database_uri(),
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 280},
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
)
# Render terminates HTTPS in front of us; trust its forwarded headers.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
db.init_app(app)


@event.listens_for(Engine, "connect")
def _sqlite_foreign_keys(dbapi_conn, _record):
    if isinstance(dbapi_conn, sqlite3.Connection):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


BOSASO_CENTER = (11.2842, 49.1816)
LAT_RANGE = (11.0, 11.6)
LNG_RANGE = (48.9, 49.5)

TYPES = ("Rent", "Sale")                                   # filter name: status
CATEGORIES = ("House", "Apartment", "Land", "Commercial")  # filter: property_type
NEIGHBORHOODS = ["Bander Ziada", "Baalade", "Suweyto", "Horseed", "Shabelle",
                 "Waaberi", "Galkacyo Road", "Other"]
MAX_IMAGES = 6
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# NOTE: coordinates are approximate and the WhatsApp numbers are fake placeholders.
SAMPLE_PROPERTIES = [
    {
        "title": "Modern 4-Bedroom Villa in Bander Ziada",
        "description": "Spacious villa with a walled compound, 3 bathrooms, "
                       "generator room and water tank. Quiet street, close to "
                       "the main road and the port.",
        "price": 185000, "type": "Sale", "category": "House",
        "neighborhood": "Bander Ziada", "latitude": 11.2905, "longitude": 49.1960,
        "whatsapp_number": "252907000001", "is_verified": True,
        "images": ["https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=800"],
    },
    {
        "title": "3-Bedroom House for Rent in Baalade",
        "description": "Clean family house with tiled floors, kitchen, "
                       "2 bathrooms and a small yard. Available immediately.",
        "price": 350, "type": "Rent", "category": "House",
        "neighborhood": "Baalade", "latitude": 11.2788, "longitude": 49.1792,
        "whatsapp_number": "252907000002", "is_verified": True,
        "images": ["https://images.unsplash.com/photo-1568605114967-8130f3a36994?w=800"],
    },
    {
        "title": "600 m² Residential Land in Suweyto",
        "description": "Flat, ready-to-build plot with clear ownership "
                       "documents. Close to the main road. Ideal for a family "
                       "home or small apartment block.",
        "price": 42000, "type": "Sale", "category": "Land",
        "neighborhood": "Suweyto", "latitude": 11.2660, "longitude": 49.1715,
        "whatsapp_number": "252907000003", "is_verified": False,
        "images": ["https://images.unsplash.com/photo-1500382017468-9049fed747ef?w=800"],
    },
    {
        "title": "2-Bedroom Apartment near the Port",
        "description": "Second-floor apartment with sea breeze, balcony, "
                       "reliable water supply and secure entrance. "
                       "Perfect for small families or professionals.",
        "price": 280, "type": "Rent", "category": "Apartment",
        "neighborhood": "Bander Ziada", "latitude": 11.2872, "longitude": 49.1858,
        "whatsapp_number": "252907000004", "is_verified": True,
        "images": ["https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800"],
    },
]


# --------------------------------------------------------------------------
# Database bootstrap
# --------------------------------------------------------------------------
def _prepare_sqlite_file():
    """Old local SQLite files carry CHECK constraints that reject the new
    'Commercial' category. Keep such a file as a backup and start a fresh one."""
    if USE_PG or not os.path.exists(DB_PATH):
        return
    con = sqlite3.connect(DB_PATH)
    try:
        row = con.execute("SELECT sql FROM sqlite_master "
                          "WHERE type='table' AND name='properties'").fetchone()
    finally:
        con.close()
    if row and row[0] and "CHECK" in row[0] and "Commercial" not in row[0]:
        backup = DB_PATH[:-3] + f".old-{int(time.time())}.db"
        os.replace(DB_PATH, backup)
        print(f"[info] Old local database backed up to {os.path.basename(backup)}; "
              "starting a fresh one.")


def _relax_postgres_checks():
    """Existing PostgreSQL tables (first versions) only allowed 3 categories."""
    if not USE_PG:
        return
    try:
        db.session.execute(text(
            "ALTER TABLE properties DROP CONSTRAINT IF EXISTS properties_category_check"))
        db.session.commit()
    except Exception as exc:          # not fatal (e.g. table has no such constraint)
        db.session.rollback()
        print("[warn] could not relax category constraint:", exc)


def _ensure_admin():
    email = "AmiinAdminBosaso.local@gmail.com"  # Geli email-kaaga admin-ka
    password = "amiinhomelocal1234"     # Geli password-kaaga
    explicit = bool(password)
    if not IS_PROD and not password:      # local development convenience only
        email = email or "AmiinAdminBosaso.local@gmail.com"
        password = "amiinhomelocal1234"
        print("[dev] Admin login -> AmiinAdminBosaso.local@gmail.com / amiinhomelocal1234")
    if not email or not password:
        print("[warn] ADMIN_EMAIL / ADMIN_PASSWORD not set: no admin account created.")
        return
    user = db.session.scalar(select(User).where(User.email == email))
    try:
        if user is None:
            db.session.add(User(name="Admin", email=email, is_admin=True,
                                 password_hash=generate_password_hash(password)))
        else:
            user.is_admin = True
            if explicit:                  # env var is the source of truth
                user.password_hash = generate_password_hash(password)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


def _seed_samples():
    if os.environ.get("SEED_SAMPLES", "1") == "0":
        return
    if db.session.scalar(select(func.count(Property.id))):
        return
    for p in SAMPLE_PROPERTIES:
        prop = Property(
            title=p["title"], description=p["description"], price=p["price"],
            type=p["type"], category=p["category"], neighborhood=p["neighborhood"],
            latitude=p["latitude"], longitude=p["longitude"],
            whatsapp_number=p["whatsapp_number"], is_verified=p["is_verified"],
            status="approved")
        prop.images = [Image(image_url=u) for u in p["images"]]
        db.session.add(prop)
    db.session.commit()
    print(f"Seeded {len(SAMPLE_PROPERTIES)} sample properties.")


def init_db():
    _prepare_sqlite_file()
    with app.app_context():
        db.create_all()          # creates missing tables only (e.g. favorites)
        _relax_postgres_checks()
        _ensure_admin()
        _seed_samples()
    print("Database:", "PostgreSQL" if USE_PG else "SQLite",
          "| Photos:", "Cloudinary" if USE_CLOUD else "local disk")


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
    if request.endpoint in (None, "static", "uploads", "favicon_ico"):
        return
    uid = session.get("user_id")
    if uid:
        g.user = db.session.get(User, uid)
        if g.user is None:
            session.pop("user_id", None)
    if request.method == "POST":
        token = session.get("_csrf", "")
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
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
        if not g.user.is_admin:
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


def safe_next(target, default=None):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return default or url_for("dashboard")


# --------------------------------------------------------------------------
# Property helpers
# --------------------------------------------------------------------------
def clean_whatsapp(raw):
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def favorite_ids_for(user):
    if user is None:
        return set()
    return set(db.session.scalars(
        select(Favorite.property_id).where(Favorite.user_id == user.id)))


def _like(value):
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_property_query(args, only_approved=True):
    """Search & filter. Supported query parameters:

        location       neighborhood (partial, case-insensitive)   [old: neighborhood]
        property_type  House | Apartment | Land | Commercial       [old: category]
        status         Rent | Sale                                 [old: type]
        min_price, max_price
        q              free text (title / description / neighborhood)
    """
    query = select(Property).options(selectinload(Property.images))
    if only_approved:
        query = query.where(Property.status == "approved")

    rent_sale = (args.get("status") or args.get("type") or "").strip()
    if rent_sale in TYPES:
        query = query.where(Property.type == rent_sale)

    category = (args.get("property_type") or args.get("category") or "").strip()
    if category in CATEGORIES:
        query = query.where(Property.category == category)

    location = (args.get("location") or args.get("neighborhood") or "").strip()
    if location:
        query = query.where(Property.neighborhood.ilike(_like(location), escape="\\"))

    low, high = _number(args.get("min_price")), _number(args.get("max_price"))
    if low is not None:
        query = query.where(Property.price >= low)
    if high is not None:
        query = query.where(Property.price <= high)

    term = (args.get("q") or "").strip()
    if term:
        pattern = _like(term[:100])
        query = query.where(or_(
            Property.title.ilike(pattern, escape="\\"),
            Property.description.ilike(pattern, escape="\\"),
            Property.neighborhood.ilike(pattern, escape="\\")))

    return query.order_by(Property.is_verified.desc(), Property.created_at.desc(),
                          Property.id.desc())


def get_property_or_404(pid):
    prop = db.session.get(Property, pid)
    if prop is None:
        abort(404)
    return prop


def can_manage(prop):
    return g.user is not None and (g.user.is_admin or prop.owner_id == g.user.id)


class ImageError(Exception):
    def __init__(self, key):
        super().__init__(key)
        self.key = key


def _store_image(jpeg_bytes):
    """Save one processed photo and return its public URL."""
    if USE_CLOUD:
        res = cloudinary.uploader.upload(io.BytesIO(jpeg_bytes), folder="bosaso-homes",
                                         resource_type="image")
        return res["secure_url"]
    name = uuid.uuid4().hex + ".jpg"
    with open(os.path.join(UPLOAD_DIR, name), "wb") as fh:
        fh.write(jpeg_bytes)
    return "/uploads/" + name


def save_images(files):
    """Validate, resize and store uploads. Returns list of image URLs."""
    saved = []
    try:
        for f in files:
            ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED_EXT:
                raise ImageError("e_images_type")
            try:
                img = PILImage.open(f.stream)
                img = ImageOps.exif_transpose(img).convert("RGB")
            except Exception:
                raise ImageError("e_images_bad")
            img.thumbnail((1400, 1400))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=82, optimize=True)
            try:
                saved.append(_store_image(buf.getvalue()))
            except Exception as exc:
                app.logger.error("Photo storage failed: %s", exc)
                raise ImageError("e_images_upload")
    except ImageError:
        for url in saved:
            remove_upload(url)
        raise
    return saved


def remove_upload(url):
    """Delete a stored photo (local file or Cloudinary asset). Never raises."""
    if not url:
        return
    if url.startswith("/uploads/"):
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(url)))
        except OSError:
            pass
    elif USE_CLOUD and "res.cloudinary.com" in url:
        m = re.search(r"/upload/(?:v\d+/)?(.+?)\.[A-Za-z0-9]+$", url)
        if m:
            try:
                cloudinary.uploader.destroy(m.group(1), resource_type="image")
            except Exception as exc:
                app.logger.warning("Cloudinary delete failed: %s", exc)


def commit_or_cleanup(new_urls=()):
    """Commit; if it fails, roll back and delete photos we just stored."""
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        for url in new_urls:
            remove_upload(url)
        raise


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

    data["is_verified"] = bool(is_admin and form.get("is_verified"))
    return data, errors


def _form_values(prop):
    price = prop.price
    return {
        "title": prop.title, "description": prop.description or "",
        "price": int(price) if price == int(price) else price,
        "type": prop.type, "category": prop.category,
        "neighborhood": prop.neighborhood, "latitude": prop.latitude,
        "longitude": prop.longitude, "whatsapp_number": prop.whatsapp_number,
        "is_verified": "1" if prop.is_verified else "",
    }


def _apply_form(prop, data):
    for field in ("title", "description", "price", "type", "category",
                  "neighborhood", "latitude", "longitude", "whatsapp_number"):
        setattr(prop, field, data[field])


# --------------------------------------------------------------------------
# Public pages + API
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/properties")
def api_properties():
    props = db.session.scalars(build_property_query(request.args)).all()
    fav_ids = favorite_ids_for(g.user)
    return jsonify([p.to_dict(fav_ids) for p in props])      # public: no owner data


@app.route("/property/<int:pid>")
def property_detail(pid):
    prop = get_property_or_404(pid)
    manageable = can_manage(prop)
    if prop.status != "approved" and not manageable:
        abort(404)
    return render_template("property.html",
                           p=prop.to_dict(favorite_ids_for(g.user)),
                           manageable=manageable)


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


@app.route("/favicon.ico")
def favicon_ico():
    return redirect(url_for("static", filename="favicon.svg"), code=301)


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/robots.txt")
def robots():
    body = ("User-agent: *\nDisallow: /admin\nDisallow: /dashboard\nDisallow: /add\n"
            "Disallow: /my-favorites\n"
            f"Sitemap: {url_for('sitemap', _external=True)}\n")
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    urls = [url_for("index", _external=True)]
    ids = db.session.scalars(select(Property.id).where(Property.status == "approved"))
    urls += [url_for("property_detail", pid=i, _external=True) for i in ids]
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
    return Response(xml, mimetype="application/xml")


# --------------------------------------------------------------------------
# Favorites (saved properties)
# --------------------------------------------------------------------------
@app.route("/favorite/<int:pid>", methods=["POST"])
def toggle_favorite(pid):
    wants_json = request.headers.get("X-Requested-With") == "fetch"
    detail_url = url_for("property_detail", pid=pid)
    if g.user is None:
        login_url = url_for("login", next=detail_url)
        if wants_json:
            return jsonify(login_url=login_url), 401
        flash_t("flash_need_login")
        return redirect(login_url)

    prop = get_property_or_404(pid)
    if prop.status != "approved" and not can_manage(prop):
        abort(404)

    fav = db.session.scalar(select(Favorite).where(
        Favorite.user_id == g.user.id, Favorite.property_id == pid))
    if fav is None:
        db.session.add(Favorite(user_id=g.user.id, property_id=pid))
        favorited = True
    else:
        db.session.delete(fav)
        favorited = False
    try:
        db.session.commit()
    except IntegrityError:            # double click race: row already exists
        db.session.rollback()
        favorited = True

    if wants_json:
        return jsonify(favorited=favorited)
    return redirect(safe_next(request.form.get("next"), default=detail_url))


@app.route("/my-favorites")
@login_required
def my_favorites():
    props = db.session.scalars(
        select(Property)
        .join(Favorite, Favorite.property_id == Property.id)
        .where(Favorite.user_id == g.user.id, Property.status == "approved")
        .options(selectinload(Property.images))
        .order_by(Favorite.id.desc())).all()
    ids = {p.id for p in props}
    return render_template("favorites.html", props=[p.to_dict(ids) for p in props])


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
        if not errors and db.session.scalar(select(User.id).where(User.email == email)):
            errors.append("e_email_taken")
        if errors:
            for e in errors:
                flash_t(e)
        else:
            user = User(name=name, email=email, phone=phone,
                        password_hash=generate_password_hash(password))
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash_t("e_email_taken")
                return render_template("register.html", form=form)
            session.clear()
            session["user_id"] = user.id
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
        user = db.session.scalar(select(User).where(User.email == email))
        if user and check_password_hash(user.password_hash, form.get("password", "")):
            session.clear()
            session["user_id"] = user.id
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
    props = db.session.scalars(
        select(Property).where(Property.owner_id == g.user.id)
        .options(selectinload(Property.images)).order_by(Property.id.desc())).all()
    return render_template("dashboard.html", props=[p.to_dict(private=True) for p in props])


@app.route("/add", methods=["GET", "POST"])
@app.route("/add/", methods=["GET", "POST"])
@app.route("/add-property", methods=["GET", "POST"])
@app.route("/add_property", methods=["GET", "POST"])
@login_required
def add_property():
    form = {"whatsapp_number": g.user.phone or ""}
    if request.method == "POST":
        form = request.form.to_dict()
        is_admin = bool(g.user.is_admin)
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
            prop = Property(owner_id=g.user.id,
                            status="approved" if is_admin else "pending",
                            is_verified=data["is_verified"])
            _apply_form(prop, data)
            prop.images = [Image(image_url=u) for u in urls]
            db.session.add(prop)
            commit_or_cleanup(urls)
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
    is_admin = bool(g.user.is_admin)
    form = _form_values(prop)
    if request.method == "POST":
        form = request.form.to_dict()
        data, errors = parse_property_form(request.form, is_admin)
        existing = {img.id: img for img in prop.images}
        to_delete = {int(raw) for raw in request.form.getlist("delete_image")
                     if raw.isdigit() and int(raw) in existing}
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
            _apply_form(prop, data)
            if is_admin:
                prop.is_verified = data["is_verified"]
            elif prop.status != "closed":
                prop.status = "pending"        # owner edits go back to review
                prop.is_verified = False
            removed_urls = []
            for img_id in to_delete:
                removed_urls.append(existing[img_id].image_url)
                prop.images.remove(existing[img_id])   # delete-orphan removes the row
            for url in urls:
                prop.images.append(Image(image_url=url))
            commit_or_cleanup(urls)
            for url in removed_urls:
                remove_upload(url)
            flash_t("flash_updated", "success")
            return redirect(url_for("admin") if is_admin else url_for("dashboard"))
    gallery = [{"id": img.id, "url": img.image_url} for img in prop.images]
    return render_template("add_property.html", form=form, editing=True,
                           images=gallery, pid=pid)


@app.route("/delete/<int:pid>", methods=["POST"])
@login_required
def delete_property(pid):
    prop = get_property_or_404(pid)
    if not can_manage(prop):
        abort(403)
    urls = [img.image_url for img in prop.images]
    db.session.delete(prop)                      # cascades images + favorites
    db.session.commit()
    for url in urls:
        remove_upload(url)
    flash_t("flash_deleted", "success")
    back = request.form.get("back")
    return redirect(back if back in (url_for("admin"), url_for("dashboard"))
                    else url_for("dashboard"))


@app.route("/status/<int:pid>", methods=["POST"])
@login_required
def change_status(pid):
    prop = get_property_or_404(pid)
    if not can_manage(prop):
        abort(403)
    action = request.form.get("action")
    if action == "close" and prop.status == "approved":
        prop.status = "closed"
    elif action == "reopen" and prop.status == "closed":
        prop.status = "approved"
    else:
        abort(400)
    db.session.commit()
    flash_t("flash_status", "success")
    return redirect(url_for("dashboard"))


# --------------------------------------------------------------------------
# Admin (approve / reject / verified toggle)
# --------------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin():
    props = db.session.scalars(
        select(Property)
        .options(selectinload(Property.images), selectinload(Property.owner))
        .order_by(case((Property.status == "pending", 0), else_=1), Property.id.desc())).all()
    rows = [p.to_dict(private=True) for p in props]
    return render_template("admin.html", props=rows,
                           pending=[r for r in rows if r["status"] == "pending"])


@app.route("/admin/action/<int:pid>", methods=["POST"])
@admin_required
def admin_action(pid):
    prop = get_property_or_404(pid)
    action = request.form.get("action")
    if action == "approve":
        prop.status = "approved"
    elif action == "reject":
        prop.status = "rejected"
    elif action == "verify":
        prop.is_verified = True
    elif action == "unverify":
        prop.is_verified = False
    else:
        abort(400)
    db.session.commit()
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
