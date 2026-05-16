from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import json

app = Flask(__name__)

DATA_FILE = "clients.json"
TIMEOUT = 60
THIRTY_DAYS = 30 * 24 * 60 * 60

def now_ist():
    return datetime.now(ZoneInfo("Asia/Kolkata"))

# -------- load data --------
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        raw = json.load(f)
        clients = raw
else:
    clients = {}

def save_clients():
    with open(DATA_FILE, "w") as f:
        json.dump(clients, f)

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

    if to_delete:
        save_clients()

# ✅ heartbeat
@app.route("/heartbeat", methods=["POST", "GET"])
def heartbeat():
    if request.method == "POST":
        data = request.json or {}
        device = data.get("device", "unknown")
        name = data.get("name", device)

        now = now_ist()

        if device in clients:
            clients[device]["status"] = "alive"
        else:
            clients[device] = {
                "name": name,
                "status": "alive"
            }

        clients[device]["last_seen"] = now.strftime("%H:%M:%S")
        clients[device]["last_active"] = now.strftime("%H:%M:%S")

        save_clients()
        return jsonify({"message": "heartbeat received", "device": device})

    mark_inactive()
    cleanup_old()
    return jsonify({
        "status": "server running",
        "connected_devices": clients
    })

# ✅ status
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

    save_clients()
    return jsonify({"ok": True})

# ✅ clients
@app.route("/clients", methods=["GET"])
def get_clients():
    mark_inactive()
    cleanup_old()
    return jsonify(clients)

# ✅ root
@app.route("/", methods=["GET"])
def home():
    return "Server is running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
