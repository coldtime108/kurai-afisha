import sqlite3

import pytest

from kurai.backup import backup_and_check, copy_database


def test_online_backup_includes_wal_and_restores_all_values(tmp_path):
    source = tmp_path / "live.db"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(
            "CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT); INSERT INTO items VALUES(7, 'проверка');"
        )
        connection.commit()
        result = backup_and_check(
            source, tmp_path / "backup.db", tmp_path / "restored.db"
        )
    assert result["isolated_restore_matches"] is True
    assert result["backup"]["table_counts"] == {"items": 1}
    with sqlite3.connect(tmp_path / "restored.db") as connection:
        assert connection.execute("SELECT * FROM items").fetchall() == [(7, "проверка")]


def test_backup_refuses_existing_destination_or_missing_source(tmp_path):
    source = tmp_path / "live.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample(id INTEGER)")
    destination = tmp_path / "existing.db"
    destination.write_bytes(b"do not replace")
    with pytest.raises(FileExistsError):
        copy_database(source, destination)
    assert destination.read_bytes() == b"do not replace"
    with pytest.raises(ValueError):
        copy_database(tmp_path / "absent.db", tmp_path / "new.db")
    assert not (tmp_path / "new.db").exists()
