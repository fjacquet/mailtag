# Design Principles

This document outlines the best practices for Python coding and `uv` usage in this project.

## Python Best Practices

- **Follow PEP 8 and PEP 257:** Adhere to the [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guide for Python code and [PEP 257](https://www.python.org/dev/peps/pep-0008/) for docstring conventions.
- **Automate Code Quality Checks:** Use `ruff` for linting and formatting. Integrate `ruff` into your Continuous Integration (CI) pipeline to ensure all code adheres to style and quality standards automatically. Consider adding pre-commit hooks to automate formatting and linting before commits.
- **Comprehensive Testing Strategy:** All new code should be accompanied by tests. Use `pytest` for unit and integration tests, `pytest-mock` for mocking, and `faker` for generating realistic test data. Aim for high test coverage.
- **Precise Date and Time Handling in Tests:** For precise control over date and time in tests, use `pendulum` or `freezegun`. This is crucial for testing time-sensitive logic, allowing you to "freeze" time or travel to specific points in time.
- **Leverage Type Hinting:** Use type hints extensively to improve code clarity, enable static analysis, and catch potential errors early during development. Consider using `mypy` for static type checking in your CI pipeline.
- **Prioritize High-Level Libraries:** For complex protocols (e.g., IMAP, HTTP), prefer robust, high-level third-party libraries (e.g., `IMAPClient`, `httpx`, `requests`) over low-level standard library equivalents. This leads to cleaner, more readable, and less error-prone code, reducing the burden of handling intricate protocol details.
- **Effective Resource Management with `contextlib`:** For resources that need reliable setup and teardown (e.g., file handles, network connections, database sessions), use the `contextlib` module (`@contextmanager`, `closing`, or `suppress`) to create clean, reusable context managers. This ensures resources are properly acquired and released, even in the event of exceptions.
- **Non-Regression Testing as a Standard Practice:** Before finalizing any set of changes, run the entire test suite (`uv run pytest`) to ensure that existing functionality has not been broken. This is a critical step to prevent regressions and maintain code stability.
- **Adhere to the Single Responsibility Principle (SRP):** Functions and classes should be small, focused, and ideally do "one thing" well. This improves readability, maintainability, and reusability.
- **Standardize Virtual Environment Management:** Use `uv` to create, manage, and isolate project dependencies within virtual environments. This prevents dependency conflicts and ensures consistent development environments.
- **Centralized and Configurable Logging:** Use the `loguru` library for all logging purposes due to its simplicity, powerful features, and flexible configuration. Ensure logging levels are appropriately used (DEBUG, INFO, WARNING, ERROR, CRITICAL) and consider externalizing logging configuration for easier management.

### Testing Best Practices

- **Correct Patch Targets for Mocks:** When using `pytest-mock`, always patch the object in the namespace where it is *used* (where it's imported or accessed), not where it is defined. For example, to mock `os.path.exists` in `mailtag.gmail_auth`, the patch target should be `mailtag.gmail_auth.os.path.exists`.
- **Integrate `loguru` with `pytest` for Log Capture:** To capture `loguru` output with `pytest`'s `caplog` fixture, configure a handler in `tests/conftest.py` to propagate `loguru` logs to `pytest`. This allows for assertion of log messages within tests.
- **Specific Mocks for Configuration Objects:** When mocking configuration objects, especially those interacting with other libraries (like `loguru` or database clients), avoid generic `MagicMock` instances if the mock needs specific behavior. Instead, provide a mock that has the necessary attributes and methods, or use a real instance of the configuration object with controlled parameters (e.g., `LoggingConfig(level="INFO", file="test.log")`). This leads to more reliable and predictable tests.
- **Test for Precise Exception Types:** Be aware of and test for the specific exception types that libraries and your own code raise. For example, `argparse` raises `SystemExit` for invalid command-line arguments, not `ValueError`. This ensures robust error handling.
- **Automated Quality Checks:** Integrate automated quality checks into your development workflow. Run commands like `uv run yamlfix src ; uv run ruff check --fix` as part of pre-commit hooks or CI/CD pipelines to ensure consistent code style and identify issues early.
- **Design for Testability:** Write code that is inherently testable. This often means preferring dependency injection, avoiding global state, and breaking down complex logic into smaller, isolated units.

### CLI Design Best Practices

- **Flexible and User-Friendly CLIs:** Design command-line interfaces to be flexible and intuitive, allowing users to control the application's behavior through clear options and arguments. Use libraries like `click` or `argparse` effectively, providing helpful `--help` messages, default values, and validation.

## `uv` Best Practices (Enhanced)

- **Centralized Dependency Management with `pyproject.toml`:** Define all project dependencies, scripts, and metadata in `pyproject.toml`. This is the modern standard for Python project configuration.
- **Reproducible Builds with Lock Files:** Utilize `uv.lock` to ensure exact and reproducible dependency installations across all environments (development, testing, production). This prevents "it works on my machine" issues.
- **Exclusive Use of `uv` for Package Management:** Use `uv` exclusively for all package management operations, including installing, updating, removing, and resolving dependencies. This maintains consistency and leverages `uv`'s performance benefits.
- **Regular Dependency Updates and Security Scanning:** Regularly update dependencies to their latest stable versions to benefit from bug fixes, new features, and security patches. Consider integrating tools for automated dependency security scanning.
- **Efficient Environment Management:** Leverage `uv`'s speed for creating and switching between virtual environments. Encourage developers to use distinct environments for different feature branches or tasks to maintain isolation.
