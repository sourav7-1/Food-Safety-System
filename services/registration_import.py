import csv
import hashlib
import io
import re
import secrets
import urllib.request
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse

from sqlalchemy import func
from werkzeug.utils import secure_filename

from extensions import db
from models import (
    Area,
    FoodCategory,
    FoodItem,
    Role,
    Stall,
    StreetFoodStallRegistration,
    User,
    Vendor,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHOTO_CACHE_DIR = PROJECT_ROOT / "static" / "uploads" / "stall_photos"
MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def _clean(value):
    return (value or "").strip()


def _yes_no(value):
    return "Yes" if _clean(value).lower() == "yes" else "No"


def _price(value):
    normalized = _clean(value).translate(BANGLA_DIGITS).replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", normalized)
    return Decimal(match.group()) if match else None


def _submitted_at(value):
    clean_value = re.sub(r"\s+GMT[+-]\d+(?::\d+)?$", "", _clean(value))
    return datetime.strptime(clean_value, "%Y/%m/%d %I:%M:%S %p")


def _city_for(area):
    lowered = area.lower()
    if "savar" in lowered:
        return "Savar"
    if "dhaka" in lowered or "daffodil" in lowered:
        return "Dhaka"
    return "Unspecified"


def _source_key(row):
    material = "|".join(
        (_clean(row[0]), _clean(row[2]), _clean(row[3]))
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _identity_key(value):
    return hashlib.sha256(_clean(value).encode("utf-8")).hexdigest()[:12]


DRIVE_ID_PATTERN = re.compile(r"(?:[?&]id=|/file/d/)([\w-]+)")


def normalize_photo_url(value):
    """Turn a Google Drive share/view link into a directly embeddable URL.

    Forms responses store the uploaded photo as a share link such as
    ``drive.google.com/u/0/open?usp=forms_web&id=FILE_ID`` or
    ``drive.google.com/file/d/FILE_ID/view``, neither of which an <img> tag
    can load directly. Google's ``uc?export=view`` endpoint serves the raw
    file for links that are shared "anyone with the link".
    """
    url = _clean(value)
    if not url:
        return None
    host = urlparse(url).netloc.lower()
    if host == "drive.google.com" or host.endswith(".drive.google.com"):
        match = DRIVE_ID_PATTERN.search(url)
        if match:
            return f"https://drive.google.com/uc?export=view&id={match.group(1)}"
    return url


def cache_photo(source_url, stall_code):
    """Download a stall photo once and serve it from our own static files.

    Providers such as Google Drive send ``Cross-Origin-Resource-Policy:
    same-site`` on their image responses, which makes browsers refuse to
    load the image in an <img> tag on any other origin -- a plain HTTP
    fetch (this function, or a quick server-side check) succeeds even
    though every visitor's browser silently fails to render it. Caching a
    local copy avoids depending on the source host's CORP policy at all.
    """
    url = normalize_photo_url(source_url)
    if not url or not url.startswith(("http://", "https://")):
        return url

    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            content_type = (
                response.headers.get("Content-Type", "")
                .split(";")[0]
                .strip()
                .lower()
            )
            extension = PHOTO_EXTENSION_BY_CONTENT_TYPE.get(content_type)
            if extension is None:
                return None
            data = response.read(MAX_PHOTO_BYTES + 1)
            if len(data) > MAX_PHOTO_BYTES:
                return None
    except (URLError, OSError, ValueError):
        return None

    filename = secure_filename(f"{stall_code}{extension}") or None
    if filename is None:
        return None
    PHOTO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (PHOTO_CACHE_DIR / filename).write_bytes(data)
    return f"/static/uploads/stall_photos/{filename}"


def import_registration_zip(zip_path):
    vendor_role = Role.query.filter(
        func.lower(Role.role_name) == "vendor"
    ).one()
    created = 0
    skipped = 0

    with zipfile.ZipFile(zip_path) as archive:
        csv_names = [
            name for name in archive.namelist() if name.lower().endswith(".csv")
        ]
        if len(csv_names) != 1:
            raise ValueError("The ZIP must contain exactly one CSV file.")
        content = archive.read(csv_names[0]).decode("utf-8-sig")

    rows = list(csv.reader(io.StringIO(content)))
    if not rows or len(rows[0]) < 16:
        raise ValueError("The registration CSV header is invalid.")

    try:
        for row in rows[1:]:
            if not any(_clean(value) for value in row):
                continue
            if len(row) < 16:
                raise ValueError("A registration row has fewer than 16 columns.")

            timestamp = _clean(row[0])
            phone = _clean(row[2])
            stall_name = _clean(row[3])
            exists = StreetFoodStallRegistration.query.filter_by(
                source_timestamp=timestamp,
                phone_number=phone,
                stall_name=stall_name,
            ).first()
            if exists:
                skipped += 1
                continue

            registration = StreetFoodStallRegistration(
                submitted_at=_submitted_at(timestamp),
                vendor_name=_clean(row[1]),
                phone_number=phone,
                stall_name=stall_name,
                area=_clean(row[4]),
                full_address=_clean(row[5]),
                food_category=_clean(row[6]),
                food_items=_clean(row[7]),
                average_price_bdt=_clean(row[8]),
                food_covered=_yes_no(row[9]),
                clean_water_used=_yes_no(row[10]),
                waste_bin_available=_yes_no(row[11]),
                vendor_uses_gloves=_yes_no(row[12]),
                payment_method=_clean(row[13]) or None,
                stall_photo_url=_clean(row[14]) or None,
                additional_comments=_clean(row[15]) or None,
                source_timestamp=timestamp,
            )
            db.session.add(registration)

            source_key = _source_key(row)
            area_name = _clean(row[4])
            area = Area.query.filter(
                func.lower(Area.area_name) == area_name.lower(),
                func.lower(Area.city) == _city_for(area_name).lower(),
                Area.zone == "",
            ).first()
            if area is None:
                area = Area(
                    area_name=area_name,
                    city=_city_for(area_name),
                    zone="",
                )
                db.session.add(area)
                db.session.flush()

            # Keyed by phone (when present) rather than the per-row source
            # key, so re-importing a later submission from the same vendor
            # (different timestamp, e.g. a correction) reuses their
            # existing account instead of creating a duplicate one.
            vendor_key = _identity_key(phone) if phone else source_key
            email = f"imported.vendor.{vendor_key}@local.invalid"
            user = User.query.filter_by(email=email).first()
            if user is None:
                usable_phone = (
                    phone
                    if phone and User.query.filter_by(phone=phone).first() is None
                    else None
                )
                user = User(
                    role_id=vendor_role.role_id,
                    full_name=_clean(row[1]),
                    email=email,
                    phone=usable_phone,
                    status="inactive",
                )
                user.set_password(secrets.token_urlsafe(32))
                db.session.add(user)
                db.session.flush()

            vendor = Vendor.query.filter_by(user_id=user.user_id).first()
            if vendor is None:
                vendor = Vendor(
                    user_id=user.user_id,
                    business_name=_clean(row[1]),
                    license_number=f"CSV-{source_key.upper()}",
                )
                db.session.add(vendor)
                db.session.flush()

            stall_code = f"CSV-{source_key.upper()}"
            stall = Stall.query.filter_by(stall_code=stall_code).first()
            if stall is None:
                stall = Stall(
                    vendor_id=vendor.vendor_id,
                    area_id=area.area_id,
                    stall_name=stall_name,
                    stall_code=stall_code,
                    address=_clean(row[5]),
                    photo_url=cache_photo(row[14], stall_code),
                    status="active",
                )
                db.session.add(stall)
                db.session.flush()

            category_names = [
                part.strip()
                for part in _clean(row[6]).split(";")
                if part.strip()
            ]
            category = None
            if category_names:
                category = FoodCategory.query.filter(
                    func.lower(FoodCategory.category_name)
                    == category_names[0].lower()
                ).first()
            if category is None:
                category = FoodCategory.query.order_by(
                    FoodCategory.category_id
                ).first()

            item_name = _clean(row[7])[:150]
            if category and item_name:
                existing_item = FoodItem.query.filter_by(
                    stall_id=stall.stall_id,
                    category_id=category.category_id,
                    item_name=item_name,
                ).first()
                if existing_item is None:
                    db.session.add(
                        FoodItem(
                            stall_id=stall.stall_id,
                            category_id=category.category_id,
                            item_name=item_name,
                            price=_price(row[8]),
                            is_available=True,
                        )
                    )
            created += 1

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return created, skipped
