import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


def create_app():

    app = Flask(__name__)

    # -----------------------------------------------------
    # Application configuration
    # -----------------------------------------------------

    app.config["SECRET_KEY"] = os.getenv(
        "SECRET_KEY",
        "dev-secret-key-change-this"
    )

    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite:///appex_payroll.db"
    )

    # Render/PostgreSQL compatibility
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://",
            "postgresql://",
            1
        )

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Secure session settings
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Enable secure cookies on HTTPS deployments
    app.config["SESSION_COOKIE_SECURE"] = (
        os.getenv("FLASK_ENV") == "production"
    )

    # -----------------------------------------------------
    # Initialize database
    # -----------------------------------------------------

    db.init_app(app)

    # -----------------------------------------------------
    # Register routes
    # -----------------------------------------------------

    from .routes import bp

    app.register_blueprint(bp)

    # -----------------------------------------------------
    # Create missing database tables
    # -----------------------------------------------------

    with app.app_context():

        # Import models so SQLAlchemy knows about them
        from . import models

        db.create_all()

    return app
