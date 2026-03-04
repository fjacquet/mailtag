# IMAP Folder-Based Classification Specification

## Overview

This document outlines the technical approach for replacing the static classification schema (`classification_schema.yml`) with a dynamic folder-based classification system that uses the actual IMAP folder structure (`imap_folders.json`) refreshed from the live server at application startup.

## Current Implementation

Currently, the application uses:

- A static `classification_schema.yml` file that defines the hierarchical classification schema
- An `imap_folders.json` file that is generated separately and not actively used for classification decisions
- The `Classifier` class in `classifier.py` that uses the schema for classification decisions

## Proposed Changes

### 1. IMAP Folder Refresh at Startup

#### Implementation Details

1. Modify the application startup process to refresh the IMAP folder structure:

```python
def refresh_imap_folders(imap_service: ImapService) -> None:
    """Refresh the IMAP folder structure from the live server."""
    try:
        with imap_service.connect():
            # Get the folder hierarchy from the IMAP server
            folders = imap_service.get_folder_hierarchy()
            
            # Save to imap_folders.json
            folder_path = Path("data/imap_folders.json")
            with folder_path.open("w", encoding="utf-8") as f:
                json.dump(folders, f, indent=2)
                
            logger.info(f"Successfully refreshed IMAP folders: {len(folders)} folders found")
    except Exception as e:
        logger.error(f"Failed to refresh IMAP folders: {e}")
        # If refresh fails, stop processing - critical error
        raise RuntimeError(f"Cannot proceed without fresh IMAP folder structure: {e}")
```

1. Add this function call to the application startup sequence in `main.py`:

```python
def main():
    # Existing initialization code...
    
    # Refresh IMAP folders at startup
    if config.use_imap_folders_for_classification:
        refresh_imap_folders(imap_service)
    
    # Continue with the rest of the application...
```

### 2. Folder Structure Analysis

#### Implementation Details

1. Create a new module `folder_analyzer.py` to parse and analyze the IMAP folder structure:

```python
class FolderAnalyzer:
    """Analyzes IMAP folder structure for classification purposes."""
    
    def __init__(self, folder_path: Path = Path("data/imap_folders.json")):
        self.folder_path = folder_path
        self.folders = self._load_folders()
        self.parent_folders = self._identify_parent_folders()
        
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
                parent = folder.split("/")[0]
                parent_folders.add(parent)
                
        return parent_folders
        
    def get_all_categories(self) -> list[str]:
        """Get all available categories from the folder structure."""
        return self.folders
        
    def get_parent_folders(self) -> list[str]:
        """Get all parent folders."""
        return list(self.parent_folders)
        
    def get_subfolders(self, parent: str) -> list[str]:
        """Get all subfolders for a given parent folder."""
        return [
            folder for folder in self.folders 
            if folder.startswith(f"{parent}/")
        ]
        
    def suggest_subfolder(self, content: str) -> tuple[str, str]:
        """
        Suggest a parent folder and subfolder based on email content.
        Returns a tuple of (parent_folder, full_path)
        """
        # Implementation will depend on the AI model integration
        # This is a placeholder for the actual implementation
        pass
```

### 3. Classifier Modifications

#### Implementation Details

1. Update the `Classifier` class to use the folder structure instead of the schema:

```python
class Classifier:
    """
    Classifies emails using a multi-signal strategy, prioritizing server-side
    labels, then historical data, and finally an AI model.
    """

    def __init__(self, config: AppConfig, database: ClassificationDatabase):
        self.config = config
        self.proposal_file = Path("proposals.log")
        self.folder_analyzer = FolderAnalyzer()
        self.database = database

    def _get_category_from_labels(self, email: Email) -> str | None:
        """
        Signal 2: Check for an existing server-side label that matches a known folder.
        """
        categories = self.folder_analyzer.get_all_categories()
        for label in email.labels:
            if label in categories:
                logger.debug(f"Found matching server-side label: {label}")
                return label
        return None

    def _get_category_from_ai(self, email: Email) -> str:
        """
        Signal 4: Fallback to the AI model for classification.
        """
        sender = (
            f"{email.sender_name} <{email.sender_address}>" if email.sender_name else email.sender_address
        )
        
        # Get all available categories from the folder structure
        categories = self.folder_analyzer.get_all_categories()
        parent_folders = self.folder_analyzer.get_parent_folders()
        
        category_list = "\n".join([f"- {cat}" for cat in categories])
        parent_list = "\n".join([f"- {parent}" for parent in parent_folders])

        prompt = (
            f"Sujet : {email.subject}\n"
            f"De : {sender}\n"
            f"Corps : {email.body}\n\n"
            "Classe cet e-mail dans l'une des catégories suivantes:\n"
            f"{category_list}\n\n"
            "Si aucune catégorie ne correspond parfaitement, propose un sous-dossier "
            "dans l'un des dossiers parents suivants:\n"
            f"{parent_list}\n\n"
            "Réponds uniquement avec le nom complet de la catégorie "
            "(ex: Finance/Bloomberg).\n"
            "Si tu proposes un nouveau sous-dossier, utilise le format 'NOUVEAU: ParentFolder/NewSubfolder'."
        )
        
        try:
            response = litellm.completion(
                model=self.config.general.ollama_model,
                messages=[{"role": "user", "content": prompt}],
                api_base=self.config.general.api_base,
                extra_body={"options": {"temperature": 0.2}},
            )
            classification = response.choices[0].message.content.strip()
            
            # Handle new subfolder suggestions
            if classification.startswith("NOUVEAU:"):
                proposed_path = classification.replace("NOUVEAU:", "").strip()
                if "/" in proposed_path:
                    parent, subfolder = proposed_path.split("/", 1)
                    if parent in parent_folders:
                        self._log_proposal(email, proposed_path)
                        return "À Classer"
                
                # If the format is incorrect or parent not valid
                return "À Classer"
                
            if classification not in categories:
                self._log_proposal(email, classification)
                return "À Classer"

            return classification
        except Exception as e:
            logger.error(f"Error calling litellm: {e}")
            return "(Model Error)"
```

### 4. Configuration Updates

Add a new configuration option to `config.toml`:

```toml
[general]
# Other existing options...
use_imap_folders_for_classification = true
```

And update the `AppConfig` class in `config.py` to include this option:

```python
class GeneralConfig:
    def __init__(self, config_dict: dict):
        self.api_base = config_dict.get("api_base", "http://localhost:11434/v1")
        self.ollama_model = config_dict.get("ollama_model", "mistral")
        self.use_imap_folders_for_classification = config_dict.get(
            "use_imap_folders_for_classification", True
        )
```

## Migration Strategy

1. Add a feature flag to enable/disable the new folder-based classification
2. Implement the changes while keeping backward compatibility
3. Test thoroughly with both approaches
4. Once validated, remove the old schema-based classification code

## Testing Plan

1. Unit tests for the `FolderAnalyzer` class
2. Integration tests with a mock IMAP server
3. End-to-end tests with real IMAP folders

## Considerations and Limitations

1. **Folder Refresh Failure**: If the folder refresh fails at startup, the application will raise an error and stop processing. This is considered a critical error as the system requires an up-to-date folder structure to function properly.

2. **New Folder Suggestions**: When suggesting new folders, the AI model must only propose subfolders under existing parent folders, not arbitrary new categories.

3. **Backward Compatibility**: During the transition period, both classification methods should be supported through the feature flag.

4. **Performance**: The folder structure should be cached after initial loading to avoid repeated file I/O operations.

## Future Enhancements

1. **Real-time Folder Updates**: Periodically refresh the folder structure during long-running application sessions.

2. **User Feedback Loop**: Allow users to confirm or reject folder suggestions to improve the AI model's accuracy.

3. **Folder Statistics**: Track which folders are most commonly used for better suggestions.
