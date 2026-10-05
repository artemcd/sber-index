from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELATIONSHIP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def read_sheet(path: Path, name: str):
    with ZipFile(path) as book:
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        sheet = next(
            (item for item in workbook.findall(f".//{{{MAIN}}}sheet") if item.get("name") == name),
            None,
        )
        if sheet is None:
            raise ValueError(f"Нет листа {name} в {path.name}")
        relationship_id = sheet.get(f"{{{RELATIONSHIP}}}id")
        relationships = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        target = next(item.get("Target") for item in relationships if item.get("Id") == relationship_id)
        sheet_path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"

        strings = []
        if "xl/sharedStrings.xml" in book.namelist():
            strings = [
                "".join(item.itertext())
                for item in ET.fromstring(book.read("xl/sharedStrings.xml")).findall(f"{{{MAIN}}}si")
            ]

        worksheet = ET.fromstring(book.read(sheet_path))
        for row in worksheet.findall(f".//{{{MAIN}}}sheetData/{{{MAIN}}}row"):
            values = []
            for cell in row.findall(f"{{{MAIN}}}c"):
                column = 0
                for letter in cell.get("r"):
                    if not letter.isalpha():
                        break
                    column = column * 26 + ord(letter) - ord("A") + 1
                while len(values) < column:
                    values.append(None)
                value = cell.find(f"{{{MAIN}}}v")
                if value is not None and value.text is not None:
                    values[column - 1] = strings[int(value.text)] if cell.get("t") == "s" else value.text
                elif cell.get("t") == "inlineStr":
                    inline = cell.find(f"{{{MAIN}}}is")
                    values[column - 1] = "".join(inline.itertext()) if inline is not None else None
            yield tuple(values)
