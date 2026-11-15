import io
import json
import sqlite3
import tempfile
import unittest
from email.message import Message
from pathlib import Path

import server


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        server.DATA = Path(self.temp.name)
        server.DB_PATH = server.DATA / "test.sqlite3"
        server.INVITE_CODE = "friends-only"
        server.initialize_database()

    def tearDown(self):
        self.temp.cleanup()

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

    def register(self, username, invite=""):
        status, _, cookie = self.request("POST", "/api/auth/register", {
            "username": username, "password": "very-secure-passphrase", "invite": invite
        })
        self.assertEqual(status, 200)
        return cookie.split(";", 1)[0]

    def test_accounts_isolation_backup_and_assets(self):
        first = self.register("first")
        status, _, _ = self.request("POST", "/api/auth/register", {
            "username": "blocked", "password": "very-secure-passphrase"
        })
        self.assertEqual(status, 403)
        second = self.register("second", "friends-only")
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

    def test_personal_credentials_and_username(self):
        self.register("first")
        self.register("second", "friends-only")
        first_login, _, _ = self.request("POST", "/api/auth/login", {
            "username": "first", "password": "very-secure-passphrase"
        })
        self.assertEqual(first_login, 200)
        status, _, _ = self.request("POST", "/api/auth/login", {
            "username": "second", "password": "very-secure-passphrase"
        })
        self.assertEqual(status, 200)
        # Authenticate through the public API, then use each account's cookie.
        _, _, first_cookie = self.request("POST", "/api/auth/login", {
            "username": "first", "password": "very-secure-passphrase"
        })
        _, _, second_cookie = self.request("POST", "/api/auth/login", {
            "username": "second", "password": "very-secure-passphrase"
        })
        first_cookie = first_cookie.split(";", 1)[0]
        second_cookie = second_cookie.split(";", 1)[0]
        status, _, _ = self.request("PUT", "/api/services/credentials/trefle", {"token": "private-key"}, first_cookie)
        self.assertEqual(status, 200)
        first_status = self.request("GET", "/api/services/status", cookie=first_cookie)[1]
        self.assertEqual(first_status["trefle"], True)
        self.assertNotIn("private-key", json.dumps(first_status))
        self.assertEqual(self.request("GET", "/api/services/status", cookie=second_cookie)[1]["trefle"], False)
        status, _, _ = self.request("PUT", "/api/services/credentials/homeassistant",
                                    {"url": "http://192.168.1.10:8123", "token": "home-key"}, first_cookie)
        self.assertEqual(status, 200)
        self.assertTrue(self.request("GET", "/api/homeassistant/status", cookie=first_cookie)[1]["connected"])
        self.assertFalse(self.request("GET", "/api/homeassistant/status", cookie=second_cookie)[1]["connected"])
        self.assertEqual(self.request("DELETE", "/api/services/credentials/trefle", cookie=first_cookie)[0], 200)
        self.assertFalse(self.request("GET", "/api/services/status", cookie=first_cookie)[1]["trefle"])
        status, result, _ = self.request("PUT", "/api/account", {"username": "gardener"}, first_cookie)
        self.assertEqual((status, result["username"]), (200, "gardener"))
        self.assertEqual(self.request("GET", "/api/auth/status", cookie=first_cookie)[1]["username"], "gardener")

    def test_origin_rejection(self):
        status, _, _ = self.request("POST", "/api/auth/login", {}, headers={"Origin": "https://wrong.example"})
        self.assertEqual(status, 403)

    def test_existing_email_account_survives_upgrade(self):
        legacy = server.DATA / "legacy.sqlite3"
        with sqlite3.connect(legacy) as db:
            db.execute("CREATE TABLE users(id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,salt BLOB NOT NULL,password_hash BLOB NOT NULL,created_at INTEGER NOT NULL)")
            salt = b"legacy-test-salt"
            db.execute("INSERT INTO users VALUES(?,?,?,?,?)",
                       ("legacy-user", "old@example.test", salt, server.password_hash("very-secure-passphrase", salt), 1))
        server.DB_PATH = legacy
        server.initialize_database()
        status, _, cookie = self.request("POST", "/api/auth/login", {
            "username": "old@example.test", "password": "very-secure-passphrase"
        })
        self.assertEqual(status, 200)
        self.assertEqual(self.request("GET", "/api/auth/status", cookie=cookie.split(";", 1)[0])[1]["username"],
                         "old@example.test")


if __name__ == "__main__":
    unittest.main()
