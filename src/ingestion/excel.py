from dataclasses import dataclass
from itertools import groupby
from typing import BinaryIO
import warnings

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.cell_range import CellRange
from openpyxl.worksheet.worksheet import Worksheet

from src.ingestion.document import Document


@dataclass(frozen=True)
class WorksheetTable:
    name: str
    bounds: CellRange
    headers: dict[int, str]
    header_row: int | None


def worksheet_tables(sheet: Worksheet) -> list[WorksheetTable]:
    tables = []
    for table in sheet.tables.values():
        bounds = CellRange(table.ref)
        headers = {
            column: definition.name
            for column, definition in enumerate(table.tableColumns, bounds.min_col)
        }
        header_row = bounds.min_row if table.headerRowCount else None
        tables.append(WorksheetTable(table.displayName, bounds, headers, header_row))

    if sheet.auto_filter.ref:
        bounds = CellRange(sheet.auto_filter.ref)
        headers = {
            column: str(cell.value)
            for column in range(bounds.min_col, bounds.max_col + 1)
            if (cell := sheet.cell(bounds.min_row, column)).value is not None
        }
        tables.append(WorksheetTable("", bounds, headers, bounds.min_row))
    return tables


def excel_row(
    sheet_name: str,
    row_number: int,
    values: list[tuple[int, object]],
    headers: dict[int, str],
    table_name: str = "",
    is_header: bool = False,
) -> Document:
    fields = []
    for column, value in values:
        coordinate = f"{get_column_letter(column)}{row_number}"
        header = headers.get(column) if not is_header else None
        label = f"{header} [{coordinate}]" if header else coordinate
        fields.append(f"{label}: {value}")
    location = f"Sheet {sheet_name}"
    if table_name:
        location += f" · table {table_name}"
    location += f" · row {row_number}"
    if is_header:
        location += " (column headers)"
    return Document(" | ".join(fields), location, embed_location=True)


def load_excel(stream: BinaryIO) -> list[Document]:
    # openpyxl warns about loss on save. Ingestion never writes the workbook.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"^Conditional Formatting extension is not supported and will be removed$",
            category=UserWarning,
            module=r"^openpyxl\.worksheet\._reader$",
        )
        workbook = load_workbook(stream, data_only=True, keep_links=False)

    documents = []
    try:
        for sheet in workbook.worksheets:
            tables = worksheet_tables(sheet)
            loose_headers = None
            # Iterate populated cells without expanding large formatted gaps into a dense grid.
            cells = sorted(
                (cell.row, cell.column, cell.value)
                for cell in sheet._cells.values()
                if cell.value is not None and cell.value != ""
            )
            for row_number, group in groupby(cells, key=lambda cell: cell[0]):
                remaining = {column: value for _, column, value in group}
                for table in tables:
                    if not table.bounds.min_row <= row_number <= table.bounds.max_row:
                        continue
                    values = [
                        (column, remaining.pop(column))
                        for column in list(remaining)
                        if table.bounds.min_col <= column <= table.bounds.max_col
                    ]
                    if values:
                        documents.append(excel_row(
                            sheet.title, row_number, values, table.headers,
                            table.name, row_number == table.header_row,
                        ))
                if remaining:
                    is_header = False
                    if loose_headers is None and len(remaining) > 1:
                        is_header = all(isinstance(value, str) for value in remaining.values())
                        loose_headers = dict(remaining) if is_header else {}
                    documents.append(excel_row(
                        sheet.title, row_number, list(remaining.items()), loose_headers or {},
                        is_header=is_header,
                    ))
    finally:
        workbook.close()
    return documents
