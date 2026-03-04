# Mailtag Project Management

## **Phase 4: IMAP Fast Parse Documentation**

This phase focuses on documenting the IMAP Fast Parse implementation for better maintainability and future development.

- [x] **IMAP Folder-Based Classification:**
  - [x] Regenerate `imap_folders.json` at application startup from actual IMAP folders
  - [x] Use IMAP folder hierarchy for categorization decisions instead of static schema
  - [x] Enhance suggestion engine to propose subfolders under parent folders only
  - [x] Update classifier to respect folder hierarchy when making suggestions
  - [x] Add documentation for the folder-based classification approach
  
- [ ] **Core Documentation:**
  - [x] Document the two-pass classification strategy
  - [x] Document the batching system implementation
  - [x] Document header and body processing logic
  - [ ] Document error handling and recovery mechanisms

- [ ] **Performance Documentation:**
  - [x] Document performance considerations and tuning options
  - [ ] Document memory management strategies
  - [ ] Document known limitations and edge cases

- [ ] **API Documentation:**
  - [x] Document all public methods in `imap_service.py`
  - [x] Add usage examples for common scenarios
  - [x] Document configuration options and their impact

- [x] **Developer Guide:**
  - [x] Add a section on extending the IMAP functionality
  - [x] Document the test suite and how to add new tests
  - [x] Add troubleshooting guide for common issues

## **Phase 5: IMAP Fast Parse Improvements**

This phase focuses on implementing recommended improvements to enhance the IMAP Fast Parse functionality.

- [x] **Configuration Enhancements:**
  - [x] Make batch size configurable via `config.toml`
  - [x] Add configuration for retry attempts and delays
  - [x] Add option to enable/disable detailed logging

- [ ] **Performance Optimizations:**
  - [ ] Implement concurrent batch processing
  - [ ] Add support for streaming large email bodies
  - [x] Add metrics/monitoring for performance tracking

- [x] **Error Handling & Reliability:**
  - [x] Add retry mechanism for transient failures
  - [x] Implement circuit breaker pattern for IMAP operations
  - [x] Add detailed error logging and metrics

- [x] **Monitoring & Metrics:**
  - [x] Add performance metrics collection
  - [x] Implement health checks for IMAP connections
  - [x] Add monitoring for batch processing statistics

- [ ] **Code Quality:**
  - [ ] Add comprehensive unit tests for new features
  - [ ] Implement integration tests with a test IMAP server
  - [x] Add type hints and improve code documentation

## **Phase 6: Functional Refactoring**

This phase focuses on refactoring the codebase to align with functional programming principles as outlined in `docs/LAYOUT.md`.

- [ ] **`src/mailtag/core/` - Create Core Module:**
  - [ ] Create a `core` directory for pure, functional logic.
  - [ ] Create `logic.py` for business logic functions.
  - [ ] Create `types.py` for custom data types and structures.
- [ ] **`src/mailtag/infrastructure/` - Create Infrastructure Module:**
  - [ ] Create an `infrastructure` directory for impure code (I/O, side effects).
  - [ ] Move database interactions to `infrastructure/database.py`.
  - [ ] Move Gmail/IMAP services to `infrastructure/api_clients.py`.
  - [ ] Move file I/O operations to `infrastructure/file_io.py`.
- [ ] **Refactor `main.py`, `app.py`, `webhook.py`:**
  - [ ] Update entry points to orchestrate calls between the `core` and `infrastructure` layers.
- [ ] **Refactor `classifier.py`:**
  - [ ] Decompose `classify_email` into smaller, pure functions.
  - [ ] Use `returns` library for error handling (`Result`, `Maybe`).
- [ ] **Refactor `database.py`:**
  - [ ] Isolate pure data transformation logic from file I/O.
  - [ ] Use `returns` for file operations that can fail.
- [ ] **Refactor `gmail_service.py` and `imap_service.py`:**
  - [ ] Wrap API calls in functions that return `Result` or `Maybe`.
  - [ ] Separate data parsing/transformation from network requests.
- [ ] **Implement Property-Based Testing:**
  - [ ] Add `hypothesis` to the testing dependencies.
  - [ ] Create a `tests/property` directory.
  - [ ] Write property-based tests for key functions in `core/logic.py`.
- [x] **Update Type Hinting:**
  - [x] Ensure all functions have complete and accurate type hints using `typing`.
  - [x] Use `Callable` for functions passed as arguments.
- [ ] **Introduce `toolz` or `fn.py`:**
  - [ ] Select and add one of the libraries to the project dependencies.
  - [ ] Refactor data processing pipelines using `pipe` or `flow`.
- [ ] **Review and Refactor for Immutability:**
  - [ ] Replace mutable data structures with immutable counterparts where appropriate (e.g., `tuple` instead of `list`).
  - [ ] Use `frozen=True` for `dataclasses`.
- [ ] **Documentation:**
  - [ ] Update `README.md` and other relevant documentation to reflect the new functional architecture.
  - [ ] Document the usage of `returns`, `hypothesis`, and the chosen composition library.

## **Phase 7: Domain-Based Classification System**

This phase implements a revolutionary 3-pass classification system to reduce AI API calls by 80-90% and dramatically improve performance.

**Core Implementation (Phases 7.1-7.3) ✅ COMPLETED** - See Archived Tasks below for details.

### **Phase 7.4: Configuration and Settings**

- [ ] **Configuration Options:**
  - [ ] Add `enable_domain_classification: bool` to config
  - [ ] Add `max_emails_per_domain: int` (default: 3)
  - [ ] Add `domain_cache_size: int` (default: 1000)
  - [ ] Add `domain_similarity_threshold: float` (default: 0.8)
  - [ ] Add `non_commercial_domains_file: str` (default: "data/non_commercial_domains.yaml")
  - [ ] Add `log_non_commercial_encounters: bool` (default: true)

- [ ] **Domain Management Commands:**
  - [ ] Add CLI command to view domain mappings
  - [ ] Add CLI command to update domain classification
  - [ ] Add CLI command to rebuild domain database
  - [ ] Add CLI command to export/import domain mappings

### **Phase 7.5: Testing and Validation**

- [ ] **Unit Tests:**
  - [ ] Test domain extraction utilities
  - [ ] Test non-commercial domain detection
  - [ ] Test domain classification database methods
  - [ ] Test classifier domain-based classification method
  - [ ] Test email grouping and deduplication logic

- [ ] **Integration Tests:**
  - [ ] Test full 3-pass classification flow
  - [ ] Test domain classification with real email data
  - [ ] Test performance improvements (measure AI call reduction)
  - [ ] Test error handling and fallback scenarios

- [ ] **Performance Testing:**
  - [ ] Benchmark domain lookup vs AI classification speed
  - [ ] Measure AI call reduction percentage
  - [ ] Test with large email volumes
  - [ ] Validate memory usage and performance impact

### **Phase 7.6: Documentation and Monitoring**

- [ ] **Documentation Updates:**
  - [ ] Update main README with new 3-pass system
  - [ ] Document domain management commands
  - [ ] Add troubleshooting guide for domain classification
  - [ ] Update API documentation

- [ ] **Monitoring and Metrics:**
  - [ ] Add domain classification success rate metrics
  - [ ] Track AI call reduction percentage
  - [ ] Monitor domain cache hit rates
  - [ ] Add alerts for domain classification failures

---

## Archived Tasks

### Phase 1: Architecture Refactoring

- [x] **`main.py` - CLI Entry Point:**
  - [x] Move the CLI logic from `app.py` to `main.py`.
  - [x] Replace `argparse` with `click`.
- [x] **`app.py` - Streamlit UI:**
  - [x] Create a placeholder for the Streamlit application.
- [x] **`webhook.py` - Webhook Entry Point:**
  - [x] Create a placeholder for the webhook endpoint using `fastapi`.

### Phase 2: Dual Database Classification

- [x] **`database.py` - Dual DB Sytem:**
  - [x] Modify `ClassificationDatabase` to manage both `sender_classification_db.json` and `validated_classification_db.json`.
- [x] **`classifier.py` - Update AMSC Strategy:**
  - [x] Update the `classify_email` method to prioritize the validated DB over all other signals.
- [x] **`main.py` - Update CLI:**
  - [x] Restore the `--validate` flag to its original "dry run" functionality.
- [x] **`tests/` - Update Tests:**
  - [x] Update all relevant tests to reflect the new architecture and dual-database system.

### Phase 3: Fast Parse Implementation

- [x] **`config.py` & `config.toml` - Add Fast Parse Settings:**
- [x] **`imap_service.py` - Implement Fast Parse Methods:**
- [x] **`main.py` - Implement Two-Pass Orchestration:**
- [x] **Testing - Update and Add Tests:**
- [x] **Documentation - Update Project Documentation:**

### Phase 7: Domain-Based Classification System (Core Implementation)

- [x] **Phase 7.1: Database Extensions** - Extended ClassificationDatabase with domain classification methods, created comprehensive domain utilities, built migration script, added non-commercial domains configuration
- [x] **Phase 7.2: Classifier Updates** - Added domain-based classification method, integrated into main classification flow, implemented domain caching
- [x] **Phase 7.3: Task Runner Updates** - Implemented full 3-pass system (Pattern → Domain → AI), added email grouping by domain, batch processing, comprehensive error handling
