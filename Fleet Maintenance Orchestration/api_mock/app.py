from flask import Flask, request, jsonify
from datetime import datetime, timezone
import uuid

app = Flask(__name__)

# In-memory "adatbázis" - csak demóhoz, újraindításkor törlődik
tasks = {}
stock_locks = {}
technician_assignments = {}
notifications = {}


def now():
    return datetime.now(timezone.utc).isoformat()


@app.route("/tasks", methods=["POST"])
def create_task():
    data = request.get_json(silent=True) or {}
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "task_id": task_id,
        "alert_type": data.get("alert_type"),
        "created_at": now(),
    }
    return jsonify(tasks[task_id]), 201


@app.route("/tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "not found"}), 404
    return jsonify(task)


@app.route("/stock/lock", methods=["POST"])
def lock_stock():
    data = request.get_json(silent=True) or {}
    lock_id = str(uuid.uuid4())
    stock_locks[lock_id] = {
        "lock_id": lock_id,
        "alert_type": data.get("alert_type"),
        "locked_amount": data.get("amount", 1),
        "locked_at": now(),
    }
    return jsonify(stock_locks[lock_id]), 201


@app.route("/technician-assignments", methods=["POST"])
def allocate_technician():
    data = request.get_json(silent=True) or {}
    assignment_id = str(uuid.uuid4())
    technician_assignments[assignment_id] = {
        "assignment_id": assignment_id,
        "alert_type": data.get("alert_type"),
        "technician": "Kovács Péter",  # mock kiosztási logika
        "assigned_at": now(),
    }
    return jsonify(technician_assignments[assignment_id]), 201


@app.route("/notifications", methods=["POST"])
def send_notification():
    data = request.get_json(silent=True) or {}
    notification_id = str(uuid.uuid4())
    notifications[notification_id] = {
        "notification_id": notification_id,
        "recipient_type": data.get("recipient_type"),
        "alert_type": data.get("alert_type"),
        "sent_at": now(),
    }
    print(f"[MOCK NOTIFICATION] -> {data.get('recipient_type')}: alert_type={data.get('alert_type')}")
    return jsonify(notifications[notification_id]), 201


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
