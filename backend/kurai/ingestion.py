import hashlib
import json
import re
import unicodedata
from sqlalchemy import select
from pydantic import ValidationError
from .models import AuditEntry, Event, RawRecord
from .schemas import EventInput


def normalize(value: str) -> str:
    return re.sub(
        r"[^\w]+",
        " ",
        unicodedata.normalize("NFKC", value).casefold().replace("ё", "е"),
    ).strip()


def sha(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def import_rows(session, rows: list[dict], actor="moderator"):
    report = {"added": 0, "updated": 0, "skipped": 0, "rejected": 0, "errors": []}
    for index, raw in enumerate(rows, start=1):
        try:
            item = EventInput.model_validate(raw)
        except ValidationError as error:
            report["rejected"] += 1
            report["errors"].append(
                {
                    "row": index,
                    "reason": "; ".join(
                        f"{'.'.join(map(str,e['loc'])) or 'запись'}: {e['msg']}"
                        for e in error.errors(include_input=False)
                    ),
                }
            )
            continue
        source_hash = sha(raw)
        if session.scalar(
            select(RawRecord).where(RawRecord.source_hash == source_hash)
        ):
            report["skipped"] += 1
            continue
        values = item.model_dump(mode="json")
        key = sha(
            [
                normalize(item.title),
                values["date_start"],
                normalize(item.city),
                normalize(item.venue),
            ]
        )
        existing = session.scalar(select(Event).where(Event.dedup_key == key))
        source = {
            "url": values["source_url"],
            "verified_at": values["verified_at"],
            "type": values["source_type"],
        }
        values.update(
            {
                field: getattr(item, field)
                for field in ("date_start", "date_end", "verified_at")
            }
        )
        if existing:
            if existing.moderated_at:
                session.add(
                    RawRecord(
                        source_hash=source_hash, payload=raw, event_id=existing.id
                    )
                )
                session.add(
                    AuditEntry(
                        actor=actor,
                        action="import_proposal",
                        entity_id=existing.id,
                        changes={
                            "proposed": raw,
                            "reason": "Карточка защищена после ручной проверки",
                        },
                    )
                )
                report["rejected"] += 1
                report["errors"].append(
                    {
                        "row": index,
                        "reason": "Карточка проверена модератором. Новые сведения сохранены в журнале для сверки; используйте редактор",
                    }
                )
                session.flush()
                continue
            sources = [s for s in existing.sources if s["url"] != source["url"]] + [
                source
            ]
            # A second source may add provenance, but cannot silently overwrite facts/status.
            conflict = any(
                values[field] != getattr(existing, field)
                for field in (
                    "price_min",
                    "price_max",
                    "age_limit",
                    "date_end",
                    "address",
                )
            )
            same_source = existing.source_url == values["source_url"]
            before = {"status": existing.status, "sources": existing.sources}
            if same_source:
                # Imports cannot undo a moderator's cancellation without an explicit edit.
                if existing.status == "cancelled" and values["status"] == "published":
                    values["status"] = "cancelled"
                for field, value in values.items():
                    setattr(existing, field, value)
                existing.source_hash = source_hash
            elif conflict:
                existing.status = "draft"
            existing.sources = sources
            session.add(
                AuditEntry(
                    actor=actor,
                    action="import_update",
                    entity_id=existing.id,
                    changes={
                        "before": before,
                        "after": {"status": existing.status, "sources": sources},
                        "conflict": conflict,
                    },
                )
            )
            target = existing
            report["updated"] += 1
        else:
            target = Event(
                **values,
                normalized_title=normalize(item.title),
                dedup_key=key,
                source_hash=source_hash,
                sources=[source],
            )
            session.add(target)
            session.flush()
            session.add(
                AuditEntry(
                    actor=actor,
                    action="import_create",
                    entity_id=target.id,
                    changes={"status": target.status, "source_url": target.source_url},
                )
            )
            report["added"] += 1
        session.add(RawRecord(source_hash=source_hash, payload=raw, event_id=target.id))
        session.flush()
    session.commit()
    return report
