"""Entry point.

Development:  python app.py
Production:   gunicorn "app:app" --bind 0.0.0.0:8000 --workers 2
"""
import os

from screener import create_app

app = create_app()

if __name__ == "__main__":
    # debug stays off unless you opt in: Flask debug mode must never be exposed publicly.
    app.run(
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
