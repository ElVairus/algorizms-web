#!/usr/bin/env python3
"""
Algorizms Lead Capture Webhook Service
Receives form submissions from https://algorizms.com and syncs them to Notion Leads Tracker database.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error
import datetime
import os

NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_DATABASE_ID = "aa820527-f6d3-4fcc-9662-26aac39fb169"
PORT = 8080

class LeadWebhookHandler(BaseHTTPRequestHandler):
    def _send_response(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_OPTIONS(self):
        self._send_response(200, {"status": "ok"})

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

        name = payload.get("name", "Website Lead")
        email = payload.get("email", "")
        focus_area = payload.get("focus_area", "Complete Ecosystem (PLAN → BUILD → FLOW → GROW)")
        company = payload.get("company", "")
        notes = payload.get("notes", f"Form submission on {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")

        # Map focus area to Notion Department
        department_map = {
            "Tech Solutions (Web App / AI Systems / SaaS MVP)": "Tech Solutions",
            "Growth Marketing (GTM / Funnels / Paid Acquisition)": "Growth",
            "Data Analytics (BI Dashboards / Attribution / Telemetry)": "Data",
            "Complete Ecosystem (PLAN → BUILD → FLOW → GROW)": "Growth"
        }
        department = department_map.get(focus_area, "Growth")

        # Build Notion Page payload
        notion_payload = {
            "parent": {"database_id": NOTION_DATABASE_ID},
            "properties": {
                "Lead Name": {
                    "title": [{"text": {"content": name}}]
                },
                "Email": {
                    "email": email
                },
                "Department": {
                    "select": {"name": department}
                },
                "Lead Source": {
                    "select": {"name": "Inbound"}
                },
                "Stage": {
                    "status": {"name": "New"}
                },
                "Priority": {
                    "select": {"name": "High"}
                },
                "Notes": {
                    "rich_text": [{"text": {"content": f"Focus Area: {focus_area}\n{notes}"}}]
                }
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

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_data = json.loads(resp.read().decode('utf-8'))
                print(f"[{datetime.datetime.utcnow().isoformat()}] Notion Lead Created: {resp_data.get('id')}")
                self._send_response(200, {
                    "success": True,
                    "message": "Lead received and saved to Notion CRM.",
                    "notion_page_id": resp_data.get("id")
                })
        except urllib.error.HTTPError as e:
            err = e.read().decode('utf-8')
            print(f"Notion API Error: {err}")
            self._send_response(500, {"error": "Failed to save to Notion", "details": err})
        except Exception as e:
            print(f"Server Error: {str(e)}")
            self._send_response(500, {"error": str(e)})

def run_server():
    server_address = ('127.0.0.1', PORT)
    httpd = HTTPServer(server_address, LeadWebhookHandler)
    print(f"Algorizms Lead API Service running on port {PORT}...")
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()
