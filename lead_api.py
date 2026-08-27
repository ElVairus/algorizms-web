#!/usr/bin/env python3
"""
Algorizms Bulletproof Lead Capture & CRM Sync Engine
Features:
1. Dual-Layer Storage: Instantly saves every lead to local SQLite DB (Zero data loss).
2. Notion Sync Pipeline: Automatically synchronizes pending leads to Notion Leads Tracker database.
3. Automatic Retries: Retries unsynced leads in background without blocking web visitors.
4. Clean JSON API endpoint on /api/lead.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error
import datetime
import sqlite3
import os
import threading
import time

DB_DIR = "/var/www/algorizms/data"
DB_PATH = os.path.join(DB_DIR, "leads.db")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_DATABASE_ID = "aa820527-f6d3-4fcc-9662-26aac39fb169"
PORT = 8080

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            company TEXT,
            focus_area TEXT,
            notes TEXT,
            notion_status TEXT DEFAULT 'PENDING',
            notion_page_id TEXT,
            created_at TEXT NOT NULL,
            synced_at TEXT,
            error_details TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_lead_local(name, email, company, focus_area, notes):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO leads (name, email, company, focus_area, notes, notion_status, created_at)
        VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
    """, (name, email, company, focus_area, notes, now_iso))
    lead_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return lead_id

def sync_lead_to_notion(lead_id, name, email, company, focus_area, notes):
    if not NOTION_API_KEY:
        return {"success": False, "error": "NOTION_API_KEY missing"}

    department_map = {
        "Tech Solutions (Web App / AI Systems / SaaS MVP)": "Tech Solutions",
        "Growth Marketing (GTM / Funnels / Paid Acquisition)": "Growth",
        "Data Analytics (BI Dashboards / Attribution / Telemetry)": "Data",
        "Complete Ecosystem (PLAN → BUILD → FLOW → GROW)": "Growth"
    }
    department = department_map.get(focus_area, "Growth")

    notion_payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Lead Name": {"title": [{"text": {"content": name}}]},
            "Email": {"email": email},
            "Department": {"select": {"name": department}},
            "Lead Source": {"select": {"name": "Inbound"}},
            "Stage": {"status": {"name": "New"}},
            "Priority": {"select": {"name": "High"}},
            "Notes": {"rich_text": [{"text": {"content": f"Focus: {focus_area}\nCompany: {company}\n{notes}"}}]}
        }
    }

    if company:
        notion_payload["properties"]["Company"] = {
            "rich_text": [{"text": {"content": company}}]
        }

    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(notion_payload).encode('utf-8'),
        headers=headers,
        method='POST'
    )

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            resp_data = json.loads(resp.read().decode('utf-8'))
            page_id = resp_data.get("id")
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cursor.execute("""
                UPDATE leads 
                SET notion_status = 'SYNCED', notion_page_id = ?, synced_at = ?, error_details = NULL
                WHERE id = ?
            """, (page_id, now_iso, lead_id))
            conn.commit()
            conn.close()
            print(f"[SYNC SUCCESS] Lead #{lead_id} synced to Notion Page {page_id}")
            return {"success": True, "notion_page_id": page_id}
    except Exception as e:
        err_str = str(e)
        cursor.execute("UPDATE leads SET error_details = ? WHERE id = ?", (err_str, lead_id))
        conn.commit()
        conn.close()
        print(f"[SYNC PENDING] Lead #{lead_id} saved locally. Notion sync error: {err_str}")
        return {"success": False, "error": err_str}

def background_sync_worker():
    """Continuously retries syncing pending leads every 60 seconds"""
    while True:
        try:
            init_db()
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, email, company, focus_area, notes FROM leads WHERE notion_status = 'PENDING'")
            pending = cursor.fetchall()
            conn.close()

            for row in pending:
                lid, name, email, comp, focus, notes = row
                sync_lead_to_notion(lid, name, email, comp, focus, notes)

        except Exception as e:
            print(f"[WORKER ERROR] {e}")
        time.sleep(60)

class LeadWebhookHandler(BaseHTTPRequestHandler):
    def _send_response(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_OPTIONS(self):
        self._send_response(200, {"status": "ok"})

    def do_GET(self):
        if self.path == "/api/lead" or self.path == "/api/lead/list":
            init_db()
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, email, company, focus_area, notion_status, created_at FROM leads ORDER BY id DESC LIMIT 50")
            leads = [
                {"id": r[0], "name": r[1], "email": r[2], "company": r[3], "focus_area": r[4], "notion_status": r[5], "created_at": r[6]}
                for r in cursor.fetchall()
            ]
            conn.close()
            self._send_response(200, {"total_leads": len(leads), "leads": leads})
        else:
            self._send_response(404, {"error": "Endpoint not found"})

    def do_POST(self):
        if self.path != "/api/lead":
            self._send_response(404, {"error": "Endpoint not found"})
            return

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send_response(400, {"error": "Invalid JSON"})
            return

        name = payload.get("name", "").strip() or "Website Lead"
        email = payload.get("email", "").strip()
        company = payload.get("company", "").strip()
        focus_area = payload.get("focus_area", "Complete Ecosystem (PLAN → BUILD → FLOW → GROW)")
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        notes = payload.get("notes", f"Consultation requested on {now_str}")

        if not email:
            self._send_response(400, {"error": "Email is required"})
            return

        # 1. Guaranteed Local Save
        lead_id = save_lead_local(name, email, company, focus_area, notes)

        # 2. Async Notion Sync (Does not block visitor response)
        threading.Thread(target=sync_lead_to_notion, args=(lead_id, name, email, company, focus_area, notes), daemon=True).start()

        # 3. Instant 200 OK Response to Web Visitor
        self._send_response(200, {
            "success": True,
            "lead_id": lead_id,
            "message": "Strategy consultation request logged successfully."
        })

def run_server():
    init_db()
    # Start background auto-retry daemon
    worker_thread = threading.Thread(target=background_sync_worker, daemon=True)
    worker_thread.start()

    server_address = ('127.0.0.1', PORT)
    httpd = HTTPServer(server_address, LeadWebhookHandler)
    print(f"[ALGORIZMS ENGINE] Lead Capture & CRM Service running on port {PORT}...")
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()
