from flask import Flask, jsonify, request

app = Flask(__name__)

# Mock adatbázis a memóriában (Gyártási gép adatok)
machines_data = {
    "CNC-01": {"status": "RUNNING", "temperature": 74.5, "parts_produced": 120},
    "PRESS-02": {"status": "IDLE", "temperature": 28.1, "parts_produced": 0}
}

@app.route('/api/v1/machines/<machine_id>', methods=['GET'])
def get_machine_status(machine_id):
    if machine_id in machines_data:
        return jsonify(machines_data[machine_id]), 200
    else:
        return jsonify({"error": "Machine not found"}), 404

@app.route('/api/v1/machines', methods=['POST'])
def update_machine():
    content = request.json
    
    # Feltételezzük, hogy a küldött JSON tartalmazza a 'machine_id'-t
    machine_id = content.get("machine_id")
    
    if machine_id:
        # Frissítjük vagy létrehozzuk a gépet a memóriában
        machines_data[machine_id] = {
            "status": content.get("status", "UNKNOWN"),
            "temperature": content.get("temperature", 0.0),
            "parts_produced": content.get("parts_produced", 0)
        }
        return jsonify({"status": "SUCCESS", "updated_data": machines_data[machine_id]}), 201
    else:
        return jsonify({"error": "machine_id is required"}), 400
    
if __name__ == '__main__':
    app.run(port=5000)