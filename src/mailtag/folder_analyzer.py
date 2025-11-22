"""
Module for analyzing IMAP folder structure for classification purposes.
"""

import json
from pathlib import Path

from loguru import logger


class FolderAnalyzer:
    """Analyzes IMAP folder structure for classification purposes."""

    def __init__(self, folder_path: Path = Path("data/imap_folders.json")):
        self.folder_path = folder_path
        self.folders = self._load_folders()
        self.parent_folders = self._identify_parent_folders()
        self.leaf_folders = self._identify_leaf_folders()

    def _load_folders(self) -> list[str]:
        """Load folders from the JSON file."""
        if not self.folder_path.exists():
            logger.warning(f"Folder file {self.folder_path} not found")
            return []

        try:
            with self.folder_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"Could not parse folder file {self.folder_path}")
            return []

    def _identify_parent_folders(self) -> set[str]:
        """Identify parent folders (those that have subfolders)."""
        parent_folders = set()

        for folder in self.folders:
            if "/" in folder:
                # Get all parent levels in the hierarchy
                parts = folder.split("/")
                for i in range(len(parts) - 1):
                    parent = "/".join(parts[: i + 1])
                    parent_folders.add(parent)

        return parent_folders

    def _identify_leaf_folders(self) -> list[str]:
        """Identify leaf folders (those without subfolders)."""
        # A folder is a leaf if it's not a parent to any other folder
        return [folder for folder in self.folders if folder not in self.parent_folders]

    def get_all_categories(self) -> list[str]:
        """Get all available categories from the folder structure.

        Returns all folders (both parent and leaf folders) as valid classification targets.
        This allows emails to be classified into parent folders when they don't fit into
        a specific subfolder.
        """
        return self.folders

    def get_parent_folders(self) -> list[str]:
        """Get all parent folders."""
        return list(self.parent_folders)

    def is_valid_parent_folder(self, folder: str) -> bool:
        """Check if a folder is a valid parent folder (can have subfolders)."""
        return folder in self.parent_folders

    def get_subfolders(self, parent: str) -> list[str]:
        """Get all subfolders for a given parent folder."""
        return [folder for folder in self.folders if folder.startswith(f"{parent}/")]

    def is_valid_folder(self, folder: str) -> bool:
        """Check if a folder exists in the hierarchy."""
        return folder in self.folders

    def is_parent_folder(self, folder: str) -> bool:
        """Check if a folder is a parent folder (has subfolders)."""
        return folder in self.parent_folders

    def get_parent_for_subfolder(self, subfolder: str) -> str:
        """Get the parent folder for a given subfolder."""
        if "/" in subfolder:
            return subfolder.split("/")[0]
        return ""
