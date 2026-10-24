import pytest

from app.schemas import STANDARD_GOVERNMENT_WARNING
from app.services.manifest import (
    DUPLICATE_PHOTO,
    DUPLICATE_ROW,
    NO_PHOTO,
    NO_ROW,
    ManifestError,
    ManifestRow,
    Upload,
    base_name,
    pair_uploads,
    parse_manifest,
)

HEADER = "filename,brand_name,class_type,alcohol_content,net_contents,government_warning\n"
ROW = "01.png,Old Tom,Bourbon Whiskey,45%,750 mL,\n"


# parse_manifest


def test_parses_rows_and_defaults_blank_warning_to_standard() -> None:
    rows = parse_manifest((HEADER + ROW).encode())
    assert len(rows) == 1
    assert rows[0].filename == "01.png"
    assert rows[0].application is not None
    assert rows[0].application.brand_name == "Old Tom"
    assert rows[0].application.government_warning == STANDARD_GOVERNMENT_WARNING


def test_warning_column_is_optional() -> None:
    header = b"filename,brand_name,class_type,alcohol_content,net_contents\n"
    rows = parse_manifest(header + ROW.encode())
    assert rows[0].application is not None


@pytest.mark.parametrize(
    "data",
    [
        # Excel UTF-8 with byte-order mark
        ("\ufeff" + HEADER + ROW).encode("utf-8"),
        # Excel's default Windows encoding, with a curly apostrophe
        (HEADER + "01.png,Stone\u2019s Throw,Bourbon,45%,750 mL,\n").encode("cp1252"),
        # Friendly column names and semicolons (European Excel)
        b"File Name;Brand Name;Class/Type;Alcohol Content;Net Contents\n"
        b"01.png;Old Tom;Bourbon;45%;750 mL\n",
        b"Photo,Brand,Class,ABV,Volume\n01.png,Old Tom,Bourbon,45%,750 mL\n",
        # Blank lines are skipped
        (HEADER + "\n" + ROW + ",,,,,\n").encode(),
    ],
)
def test_parses_spreadsheet_variants(data: bytes) -> None:
    rows = parse_manifest(data)
    assert len(rows) == 1
    assert rows[0].filename == "01.png"
    assert rows[0].application is not None


def test_folder_path_in_filename_is_ignored() -> None:
    rows = parse_manifest((HEADER + "labels\\01.png,Old Tom,Bourbon,45%,750 mL,\n").encode())
    assert rows[0].filename == "01.png"


def test_blank_required_cell_becomes_a_row_problem_not_a_rejection() -> None:
    rows = parse_manifest((HEADER + "01.png,,Bourbon,45%,\n" + ROW.replace("01", "02")).encode())
    assert rows[0] == ManifestRow(
        "01.png", None, "The spreadsheet row is missing the brand name and net contents"
    )
    assert rows[1].application is not None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "The spreadsheet is empty"),
        (b"   \n", "The spreadsheet is empty"),
        (HEADER.encode(), "no rows"),
        (
            b"filename,brand\n01.png,Old Tom\n",
            "missing these columns: class_type, alcohol_content and net_contents",
        ),
        (
            b"brand_name,class_type,alcohol_content,net_contents\nA,B,45%,750 mL\n",
            "missing this column: filename",
        ),
    ],
)
def test_unusable_manifest_raises_plain_error(data: bytes, message: str) -> None:
    with pytest.raises(ManifestError, match=message):
        parse_manifest(data)


# pair_uploads


def _rows(*names: str) -> list[ManifestRow]:
    return parse_manifest((HEADER + "".join(ROW.replace("01.png", n) for n in names)).encode())


def test_pairs_by_name_ignoring_case_and_folders() -> None:
    items = pair_uploads([Upload("Labels/01.PNG", b"img")], _rows("01.png"))
    assert len(items) == 1
    assert items[0].filename == "01.PNG"
    assert items[0].image == b"img"
    assert items[0].problem is None


def test_every_photo_and_row_becomes_exactly_one_item() -> None:
    uploads = [Upload("01.png", b"a"), Upload("02.png", b"b"), Upload("orphan.png", b"c")]
    items = pair_uploads(uploads, _rows("01.png", "02.png", "missing_file.png"))
    problems = {item.filename: item.problem for item in items}
    assert problems == {
        "01.png": None,
        "02.png": None,
        "orphan.png": NO_ROW,
        "missing_file.png": NO_PHOTO,
    }


def test_rejected_photo_keeps_its_problem_and_claims_its_row() -> None:
    rejected = Upload("01.gif", None, "01.gif is not a supported photo type.")
    items = pair_uploads([rejected], _rows("01.gif"))
    assert [(i.filename, i.problem) for i in items] == [
        ("01.gif", "01.gif is not a supported photo type.")
    ]


def test_row_problem_is_carried_to_the_item() -> None:
    rows = parse_manifest((HEADER + "01.png,,Bourbon,45%,750 mL,\n").encode())
    items = pair_uploads([Upload("01.png", b"a")], rows)
    assert items[0].problem == "The spreadsheet row is missing the brand name"
    assert items[0].image is None


def test_duplicates_are_reported() -> None:
    items = pair_uploads(
        [Upload("01.png", b"a"), Upload("sub/01.png", b"b")], _rows("01.png", "01.png")
    )
    problems = sorted(str(i.problem) for i in items)
    assert problems == sorted([DUPLICATE_ROW, DUPLICATE_PHOTO, "None"])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01.png", "01.png"),
        ("a/b/01.png", "01.png"),
        ("C:\\x\\01.png", "01.png"),
        (" 01.png ", "01.png"),
    ],
)
def test_base_name(raw: str, expected: str) -> None:
    assert base_name(raw) == expected
