import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path

import server


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.DATA = Path(cls.temp.name)
        server.DB_PATH = server.DATA / "test.sqlite3"
        server.INVITE_CODE = "friends-only"
        server.initialize_database()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def request(self, method, path, data=None, cookie=None, headers=None):
        request_headers = {"Content-Type": "application/json", "Host": "127.0.0.1:8000", **(headers or {})}
        if cookie:
            request_headers["Cookie"] = cookie
        body = json.dumps(data).encode() if data is not None else None
        request_headers["Content-Length"] = str(len(body or b""))
        handler = server.Handler.__new__(server.Handler)
        handler.path = path
        handler.command = method
        handler.rfile = io.BytesIO(body or b"")
        handler.wfile = io.BytesIO()
        handler.headers = Message()
        for key, value in request_headers.items():
            handler.headers[key] = value
        sent = {}
        handler.send_response = lambda code: sent.update(status=code)
        handler.send_header = lambda key, value: sent.update({key.lower(): value})
        handler.end_headers = lambda: None
        handler.log_error = lambda *args, **kwargs: None
        handler.route(method)
        raw = handler.wfile.getvalue()
        result = json.loads(raw) if sent.get("content-type", "").startswith("application/json") else raw
        cookie_header = sent.get("set-cookie")
        status = sent["status"]
        return status, result, cookie_header

    def register(self, email, invite=""):
        status, _, cookie = self.request("POST", "/api/auth/register", {
            "email": email, "password": "very-secure-passphrase", "invite": invite
        })
        self.assertEqual(status, 200)
        return cookie.split(";", 1)[0]

    def test_accounts_isolation_backup_and_assets(self):
        first = self.register("first@example.test")
        status, _, _ = self.request("POST", "/api/auth/register", {
            "email": "blocked@example.test", "password": "very-secure-passphrase"
        })
        self.assertEqual(status, 403)
        second = self.register("second@example.test", "friends-only")
        plant = {"id": "plant_alpha_123", "species": "Monstera", "events": []}
        status, _, _ = self.request("PUT", "/api/plants/plant_alpha_123", plant, first)
        self.assertEqual(status, 200)
        status, data, _ = self.request("GET", "/api/state", cookie=second)
        self.assertEqual(status, 200)
        self.assertEqual(data["plants"], [])
        status, _, _ = self.request("PUT", "/api/plants/plant_alpha_123", plant, second)
        self.assertEqual(status, 403)
        status, backup, _ = self.request("GET", "/api/export", cookie=first)
        self.assertEqual(status, 200)
        self.assertEqual(backup["plants"][0]["species"], "Monstera")
        status, _, _ = self.request("POST", "/api/import", backup, second)
        self.assertEqual(status, 409)
        status, data, _ = self.request("GET", "/api/state", cookie=second)
        self.assertEqual(data["plants"], [])
        status, _, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        status, _, _ = self.request("GET", "/api/health")
        self.assertEqual(status, 200)

    def test_origin_rejection(self):
        status, _, _ = self.request("POST", "/api/auth/login", {}, headers={"Origin": "https://wrong.example"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
