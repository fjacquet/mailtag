"""
Webhook entry point for the MailTag email classification API.

Usage:
    uvicorn webhook:app --reload
    # or (preferred)
    python src/main.py serve
"""

from mailtag.api import create_app

app = create_app()
