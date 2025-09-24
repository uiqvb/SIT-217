
import os
import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4

from flask import Flask, render_template, request, redirect, url_for, flash

APP_TITLE = "DronePad – Prototype"
DB_PATH = os.path.join(os.path.dirname(__file__), "dronepad.db")

app = Flask(__name__)
app.secret_key = "dev-secret"  # for flash messages


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    first_time = not os.path.exists(DB_PATH)
    conn = get_db()
    c = conn.cursor()
    c.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS pads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            zone TEXT NOT NULL,
            payload_classes TEXT NOT NULL, -- CSV of allowed classes e.g. 'S,M'
            turnaround_minutes INTEGER NOT NULL DEFAULT 5,
            separation_seconds INTEGER NOT NULL DEFAULT 90,
            out_of_service INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS reservations (
            id TEXT PRIMARY KEY,
            pad_id INTEGER NOT NULL,
            payload_class TEXT NOT NULL,
            start_ts TEXT NOT NULL,  -- ISO
            end_ts TEXT NOT NULL,    -- ISO
            status TEXT NOT NULL,    -- CONFIRMED, CHECKED_IN, RELEASED, CANCELLED
            created_at TEXT NOT NULL,
            checkin_ts TEXT,
            FOREIGN KEY (pad_id) REFERENCES pads(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_res_pad_time ON reservations(pad_id, start_ts, end_ts);
        """
    )
    conn.commit()

    if first_time:
        seed_pads = [
            ("Roof A-1", "A", "S,M", 5, 90, 0),
            ("Roof A-2", "A", "S", 5, 60, 0),
            ("Courtyard B-1", "B", "M,L", 10, 120, 0),
            ("Courtyard B-2", "B", "S,M,L", 5, 90, 0),
        ]
        c.executemany(
            "INSERT INTO pads(name,zone,payload_classes,turnaround_minutes,separation_seconds,out_of_service) VALUES (?,?,?,?,?,?)",
            seed_pads,
        )
        conn.commit()

    conn.close()


def parse_dt(s):
    # Expect 'YYYY-MM-DD HH:MM'
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def overlaps_with_separation(c_start, c_end, r_start, r_end, sep_sec):
    # block if [c_start, c_end] overlaps [r_start - sep, r_end + sep]
    window_start = r_start - timedelta(seconds=sep_sec)
    window_end = r_end + timedelta(seconds=sep_sec)
    return not (c_end <= window_start or c_start >= window_end)


def pad_supports_payload(pad_row, payload_class):
    allowed = [p.strip() for p in pad_row["payload_classes"].split(",")]
    return payload_class in allowed


def existing_reservations(conn, pad_id, window_start, window_end):
    c = conn.cursor()
    # fetch reservations within a broad window
    c.execute(
        """
        SELECT * FROM reservations
        WHERE pad_id = ?
          AND status IN ('CONFIRMED','CHECKED_IN')
          AND NOT (end_ts <= ? OR start_ts >= ?)
        """,
        (pad_id, fmt_dt(window_start), fmt_dt(window_end)),
    )
    return [dict(r) for r in c.fetchall()]


def find_slots(zone, window_start, window_end, turnaround_minutes, payload_class, step_minutes=5, limit_per_pad=10):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM pads WHERE zone = ? AND out_of_service = 0 ORDER BY id",
        (zone,),
    )
    pads = [dict(r) for r in c.fetchall()]

    results = []
    for pad in pads:
        if not pad_supports_payload(pad, payload_class):
            continue
        sep = int(pad["separation_seconds"])
        turn = int(turnaround_minutes) if turnaround_minutes else int(pad["turnaround_minutes"])
        slots = []
        reservations = existing_reservations(conn, pad["id"], window_start - timedelta(minutes=60), window_end + timedelta(minutes=60))
        # candidate starts on a grid
        t = window_start
        while t + timedelta(minutes=turn) <= window_end and len(slots) < limit_per_pad:
            candidate_start = t
            candidate_end = t + timedelta(minutes=turn)
            conflict = False
            for r in reservations:
                r_start = parse_dt(r["start_ts"])
                r_end = parse_dt(r["end_ts"])
                if overlaps_with_separation(candidate_start, candidate_end, r_start, r_end, sep):
                    conflict = True
                    break
            if not conflict:
                slots.append({"pad": pad, "start": candidate_start, "end": candidate_end})
            t += timedelta(minutes=step_minutes)
        if slots:
            results.append({"pad": pad, "slots": slots})

    conn.close()
    return results


@app.route("/", methods=["GET"])
def home():
    now = datetime.now().replace(second=0, microsecond=0)
    default_start = (now + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M")
    default_end = (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    return render_template("index.html", title=APP_TITLE, default_start=default_start, default_end=default_end)


@app.route("/search", methods=["POST"])
def search():
    zone = request.form.get("zone", "A")
    payload_class = request.form.get("payload_class", "S")
    turnaround = int(request.form.get("turnaround", "5"))
    start_str = request.form.get("start")
    end_str = request.form.get("end")
    try:
        start_dt = parse_dt(start_str)
        end_dt = parse_dt(end_str)
    except Exception:
        flash("Invalid date/time format. Use YYYY-MM-DD HH:MM")
        return redirect(url_for("home"))

    if end_dt <= start_dt:
        flash("End time must be after start time.")
        return redirect(url_for("home"))

    results = find_slots(zone, start_dt, end_dt, turnaround, payload_class)
    return render_template("results.html", title=APP_TITLE, zone=zone, payload_class=payload_class,
                           turnaround=turnaround, start=start_str, end=end_str, results=results)


@app.route("/reserve", methods=["POST"])
def reserve():
    pad_id = int(request.form["pad_id"])
    start_str = request.form["start"]
    end_str = request.form["end"]
    payload_class = request.form["payload_class"]
    start_dt = parse_dt(start_str)
    end_dt = parse_dt(end_str)

    conn = get_db()
    c = conn.cursor()
    pad = c.execute("SELECT * FROM pads WHERE id = ?", (pad_id,)).fetchone()
    if not pad:
        flash("Pad not found.")
        return redirect(url_for("home"))
    if pad["out_of_service"] == 1:
        flash("Pad is out of service.")
        return redirect(url_for("home"))
    if not pad_supports_payload(pad, payload_class):
        flash("Pad does not support the selected payload class.")
        return redirect(url_for("home"))

    # Re-check separation before committing
    sep = int(pad["separation_seconds"])
    reservations = existing_reservations(conn, pad_id, start_dt - timedelta(minutes=60), end_dt + timedelta(minutes=60))
    for r in reservations:
        r_start = parse_dt(r["start_ts"])
        r_end = parse_dt(r["end_ts"])
        if overlaps_with_separation(start_dt, end_dt, r_start, r_end, sep):
            flash("Slot no longer available due to separation rules. Please search again.")
            conn.close()
            return redirect(url_for("home"))

    res_id = str(uuid4())
    c.execute(
        "INSERT INTO reservations(id, pad_id, payload_class, start_ts, end_ts, status, created_at) VALUES (?,?,?,?,?,?,?)",
        (res_id, pad_id, payload_class, start_str, end_str, "CONFIRMED", fmt_dt(datetime.now())),
    )
    conn.commit()
    conn.close()
    flash("Reservation confirmed.")
    return redirect(url_for("reservation", res_id=res_id))


@app.route("/reservation/<res_id>", methods=["GET"])
def reservation(res_id):
    conn = get_db()
    c = conn.cursor()
    r = c.execute("""
        SELECT r.*, p.name AS pad_name, p.zone AS pad_zone FROM reservations r
        JOIN pads p ON p.id = r.pad_id
        WHERE r.id = ?
    """, (res_id,)).fetchone()
    conn.close()
    if not r:
        flash("Reservation not found.")
        return redirect(url_for("home"))
    return render_template("reservation.html", title=APP_TITLE, r=r)


@app.route("/reservation/<res_id>/checkin", methods=["POST"])
def do_checkin(res_id):
    conn = get_db()
    c = conn.cursor()
    r = c.execute("SELECT * FROM reservations WHERE id = ?", (res_id,)).fetchone()
    if not r:
        conn.close()
        flash("Reservation not found.")
        return redirect(url_for("home"))
    # Simple window: allow check-in from start time - 2 minutes to end time
    now = datetime.now()
    start_dt = parse_dt(r["start_ts"])
    end_dt = parse_dt(r["end_ts"])
    if now < start_dt - timedelta(minutes=2) or now > end_dt:
        flash("Check-in not allowed at this time.")
    else:
        c.execute("UPDATE reservations SET status='CHECKED_IN', checkin_ts=? WHERE id=?", (fmt_dt(now), res_id))
        conn.commit()
        flash("Checked in.")
    conn.close()
    return redirect(url_for("reservation", res_id=res_id))


@app.route("/reservation/<res_id>/release", methods=["POST"])
def release(res_id):
    conn = get_db()
    c = conn.cursor()
    r = c.execute("SELECT * FROM reservations WHERE id = ?", (res_id,)).fetchone()
    if not r:
        conn.close()
        flash("Reservation not found.")
        return redirect(url_for("home"))
    status = r["status"]
    start_dt = parse_dt(r["start_ts"])
    # auto-release allowed if not checked-in within grace (2 min)
    if status in ("CONFIRMED",) and datetime.now() >= start_dt + timedelta(minutes=10):
        c.execute("UPDATE reservations SET status='RELEASED' WHERE id=?", (res_id,))
        conn.commit()
        flash("Reservation released (no check-in).")
    else:
        # Manual release allowed anytime
        c.execute("UPDATE reservations SET status='RELEASED' WHERE id=?", (res_id,))
        conn.commit()
        flash("Reservation released.")
    conn.close()
    return redirect(url_for("home"))


@app.route("/admin", methods=["GET", "POST"])
def admin():
    conn = get_db()
    c = conn.cursor()
    if request.method == "POST":
        pad_id = int(request.form["pad_id"])
        action = request.form.get("action")
        if action == "toggle_oos":
            p = c.execute("SELECT out_of_service FROM pads WHERE id=?", (pad_id,)).fetchone()
            if p:
                new_val = 0 if p["out_of_service"] == 1 else 1
                c.execute("UPDATE pads SET out_of_service=? WHERE id=?", (new_val, pad_id))
                conn.commit()
                flash(f"Pad {pad_id} out_of_service set to {new_val}.")
    pads = [dict(r) for r in c.execute("SELECT * FROM pads ORDER BY zone, id").fetchall()]
    upcoming = [dict(r) for r in c.execute(
        "SELECT r.id, r.start_ts, r.end_ts, r.status, p.name AS pad_name, p.zone FROM reservations r JOIN pads p ON p.id=r.pad_id WHERE r.start_ts >= ? ORDER BY r.start_ts LIMIT 50",
        (fmt_dt(datetime.now() - timedelta(hours=1)),)
    ).fetchall()]
    conn.close()
    return render_template("admin.html", title=APP_TITLE, pads=pads, upcoming=upcoming)


if __name__ == "__main__":
    init_db()
    # Turn off the debug reloader so the server doesn’t keep restarting
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False, threaded=True)
