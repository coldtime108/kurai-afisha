"""Load reviewed source metadata; never replace dates with fabricated future ones."""

import json
from pathlib import Path
from .db import make_engine, session_factory
from .ingestion import import_rows


def reviewed_rows():
    directory = Path(__file__).resolve().parents[2] / "data"
    return [
        row
        for filename in (
            "reviewed-events.json",
            "reviewed-events-extra.json",
            "reviewed-events-collected.json",
        )
        for row in json.loads((directory / filename).read_text(encoding="utf-8"))
    ]


def main():
    engine = make_engine()
    try:
        with session_factory(engine)() as session:
            print(
                json.dumps(
                    import_rows(session, reviewed_rows(), actor="reviewed_seed"),
                    ensure_ascii=False,
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
