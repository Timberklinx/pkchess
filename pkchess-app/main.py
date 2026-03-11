from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
import json, random, string, asyncio

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── État des parties en mémoire ──────────────────────────────────────────────
parties = {}  # code → état de la partie

def generer_code():
    """Génère un code de partie à 4 lettres."""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase, k=4))
        if code not in parties:
            return code

def etat_initial_joueur(pseudo):
    return {
        "pseudo":    pseudo,
        "pv":        100,
        "pieces":    0,
        "niveau":    1,
        "exp":       0,
        "serie_vic": 0,
        "serie_def": 0,
        "pokemon":   [],   # Pokémon sur le terrain
        "banc":      [],   # Pokémon sur le banc
        "synergies": {},   # type → niveau synergie
    }

# ── Connexions WebSocket ──────────────────────────────────────────────────────
class GestionnaireConnexions:
    def __init__(self):
        self.connexions: dict[str, list[WebSocket]] = {}  # code → liste websockets

    async def connecter(self, code: str, ws: WebSocket):
        await ws.accept()
        if code not in self.connexions:
            self.connexions[code] = []
        self.connexions[code].append(ws)

    def deconnecter(self, code: str, ws: WebSocket):
        if code in self.connexions:
            self.connexions[code].remove(ws)

    async def diffuser(self, code: str, message: dict):
        """Envoie un message à tous les joueurs de la partie."""
        if code in self.connexions:
            morts = []
            for ws in self.connexions[code]:
                try:
                    await ws.send_json(message)
                except:
                    morts.append(ws)
            for ws in morts:
                self.connexions[code].remove(ws)

gestionnaire = GestionnaireConnexions()

# ── Routes HTTP ───────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def accueil(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/jeu/{code}", response_class=HTMLResponse)
async def jeu(request: Request, code: str):
    return templates.TemplateResponse("jeu.html", {"request": request, "code": code})

@app.post("/creer")
async def creer_partie(data: dict):
    pseudo = data.get("pseudo", "Joueur")
    code = generer_code()
    parties[code] = {
        "code":    code,
        "tour":    0,
        "phase":   "attente",
        "joueurs": {pseudo: etat_initial_joueur(pseudo)},
    }
    return {"code": code}

@app.post("/rejoindre")
async def rejoindre_partie(data: dict):
    code   = data.get("code", "").upper()
    pseudo = data.get("pseudo", "Joueur")
    if code not in parties:
        return {"erreur": "Partie introuvable"}
    if pseudo in parties[code]["joueurs"]:
        return {"erreur": "Pseudo déjà pris"}
    parties[code]["joueurs"][pseudo] = etat_initial_joueur(pseudo)
    return {"ok": True}

@app.get("/etat/{code}")
async def etat_partie(code: str):
    if code not in parties:
        return {"erreur": "Partie introuvable"}
    return parties[code]

# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws/{code}/{pseudo}")
async def websocket_endpoint(ws: WebSocket, code: str, pseudo: str):
    await gestionnaire.connecter(code, ws)
    # Annoncer l'arrivée du joueur
    await gestionnaire.diffuser(code, {
        "type":    "joueur_connecte",
        "pseudo":  pseudo,
        "etat":    parties.get(code, {}),
    })
    try:
        while True:
            data = await ws.receive_json()
            await traiter_action(code, pseudo, data)
    except WebSocketDisconnect:
        gestionnaire.deconnecter(code, ws)
        await gestionnaire.diffuser(code, {"type": "joueur_deconnecte", "pseudo": pseudo})

async def traiter_action(code: str, pseudo: str, action: dict):
    """Traite une action d'un joueur et diffuse le nouvel état."""
    if code not in parties:
        return
    partie = parties[code]
    joueur = partie["joueurs"].get(pseudo)
    if not joueur:
        return

    t = action.get("type")

    if t == "fin_tour":
        # Calcul des pièces
        niveau    = joueur["niveau"]
        pieces    = joueur["pieces"]
        serie_vic = joueur["serie_vic"]
        serie_def = joueur["serie_def"]

        # Série en cours (voir plateau de jeu)
        serie = serie_vic if serie_vic > 0 else serie_def

        # Intérêts : 1 pièce par tranche de 10, max 5
        interets = min(pieces // 10, 5)

        gain = niveau + serie + interets
        joueur["pieces"] += gain
        joueur["exp"]    += 1

        # Montée de niveau (simplifié : 4 exp par niveau)
        if joueur["exp"] >= joueur["niveau"] * 4:
            joueur["niveau"] += 1
            joueur["exp"]     = 0

        await gestionnaire.diffuser(code, {
            "type":  "etat_mis_a_jour",
            "etat":  partie,
            "msg":   f"{pseudo} a gagné {gain} pièces",
        })

    elif t == "depenser_pieces":
        montant = action.get("montant", 0)
        if joueur["pieces"] >= montant:
            joueur["pieces"] -= montant
            await gestionnaire.diffuser(code, {
                "type": "etat_mis_a_jour",
                "etat": partie,
            })

    else:
        # Diffuser l'action brute pour les autres cas
        await gestionnaire.diffuser(code, {
            "type":   "action",
            "pseudo": pseudo,
            "action": action,
            "etat":   partie,
        })
