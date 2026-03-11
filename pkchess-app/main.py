from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
import json, random, string, os

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ── Charger la base Pokémon ───────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pokemons_db.json")
with open(DB_PATH, encoding="utf-8") as f:
    POKEMONS_DB = json.load(f)

# Index par niveau pour la pioche
POKEMONS_PAR_NIVEAU = {}
for p in POKEMONS_DB:
    niv = p["niveau"]
    if niv not in POKEMONS_PAR_NIVEAU:
        POKEMONS_PAR_NIVEAU[niv] = []
    POKEMONS_PAR_NIVEAU[niv].append(p)

# ── Constantes économie ───────────────────────────────────────────────────────
BONUS_SERIE    = [0, 0, 1, 1, 2, 3]
XP_PAR_NIVEAU  = [0, 1, 1, 2, 4, 8, 16, 24, 32, 40]
BONUS_PV_SYNERGIE = {3: 10, 6: 20, 9: 40}

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

# ── Pioche ────────────────────────────────────────────────────────────────────
def generer_offre_boutique(niveau_joueur: int, n: int = 5) -> list:
    """Génère n Pokémon disponibles selon le niveau du joueur.
    Exclut les évolutions (sauf si niveau_joueur >= 10 qui débloque tous les Pokémon de BASE).
    """
    pool = []
    max_niv = 10 if niveau_joueur >= 10 else niveau_joueur
    for niv in range(1, max_niv + 1):
        for p in POKEMONS_PAR_NIVEAU.get(niv, []):
            # Exclure les évolutions sauf si niveau joueur >= 10
            if not p.get("est_evolution", False) or niveau_joueur >= 10:
                pool.append(p)

    if not pool:
        return []

    choix = random.sample(pool, min(n, len(pool)))
    return [{"id": p["id"], "nom": p["nom"], "types": p["types"], "niveau": p["niveau"]} for p in choix]

# ── État initial ──────────────────────────────────────────────────────────────
parties = {}

def generer_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase, k=4))
        if code not in parties:
            return code

def etat_initial_joueur(pseudo):
    return {
        "pseudo":          pseudo,
        "pv":              100,
        "pieces":          0,
        "niveau":          1,
        "exp":             0,
        "serie_vic":       0,
        "serie_def":       0,
        "pokemon":         [],
        "synergies":       {},
        "inventaire":      [],
        "en_vie":          True,
        "a_achete_tour1":  False,  # a déjà acheté au tour 1
        "boutique_offre":  [],     # offre actuelle de la boutique
    }

# ── Logique économique ────────────────────────────────────────────────────────
def calculer_bonus_serie(joueur):
    serie = max(joueur["serie_vic"], joueur["serie_def"])
    return BONUS_SERIE[min(serie, len(BONUS_SERIE) - 1)]

def calculer_interets(pieces):
    return min(pieces // 10, 5)

def appliquer_xp(joueur, xp_gagnes=1):
    messages = []
    joueur["exp"] += xp_gagnes
    while joueur["niveau"] < 10:
        xp_needed = XP_PAR_NIVEAU[joueur["niveau"]] if joueur["niveau"] < len(XP_PAR_NIVEAU) else 999
        if joueur["exp"] >= xp_needed:
            joueur["exp"] -= xp_needed
            joueur["niveau"] += 1
            messages.append(f"🎉 {joueur['pseudo']} passe au niveau {joueur['niveau']} !")
        else:
            break
    return messages

def calculer_synergies(joueur):
    terrain = [p for p in joueur.get("pokemon", []) if p["position"] in ("off", "def")]
    compteur = {}
    for poke in terrain:
        for t in poke.get("types", []):
            compteur[t] = compteur.get(t, 0) + 1
    synergies = {}
    for t, count in compteur.items():
        if count >= 9:   synergies[t] = 9
        elif count >= 6: synergies[t] = 6
        elif count >= 3: synergies[t] = 3
    return synergies

def appliquer_bonus_pv_synergies(joueur):
    messages = []
    synergies = calculer_synergies(joueur)
    joueur["synergies"] = synergies
    for poke in joueur.get("pokemon", []):
        meilleur = 0
        for t in poke.get("types", []):
            if t in synergies:
                meilleur = max(meilleur, BONUS_PV_SYNERGIE.get(synergies[t], 0))
        ancien = poke.get("bonus_pv_synergie", 0)
        if meilleur != ancien:
            diff = meilleur - ancien
            poke["pv_max"] = poke.get("pv_max", 100) + diff
            poke["pv"] = min(poke.get("pv", 100), poke["pv_max"])
            poke["bonus_pv_synergie"] = meilleur
            if diff != 0:
                messages.append(f"✨ {poke.get('nom','?')} : {'+' if diff>0 else ''}{diff} PV MAX")
    return messages

# ── Connexions WebSocket ──────────────────────────────────────────────────────
class GestionnaireConnexions:
    def __init__(self):
        self.connexions: dict[str, dict[str, WebSocket]] = {}  # code → pseudo → ws

    async def connecter(self, code: str, pseudo: str, ws: WebSocket):
        await ws.accept()
        if code not in self.connexions:
            self.connexions[code] = {}
        self.connexions[code][pseudo] = ws

    def deconnecter(self, code: str, pseudo: str):
        if code in self.connexions and pseudo in self.connexions[code]:
            del self.connexions[code][pseudo]

    async def diffuser(self, code: str, message: dict):
        if code in self.connexions:
            morts = []
            for pseudo, ws in self.connexions[code].items():
                try:
                    await ws.send_json(message)
                except:
                    morts.append(pseudo)
            for p in morts:
                self.connexions[code].pop(p, None)

    async def envoyer_a(self, code: str, pseudo: str, message: dict):
        ws = self.connexions.get(code, {}).get(pseudo)
        if ws:
            try:
                await ws.send_json(message)
            except:
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
    joueur = etat_initial_joueur(pseudo)
    parties[code] = {
        "code":    code,
        "tour":    0,
        "phase":   "attente",
        "hote":    pseudo,
        "joueurs": {pseudo: joueur},
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
    await gestionnaire.connecter(code, pseudo, ws)
    partie = parties.get(code, {})
    # Générer offre boutique initiale et envoyer au joueur
    if pseudo in partie.get("joueurs", {}):
        joueur = partie["joueurs"][pseudo]
        if not joueur.get("boutique_offre"):
            joueur["boutique_offre"] = generer_offre_boutique(joueur["niveau"])

    await gestionnaire.diffuser(code, {
        "type":   "joueur_connecte",
        "pseudo": pseudo,
        "etat":   partie,
    })
    # Envoyer la boutique automatiquement dès la connexion (tour 0)
    if pseudo in partie.get("joueurs", {}):
        joueur = partie["joueurs"][pseudo]
        await gestionnaire.envoyer_a(code, pseudo, {
            "type":          "boutique_offre",
            "pour":          pseudo,
            "offre":         joueur["boutique_offre"],
            "tour":          partie["tour"],
            "tour1_gratuit": True,
            "auto":          True,
        })
    try:
        while True:
            data = await ws.receive_json()
            await traiter_action(code, pseudo, data)
    except WebSocketDisconnect:
        gestionnaire.deconnecter(code, pseudo)
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
            niveau    = j["niveau"]
            interets  = calculer_interets(j["pieces"])
            serie     = calculer_bonus_serie(j)
            gain      = niveau + interets + serie
            j["pieces"] += gain
            detail = f"+{niveau} niv."
            if serie > 0:    detail += f" +{serie} série"
            if interets > 0: detail += f" +{interets} intérêts"
            messages.append(f"💰 {pseudo_j} +{gain} ({detail})")
            msgs_level = appliquer_xp(j, xp_gagnes=1)
            messages.extend(msgs_level)
            msgs_syn = appliquer_bonus_pv_synergies(j)
            messages.extend(msgs_syn)
            # Nouvelle offre boutique pour ce tour (sauf si locked)
            locked = action.get("boutique_locked", False) if pseudo_j == pseudo else False
            if not locked or j.get("boutique_lock_used"):
                j["boutique_offre"] = generer_offre_boutique(j["niveau"])
                j["boutique_lock_used"] = False
            else:
                j["boutique_lock_used"] = True  # consomme le lock
            j["a_achete_tour1"] = False  # reset achat gratuit tour suivant si tour > 1

        await gestionnaire.diffuser(code, {
            "type": "fin_tour",
            "etat": partie,
            "msg":  f"⏱️ Tour {partie['tour']} — " + " | ".join(messages),
        })

    # ── Demander boutique ─────────────────────────────────────────────────────
    elif t == "demander_boutique":
        offre = joueur.get("boutique_offre") or generer_offre_boutique(joueur["niveau"])
        joueur["boutique_offre"] = offre
        await gestionnaire.envoyer_a(code, pseudo, {
            "type":      "boutique_offre",
            "pour":      pseudo,
            "offre":     offre,
            "tour":      partie["tour"],
            "tour1_gratuit": partie["tour"] == 1,
        })

    # ── Roll (renouveler boutique) ────────────────────────────────────────────
    elif t == "roll":
        cout = 2
        if joueur["pieces"] >= cout:
            joueur["pieces"] -= cout
            joueur["boutique_offre"] = generer_offre_boutique(joueur["niveau"])
            await gestionnaire.envoyer_a(code, pseudo, {
                "type":  "boutique_offre",
                "pour":  pseudo,
                "offre": joueur["boutique_offre"],
                "tour":  partie["tour"],
                "tour1_gratuit": partie["tour"] == 1,
            })
            await gestionnaire.diffuser(code, {
                "type": "etat_mis_a_jour",
                "etat": partie,
                "msg":  f"🎲 {pseudo} reroll pour {cout} pièces",
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

    # ── Capturer Pokémon → va sur le banc ────────────────────────────────────
    elif t == "capturer_pokemon":
        pokemon_id = str(action.get("pokemon_id", ""))
        cout       = action.get("cout", 0)
        tour       = partie["tour"]

        # Vérif pièces
        if joueur["pieces"] < cout:
            await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Pas assez de pièces !"})
            return

        # Tour 1 : un seul achat gratuit
        if tour == 1 and cout == 0:
            if joueur.get("a_achete_tour1"):
                await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Tu as déjà capturé ton Pokémon gratuit !"})
                return
            joueur["a_achete_tour1"] = True

        joueur["pieces"] -= cout

        # Trouver infos du Pokémon dans la DB
        poke_data = next((p for p in POKEMONS_DB if str(p["id"]) == pokemon_id), None)
        nom  = poke_data["nom"]  if poke_data else f"#{pokemon_id}"
        types = poke_data["types"] if poke_data else []
        niv_poke = poke_data["niveau"] if poke_data else 1

        # Trouver un slot libre sur le banc (positions 0-4)
        slots_banc = {p["slot"] for p in joueur["pokemon"] if p["position"] == "banc"}
        slot_libre = next((i for i in range(5) if i not in slots_banc), None)
        if slot_libre is None:
            await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Banc plein !"})
            return

        joueur["pokemon"].append({
            "id":       pokemon_id,
            "nom":      nom,
            "position": "banc",
            "slot":     slot_libre,
            "niveau":   niv_poke,
            "pv":       100,
            "pv_max":   100,
            "types":    types,
            "bonus_pv_synergie": 0,
        })

        await gestionnaire.diffuser(code, {
            "type": "etat_mis_a_jour",
            "etat": partie,
            "msg":  f"⚡ {pseudo} capture {nom} !",
        })

    # ── Déplacer Pokémon (banc ↔ arène) ──────────────────────────────────────
    elif t == "deplacer_pokemon":
        from_pos  = action.get("from_pos")
        from_slot = action.get("from_slot")
        to_pos    = action.get("to_pos")
        to_slot   = action.get("to_slot")
        niveau_joueur = joueur["niveau"]

        # Vérif cases disponibles
        cases_dispo = 5 if niveau_joueur >= 5 else 3
        if to_pos in ("off", "def") and to_slot >= cases_dispo:
            await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Case non disponible à ce niveau !"})
            return

        # Vérif case défensive : doit avoir offensif devant
        if to_pos == "def":
            off_devant = any(p["position"] == "off" and p["slot"] == to_slot for p in joueur["pokemon"])
            if not off_devant:
                await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Il faut un Pokémon offensif dans cette colonne !"})
                return

        # Trouver le Pokémon source
        poke = next((p for p in joueur["pokemon"] if p["position"] == from_pos and p["slot"] == from_slot), None)
        if not poke:
            return

        # Échanger avec l'éventuel occupant de la destination
        occupant = next((p for p in joueur["pokemon"] if p["position"] == to_pos and p["slot"] == to_slot), None)
        if occupant:
            occupant["position"] = from_pos
            occupant["slot"]     = from_slot

        poke["position"] = to_pos
        poke["slot"]     = to_slot

        appliquer_bonus_pv_synergies(joueur)

        await gestionnaire.diffuser(code, {
            "type": "etat_mis_a_jour",
            "etat": partie,
            "msg":  f"↕️ {pseudo} déplace {poke['nom']}",
        })

    # ── Retirer Pokémon → banc ────────────────────────────────────────────────
    elif t == "retirer_pokemon":
        position = action.get("position")
        slot     = action.get("slot")
        poke = next((p for p in joueur["pokemon"] if p["position"] == position and p["slot"] == slot), None)
        if poke:
            slots_banc = {p["slot"] for p in joueur["pokemon"] if p["position"] == "banc"}
            slot_libre = next((i for i in range(5) if i not in slots_banc), None)
            if slot_libre is not None:
                poke["position"] = "banc"
                poke["slot"]     = slot_libre
            appliquer_bonus_pv_synergies(joueur)
            await gestionnaire.diffuser(code, {
                "type": "etat_mis_a_jour",
                "etat": partie,
                "msg":  f"↩️ {pseudo} retire {poke['nom']} vers le banc",
            })

    else:
        await gestionnaire.diffuser(code, {"type": "action", "pseudo": pseudo, "action": action, "etat": partie})
