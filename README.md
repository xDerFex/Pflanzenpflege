# Pflanzenpflege Web

Die Web-App läuft auf deinem eigenen Docker-Server. Docker baut das Image beim ersten Start automatisch aus dem mitgelieferten `Dockerfile`. Du brauchst dafür kein veröffentlichtes Image, keinen Apple-Entwickleraccount und für den ersten Test im Heimnetz kein HTTPS.

## Einfacher Start mit Docker

1. Kopiere `Pflanzenpflege-Web.tar.gz` auf deinen Docker-Server und entpacke es dort. Falls du den Ordner bereits übertragen hast, kannst du diesen Schritt überspringen.
2. Öffne auf dem Server ein Terminal im entpackten Ordner `Pflanzenpflege-Web`.
3. Starte die App:

   ```sh
   docker compose up --build -d
   ```

4. Öffne auf deinem Computer im selben Heimnetz `http://SERVER-IP:8000`. Ersetze `SERVER-IP` durch die lokale Adresse deines Servers. Beim ersten Besuch legst du dein Konto an.

Mehr Konfiguration ist für den ersten Test nicht erforderlich. Die Daten liegen in einem Docker-Volume und bleiben bei normalen Container-Updates erhalten. Zum Nachsehen bei einem Startproblem: `docker compose logs --tail=100 pflanzenpflege`.

**Heimnetz-Test:** Port 8000 wird auf dem Docker-Host freigegeben. Leite ihn nicht im Router ins öffentliche Internet weiter. Falls eine Firewall auf dem Server läuft, muss sie Zugriffe aus deinem Heimnetz auf Port 8000 erlauben. Läuft Docker in einer VM oder einem Container, verwende deren Netzwerkadresse.

## Später: iPhone und weitere Geräte

Die Seite lässt sich über die Serveradresse auch im iPhone-Browser öffnen. Für die volle Installation als Web-App mit Service Worker und bestimmte Browserfunktionen brauchst du HTTPS. Das kannst du später ergänzen, etwa mit Tailscale Serve auf dem Docker-Host oder einem Reverse Proxy. Die App selbst kann dabei intern auf HTTP bleiben.

Für weitere Konten setze später `INVITE_CODE` in einer `.env`-Datei auf dem Server. Ohne Einladungscode kann nur das erste Konto angelegt werden. Die optionale `.env.example` zeigt auch die Felder für Trefle, Pl@ntNet, Open Plantbook und Home Assistant. Die Zugangsdaten gehören auf den Server, nicht in die App oder ein öffentliches GitHub-Repository.

## Umfang und Grenzen

Pflanzen, Räume und Fenster, Aufgaben, Pflegepläne, Fortschrittsfotos, Verlauf, Jahresüberblick, getrennte Konten, Sicherung und optional verbundene Pflanzendienste sind enthalten. Deine Daten aus der bisherigen iPhone-App werden nicht automatisch übernommen. Die tägliche Erinnerung funktioniert nur bei geöffneter Web-App; Push im Hintergrund ist noch nicht implementiert. Die Jahresgrafik ist eine Schätzung anhand deiner Intervalle.

Optional ohne Docker auf dem Mac testen: im Projektordner `python3 server.py` ausführen und `http://127.0.0.1:8000` öffnen.

## GitHub und spätere Updates

Der Quellcode liegt im öffentlichen Repository `xDerFex/Pflanzenpflege`. Der vorbereitete GitHub-Ablauf prüft den Python-Code und baut bei Änderungen am Hauptzweig automatisch ein Docker-Image für AMD64 und ARM64. Das Image wird erst verfügbar, nachdem der Code hochgeladen und der erste GitHub-Ablauf erfolgreich beendet wurde. GitHub Container Registry legt neue Pakete zunächst privat an; damit der Server ohne GitHub-Anmeldung laden kann, muss das Paket danach einmalig öffentlich gestellt werden.

Für diese spätere Variante liegt `compose.github.yaml` bereit. Auf dem Server kann man damit `docker compose -f compose.github.yaml pull` und anschließend `docker compose -f compose.github.yaml up -d` ausführen. Das Datenvolume bleibt erhalten, solange dasselbe Compose-Projektverzeichnis verwendet und das Volume nicht gelöscht wird.
