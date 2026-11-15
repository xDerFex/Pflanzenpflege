# Pflanzenpflege Web

Eine selbst gehostete Web-App für Zimmerpflanzen: Pflanzen und Räume verwalten, Pflegeaufgaben planen, Fortschritt mit Fotos festhalten und Pflanzendienste optional verbinden. Die Oberfläche ist für Smartphone und Desktop ausgelegt.

## Schnellstart mit Docker Compose

Das öffentliche Image ist für AMD64 und ARM64 verfügbar. Eine Compose-Datei für den Image-Download liegt in [`compose.github.yaml`](compose.github.yaml).

```sh
docker compose -f compose.github.yaml up -d
```

Alternativ kann das Image aus dem Quellcode gebaut werden:

```sh
docker compose up --build -d
```

Die App ist anschließend im lokalen Netzwerk unter `http://<SERVER-IP>:8000` erreichbar. Beim ersten Aufruf wird ein Konto mit Benutzername und Passwort angelegt. Für den ersten Test im Heimnetz ist kein HTTPS erforderlich. Port 8000 sollte nicht per Router ins öffentliche Internet weitergeleitet werden.

Docker-Oberflächen mit Compose-Unterstützung können den Inhalt von `compose.github.yaml` als Projekt importieren. Ein benanntes Volume unter `/data` enthält Konten, Pflanzen, Fotos und persönliche Dienst-Zugangsdaten. Bei Updates muss das Volume erhalten bleiben.

## Weitere Konten und Einstellungen

Standardmäßig kann nur das erste Konto angelegt werden. Für weitere Konten kann ein privater `INVITE_CODE` als Umgebungsvariable gesetzt werden, zum Beispiel über eine `.env`-Datei oder die Docker-Oberfläche. Neue Benutzer geben diesen Code bei der Registrierung ein. Jedes Konto hat eigene Pflanzen, Fotos und Zugangsdaten für Pflanzendienste und Smart Home.

Trefle, Open Plantbook, Pl@ntNet und Home Assistant können nach der Anmeldung in **Einstellungen → Verbindungen** pro Konto eingerichtet werden. Die Schlüssel werden serverseitig in der Datenbank gespeichert und nicht an andere Konten ausgegeben. Verbindungen lassen sich dort auch wieder entfernen. Benutzername und Passwort können unter **Einstellungen → Konto** geändert werden. Bei selbst gehosteten Installationen sollte der Zugriff auf das Docker-Volume entsprechend geschützt und gesichert werden.

Beim Anlegen einer Pflanze führt das Formular durch Pflanzenart, Standort und Licht sowie Angaben zu Topf, Substrat, letzter Gießung und Pflanzenhöhe. Eine verbundene Trefle-Bibliothek bietet Vorschläge während der Eingabe. Das Geburtsdatum wird zunächst auf den Anlegetag gesetzt und kann später bearbeitet werden. Der erste Prüftermin ist eine Schätzung aus den angegebenen Bedingungen; Bodenfeuchte und Pflanzenzustand sollten weiterhin direkt kontrolliert werden. Bei Pflanzen in Wasser wird stattdessen ein Wasserstandscheck geplant. DLI wird aus PPFD und Beleuchtungsstunden berechnet.

Für Zugriff außerhalb des Heimnetzes empfiehlt sich HTTPS über einen Reverse Proxy oder einen privaten Zugang wie Tailscale Serve. Mit `PUBLIC_ORIGIN` kann die öffentliche HTTPS-Adresse angegeben werden. Eine installierbare Web-App mit Service Worker benötigt einen sicheren Browser-Kontext.

## Updates und Sicherungen

Bei Änderungen am Hauptzweig prüft GitHub Actions den Python-Code und veröffentlicht ein neues Image. Für ein Update das aktuelle Image laden und das Compose-Projekt mit demselben Datenvolume neu bereitstellen. **Das Volume nicht löschen.**

In der App kann jedes Konto unter **Einstellungen → Deine Daten** seine Pflanzen, Räume, Fotos und Darstellungseinstellungen als JSON-Datei exportieren und wieder einlesen. Dienst-Zugangsdaten sind aus Sicherheitsgründen nicht Teil dieser Sicherung.

## Entwicklung

Die App benötigt zur Laufzeit nur Python 3 und die Standardbibliothek. Lokal starten:

```sh
python3 server.py
```

Danach `http://127.0.0.1:8000` öffnen. Tests:

```sh
python3 -m unittest discover -s tests -v
```

Die Web-App übernimmt keine Daten automatisch aus einer früheren iOS-App. Hintergrund-Push-Benachrichtigungen sind derzeit nicht enthalten.
