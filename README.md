# Bosaso Homes – Real Estate & Land Marketplace (Flask)

## Run locally
    pip install -r requirements.txt
    python app.py            # http://127.0.0.1:5000
Local admin login (dev only): admin@bosaso.local / admin123

## Deploy on Render
1. Push this folder to a GitHub repo (the .gitignore keeps the .db and uploads out).
2. Render > New > Blueprint > select the repo (uses render.yaml).
3. Fill in ADMIN_EMAIL and ADMIN_PASSWORD when asked. Optional: ADMIN_WHATSAPP.
4. Open the site, log in with that email/password, and use /admin to approve listings.

Environment variables: SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_WHATSAPP,
DATA_DIR (where the DB + photos live), SEED_SAMPLES (0/1), BRAND_NAME.
