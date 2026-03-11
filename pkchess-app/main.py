from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
import json, random, string, asyncio

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ── Constantes économie ───────────────────────────────────────────────────────

# Bonus de série (victoires ou défaites) — index = nb de séries consécutives
# Série 0→0, 1→0, 2→1, 3→1, 4→2, 5+→3
BONUS_SERIE = [0, 0, 1, 1, 2, 3]

# XP nécessaire pour passer au niveau suivant (index = niveau actuel)
XP_PAR_NIVEAU = [0, 1, 1, 2, 4, 8, 16, 24, 32, 40]

# ── État initial ──────────────────────────────────────────────────────────────
parties = {}

def generer_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase, k=4))
        if code not in parties:
            return code

def etat_initial_joueur(pseudo):
    return {
        "pseudo":     pseudo,
        "pv":         100,
        "pieces":     0,
        "niveau":     1,
        "exp":        0,
        "serie_vic":  0,
        "serie_def":  0,
        "pokemon":    [],
        "banc":       [],
        "synergies":  {},
        "inventaire": [],
        "en_vie":     True,
    }

# ── Logique économique ────────────────────────────────────────────────────────

def calculer_bonus_serie(joueur):
    serie = max(joueur["serie_vic"], joueur["serie_def"])
    idx = min(serie, len(BONUS_SERIE) - 1)
    return BONUS_SERIE[idx]

def calculer_interets(pieces):
    return min(pieces // 10, 5)

def calculer_gain_pieces(joueur):
    niveau   = joueur["niveau"]
    interets = calculer_interets(joueur["pieces"])
    serie    = calculer_bonus_serie(joueur)
    return niveau, interets, serie

def calculer_xp_necessaire(niveau):
    if niveau >= len(XP_PAR_NIVEAU):
        return 999
    return XP_PAR_NIVEAU[niveau]

def appliquer_xp(joueur, xp_gagnes=1):
    messages = []
    joueur["exp"] += xp_gagnes
    while joueur["niveau"] < 10:
        xp_needed = calculer_xp_necessaire(joueur["niveau"])
        if joueur["exp"] >= xp_needed:
            joueur["exp"] -= xp_needed
            joueur["niveau"] += 1
            messages.append(f"🎉 {joueur['pseudo']} passe au niveau {joueur['niveau']} !")
        else:
            break
    return messages

# ── Connexions WebSocket ──────────────────────────────────────────────────────
class GestionnaireConnexions:
    def __init__(self):
        self.connexions: dict[str, list[WebSocket]] = {}

    async def connecter(self, code: str, ws: WebSocket):
        await ws.accept()
        if code not in self.connexions:
            self.connexions[code] = []
        self.connexions[code].append(ws)

    def deconnecter(self, code: str, ws: WebSocket):
        if code in self.connexions:
            try:
                self.connexions[code].remove(ws)
            except ValueError:
                pass

    async def diffuser(self, code: str, message: dict):
        if code in self.connexions:
            morts = []
            for ws in self.connexions[code]:
                try:
                    await ws.send_json(message)
                except:
                    morts.append(ws)
            for ws in morts:
                try:
                    self.connexions[code].remove(ws)
                except ValueError:
                    pass

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
    await gestionnaire.diffuser(code, {
        "type":   "joueur_connecte",
        "pseudo": pseudo,
        "etat":   parties.get(code, {}),
    })
    try:
        while True:
            data = await ws.receive_json()
            await traiter_action(code, pseudo, data)
    except WebSocketDisconnect:
        gestionnaire.deconnecter(code, ws)
        await gestionnaire.diffuser(code, {"type": "joueur_deconnecte", "pseudo": pseudo})

async def traiter_action(code: str, pseudo: str, action: dict):
    if code not in parties:
        return
    partie  = parties[code]
    joueur  = partie["joueurs"].get(pseudo)
    if not joueur:
        return

    t = action.get("type")

    # ── Fin de tour ──────────────────────────────────────────────────────────
    if t == "fin_tour":
        partie["tour"] += 1
        messages = []
        for pseudo_j, j in partie["joueurs"].items():
            if not j.get("en_vie", True):
                continue
            niveau, interets, serie = calculer_gain_pieces(j)
            gain_total = niveau + interets + serie
            j["pieces"] += gain_total
            detail = f"+{niveau} niv."
            if serie > 0:   detail += f" +{serie} série"
            if interets > 0: detail += f" +{interets} intérêts"
            messages.append(f"💰 {pseudo_j} +{gain_total} pièces ({detail})")
            msgs_level = appliquer_xp(j, xp_gagnes=1)
            messages.extend(msgs_level)

        await gestionnaire.diffuser(code, {
            "type": "etat_mis_a_jour",
            "etat": partie,
            "msg":  f"⏱️ Tour {partie['tour']} — " + " | ".join(messages),
        })

    # ── Achat XP ─────────────────────────────────────────────────────────────
    elif t == "acheter_xp":
        cout = 4
        if joueur["pieces"] >= cout and joueur["niveau"] < 10:
            joueur["pieces"] -= cout
            msgs = appliquer_xp(joueur, xp_gagnes=2)
            msg = f"📈 {pseudo} achète 2 XP pour {cout} pièces"
            if msgs: msg += " — " + " ".join(msgs)
            await gestionnaire.diffuser(code, {"type": "etat_mis_a_jour", "etat": partie, "msg": msg})
        else:
            await gestionnaire.diffuser(code, {"type": "erreur", "msg": "Pas assez de pièces ou niveau max", "pour": pseudo})

    # ── Roll ─────────────────────────────────────────────────────────────────
    elif t == "roll":
        cout = 2
        if joueur["pieces"] >= cout:
            joueur["pieces"] -= cout
            await gestionnaire.diffuser(code, {
                "type": "etat_mis_a_jour",
                "etat": partie,
                "msg":  f"🎲 {pseudo} reroll pour {cout} pièces",
            })

    # ── Dépenser générique ────────────────────────────────────────────────────
    elif t == "depenser_pieces":
        montant = action.get("montant", 0)
        raison  = action.get("raison", "")
        if joueur["pieces"] >= montant:
            joueur["pieces"] -= montant
            await gestionnaire.diffuser(code, {"type": "etat_mis_a_jour", "etat": partie,
                "msg": f"💸 {pseudo} dépense {montant} pièces ({raison})"})

    else:
        await gestionnaire.diffuser(code, {"type": "action", "pseudo": pseudo, "action": action, "etat": partie})
