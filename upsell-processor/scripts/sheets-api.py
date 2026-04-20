# /// script
# requires-python = ">=3.11"
# dependencies = ["google-auth", "google-api-python-client"]
# ///

"""
Google Sheets API for the Upsell Processor skill.
Uses a service account for authentication.

Credentials must be passed in the input JSON under "gsheets_credentials"
as the full service account JSON object.

Input (stdin JSON):
  {"command": "read", "spreadsheet_id": "...", "worksheet_name": "...", "range": "A1:Z100", "gsheets_credentials": {...}}
  {"command": "get_headers", "spreadsheet_id": "...", "worksheet_name": "...", "gsheets_credentials": {...}}
  {"command": "append", "spreadsheet_id": "...", "worksheet_name": "...", "values": ["val1", "val2"], "gsheets_credentials": {...}}
  {"command": "find_row", "spreadsheet_id": "...", "worksheet_name": "...", "search_col": "B", "search_value": "Acme", "gsheets_credentials": {...}}
  {"command": "find_and_update", "spreadsheet_id": "...", "worksheet_name": "...", "search_col": "B", "search_value": "Acme", "update_col": "F", "update_value": "110000", "gsheets_credentials": {...}}
  {"command": "update_cell", "spreadsheet_id": "...", "worksheet_name": "...", "cell_ref": "F25", "value": "110000", "gsheets_credentials": {...}}
  {"command": "extend_formulas", "spreadsheet_id": "...", "worksheet_name": "...", "col_start": "H", "col_end": "K", "gsheets_credentials": {...}}
"""

import json
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_service_account_info = None


def get_service():
    """Authenticate and return a Google Sheets API service object."""
    creds = service_account.Credentials.from_service_account_info(
        _service_account_info, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def read_sheet(spreadsheet_id, worksheet_name, cell_range=None):
    service = get_service()
    range_str = f"'{worksheet_name}'!{cell_range}" if cell_range else f"'{worksheet_name}'"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_str
    ).execute()
    return result.get("values", [])


def get_headers(spreadsheet_id, worksheet_name):
    rows = read_sheet(spreadsheet_id, worksheet_name, "1:1")
    return rows[0] if rows else []


def append_row(spreadsheet_id, worksheet_name, values):
    service = get_service()
    result = service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"'{worksheet_name}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [values]},
    ).execute()
    updated_range = result.get("updates", {}).get("updatedRange", "")
    try:
        row_number = int(updated_range.split("!")[1].split(":")[0].lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    except (IndexError, ValueError):
        row_number = None
    return {"updated_range": updated_range, "row_number": row_number}


def _col_to_index(col):
    col = col.upper()
    index = 0
    for c in col:
        index = index * 26 + (ord(c) - ord("A") + 1)
    return index - 1


def find_row(spreadsheet_id, worksheet_name, search_col, search_value):
    rows = read_sheet(spreadsheet_id, worksheet_name)
    if not rows:
        return None, None
    col_index = _col_to_index(search_col)
    for i, row in enumerate(rows):
        if col_index < len(row):
            if search_value.strip().lower() in str(row[col_index]).strip().lower():
                return i + 1, row
    return None, None


def update_cell(spreadsheet_id, worksheet_name, cell_ref, value):
    service = get_service()
    result = service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{worksheet_name}'!{cell_ref}",
        valueInputOption="USER_ENTERED",
        body={"values": [[value]]},
    ).execute()
    return result


def find_and_update(spreadsheet_id, worksheet_name, search_col, search_value, update_col, update_value):
    row_number, _ = find_row(spreadsheet_id, worksheet_name, search_col, search_value)
    if row_number is None:
        return None
    update_cell(spreadsheet_id, worksheet_name, f"{update_col}{row_number}", update_value)
    return row_number


def extend_formulas(spreadsheet_id, worksheet_name, col_start, col_end):
    service = get_service()
    all_rows = read_sheet(spreadsheet_id, worksheet_name)
    last_data_row = None
    for i, row in enumerate(all_rows, 1):
        if row and str(row[0]).strip():
            last_data_row = i
    if last_data_row is None or last_data_row < 2:
        return {"error": "Could not determine last data row"}

    source_row = last_data_row - 1
    target_row = last_data_row

    source_range = f"'{worksheet_name}'!{col_start}{source_row}:{col_end}{source_row}"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=source_range, valueRenderOption="FORMULA"
    ).execute()
    source_formulas = result.get("values", [[]])[0]
    if not source_formulas:
        return {"error": f"No formulas found in row {source_row}"}

    target_formulas = [f.replace(str(source_row), str(target_row)) for f in source_formulas]
    target_range = f"'{worksheet_name}'!{col_start}{target_row}:{col_end}{target_row}"
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=target_range,
        valueInputOption="USER_ENTERED",
        body={"values": [target_formulas]},
    ).execute()
    return {"row_updated": target_row}


def main():
    global _service_account_info
    data = json.load(sys.stdin)

    gsheets_creds = data.get("gsheets_credentials")
    if not gsheets_creds:
        print(json.dumps({"error": "gsheets_credentials is required in input"}))
        return
    _service_account_info = gsheets_creds

    command = data.get("command")
    sid = data.get("spreadsheet_id")
    ws = data.get("worksheet_name")

    if command == "read":
        rows = read_sheet(sid, ws, data.get("range"))
        print(json.dumps({"rows": rows, "count": len(rows)}))

    elif command == "get_headers":
        print(json.dumps({"headers": get_headers(sid, ws)}))

    elif command == "append":
        result = append_row(sid, ws, data["values"])
        print(json.dumps(result))

    elif command == "find_row":
        row_num, row_data = find_row(sid, ws, data["search_col"], data["search_value"])
        print(json.dumps({"row_number": row_num, "row_data": row_data}))

    elif command == "find_and_update":
        row_num = find_and_update(sid, ws, data["search_col"], data["search_value"], data["update_col"], data["update_value"])
        print(json.dumps({"row_updated": row_num}))

    elif command == "update_cell":
        result = update_cell(sid, ws, data["cell_ref"], data["value"])
        print(json.dumps(result))

    elif command == "extend_formulas":
        result = extend_formulas(sid, ws, data["col_start"], data["col_end"])
        print(json.dumps(result))

    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))


if __name__ == "__main__":
    main()
