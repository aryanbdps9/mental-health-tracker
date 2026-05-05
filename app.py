import argparse
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory, make_response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_DIR = os.path.join(os.path.expanduser("~"), ".mental-health-tracker")
LOCAL_PREFS_FILE = os.path.join(LOCAL_DIR, "local.json")
DEFAULT_DATA_DIR = os.path.join(LOCAL_DIR, "data")
QUESTIONNAIRE_DIR = os.path.join(BASE_DIR, "questionnaires")


def load_local_prefs():
    if os.path.exists(LOCAL_PREFS_FILE):
        with open(LOCAL_PREFS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_local_prefs(prefs):
    os.makedirs(LOCAL_DIR, exist_ok=True)
    with open(LOCAL_PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)


def resolve_data_dir(cli_arg=None):
    """Precedence: CLI arg > saved local pref > default.
    If CLI arg is given, save it for next time."""
    prefs = load_local_prefs()
    if cli_arg:
        prefs["data_dir"] = cli_arg
        save_local_prefs(prefs)
        return cli_arg
    saved = prefs.get("data_dir")
    if saved:
        return saved
    return DEFAULT_DATA_DIR


app = Flask(__name__, static_folder="static", template_folder="templates")

SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")

# ─── Security ────────────────────────────────────────────────

def check_auth():
    """Verify the session token cookie matches."""
    token = app.config.get("AUTH_TOKEN")
    if not token:
        return  # no auth configured
    cookie = request.cookies.get("mht_token")
    if not cookie or not secrets.compare_digest(cookie, token):
        return jsonify({"error": "Unauthorized"}), 401


@app.before_request
def before_request_hook():
    # Reset inactivity timer on every request
    app.config["LAST_ACTIVITY"] = time.time()

    # Skip auth for login page and static assets
    if request.path in ("/", "/login") or request.path.startswith("/static/"):
        return

    auth_result = check_auth()
    if auth_result:
        return auth_result


@app.after_request
def security_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
    # Block cross-origin requests
    origin = request.headers.get("Origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = ""  # deny all
    return response


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    password = data.get("password", "")
    expected_hash = app.config.get("PASSWORD_HASH")
    if not expected_hash:
        return jsonify({"error": "No password configured"}), 500
    if hashlib.sha256(password.encode()).hexdigest() == expected_hash:
        token = app.config["AUTH_TOKEN"]
        resp = make_response(jsonify({"status": "ok"}))
        resp.set_cookie("mht_token", token, httponly=True, samesite="Strict", path="/")
        return resp
    return jsonify({"error": "Wrong password"}), 401


def start_inactivity_timer(timeout_minutes):
    """Shut down the server after timeout_minutes of no requests."""
    if not timeout_minutes:
        return

    def watcher():
        while True:
            time.sleep(30)
            elapsed = time.time() - app.config.get("LAST_ACTIVITY", time.time())
            if elapsed > timeout_minutes * 60:
                print(f"\n⏱ No activity for {timeout_minutes} minutes. Shutting down.")
                os._exit(0)

    t = threading.Thread(target=watcher, daemon=True)
    t.start()


def get_data_dir():
    return app.config.get("DATA_DIR", DEFAULT_DATA_DIR)


def get_staging_dir():
    return os.path.join(get_data_dir(), "staging")


def get_entries_dir():
    return os.path.join(get_data_dir(), "entries")


def get_prefs_dir():
    return os.path.join(get_data_dir(), "prefs")


def ensure_dirs():
    os.makedirs(get_staging_dir(), exist_ok=True)
    os.makedirs(get_entries_dir(), exist_ok=True)
    os.makedirs(get_prefs_dir(), exist_ok=True)


def safe_write(filepath, data):
    """Atomic write: write to temp file then rename."""
    dirpath = os.path.dirname(filepath)
    fd, tmp = tempfile.mkstemp(dir=dirpath, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, filepath)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_questionnaires():
    questionnaires = {}
    for fname in os.listdir(QUESTIONNAIRE_DIR):
        if fname.endswith(".json") and fname != "flows.json":
            fpath = os.path.join(QUESTIONNAIRE_DIR, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                q = json.load(f)
            questionnaires[q["id"]] = q
    return questionnaires


def load_flows():
    fpath = os.path.join(QUESTIONNAIRE_DIR, "flows.json")
    if not os.path.exists(fpath):
        return []
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    flows = data.get("flows", [])
    # Merge user-saved order preferences
    for flow in flows:
        saved_order, saved_selected = _load_flow_order(flow["id"])
        if saved_order:
            defined = set(flow["questionnaire_order"])
            valid = [qid for qid in saved_order if qid in defined]
            for qid in flow["questionnaire_order"]:
                if qid not in valid:
                    valid.append(qid)
            flow["questionnaire_order"] = valid
        if saved_selected is not None:
            flow["selected"] = saved_selected
    return flows


def _load_flow_order(flow_id):
    fpath = os.path.join(get_prefs_dir(), f"flow_order_{flow_id}.json")
    if not os.path.exists(fpath):
        return None, None
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("order"), data.get("selected")


def _save_flow_order(flow_id, order, selected=None):
    ensure_dirs()
    fpath = os.path.join(get_prefs_dir(), f"flow_order_{flow_id}.json")
    data = {"flow_id": flow_id, "order": order}
    if selected is not None:
        data["selected"] = selected
    safe_write(fpath, data)


def get_question_map(questionnaire):
    return {q["id"]: q for q in questionnaire["questions"]}


def should_show(question, responses):
    cond = question.get("show_if")
    if not cond:
        return True
    if "any_of" in cond:
        return any(
            responses.get(c["question"]) == c["equals"] for c in cond["any_of"]
        )
    return responses.get(cond["question"]) == cond["equals"]


def get_visible_questions(questionnaire, responses):
    return [q for q in questionnaire["questions"] if should_show(q, responses)]


def find_option_label(question, opt_id):
    """Look up option by its ID and return the label. For sliders, format as percentage."""
    if question.get("type") == "slider":
        return f"{opt_id}%"
    for opt in question.get("options", []):
        if opt["id"] == opt_id:
            return opt["label"]
    return str(opt_id)


def resolve_opt_value(question_map, qid, opt_id):
    """Given a stored option ID, return its numeric/semantic value for scoring."""
    q = question_map.get(qid)
    if not q:
        return opt_id
    for opt in q.get("options", []):
        if opt["id"] == opt_id:
            return opt["value"]
    return opt_id


def opt_value_is(question_map, qid, opt_id, expected):
    """Check if the option ID's underlying value equals expected."""
    return resolve_opt_value(question_map, qid, opt_id) == expected


def calculate_scores(questionnaire, responses):
    scoring = questionnaire.get("scoring", {})
    method = scoring.get("method", "none")
    question_map = get_question_map(questionnaire)

    if method == "sum":
        scored_ids = set(scoring.get("scored_questions", []))
        total = 0
        for qid in scored_ids:
            opt_id = responses.get(qid)
            if opt_id is not None:
                val = resolve_opt_value(question_map, qid, opt_id)
                if isinstance(val, (int, float)):
                    total += val
        severity = None
        for r in scoring.get("ranges", []):
            if r["min"] <= total <= r["max"]:
                severity = r["label"]
                break
        return {"total": total, "severity": severity}

    elif method == "threshold_count":
        thresholds = scoring.get("thresholds", {})
        screener = scoring.get("screener_questions", [])
        positive_count = 0
        for qid in screener:
            opt_id = responses.get(qid)
            if opt_id is not None:
                val = resolve_opt_value(question_map, qid, opt_id)
                threshold = thresholds.get(qid, 0)
                if isinstance(val, (int, float)) and val >= threshold:
                    positive_count += 1
        is_positive = positive_count >= scoring.get("positive_count", 4)
        all_questions = [q["id"] for q in questionnaire["questions"] if q.get("scored", True)]
        part_a_total = sum(
            resolve_opt_value(question_map, qid, responses[qid])
            for qid in screener
            if responses.get(qid) is not None
            and isinstance(resolve_opt_value(question_map, qid, responses[qid]), (int, float))
        )
        full_total = sum(
            resolve_opt_value(question_map, qid, responses[qid])
            for qid in all_questions
            if responses.get(qid) is not None
            and isinstance(resolve_opt_value(question_map, qid, responses[qid]), (int, float))
        )
        return {
            "screener_positive_count": positive_count,
            "screener_result": scoring["positive_label"] if is_positive else scoring["negative_label"],
            "part_a_total": part_a_total,
            "total": full_total,
        }

    elif method == "multi_criteria":
        criteria_results = []
        all_met = True
        for crit in scoring.get("criteria", []):
            met = False
            if crit["type"] == "count_yes":
                count = sum(
                    1 for qid in crit["questions"]
                    if opt_value_is(question_map, qid, responses.get(qid), "yes")
                )
                met = count >= crit["min_count"]
                criteria_results.append({
                    "id": crit["id"], "label": crit["label"],
                    "met": met, "count": count, "required": crit["min_count"],
                })
            elif crit["type"] == "equals":
                met = responses.get(crit["question"]) == crit["value"]
                criteria_results.append({
                    "id": crit["id"], "label": crit["label"], "met": met,
                })
            elif crit["type"] == "in":
                met = responses.get(crit["question"]) in crit["values"]
                criteria_results.append({
                    "id": crit["id"], "label": crit["label"], "met": met,
                })
            if not met:
                all_met = False
        return {
            "screen_result": scoring["all_met_label"] if all_met else scoring["not_met_label"],
            "positive": all_met,
            "criteria": criteria_results,
        }

    elif method == "categorical":
        ideation_qs = scoring.get("ideation_questions", [])
        ideation_labels = scoring.get("ideation_labels", {})
        ideation_level = 0
        for i, qid in enumerate(ideation_qs, 1):
            if opt_value_is(question_map, qid, responses.get(qid), "yes"):
                ideation_level = i
        behavior_q = scoring.get("behavior_question", "")
        frequency_q = scoring.get("frequency_question", "")
        protective_q = scoring.get("protective_question", "")
        return {
            "ideation_level": ideation_level,
            "ideation_label": ideation_labels.get(str(ideation_level), "Unknown"),
            "behavior": opt_value_is(question_map, behavior_q, responses.get(behavior_q), "yes"),
            "frequency": find_option_label(question_map.get(frequency_q, {}), responses.get(frequency_q)) if responses.get(frequency_q) else None,
            "protective_factors": [find_option_label(question_map.get(protective_q, {}), pid) for pid in (responses.get(protective_q) or [])],
        }

    return {}


# --- Routes ---

@app.route("/")
def index():
    # If auth is configured, check token
    token = app.config.get("AUTH_TOKEN")
    if token:
        cookie = request.cookies.get("mht_token")
        if not cookie or not secrets.compare_digest(cookie, token):
            return send_from_directory("templates", "login.html")
    return send_from_directory("templates", "index.html")


@app.route("/api/questionnaires")
def list_questionnaires():
    qs = load_questionnaires()
    result = []
    for q in sorted(qs.values(), key=lambda x: x.get("display_order", 99)):
        result.append({
            "id": q["id"],
            "title": q["title"],
            "description": q["description"],
            "recall_period": q.get("recall_period", ""),
            "question_count": len(q["questions"]),
            "micro": q.get("micro", False),
        })
    return jsonify(result)


@app.route("/api/flows")
def list_flows():
    flows = load_flows()
    qs = load_questionnaires()
    result = []
    for flow in flows:
        total_questions = 0
        for qid in flow.get("questionnaire_order", []):
            q = qs.get(qid)
            if q:
                total_questions += len(q["questions"])
        result.append({
            "id": flow["id"],
            "title": flow["title"],
            "description": flow.get("description", ""),
            "questionnaire_order": flow["questionnaire_order"],
            "questionnaire_count": len(flow["questionnaire_order"]),
            "total_questions": total_questions,
            "ordering_constraints": flow.get("ordering_constraints", []),
            "selected": flow.get("selected"),
        })
    return jsonify(result)


@app.route("/api/flows/<flow_id>/order", methods=["POST"])
def save_flow_order(flow_id):
    if not SAFE_ID.match(flow_id):
        return jsonify({"error": "Invalid flow ID"}), 400

    data = request.get_json()
    order = data.get("order")
    selected = data.get("selected")  # optional subset
    if not order or not isinstance(order, list):
        return jsonify({"error": "order must be a list of questionnaire IDs"}), 400

    for qid in order:
        if not isinstance(qid, str) or not SAFE_ID.match(qid):
            return jsonify({"error": f"Invalid questionnaire ID: {qid}"}), 400

    if selected is not None:
        if not isinstance(selected, list):
            return jsonify({"error": "selected must be a list"}), 400
        for qid in selected:
            if not isinstance(qid, str) or not SAFE_ID.match(qid):
                return jsonify({"error": f"Invalid questionnaire ID: {qid}"}), 400

    # Load the flow definition to validate constraints
    fpath = os.path.join(QUESTIONNAIRE_DIR, "flows.json")
    with open(fpath, "r", encoding="utf-8") as f:
        flows_data = json.load(f)
    flow_def = None
    for f_item in flows_data.get("flows", []):
        if f_item["id"] == flow_id:
            flow_def = f_item
            break
    if not flow_def:
        return jsonify({"error": "Flow not found"}), 404

    # Check that order contains exactly the defined IDs
    defined = set(flow_def["questionnaire_order"])
    provided = set(order)
    if defined != provided:
        return jsonify({"error": "Order must contain exactly the same questionnaire IDs"}), 400

    # Validate ordering constraints among selected items only
    active = set(selected) if selected else provided
    for constraint in flow_def.get("ordering_constraints", []):
        if constraint["before"] not in active or constraint["after"] not in active:
            continue
        before_idx = order.index(constraint["before"])
        after_idx = order.index(constraint["after"])
        if before_idx >= after_idx:
            return jsonify({
                "error": f"Constraint violated: {constraint['reason']}",
                "constraint": constraint,
            }), 400

    _save_flow_order(flow_id, order, selected)
    return jsonify({"status": "ok", "order": order, "selected": selected})


@app.route("/api/questionnaire/<qid>")
def get_questionnaire(qid):
    if not SAFE_ID.match(qid):
        return jsonify({"error": "Invalid questionnaire ID"}), 400
    qs = load_questionnaires()
    q = qs.get(qid)
    if not q:
        return jsonify({"error": "Questionnaire not found"}), 404
    return jsonify(q)


@app.route("/api/staging", methods=["GET"])
def list_staging():
    ensure_dirs()
    result = []
    for fname in os.listdir(get_staging_dir()):
        if fname.endswith(".json"):
            fpath = os.path.join(get_staging_dir(), fname)
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            result.append(data)
    return jsonify(result)


@app.route("/api/staging/<entry_id>", methods=["GET"])
def get_staging(entry_id):
    if not SAFE_ID.match(entry_id):
        return jsonify({"error": "Invalid entry ID"}), 400
    fpath = os.path.join(get_staging_dir(), f"{entry_id}.json")
    if not os.path.exists(fpath):
        return jsonify({"error": "Staging entry not found"}), 404
    with open(fpath, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/staging", methods=["POST"])
def save_staging():
    ensure_dirs()
    data = request.get_json()
    if not data or "questionnaire_id" not in data:
        return jsonify({"error": "questionnaire_id required"}), 400

    entry_id = data.get("entry_id") or str(uuid.uuid4())
    if not SAFE_ID.match(entry_id):
        return jsonify({"error": "Invalid entry ID"}), 400
    if not SAFE_ID.match(data["questionnaire_id"]):
        return jsonify({"error": "Invalid questionnaire ID"}), 400

    staging_data = {
        "entry_id": entry_id,
        "questionnaire_id": data["questionnaire_id"],
        "responses": data.get("responses", {}),
        "current_index": data.get("current_index", 0),
        "started_at": data.get("started_at") or datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if data.get("flow_id"):
        staging_data["flow_id"] = data["flow_id"]
        staging_data["flow_step"] = data.get("flow_step", 0)
        staging_data["flow_session_id"] = data.get("flow_session_id", "")
    if data.get("implied_questions"):
        staging_data["implied_questions"] = data["implied_questions"]
    if data.get("gap_hours"):
        staging_data["gap_hours"] = data["gap_hours"]
    fpath = os.path.join(get_staging_dir(), f"{entry_id}.json")
    safe_write(fpath, staging_data)
    return jsonify(staging_data)


@app.route("/api/staging/<entry_id>", methods=["DELETE"])
def discard_staging(entry_id):
    if not SAFE_ID.match(entry_id):
        return jsonify({"error": "Invalid entry ID"}), 400
    fpath = os.path.join(get_staging_dir(), f"{entry_id}.json")
    if os.path.exists(fpath):
        os.unlink(fpath)
    return jsonify({"status": "ok"})


@app.route("/api/submit/<entry_id>", methods=["POST"])
def submit_entry(entry_id):
    ensure_dirs()
    if not SAFE_ID.match(entry_id):
        return jsonify({"error": "Invalid entry ID"}), 400

    # Guard against duplicate submission
    entries_dir = get_entries_dir()
    for fname in os.listdir(entries_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(entries_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                if json.load(f).get("entry_id") == entry_id:
                    return jsonify({"error": "Already submitted"}), 409
        except (json.JSONDecodeError, OSError):
            continue

    staging_path = os.path.join(get_staging_dir(), f"{entry_id}.json")
    if not os.path.exists(staging_path):
        return jsonify({"error": "Staging entry not found"}), 404

    with open(staging_path, "r", encoding="utf-8") as f:
        staging = json.load(f)

    qs = load_questionnaires()
    questionnaire = qs.get(staging["questionnaire_id"])
    if not questionnaire:
        return jsonify({"error": "Questionnaire not found"}), 404

    responses = staging.get("responses", {})
    question_map = get_question_map(questionnaire)
    visible = get_visible_questions(questionnaire, responses)
    visible_ids = {q["id"] for q in visible}

    implied_ids = set(staging.get("implied_questions", []))

    response_list = []
    for q in visible:
        val = responses.get(q["id"])
        if val is not None:
            resp_item = {
                "question_id": q["id"],
                "question_text": q["text"],
                "section": q.get("section", ""),
                "value": val,
                "value_label": find_option_label(q, val) if q["type"] != "text" else val,
            }
            if q["id"] in implied_ids:
                resp_item["auto_implied"] = True
            response_list.append(resp_item)

    scores = calculate_scores(questionnaire, responses)

    now = datetime.now(timezone.utc)
    is_micro = questionnaire.get("micro", False)
    entry = {
        "schema_version": 2 if is_micro else 1,
        "entry_id": entry_id,
        "questionnaire_id": questionnaire["id"],
        "questionnaire_title": questionnaire["title"],
        "date": now.strftime("%Y-%m-%d"),
        "started_at": staging.get("started_at"),
        "completed_at": now.isoformat(),
        "responses": response_list,
        "scores": scores,
    }
    if is_micro:
        entry["micro"] = True
        if staging.get("gap_hours"):
            entry["gap_hours"] = staging["gap_hours"]
    if staging.get("flow_id"):
        entry["flow_id"] = staging["flow_id"]
        entry["flow_session_id"] = staging.get("flow_session_id", "")

    filename = f"{now.strftime('%Y-%m-%d_%H%M%S')}_{questionnaire['id']}.json"
    entry_path = os.path.join(get_entries_dir(), filename)
    safe_write(entry_path, entry)

    # Retry unlink — Windows may briefly lock the file (antivirus, indexer)
    for attempt in range(5):
        try:
            os.unlink(staging_path)
            break
        except PermissionError:
            if attempt < 4:
                time.sleep(0.1)
            else:
                app.logger.warning("Could not delete staging file %s", staging_path)
    return jsonify(entry)


@app.route("/api/entries")
def list_entries():
    ensure_dirs()
    questionnaire_filter = request.args.get("questionnaire")
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    search_q = (request.args.get("search") or "").lower().strip()

    entries = []
    for fname in sorted(os.listdir(get_entries_dir()), reverse=True):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(get_entries_dir(), fname)
        with open(fpath, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if questionnaire_filter and entry.get("questionnaire_id") != questionnaire_filter:
            continue
        entry_date = entry.get("date", "")
        if date_from and entry_date < date_from:
            continue
        if date_to and entry_date > date_to:
            continue
        if search_q:
            searchable = " ".join([
                entry.get("questionnaire_title", ""),
                entry.get("date", ""),
                json.dumps(entry.get("scores", {})),
                " ".join(
                    str(r.get("value_label", "")) for r in entry.get("responses", [])
                ),
            ]).lower()
            if search_q not in searchable:
                continue
        entries.append({
            "entry_id": entry["entry_id"],
            "questionnaire_id": entry["questionnaire_id"],
            "questionnaire_title": entry["questionnaire_title"],
            "date": entry["date"],
            "completed_at": entry["completed_at"],
            "scores": entry.get("scores", {}),
            "flow_id": entry.get("flow_id"),
            "flow_session_id": entry.get("flow_session_id"),
            "micro": entry.get("micro", False),
            "generated": entry.get("generated", False),
            "gap_hours": entry.get("gap_hours"),
            "filename": fname,
        })
    return jsonify(entries)


@app.route("/api/entry/<entry_id>")
def get_entry(entry_id):
    if not SAFE_ID.match(entry_id):
        return jsonify({"error": "Invalid entry ID"}), 400
    ensure_dirs()
    for fname in os.listdir(get_entries_dir()):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(get_entries_dir(), fname)
        with open(fpath, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if entry.get("entry_id") == entry_id:
            return jsonify(entry)
    return jsonify({"error": "Entry not found"}), 404


@app.route("/api/entries/delete", methods=["POST"])
def delete_entries():
    data = request.get_json()
    ids = data.get("entry_ids", [])
    if not isinstance(ids, list):
        return jsonify({"error": "entry_ids must be a list"}), 400
    for eid in ids:
        if not isinstance(eid, str) or not SAFE_ID.match(eid):
            return jsonify({"error": f"Invalid entry ID: {eid}"}), 400

    deleted = 0
    ensure_dirs()
    for fname in list(os.listdir(get_entries_dir())):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(get_entries_dir(), fname)
        with open(fpath, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if entry.get("entry_id") in ids:
            os.unlink(fpath)
            deleted += 1
    return jsonify({"status": "ok", "deleted": deleted})


@app.route("/api/generate", methods=["POST"])
def generate_full():
    """Reconstruct full questionnaire entries from micro entries."""
    data = request.get_json()
    targets = data.get("targets", [])
    # targets: [{ questionnaire_id, days, use_full }]

    if not targets:
        return jsonify({"error": "No targets specified"}), 400

    ensure_dirs()
    all_qs = load_questionnaires()

    # Load all entries
    all_entries = []
    for fname in os.listdir(get_entries_dir()):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(get_entries_dir(), fname)
        with open(fpath, "r", encoding="utf-8") as f:
            all_entries.append(json.load(f))

    # Find micro questionnaires that reconstruct each target
    micro_map = {}  # target_qid → micro_qdef
    for q in all_qs.values():
        rec = q.get("reconstructs")
        if rec:
            micro_map[rec["questionnaire_id"]] = q

    results = []
    now = datetime.now(timezone.utc)

    for target in targets:
        tgt_qid = target["questionnaire_id"]
        days = target.get("days", 14)
        use_full = target.get("use_full", False)

        tgt_q = all_qs.get(tgt_qid)
        micro_q = micro_map.get(tgt_qid)
        if not tgt_q:
            continue

        cutoff = now.timestamp() - days * 86400

        # Collect source entries
        source_entries = []
        for e in all_entries:
            completed = e.get("completed_at", "")
            try:
                t = datetime.fromisoformat(completed.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                continue
            if t < cutoff:
                continue

            if micro_q and e.get("questionnaire_id") == micro_q["id"]:
                source_entries.append(e)
            elif use_full and e.get("questionnaire_id") == tgt_qid and not e.get("generated"):
                source_entries.append(e)

        if not source_entries:
            continue

        rec_method = micro_q.get("reconstructs", {}).get("method", "") if micro_q else ""
        tgt_scored = [q for q in tgt_q["questions"] if q.get("scored")]
        micro_scored = [q for q in micro_q["questions"] if q.get("scored")] if micro_q else []

        question_map = get_question_map(tgt_q)

        # Build response map based on method
        response_map = {}
        source_ids = [e["entry_id"] for e in source_entries]

        if rec_method in ("weighted_pct_to_likert_v1", "weighted_pct_to_5point_v1"):
            # Weighted average of slider values per question position
            bands_4 = [
                {"max_pct": 10, "score": 0},
                {"max_pct": 35, "score": 1},
                {"max_pct": 70, "score": 2},
                {"max_pct": 100, "score": 3},
            ]
            bands_5 = [
                {"max_pct": 10, "score": 0},
                {"max_pct": 25, "score": 1},
                {"max_pct": 50, "score": 2},
                {"max_pct": 75, "score": 3},
                {"max_pct": 100, "score": 4},
            ]
            bands = bands_5 if "5point" in rec_method else bands_4

            for qi, (mq_def, tgt_qdef) in enumerate(zip(micro_scored, tgt_scored)):
                weighted_sum = 0
                weight_total = 0
                for e in source_entries:
                    if e.get("questionnaire_id") != micro_q["id"]:
                        continue
                    resp = {r["question_id"]: r["value"] for r in e.get("responses", [])}
                    val = resp.get(mq_def["id"])
                    if val is None or not isinstance(val, (int, float)):
                        continue
                    gap = e.get("gap_hours", 24)
                    weighted_sum += val * gap
                    weight_total += gap
                if weight_total > 0:
                    avg = weighted_sum / weight_total
                    score = 0
                    for band in bands:
                        if avg <= band["max_pct"]:
                            score = band["score"]
                            break
                    # Find the option ID matching this score value
                    opt_id = None
                    for opt in tgt_qdef.get("options", []):
                        if opt["value"] == score:
                            opt_id = opt["id"]
                            break
                    if opt_id:
                        response_map[tgt_qdef["id"]] = opt_id

        elif rec_method == "categorical_ideation_v1":
            # C-SSRS: highest ideation level
            ideation_qs = micro_scored[:5]
            tgt_ideation = tgt_scored[:5]
            for qi in range(len(ideation_qs)):
                any_yes = False
                for e in source_entries:
                    if e.get("questionnaire_id") != micro_q["id"]:
                        continue
                    resp = {r["question_id"]: r["value"] for r in e.get("responses", [])}
                    val = resp.get(ideation_qs[qi]["id"])
                    # Check if the value is the "yes" option
                    for opt in ideation_qs[qi].get("options", []):
                        if opt["id"] == val and opt.get("value") == "yes":
                            any_yes = True
                            break
                # Map to full questionnaire
                if qi < len(tgt_ideation):
                    yes_opt = next((o["id"] for o in tgt_ideation[qi].get("options", []) if o.get("value") == "yes"), None)
                    no_opt = next((o["id"] for o in tgt_ideation[qi].get("options", []) if o.get("value") == "no"), None)
                    response_map[tgt_ideation[qi]["id"]] = yes_opt if any_yes else no_opt

        elif rec_method == "episodic_cluster_v1":
            # MDQ: check any single entry with 7+ yes
            tgt_symptom_qs = tgt_scored[:13]
            micro_symptom_qs = micro_scored[:13]
            best_count = 0
            best_entry = None
            for e in source_entries:
                if e.get("questionnaire_id") != micro_q["id"]:
                    continue
                resp = {r["question_id"]: r["value"] for r in e.get("responses", [])}
                count = 0
                for mq_def in micro_symptom_qs:
                    val = resp.get(mq_def["id"])
                    for opt in mq_def.get("options", []):
                        if opt["id"] == val and opt.get("value") == "yes":
                            count += 1
                            break
                if count > best_count:
                    best_count = count
                    best_entry = e
            # Map symptoms from best entry
            if best_entry:
                resp = {r["question_id"]: r["value"] for r in best_entry.get("responses", [])}
                for qi in range(min(len(micro_symptom_qs), len(tgt_symptom_qs))):
                    val = resp.get(micro_symptom_qs[qi]["id"])
                    is_yes = False
                    for opt in micro_symptom_qs[qi].get("options", []):
                        if opt["id"] == val and opt.get("value") == "yes":
                            is_yes = True
                            break
                    yes_opt = next((o["id"] for o in tgt_symptom_qs[qi].get("options", []) if o.get("value") == "yes"), None)
                    no_opt = next((o["id"] for o in tgt_symptom_qs[qi].get("options", []) if o.get("value") == "no"), None)
                    response_map[tgt_symptom_qs[qi]["id"]] = yes_opt if is_yes else no_opt

        # If we also want to include full entries' answers directly
        if use_full:
            for e in source_entries:
                if e.get("questionnaire_id") == tgt_qid and not e.get("generated"):
                    for r in e.get("responses", []):
                        if r["question_id"] not in response_map:
                            response_map[r["question_id"]] = r["value"]

        # Build the full entry
        visible = get_visible_questions(tgt_q, response_map)
        response_list = []
        for q in visible:
            val = response_map.get(q["id"])
            if val is not None:
                response_list.append({
                    "question_id": q["id"],
                    "question_text": q["text"],
                    "section": q.get("section", ""),
                    "value": val,
                    "value_label": find_option_label(q, val) if q.get("type") != "text" else val,
                })

        scores = calculate_scores(tgt_q, response_map)

        entry = {
            "schema_version": 1,
            "entry_id": str(uuid.uuid4()),
            "questionnaire_id": tgt_qid,
            "questionnaire_title": tgt_q["title"],
            "date": now.strftime("%Y-%m-%d"),
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "responses": response_list,
            "scores": scores,
            "generated": True,
            "generation_method": rec_method,
            "source_entries": source_ids,
            "source_timeframe": {"days": days},
        }

        filename = f"{now.strftime('%Y-%m-%d_%H%M%S')}_gen_{tgt_qid}.json"
        entry_path = os.path.join(get_entries_dir(), filename)
        safe_write(entry_path, entry)
        results.append(entry)

    return jsonify({"status": "ok", "generated": len(results), "entries": results})


@app.route("/api/export", methods=["POST"])
def export_entries():
    import csv
    import io
    import zipfile

    data = request.get_json()
    ids = set(data.get("entry_ids", []))
    formats = data.get("formats", ["md"])

    # Load matching entries
    entries = []
    ensure_dirs()
    for fname in sorted(os.listdir(get_entries_dir())):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(get_entries_dir(), fname)
        with open(fpath, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if entry.get("entry_id") in ids:
            entries.append(entry)

    if not entries:
        return jsonify({"error": "No entries found"}), 404

    files = {}

    # Markdown
    if "md" in formats:
        md_parts = []
        for e in entries:
            lines = [f"# {e.get('questionnaire_title', 'Unknown')}"]
            lines.append(f"Date: {e.get('completed_at', '')}")
            if e.get("micro"):
                lines.append(f"Type: Micro (period: {e.get('gap_hours', '?')} hours)")
            elif e.get("generated"):
                lines.append("Type: Generated")
            else:
                lines.append("Type: Full")
            s = e.get("scores", {})
            if s.get("total") is not None:
                lines.append(f"Score: {s['total']} ({s.get('severity', '')})")
            elif s.get("ideation_label"):
                lines.append(f"Result: {s['ideation_label']}")
            elif s.get("screen_result"):
                lines.append(f"Result: {s['screen_result']}")
            lines.append("")
            last_sec = ""
            for r in e.get("responses", []):
                if r.get("section") and r["section"] != last_sec:
                    last_sec = r["section"]
                    lines.append(f"## {last_sec}")
                val_label = r.get("value_label", r.get("value", ""))
                if isinstance(val_label, list):
                    val_label = ", ".join(str(v) for v in val_label)
                auto = " (auto)" if r.get("auto_implied") else ""
                lines.append(f"- **{r.get('question_text', '')}**: {val_label}{auto}")
            lines.append("")
            md_parts.append("\n".join(lines))
        files["export.md"] = "\n---\n\n".join(md_parts)

    # CSV
    if "csv" in formats:
        out = io.StringIO()
        if entries:
            # Collect all unique question texts across entries
            all_q_texts = []
            seen_q = set()
            for e in entries:
                for r in e.get("responses", []):
                    qt = r.get("question_text", "")
                    if qt not in seen_q:
                        seen_q.add(qt)
                        all_q_texts.append(qt)
            headers = ["Questionnaire", "Type", "Date", "Score", "Severity"] + all_q_texts
            writer = csv.writer(out)
            writer.writerow(headers)
            for e in entries:
                etype = "micro" if e.get("micro") else ("generated" if e.get("generated") else "full")
                s = e.get("scores", {})
                score = s.get("total", s.get("ideation_label", s.get("screen_result", "")))
                sev = s.get("severity", "")
                row = [e.get("questionnaire_title", ""), etype, e.get("completed_at", ""), str(score), sev]
                resp_map = {}
                for r in e.get("responses", []):
                    vl = r.get("value_label", r.get("value", ""))
                    if isinstance(vl, list):
                        vl = ", ".join(str(v) for v in vl)
                    resp_map[r.get("question_text", "")] = str(vl)
                for qt in all_q_texts:
                    row.append(resp_map.get(qt, ""))
                writer.writerow(row)
        files["export.csv"] = out.getvalue()

    # XLSX
    if "xlsx" in formats:
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Entries"
            all_q_texts = []
            seen_q = set()
            for e in entries:
                for r in e.get("responses", []):
                    qt = r.get("question_text", "")
                    if qt not in seen_q:
                        seen_q.add(qt)
                        all_q_texts.append(qt)
            headers = ["Questionnaire", "Type", "Date", "Score", "Severity"] + all_q_texts
            ws.append(headers)
            for e in entries:
                etype = "micro" if e.get("micro") else ("generated" if e.get("generated") else "full")
                s = e.get("scores", {})
                score = s.get("total", s.get("ideation_label", s.get("screen_result", "")))
                sev = s.get("severity", "")
                row = [e.get("questionnaire_title", ""), etype, e.get("completed_at", ""), str(score), sev]
                resp_map = {}
                for r in e.get("responses", []):
                    vl = r.get("value_label", r.get("value", ""))
                    if isinstance(vl, list):
                        vl = ", ".join(str(v) for v in vl)
                    resp_map[r.get("question_text", "")] = str(vl)
                for qt in all_q_texts:
                    row.append(resp_map.get(qt, ""))
                ws.append(row)
            xlsx_buf = io.BytesIO()
            wb.save(xlsx_buf)
            files["export.xlsx"] = xlsx_buf.getvalue()
        except ImportError:
            return jsonify({"error": "openpyxl not installed. Run: pip install openpyxl"}), 500

    # Return single file or zip
    if len(files) == 1:
        name, content = next(iter(files.items()))
        if isinstance(content, bytes):
            from flask import Response
            return Response(content, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f"attachment; filename={name}"})
        return app.response_class(content, mimetype="text/plain" if name.endswith(".md") else "text/csv",
                                  headers={"Content-Disposition": f"attachment; filename={name}"})
    else:
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                if isinstance(content, bytes):
                    zf.writestr(name, content)
                else:
                    zf.writestr(name, content.encode("utf-8"))
        zip_buf.seek(0)
        from flask import Response
        return Response(zip_buf.getvalue(), mimetype="application/zip",
                        headers={"Content-Disposition": "attachment; filename=mht_export.zip"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mental Health Tracker")
    parser.add_argument("--data-dir", "-d", help="Directory to store data files")
    parser.add_argument("--port", "-p", type=int, default=0, help="Port (default: random available)")
    parser.add_argument("--password", required=True, help="Password for accessing the app")
    parser.add_argument("--auto-shutdown", type=int, default=0, metavar="MINUTES",
                        help="Auto-shutdown after N minutes of inactivity (default: disabled)")
    args = parser.parse_args()

    if args.port and not (1 <= args.port <= 65535):
        parser.error(f"Port must be between 1 and 65535, got {args.port}")

    # Pick a random available port if not specified
    port = args.port
    if port == 0:
        import socket
        BLOCKED_PORTS = set(range(0, 1024)) | {
            1433, 1521, 1723,           # MSSQL, Oracle, PPTP
            3306, 3389, 3390,           # MySQL, RDP
            5432, 5900, 5901, 5938,     # Postgres, VNC, TeamViewer
            6379, 6443,                 # Redis, Kubernetes
            8080, 8443, 8888,           # common HTTP alternates
            9090, 9200, 9300,           # Prometheus, Elasticsearch
            27017,                      # MongoDB
        }
        for _ in range(20):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                candidate = s.getsockname()[1]
            if candidate not in BLOCKED_PORTS:
                port = candidate
                break
        else:
            port = candidate  # give up after 20 tries, use whatever we got

    # Set up auth
    app.config["PASSWORD_HASH"] = hashlib.sha256(args.password.encode()).hexdigest()
    app.config["AUTH_TOKEN"] = secrets.token_urlsafe(32)
    app.config["LAST_ACTIVITY"] = time.time()
    app.config["DATA_DIR"] = resolve_data_dir(args.data_dir)
    ensure_dirs()

    if args.auto_shutdown:
        start_inactivity_timer(args.auto_shutdown)
        print(f"Auto-shutdown: {args.auto_shutdown} minutes of inactivity")

    print(f"Data directory: {app.config['DATA_DIR']}")
    print(f"Questionnaires: {QUESTIONNAIRE_DIR}")
    print(f"Server: http://127.0.0.1:{port}")
    app.run(debug=False, port=port)
