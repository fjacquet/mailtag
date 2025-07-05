# Design Principles

This document outlines the best practices for Python coding and `uv` usage in this project.

## Python Best Practices

- **Follow PEP 8:** Adhere to the [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guide for Python code.
- **Use a Linter and Formatter:** Use `ruff` to enforce code style and quality.
- **Write Tests:** All new code should be accompanied by tests. Use `pytest`, `pytest-mock`, and `faker` for writing and running tests.
- **Use `pendulum` for testing**: For precise control over date and time in tests. This is crucial for testing time-sensitive logic, allowing you to "freeze" time or travel to specific points in time.
- **Use Type Hinting:** Use type hints to improve code clarity and catch errors early.
- **Keep Functions Small:** Functions should be small and do one thing.
- **Use Virtual Environments:** Use `uv` to create and manage virtual environments.
- **Use `loguru` for Logging:** Use the `loguru` library for all logging purposes.
- **Quality Checks**: Run `uv run yamlfix src ; uv run ruff check --fix` to ensure code quality

## `uv` Best Practices

- **Use `pyproject.toml`:** Define all project dependencies and metadata in `pyproject.toml`.
- **Use Lock Files:** Use `uv.lock` to ensure reproducible builds.
- **Use `uv` for all package management:** Use `uv` to install, update, and remove packages.
- **Keep Dependencies Up-to-Date:** Regularly update dependencies to their latest versions.
