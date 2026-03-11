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

POKEMONS_PAR_NIVEAU = {}
for p in POKEMONS_DB:
    niv = p["niveau"]
    if niv not in POKEMONS_PAR_NIVEAU:
        POKEMONS_PAR_NIVEAU[niv] = []
    POKEMONS_PAR_NIVEAU[niv].append(p)

# ── Constantes ────────────────────────────────────────────────────────────────
BONUS_SERIE       = [0, 0, 1, 1, 2, 3]
XP_PAR_NIVEAU     = [0, 1, 1, 2, 4, 8, 16, 24, 32, 40]
BONUS_PV_SYNERGIE = {3: 10, 6: 20, 9: 40}

SYNERGIES = {
    "Acier":    {3: "1/3 esquive",          6: "2/3 esquive",   9: "3/3 esquive"},
    "Combat":   {3: "Soigne 10PV/niv KO",   6: "20PV/niv KO",   9: "30PV/niv KO"},
    "Dragon":   {3: "+10 dégâts off.",       6: "+20 dégâts",    9: "+40 dégâts"},
    "Eau":      {3: "+10 Vitesse",           6: "+20 Vitesse",   9: "+40 Vitesse"},
    "Electrik": {3: "1/3 Paralyse",          6: "2/3 Paralyse",  9: "3/3 Paralyse"},
    "Fée":      {3: "+1 pièce/combat",       6: "+2 pièces",     9: "+4 pièces"},
    "Feu":      {3: "1/3 Brûlure",           6: "2/3 Brûlure",   9: "3/3 Brûlure"},
    "Glace":    {3: "1/3 Gel",               6: "2/3 Gel",       9: "3/3 Gel"},
    "Insecte":  {3: "+1 pt Force/Insecte",   6: "+2 pts",        9: "+3 pts"},
    "Normal":   {3: "+10 PV MAX",            6: "+20 PV MAX",    9: "+40 PV MAX"},
    "Plante":   {3: "+10 PV soignés",        6: "+20 PV",        9: "+40 PV"},
    "Poison":   {3: "1/3 Empoisonnement",    6: "2/3",           9: "3/3"},
    "Psy":      {3: "1/3 Confusion",         6: "2/3",           9: "3/3"},
    "Roche":    {3: "-10 dégâts reçus",      6: "-20 dégâts",    9: "-30 dégâts"},
    "Sol":      {3: "1/3 Piège",             6: "2/3",           9: "3/3"},
    "Spectre":  {3: "KO→10 dég×niv adverse", 6: "KO→20 dég",    9: "KO→30 dég"},
    "Ténèbre":  {3: "1/3 Peur",              6: "2/3",           9: "3/3"},
    "Vol":      {3: "1/3 cible Support",      6: "2/3+20 dég",   9: "3/3+30 dég"},
}

# ── Pool partagé par partie ───────────────────────────────────────────────────
def init_pool(partie):
    """Crée le pool global de la partie — chaque ID est unique, stocké comme liste."""
    pool = [p["id"] for p in POKEMONS_DB]
    random.shuffle(pool)
    partie["pool"] = pool  # liste simple, JSON-sérialisable

def piocher_depuis_pool(partie, niveau_joueur, n=5):
    """Pioche n Pokémon de base dispo dans le pool selon le niveau joueur."""
    max_niv = 10 if niveau_joueur >= 10 else niveau_joueur
    pool = partie.get("pool", [])
    eligibles = []
    for pid in pool:
        p = _get_poke(pid)
        if p and p.get("stade", 0) == 0 and p["niveau"] <= max_niv:
            eligibles.append(pid)
    choix = eligibles[:n]
    # Retirer du pool
    for pid in choix:
        if pid in pool:
            pool.remove(pid)
    return [_get_poke(pid) for pid in choix]

def retourner_au_pool(partie, pokemon_ids):
    """Remet des Pokémon dans le pool."""
    pool = partie.get("pool", [])
    for pid in pokemon_ids:
        if pid not in pool:
            pool.append(pid)

def _get_poke(pid):
    return next((p for p in POKEMONS_DB if p["id"] == pid), None)

# ── Pioche boutique ───────────────────────────────────────────────────────────
def generer_offre_boutique(partie, niveau_joueur, ancienne_offre=None, locked=False):
    if locked and ancienne_offre:
        return ancienne_offre
    # Remettre l'ancienne offre dans le pool avant d'en tirer une nouvelle
    if ancienne_offre:
        retourner_au_pool(partie, [p["id"] for p in ancienne_offre])
    pokes = piocher_depuis_pool(partie, niveau_joueur)
    return [{"id": p["id"], "nom": p["nom"], "types": p["types"], "niveau": p["niveau"]} for p in pokes]

# ── État joueur ───────────────────────────────────────────────────────────────
def etat_initial_joueur(pseudo):
    return {
        "pseudo":         pseudo,
        "pv":             100,
        "pieces":         0,
        "niveau":         1,
        "exp":            0,
        "serie_vic":      0,
        "serie_def":      0,
        "pokemon":        [],
        "synergies":      {},
        "inventaire":     [],
        "en_vie":         True,
        "a_achete_tour1": False,
        "boutique_offre": [],
        "boutique_locked": False,
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
            messages.append(f"🎉 {joueur['pseudo']} passe niveau {joueur['niveau']} !")
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

def prix_vente(poke):
    """Prix de vente = niveau du Pokémon."""
    return poke.get("niveau", 1)

# ── Logique de combat ─────────────────────────────────────────────────────────
def points_force(poke):
    """Points de force d'un Pokémon selon son niveau + bonus stade."""
    niv = poke.get("niveau", 1)
    if niv <= 3:   base = 1
    elif niv <= 6: base = 2
    else:          base = 3
    bonus_stade = poke.get("stade", 0)  # +1 par stade (évolution)
    return base + bonus_stade

def equipe_terrain(joueur):
    """Retourne les Pokémon en off/def non KO."""
    return [p for p in joueur.get("pokemon", [])
            if p["position"] in ("off", "def") and not p.get("ko", False)]

def lancer_combat(partie):
    """
    Résolution des combats pour un tour.
    Retourne une liste de résultats de combats pour diffusion.
    """
    joueurs_actifs = {
        pseudo: j for pseudo, j in partie["joueurs"].items()
        if j.get("en_vie", True)
    }
    pseudos = list(joueurs_actifs.keys())
    random.shuffle(pseudos)

    resultats = []
    deja_apparies = set()

    # Apparier les joueurs 2 par 2
    paires = []
    disponibles = [p for p in pseudos]
    random.shuffle(disponibles)
    while len(disponibles) >= 2:
        a = disponibles.pop()
        b = disponibles.pop()
        paires.append((a, b))
    # Si nombre impair → le dernier se bat contre un ghost (aucun adversaire)
    solo = disponibles[0] if disponibles else None

    for (p1, p2) in paires:
        j1 = joueurs_actifs[p1]
        j2 = joueurs_actifs[p2]
        res = resoudre_duel(partie, p1, j1, p2, j2)
        resultats.append(res)

    if solo:
        j_solo = joueurs_actifs[solo]
        res = resoudre_duel_ghost(partie, solo, j_solo)
        resultats.append(res)

    return resultats

def resoudre_duel(partie, p1, j1, p2, j2):
    """Combat entre deux joueurs."""
    equipe1 = equipe_terrain(j1)
    equipe2 = equipe_terrain(j2)

    pts1 = sum(points_force(p) for p in equipe1)
    pts2 = sum(points_force(p) for p in equipe2)

    logs = []
    logs.append(f"⚔️ {p1} ({pts1} pts) vs {p2} ({pts2} pts)")

    # Dégâts directs des Pokémon sans adversaire (équipe plus grande)
    degats_directs_p2 = 0  # dégâts reçus par j2 de Pokémon sans adversaire de j1
    degats_directs_p1 = 0

    taille1, taille2 = len(equipe1), len(equipe2)
    if taille1 > taille2:
        sans_adv = sorted(equipe1, key=lambda p: points_force(p), reverse=True)[:taille1 - taille2]
        for poke in sans_adv:
            dmg = points_force(poke)
            degats_directs_p2 += dmg
            logs.append(f"💥 {poke['nom']} sans adversaire → {dmg} dégâts directs à {p2}")
    elif taille2 > taille1:
        sans_adv = sorted(equipe2, key=lambda p: points_force(p), reverse=True)[:taille2 - taille1]
        for poke in sans_adv:
            dmg = points_force(poke)
            degats_directs_p1 += dmg
            logs.append(f"💥 {poke['nom']} sans adversaire → {dmg} dégâts directs à {p1}")

    # Résultat global
    if pts1 > pts2:
        ecart = pts1 - pts2
        j2["pv"] = max(0, j2["pv"] - ecart - degats_directs_p2)
        j1["serie_vic"] = j1.get("serie_vic", 0) + 1
        j1["serie_def"] = 0
        j2["serie_def"] = j2.get("serie_def", 0) + 1
        j2["serie_vic"] = 0
        logs.append(f"🏆 {p1} gagne ! {p2} perd {ecart + degats_directs_p2} PV → {j2['pv']} PV")
        gagnant, perdant = p1, p2
    elif pts2 > pts1:
        ecart = pts2 - pts1
        j1["pv"] = max(0, j1["pv"] - ecart - degats_directs_p1)
        j2["serie_vic"] = j2.get("serie_vic", 0) + 1
        j2["serie_def"] = 0
        j1["serie_def"] = j1.get("serie_def", 0) + 1
        j1["serie_vic"] = 0
        logs.append(f"🏆 {p2} gagne ! {p1} perd {ecart + degats_directs_p1} PV → {j1['pv']} PV")
        gagnant, perdant = p2, p1
    else:
        # Égalité
        if degats_directs_p2 > 0:
            j2["pv"] = max(0, j2["pv"] - degats_directs_p2)
        if degats_directs_p1 > 0:
            j1["pv"] = max(0, j1["pv"] - degats_directs_p1)
        logs.append(f"🤝 Égalité !")
        gagnant, perdant = None, None

    # Vérifier éliminations
    for pseudo, joueur in [(p1, j1), (p2, j2)]:
        if joueur["pv"] <= 0:
            joueur["en_vie"] = False
            logs.append(f"💀 {pseudo} est éliminé !")

    # Les Pokémon KO vont au banc
    for joueur in [j1, j2]:
        for poke in joueur.get("pokemon", []):
            if poke["position"] in ("off", "def") and poke.get("ko", False):
                slots_banc = {p["slot"] for p in joueur["pokemon"] if p["position"] == "banc"}
                slot_libre = next((i for i in range(10) if i not in slots_banc), None)
                if slot_libre is not None:
                    poke["position"] = "banc"
                    poke["slot"] = slot_libre

    return {
        "type_duel": "normal",
        "joueurs": [p1, p2],
        "pts": [pts1, pts2],
        "gagnant": gagnant,
        "perdant": perdant,
        "logs": logs,
        "pv_apres": {p1: j1["pv"], p2: j2["pv"]},
    }

def resoudre_duel_ghost(partie, pseudo, joueur):
    """Joueur seul (nombre impair) : ses Pokémon sans adversaire font des dégâts directs."""
    equipe = equipe_terrain(joueur)
    pts = sum(points_force(p) for p in equipe)
    logs = [f"👻 {pseudo} n'a pas d'adversaire ce tour"]
    # Pas de dégâts reçus, pas de dégâts infligés, série neutre
    return {
        "type_duel": "ghost",
        "joueurs": [pseudo],
        "pts": [pts],
        "gagnant": None,
        "perdant": None,
        "logs": logs,
        "pv_apres": {pseudo: joueur["pv"]},
    }

# ── Connexions WebSocket ──────────────────────────────────────────────────────
class GestionnaireConnexions:
    def __init__(self):
        self.connexions: dict[str, dict[str, WebSocket]] = {}

    async def connecter(self, code, pseudo, ws):
        await ws.accept()
        if code not in self.connexions:
            self.connexions[code] = {}
        self.connexions[code][pseudo] = ws

    def deconnecter(self, code, pseudo):
        if code in self.connexions and pseudo in self.connexions[code]:
            del self.connexions[code][pseudo]

    async def diffuser(self, code, message):
        if code in self.connexions:
            morts = []
            msg_serialisable = self._nettoyer(message)
            for pseudo, ws in self.connexions[code].items():
                try:    await ws.send_json(msg_serialisable)
                except: morts.append(pseudo)
            for p in morts: self.connexions[code].pop(p, None)

    async def envoyer_a_raw(self, code, pseudo, message):
        ws = self.connexions.get(code, {}).get(pseudo)
        if ws:
            try: await ws.send_json(self._nettoyer(message))
            except: pass

    def _nettoyer(self, obj):
        """Rend un objet sérialisable JSON (retire les sets, etc.)"""
        if isinstance(obj, dict):
            return {k: self._nettoyer(v) for k, v in obj.items()}
        elif isinstance(obj, (set, frozenset)):
            return list(obj)
        elif isinstance(obj, list):
            return [self._nettoyer(i) for i in obj]
        return obj

    async def envoyer_a(self, code, pseudo, message):
        ws = self.connexions.get(code, {}).get(pseudo)
        if ws:
            try: await ws.send_json(self._nettoyer(message))
            except: pass

gestionnaire = GestionnaireConnexions()
parties = {}

def generer_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase, k=4))
        if code not in parties: return code

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
    code   = generer_code()
    joueur = etat_initial_joueur(pseudo)
    partie = {
        "code":    code,
        "tour":    0,
        "phase":   "attente",
        "hote":    pseudo,
        "joueurs": {pseudo: joueur},
        "pool":    [],
    }
    init_pool(partie)
    joueur["boutique_offre"] = generer_offre_boutique(partie, joueur["niveau"])
    parties[code] = partie
    return {"code": code}

@app.post("/rejoindre")
async def rejoindre_partie(data: dict):
    code   = data.get("code", "").upper()
    pseudo = data.get("pseudo", "Joueur")
    if code not in parties:
        return {"erreur": "Partie introuvable"}
    if pseudo in parties[code]["joueurs"]:
        return {"erreur": "Pseudo déjà pris"}
    joueur = etat_initial_joueur(pseudo)
    partie = parties[code]
    joueur["boutique_offre"] = generer_offre_boutique(partie, joueur["niveau"])
    partie["joueurs"][pseudo] = joueur
    return {"ok": True}

@app.get("/etat/{code}")
async def etat_partie(code: str):
    if code not in parties: return {"erreur": "Partie introuvable"}
    return parties[code]

# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws/{code}/{pseudo}")
async def websocket_endpoint(ws: WebSocket, code: str, pseudo: str):
    await gestionnaire.connecter(code, pseudo, ws)
    partie = parties.get(code, {})

    await gestionnaire.diffuser(code, {
        "type": "joueur_connecte", "pseudo": pseudo, "etat": partie,
    })

    # Envoyer boutique dès la connexion
    if pseudo in partie.get("joueurs", {}):
        joueur = partie["joueurs"][pseudo]
        await gestionnaire.envoyer_a(code, pseudo, {
            "type": "boutique_offre", "pour": pseudo,
            "offre": joueur["boutique_offre"],
            "tour": partie["tour"], "tour1_gratuit": True, "auto": True,
        })

    try:
        while True:
            data = await ws.receive_json()
            await traiter_action(code, pseudo, data)
    except WebSocketDisconnect:
        gestionnaire.deconnecter(code, pseudo)
        await gestionnaire.diffuser(code, {"type": "joueur_deconnecte", "pseudo": pseudo})

# ── Traitement actions ────────────────────────────────────────────────────────
async def traiter_action(code, pseudo, action):
    if code not in parties: return
    partie = parties[code]
    joueur = partie["joueurs"].get(pseudo)
    if not joueur: return
    t = action.get("type")

    # ── Fin de tour ──────────────────────────────────────────────────────────
    if t == "fin_tour":
        partie["tour"] += 1
        messages = []
        locked_par_joueur = {pseudo: action.get("boutique_locked", False)}

        for pj, j in partie["joueurs"].items():
            if not j.get("en_vie", True): continue
            niveau   = j["niveau"]
            interets = calculer_interets(j["pieces"])
            serie    = calculer_bonus_serie(j)
            gain     = niveau + interets + serie
            j["pieces"] += gain
            detail = f"+{niveau} niv."
            if serie > 0:    detail += f" +{serie} série"
            if interets > 0: detail += f" +{interets} intérêts"
            messages.append(f"💰 {pj} +{gain} ({detail})")
            msgs_level = appliquer_xp(j, xp_gagnes=1)
            messages.extend(msgs_level)
            appliquer_bonus_pv_synergies(j)
            # Nouvelle boutique (sauf si locked)
            locked = j.get("boutique_locked", False)
            j["boutique_offre"] = generer_offre_boutique(
                partie, j["niveau"],
                ancienne_offre=j["boutique_offre"],
                locked=locked
            )
            j["boutique_locked"] = False
            j["a_achete_tour1"]  = False

        await gestionnaire.diffuser(code, {
            "type": "fin_tour", "etat": partie,
            "msg": f"⏱️ Tour {partie['tour']} — " + " | ".join(messages),
        })
        # Envoyer la nouvelle boutique à chaque joueur
        for pj, j in partie["joueurs"].items():
            await gestionnaire.envoyer_a(code, pj, {
                "type": "boutique_offre", "pour": pj,
                "offre": j["boutique_offre"],
                "tour": partie["tour"],
                "tour1_gratuit": partie["tour"] <= 1,
                "auto": True,
            })

    # ── Demander boutique ─────────────────────────────────────────────────────
    elif t == "demander_boutique":
        offre = joueur.get("boutique_offre") or generer_offre_boutique(partie, joueur["niveau"])
        joueur["boutique_offre"] = offre
        await gestionnaire.envoyer_a(code, pseudo, {
            "type": "boutique_offre", "pour": pseudo,
            "offre": offre, "tour": partie["tour"],
            "tour1_gratuit": partie["tour"] <= 1,
        })

    # ── Roll ──────────────────────────────────────────────────────────────────
    elif t == "roll":
        cout = 2
        if joueur["pieces"] >= cout:
            joueur["pieces"] -= cout
            joueur["boutique_offre"] = generer_offre_boutique(
                partie, joueur["niveau"], ancienne_offre=joueur["boutique_offre"]
            )
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "boutique_offre", "pour": pseudo,
                "offre": joueur["boutique_offre"], "tour": partie["tour"],
                "tour1_gratuit": partie["tour"] <= 1,
            })
            await gestionnaire.diffuser(code, {
                "type": "etat_mis_a_jour", "etat": partie,
                "msg": f"🎲 {pseudo} reroll",
            })
        else:
            await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Pas assez de pièces !", "pour": pseudo})

    # ── Lock boutique ─────────────────────────────────────────────────────────
    elif t == "lock_boutique":
        joueur["boutique_locked"] = action.get("locked", False)

    # ── Acheter XP ────────────────────────────────────────────────────────────
    elif t == "acheter_xp":
        cout = 4
        if joueur["pieces"] >= cout and joueur["niveau"] < 10:
            joueur["pieces"] -= cout
            msgs = appliquer_xp(joueur, xp_gagnes=2)
            msg = f"📈 {pseudo} achète 2 XP"
            if msgs: msg += " — " + " ".join(msgs)
            await gestionnaire.diffuser(code, {"type": "etat_mis_a_jour", "etat": partie, "msg": msg})
        else:
            await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Pas assez de pièces ou niveau max !", "pour": pseudo})

    # ── Capturer Pokémon → banc ───────────────────────────────────────────────
    elif t == "capturer_pokemon":
        pokemon_id = str(action.get("pokemon_id", ""))
        cout       = action.get("cout", 0)
        tour       = partie["tour"]
        gratuit    = tour <= 1 and not joueur.get("a_achete_tour1")

        if not gratuit and joueur["pieces"] < cout:
            await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Pas assez de pièces !", "pour": pseudo})
            return

        if gratuit:
            joueur["a_achete_tour1"] = True
        else:
            joueur["pieces"] -= cout

        # Retirer de l'offre boutique
        offre = joueur.get("boutique_offre", [])
        offre_restante = [p for p in offre if p["id"] != pokemon_id]
        # Les autres Pokémon de la boutique restent en boutique (pas dans le pool)
        joueur["boutique_offre"] = offre_restante

        poke_data = _get_poke(pokemon_id)
        nom      = poke_data["nom"] if poke_data else f"#{pokemon_id}"
        types    = poke_data["types"] if poke_data else []
        niv_poke = poke_data["niveau"] if poke_data else 1
        stade    = poke_data.get("stade", 0) if poke_data else 0

        slots_banc = {p["slot"] for p in joueur["pokemon"] if p["position"] == "banc"}
        slot_libre = next((i for i in range(10) if i not in slots_banc), None)
        if slot_libre is None:
            await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Banc plein !", "pour": pseudo})
            return

        joueur["pokemon"].append({
            "id": pokemon_id, "nom": nom,
            "position": "banc", "slot": slot_libre,
            "niveau": niv_poke, "stade": stade,
            "pv": 100, "pv_max": 100,
            "types": types, "bonus_pv_synergie": 0,
            "ko": False,
        })

        await gestionnaire.diffuser(code, {
            "type": "etat_mis_a_jour", "etat": partie,
            "msg": f"⚡ {pseudo} capture {nom} !",
        })

    # ── Vendre Pokémon ────────────────────────────────────────────────────────
    elif t == "vendre_pokemon":
        position = action.get("position")
        slot     = action.get("slot")
        poke = next((p for p in joueur["pokemon"] if p["position"] == position and p["slot"] == slot), None)
        if not poke:
            return
        gain = prix_vente(poke)
        joueur["pokemon"].remove(poke)
        joueur["pieces"] += gain
        # Remettre dans le pool
        retourner_au_pool(partie, [poke["id"]])
        appliquer_bonus_pv_synergies(joueur)
        await gestionnaire.diffuser(code, {
            "type": "etat_mis_a_jour", "etat": partie,
            "msg": f"💸 {pseudo} vend {poke['nom']} (+{gain} pièces)",
        })

    # ── Déplacer Pokémon ──────────────────────────────────────────────────────
    elif t == "deplacer_pokemon":
        fp, fs = action.get("from_pos"), action.get("from_slot")
        tp, ts = action.get("to_pos"), action.get("to_slot")
        niveau_joueur = joueur["niveau"]
        # Cases 0 et 4 (extrêmes) bloquées avant niveau 5
        case_bloquee = tp in ("off", "def") and (ts == 0 or ts == 4) and niveau_joueur < 5

        if case_bloquee:
            await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Case non disponible à ce niveau !", "pour": pseudo})
            return
        # Limite terrain = niveau dresseur
        nb_terrain = sum(1 for p in joueur["pokemon"] if p["position"] in ("off", "def") and not getPoke_joueur(joueur, p["position"], p["slot"]) == getPoke_joueur(joueur, tp, ts))
        nb_terrain = sum(1 for p in joueur["pokemon"] if p["position"] in ("off", "def"))
        poke_existant = next((p for p in joueur["pokemon"] if p["position"] == tp and p["slot"] == ts), None)
        if tp in ("off", "def") and not poke_existant and nb_terrain >= niveau_joueur:
            await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Terrain plein pour ce niveau !", "pour": pseudo})
            return
        if tp == "def":
            off_devant = any(p["position"] == "off" and p["slot"] == ts for p in joueur["pokemon"])
            if not off_devant:
                await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Pas d'offensif dans cette colonne !", "pour": pseudo})
                return

        poke     = next((p for p in joueur["pokemon"] if p["position"] == fp and p["slot"] == fs), None)
        if not poke: return
        occupant = next((p for p in joueur["pokemon"] if p["position"] == tp and p["slot"] == ts), None)
        if occupant:
            occupant["position"] = fp
            occupant["slot"]     = fs
        poke["position"] = tp
        poke["slot"]     = ts
        appliquer_bonus_pv_synergies(joueur)
        await gestionnaire.diffuser(code, {
            "type": "etat_mis_a_jour", "etat": partie,
            "msg": f"↕️ {pseudo} déplace {poke['nom']}",
        })

    # ── Lancer combat ────────────────────────────────────────────────────────
    elif t == "lancer_combat":
        # Seul l'hôte peut déclencher le combat
        if partie.get("hote") != pseudo:
            await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Seul l'hôte peut lancer le combat !", "pour": pseudo})
            return
        if partie.get("phase") == "combat":
            await gestionnaire.envoyer_a(code, pseudo, {"type": "erreur", "msg": "Combat déjà en cours !", "pour": pseudo})
            return

        partie["phase"] = "combat"
        resultats = lancer_combat(partie)
        partie["phase"] = "preparation"

        # Diffuser les résultats à tous
        await gestionnaire.diffuser(code, {
            "type": "resultat_combat",
            "etat": partie,
            "resultats": resultats,
            "tour": partie["tour"],
        })

    # ── Retirer Pokémon → banc ────────────────────────────────────────────────
    elif t == "retirer_pokemon":
        position = action.get("position")
        slot     = action.get("slot")
        poke = next((p for p in joueur["pokemon"] if p["position"] == position and p["slot"] == slot), None)
        if poke:
            slots_banc = {p["slot"] for p in joueur["pokemon"] if p["position"] == "banc"}
            slot_libre = next((i for i in range(10) if i not in slots_banc), None)
            if slot_libre is not None:
                poke["position"] = "banc"
                poke["slot"]     = slot_libre
            appliquer_bonus_pv_synergies(joueur)
            await gestionnaire.diffuser(code, {
                "type": "etat_mis_a_jour", "etat": partie,
                "msg": f"↩️ {pseudo} retire {poke['nom']} vers le banc",
            })
