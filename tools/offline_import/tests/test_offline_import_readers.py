"""Feed readers on synthetic files: CSV, JSON and a stdlib-built XLSX."""

import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from offline_import.mapping import ImportMapping
from offline_import.readers import FeedError, read_csv, read_json, read_rows, read_xlsx
from offline_import.validate import validate_file

FIXTURES = Path(__file__).parent / "fixtures"

_OOXML = "application/vnd.openxmlformats"
_CT = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    f'<Default Extension="rels" ContentType="{_OOXML}-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml"'
    f' ContentType="{_OOXML}-officedocument.spreadsheetml.sheet.main+xml"/>'
    "</Types>"
)
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _col(i: int) -> str:
    name = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        name = chr(ord("A") + rem) + name
    return name


def write_xlsx(
    path: Path, rows: list[list[object]], *, sheets: tuple[str, ...] = ("Feed",)
) -> Path:
    """A minimal valid .xlsx (no openpyxl): strings shared, numbers/bools typed, None skipped.

    Every sheet named in ``sheets`` gets the same rows, except the first gets them as given and
    the others get a single header row, so sheet selection is observable.
    """
    shared: list[str] = []

    def cell(ref: str, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
        if isinstance(value, int | float):
            return f'<c r="{ref}"><v>{value}</v></c>'
        text = str(value)
        if text.startswith("inline:"):
            body = escape(text.removeprefix("inline:"))
            return f'<c r="{ref}" t="inlineStr"><is><t>{body}</t></is></c>'
        if text not in shared:
            shared.append(text)
        return f'<c r="{ref}" t="s"><v>{shared.index(text)}</v></c>'

    def sheet_xml(data: list[list[object]]) -> str:
        body = "".join(
            f'<row r="{r}">'
            + "".join(cell(f"{_col(c)}{r}", v) for c, v in enumerate(values))
            + "</row>"
            for r, values in enumerate(data, start=1)
        )
        return f'<worksheet xmlns="{_MAIN}"><sheetData>{body}</sheetData></worksheet>'

    sheet_docs = [sheet_xml(rows if i == 0 else rows[:1]) for i in range(len(sheets))]
    workbook = (
        f'<workbook xmlns="{_MAIN}" xmlns:r="{_REL}"><sheets>'
        + "".join(
            f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(sheets)
        )
        + "</sheets></workbook>"
    )
    rels = (
        f'<Relationships xmlns="{_PKG_REL}">'
        + "".join(
            f'<Relationship Id="rId{i + 1}" Type="{_REL}/worksheet"'
            f' Target="worksheets/sheet{i + 1}.xml"/>'
            for i in range(len(sheets))
        )
        + "</Relationships>"
    )
    strings = (
        f'<sst xmlns="{_MAIN}">'
        + "".join(f"<si><t>{escape(s)}</t></si>" for s in shared)
        + "</sst>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/sharedStrings.xml", strings)
        for i, doc in enumerate(sheet_docs):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", doc)
    return path


def test_csv_rows_are_numbered_like_a_spreadsheet() -> None:
    rows = list(read_csv(FIXTURES / "acme_feed.csv"))
    assert len(rows) == 11
    number, first = rows[0]
    assert number == 2  # the header is row 1
    assert first["Variant ID"] == "AB-1001"
    assert first["Product Name AR"] == "أحمر شفاه أكمي"
    assert rows[1][1]["Sale Price"] == "99.00"


def test_csv_delimiter_encoding_and_ragged_rows(tmp_path: Path) -> None:
    feed = tmp_path / "feed.csv"
    feed.write_text("key;price\nK1;12,50\nK2\n", encoding="cp1252")
    assert list(read_csv(feed, delimiter=";", encoding="cp1252")) == [
        (2, {"key": "K1", "price": "12,50"}),
        (3, {"key": "K2", "price": None}),
    ]
    feed.write_text("key,price\nK1,1,2\n")
    with pytest.raises(FeedError, match="more values than header"):
        list(read_csv(feed))
    feed.write_text("")
    assert list(read_csv(feed)) == []


def test_json_items_path_and_errors(tmp_path: Path) -> None:
    rows = list(read_json(FIXTURES / "acme_feed.json", items_path="data.items"))
    assert [n for n, _ in rows] == [1, 2, 3]
    assert rows[0][1]["price"] == 55.5
    assert rows[0][1]["stock"] is True

    feed = tmp_path / "feed.json"
    feed.write_text(json.dumps([{"k": 1}]))
    assert list(read_json(feed)) == [(1, {"k": 1})]
    with pytest.raises(FeedError, match="has no 'items'"):
        list(read_json(feed, items_path="items"))
    feed.write_text(json.dumps({"items": {"k": 1}}))
    with pytest.raises(FeedError, match="array of objects"):
        list(read_json(feed, items_path="items"))
    feed.write_text(json.dumps([1]))
    with pytest.raises(FeedError, match="item 1 is not an object"):
        list(read_json(feed))


def test_xlsx_values_types_and_row_numbers(tmp_path: Path) -> None:
    path = write_xlsx(
        tmp_path / "feed.xlsx",
        [
            ["Variant ID", "Price", "EAN", "In Stock", "Note"],
            ["AB-1", 89, 2000000001012, True, "inline:Tom & Jerry"],
            ["AB-2", 12.5, None, False, None],
        ],
    )
    assert list(read_xlsx(path)) == [
        (2, {"Variant ID": "AB-1", "Price": "89", "EAN": "2000000001012", "In Stock": True,
             "Note": "Tom & Jerry"}),
        (3, {"Variant ID": "AB-2", "Price": "12.5", "EAN": None, "In Stock": False,
             "Note": None}),
    ]  # fmt: skip


def test_xlsx_sheet_selection_and_errors(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "feed.xlsx", [["k"], ["A"]], sheets=("Feed", "Other"))
    assert list(read_xlsx(path)) == [(2, {"k": "A"})]
    assert list(read_xlsx(path, sheet="Other")) == []
    with pytest.raises(FeedError, match="no sheet 'Nope'"):
        list(read_xlsx(path, sheet="Nope"))

    bad = tmp_path / "bad.xlsx"
    bad.write_text("not a zip")
    with pytest.raises(FeedError, match="not an xlsx"):
        list(read_xlsx(bad))

    headless = write_xlsx(tmp_path / "headless.xlsx", [["k"], ["A", "extra"]])
    with pytest.raises(FeedError, match="without a header"):
        list(read_xlsx(headless))

    empty_zip = tmp_path / "empty.xlsx"
    with zipfile.ZipFile(empty_zip, "w"):
        pass
    with pytest.raises(FeedError, match=r"missing xl/workbook\.xml"):
        list(read_xlsx(empty_zip))


def test_read_rows_dispatches_on_suffix_or_config(tmp_path: Path) -> None:
    mapping = ImportMapping.model_validate(json.loads((FIXTURES / "acme_mapping.json").read_text()))
    xlsx = write_xlsx(tmp_path / "feed.xlsx", [["Variant ID"], ["AB-9"]])
    assert list(read_rows(xlsx, mapping)) == [(2, {"Variant ID": "AB-9"})]
    assert len(list(read_rows(FIXTURES / "acme_feed.csv", mapping))) == 11
    odd = tmp_path / "feed.txt"
    odd.write_text("[]")
    with pytest.raises(ValueError, match="cannot tell the format"):
        list(read_rows(odd, mapping))
    as_json = mapping.model_copy(update={"format": "json"})
    assert list(read_rows(odd, as_json)) == []


def test_xlsx_feed_validates_like_csv(tmp_path: Path) -> None:
    """The same mapping serves an .xlsx export of the feed (format from the suffix)."""
    mapping = ImportMapping.model_validate(json.loads((FIXTURES / "acme_mapping.json").read_text()))
    header: list[object] = [
        "Variant ID",
        "SKU",
        "EAN",
        "Product Name",
        "Brand",
        "Price",
        "Sale Price",
        "In Stock",
    ]
    path = write_xlsx(
        tmp_path / "acme.xlsx",
        [
            header,
            ["AB-1001", "ACME-LIP-01", 2000000001012, "Acme Velvet Lipstick", "Acme Beauty", 89,
             None, "yes"],
            ["AB-1002", "ACME-LIP-02", None, "Acme Velvet Lipstick", "Acme Beauty", 120, 99, 0],
            ["AB-1003", None, None, "Acme Glow Serum", "Acme Beauty", 0, None, "yes"],
        ],
    )  # fmt: skip
    report = validate_file(path, mapping)
    assert report.format == "xlsx"
    assert [r.listing_key for r in report.accepted] == ["AB-1001", "AB-1002"]
    assert report.accepted[0].text["gtin"] == "2000000001012"
    assert str(report.accepted[1].price_current) == "99"
    assert report.accepted[1].availability == "out_of_stock"
    assert [r.row for r in report.rejected] == [4]
