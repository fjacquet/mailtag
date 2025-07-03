import streamlit as st
import pandas as pd
from pathlib import Path

from mailtag.classifier import Classifier
from mailtag.config import CONFIG
from mailtag.database import ClassificationDatabase
from mailtag.mail_service import MailService

st.set_page_config(page_title="MailTag Classifier", layout="wide")

st.title("📧 MailTag Email Classifier")

st.info(
    "This tool scans your Apple Mail inbox, classifies emails using a local LLM, "
    "and suggests categories. No data ever leaves your machine."
)

# --- State Management ---
if "results" not in st.session_state:
    st.session_state.results = []
if "is_running" not in st.session_state:
    st.session_state.is_running = False


def run_classification():
    """
    Generator function that processes emails and yields results for real-time updates.
    """
    st.session_state.is_running = True
    st.session_state.results = []

    try:
        db_path = Path("db/sender_classification_db.json")
        database = ClassificationDatabase(db_path)
        mail_service = MailService()
        classifier = Classifier(CONFIG, database)
    except FileNotFoundError as e:
        st.error(f"Initialization failed: {e}")
        st.session_state.is_running = False
        return

    emails = mail_service.get_inbox_emails()
    if not emails:
        st.warning("No emails found in the inbox.")
        st.session_state.is_running = False
        return

    progress_bar = st.progress(0, text="Starting analysis...")
    total_emails = len(emails)

    for i, email in enumerate(emails):
        body = mail_service.get_email_body(email)
        if not body:
            category = "(Could not read body)"
        else:
            category = classifier.classify_email(email, body)

        result = {
            "Subject": email.subject,
            "Sender": email.sender_address,
            "Category": category,
        }
        st.session_state.results.append(result)

        # Update progress bar
        progress_text = f"Processing email {i + 1}/{total_emails}: {email.subject}"
        progress_bar.progress((i + 1) / total_emails, text=progress_text)
        
        # Yield for real-time display
        yield

    progress_bar.progress(1.0, text="Analysis complete.")
    st.session_state.is_running = False


# --- UI Layout ---
col1, col2, _ = st.columns([1, 1, 3])

with col1:
    start_button = st.button(
        "Start Classification",
        type="primary",
        disabled=st.session_state.is_running,
        use_container_width=True,
    )

with col2:
    stop_button = st.button(
        "Stop", disabled=not st.session_state.is_running, use_container_width=True
    )

if start_button:
    st.session_state.results = []
    placeholder = st.empty()
    
    # This will consume the generator and update the UI
    for _ in run_classification():
        with placeholder.container():
            st.dataframe(
                pd.DataFrame(st.session_state.results), use_container_width=True
            )

if stop_button:
    st.session_state.is_running = False
    st.warning("Classification stopped by user.")
    # This is a simple stop; a more robust implementation might use threads.

# Display final results if not running
if not st.session_state.is_running and st.session_state.results:
    st.header("Classification Results")
    st.dataframe(pd.DataFrame(st.session_state.results), use_container_width=True)
