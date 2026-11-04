"""
Bosaso Real Estate & Land Marketplace - MVP
Run with:  python app.py   ->  http://127.0.0.1:5000
"""
import os
import re
import sqlite3

from flask import (Flask, flash, g, jsonify, redirect, render_template,
                   request, url_for)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bosaso_realestate.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")

# Simple protection for the Add Property page. Change it!
# Linux/Mac: export ADMIN_PASSWORD="mysecret"   Windows: set ADMIN_PASSWORD=mysecret
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

BOSASO_CENTER = (11.2842, 49.1816)
# Loose bounding box around Bosaso so listings stay Bosaso-focused
LAT_RANGE = (11.0, 11.6)
LNG_RANGE = (48.9, 49.5)

TYPES = ("Rent", "Sale")
CATEGORIES = ("House", "Land", "Apartment")
NEIGHBORHOODS = ["Bander Ziada", "Baalade", "Suweyto", "Horseed", "Shabelle",
                 "Waaberi", "Galkacyo Road", "Other"]


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
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
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS property_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL,
    image_url   TEXT    NOT NULL,
    FOREIGN KEY (property_id) REFERENCES properties (id) ON DELETE CASCADE
);
"""

# NOTE: coordinates are approximate and the WhatsApp numbers are fake
# placeholders. Replace them with real data via the Add Property page.
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


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(SCHEMA)
        count = db.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        if count == 0:
            for p in SAMPLE_PROPERTIES:
                cur = db.execute(
                    """INSERT INTO properties
                       (title, description, price, type, category, neighborhood,
                        latitude, longitude, whatsapp_number, is_verified)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (p["title"], p["description"], p["price"], p["type"],
                     p["category"], p["neighborhood"], p["latitude"],
                     p["longitude"], p["whatsapp_number"], p["is_verified"]),
                )
                for url in p["images"]:
                    db.execute(
                        "INSERT INTO property_images (property_id, image_url) VALUES (?,?)",
                        (cur.lastrowid, url),
                    )
            print(f"Seeded {len(SAMPLE_PROPERTIES)} sample properties.")


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", center=BOSASO_CENTER,
                           neighborhoods=NEIGHBORHOODS)


@app.route("/api/properties")
def api_properties():
    """JSON list of properties, with optional filters:
    ?type=Rent|Sale &category=House|Land|Apartment &min_price= &max_price="""
    where, params = [], []

    ptype = request.args.get("type", "").strip()
    if ptype in TYPES:
        where.append("type = ?")
        params.append(ptype)

    category = request.args.get("category", "").strip()
    if category in CATEGORIES:
        where.append("category = ?")
        params.append(category)

    for key, op in (("min_price", ">="), ("max_price", "<=")):
        raw = request.args.get(key, "").strip()
        if raw:
            try:
                params.append(float(raw))
                where.append(f"price {op} ?")
            except ValueError:
                pass

    sql = "SELECT * FROM properties"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY is_verified DESC, created_at DESC, id DESC"

    db = get_db()
    rows = db.execute(sql, params).fetchall()

    images = {}
    if rows:
        ids = [r["id"] for r in rows]
        marks = ",".join("?" * len(ids))
        for img in db.execute(
            f"SELECT property_id, image_url FROM property_images "
            f"WHERE property_id IN ({marks}) ORDER BY id", ids
        ):
            images.setdefault(img["property_id"], []).append(img["image_url"])

    result = []
    for r in rows:
        d = dict(r)
        d["is_verified"] = bool(d["is_verified"])
        d["images"] = images.get(r["id"], [])
        result.append(d)
    return jsonify(result)


def _clean_whatsapp(raw):
    """Keep digits only (wa.me needs international format, no + or spaces)."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


@app.route("/add", methods=["GET", "POST"])
def add_property():
    form = {}
    if request.method == "POST":
        form = request.form.to_dict()
        errors = []

        if form.get("password", "") != ADMIN_PASSWORD:
            errors.append("Wrong admin password.")

        title = form.get("title", "").strip()
        if not title:
            errors.append("Title is required.")

        try:
            price = float(form.get("price", ""))
            if price <= 0:
                raise ValueError
        except ValueError:
            errors.append("Price must be a positive number.")
            price = None

        if form.get("type") not in TYPES:
            errors.append("Choose Rent or Sale.")
        if form.get("category") not in CATEGORIES:
            errors.append("Choose a category.")

        neighborhood = form.get("neighborhood", "").strip()
        if not neighborhood:
            errors.append("Neighborhood is required.")

        try:
            lat = float(form.get("latitude", ""))
            lng = float(form.get("longitude", ""))
            if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]
                    and LNG_RANGE[0] <= lng <= LNG_RANGE[1]):
                errors.append("Coordinates must be inside the Bosaso area "
                              "(click the map to pick a spot).")
        except ValueError:
            errors.append("Latitude and longitude must be numbers.")
            lat = lng = None

        whatsapp = _clean_whatsapp(form.get("whatsapp_number"))
        if not 8 <= len(whatsapp) <= 15:
            errors.append("WhatsApp number must be in international format, "
                          "e.g. 252907123456.")

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            db = get_db()
            cur = db.execute(
                """INSERT INTO properties
                   (title, description, price, type, category, neighborhood,
                    latitude, longitude, whatsapp_number, is_verified)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (title, form.get("description", "").strip(), price,
                 form["type"], form["category"], neighborhood, lat, lng,
                 whatsapp, 1 if form.get("is_verified") else 0),
            )
            # Image URLs: one per line (or comma separated)
            urls = re.split(r"[\n,]+", form.get("image_urls", ""))
            for url in (u.strip() for u in urls):
                if url.startswith(("http://", "https://")):
                    db.execute(
                        "INSERT INTO property_images (property_id, image_url) VALUES (?,?)",
                        (cur.lastrowid, url),
                    )
            db.commit()
            flash(f"Property #{cur.lastrowid} added successfully!", "success")
            return redirect(url_for("index"))

    return render_template("add_property.html", form=form,
                           center=BOSASO_CENTER, neighborhoods=NEIGHBORHOODS)


# --------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
