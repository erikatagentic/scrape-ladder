import io

import pytest
from openpyxl import Workbook

from scrape_ladder import structured


@pytest.mark.parametrize(
    "url, content_type, kind",
    [
        ("http://a.example/x.csv", "", "csv"),
        ("http://a.example/x", "text/csv; charset=utf-8", "csv"),
        ("http://a.example/x.json", "", "json"),
        ("http://a.example/x", "application/ld+json", "json"),
        ("http://a.example/x.xlsx", "", "xlsx"),
        ("http://a.example/x", "text/html", None),
    ],
)
def test_kind_of(url, content_type, kind):
    assert structured.kind_of(url, content_type) == kind


def test_csv_keeps_columns_and_samples_five_rows():
    body = ("a,b\n" + "".join(f"{i},{i * 2}\n" for i in range(9))).encode()
    parsed = structured.parse(body, "csv")
    assert parsed.row_count == 9 and parsed.columns == ["a", "b"] and len(parsed.sample_rows) == 5


def test_csv_with_a_byte_order_mark():
    parsed = structured.parse("\ufeffname\nx\n".encode(), "csv")
    assert parsed.columns == ["name"]


def test_json_list_dict_wrapper_and_scalar():
    assert structured.parse(b'[{"a": 1}, {"a": 2}]', "json").row_count == 2
    assert structured.parse(b'{"results": [{"a": 1}]}', "json").columns == ["a"]
    assert structured.parse(b'{"a": 1}', "json").row_count == 1
    assert structured.parse(b"[1, 2]", "json").sample_rows == [{"value": 1}, {"value": 2}]


def test_xlsx_reads_the_first_sheet():
    book = Workbook()
    book.active.append(["crop", "packets"])
    book.active.append(["beans", 142])
    buffer = io.BytesIO()
    book.save(buffer)
    parsed = structured.parse(buffer.getvalue(), "xlsx")
    assert parsed.columns == ["crop", "packets"] and parsed.sample_rows == [{"crop": "beans", "packets": 142}]


def test_broken_json_raises():
    with pytest.raises(ValueError):
        structured.parse(b"{not json", "json")
