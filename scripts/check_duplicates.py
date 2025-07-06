#!/usr/bin/env python3

import json
import shutil
from pathlib import Path

import click


@click.command()
@click.argument("db_path", type=click.Path(exists=True))
def check_and_fix_duplicates(db_path):
    """
    Checks a classification database for senders with multiple classifications.
    If duplicates are found, it creates a backup of the original file and
    saves a deduplicated version.
    """
    db_path = Path(db_path)
    with open(db_path, "r") as f:
        data = json.load(f)

    duplicates_found = False
    for sender, classifications in data.items():
        if len(classifications) > 1:
            duplicates_found = True
            click.echo(f"Duplicate found for sender: {sender}")
            for category, count in classifications.items():
                click.echo(f"  - {category}: {count}")

            # Keep the most frequent classification
            most_frequent_category = max(classifications, key=classifications.get)
            data[sender] = {most_frequent_category: classifications[most_frequent_category]}
            click.echo(f"  Keeping: {most_frequent_category}")

    if duplicates_found:
        # Create a backup
        backup_path = db_path.with_suffix(".json.old")
        shutil.copy(db_path, backup_path)
        click.echo(f"Backup of original file created at {backup_path}")

        # Save the deduplicated data
        with open(db_path, "w") as f:
            json.dump(data, f, indent=4)
        click.echo("Duplicates fixed and file saved.")
    else:
        click.echo("No duplicates found.")


if __name__ == "__main__":
    check_and_fix_duplicates()
