"""Faux serveur HTTP local pour les tests : enregistre les requêtes, rend une réponse programmée."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class Gestionnaire(BaseHTTPRequestHandler):
    vues: list = []
    reponses: list = []  # file de (statut, corps, entêtes) ; la dernière se répète

    def _repondre(self):
        n = int(self.headers.get("Content-Length") or 0)
        corps = json.loads(self.rfile.read(n)) if n else None
        Gestionnaire.vues.append({"methode": self.command, "chemin": self.path,
                                  "auth": self.headers.get("Authorization"), "corps": corps,
                                  "agent": self.headers.get("User-Agent")})
        statut, payload, entetes = Gestionnaire.reponses[0] if len(Gestionnaire.reponses) == 1 else Gestionnaire.reponses.pop(0)
        if statut == 302:
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/ailleurs")
            self.end_headers()
            return
        data = json.dumps(payload).encode()
        self.send_response(statut)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (entetes or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _repondre

    def log_message(self, *args):
        pass


def demarrer():
    serveur = HTTPServer(("127.0.0.1", 0), Gestionnaire)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    return serveur, f"http://127.0.0.1:{serveur.server_port}"


def programmer(*reponses):
    Gestionnaire.vues = []
    Gestionnaire.reponses = [r if len(r) == 3 else (*r, None) for r in reponses]
