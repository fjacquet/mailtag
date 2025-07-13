# Folder-Based Classification System

## Overview

The Folder-Based Classification System is a dynamic approach to email categorization that uses the actual IMAP folder structure from the mail server instead of a static classification schema. This document explains how the system works and how to configure it.

## Key Features

1. **Dynamic Folder Structure**: The system refreshes the IMAP folder list at application startup, ensuring that the classification system always uses the most up-to-date folder structure.

2. **Parent-Subfolder Hierarchy**: When suggesting new categories for emails, the system respects the folder hierarchy, only proposing subfolders under existing parent folders.

3. **Configurable**: The system can be enabled or disabled via configuration, allowing for a smooth transition from the legacy static schema approach.

## How It Works

### Folder Refresh at Startup

When the application starts, it connects to the IMAP server and retrieves the current folder hierarchy. This information is saved to `data/imap_folders.json` for use by the classification system.

```python
# Example of how the folder refresh works
with imap_service.connect():
    folders = imap_service.get_folder_hierarchy()
    with Path("data/imap_folders.json").open("w", encoding="utf-8") as f:
        json.dump(folders, f, indent=2)
```

If the folder refresh fails, the application will raise an error and stop processing, as an up-to-date folder structure is essential for the classification system.

### Folder Structure Analysis

The `FolderAnalyzer` class is responsible for parsing and analyzing the IMAP folder structure:

```python
# Example usage of the FolderAnalyzer
analyzer = FolderAnalyzer()
all_folders = analyzer.get_all_categories()
parent_folders = analyzer.get_parent_folders()
subfolders = analyzer.get_subfolders("Finance")
```

The analyzer identifies parent folders (those that have subfolders) and provides methods to access the folder hierarchy.

### Classification Process

The classification process follows these steps:

1. **Check Validated Database**: First, check if the sender has a validated classification.
2. **Check Server-Side Labels**: If the email already has a server-side label that matches a known folder, use that.
3. **Check Historical Data**: Look for high-confidence classifications from the sender's history.
4. **AI Model Classification**: If no classification is found through the above methods, use the AI model to suggest a category.

When using the AI model for classification, the system provides both the full list of existing folders and the list of parent folders. If no existing folder is appropriate, the model can suggest a new subfolder under one of the parent folders.

## Configuration

To enable or disable the folder-based classification system, set the `use_imap_folders_for_classification` option in the `config.toml` file:

```toml
[general]
ollama_model = "mistral"
api_base = "http://localhost:11434/v1"
use_imap_folders_for_classification = true
```

## Comparison with Legacy Schema-Based Approach

### Legacy Approach

The legacy approach used a static YAML file (`data/classification_schema.yml`) to define the classification schema. This required manual updates whenever the folder structure changed.

### New Approach

The new approach dynamically updates the folder structure from the IMAP server, ensuring that the classification system always uses the most current folder hierarchy. This eliminates the need for manual updates to the classification schema.

## Best Practices

1. **Regular Folder Maintenance**: Keep your IMAP folder structure organized and meaningful to improve classification accuracy.

2. **Parent Folders**: Create parent folders with clear semantic meaning to help the AI model make better suggestions for new subfolders.

3. **Monitoring**: Check the `proposals.log` file regularly to review new folder suggestions and potentially create those folders if they make sense for your organization.

## Troubleshooting

### Common Issues

1. **Connection Errors**: If the application fails to connect to the IMAP server at startup, check your network connection and IMAP server settings.

2. **Classification Errors**: If emails are being incorrectly classified, check the `proposals.log` file for insights into the AI model's reasoning.

3. **Performance Issues**: If the application is slow to start, consider optimizing your IMAP folder structure by reducing the number of folders or simplifying the hierarchy.
