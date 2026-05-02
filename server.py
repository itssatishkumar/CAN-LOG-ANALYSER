from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

clients = {}

@app.route("/status", methods=["POST"])
def status():
    data = request.json or {}
    host = data.get("host", "unknown")

    clients[host] = {
        "status": data.get("status", "running"),
        "last_seen": datetime.now().strftime("%H:%M:%S")
    }

    return jsonify({"ok": True})


@app.route("/clients", methods=["GET"])
def get_clients():
    return clients


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
