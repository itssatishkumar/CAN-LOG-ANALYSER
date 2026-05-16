from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import json
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# -------- CONFIG --------
TIMEOUT = 60
THIRTY_DAYS = 30 * 24 * 60 * 60

SHEET_ID = "1nDkL93epR1RQfFvCrzAVeiu5a9TpaU2484sOaVkQAQw"

# -------- GOOGLE SHEETS AUTH --------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

creds_json = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
client = gspread.authorize(creds)

sheet = client.open_by_key(SHEET_ID).get_worksheet(4)

# -------- MEMORY --------
clients = {}

def now_ist():
    return datetime.now(ZoneInfo("Asia/Kolkata"))

# -------- LOAD --------
def load_from_sheet():
    global clients
    try:
        rows = sheet.get_all_records()
        for row in rows:
            device = row["DEVISE NAME"]
            clients[device] = {
                "name": row["USER INFO"],
                "login_time": row["LOGIN"],
                "last_seen": row["LOGOUT"]
            }
    except:
        clients = {}

# -------- SAVE (overwrite row if exists) --------
def save_to_sheet():
    rows = sheet.get_all_records()
    row_map = {row["DEVISE NAME"]: idx + 2 for idx, row in enumerate(rows)}

    for device, info in clients.items():
        row_data = [
            device,
            info.get("name", ""),
            info.get("login_time", ""),
            info.get("last_seen", "")
        ]

        if device in row_map:
            sheet.update(f"A{row_map[device]}:D{row_map[device]}", [row_data])
        else:
            sheet.append_row(row_data)

# -------- LOAD EXISTING --------
load_from_sheet()

# -------- ROUTES --------
@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    data = request.json or {}
    device = data.get("device", "unknown")
    name = data.get("name", device)

    now = now_ist().isoformat()

    if device not in clients:
        clients[device] = {
            "name": name,
            "login_time": now,
            "last_seen": now
        }
    else:
        clients[device]["last_seen"] = now

    save_to_sheet()
    return jsonify({"ok": True})

@app.route("/clients", methods=["GET"])
def get_clients():
    return jsonify(clients)

@app.route("/")
def home():
    return "Server running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
