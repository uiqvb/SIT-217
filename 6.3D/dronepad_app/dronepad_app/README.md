# DronePad – Autonomous Drone Delivery Pad Scheduling (Prototype)

A tiny, self-contained Flask prototype that demonstrates:
- Slot search respecting pad separation and capabilities
- Reservation creation
- Check-in with grace period
- Manual release
- Operator console to toggle pad out-of-service

> No login/auth in this prototype. Everything is in SQLite in the local folder.

## Quick start

### 1) Create a virtual environment and install dependencies
```bash
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# macOS/Linux/WSL
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Run the app
```bash
python app.py
```
Then open http://127.0.0.1:5000

### 3) First run initialises the database with sample pads
You’ll see sample pads in zones A & B. Try searching for today within the next hour; default turnaround = 5 minutes.

## Pages
- **/** – Search for slots
- **/search** – POST handler for search
- **/reserve** – POST to create a reservation
- **/reservation/<id>** – View/Check-in/Release a reservation
- **/admin** – Operator console to toggle pads out-of-service, view upcoming reservations

## Notes
- **Separation** is enforced per pad; the prototype blocks slots that would violate separation before or after neighboring reservations.
- **Grace period** for check-in defaults to 2 minutes after slot start.
- **Time zone**: naive local server time.
- **Data**: `dronepad.db` (SQLite). To reset, stop the server and delete the DB file.

## Tests (manual)
- Make overlapping bookings for the same pad to see separation enforcement.
- Toggle a pad Out Of Service in **/admin** and re-run a search.
- Let a reservation pass its start time without check-in and click Release.

## License
MIT (for coursework/demo purposes)
