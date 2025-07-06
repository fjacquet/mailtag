import streamlit as st
from loguru import logger

from main import start_classification_run


class StreamlitLogHandler:
    def __init__(self, placeholder):
        self.placeholder = placeholder
        self.buffer = ""

    def write(self, message):
        self.buffer += message
        self.placeholder.text_area("Logs", self.buffer, height=400)


st.title("MailTag")

st.write("Welcome to MailTag! This is the Streamlit interface.")

provider = st.selectbox("Select a provider", ["imap", "gmail", "all"])
validate = st.checkbox("Dry run (read-only)")

if st.button("Start Classification"):
    st.info("Starting classification...")
    log_placeholder = st.empty()
    handler = StreamlitLogHandler(log_placeholder)
    logger.add(handler.write, level="INFO")

    try:
        start_classification_run(provider, validate)
        st.success("Classification complete!")
    except Exception as e:
        st.error(f"An error occurred: {e}")
    finally:
        logger.remove()
