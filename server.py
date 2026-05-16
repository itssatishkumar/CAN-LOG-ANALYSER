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
SHEET_NAME = "Sheet1"   # change if needed

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

# -------- SHEET FUNCTIONS --------
def load_from_sheet():
    global clients
    try:
        rows = sheet.get_all_records()
        for row in rows:
            device = row["device"]
            clients[device] = {
                "name": row["name"],
                "status": row["status"],
                "last_seen": row["last_seen"],
                "last_active": row["last_active"]
            }
    except:
        pass

def save_to_sheet():
    sheet.clear()
    sheet.append_row(["device", "name", "status", "last_seen", "last_active"])

    for device, info in clients.items():
        sheet.append_row([
            device,
            info.get("name", ""),
            info.get("status", ""),
            info.get("last_seen", ""),
            info.get("last_active", "")
        ])

# -------- LOGIC --------
def mark_inactive(timeout_seconds=TIMEOUT):
    now = now_ist()
    for device, info in clients.items():
        last_seen_time = datetime.strptime(info["last_seen"], "%H:%M:%S").replace(
            year=now.year, month=now.month, day=now.day, tzinfo=now.tzinfo
        )
        if (now - last_seen_time).total_seconds() > timeout_seconds:
            info["status"] = "offline"

def cleanup_old():
    now = now_ist()
    to_delete = []
    for device, info in clients.items():
        last_seen_time = datetime.strptime(info["last_seen"], "%H:%M:%S").replace(
            year=now.year, month=now.month, day=now.day, tzinfo=now.tzinfo
        )
        if (now - last_seen_time).total_seconds() > THIRTY_DAYS:
            to_delete.append(device)

    for d in to_delete:
        del clients[d]

# -------- LOAD EXISTING --------
load_from_sheet()

# -------- ROUTES --------
@app.route("/heartbeat", methods=["POST", "GET"])
def heartbeat():
    if request.method == "POST":
        data = request.json or {}
        device = data.get("device", "unknown")
        name = data.get("name", device)

        now = now_ist()

        if device not in clients:
            clients[device] = {"name": name}

        clients[device]["status"] = "alive"
        clients[device]["last_seen"] = now.strftime("%H:%M:%S")
        clients[device]["last_active"] = now.strftime("%H:%M:%S")

        save_to_sheet()

        return jsonify({"message": "heartbeat received", "device": device})

    mark_inactive()
    cleanup_old()
    save_to_sheet()

    return jsonify({
        "status": "server running",
        "connected_devices": clients
    })

@app.route("/status", methods=["POST"])
def status():
    data = request.json or {}
    host = data.get("host", "unknown")
    name = data.get("name", host)

    now = now_ist()

    if host not in clients:
        clients[host] = {"name": name}

    clients[host]["status"] = data.get("status", "running")
    clients[host]["last_seen"] = now.strftime("%H:%M:%S")
    clients[host]["last_active"] = now.strftime("%H:%M:%S")

    save_to_sheet()

    return jsonify({"ok": True})

@app.route("/clients", methods=["GET"])
def get_clients():
    mark_inactive()
    cleanup_old()
    save_to_sheet()
    return jsonify(clients)

@app.route("/", methods=["GET"])
def home():
    return "Server is running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
