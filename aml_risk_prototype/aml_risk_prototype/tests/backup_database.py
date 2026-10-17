
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aml.core import connect

backup_dir = Path("backups")
backup_dir.mkdir(exist_ok=True)

timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
backup_path = backup_dir / f"aml_backup_{timestamp}.db"

with connect() as source:
    with sqlite3.connect(backup_path) as destination:
        source.backup(destination)

print(f"Backup saved: {backup_path}")
