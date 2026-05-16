from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

clients = {}

def now_ist():
    return datetime.now(ZoneInfo("Asia/Kolkata"))

def mark_inactive(timeout_seconds=60):
    now = now_ist()
    for device, info in clients.items():
        last_seen_time = datetime.strptime(info["last_seen"], "%H:%M:%S").replace(
            year=now.year, month=now.month, day=now.day, tzinfo=now.tzinfo
        )
        if (now - last_seen_time).total_seconds() > timeout_seconds:
            info["status"] = "offline"

# ✅ heartbeat endpoint
@app.route("/heartbeat", methods=["POST", "GET"])
def heartbeat():
    if request.method == "POST":
        data = request.json or {}
        device = data.get("device", "unknown")
        name = data.get("name", device)

        now = now_ist()

        if device in clients:
            clients[device]["status"] = "alive"
            clients[device]["last_seen"] = now.strftime("%H:%M:%S")
            clients[device]["last_active"] = now.strftime("%H:%M:%S")
        else:
            clients[device] = {
                "name": name,
                "status": "alive",
                "last_seen": now.strftime("%H:%M:%S"),
                "last_active": now.strftime("%H:%M:%S")
            }

        return jsonify({"message": "heartbeat received", "device": device})

    mark_inactive()
    return jsonify({
        "status": "server running",
        "connected_devices": clients
    })

# ✅ status endpoint
@app.route("/status", methods=["POST"])
def status():
    data = request.json or {}
    host = data.get("host", "unknown")
    name = data.get("name", host)

    now = now_ist()

    if host in clients:
        clients[host]["status"] = data.get("status", "running")
        clients[host]["last_seen"] = now.strftime("%H:%M:%S")
        clients[host]["last_active"] = now.strftime("%H:%M:%S")
    else:
        clients[host] = {
            "name": name,
            "status": data.get("status", "running"),
            "last_seen": now.strftime("%H:%M:%S"),
            "last_active": now.strftime("%H:%M:%S")
        }

    return jsonify({"ok": True})

# ✅ view all clients
@app.route("/clients", methods=["GET"])
def get_clients():
    mark_inactive()
    return jsonify(clients)

# ✅ root check
@app.route("/", methods=["GET"])
def home():
    return "Server is running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
