"""SQLite lead and appointment store. One database per business deployment."""
import datetime as dt
import json
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from contextlib import contextmanager
from zoneinfo import ZoneInfo

class ValidationError(ValueError):
    pass

class ConflictError(ValueError):
    pass

def validate_text(value, label, limit=180, required=True):
    value = str(value or "").strip()
    if required and not value:
        raise ValidationError(label + " is required")
    if len(value) > limit:
        raise ValidationError(label + " is too long")
    return value

class Store:
    def __init__(self, path, timezone="UTC"):
        self.path = str(path)
        self.timezone = ZoneInfo(timezone)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=8)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=8000")
            conn.execute("PRAGMA foreign_keys=ON")
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    name TEXT NOT NULL,
                    contact TEXT NOT NULL,
                    interest TEXT NOT NULL,
                    source TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new'
                );
                CREATE TABLE IF NOT EXISTS appointments (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    name TEXT NOT NULL,
                    contact TEXT NOT NULL,
                    service TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'requested',
                    UNIQUE(date, time)
                );
                CREATE INDEX IF NOT EXISTS leads_created_idx ON leads(created_at DESC);
                CREATE INDEX IF NOT EXISTS appointments_date_idx ON appointments(date, time);
            """)

    def now(self):
        return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    def create_lead(self, data):
        name = validate_text(data.get("name"), "name", 100)
        contact = validate_text(data.get("contact"), "contact", 150)
        interest = validate_text(data.get("interest", "General inquiry"), "interest", 120)
        source = validate_text(data.get("source", "manual"), "source", 60)
        notes = validate_text(data.get("notes", ""), "notes", 1000, False)
        lid = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO leads (id,created_at,name,contact,interest,source,notes,status) VALUES (?,?,?,?,?,?,?,?)",
                (lid,self.now(),name,contact,interest,source,notes,"new"))
        return {"id":lid,"status":"new"}

    def create_appointment(self, data):
        name = validate_text(data.get("name"), "name", 100)
        contact = validate_text(data.get("contact"), "contact", 150)
        service = validate_text(data.get("service", "Consultation"), "service", 120)
        date = validate_text(data.get("date"), "date", 10)
        time = validate_text(data.get("time"), "time", 5)
        try:
            day = dt.date.fromisoformat(date)
            hour, minute = map(int, time.split(":"))
            assert time == f"{hour:02d}:{minute:02d}"
        except (ValueError, AssertionError):
            raise ValidationError("Invalid ISO date or HH:MM time")
        if day.weekday() >= 5 or hour not in range(9,17) or minute not in (0,30):
            raise ValidationError("Slots are Monday-Friday, 09:00-16:30, every 30 minutes")
        local_slot = dt.datetime.combine(day, dt.time(hour, minute), self.timezone)
        if local_slot <= dt.datetime.now(self.timezone):
            raise ValidationError("Appointment must be in the future")
        if day > dt.datetime.now(self.timezone).date() + dt.timedelta(days=180):
            raise ValidationError("Appointment cannot be more than 180 days out")
        aid = uuid.uuid4().hex
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO appointments (id,created_at,date,time,name,contact,service,status) VALUES (?,?,?,?,?,?,?,?)",
                    (aid,self.now(),date,time,name,contact,service,"requested"))
        except sqlite3.IntegrityError:
            raise ConflictError("This slot has already been requested")
        return {"id":aid,"status":"requested","date":date,"time":time}

    def list_leads(self, limit=100):
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT ?", (min(int(limit),200),)).fetchall()
        return [dict(r) for r in rows]

    def list_appointments(self, limit=100):
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM appointments ORDER BY date ASC,time ASC LIMIT ?", (min(int(limit),200),)).fetchall()
        return [dict(r) for r in rows]

    def summary(self):
        with self._connect() as conn:
            leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            appointments = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
            new = conn.execute("SELECT COUNT(*) FROM leads WHERE status='new'").fetchone()[0]
        return {"total_leads":leads,"appointment_requests":appointments,"new_leads":new,"source":"database"}
