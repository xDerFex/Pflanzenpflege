"""Small self-hosted API for Pflanzenpflege. No external runtime dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
DB_PATH = DATA / "pflanzenpflege.sqlite3"
PORT = int(os.environ.get("PORT", "8000"))
BIND = os.environ.get("BIND", "127.0.0.1")
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "").rstrip("/")
INVITE_CODE = os.environ.get("INVITE_CODE", "")
MAX_BODY = 12 * 1024 * 1024
SESSION_AGE = 30 * 86400
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{3,40}$")
SERVICE_FIELDS = {
    "trefle": ("token",), "plantnet": ("token",),
    "plantbook": ("clientId", "clientSecret"),
    "homeassistant": ("url", "token"),
}


@contextmanager
def database():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    DATA.mkdir(parents=True, exist_ok=True)
    with database() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
                salt BLOB NOT NULL, password_hash BLOB NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS plants (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS rooms (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS photos (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mime TEXT NOT NULL,
                content BLOB NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS preferences (
                user_id TEXT PRIMARY KEY, data TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS service_credentials (
                user_id TEXT NOT NULL, service TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(user_id, service),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
            CREATE INDEX IF NOT EXISTS plants_user ON plants(user_id);
            CREATE INDEX IF NOT EXISTS rooms_user ON rooms(user_id);
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "username" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN username TEXT")
            # Existing email accounts keep their old login until renamed in account settings.
            db.execute("UPDATE users SET username=email WHERE username IS NULL")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_username ON users(username COLLATE NOCASE)")


def password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 350_000)


def fetch_remote(url: str, *, headers=None, data=None, method=None) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read(3 * 1024 * 1024)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise ApiError(502, "Der Dienst hat die Zugangsdaten abgelehnt.") from error
        if error.code == 429:
            raise ApiError(429, "Das Tageslimit des Dienstes ist erreicht.") from error
        raise ApiError(502, "Der externe Dienst ist gerade nicht erreichbar.") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ApiError(502, "Der externe Dienst ist gerade nicht erreichbar.") from error


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class Handler(BaseHTTPRequestHandler):
    server_version = "Pflanzenpflege/1"

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method: str):
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if method != "GET":
                self.check_origin()
            if path.startswith("/api/"):
                self.api(method, path, query)
            elif method == "GET":
                self.static(path)
            else:
                raise ApiError(405, "Methode nicht erlaubt.")
        except ApiError as error:
            self.json(error.status, {"error": error.message})
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            self.json(400, {"error": "Ungültige Daten."})
        except Exception:
            self.log_error("Unhandled request error", exc_info=True)
            self.json(500, {"error": "Ein Serverfehler ist aufgetreten."})

    def check_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return
        host = self.headers.get("Host", "")
        forwarded = self.headers.get("X-Forwarded-Proto", "")
        allowed = {PUBLIC_ORIGIN} if PUBLIC_ORIGIN else {f"http://{host}", f"https://{host}"}
        if forwarded == "https":
            allowed.add(f"https://{host}")
        if origin not in allowed:
            raise ApiError(403, "Anfrage von einer anderen Website abgelehnt.")

    def body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ApiError(400, "Ungültige Anfragegröße.") from error
        if length < 0 or length > MAX_BODY:
            raise ApiError(413, "Die Datei ist zu groß.")
        return self.rfile.read(length)

    def json_body(self) -> dict:
        value = json.loads(self.body())
        if not isinstance(value, dict):
            raise ApiError(400, "Ein JSON-Objekt wird erwartet.")
        return value

    def json(self, status: int, value, *, cookie: str | None = None):
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(payload)

    def raw(self, status: int, payload: bytes, mime: str, *, cache: str = "no-store"):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        if mime.startswith("text/html"):
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def static(self, path: str):
        if path == "/":
            path = "/index.html"
        file_path = (STATIC / path.lstrip("/")).resolve()
        if not file_path.is_relative_to(STATIC) or not file_path.is_file():
            raise ApiError(404, "Nicht gefunden.")
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/javascript", "application/json"):
            mime += "; charset=utf-8"
        cache = "public, max-age=86400" if file_path.suffix in (".png", ".svg") else "no-cache"
        self.raw(200, file_path.read_bytes(), mime, cache=cache)

    def user_id(self) -> str:
        cookie = self.headers.get("Cookie", "")
        match = re.search(r"(?:^|;\s*)pflanzen_session=([a-zA-Z0-9_-]{40,100})(?:;|$)", cookie)
        if not match:
            raise ApiError(401, "Bitte anmelden.")
        token_hash = hashlib.sha256(match.group(1).encode()).hexdigest()
        with database() as db:
            row = db.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?",
                             (token_hash, int(time.time()))).fetchone()
        if not row:
            raise ApiError(401, "Bitte erneut anmelden.")
        return row["user_id"]

    def session_cookie(self, token: str, max_age: int) -> str:
        secure = PUBLIC_ORIGIN.startswith("https://") or self.headers.get("X-Forwarded-Proto") == "https"
        return f"pflanzen_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}" + ("; Secure" if secure else "")

    def api(self, method: str, path: str, query: dict):
        if path == "/api/health" and method == "GET":
            return self.json(200, {"ok": True})
        if path == "/api/auth/status" and method == "GET":
            with database() as db:
                users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            try:
                user = self.user_id()
            except ApiError:
                user = None
            with database() as db:
                account = db.execute("SELECT username FROM users WHERE id=?", (user,)).fetchone() if user else None
            return self.json(200, {"authenticated": bool(user), "firstAccount": users == 0,
                                   "registrationOpen": users == 0 or bool(INVITE_CODE),
                                   "username": account["username"] if account else None})
        if path == "/api/auth/register" and method == "POST":
            return self.register()
        if path == "/api/auth/login" and method == "POST":
            return self.login()
        if path == "/api/auth/logout" and method == "POST":
            user = self.user_id()
            cookie = self.headers.get("Cookie", "")
            match = re.search(r"pflanzen_session=([a-zA-Z0-9_-]+)", cookie)
            if match:
                with database() as db:
                    db.execute("DELETE FROM sessions WHERE token_hash=? AND user_id=?",
                               (hashlib.sha256(match.group(1).encode()).hexdigest(), user))
            return self.json(200, {"ok": True}, cookie=self.session_cookie("", 0))

        user = self.user_id()
        if path == "/api/account" and method == "PUT":
            username = str(self.json_body().get("username", "")).strip()
            if not USERNAME_PATTERN.fullmatch(username):
                raise ApiError(400, "Benutzername: drei bis vierzig Buchstaben, Zahlen, Punkte, Binde- oder Unterstriche.")
            try:
                with database() as db:
                    db.execute("UPDATE users SET username=? WHERE id=?", (username, user))
            except sqlite3.IntegrityError as error:
                raise ApiError(409, "Dieser Benutzername ist schon vergeben.") from error
            return self.json(200, {"username": username})
        if path == "/api/account/password" and method == "PUT":
            value = self.json_body()
            old_password = str(value.get("currentPassword", ""))
            new_password = str(value.get("newPassword", ""))
            if len(new_password) < 10 or len(new_password) > 200:
                raise ApiError(400, "Das neue Passwort braucht mindestens zehn Zeichen.")
            with database() as db:
                account = db.execute("SELECT salt,password_hash FROM users WHERE id=?", (user,)).fetchone()
                if not hmac.compare_digest(password_hash(old_password, account["salt"]), account["password_hash"]):
                    raise ApiError(403, "Das bisherige Passwort stimmt nicht.")
                salt = secrets.token_bytes(16)
                db.execute("UPDATE users SET salt=?,password_hash=? WHERE id=?",
                           (salt, password_hash(new_password, salt), user))
                match = re.search(r"pflanzen_session=([a-zA-Z0-9_-]+)", self.headers.get("Cookie", ""))
                if match:
                    db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?",
                               (user, hashlib.sha256(match.group(1).encode()).hexdigest()))
            return self.json(200, {"ok": True})
        if path == "/api/state" and method == "GET":
            with database() as db:
                plants = [json.loads(row[0]) for row in db.execute("SELECT data FROM plants WHERE user_id=?", (user,))]
                rooms = [json.loads(row[0]) for row in db.execute("SELECT data FROM rooms WHERE user_id=?", (user,))]
                row = db.execute("SELECT data FROM preferences WHERE user_id=?", (user,)).fetchone()
            return self.json(200, {"plants": plants, "rooms": rooms,
                                   "preferences": json.loads(row[0]) if row else {}})
        if path == "/api/preferences" and method == "PUT":
            value = self.json_body()
            allowed = {"appearance", "dailyNotifications", "reminderMinutes"}
            settings = {key: value[key] for key in allowed if key in value}
            with database() as db:
                db.execute("INSERT INTO preferences(user_id,data) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
                           (user, json.dumps(settings, ensure_ascii=False)))
            return self.json(200, settings)
        for collection in ("plants", "rooms"):
            prefix = f"/api/{collection}/"
            if path.startswith(prefix) and method in ("PUT", "DELETE"):
                item_id = path[len(prefix):]
                if not ID_PATTERN.fullmatch(item_id):
                    raise ApiError(400, "Ungültige Kennung.")
                if method == "PUT":
                    value = self.json_body()
                    if value.get("id") != item_id:
                        raise ApiError(400, "Kennung stimmt nicht überein.")
                    if collection == "plants" and not str(value.get("species", "")).strip():
                        raise ApiError(400, "Bitte eine Pflanzenart eingeben.")
                    if collection == "rooms" and not str(value.get("name", "")).strip():
                        raise ApiError(400, "Bitte einen Raumnamen eingeben.")
                    with database() as db:
                        db.execute(f"INSERT INTO {collection}(id,user_id,data) VALUES(?,?,?) "
                                   "ON CONFLICT(id) DO UPDATE SET data=excluded.data WHERE user_id=excluded.user_id",
                                   (item_id, user, json.dumps(value, ensure_ascii=False)))
                        if db.execute("SELECT changes()").fetchone()[0] == 0:
                            raise ApiError(403, "Kein Zugriff auf diesen Eintrag.")
                    return self.json(200, value)
                with database() as db:
                    db.execute(f"DELETE FROM {collection} WHERE id=? AND user_id=?", (item_id, user))
                return self.json(200, {"ok": True})
        if path == "/api/photos" and method == "POST":
            mime = self.headers.get("Content-Type", "").split(";")[0]
            if mime not in ALLOWED_IMAGE_TYPES:
                raise ApiError(415, "Bitte ein JPG-, PNG- oder WebP-Bild wählen.")
            photo = self.body()
            if not photo:
                raise ApiError(400, "Das Foto ist leer.")
            photo_id = secrets.token_urlsafe(18)
            with database() as db:
                db.execute("INSERT INTO photos(id,user_id,mime,content) VALUES(?,?,?,?)",
                           (photo_id, user, mime, photo))
            return self.json(201, {"id": photo_id, "url": f"/api/photos/{photo_id}"})
        if path.startswith("/api/photos/") and method == "GET":
            photo_id = path.removeprefix("/api/photos/")
            with database() as db:
                row = db.execute("SELECT mime,content FROM photos WHERE id=? AND user_id=?",
                                 (photo_id, user)).fetchone()
            if not row:
                raise ApiError(404, "Foto nicht gefunden.")
            return self.raw(200, row["content"], row["mime"])
        if path == "/api/export" and method == "GET":
            with database() as db:
                plants = [json.loads(row[0]) for row in db.execute("SELECT data FROM plants WHERE user_id=?", (user,))]
                rooms = [json.loads(row[0]) for row in db.execute("SELECT data FROM rooms WHERE user_id=?", (user,))]
                photos = [{"id": row[0], "mime": row[1], "base64": base64.b64encode(row[2]).decode()}
                          for row in db.execute("SELECT id,mime,content FROM photos WHERE user_id=?", (user,))]
                row = db.execute("SELECT data FROM preferences WHERE user_id=?", (user,)).fetchone()
            return self.json(200, {"version": 1, "plants": plants, "rooms": rooms, "photos": photos,
                                   "preferences": json.loads(row[0]) if row else {}})
        if path == "/api/import" and method == "POST":
            return self.import_data(user)
        if path.startswith("/api/services/"):
            return self.services(user, method, path, query)
        if path == "/api/homeassistant/status" and method == "GET":
            credentials = self.credentials(user, "homeassistant")
            return self.json(200, {"connected": bool(credentials.get("url") and credentials.get("token"))})
        if path == "/api/homeassistant/readings" and method == "GET":
            return self.home_assistant(user, query)
        raise ApiError(404, "Nicht gefunden.")

    def register(self):
        value = self.json_body()
        username = str(value.get("username", "")).strip()
        password = str(value.get("password", ""))
        if not USERNAME_PATTERN.fullmatch(username):
            raise ApiError(400, "Benutzername: drei bis vierzig Buchstaben, Zahlen, Punkte, Binde- oder Unterstriche.")
        if len(password) < 10 or len(password) > 200:
            raise ApiError(400, "Das Passwort braucht mindestens zehn Zeichen.")
        user_id = secrets.token_urlsafe(18)
        salt = secrets.token_bytes(16)
        with database() as db:
            users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if users and (not INVITE_CODE or not hmac.compare_digest(str(value.get("invite", "")), INVITE_CODE)):
                raise ApiError(403, "Für weitere Konten brauchst du den Einladungscode.")
            try:
                db.execute("INSERT INTO users(id,email,salt,password_hash,created_at,username) VALUES(?,?,?,?,?,?)",
                           (user_id, user_id + "@local.invalid", salt, password_hash(password, salt), int(time.time()), username))
            except sqlite3.IntegrityError as error:
                raise ApiError(409, "Dieser Benutzername ist schon vergeben.") from error
        return self.start_session(user_id)

    def login(self):
        value = self.json_body()
        username = str(value.get("username", "")).strip()
        password = str(value.get("password", ""))
        with database() as db:
            row = db.execute("SELECT id,salt,password_hash FROM users WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE",
                             (username, username)).fetchone()
        if not row or not hmac.compare_digest(password_hash(password, row["salt"]), row["password_hash"]):
            raise ApiError(401, "Benutzername oder Passwort stimmt nicht.")
        return self.start_session(row["id"])

    def start_session(self, user_id: str):
        token = secrets.token_urlsafe(36)
        with database() as db:
            db.execute("DELETE FROM sessions WHERE expires_at<?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES(?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), user_id, int(time.time()) + SESSION_AGE))
        return self.json(200, {"ok": True}, cookie=self.session_cookie(token, SESSION_AGE))

    def import_data(self, user: str):
        data = self.json_body()
        plants, rooms, photos = data.get("plants"), data.get("rooms"), data.get("photos")
        if not isinstance(plants, list) or not isinstance(rooms, list) or not isinstance(photos, list):
            raise ApiError(400, "Ungültige Sicherungsdatei.")
        if len(plants) > 5000 or len(rooms) > 1000 or len(photos) > 5000:
            raise ApiError(413, "Zu viele Einträge.")
        with database() as db:
            for collection, values in (("rooms", rooms), ("plants", plants)):
                for item in values:
                    if not isinstance(item, dict) or not ID_PATTERN.fullmatch(str(item.get("id", ""))):
                        raise ApiError(400, "Ungültiger Eintrag in der Sicherung.")
                    owner = db.execute(f"SELECT user_id FROM {collection} WHERE id=?", (item["id"],)).fetchone()
                    if owner and owner["user_id"] != user:
                        raise ApiError(409, "Ein Eintrag aus der Sicherung gehört zu einem anderen Konto.")
                    db.execute(f"INSERT INTO {collection}(id,user_id,data) VALUES(?,?,?) "
                               "ON CONFLICT(id) DO UPDATE SET data=excluded.data WHERE user_id=excluded.user_id",
                               (item["id"], user, json.dumps(item, ensure_ascii=False)))
            for item in photos:
                if not isinstance(item, dict) or not ID_PATTERN.fullmatch(str(item.get("id", ""))) or item.get("mime") not in ALLOWED_IMAGE_TYPES:
                    raise ApiError(400, "Ungültiges Foto in der Sicherung.")
                try:
                    content = base64.b64decode(item["base64"], validate=True)
                except (KeyError, ValueError) as error:
                    raise ApiError(400, "Ungültiges Foto in der Sicherung.") from error
                if len(content) > 8 * 1024 * 1024:
                    raise ApiError(413, "Ein Foto ist zu groß.")
                owner = db.execute("SELECT user_id FROM photos WHERE id=?", (item["id"],)).fetchone()
                if owner and owner["user_id"] != user:
                    raise ApiError(409, "Ein Foto aus der Sicherung gehört zu einem anderen Konto.")
                db.execute("INSERT INTO photos(id,user_id,mime,content) VALUES(?,?,?,?) "
                           "ON CONFLICT(id) DO UPDATE SET content=excluded.content WHERE user_id=excluded.user_id",
                           (item["id"], user, item["mime"], content))
            preferences = data.get("preferences", {})
            if not isinstance(preferences, dict):
                raise ApiError(400, "Ungültige Einstellungen in der Sicherung.")
            settings = {key: preferences[key] for key in ("appearance", "dailyNotifications", "reminderMinutes")
                        if key in preferences}
            db.execute("INSERT INTO preferences(user_id,data) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
                       (user, json.dumps(settings, ensure_ascii=False)))
        return self.json(200, {"ok": True})

    def credentials(self, user: str, service: str) -> dict:
        with database() as db:
            row = db.execute("SELECT data FROM service_credentials WHERE user_id=? AND service=?",
                             (user, service)).fetchone()
        return json.loads(row["data"]) if row else {}

    def services(self, user: str, method: str, path: str, query: dict):
        prefix = "/api/services/credentials/"
        if path.startswith(prefix) and method in ("PUT", "DELETE"):
            service = path[len(prefix):]
            fields = SERVICE_FIELDS.get(service)
            if not fields:
                raise ApiError(404, "Unbekannter Dienst.")
            if method == "DELETE":
                with database() as db:
                    db.execute("DELETE FROM service_credentials WHERE user_id=? AND service=?", (user, service))
                return self.json(200, {"ok": True})
            supplied = self.json_body()
            previous = self.credentials(user, service)
            values = {key: str(supplied.get(key, "")).strip() or previous.get(key, "") for key in fields}
            if any(not value or len(value) > 2048 for value in values.values()):
                raise ApiError(400, "Bitte alle benötigten Zugangsdaten eingeben.")
            if service == "homeassistant":
                parsed = urllib.parse.urlsplit(values["url"])
                if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                    raise ApiError(400, "Bitte eine gültige Home-Assistant-Adresse eingeben.")
                values["url"] = values["url"].rstrip("/")
            with database() as db:
                db.execute("INSERT INTO service_credentials(user_id,service,data) VALUES(?,?,?) "
                           "ON CONFLICT(user_id,service) DO UPDATE SET data=excluded.data",
                           (user, service, json.dumps(values)))
            return self.json(200, {"ok": True})
        trefle = self.credentials(user, "trefle").get("token", "")
        plantnet = self.credentials(user, "plantnet").get("token", "")
        plantbook = self.credentials(user, "plantbook")
        plantbook_id, plantbook_secret = plantbook.get("clientId", ""), plantbook.get("clientSecret", "")
        if path == "/api/services/status" and method == "GET":
            return self.json(200, {"trefle": bool(trefle), "plantnet": bool(plantnet),
                                   "plantbook": bool(plantbook_id and plantbook_secret)})
        if path == "/api/services/search" and method == "GET":
            if not trefle:
                raise ApiError(503, "Trefle ist noch nicht verbunden.")
            text = query.get("q", [""])[0].strip()
            if len(text) < 2 or len(text) > 100:
                raise ApiError(400, "Bitte mindestens zwei Zeichen eingeben.")
            url = "https://trefle.io/api/v1/plants/search?" + urllib.parse.urlencode({"q": text, "token": trefle})
            response = json.loads(fetch_remote(url))
            items = response.get("data", [])[:15]
            return self.json(200, [{"id": item.get("id"), "title": item.get("common_name") or item.get("scientific_name"),
                                    "scientificName": item.get("scientific_name"), "imageURL": item.get("image_url")}
                                   for item in items if item.get("scientific_name")])
        if path == "/api/services/advice" and method == "GET":
            if not plantbook_id or not plantbook_secret:
                raise ApiError(503, "Open Plantbook ist noch nicht verbunden.")
            name = query.get("name", [""])[0].strip()
            if not name or len(name) > 120:
                raise ApiError(400, "Bitte einen wissenschaftlichen Namen angeben.")
            fields = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": plantbook_id,
                                             "client_secret": plantbook_secret}).encode()
            token_response = json.loads(fetch_remote("https://open.plantbook.io/api/v1/token/",
                                                     headers={"Content-Type": "application/x-www-form-urlencoded"}, data=fields))
            token = token_response.get("access_token")
            if not token:
                raise ApiError(502, "Open Plantbook konnte nicht angemeldet werden.")
            headers = {"Authorization": "Bearer " + token}
            search = json.loads(fetch_remote("https://open.plantbook.io/api/v1/plant/search?" +
                                             urllib.parse.urlencode({"alias": name}), headers=headers))
            exact = [item for item in search.get("results", []) if
                     (item.get("display_pid") or item.get("pid", "")).casefold() == name.casefold()]
            if len(exact) != 1:
                return self.json(200, None)
            plant_id = urllib.parse.quote(exact[0]["pid"], safe="")
            detail = json.loads(fetch_remote(f"https://open.plantbook.io/api/v1/plant/detail/{plant_id}/?include=care&lang=de",
                                             headers=headers))
            care = detail.get("care") or {}
            field = lambda key: care.get(key) or detail.get(key)
            return self.json(200, {"scientificName": name, "minLux": detail.get("min_light_lux"),
                                   "maxLux": detail.get("max_light_lux"), "minDLI": detail.get("min_light_mmol"),
                                   "maxDLI": detail.get("max_light_mmol"), "sunlight": field("sunlight"),
                                   "watering": field("watering"), "fertilization": field("fertilization"),
                                   "soil": field("soil")})
        if path == "/api/services/identify" and method == "POST":
            if not plantnet:
                raise ApiError(503, "Pl@ntNet ist noch nicht verbunden.")
            image = self.body()
            if not image or len(image) > 8 * 1024 * 1024:
                raise ApiError(400, "Bitte ein Foto bis acht Megabyte wählen.")
            image_type = self.headers.get("Content-Type", "").split(";")[0]
            if image_type not in ALLOWED_IMAGE_TYPES:
                raise ApiError(415, "Für die Erkennung bitte JPG, PNG oder WebP verwenden.")
            extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[image_type]
            boundary = "PlantPhoto" + secrets.token_hex(10)
            payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"images\"; filename=\"plant.{extension}\"\r\n"
                       f"Content-Type: {image_type}\r\n\r\n").encode() + image + f"\r\n--{boundary}--\r\n".encode()
            url = "https://my-api.plantnet.org/v2/identify/all?" + urllib.parse.urlencode({"api-key": plantnet, "lang": "de"})
            response = json.loads(fetch_remote(url, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                               data=payload))
            return self.json(200, [{"scientificName": item["species"]["scientificNameWithoutAuthor"],
                                    "commonName": (item["species"].get("commonNames") or [None])[0],
                                    "score": item.get("score", 0)} for item in response.get("results", [])[:5]])
        raise ApiError(404, "Nicht gefunden.")

    def home_assistant(self, user: str, query: dict):
        credentials = self.credentials(user, "homeassistant")
        base = credentials.get("url", "").rstrip("/")
        token = credentials.get("token", "")
        if not base or not token:
            raise ApiError(503, "Home Assistant ist noch nicht verbunden.")
        if not base.startswith(("https://", "http://")):
            raise ApiError(500, "Home-Assistant-Adresse ist ungültig.")
        entities = query.get("entity", [])[:30]
        if not entities or any(not re.fullmatch(r"sensor\.[a-z0-9_]+", item) for item in entities):
            raise ApiError(400, "Ungültige Sensor-ID.")
        result = {}
        for entity in entities:
            url = base + "/api/states/" + urllib.parse.quote(entity)
            state = json.loads(fetch_remote(url, headers={"Authorization": "Bearer " + token}))
            try:
                result[entity] = {"value": float(state["state"]), "updated": state.get("last_updated")}
            except (TypeError, ValueError, KeyError):
                result[entity] = {"value": None, "updated": state.get("last_updated")}
        return self.json(200, result)


def run():
    initialize_database()
    httpd = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"Pflanzenpflege Web läuft auf http://{BIND}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    run()
