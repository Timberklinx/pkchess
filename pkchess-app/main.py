from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
import json, random, string, os

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ── Base Pokémon ──────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pokemons_db.json")
with open(DB_PATH, encoding="utf-8") as f:
    POKEMONS_DB = json.load(f)

def _get_poke(pid):
    return next((p for p in POKEMONS_DB if p["id"] == pid), None)

# IDs qui sont des formes intermédiaires (cibles d'évolution) → exclues du pool
_IDS_INTERMEDIAIRES = {p["evolution_id"] for p in POKEMONS_DB if p.get("evolution_id")}
# Formes intermédiaires dont le lien d'entrée est absent dans la DB (bug données)
_IDS_INTERMEDIAIRES |= {"0266"}  # Armulys

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
    "Vol":      {3: "1/3 cible Support",     6: "2/3+20 dég",    9: "3/3+30 dég"},
}

# ── Pool ──────────────────────────────────────────────────────────────────────
def init_pool(partie):
    pool = [p["id"] for p in POKEMONS_DB]
    random.shuffle(pool)
    partie["pool"] = pool

def piocher_depuis_pool(partie, niveau_joueur, n=5):
    """Pioche n Pokémon stade 0 de niveau <= niveau_joueur, choix aléatoire."""
    max_niv = min(niveau_joueur, 10)
    pool = partie.get("pool", [])
    eligibles = [pid for pid in pool
                 if (lambda p: p
                     and p.get("stade", 0) == 0
                     and p["id"] not in _IDS_INTERMEDIAIRES
                     and p["niveau"] <= max_niv)(_get_poke(pid))]
    random.shuffle(eligibles)
    choix = eligibles[:n]
    for pid in choix:
        pool.remove(pid)
    return [_get_poke(pid) for pid in choix]

def retourner_au_pool(partie, pokemon_ids):
    pool = partie.get("pool", [])
    for pid in pokemon_ids:
        if pid not in pool:
            pool.append(pid)

def generer_offre_boutique(partie, niveau_joueur, ancienne_offre=None, locked=False):
    if locked and ancienne_offre:
        return ancienne_offre
    if ancienne_offre:
        retourner_au_pool(partie, [p["id"] for p in ancienne_offre])
    pokes = piocher_depuis_pool(partie, niveau_joueur)
    return [{"id": p["id"], "nom": p["nom"], "types": p["types"], "niveau": p["niveau"]} for p in pokes]

# ── État joueur ───────────────────────────────────────────────────────────────
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
        "en_vie":          True,
        "a_achete_tour1":  False,
        "boutique_offre":  [],
        "boutique_locked": False,
    }

# ── Économie ──────────────────────────────────────────────────────────────────
def calculer_bonus_serie(joueur):
    serie = max(joueur.get("serie_vic", 0), joueur.get("serie_def", 0))
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

# ── Synergies ─────────────────────────────────────────────────────────────────
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
            poke["pv"]     = min(poke.get("pv", 100) + diff, poke["pv_max"])
            poke["bonus_pv_synergie"] = meilleur

# ── Combat ────────────────────────────────────────────────────────────────────
def points_force(poke):
    """Points de force de base : dégâts directs et durée de soin au Centre."""
    niv = poke.get("niveau", 1)
    if niv <= 3:   return 1
    elif niv <= 6: return 2
    elif niv <= 9: return 3
    else:          return 4

def calculer_degats(attaquant, defenseur, type_attaque=None):
    """
    Calcule les dégâts. Le type utilisé est :
      1. type_attaque (type de l'attaque spécifique, ex: att_off_type)
      2. sinon les types du Pokémon attaquant
    """
    degats_base  = attaquant.get("degats", 20)
    # Priorité : type de l'attaque > types du Pokémon
    if type_attaque:
        types_att = [type_attaque]
    else:
        types_att = attaquant.get("types", [])
    faiblesses   = defenseur.get("faiblesses", [])
    resistances  = defenseur.get("resistances", [])
    immunites    = defenseur.get("immunites", [])

    multiplicateur = 1.0
    for t in types_att:
        t_low = t.lower()
        if t_low in [x.lower() for x in immunites]:
            return 0, "immunité"
        if t_low in [x.lower() for x in faiblesses]:
            multiplicateur = max(multiplicateur, 2.0)
        elif t_low in [x.lower() for x in resistances]:
            multiplicateur = min(multiplicateur, 0.5)

    degats_final = int(degats_base * multiplicateur)
    if multiplicateur >= 2.0:   effet = "super efficace"
    elif multiplicateur <= 0.5: effet = "pas très efficace"
    else:                       effet = "normal"
    return degats_final, effet

def resoudre_duel_complet(partie, p1, j1, p2, j2):
    equipe1 = [p for p in j1.get("pokemon", []) if p["position"] in ("off", "def") and not p.get("ko")]
    equipe2 = [p for p in j2.get("pokemon", []) if p["position"] in ("off", "def") and not p.get("ko")]

    logs = [f"⚔️ {p1} vs {p2}"]
    pts1, pts2 = 0, 0

    # Appariement miroir : slot s de j1 affronte slot (4-s) de j2
    slots1 = {p["slot"]: p for p in equipe1}
    slots2 = {p["slot"]: p for p in equipe2}
    paires, apparies1, apparies2 = [], set(), set()
    for s in range(5):
        a = slots1.get(s)
        b = slots2.get(4 - s)
        if a and b and id(a) not in apparies1 and id(b) not in apparies2:
            paires.append((a, b))
            apparies1.add(id(a))
            apparies2.add(id(b))

    sans_adv1 = [p for p in equipe1 if id(p) not in apparies1]
    sans_adv2 = [p for p in equipe2 if id(p) not in apparies2]

    for (a, b) in paires:
        logs.append(f"  🔸 {a['nom']} (⚡{a.get('vitesse',50)}, {a.get('pv',0)}PV)"
                    f" vs {b['nom']} (⚡{b.get('vitesse',50)}, {b.get('pv',0)}PV)")
        premier, second = (a, b) if a.get("vitesse", 50) >= b.get("vitesse", 50) else (b, a)

        type_att1 = premier.get("att_off_type")
        dmg1, eff1 = calculer_degats(premier, second, type_attaque=type_att1)
        second["pv"] = max(0, second.get("pv", 0) - dmg1)
        logs.append(f"    ➤ {premier['nom']} attaque ({eff1}) → {dmg1} dégâts → {second['nom']} {second['pv']}PV")

        if second["pv"] > 0:
            type_att2 = second.get("att_off_type")
            dmg2, eff2 = calculer_degats(second, premier, type_attaque=type_att2)
            premier["pv"] = max(0, premier.get("pv", 0) - dmg2)
            logs.append(f"    ➤ {second['nom']} riposte ({eff2}) → {dmg2} dégâts → {premier['nom']} {premier['pv']}PV")

        for poke in [a, b]:
            if poke["pv"] <= 0 and not poke.get("ko"):
                poke["ko"] = True
                poke["pv"] = 0
                logs.append(f"    💀 {poke['nom']} est KO !")
                equipe_adv  = equipe2 if poke in equipe1 else equipe1
                slot_miroir = 4 - poke["slot"]
                vainqueur   = next((x for x in equipe_adv if x["slot"] == slot_miroir), None)
                if poke in equipe1: pts2 += 1
                else:               pts1 += 1
                if vainqueur:
                    vainqueur["xp_combats"] = vainqueur.get("xp_combats", 0) + 1
                    xp = vainqueur["xp_combats"]
                    evol_ko = vainqueur.get("evolution_ko")
                    logs.append(f"    ⭐ {vainqueur['nom']} gagne 1 XP combat !" +
                                (f" ({xp}/{evol_ko} KO)" if evol_ko else ""))

    # Dégâts directs
    degats_directs_j1, degats_directs_j2 = 0, 0
    for poke in sans_adv1:
        dmg = points_force(poke)
        degats_directs_j2 += dmg
        logs.append(f"  💥 {poke['nom']} sans adversaire → {dmg} dégâts directs à {p2}")
    for poke in sans_adv2:
        dmg = points_force(poke)
        degats_directs_j1 += dmg
        logs.append(f"  💥 {poke['nom']} sans adversaire → {dmg} dégâts directs à {p1}")

    # Résultat KO
    if pts1 > pts2:
        ecart = pts1 - pts2
        j2["pv"] = max(0, j2["pv"] - ecart)
        j1["serie_vic"] = j1.get("serie_vic", 0) + 1; j1["serie_def"] = 0
        j2["serie_def"] = j2.get("serie_def", 0) + 1; j2["serie_vic"] = 0
        gagnant, perdant = p1, p2
        logs.append(f"🏆 {p1} gagne ! ({pts1} KO vs {pts2}) → {p2} perd {ecart} PV → {j2['pv']} PV")
    elif pts2 > pts1:
        ecart = pts2 - pts1
        j1["pv"] = max(0, j1["pv"] - ecart)
        j2["serie_vic"] = j2.get("serie_vic", 0) + 1; j2["serie_def"] = 0
        j1["serie_def"] = j1.get("serie_def", 0) + 1; j1["serie_vic"] = 0
        gagnant, perdant = p2, p1
        logs.append(f"🏆 {p2} gagne ! ({pts2} KO vs {pts1}) → {p1} perd {ecart} PV → {j1['pv']} PV")
    else:
        gagnant, perdant = None, None
        logs.append(f"🤝 Égalité ! ({pts1} KO chacun)")

    if degats_directs_j2 > 0:
        j2["pv"] = max(0, j2["pv"] - degats_directs_j2)
        logs.append(f"💢 {p2} subit {degats_directs_j2} dégâts directs → {j2['pv']} PV")
    if degats_directs_j1 > 0:
        j1["pv"] = max(0, j1["pv"] - degats_directs_j1)
        logs.append(f"💢 {p1} subit {degats_directs_j1} dégâts directs → {j1['pv']} PV")

    # Éliminations
    for pseudo_check, joueur_check in [(p1, j1), (p2, j2)]:
        if joueur_check["pv"] <= 0:
            joueur_check["en_vie"] = False
            logs.append(f"💀 {pseudo_check} est éliminé !")

    # KO offensif → défensif de la même colonne avance
    for joueur_check in [j1, j2]:
        for poke in list(joueur_check.get("pokemon", [])):
            if poke.get("ko") and poke["position"] == "off":
                defensif = next((p for p in joueur_check["pokemon"]
                                 if p["position"] == "def" and p["slot"] == poke["slot"]
                                 and not p.get("ko")), None)
                if defensif:
                    defensif["position"] = "off"
                    logs.append(f"  ↑ {defensif['nom']} avance en position offensive (col. {poke['slot']})")

    # Remettre les KO au banc
    for joueur_check in [j1, j2]:
        for poke in list(joueur_check.get("pokemon", [])):
            if poke.get("ko") and poke["position"] in ("off", "def"):
                slots_banc = {p["slot"] for p in joueur_check["pokemon"] if p["position"] == "banc"}
                slot_libre = next((i for i in range(10) if i not in slots_banc), None)
                if slot_libre is not None:
                    poke["position"] = "banc"
                    poke["slot"]     = slot_libre

    # Évolutions post-combat
    for pseudo_check, joueur_check in [(p1, j1), (p2, j2)]:
        for msg in verifier_evolutions(partie, joueur_check):
            logs.append(f"[{pseudo_check}] {msg}")

    return {
        "type_duel": "normal",
        "joueurs":   [p1, p2],
        "pts":       [pts1, pts2],
        "gagnant":   gagnant,
        "perdant":   perdant,
        "logs":      logs,
        "pv_apres":  {p1: j1["pv"], p2: j2["pv"]},
    }

def resoudre_duel_ghost(partie, pseudo, joueur):
    return {
        "type_duel": "ghost",
        "joueurs":  [pseudo],
        "pts":      [0],
        "gagnant":  None,
        "perdant":  None,
        "logs":     [f"👻 {pseudo} n'a pas d'adversaire ce tour — aucun dégât reçu"],
        "pv_apres": {pseudo: joueur["pv"]},
    }

def faire_evoluer(partie, joueur, poke):
    if poke.get("ko"):
        return False, ""
    evol_id  = poke.get("evolution_id")
    evol_nom = poke.get("evolution_nom")
    evol_ko  = poke.get("evolution_ko")
    if not evol_id or evol_ko is None:
        return False, ""
    if poke.get("xp_combats", 0) < evol_ko:
        return False, ""
    evol_data = _get_poke(evol_id)
    if not evol_data:
        return False, ""

    ancien_nom    = poke["nom"]
    ancien_pv_max = poke.get("pv_max", 100)
    nouveau_pv_max = evol_data.get("pv_max", 100)
    diff_pv = max(0, nouveau_pv_max - ancien_pv_max)

    poke.update({
        "id":           evol_data["id"],
        "nom":          evol_data["nom"],
        "types":        evol_data.get("types", poke["types"]),
        "niveau":       evol_data.get("niveau", poke["niveau"]),
        "stade":        evol_data.get("stade", poke["stade"]),
        "pv_max":       nouveau_pv_max,
        "pv":           min(poke.get("pv", nouveau_pv_max) + diff_pv, nouveau_pv_max),
        "vitesse":      evol_data.get("vitesse", poke.get("vitesse", 50)),
        "degats":       evol_data.get("degats", poke.get("degats", 20)),
        "faiblesses":   evol_data.get("faiblesses", []),
        "resistances":  evol_data.get("resistances", []),
        "immunites":    evol_data.get("immunites", []),
        "att_off_nom":  evol_data.get("att_off_nom", ""),
        "att_off_desc": evol_data.get("att_off_desc", ""),
        "att_def_nom":  evol_data.get("att_def_nom", ""),
        "att_def_desc": evol_data.get("att_def_desc", ""),
        "att_off_type": evol_data.get("att_off_type"),
        "att_def_type": evol_data.get("att_def_type"),
        "evolution_id":  evol_data.get("evolution_id"),
        "evolution_nom": evol_data.get("evolution_nom"),
        "evolution_ko":  evol_data.get("evolution_ko"),
        "xp_combats":   0,
    })
    appliquer_bonus_pv_synergies(joueur)
    return True, f"🌟 {ancien_nom} évolue en {evol_nom} ! (+{diff_pv} PV → {poke['pv']}/{nouveau_pv_max})"

def verifier_evolutions(partie, joueur):
    messages = []
    for poke in joueur.get("pokemon", []):
        ok, msg = faire_evoluer(partie, joueur, poke)
        if ok:
            messages.append(msg)
    return messages

def lancer_combat(partie):
    joueurs_actifs = {p: j for p, j in partie["joueurs"].items() if j.get("en_vie", True)}
    pseudos = list(joueurs_actifs.keys())
    random.shuffle(pseudos)
    paires, resultats = [], []
    while len(pseudos) >= 2:
        paires.append((pseudos.pop(), pseudos.pop()))
    solo = pseudos[0] if pseudos else None
    for (p1, p2) in paires:
        resultats.append(resoudre_duel_complet(partie, p1, joueurs_actifs[p1], p2, joueurs_actifs[p2]))
    if solo:
        resultats.append(resoudre_duel_ghost(partie, solo, joueurs_actifs[solo]))
    return resultats

def appliquer_fin_tour(partie):
    """Pièces, XP, synergies, Centre Pokémon, nouvelles boutiques."""
    partie["tour"] += 1
    messages = []
    for pj, j in partie["joueurs"].items():
        if not j.get("en_vie", True):
            continue
        niveau   = j["niveau"]
        interets = calculer_interets(j["pieces"])
        serie    = calculer_bonus_serie(j)
        gain     = niveau + interets + serie
        j["pieces"] += gain
        detail = f"+{niveau} niv."
        if serie > 0:    detail += f" +{serie} série"
        if interets > 0: detail += f" +{interets} intérêts"
        messages.append(f"💰 {pj} +{gain} ({detail})")
        messages.extend(appliquer_xp(j, xp_gagnes=1))
        appliquer_bonus_pv_synergies(j)
        # Centre Pokémon
        poke_centre = next((p for p in j.get("pokemon", []) if p["position"] == "centre"), None)
        if poke_centre:
            tours = poke_centre.get("soin_tours_restants", 1) - 1
            poke_centre["soin_tours_restants"] = tours
            if tours <= 0:
                poke_centre["pv"]       = poke_centre.get("pv_max", 100)
                poke_centre["position"] = "banc"
                slots_banc = {p["slot"] for p in j.get("pokemon", []) if p["position"] == "banc"}
                poke_centre["slot"] = next((i for i in range(10) if i not in slots_banc), 0)
                poke_centre.pop("soin_tours_restants", None)
                messages.append(f"💊 {poke_centre['nom']} de {pj} est soigné !")
        locked = j.get("boutique_locked", False)
        j["boutique_offre"]  = generer_offre_boutique(partie, j["niveau"],
                                                       ancienne_offre=j["boutique_offre"], locked=locked)
        j["boutique_locked"] = False
        j["a_achete_tour1"]  = False
    return messages

# ── WebSocket ─────────────────────────────────────────────────────────────────
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

    def _nettoyer(self, obj):
        if isinstance(obj, dict):
            return {k: self._nettoyer(v) for k, v in obj.items()}
        elif isinstance(obj, (set, frozenset)):
            return list(obj)
        elif isinstance(obj, list):
            return [self._nettoyer(i) for i in obj]
        return obj

    async def diffuser(self, code, message):
        if code not in self.connexions:
            return
        morts = []
        msg_clean = self._nettoyer(message)
        for pseudo, ws in self.connexions[code].items():
            try:    await ws.send_json(msg_clean)
            except: morts.append(pseudo)
        for p in morts:
            self.connexions[code].pop(p, None)

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
        if code not in parties:
            return code

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
    if code not in parties:
        return {"erreur": "Partie introuvable"}
    return parties[code]

# ── WebSocket endpoint ────────────────────────────────────────────────────────
@app.websocket("/ws/{code}/{pseudo}")
async def websocket_endpoint(ws: WebSocket, code: str, pseudo: str):
    await gestionnaire.connecter(code, pseudo, ws)
    partie = parties.get(code, {})

    await gestionnaire.diffuser(code, {
        "type": "joueur_connecte", "pseudo": pseudo, "etat": partie,
    })

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

# ── Actions WebSocket ─────────────────────────────────────────────────────────
async def traiter_action(code, pseudo, action):
    if code not in parties:
        return
    partie = parties[code]
    joueur = partie["joueurs"].get(pseudo)
    if not joueur:
        return
    t = action.get("type")

    if t == "demander_boutique":
        offre = joueur.get("boutique_offre") or generer_offre_boutique(partie, joueur["niveau"])
        joueur["boutique_offre"] = offre
        await gestionnaire.envoyer_a(code, pseudo, {
            "type": "boutique_offre", "pour": pseudo,
            "offre": offre, "tour": partie["tour"],
            "tour1_gratuit": partie["tour"] <= 1,
        })

    elif t == "roll":
        if joueur["pieces"] >= 2:
            joueur["pieces"] -= 2
            joueur["boutique_offre"] = generer_offre_boutique(
                partie, joueur["niveau"], ancienne_offre=joueur["boutique_offre"])
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "boutique_offre", "pour": pseudo,
                "offre": joueur["boutique_offre"], "tour": partie["tour"],
                "tour1_gratuit": partie["tour"] <= 1,
            })
            await gestionnaire.diffuser(code, {"type": "etat_mis_a_jour", "etat": partie,
                                               "msg": f"🎲 {pseudo} reroll"})
        else:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Pas assez de pièces !", "pour": pseudo})

    elif t == "lock_boutique":
        joueur["boutique_locked"] = action.get("locked", False)

    elif t == "acheter_xp":
        if joueur["pieces"] >= 4 and joueur["niveau"] < 10:
            joueur["pieces"] -= 4
            msgs = appliquer_xp(joueur, xp_gagnes=2)
            msg = f"📈 {pseudo} achète 2 XP"
            if msgs: msg += " — " + " ".join(msgs)
            await gestionnaire.diffuser(code, {"type": "etat_mis_a_jour", "etat": partie, "msg": msg})
        else:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Pas assez de pièces ou niveau max !", "pour": pseudo})

    elif t == "capturer_pokemon":
        pokemon_id = str(action.get("pokemon_id", ""))
        cout       = action.get("cout", 0)
        gratuit    = partie["tour"] <= 1 and not joueur.get("a_achete_tour1")

        if not gratuit and joueur["pieces"] < cout:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Pas assez de pièces !", "pour": pseudo})
            return

        if gratuit:
            joueur["a_achete_tour1"] = True
        else:
            joueur["pieces"] -= cout

        joueur["boutique_offre"] = [p for p in joueur.get("boutique_offre", []) if p["id"] != pokemon_id]

        poke_data = _get_poke(pokemon_id)
        if not poke_data:
            return
        slots_banc = {p["slot"] for p in joueur["pokemon"] if p["position"] == "banc"}
        slot_libre = next((i for i in range(10) if i not in slots_banc), None)
        if slot_libre is None:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Banc plein !", "pour": pseudo})
            return

        joueur["pokemon"].append({
            "id":           poke_data["id"],
            "nom":          poke_data["nom"],
            "position":     "banc",
            "slot":         slot_libre,
            "niveau":       poke_data["niveau"],
            "stade":        poke_data.get("stade", 0),
            "pv":           poke_data.get("pv_max", 100),
            "pv_max":       poke_data.get("pv_max", 100),
            "vitesse":      poke_data.get("vitesse", 50),
            "degats":       poke_data.get("degats", 20),
            "types":        poke_data.get("types", []),
            "faiblesses":   poke_data.get("faiblesses", []),
            "resistances":  poke_data.get("resistances", []),
            "immunites":    poke_data.get("immunites", []),
            "att_off_nom":  poke_data.get("att_off_nom", ""),
            "att_off_desc": poke_data.get("att_off_desc", ""),
            "att_def_nom":  poke_data.get("att_def_nom", ""),
            "att_def_desc": poke_data.get("att_def_desc", ""),
            "att_off_type": poke_data.get("att_off_type"),
            "att_def_type": poke_data.get("att_def_type"),
            "evolution_id":  poke_data.get("evolution_id"),
            "evolution_nom": poke_data.get("evolution_nom"),
            "evolution_ko":  poke_data.get("evolution_ko"),
            "bonus_pv_synergie": 0,
            "ko":            False,
            "xp_combats":    0,
        })
        await gestionnaire.diffuser(code, {
            "type": "etat_mis_a_jour", "etat": partie,
            "msg": f"⚡ {pseudo} capture {poke_data['nom']} !",
        })

    elif t == "vendre_pokemon":
        position = action.get("position")
        slot     = action.get("slot")
        poke = next((p for p in joueur["pokemon"]
                     if p["position"] == position and p["slot"] == slot), None)
        if not poke:
            return
        gain = poke.get("niveau", 1)
        joueur["pokemon"].remove(poke)
        joueur["pieces"] += gain
        retourner_au_pool(partie, [poke["id"]])
        appliquer_bonus_pv_synergies(joueur)
        await gestionnaire.diffuser(code, {
            "type": "etat_mis_a_jour", "etat": partie,
            "msg": f"💸 {pseudo} vend {poke['nom']} (+{gain} 🪙)",
        })

    elif t == "racheter_pokemon":
        position = action.get("position")
        slot     = action.get("slot")
        poke = next((p for p in joueur["pokemon"]
                     if p["position"] == position and p["slot"] == slot), None)
        if not poke or not poke.get("ko"):
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Pokémon introuvable ou non KO !", "pour": pseudo})
            return
        cout = poke.get("niveau", 1)
        if joueur["pieces"] < cout:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": f"Pas assez de pièces ! ({cout} 🪙)", "pour": pseudo})
            return
        joueur["pieces"] -= cout
        poke["ko"] = False
        poke["pv"] = poke.get("pv_max", 100)
        await gestionnaire.diffuser(code, {
            "type": "etat_mis_a_jour", "etat": partie,
            "msg": f"💊 {pseudo} rachète {poke['nom']} (-{cout} 🪙)",
        })

    elif t == "deplacer_pokemon":
        fp, fs = action.get("from_pos"), action.get("from_slot")
        tp, ts = action.get("to_pos"),   action.get("to_slot")
        niveau_joueur = joueur["niveau"]

        if tp in ("off", "def") and (ts == 0 or ts == 4) and niveau_joueur < 5:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Case non disponible à ce niveau !", "pour": pseudo})
            return

        nb_terrain = sum(1 for p in joueur["pokemon"]
                         if p["position"] in ("off", "def") and not p.get("ko")
                         and not (p["position"] == fp and p["slot"] == fs))
        poke_existant = next((p for p in joueur["pokemon"]
                              if p["position"] == tp and p["slot"] == ts), None)
        if tp in ("off", "def") and not poke_existant and nb_terrain >= niveau_joueur:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Terrain plein pour ce niveau !", "pour": pseudo})
            return

        if tp == "def":
            if not any(p["position"] == "off" and p["slot"] == ts for p in joueur["pokemon"]):
                await gestionnaire.envoyer_a(code, pseudo, {
                    "type": "erreur", "msg": "Pas d'offensif dans cette colonne !", "pour": pseudo})
                return

        if tp == "centre":
            if any(p["position"] == "centre" for p in joueur["pokemon"]):
                await gestionnaire.envoyer_a(code, pseudo, {
                    "type": "erreur", "msg": "Le Centre Pokémon est déjà occupé !", "pour": pseudo})
                return
            poke_src = next((p for p in joueur["pokemon"] if p["position"] == fp and p["slot"] == fs), None)
            if poke_src and poke_src.get("ko"):
                await gestionnaire.envoyer_a(code, pseudo, {
                    "type": "erreur", "msg": "Un Pokémon KO ne peut pas aller au Centre !", "pour": pseudo})
                return
            if poke_src and poke_src.get("pv", 0) >= poke_src.get("pv_max", 100):
                await gestionnaire.envoyer_a(code, pseudo, {
                    "type": "erreur", "msg": "Ce Pokémon est déjà à pleine santé !", "pour": pseudo})
                return
            if poke_src:
                poke_src["soin_tours_restants"] = points_force(poke_src)

        poke     = next((p for p in joueur["pokemon"] if p["position"] == fp and p["slot"] == fs), None)
        if not poke:
            return
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

    elif t == "retirer_pokemon":
        position = action.get("position")
        slot     = action.get("slot")
        poke = next((p for p in joueur["pokemon"]
                     if p["position"] == position and p["slot"] == slot), None)
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

    elif t == "lancer_combat":
        if partie.get("hote") != pseudo:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Seul l'hôte peut lancer le combat !", "pour": pseudo})
            return
        partie["phase"] = "combat"
        # Snapshot AVANT le combat pour l'arène animée (PV et positions d'origine)
        import copy
        etat_avant_combat = copy.deepcopy(partie)
        resultats = lancer_combat(partie)
        partie["phase"] = "preparation"

        await gestionnaire.diffuser(code, {
            "type": "resultat_combat",
            "etat_avant": etat_avant_combat,
            "etat": partie,
            "resultats": resultats,
            "tour": partie["tour"],
        })

        messages = appliquer_fin_tour(partie)
        await gestionnaire.diffuser(code, {
            "type": "fin_tour", "etat": partie,
            "msg": f"⏱️ Tour {partie['tour']} — " + " | ".join(messages),
        })
        for pj, j in partie["joueurs"].items():
            await gestionnaire.envoyer_a(code, pj, {
                "type": "boutique_offre", "pour": pj,
                "offre": j["boutique_offre"],
                "tour": partie["tour"],
                "tour1_gratuit": partie["tour"] <= 1,
                "auto": True,
            })
