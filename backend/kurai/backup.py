"""Online SQLite backup with an optional isolated restore check. Never overwrite files."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from sqlalchemy.engine import make_url


def inspect_snapshot(path):
    path = Path(path).resolve()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Проверка целостности копии не пройдена")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("В копии нарушены связи данных")
        counts = {}
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ):
            quoted = '"' + name.replace('"', '""') + '"'
            counts[name] = connection.execute(
                f"SELECT count(*) FROM {quoted}"
            ).fetchone()[0]
        fingerprint = hashlib.sha256()
        for line in connection.iterdump():
            fingerprint.update(line.encode("utf-8"))
            fingerprint.update(b"\n")
        return {
            "integrity": "ok",
            "table_counts": counts,
            "logical_sha256": fingerprint.hexdigest(),
        }


def copy_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError("Исходная база не найдена")
    if source == destination:
        raise ValueError("Копия должна иметь отдельный путь")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Reserve a new file atomically; a working database or existing backup is never replaced.
    with destination.open("xb"):
        pass
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as reader:
        with sqlite3.connect(destination) as writer:
            reader.backup(writer)
    return inspect_snapshot(destination)


def backup_and_check(source, destination, restore_check=None):
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backup": copy_database(source, destination),
    }
    if restore_check is not None:
        restored = copy_database(destination, restore_check)
        if restored != result["backup"]:
            raise ValueError("Восстановленная копия отличается от резервной")
        result["isolated_restore_matches"] = True
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Резервная копия локальной SQLite без перезаписи файлов"
    )
    parser.add_argument("--destination", type=Path)
    parser.add_argument(
        "--restore-check",
        type=Path,
        help="Новый отдельный файл для проверки восстановления",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    url = make_url(os.getenv("DATABASE_URL", "sqlite:///./data/runtime/preview.db"))
    if (
        url.get_backend_name() != "sqlite"
        or not url.database
        or url.database == ":memory:"
    ):
        raise SystemExit(
            "Этот способ предназначен для файловой SQLite; PostgreSQL требует отдельного регламента"
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = (
        args.destination or Path("data/runtime/backups") / f"preview-{stamp}.db"
    )
    protected = {Path(url.database).resolve(), destination.resolve()}
    if args.restore_check:
        protected.add(args.restore_check.resolve())
    if args.report and (
        args.report.suffix.lower() != ".json" or args.report.resolve() in protected
    ):
        raise SystemExit(
            "Отчёт должен быть отдельным JSON-файлом, не файлом базы данных"
        )
    try:
        result = backup_and_check(Path(url.database), destination, args.restore_check)
    except (ValueError, OSError, sqlite3.Error) as error:
        # Never include database contents or a credential-bearing URL in the message.
        raise SystemExit("Копия не подтверждена: " + type(error).__name__) from None
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
