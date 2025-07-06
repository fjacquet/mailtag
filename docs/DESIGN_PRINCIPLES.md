# Design Principles

This document outlines the best practices for Python coding and `uv` usage in this project.

## Python Best Practices

- **Follow PEP 8:** Adhere to the [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guide for Python code.
- **Use a Linter and Formatter:** Use `ruff` to enforce code style and quality.
- **Write Tests:** All new code should be accompanied by tests. Use `pytest`, `pytest-mock`, and `faker` for writing and running tests.
- **Use `pendulum` for testing**: For precise control over date and time in tests. This is crucial for testing time-sensitive logic, allowing you to "freeze" time or travel to specific points in time.
- **Use Type Hinting:** Use type hints to improve code clarity and catch errors early.
- **Prefer High-Level Libraries over Standard Libs**: For complex protocols like IMAP, prefer robust, high-level third-party libraries (e.g., `IMAPClient`) over the low-level standard library equivalent (e.g., `imaplib`). This leads to cleaner, more readable, and less error-prone code.
- **Use `contextlib` for Resource Management**: For resources that need to be reliably set up and torn down (like network connections), use the `contextlib` module (`@contextmanager` or `suppress`) to create clean, reusable context managers. This ensures resources are properly handled, even in the event of errors.
- **Run Non-Regression Tests**: Before finalizing any set of changes, run the entire test suite (`uv run pytest`) to ensure that existing functionality has not been broken. This is a critical step to prevent regressions.
- **Keep Functions Small:** Functions should be small and do one thing.
- **Use Virtual Environments:** Use `uv` to create and manage virtual environments.
- **Use `loguru` for Logging:** Use the `loguru` library for all logging purposes.

### Testing Best Practices

- **Use Correct Patch Targets**: When using `pytest-mock`, always patch the object in the namespace where it is *used*, not where it is defined. For example, to mock `os.path.exists` in `mailtag.gmail_auth`, the patch target should be `mailtag.gmail_auth.os.path.exists`.
- **Integrate `loguru` with `pytest`**: To capture `loguru` output with `pytest`'s `caplog` fixture, you must configure a handler in `tests/conftest.py` to propagate `loguru` logs to `pytest`.
- **Avoid Generic Mocks for Configs**: When mocking configuration objects that interact with other libraries (like `loguru`), avoid using a generic `MagicMock`. Instead, provide a mock that has the necessary attributes and methods, or use a real instance of the configuration object (e.g., `LoggingConfig(level="INFO", file="test.log")`).
- **Test for the Correct Exceptions**: Be aware of the specific exceptions that libraries raise. For example, `argparse` raises `SystemExit` for invalid command-line arguments, not `ValueError`.
- **Run Non-Regression Tests**: Before finalizing any set of changes, run the entire test suite (`uv run pytest`) to ensure that existing functionality has not been broken. This is a critical step to prevent regressions.
- **Flexible CLI:** Design command-line interfaces to be flexible, allowing users to control the application's behavior, such as selecting specific providers or modes of operation.
- **Quality Checks**: Run `uv run yamlfix src ; uv run ruff check --fix` to ensure code quality

## `uv` Best Practices

- **Use `pyproject.toml`:** Define all project dependencies and metadata in `pyproject.toml`.
- **Use Lock Files:** Use `uv.lock` to ensure reproducible builds.
- **Use `uv` for all package management:** Use `uv` to install, update, and remove packages.
- **Keep Dependencies Up-to-Date:** Regularly update dependencies to their latest versions.
