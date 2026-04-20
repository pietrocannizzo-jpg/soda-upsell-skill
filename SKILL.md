# Upsell Processor

Process signed upsell contracts end-to-end: close upsell Opportunities in Salesforce, update Renewal ARR, log changes to Google Sheets (ARR Tracker + Customer Overview), and generate a summary for Slack.

## Scripts

- **salesforce-api** — Salesforce REST API (Client Credentials OAuth). Commands: `auth`, `query`, `get_opportunity`, `find_open_upsell`, `find_renewal`, `update`, `process`.
- **sheets-api** — Google Sheets API (Service Account). Commands: `read`, `get_headers`, `append`, `find_and_update`, `find_row`, `update_cell`, `extend_formulas`.

## Credentials

Both scripts require credentials passed in the input JSON. The agent system prompt contains the credential objects. Always include them when calling a script:

- `sf_credentials` — Salesforce OAuth2 client credentials (client_id, client_secret, domain, api_version)
- `gsheets_credentials` — Google service account JSON (full object with private_key)

## Workflow

1. `salesforce-api` with `{"command": "find_open_upsell", "account_name": "...", "sf_credentials": {...}}` to locate the open upsell Opportunity.
2. `salesforce-api` with `{"command": "process", "upsell_id": "...", "arr": ..., "close_date": "YYYY-MM-DD", "sf_credentials": {...}}` to close it as Won and update the Renewal.
3. `sheets-api` with `{"command": "append", ..., "gsheets_credentials": {...}}` to add a row to the ARR Tracker.
4. `sheets-api` with `{"command": "extend_formulas", ..., "gsheets_credentials": {...}}` to propagate formulas to the new row.
5. `sheets-api` with `{"command": "find_and_update", ..., "gsheets_credentials": {...}}` to update Customer Overview ARR.

## Sheet IDs

- **ARR Tracker**: `14grEEWWP5VBXlhDBlK-H4sMYKYJNk8SBYnxorl4dOHg` (worksheet: `Current ARR`)
- **Customer Overview**: `1BZevEHENesy68vziZHXW_Y7SIvgExV-mjLfwVJHzLG8` (worksheet: `Active Customers`)
