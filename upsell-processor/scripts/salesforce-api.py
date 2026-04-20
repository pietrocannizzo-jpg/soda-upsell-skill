# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
Salesforce REST API for the Upsell Processor skill.
Uses Client Credentials Flow (OAuth 2.0).

Credentials must be passed in the input JSON under "sf_credentials":
  {"client_id": "...", "client_secret": "...", "domain": "...", "api_version": "59.0"}

Input (stdin JSON):
  {"command": "auth", "sf_credentials": {...}}
  {"command": "query", "soql": "SELECT ...", "sf_credentials": {...}}
  {"command": "get_opportunity", "opp_id": "006...", "sf_credentials": {...}}
  {"command": "find_open_upsell", "account_name": "Acme Corp", "sf_credentials": {...}}
  {"command": "find_renewal", "account_id": "001...", "sf_credentials": {...}}
  {"command": "update", "object_type": "Opportunity", "record_id": "006...", "data": {"ARR__c": 110000}, "sf_credentials": {...}}
  {"command": "process", "upsell_id": "006...", "arr": 25000, "close_date": "2026-04-17", "sf_credentials": {...}}
"""

import json
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import date

SF_CONFIG = {}


def authenticate():
    """Authenticate using Client Credentials Flow. Returns (access_token, instance_url)."""
    token_url = f"https://{SF_CONFIG['domain']}/services/oauth2/token"
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": SF_CONFIG["client_id"],
        "client_secret": SF_CONFIG["client_secret"],
    }).encode("utf-8")
    req = urllib.request.Request(token_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["access_token"], result["instance_url"]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        return None, f"Authentication failed ({e.code}): {error_body}"


def sf_request(method, path, data=None):
    """Make an authenticated Salesforce REST API request."""
    access_token, instance_url = authenticate()
    if access_token is None:
        return {"error": instance_url}

    api_version = SF_CONFIG.get("api_version", "59.0")
    if path.startswith("/"):
        url = f"{instance_url}{path}"
    else:
        url = f"{instance_url}/services/data/v{api_version}/{path}"

    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    if data:
        req.data = json.dumps(data).encode("utf-8")

    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 204:
                return {"success": True}
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            return {"error": json.loads(error_body)}
        except json.JSONDecodeError:
            return {"error": error_body}


def soql_query(query):
    """Run a SOQL query and return results."""
    api_version = SF_CONFIG.get("api_version", "59.0")
    encoded_query = urllib.parse.quote(query)
    path = f"/services/data/v{api_version}/query?q={encoded_query}"
    return sf_request("GET", path)


def get_opportunity(opp_id):
    query = f"""
    SELECT Id, Name, AccountId, Account.Name, StageName, Amount, ARR__c,
           CurrencyIsoCode, Type, Region__c,
           Subscription_Start_Date__c, Subscription_Length_Months__c,
           Owner.Name, Owner.Email
    FROM Opportunity
    WHERE Id = '{opp_id}'
    """
    return soql_query(query.strip())


def find_open_upsell(account_name):
    query = f"""
    SELECT Id, Name, AccountId, Account.Name, StageName, Amount,
           CurrencyIsoCode, Owner.Name, Owner.Email
    FROM Opportunity
    WHERE (Account.Name LIKE '%{account_name}%' OR Name LIKE '%{account_name}%')
      AND Name LIKE '%Upsell%'
      AND StageName != 'Closed Won'
      AND StageName != 'Closed Lost'
    ORDER BY LastModifiedDate DESC
    LIMIT 5
    """
    return soql_query(query.strip())


def find_renewal(account_id):
    query = f"""
    SELECT Id, Name, AccountId, StageName, Amount, ARR__c, CurrencyIsoCode, Owner.Name, Owner.Email
    FROM Opportunity
    WHERE AccountId = '{account_id}'
      AND Name LIKE '%Renewal%'
    ORDER BY CreatedDate DESC
    LIMIT 1
    """
    return soql_query(query.strip())


def update_opportunity(opp_id, fields):
    api_version = SF_CONFIG.get("api_version", "59.0")
    path = f"/services/data/v{api_version}/sobjects/Opportunity/{opp_id}"
    return sf_request("PATCH", path, data=fields)


def process_upsell(upsell_id, arr, close_date=None):
    """
    Full upsell processing:
    1. Get the upsell Opportunity
    2. Close it as Won + set ARR in a single PATCH
    3. Find the Renewal for the same Account
    4. Update Renewal ARR = existing + upsell ARR
    """
    arr = float(arr)
    close_date = close_date or date.today().isoformat()

    upsell_result = get_opportunity(upsell_id)
    if not upsell_result.get("records"):
        return {"error": f"Upsell Opportunity {upsell_id} not found"}

    upsell = upsell_result["records"][0]
    account_id = upsell["AccountId"]
    account_name = upsell.get("Account", {}).get("Name", "Unknown")
    owner_name = upsell.get("Owner", {}).get("Name", "Unknown")
    owner_email = upsell.get("Owner", {}).get("Email", None)

    update_opportunity(upsell_id, {
        "StageName": "Closed Won",
        "CloseDate": close_date,
        "ARR__c": arr,
    })

    renewal_result = find_renewal(account_id)
    if not renewal_result.get("records"):
        return {"error": f"No Renewal found for account {account_name} ({account_id})"}

    renewal = renewal_result["records"][0]
    renewal_arr_existing = renewal.get("ARR__c")
    renewal_amount_existing = renewal.get("Amount") or 0
    base_arr = renewal_arr_existing if renewal_arr_existing else renewal_amount_existing
    new_renewal_arr = base_arr + arr

    update_opportunity(renewal["Id"], {"ARR__c": new_renewal_arr, "Amount": new_renewal_arr})

    return {
        "success": True,
        "upsell": {
            "id": upsell["Id"], "name": upsell["Name"],
            "account": account_name, "account_id": account_id,
            "arr": arr, "currency": upsell.get("CurrencyIsoCode", "Unknown"),
            "closed_date": close_date,
        },
        "renewal": {
            "id": renewal["Id"], "name": renewal["Name"],
            "base_used": "ARR__c" if renewal_arr_existing else "Amount",
            "old_value": base_arr, "new_arr": new_renewal_arr,
        },
        "owner": {"name": owner_name, "email": owner_email},
    }


def main():
    global SF_CONFIG
    data = json.load(sys.stdin)

    sf_creds = data.get("sf_credentials")
    if not sf_creds:
        print(json.dumps({"error": "sf_credentials is required in input"}))
        return
    SF_CONFIG = sf_creds

    command = data.get("command")

    if command == "auth":
        token, url = authenticate()
        if token:
            print(json.dumps({"success": True, "instance_url": url}))
        else:
            print(json.dumps({"error": url}))

    elif command == "query":
        print(json.dumps(soql_query(data["soql"])))

    elif command == "get_opportunity":
        print(json.dumps(get_opportunity(data["opp_id"])))

    elif command == "find_open_upsell":
        print(json.dumps(find_open_upsell(data["account_name"])))

    elif command == "find_renewal":
        print(json.dumps(find_renewal(data["account_id"])))

    elif command == "update":
        api_version = SF_CONFIG.get("api_version", "59.0")
        path = f"/services/data/v{api_version}/sobjects/{data['object_type']}/{data['record_id']}"
        print(json.dumps(sf_request("PATCH", path, data=data.get("data", {}))))

    elif command == "process":
        print(json.dumps(process_upsell(
            data["upsell_id"], data["arr"], close_date=data.get("close_date"),
        )))

    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))


if __name__ == "__main__":
    main()
