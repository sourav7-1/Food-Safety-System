import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL


load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = (
        os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    )
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    UPLOAD_FOLDER = os.getenv(
        "UPLOAD_FOLDER",
        str(Path(__file__).resolve().parent / "static" / "uploads" / "evidence"),
    )

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "smart_street_food_safety")

    # Outgoing mail (used to send email-verification links).
    MAIL_SERVER = os.getenv("MAIL_SERVER", "")
    MAIL_PORT = int(os.getenv("MAIL_PORT") or "587")
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "false").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER") or MAIL_USERNAME

    # How long an email-verification link stays valid, in seconds.
    EMAIL_VERIFICATION_MAX_AGE = int(
        os.getenv("EMAIL_VERIFICATION_MAX_AGE_SECONDS") or str(24 * 60 * 60)
    )

    # Cloudflare Turnstile (registration bot protection). Left blank,
    # verification is skipped so local development keeps working.
    TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")
    TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")

    # Flask-Limiter storage backend for register/login rate limits.
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or URL.create(
        drivername="mysql+pymysql",
        username=MYSQL_USER,
        password=MYSQL_PASSWORD,
        host=MYSQL_HOST,
        port=int(MYSQL_PORT),
        database=MYSQL_DATABASE,
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
