from flask import Flask, request, jsonify, session, render_template, redirect, url_for
import json
import os
import re
from functools import wraps

app = Flask(__name__)
app.secret_key = "yobetoje"

DATA_FILE = "data.json"
phone_regex = re.compile(r"^\+98\d{10}$")

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "tasks": {}, "time": {}, "breaks": {}}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            return "Forbidden", 403
        return f(*args, **kwargs)
    return decorated

def developer_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "developer":
            return "Forbidden", 403
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def login_page():
    if "username" in session:
        if session["role"] == "admin":
            return redirect(url_for('admin_dashboard'))
        elif session["role"] == "developer":
            return redirect(url_for('user_dashboard'))
    return render_template("login.html")

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400
    db = load_data()
    user = db["users"].get(username)
    if not user or user["password"] != password:
        return jsonify({"error": "Invalid credentials"}), 401
    session["username"] = username
    session["role"] = user["role"]
    return jsonify({"username": username, "role": user["role"]})

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})

# ============== Admin pages ====================

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    return render_template("admin_dashboard.html")

@app.route('/admin/user', methods=['GET'])
@login_required
@admin_required
def admin_get_users():
    db = load_data()
    users = db["users"]
    users_safe = {u: {k:v for k,v in info.items() if k!="password"} for u, info in users.items()}
    return jsonify(users_safe)

@app.route('/admin/user', methods=['POST'])
@login_required
@admin_required
def admin_add_user():
    data = request.json
    required_fields = ["username","password","email","numberphone","github_id","role"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing fields"}), 400
    if not phone_regex.match(data["numberphone"]):
        return jsonify({"error": "Phone number format invalid. Use +98XXXXXXXXXX"}), 400
    db = load_data()
    if data["username"] in db["users"]:
        return jsonify({"error": "Username exists"}), 400
    db["users"][data["username"]] = {
        "username": data["username"],
        "password": data["password"],
        "email": data["email"],
        "numberphone": data["numberphone"],
        "github_id": data["github_id"],
        "role": data["role"]
    }
    save_data(db)
    return jsonify({"message": "User added"})

@app.route('/admin/task', methods=['GET'])
@login_required
@admin_required
def admin_get_tasks():
    db = load_data()
    return jsonify(db["tasks"])

@app.route('/admin/task', methods=['POST'])
@login_required
@admin_required
def admin_add_task():
    data = request.json
    required_fields = ["title", "description", "developers"]  # note plural
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing fields"}), 400
    devs_raw = data["developers"]
    if not devs_raw:
        return jsonify({"error": "At least one developer required"}), 400

    db = load_data()

    # Parse developers: comma separated, strip spaces
    devs = [d.strip() for d in devs_raw.split(",") if d.strip()]
    if not devs:
        return jsonify({"error": "Invalid developers list"}), 400

    # Validate each developer exists and has role developer
    for d in devs:
        if d not in db["users"] or db["users"][d]["role"] != "developer":
            return jsonify({"error": f"Developer '{d}' not found or invalid"}), 400

    # Add a separate task for each developer
    max_id = max([int(k) for k in db["tasks"].keys()] + [0])
    created_task_ids = []
    for d in devs:
        max_id += 1
        tid = str(max_id)
        db["tasks"][tid] = {
            "id": tid,
            "title": data["title"],
            "description": data["description"],
            "developer": d,
            "status": "pending",
            "updates": []
        }
        created_task_ids.append(tid)

    save_data(db)
    return jsonify({"message": "Tasks added for developers", "task_ids": created_task_ids})

@app.route('/admin/time', methods=['GET'])
@login_required
@admin_required
def admin_time():
    db = load_data()
    return jsonify(db.get("time", {}))

@app.route('/admin/task/updates/<task_id>', methods=['GET'])
@login_required
@admin_required
def admin_task_updates(task_id):
    db = load_data()
    task = db["tasks"].get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task.get("updates", []))

@app.route('/admin/task/updates/<task_id>/decide', methods=['POST'])
@login_required
@admin_required
def admin_task_decide(task_id):
    data = request.json
    decision = data.get("decision")  # 'accept' or 'reject'
    update_index = data.get("update_index")  # which update to decide on
    reason = data.get("reason", "")  # optional reject reason

    if decision not in ("accept", "reject") or update_index is None:
        return jsonify({"error": "Missing or invalid fields"}), 400

    db = load_data()
    task = db["tasks"].get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    updates = task.get("updates", [])
    if update_index < 0 or update_index >= len(updates):
        return jsonify({"error": "Invalid update index"}), 400

    update = updates[update_index]
    if "decision" in update:
        return jsonify({"error": "This update was already decided"}), 400

    if decision == "accept":
        update["decision"] = "accepted"
        update["reason"] = ""
        task["status"] = "done"
    else:
        update["decision"] = "rejected"
        update["reason"] = reason or "No reason provided"
        task["status"] = "pending"

    save_data(db)
    return jsonify({"message": f"Update {decision}ed"})

# ============== Developer (User) pages =================

@app.route('/user')
@login_required
@developer_required
def user_dashboard():
    return render_template("user_dashboard.html")

@app.route('/user/task', methods=['GET'])
@login_required
@developer_required
def user_get_tasks():
    db = load_data()
    username = session["username"]
    tasks = {tid: t for tid,t in db["tasks"].items() if t["developer"] == username}
    return jsonify(tasks)

@app.route('/user/task/say/<task_id>', methods=['POST'])
@login_required
@developer_required
def user_task_say(task_id):
    data = request.json
    description = data.get("description")
    if not description:
        return jsonify({"error": "Description required"}), 400
    db = load_data()
    task = db["tasks"].get(task_id)
    if not task or task["developer"] != session["username"]:
        return jsonify({"error": "Task not found or not assigned to you"}), 404
    update = {"description": description}
    task.setdefault("updates", []).append(update)
    task["status"] = "in progress"
    save_data(db)
    return jsonify({"message": "Update added"})

@app.route('/user/break', methods=['POST'])
@login_required
@developer_required
def user_break():
    # Mark break (for simplicity, just note a timestamp)
    # Not implemented detailed time tracking here, just dummy example
    return jsonify({"message": "Break registered"})

if __name__ == "__main__":
    app.run(debug=True)
