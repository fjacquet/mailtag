# Impact Analysis: Fast Parse Implementation (Reassessed)

This document analyzes the expected impact of implementing the "Fast Parse" specification, updated to reflect the detailed requirements including caching, batching, and specific error handling and fallback strategies.

## 1. Code Changes

The implementation will be more involved than initially estimated, touching several components.

### `src/mailtag/config.py`

New configuration options will be needed to control the new behavior:

- `fast_parse_batch_size`: The number of emails to fetch in the first pass (e.g., 500).
- `folder_cache_ttl_hours`: The time-to-live for the folder hierarchy cache (e.g., 24).
- `unclassified_folder_name`: The designated folder for emails the AI cannot confidently classify.

### `src/mailtag/imap_service.py`

This service will require the most significant changes:

- **Method Restructuring:** `get_emails` will be deprecated. New methods will be introduced:
  - `get_folder_hierarchy()`: Fetches the IMAP folder list and manages the JSON cache file (`data/imap_folders.json`), including TTL logic.
  - `get_email_senders(uids: list[str])`: Fetches only the `From` header for a given batch of email UIDs.
  - `get_full_emails(uids: list[str])`: Fetches the full content for the remaining emails for Pass 2.
- **`batch_move_emails`:** This method is confirmed and will be used for moving emails in both passes.

### `src/mailtag/database.py`

- No structural changes are required. However, its `find_sender` method will be called much more frequently and independently during Pass 1. Performance of this lookup will be more critical.

### `src/app.py` (or main orchestration logic)

- The core application workflow needs a complete overhaul to manage the two-pass system:
    1. Manage the folder cache, triggering a refresh if needed.
    2. Fetch all INBOX UIDs.
    3. Process UIDs in batches according to `fast_parse_batch_size`.
    4. For each batch, call `imap_service.get_email_senders`.
    5. Compare senders against the database.
    6. For matches, call `imap_service.batch_move_emails`. Keep track of UIDs that were not moved.
    7. After Pass 1, iterate through the remaining UIDs and process them with the existing AI classification logic (Pass 2), which will use `imap_service.get_full_emails`.
    8. Implement the AI fallback logic (moving to "Unclassified" folder).

## 2. Performance

- **Positive Impact:** The 30% processing time reduction target for high-volume inboxes seems achievable. This is primarily due to reduced network I/O (fetching only headers) and lower CPU/API usage from avoiding AI analysis on most emails.
- **Potential Bottlenecks & Considerations:**
  - **Cold Start:** On a new setup with an empty sender database, the Fast Parse method will be *slower* than the single-pass method due to the overhead of the two-pass orchestration. The performance benefit is directly proportional to the classification hit rate in `sender_classification_db.json`.
  - **IMAP Server Performance:** The efficiency of fetching headers for large batches of UIDs depends on the IMAP server's performance.

## 3. User Experience

- **Positive Impact:** The "faster feedback loop" is a key benefit. Users will see their inbox being organized much more quickly.
- **New UX Element:** The introduction of an "Unclassified" folder provides a clear place for users to review emails that the system could not handle automatically, which is an improvement over leaving them in the INBOX.

## 4. Error Handling

The implementation complexity increases due to more sophisticated error handling requirements:

- **Invalid Target Folder:** The logic to keep an email in the INBOX if its target folder from the database is invalid is critical.
- **Filesystem Errors:** The application must gracefully handle errors when reading or writing the `imap_folders.json` cache file.
- **IMAP Errors:** All batch operations (`get_email_senders`, `batch_move_emails`) must have robust error handling to prevent a single failed email from stopping an entire batch.

## 5. Testing

- **Expanded Scope:** The testing effort is larger than initially anticipated.
- **New Unit Tests:**
  - `get_folder_hierarchy` must be tested for cache logic (creation, expiration, and invalid file handling).
  - `get_email_senders` and `get_full_emails` need to be tested.
- **Integration Tests:** The end-to-end two-pass orchestration in `app.py` is critical to test. This includes:
  - Verifying that emails are correctly moved in Pass 1.
  - Verifying that remaining emails are correctly passed to Pass 2.
  - Testing the fallback logic for both invalid target folders and low AI confidence.
  - Testing the re-classification policy.

## Conclusion

The implementation of the detailed Fast Parse specification is a more significant undertaking than first estimated. However, the added robustness, performance gains, and improved user experience justify the increased complexity. The plan is sound, but development and testing will require careful attention to the new orchestration logic and error handling cases.
