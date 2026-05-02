from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

clients = {}

# ✅ heartbeat endpoint (what your app is calling)
@app.route("/heartbeat", methods=["POST", "GET"])
def heartbeat():
    if request.method == "POST":
        data = request.json or {}
        device = data.get("device", "unknown")

        clients[device] = {
            "status": "alive",
            "last_seen": datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M:%S")
        }

        return jsonify({"message": "heartbeat received", "device": device})

    # GET → show something in browser
    return jsonify({
        "status": "server running",
        "connected_devices": clients
    })


# existing status API
@app.route("/status", methods=["POST"])
def status():
    data = request.json or {}
    host = data.get("host", "unknown")

    clients[host] = {
        "status": data.get("status", "running"),
        "last_seen": datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M:%S")
    }

    return jsonify({"ok": True})


# view all clients
@app.route("/clients", methods=["GET"])
def get_clients():
    return jsonify(clients)


# optional root check
@app.route("/", methods=["GET"])
def home():
    return "Server is running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
