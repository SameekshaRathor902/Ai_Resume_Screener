"""Application factory."""
import logging

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import ratelimit
from .config import Config
from .routes import bp
from .services.gemini import GeminiClient
from .services.skills import load_custom_skills


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="../templates")
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # The Gemini client is optional: without a key the keyword scorer still works.
    api_key = app.config["GOOGLE_API_KEY"]
    app.extensions["gemini"] = (
        GeminiClient(
            api_key=api_key,
            model=app.config["GEMINI_MODEL"],
            embed_model=app.config["GEMINI_EMBED_MODEL"],
            timeout=app.config["GEMINI_TIMEOUT"],
        )
        if api_key
        else None
    )
    if not api_key:
        app.logger.warning("GOOGLE_API_KEY is not set: AI features are disabled.")

    ratelimit.init_app(app)

    skills_file = app.config["CUSTOM_SKILLS_FILE"]
    if skills_file:
        try:
            count = load_custom_skills(skills_file)
            app.logger.info("Loaded %d custom skill lines from %s", count, skills_file)
        except OSError as exc:
            app.logger.warning("Could not read CUSTOM_SKILLS_FILE (%s): %s", skills_file, exc.strerror)

    app.register_blueprint(bp)
    return app
