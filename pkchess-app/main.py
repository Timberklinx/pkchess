from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import os
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
import json, random, string, asyncio

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Servir les cartes PNG si le dossier existe
if os.path.exists("cartes"):
    app.mount("/cartes", StaticFiles(directory="cartes"), name="cartes")


# ── Synergies ──────────────────────────────────────────────────────────────────

SYNERGIES = {
    "Acier":    {3: "1/3 esquive effet supp.", 6: "2/3 esquive effet supp.", 9: "3/3 esquive effet supp."},
    "Combat":   {3: "Soigne Combat +10PV/niv au KO", 6: "+20PV/niv au KO", 9: "+30PV/niv au KO"},
    "Dragon":   {3: "+10 dégâts offensifs", 6: "+20 dégâts offensifs", 9: "+40 dégâts offensifs"},
    "Eau":      {3: "+10 Vitesse", 6: "+20 Vitesse", 9: "+40 Vitesse"},
    "Electrik": {3: "1/3 Paralyser (offensif)", 6: "2/3 Paralyser", 9: "3/3 Paralyser"},
    "Fée":      {3: "+1 pièce fin combat", 6: "+2 pièces", 9: "+4 pièces"},
    "Feu":      {3: "1/3 Brûler (offensif)", 6: "2/3 Brûler", 9: "3/3 Brûler"},
    "Glace":    {3: "1/3 Geler (offensif)", 6: "2/3 Geler", 9: "3/3 Geler"},
    "Insecte":  {3: "+1 pt Force/Insecte", 6: "+2 pts Force/Insecte", 9: "+3 pts Force/Insecte"},
    "Normal":   {3: "+10 PV MAX", 6: "+20 PV MAX", 9: "+40 PV MAX"},
    "Plante":   {3: "+10 PV soignés fin combat", 6: "+20 PV soignés", 9: "+40 PV soignés"},
    "Poison":   {3: "1/3 Empoisonner (offensif)", 6: "2/3 Empoisonner", 9: "3/3 Empoisonner"},
    "Psy":      {3: "1/3 Confusion (offensif)", 6: "2/3 Confusion", 9: "3/3 Confusion"},
    "Roche":    {3: "-10 dégâts reçus", 6: "-20 dégâts reçus", 9: "-30 dégâts reçus"},
    "Sol":      {3: "1/3 Piéger (offensif)", 6: "2/3 Piéger", 9: "3/3 Piéger"},
    "Spectre":  {3: "KO -> 10 dégâts x niv col. adverse", 6: "20 dégâts x niv", 9: "30 dégâts x niv"},
    "Ténèbre":  {3: "1/3 Apeurer (offensif)", 6: "2/3 Apeurer", 9: "3/3 Apeurer"},
    "Vol":      {3: "1/3 cible Support +10 dégâts", 6: "2/3 +20 dégâts", 9: "3/3 +30 dégâts"},
}

def calculer_synergies(joueur):
    """Compte les types sur le terrain (arene_off + arene_def) et retourne les synergies actives."""
    comptage = {}
    terrain = joueur.get("arene_off", []) + joueur.get("arene_def", [])
    for pokemon in terrain:
        for type_ in pokemon.get("types", []):
            comptage[type_] = comptage.get(type_, 0) + 1

    synergies_actives = {}
    for type_, nb in comptage.items():
        if nb >= 9:   palier = 9
        elif nb >= 6: palier = 6
        elif nb >= 3: palier = 3
        else: continue
        synergies_actives[type_] = {
            "nb": nb,
            "palier": palier,
            "bonus": SYNERGIES.get(type_, {}).get(palier, ""),
        }
    return synergies_actives

# ── Constantes économie ───────────────────────────────────────────────────────

# Bonus de série (victoires ou défaites) — index = nb de séries consécutives
# Série 0→0, 1→0, 2→1, 3→1, 4→2, 5+→3
BONUS_SERIE = [0, 0, 1, 1, 2, 3]

# ── Synergies ─────────────────────────────────────────────────────────────────

SYNERGIES = {
    "Acier":    {3: "1/3 esquive effet supp.", 6: "2/3 esquive", 9: "3/3 esquive"},
    "Combat":   {3: "Soigne 10PV/niv KO",     6: "20PV/niv KO", 9: "30PV/niv KO"},
    "Dragon":   {3: "+10 dégâts offensifs",    6: "+20 dégâts",  9: "+40 dégâts"},
    "Eau":      {3: "+10 Vitesse",             6: "+20 Vitesse", 9: "+40 Vitesse"},
    "Electrik": {3: "1/3 Paralyse",            6: "2/3 Paralyse",9: "3/3 Paralyse"},
    "Fée":      {3: "+1 pièce fin combat",     6: "+2 pièces",   9: "+4 pièces"},
    "Feu":      {3: "1/3 Brûlure",             6: "2/3 Brûlure", 9: "3/3 Brûlure"},
    "Glace":    {3: "1/3 Gel",                 6: "2/3 Gel",     9: "3/3 Gel"},
    "Insecte":  {3: "+1 pt Force/Insecte",     6: "+2 pts",      9: "+3 pts"},
    "Normal":   {3: "+10 PV MAX",              6: "+20 PV MAX",  9: "+40 PV MAX"},
    "Plante":   {3: "+10 PV soignés fin combat",6:"+20 PV",      9: "+40 PV"},
    "Poison":   {3: "1/3 Empoisonnement",      6: "2/3",         9: "3/3"},
    "Psy":      {3: "1/3 Confusion",           6: "2/3",         9: "3/3"},
    "Roche":    {3: "-10 dégâts reçus",        6: "-20 dégâts",  9: "-30 dégâts"},
    "Sol":      {3: "1/3 Piège",               6: "2/3",         9: "3/3"},
    "Spectre":  {3: "KO→10 dégâts×niv adverse",6:"KO→20 dégâts", 9:"KO→30 dégâts"},
    "Ténèbre":  {3: "1/3 Peur",                6: "2/3",         9: "3/3"},
    "Vol":      {3: "1/3 cible Support+10 dég",6:"2/3+20 dég",   9:"3/3+30 dég"},
}

# Bonus PV MAX universel par palier de synergie
BONUS_PV_SYNERGIE = {3: 10, 6: 20, 9: 40}

def calculer_synergies(joueur):
    """Calcule les synergies actives basées sur les Pokémon en arène (offensifs + défensifs)."""
    # Compter les types sur le terrain (arène rouge + arène bleue)
    terrain = joueur.get("pokemon", [])  # liste de dicts avec "types": ["Feu", "Vol"]
    compteur_types = {}
    for poke in terrain:
        types = poke.get("types", [])
        for t in types:
            compteur_types[t] = compteur_types.get(t, 0) + 1

    synergies_actives = {}
    for type_poke, count in compteur_types.items():
        if count >= 9:
            synergies_actives[type_poke] = 9
        elif count >= 6:
            synergies_actives[type_poke] = 6
        elif count >= 3:
            synergies_actives[type_poke] = 3

    return synergies_actives

def appliquer_bonus_pv_synergies(joueur):
    """Applique les bonus de PV MAX liés aux synergies. Retourne les messages."""
    messages = []
    synergies = calculer_synergies(joueur)
    joueur["synergies"] = synergies

    for poke in joueur.get("pokemon", []):
        # Trouver le meilleur bonus PV parmi les types du Pokémon
        meilleur_bonus = 0
        for t in poke.get("types", []):
            if t in synergies:
                palier = synergies[t]
                bonus = BONUS_PV_SYNERGIE.get(palier, 0)
                meilleur_bonus = max(meilleur_bonus, bonus)

        # Appliquer le bonus PV MAX (si pas déjà appliqué)
        ancien_bonus = poke.get("bonus_pv_synergie", 0)
        if meilleur_bonus != ancien_bonus:
            diff = meilleur_bonus - ancien_bonus
            poke["pv_max"] = poke.get("pv_max", poke.get("pv", 100)) + diff
            poke["pv"] = min(poke.get("pv", 100), poke["pv_max"])
            poke["bonus_pv_synergie"] = meilleur_bonus
            if diff != 0:
                messages.append(f"✨ {poke.get('nom','?')} : {'+'if diff>0 else ''}{diff} PV MAX (synergie)")

    return messages



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
        "arene_off":  [],  # Pokémon offensifs (cases rouges)
        "arene_def":  [],  # Pokémon défensifs (cases bleues)
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
            j["synergies"] = calculer_synergies(j)
            msgs_level = appliquer_xp(j, xp_gagnes=1)
            messages.extend(msgs_level)
            # Recalculer les synergies
            msgs_syn = appliquer_bonus_pv_synergies(j)
            messages.extend(msgs_syn)

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
