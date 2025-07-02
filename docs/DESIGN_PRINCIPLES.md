# Design Principles

This document outlines the best practices for Python coding and `uv` usage in this project.

## Python Best Practices

- **Follow PEP 8:** Adhere to the [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guide for Python code.
- **Use a Linter and Formatter:** Use `ruff` to enforce code style and quality.
- **Write Tests:** All new code should be accompanied by tests. Use `pytest` for writing and running tests.
- **Use Type Hinting:** Use type hints to improve code clarity and catch errors early.
- **Keep Functions Small:** Functions should be small and do one thing.
- **Use Virtual Environments:** Use `uv` to create and manage virtual environments.

## `uv` Best Practices

- **Use `pyproject.toml`:** Define all project dependencies and metadata in `pyproject.toml`.
- **Use Lock Files:** Use `uv.lock` to ensure reproducible builds.
- **Use `uv` for all package management:** Use `uv` to install, update, and remove packages.
- **Keep Dependencies Up-to-Date:** Regularly update dependencies to their latest versions.
