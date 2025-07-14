
# Fast Parse Specification

This document outlines a new, two-pass approach for processing emails from an IMAP server. The goal is to improve performance by quickly handling emails from known senders and deferring more resource-intensive AI analysis.

## Pass 1: Fast Classification and Move

1. **Fetch Folder Hierarchy:**
    * Before processing emails, the application will fetch the complete folder (mailbox) hierarchy from the IMAP server.
    * This hierarchy will be saved to a local, structured file (e.g., `data/imap_folders.json`) to serve as a cache and for reference.
    * **Cache Management:** The cache will be refreshed if it's older than 24 hours or if the file does not exist, ensuring folder structure remains up-to-date.

2. **Batch Fetch Senders:**
    * The application will fetch a batch of emails (e.g., 500-1000) from the INBOX.
    * For each email in the batch, it will only fetch the `From` header. This batching leverages IMAP's ability to efficiently fetch specific headers for multiple UIDs in a single command.

3. **Check Against Sender Database:**
    * The sender's email address (or derived domain, based on configuration) of each email will be compared against the known senders in `db/sender_classification_db.json`.

4. **Immediate Move:**
    * If a sender is found in the database and has a valid classification, the email will be moved to the corresponding target folder immediately, without downloading the full email body.
    * **Error Handling:** If the target folder specified in the database does not exist on the IMAP server, the email will remain in the INBOX and be passed to Pass 2 for potential re-classification or manual handling.

## Pass 2: AI Classification

1. **Process Remaining Emails:**
    * Emails that were not moved in Pass 1 (i.e., those from unknown senders, unclassified known senders, or those whose target folder was invalid) will be processed by the AI classification logic.
    * This involves fetching the full email content (all headers and body).

2. **AI Analysis:**
    * The AI classifier will analyze the email content to determine the appropriate classification.
    * **Fallback Strategy:** If the AI classifier returns a low confidence score or fails to classify an email, the email will be moved to a designated "Unclassified" folder (or remain in INBOX for manual review).

3. **Update Database and Move:**
    * The new classification for the sender will be added to or updated in `db/sender_classification_db.json`.
    * **Re-classification Policy:** Pass 2's classification for a sender will always override any existing, less specific classification in the database, allowing for refinement based on full content analysis.
    * The email will then be moved to the appropriate folder.

## Benefits

* **Improved Performance:** By handling known sereanders in a lightweight first pass, the overall processing time should be significantly reduced. We aim for at least a 30% reduction in processing time for high-volume inboxes.
* **Reduced Resource Usage:** Fewer emails will require full content download and AI analysis, saving bandwidth and computational resources. This also contributes to better IMAP server load.
* **Faster Feedback Loop:** Users will see emails from known senders being sorted more quickly, enhancing the user experience.
* **Enhanced Scalability:** The two-pass system inherently scales better, as the more resource-intensive AI analysis is reserved for a smaller subset of emails.
