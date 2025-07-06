#!/usr/bin/env python3

"""
Webhook entry point for the mailtag email classification script.
"""

from fastapi import FastAPI

app = FastAPI()


@app.post("/webhook")
async def webhook():
    """Webhook endpoint to trigger email classification."""
    # This is a placeholder for the webhook logic.
    return {"message": "Webhook received"}
