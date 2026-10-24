"""Parse the batch manifest (CSV) and pair its rows with uploaded photos by filename.

Problems with single rows or photos (no match, duplicate, blank required cell) never reject
the batch: each becomes a BatchItem with a plain-language `problem`, which the batch runner
reports as an error row in the results table. Only problems with the whole manifest (not
CSV, missing columns, no rows) raise ManifestError.
"""

import csv
import io
from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import ValidationError

from app.schemas import ApplicationData

REQUIRED_COLUMNS = ("filename", "brand_name", "class_type", "alcohol_content", "net_contents")
OPTIONAL_COLUMNS = ("government_warning",)
_COLUMN_LABELS = {
    "brand_name": "brand name",
    "class_type": "class/type",
    "alcohol_content": "alcohol content",
    "net_contents": "net contents",
    "government_warning": "government warning",
}


class ManifestError(ValueError):
    """The manifest as a whole cannot be used. The message is shown to the user."""


@dataclass(frozen=True)
class ManifestRow:
    filename: str
    # None when a required cell is blank; `problem` then says which.
    application: ApplicationData | None
    problem: str | None = None


@dataclass(frozen=True)
class Upload:
    filename: str
    # None when the file was rejected before pairing (wrong type, too large); see problem.
    data: bytes | None
    problem: str | None = None


@dataclass
class BatchItem:
    filename: str
    image: bytes | None
    application: ApplicationData | None
    problem: str | None = None


def base_name(filename: str) -> str:
    """Strip any folder path, so "labels/01.png" and "labels\\01.png" match "01.png"."""
    return PurePosixPath(filename.replace("\\", "/")).name.strip()


def _match_key(filename: str) -> str:
    return base_name(filename).casefold()


# Friendly column names people put in their own spreadsheets.
_HEADER_ALIASES = {
    "file_name": "filename",
    "file": "filename",
    "image": "filename",
    "photo": "filename",
    "brand": "brand_name",
    "class": "class_type",
    "type": "class_type",
    "alcohol": "alcohol_content",
    "abv": "alcohol_content",
    "net_content": "net_contents",
    "volume": "net_contents",
    "warning": "government_warning",
}


def _header_key(header: str) -> str:
    """"Brand Name", "brand-name", "BRAND_NAME" and "Brand" all mean brand_name."""
    key = "_".join(header.strip().casefold().replace("-", " ").replace("/", " ").split())
    return _HEADER_ALIASES.get(key, key)


def _decode(data: bytes) -> str:
    """UTF-8 (with or without Excel's byte-order mark), else Windows-1252 as Excel saves it."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + f" and {words[-1]}"


def parse_manifest(data: bytes) -> list[ManifestRow]:
    text = _decode(data)
    if not text.strip():
        raise ManifestError("The spreadsheet is empty")
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if reader.fieldnames is None:
        raise ManifestError("The spreadsheet is empty")
    columns = {_header_key(name): name for name in reader.fieldnames if name}
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        noun = "this column" if len(missing) == 1 else "these columns"
        raise ManifestError(
            f"The spreadsheet is missing {noun}: {_join(missing)}. The first row must name "
            f"the columns {', '.join(REQUIRED_COLUMNS)} (government_warning is optional)."
        )

    rows: list[ManifestRow] = []
    for raw in reader:
        values = {
            key: (raw.get(columns[key]) or "").strip()
            for key in REQUIRED_COLUMNS + OPTIONAL_COLUMNS
            if key in columns
        }
        if not any(values.values()):
            continue  # blank line
        filename = base_name(values.pop("filename"))
        if not values.get("government_warning"):
            values.pop("government_warning", None)  # blank means the standard text
        try:
            rows.append(ManifestRow(filename, ApplicationData(**values)))
        except ValidationError:
            blank = [_COLUMN_LABELS[k] for k in REQUIRED_COLUMNS[1:] if not values.get(k)]
            rows.append(
                ManifestRow(filename, None, f"The spreadsheet row is missing the {_join(blank)}")
            )
    if not rows:
        raise ManifestError("The spreadsheet has no rows after the column names")
    return rows


NO_FILE_NAME = "A spreadsheet row has no file name"
DUPLICATE_ROW = "This file name is listed more than once in the spreadsheet"
DUPLICATE_PHOTO = "A photo with this file name was uploaded more than once"
NO_ROW = "This photo has no row in the spreadsheet"
NO_PHOTO = "No photo was uploaded for this spreadsheet row"


def pair_uploads(uploads: list[Upload], rows: list[ManifestRow]) -> list[BatchItem]:
    """Match photos to manifest rows by file name, ignoring folders and letter case.

    Every photo and every row ends up in exactly one item. A photo rejected earlier keeps its
    own problem but still claims its row, so the row is not also reported as missing a photo.
    """
    by_name: dict[str, ManifestRow] = {}
    items: list[BatchItem] = []
    for row in rows:
        key = _match_key(row.filename)
        if not key:
            items.append(BatchItem("(no file name)", None, None, NO_FILE_NAME))
        elif key in by_name:
            items.append(BatchItem(row.filename, None, None, DUPLICATE_ROW))
        else:
            by_name[key] = row

    claimed: set[str] = set()
    for upload in uploads:
        name, key = base_name(upload.filename), _match_key(upload.filename)
        row = by_name.get(key)
        if key in claimed:
            items.append(BatchItem(name, None, None, DUPLICATE_PHOTO))
        elif row is None:
            items.append(BatchItem(name, None, None, upload.problem or NO_ROW))
        else:
            claimed.add(key)
            problem = upload.problem or row.problem
            image = None if problem else upload.data
            items.append(BatchItem(name, image, row.application, problem))

    for key, row in by_name.items():
        if key not in claimed:
            items.append(BatchItem(row.filename, None, None, NO_PHOTO))
    return items
