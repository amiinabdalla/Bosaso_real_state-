<p align="center">
  <img src="static/logo.png" alt="Bosaso Homes logo" width="120">
</p>

<h1 align="center">Bosaso Homes</h1>

<p align="center">
  <b>A real estate &amp; land marketplace for Bosaso, Somalia.</b><br>
  Find verified houses, apartments, land and shops for rent or sale on an interactive map, then contact the owner directly on WhatsApp.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="Flask" src="https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white">
  <img alt="SQLAlchemy" src="https://img.shields.io/badge/SQLAlchemy-2.x-D71F00">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-ready-4169E1?logo=postgresql&logoColor=white">
  <img alt="Tailwind CSS" src="https://img.shields.io/badge/Tailwind_CSS-38B2AC?logo=tailwindcss&logoColor=white">
  <img alt="Leaflet" src="https://img.shields.io/badge/Leaflet-OpenStreetMap-199900?logo=leaflet&logoColor=white">
</p>

<p align="center">
  <a href="https://bosaso-real-state.onrender.com"><b>Live demo</b></a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#quick-start-local">Quick start</a> ·
  <a href="#deploying-to-render">Deploy</a> ·
  <a href="#soomaali-af-soomaali">Soomaali</a>
</p>

> The live demo runs on a free Render instance, so the first request after a period of inactivity can take up to ~50 seconds while the server wakes up.

---

## Why this project exists

Finding a home or a plot of land in Bosaso usually means asking around, scrolling through unverified social-media posts, or relying on word of mouth. Buyers and tenants (including people living in the diaspora, for example in the UK) have no single place to see **what is available, where it is, and whether it can be trusted**.

Bosaso Homes puts every listing on a map, lets an admin **review and verify** listings before they go public, and sends the visitor straight to the owner on **WhatsApp**, the tool people in the region already use every day. The website itself does not handle money.

## Features

**For visitors (no account needed)**
- Interactive map of Bosaso (Leaflet + OpenStreetMap) with a pin for every listing
- Search and filters: free text, location (neighborhood), property type, rent/sale, and price range. Results update as you type and the URL is shareable
- Listing page with a photo carousel (arrows, dots, thumbnails, swipe, keyboard), description, map and price
- One-tap **WhatsApp** button with a pre-filled message that contains the property ID
- **Verified 🛡️** badge on listings that the admin has checked
- English and Somali interface, mobile-friendly

**For owners and agents (free account)**
- Register, log in and add a listing with up to **6 photos** and a pin dropped on the map
- Dashboard to edit, delete, or mark a listing as rented/sold (and reopen it later)
- **Save** listings with the ❤ button and review them on the *Saved* page

**For the admin**
- Moderation queue: approve or reject new and edited listings
- Verified toggle (only the admin can grant the badge)
- Edit or delete any listing

## How it works

### The big picture

```mermaid
flowchart LR
    V["Visitor's browser"] -->|HTTPS| R["Flask + Gunicorn<br/>(Render web service)"]
    R --> P[("PostgreSQL<br/>users, listings, favorites")]
    R --> C["Cloudinary<br/>listing photos"]
    V -->|wa.me link| W["WhatsApp chat with the owner"]
    V --> O["OpenStreetMap map tiles"]
```

1. A visitor opens the site. The page calls `GET /api/properties` with the current filters and receives only **approved** listings as JSON.
2. The JavaScript draws a card and a map pin for each result. Changing a filter reloads the list without a page refresh.
3. Opening a listing shows the photo carousel and a **WhatsApp** button. The link looks like `https://wa.me/<owner number>?text=...ID:<id>`, so the owner immediately knows which property the visitor is asking about.
4. Money and viewings are arranged directly between the visitor and the owner.

### Life of a listing

```mermaid
stateDiagram-v2
    [*] --> pending: Owner submits a listing
    pending --> approved: Admin approves
    pending --> rejected: Admin rejects
    rejected --> pending: Owner edits and resubmits
    approved --> pending: Owner edits (re-reviewed, badge removed)
    approved --> closed: Owner marks rented / sold
    closed --> approved: Owner reopens
```

- Only `approved` listings are visible to the public and appear in the API, the sitemap and the map.
- Listings created by an admin are approved immediately.
- The **Verified** badge is separate from approval and can only be set by the admin.

### Photos

Uploaded images are validated (JPG, PNG or WebP only), corrected for phone rotation, resized to at most 1400 px and re-encoded as JPEG. They are stored on **Cloudinary** in production, or in the local `uploads/` folder during development.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask, Flask-SQLAlchemy (SQLAlchemy 2) |
| Database | PostgreSQL in production, SQLite for local development |
| Frontend | Jinja2 templates, Tailwind CSS (CDN), vanilla JavaScript |
| Maps | Leaflet.js + OpenStreetMap tiles (free, no API key) |
| Photos | Pillow for processing, Cloudinary for storage |
| Server | Gunicorn on Render |

## Project structure

```
bosaso-homes/
├── app.py                 # routes, search query, uploads, auth, admin
├── models.py              # User, Property, Image, Favorite
├── i18n.py                # English + Somali texts
├── requirements.txt
├── render.yaml            # optional Render blueprint
├── static/
│   ├── favorites.js       # heart / save buttons
│   └── logo*.svg|png, favicon.svg
└── templates/
    ├── base.html          # layout, navigation, language switch
    ├── index.html         # search + map + results
    ├── property.html      # listing page with carousel
    ├── favorites.html     # saved listings
    ├── add_property.html  # add / edit form with map picker
    ├── dashboard.html     # owner's listings
    ├── admin.html         # moderation panel
    └── login.html, register.html, error.html, _macros.html
```

## Data model

```mermaid
erDiagram
    USERS ||--o{ PROPERTIES : owns
    PROPERTIES ||--o{ PROPERTY_IMAGES : has
    USERS ||--o{ FAVORITES : saves
    PROPERTIES ||--o{ FAVORITES : "saved in"

    USERS {
        int id PK
        string name
        string email UK
        string phone
        string password_hash
        bool is_admin
    }
    PROPERTIES {
        int id PK
        string title
        text description
        float price
        string type "Rent or Sale"
        string category "House, Apartment, Land, Commercial"
        string neighborhood
        float latitude
        float longitude
        string whatsapp_number
        bool is_verified
        string status "pending, approved, rejected, closed"
        int owner_id FK
    }
    PROPERTY_IMAGES {
        int id PK
        int property_id FK
        text image_url
    }
    FAVORITES {
        int id PK
        int user_id FK
        int property_id FK
    }
```

A user can save a given property only once (unique `user_id` + `property_id`).

## Search and filter parameters

Used by the home page (they appear in the address bar) and by `GET /api/properties`.

| Parameter | Meaning | Example |
|---|---|---|
| `q` | Free text in title, description and neighborhood | `villa` |
| `location` | Neighborhood, partial and case-insensitive | `baal` matches *Baalade* |
| `property_type` | `House`, `Apartment`, `Land` or `Commercial` | `Land` |
| `status` | `Rent` or `Sale` | `Rent` |
| `min_price`, `max_price` | Price range in USD | `300`, `400` |

Example: `/?location=baalade&property_type=House&status=Rent&max_price=400`

## Quick start (local)

Requirements: Python 3.10 or newer (developed and tested on 3.12).

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

python -m venv venv
# Windows:  venv\Scripts\activate
# macOS/Linux:  source venv/bin/activate

pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**.

- Without any configuration the app uses a local **SQLite** file (`bosaso_realestate.db`) and stores photos in `uploads/`.
- It seeds **4 sample listings** (with fake phone numbers) so the map is not empty. Set `SEED_SAMPLES=0` to disable this.
- Local admin account (development only): `admin@bosaso.local` / `admin123`.

## Configuration

All settings are environment variables.

| Variable | Required in production | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string (`postgres://` and `postgresql://` both work). Not set = SQLite |
| `CLOUDINARY_URL` | Yes | `cloudinary://API_KEY:API_SECRET@CLOUD_NAME`. Not set = photos on local disk |
| `SECRET_KEY` | Yes | Long random text. Keeps logins valid across restarts |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Yes | Admin account, created or updated at startup |
| `SEED_SAMPLES` | Recommended `0` | `0` starts with an empty marketplace |
| `ADMIN_WHATSAPP` | No | Office number (for example `252907123456`) for an extra "Ask the office" button and the "Report listing" link |
| `BRAND_NAME` | No | Site name, default `Bosaso Homes` |

## Deploying to Render

The web service keeps **no data on its own disk**: users and listings live in PostgreSQL and photos live on Cloudinary, so nothing is lost when the service restarts or is redeployed.

1. **Create a PostgreSQL database** (Render Postgres or any provider) and copy its connection string.
2. **Create a free Cloudinary account** and copy the `CLOUDINARY_URL` from the dashboard.
3. Push this repository to GitHub.
4. On Render choose **New → Web Service**, connect the repository and set:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app --workers 1 --threads 4 --timeout 60`
   - Health check path: `/healthz`
5. Add the environment variables from the table above.
6. Deploy. Tables are created automatically on first start, and a database created by an earlier version of this project is upgraded in place.
7. Open the site, log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`, and approve listings from **/admin**.

Free instances sleep after inactivity; a paid instance removes the cold start. Check each provider's current plans and limits before choosing.

## Security

- Passwords are stored as salted hashes (never in plain text)
- CSRF protection on every form and AJAX request
- Login/registration rate limiting (10 attempts per 10 minutes per IP)
- Upload validation: allowed extensions, real image decoding, size limits, resizing
- Listings are moderated before they become public; the verified badge is admin-only
- Public API never exposes owner e-mail addresses
- Secure, HTTP-only, same-site session cookies, plus basic security headers
- Open-redirect protection on login

## Main routes

| Route | Purpose |
|---|---|
| `/` | Map, search and results |
| `/property/<id>` | Listing page |
| `/api/properties` | JSON API (approved listings, supports the filters above) |
| `/my-favorites` | Saved listings (login required) |
| `/register`, `/login` | Accounts |
| `/dashboard`, `/add`, `/edit/<id>` | Owner area |
| `/admin` | Moderation panel (admin only) |
| `/healthz`, `/sitemap.xml`, `/robots.txt` | Health check and SEO |

## Roadmap and known limitations

- Password reset by e-mail and e-mail / phone verification
- Automated database backups and an admin export
- Featured / paid listings
- Automated tests in CI and a Tailwind build step instead of the CDN
- More languages, and neighborhood boundaries on the map

Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.

---

## Soomaali (Af-Soomaali)

**Bosaso Homes** waa website lagu raadiyo guryo, dhul, apartment-yo iyo dukaamo **kiro ama iib ah** oo ku yaal **Boosaaso, Soomaaliya**.

### Sidee u shaqeeyaa?
1. **Booqdaha** wuxuu furaa website-ka oo arkaa khariidad Boosaaso ah oo calaamad (pin) ka muuqato guri kasta iyo dhul kasta. Wuxuu ku raadin karaa **goobta (xaafadda)**, nooca (guri, dhul, apartment, ganacsi), kiro/iib, iyo qiimaha.
2. Marka uu furo liis, wuxuu arkaa sawirro badan (carousel), faahfaahin iyo goobta khariidadda.
3. Wuxuu riixaa **WhatsApp**, fariin diyaar ah oo ay ku jirto **ID-ga guriga** ayaa toos ugu furmaysa mulkiilaha. Website-ku lacag ma qaato.
4. **Mulkiilaha** wuxuu samaystaa akoon bilaash ah, wuxuu geliyaa liis (ilaa 6 sawir iyo goobta khariidadda), wuuna maamuli karaa ("la kiraystay/la iibiyay").
5. **Maamulka (admin)** ayaa dib u eega liis kasta ka hor intaan dadweynaha la tusin, wuxuuna siin karaa calaamadda **Verified 🛡️** liisaska la hubiyay.
6. Qof kasta wuxuu ku kaydin karaa liisaska uu jecel yahay qalbiga ❤ iyo bogga **Saved**.

Website-ku wuxuu leeyahay **Soomaali iyo English**, wuxuuna si fiican ugu shaqeeyaa mobile-ka.

### Sidaan u furo (local)?
```bash
pip install -r requirements.txt
python app.py
```
Kadib fur **http://127.0.0.1:5000**. Admin-ka local: `admin@bosaso.local` / `admin123`.

Si loogu rido online (Render + PostgreSQL + Cloudinary), fiiri qaybta [Deploying to Render](#deploying-to-render).
