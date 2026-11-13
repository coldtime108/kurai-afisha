"""Load reviewed source metadata; never replace dates with fabricated future ones."""

import json
from pathlib import Path
from .db import make_engine, session_factory
from .ingestion import import_rows


def main():
    path = Path(__file__).resolve().parents[2] / "data" / "reviewed-events.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    with session_factory(make_engine())() as session:
        print(
            json.dumps(
                import_rows(session, rows, actor="reviewed_seed"), ensure_ascii=False
            )
        )


if __name__ == "__main__":
    main()
