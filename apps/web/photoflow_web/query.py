"""Pure query validation and SQL over rebuildable photo metadata indexes."""

import re
from datetime import date, datetime
from pathlib import PurePosixPath

LABELS = ("people", "place", "albums", "tags")
DEFAULTS = {
    "people": [],
    "place": [],
    "people_mode": "any",
    "albums": [],
    "tags": [],
    "from": "",
    "to": "",
    "date": "any",
    "favorite": "any",
    "type": "any",
    "missing": "any",
}
CHOICES = {
    "people_mode": ("any", "all"),
    "date": ("any", "known", "unknown"),
    "favorite": ("any", "yes", "no"),
    "type": ("any", "image", "video"),
    "missing": ("any", "people", "albums", "place", "location", "location_conflict"),
}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp", ".mts", ".webm"}
TABLES = "listing l JOIN query_properties p ON p.id=l.id"
ORDER = "l.captured DESC,l.id"


def normalize_filters(value=None):
    """Return a canonical JSON-compatible predicate set; reject silent broadening."""
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Invalid filter object or unknown filter")
    result = {**DEFAULTS, **value}
    for field in LABELS:
        values = result[field]
        if (
            not isinstance(values, list)
            or len(values) > 256
            or any(
                not isinstance(item, str)
                or not item.strip()
                or len(item) > 256
                or "\x00" in item
                for item in values
            )
        ):
            raise ValueError(f"Invalid {field} filter")
        result[field] = sorted(set(values), key=lambda x: (x.casefold(), x))
    for field, choices in CHOICES.items():
        if result[field] not in choices:
            raise ValueError(f"Invalid {field} filter")
    for field in ("from", "to"):
        value = result[field]
        if not isinstance(value, str):
            raise ValueError("Dates must be YYYY-MM-DD strings")
        if value:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("Dates must be YYYY-MM-DD strings")
            date.fromisoformat(value)
    if result["from"] and result["to"] and result["from"] > result["to"]:
        raise ValueError("Start date must not follow end date")
    if result["date"] == "unknown" and (result["from"] or result["to"]):
        raise ValueError("Unknown dates cannot be combined with a date range")
    return result


def create_indexes(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS query_labels(
          id TEXT NOT NULL,facet TEXT NOT NULL,value TEXT NOT NULL,
          PRIMARY KEY(id,facet,value)
        );
        CREATE INDEX IF NOT EXISTS query_label_values ON query_labels(facet,value,id);
        CREATE TABLE IF NOT EXISTS query_properties(
          id TEXT PRIMARY KEY,day TEXT NOT NULL,year TEXT NOT NULL,
          media_type TEXT NOT NULL,favorite INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS query_days ON query_properties(day,id);
        CREATE INDEX IF NOT EXISTS query_types ON query_properties(media_type,id);
        CREATE INDEX IF NOT EXISTS query_favorites ON query_properties(favorite,id);
        """)


def index_record(db, record):
    ident = record["record_id"]
    metadata = record.get("resolved", {})
    captured = metadata.get("capture_time")
    day = ""
    if captured:
        # Calendar dates follow the recorded capture offset, matching placement.
        try:
            day = (
                datetime.fromisoformat(captured.replace("Z", "+00:00"))
                .date()
                .isoformat()
            )
        except (ValueError, AttributeError):
            pass
    media_type = (
        "video"
        if PurePosixPath(record["file"]["relative_path"]).suffix.lower()
        in VIDEO_EXTENSIONS
        else "image"
    )
    db.execute(
        "INSERT OR REPLACE INTO query_properties VALUES(?,?,?,?,?)",
        (ident, day, day[:4], media_type, int(metadata.get("favorite") is True)),
    )
    db.execute("DELETE FROM query_labels WHERE id=?", (ident,))
    rows = []
    for field in LABELS:
        values = metadata.get(field, [])
        if isinstance(values, list):
            rows.extend(
                (ident, field, value)
                for value in set(v for v in values if isinstance(v, str) and v.strip())
            )
    db.executemany("INSERT INTO query_labels VALUES(?,?,?)", rows)


class Query:
    """Scope and predicates shared by listing, facets, and frozen selections."""

    def __init__(
        self,
        q="",
        folder=None,
        duplicates=False,
        favorite=False,
        trash=False,
        filters=None,
    ):
        if not isinstance(q, str) or len(q) > 4096:
            raise ValueError("Invalid search text")
        if folder is not None and not isinstance(folder, str):
            raise ValueError("Invalid folder scope")
        self.q, self.folder = q, folder
        self.duplicates, self.favorite, self.trash = duplicates, favorite, trash
        self.filters = normalize_filters(filters)

    def where(self, exclude=()):
        filters = self.filters
        conditions = ["l.trashed=?"]
        params = [int(self.trash)]
        if not self.duplicates and not self.folder and not self.trash:
            conditions.append("l.duplicate=0")
        if self.folder and self.folder != ".":
            prefix = self.folder.rstrip("/") + "/"
            conditions.append("substr(l.path,1,?)=?")
            params.extend([len(prefix), prefix])
        if self.q:
            conditions.append("instr(l.search,?)>0")
            params.append(self.q.casefold())
        if self.favorite:
            conditions.append("p.favorite=1")
        for field in LABELS:
            if field in exclude or not filters[field]:
                continue
            values = filters[field]
            if field == "people" and filters["people_mode"] == "all":
                for value in values:
                    conditions.append(
                        "EXISTS(SELECT 1 FROM query_labels x WHERE x.id=l.id AND x.facet=? AND x.value=?)"
                    )
                    params.extend([field, value])
            else:
                placeholders = ",".join("?" for _ in values)
                conditions.append(
                    f"EXISTS(SELECT 1 FROM query_labels x WHERE x.id=l.id AND x.facet=? AND x.value IN ({placeholders}))"
                )
                params.extend([field, *values])
        if "date" not in exclude:
            if filters["date"] == "unknown":
                conditions.append("p.day=''")
            elif filters["date"] == "known" or filters["from"] or filters["to"]:
                conditions.append("p.day<>''")
            if filters["from"]:
                conditions.append("p.day>=?")
                params.append(filters["from"])
            if filters["to"]:
                conditions.append("p.day<=?")
                params.append(filters["to"])
        if filters["favorite"] != "any":
            conditions.append("p.favorite=?")
            params.append(int(filters["favorite"] == "yes"))
        if filters["type"] != "any":
            conditions.append("p.media_type=?")
            params.append(filters["type"])
        if filters["missing"] == "location":
            conditions.append("json_extract(l.metadata,'$.location') IS NULL")
        elif filters["missing"] == "location_conflict":
            conditions.append("json_extract(l.metadata,'$.location_status')='conflict'")
        elif filters["missing"] != "any":
            conditions.append(
                "NOT EXISTS(SELECT 1 FROM query_labels x WHERE x.id=l.id AND x.facet=?)"
            )
            params.append(filters["missing"])
        return " AND ".join(conditions), params

    def matching(self, db):
        where, params = self.where()
        return [
            dict(row)
            for row in db.execute(
                f"SELECT l.id,l.revision FROM {TABLES} WHERE {where} ORDER BY {ORDER}",
                params,
            )
        ]

    def facets(self, db):
        where, params = self.where()
        result = {
            "total": db.execute(
                f"SELECT count(*) FROM {TABLES} WHERE {where}", params
            ).fetchone()[0]
        }
        for field in LABELS:
            # OR lists retain alternatives; ALL people previews adding a constraint.
            exclude = (
                ()
                if field == "people" and self.filters["people_mode"] == "all"
                else (field,)
            )
            where, params = self.where(exclude)
            counts = dict(
                db.execute(
                    f"SELECT x.value,count(*) FROM {TABLES} JOIN query_labels x ON x.id=l.id AND x.facet=? WHERE {where} GROUP BY x.value",
                    [field, *params],
                ).fetchall()
            )
            for value in self.filters[field]:
                counts.setdefault(value, 0)
            result[field] = [
                {"value": value, "count": counts[value]}
                for value in sorted(counts, key=lambda x: (x.casefold(), x))
            ]
        where, params = self.where(("date",))
        years = dict(
            db.execute(
                f"SELECT p.year,count(*) FROM {TABLES} WHERE {where} GROUP BY p.year",
                params,
            ).fetchall()
        )
        result["date_unknown"] = years.pop("", 0)
        result["years"] = [
            {"value": year, "count": years[year]} for year in sorted(years)
        ]
        return result
