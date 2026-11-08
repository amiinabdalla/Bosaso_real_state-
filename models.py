"""
Database models (Flask-SQLAlchemy).

Table and column names are identical to the previous raw-SQL version, so an
existing database (SQLite or PostgreSQL) keeps working. Only the new
`favorites` table is added automatically by db.create_all().
"""
from datetime import datetime, timezone

from sqlalchemy import Integer, TypeDecorator, UniqueConstraint
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class IntBool(TypeDecorator):
    """A real Python bool in the code, stored as 0/1 INTEGER in the database.

    Older databases created by this project store is_verified / is_admin as
    INTEGER. This type keeps them compatible on SQLite *and* PostgreSQL while
    the code only ever sees True / False.
    """
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else int(bool(value))

    def process_result_value(self, value, dialect):
        return None if value is None else bool(value)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(IntBool, nullable=False, default=False)
    created_at = db.Column(db.String(19), nullable=False, default=_now)

    properties = db.relationship("Property", back_populates="owner")
    favorites = db.relationship("Favorite", back_populates="user",
                                cascade="all, delete-orphan")


# --------------------------------------------------------------------------
class Property(db.Model):
    __tablename__ = "properties"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    # "Rent" | "Sale"   (the search filter calls this `status`)
    type = db.Column(db.String(10), nullable=False)
    # "House" | "Apartment" | "Land" | "Commercial"   (filter: `property_type`)
    category = db.Column(db.String(20), nullable=False)
    # City / town in Puntland (e.g. Bosaso, Garowe, Galkayo). Existing rows default to Bosaso.
    city = db.Column(db.String(40), nullable=False, default="Bosaso", server_default="Bosaso")
    neighborhood = db.Column(db.String(60), nullable=False)   # filter: `location`
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    whatsapp_number = db.Column(db.String(20), nullable=False)
    # Verification badge. Boolean in code, INTEGER 0/1 in the database.
    is_verified = db.Column(IntBool, nullable=False, default=False)
    created_at = db.Column(db.String(19), nullable=False, default=_now)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    # moderation state: pending | approved | rejected | closed
    status = db.Column(db.String(10), nullable=False, default="approved")

    owner = db.relationship("User", back_populates="properties")
    # One-to-many: a property has many images
    images = db.relationship("Image", back_populates="property",
                             cascade="all, delete-orphan", order_by="Image.id")
    favorites = db.relationship("Favorite", back_populates="property",
                                cascade="all, delete-orphan")

    def to_dict(self, favorite_ids=None, private=False):
        """Plain dict used by the templates and the JSON API.

        private=True adds owner details + image ids (dashboard / admin / edit).
        Never use private=True for the public API.
        """
        data = {
            "id": self.id,
            "title": self.title,
            "description": self.description or "",
            "price": self.price,
            "type": self.type,
            "category": self.category,
            "city": self.city,
            "neighborhood": self.neighborhood,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "whatsapp_number": self.whatsapp_number,
            "is_verified": bool(self.is_verified),
            "created_at": self.created_at,
            "status": self.status,
            "images": [img.image_url for img in self.images],
            "is_favorite": bool(favorite_ids and self.id in favorite_ids),
        }
        if private:
            data["owner_id"] = self.owner_id
            data["owner_name"] = self.owner.name if self.owner else None
            data["owner_email"] = self.owner.email if self.owner else None
            data["image_list"] = [{"id": img.id, "url": img.image_url} for img in self.images]
        return data


# --------------------------------------------------------------------------
class Image(db.Model):
    """One photo of a property (table name kept from the first version)."""
    __tablename__ = "property_images"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    image_url = db.Column(db.Text, nullable=False)

    property = db.relationship("Property", back_populates="images")


# --------------------------------------------------------------------------
class Favorite(db.Model):
    """A user's saved (hearted) property. One row per user + property."""
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "property_id", name="uq_favorite_user_property"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    created_at = db.Column(db.String(19), nullable=False, default=_now)

    user = db.relationship("User", back_populates="favorites")
    property = db.relationship("Property", back_populates="favorites")
