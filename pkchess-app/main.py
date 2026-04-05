from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from fastapi.staticfiles import StaticFiles
import asyncio
import time
import json, random, string, os

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

async def nettoyer_parties_inactives():
    """Supprime les parties sans activité depuis 15 minutes."""
    while True:
        await asyncio.sleep(60)
        maintenant = time.time()
        codes_a_supprimer = [
            code for code, partie in list(parties.items())
            if maintenant - partie.get("derniere_activite", maintenant) > 900
        ]
        for code in codes_a_supprimer:
            parties.pop(code, None)
            gestionnaire.connexions.pop(code, None)
            print(f"[NETTOYAGE] Partie {code} supprimée (inactivité 15min)")

@app.on_event("startup")
async def demarrage():
    asyncio.create_task(nettoyer_parties_inactives())
templates = Jinja2Templates(directory="templates")

# ── Base Pokémon ──────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pokemons_db.json")
with open(DB_PATH, encoding="utf-8") as f:
    POKEMONS_DB = json.load(f)

def _get_poke(pid):
    return next((p for p in POKEMONS_DB if p["id"] == pid), None)

# IDs qui sont des formes intermédiaires (cibles d'évolution) → exclues du pool
_IDS_INTERMEDIAIRES = {p["evolution_id"] for p in POKEMONS_DB if p.get("evolution_id")}
# Formes intermédiaires dont le lien d'entrée est absent dans la DB
_IDS_INTERMEDIAIRES |= {"0266"}  # Armulys
_IDS_INTERMEDIAIRES |= {"0292"}  # Munja (obtenu avec Ninjask, pas un Pokémon de base)

# Pokémon exclus du pool boutique (cas spéciaux)
_EXCLUS_POOL = {
    "0266",   # Armulys
    "0292",   # Munja
    "0052d",  # Miaouss Gigamax (forme spéciale, pas disponible en boutique)
    "0412b",  # Cheniti Déchet (forme conditionnelle)
    "0412c",  # Cheniti Sable (forme conditionnelle)
    "0412d",  # Cheniti Plante (forme conditionnelle)
    "0351b",  # Morpheo Blizzard (forme climat uniquement)
    "0351c",  # Morpheo Pluie (forme climat uniquement)
    "0351d",  # Morpheo Solaire (forme climat uniquement)
}

# Mapping synergie → évolition d'Évoli (palier 6 requis)
EVOLITIONS_MAP = {
    "insecte":   "0133c",  "dragon":    "0133d",  "vol":       "0133e",
    "acier":     "0133f",  "normal":    "0133g",  "nucleaire": "0133h",
    "roche":     "0133i",  "sol":       "0133j",  "spectre":   "0133k",
    "poison":    "0133l",  "combat":    "0133m",  "eau":       "0134",
    "electrik":  "0135",   "feu":       "0136",   "psy":       "0196",
    "tenebres":  "0197",   "plante":    "0470",   "glace":     "0471",
    "fee":       "0700",
}

# Pool de cartes Climat
NOMS_CLIMATS_SPECIAUX = [
    "Brouillard", "Canicule", "Distorsion", "Grêle", "Nuageux",
    "Nuit", "Nuée", "Orage", "Pluie", "Smog",
    "Tempête", "Tempête de Sable", "Vent"
]

# Correspondance nom → fichier image
CLIMAT_IMG = {
    "Ensoleillé":       "C-Ensoleille",
    "Brouillard":       "C-Brouillard",
    "Canicule":         "C-Canicule",
    "Distorsion":       "C-Distorsion",
    "Grêle":            "C-Grele",
    "Nuageux":          "C-Nuageux",
    "Nuit":             "C-Nuit",
    "Nuée":             "C-Nuee",
    "Orage":            "C-Orage",
    "Pluie":            "C-Pluie",
    "Smog":             "C-Smog",
    "Tempête":          "C-Tempete",
    "Tempête de Sable": "C-Tempete_de_Sable",
    "Vent":             "C-Vent",
}

def init_pool_climat():
    """Crée un pool de 26 cartes climat : 13x Ensoleillé + 13 spéciaux."""
    pool = ["Ensoleillé"] * 13 + list(NOMS_CLIMATS_SPECIAUX)
    random.shuffle(pool)
    return pool

def piocher_climat(partie):
    """Pioche le prochain climat du pool. Régénère si vide."""
    pool = partie.get("pool_climat", [])
    if not pool:
        pool = init_pool_climat()
    climat = pool.pop(0)
    partie["pool_climat"] = pool
    partie["climat_actuel"] = climat
    return climat

def _calculer_formes_exclusives():
    import re as _re
    from collections import defaultdict as _dd
    groupes = _dd(list)
    for p in POKEMONS_DB:
        base = _re.match(r"^(\d+)", p["id"])
        if base:
            groupes[base.group(1)].append(p)
    exclus = set()
    for base_num, membres in groupes.items():
        stade0 = [p for p in membres if p.get("stade", 0) == 0]
        if len(stade0) <= 1:
            continue
        base_id    = base_num.zfill(4)
        forme_base = next((p for p in stade0 if p["id"] == base_id), None)
        variantes  = [p for p in stade0 if p["id"] != base_id]
        if not forme_base or not variantes:
            continue
        evols = [p.get("evolution_id") for p in variantes if p.get("evolution_id")]
        if not forme_base.get("evolution_id") and evols:
            for p in variantes:
                exclus.add(p["id"])
    return exclus

_IDS_INTERMEDIAIRES |= _calculer_formes_exclusives()

# Formes Méga et Gigamax : jamais disponibles en boutique
import unicodedata as _ud
def _norm(s): return _ud.normalize("NFD", s).encode("ascii","ignore").decode().lower()
_IDS_INTERMEDIAIRES |= {
    p["id"] for p in POKEMONS_DB
    if any(x in _norm(p["nom"]) for x in ("gigamax", "mega")) and p.get("stade", 0) == 0
}

# ── Constantes ────────────────────────────────────────────────────────────────
BONUS_SERIE       = [0, 0, 1, 1, 2, 3]
XP_PAR_NIVEAU     = [0, 1, 1, 2, 4, 8, 16, 24, 32, 40]
BONUS_PV_SYNERGIE = {3: 10, 6: 20, 9: 40}

# ── Attaques qui ne peuvent pas échouer ───────────────────────────────────────
ATTAQUES_NE_PEUVENT_ECHOUER = {
    "Aéropique", "Voix Enjoleuse", "Bombaimant", "Oeil Miracle",
    "Vérouillage", "Verrou Tactique",
}

# ── Effets des attaques ───────────────────────────────────────────────────────
def _support_adverse(cible, equipe_adverse):
    """Retourne le Pokémon défensif adverse dans la même colonne que cible."""
    return next((p for p in equipe_adverse
                 if p["slot"] == cible["slot"]
                 and p["position"] == "def"
                 and not p.get("ko")), None)

def _appliquer_degats_support(cible, equipe_adverse, dmg, type_att, logs):
    """Inflige des dégâts au support adverse (Damoclès, Lumière du Néant...)."""
    support = _support_adverse(cible, equipe_adverse)
    if support:
        support["pv"] = max(0, support.get("pv", 0) - dmg)
        logs.append(f"    💥 Support {support['nom']} subit {dmg} dégâts !")
        return support
    return None

def _jet_de(seuil, logs, nom, desc=""):
    """Lance un dé, retourne True si >= seuil."""
    de = random.randint(1, 6)
    ok = de >= seuil
    if desc:
        logs.append(f"    🎲 {nom} {desc} (dé: {de}, besoin: {seuil}+) → {'✅' if ok else '❌'}")
    return ok

def appliquer_effet_attaque(pokemon, cible, joueur_att, joueur_def,
                             equipe_att, equipe_adv, equipe_propre,
                             mode, logs, partie):
    """
    Applique l'effet de l'attaque offensive (mode='off') ou défensive (mode='def').
    Retourne la nouvelle cible si elle a changé, sinon None.
    """
    if mode == "off":
        nom_att = pokemon.get("att_off_nom", "")
    else:
        nom_att = pokemon.get("att_def_nom", "")

    if not nom_att:
        return None

    niv = pokemon.get("niveau", 1)
    X   = valeur_x(niv)
    Y   = valeur_y(niv)
    nom = pokemon["nom"]

    # Helper : cibles des 2 Pokémon adverses de la colonne
    def _cibles_colonne():
        col = cible.get("slot")
        return [p for p in equipe_adv if p.get("slot") == col and not p.get("ko")]

    # ── BONUS DÉFENSE (Pokemon offensif) ──────────────────────────────────
    if nom_att in {"Acidarmure", "Armure", "Armure (Normale)", "Coquille", "Bouclier",
                   "Repli Tactique", "Fortification", "Abri Rocheux", "Barrage"}:
        appliquer_bonus(pokemon, "bonus_defense", X)
        logs.append(f"    🛡️ {nom} [{nom_att}] : +{X} Bonus Défense")

    # ── BONUS DÉFENSE (Pokemon offensif allié) ────────────────────────────
    elif nom_att in {"Coup d'Main"}:
        # Augmente dégâts du pokemon offensif allié (si att_def)
        if mode == "def":
            appliquer_bonus(pokemon, "bonus_attaque", X)
            logs.append(f"    ⚔️ {nom} [{nom_att}] : Pokemon offensif +{X} dégâts ce tour")

    # ── MALUS DÉFENSE adverse ─────────────────────────────────────────────
    elif nom_att in {"Acide Malique", "Assaut Frontal", "Griffe", "Guillotine Mentale",
                     "Morsure Acide", "Rugissement", "Mimi-Queue", "Criaillerie",
                     "Chant Triste", "Queue de Fer", "Tranche-Vent", "Onde de Choc"}:
        appliquer_bonus(cible, "bonus_defense", -X)
        logs.append(f"    📉 {nom} [{nom_att}] : {cible['nom']} -{X} Bonus Défense")

    # ── MALUS DÉFENSE + dé ────────────────────────────────────────────────
    elif nom_att in {"Acide", "Aqua-Brèche", "Aqua-Bréche"}:
        if _jet_de(6, logs, nom, f"[{nom_att}] tente réduction défense"):
            appliquer_bonus(cible, "bonus_defense", -X)
            logs.append(f"    📉 {nom} [{nom_att}] : {cible['nom']} -{X} Bonus Défense")

    # ── BOOST ATTAQUE ─────────────────────────────────────────────────────
    elif nom_att in {"Aiguisage", "Tranche", "Lame d'Acier", "Danse Lames",
                     "Boost", "Concentration", "Jackpot", "Coup d'Boue",
                     "Griffe Acier", "Taillade"}:
        compteur_key = f"_taillade_compteur" if nom_att == "Taillade" else None
        if compteur_key:
            cnt = pokemon.get(compteur_key, 0)
            if cnt < 3:
                pokemon[compteur_key] = cnt + 1
                appliquer_bonus(pokemon, "bonus_attaque", (cnt + 1) * 10)
                logs.append(f"    ⚔️ {nom} [{nom_att}] : +{(cnt+1)*10} dégâts cumulés (tour {cnt+1}/3)")
        else:
            appliquer_bonus(pokemon, "bonus_attaque", X)
            logs.append(f"    ⚔️ {nom} [{nom_att}] : +{X} Bonus Attaque")

    # ── ROULADE ───────────────────────────────────────────────────────────
    elif nom_att == "Roulade":
        cnt = pokemon.get("_roulade_compteur", 0)
        if cnt < 3:
            pokemon["_roulade_compteur"] = cnt + 1
            appliquer_bonus(pokemon, "bonus_attaque", (cnt + 1) * 10)
            logs.append(f"    🎳 {nom} [Roulade] : +{(cnt+1)*10} dégâts (tour {cnt+1}/3)")
        # Ne peut pas retourner en support
        pokemon["_roulade_actif"] = True

    # ── BOOST VITESSE ─────────────────────────────────────────────────────
    elif nom_att in {"Changement Vitesse", "Danse Draco", "Allégement", "Agilité",
                     "Trempette Turbo", "Accélération"}:
        appliquer_bonus(pokemon, "bonus_vitesse", X)
        pokemon["vitesse"] = pokemon.get("vitesse", 50) + X
        logs.append(f"    💨 {nom} [{nom_att}] : +{X} Vitesse")

    # ── MALUS VITESSE adverse ─────────────────────────────────────────────
    elif nom_att in {"Balayette", "Bulles d'O", "Goudronnage", "Fil Toxique",
                     "Entrave Sable", "Ralentissement"}:
        appliquer_bonus(cible, "bonus_vitesse", -X)
        cible["vitesse"] = max(5, cible.get("vitesse", 50) - X)
        logs.append(f"    🐢 {nom} [{nom_att}] : {cible['nom']} -{X} Vitesse")

    # ── SOIN ──────────────────────────────────────────────────────────────
    elif nom_att in {"Récupération", "Repos", "Soin", "Synthesis", "Synthèse",
                     "Moonlight", "Clair de Lune", "Aromasoin", "Fontaine de Vie",
                     "Sève Salvatrice", "Seve Salvatrice", "Voeu", "Appel Soins",
                     "Anneau Hydro", "Paroi Brume", "Atterrissage"}:
        soin = X
        ancien_pv = pokemon.get("pv", 0)
        pv_max = pokemon.get("pv_max", 100)
        pokemon["pv"] = min(pv_max, ancien_pv + soin)
        logs.append(f"    💚 {nom} [{nom_att}] : +{soin} PV ({ancien_pv}→{pokemon['pv']})")

    # ── STATUT PARALYSIE ──────────────────────────────────────────────────
    elif nom_att in {"Cage Eclair", "Cage Éclair", "Tonnerre", "Coup d'Jus",
                     "Crocs Eclair", "Crocs Éclair", "Stunt Spore",
                     "Para-Spore", "Onde Boréale"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente paralysie"):
            ok, msg = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé !")

    # ── STATUT GEL ────────────────────────────────────────────────────────
    elif nom_att in {"Blizzard", "Laser Glace", "Crocs Givre", "Lyophilisation",
                     "Onde Glace", "Blizzard Poing", "Grêlon"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente gel"):
            ok, msg = appliquer_statut(cible, "FRZ")
            if ok: logs.append(f"    ❄️ {cible['nom']} est gelé !")

    # ── STATUT BRÛLURE ────────────────────────────────────────────────────
    elif nom_att in {"Feu Follet", "Lance-Flamme", "Crocs Feu", "Bec-Canon",
                     "Déflagration", "Flammèche", "Flammeche"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente brûlure"):
            ok, msg = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")

    # ── STATUT POISON ─────────────────────────────────────────────────────
    elif nom_att in {"Gaz Toxik", "Dard-Venin", "Choc Venin", "Bombe Beurk",
                     "Acide", "Fil Toxique", "Poudre Toxik"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente poison"):
            ok, msg = appliquer_statut(cible, "PSN")
            if ok: logs.append(f"    ☠️ {cible['nom']} est empoisonné !")

    # ── STATUT SOMMEIL ────────────────────────────────────────────────────
    elif nom_att in {"Berceuse", "Hypnose", "Grobisou", "Chant Antique",
                     "Chant", "Baillement", "Poudre Dodo"}:
        if not cible.get("statut"):
            ok, msg = appliquer_statut(cible, "SLP")
            if ok: logs.append(f"    😴 {cible['nom']} s'endort !")

    # ── STATUT CONFUSION ──────────────────────────────────────────────────
    elif nom_att in {"Babil", "Danse Folle", "Doux Baiser", "Choc Mental",
                     "Colère", "Onde Psy", "Tourbillon"}:
        if not cible.get("statut"):
            ok, msg = appliquer_statut(cible, "CNF")
            if ok: logs.append(f"    😵 {cible['nom']} est confus !")

    # ── ULTRASON (pièce → confusion, 50% = dé >= 4) ───────────────────────
    elif nom_att == "Ultrason":
        if not cible.get("statut") and _jet_de(4, logs, nom, "[Ultrason] tente confusion"):
            ok, _ = appliquer_statut(cible, "CNF")
            if ok: logs.append(f"    😵 {cible['nom']} est confus !")

    # ── ÉTONNEMENT (dé 5-6 → peur) ────────────────────────────────────────
    elif nom_att in {"Etonnement", "Étonnement"}:
        if not cible.get("peur") and _jet_de(5, logs, nom, "[Étonnement] tente peur"):
            cible["peur"] = True
            logs.append(f"    😨 {cible['nom']} a peur !")

    # ── PEUR ──────────────────────────────────────────────────────────────
    elif nom_att in {"Bluff", "Intimidation", "Rugissement Sombre", "Hurlement Sinistre"}:
        if not cible.get("peur") and cible.get("vitesse", 50) < pokemon.get("vitesse", 50):
            cible["peur"] = True
            logs.append(f"    😨 {cible['nom']} a peur de {nom} !")

    # ── PIÈGE ─────────────────────────────────────────────────────────────
    elif nom_att in {"Claquoir", "Ligotage", "Etreinte", "Étreinte",
                     "Lianes Fouet", "Lianes", "Tentacules", "Dard Venin"}:
        if not cible.get("piege"):
            ok, msg = appliquer_statut(cible, "PIE")
            if ok: logs.append(f"    🔗 {cible['nom']} est piégé !")

    # ── IGNORE DÉFENSE ────────────────────────────────────────────────────
    elif nom_att in {"Affilage", "Choc Psy", "Frappe Psy", "Hyperceuse",
                     "Mépris", "Perce-Armure", "Tranche-Herbe", "Carnareket"}:
        ancien = cible.get("bonus_defense", 0)
        if ancien > 0:
            cible["bonus_defense"] = 0
            logs.append(f"    🗡️ {nom} [{nom_att}] : ignore le Bonus Défense de {cible['nom']}")

    # ── SI ATTAQUE AVANT (+10 dégâts) ─────────────────────────────────────
    elif nom_att in {"Aqua-Jet", "Mach Punch", "Vive-Attaque", "Eclats Glace",
                     "Ombre Portée", "Pisto-Poing", "Vif Roc", "Vif-Roc",
                     "Trépignement"}:
        attaque_avant = pokemon.get("vitesse", 50) > cible.get("vitesse", 50)
        if attaque_avant:
            appliquer_bonus(pokemon, "bonus_attaque", 10)
            logs.append(f"    ⚡ {nom} [{nom_att}] : +10 dégâts (attaque en premier)")

    # ── SI ATTAQUE AVANT (+X dégâts selon niveau) ─────────────────────────
    elif nom_att in {"Boule Elek"}:
        attaque_avant = pokemon.get("vitesse", 50) > cible.get("vitesse", 50)
        if attaque_avant:
            appliquer_bonus(pokemon, "bonus_attaque", X)
            logs.append(f"    ⚡ {nom} [{nom_att}] : +{X} dégâts (attaque en premier)")

    # ── SI ATTAQUE AVANT (double dégâts) ──────────────────────────────────
    elif nom_att in {"Branchicrok", "Prise de Bec"}:
        attaque_avant = pokemon.get("vitesse", 50) > cible.get("vitesse", 50)
        if attaque_avant:
            appliquer_bonus(pokemon, "bonus_attaque", pokemon.get("degats", 20))
            logs.append(f"    ⚡ {nom} [{nom_att}] : dégâts doublés (attaque en premier)")

    # ── SI ATTAQUE AVANT (+10 + peur) ─────────────────────────────────────
    elif nom_att in {"Bluff", "Escarmouche"}:
        attaque_avant = pokemon.get("vitesse", 50) > cible.get("vitesse", 50)
        if attaque_avant:
            appliquer_bonus(pokemon, "bonus_attaque", 10)
            logs.append(f"    ⚡ {nom} [{nom_att}] : +10 dégâts (attaque en premier)")
            if not cible.get("peur") and cible.get("vitesse", 50) < pokemon.get("vitesse", 50):
                cible["peur"] = True
                logs.append(f"    😨 {cible['nom']} a peur !")

    # ── SI ATTAQUE AVANT (bonus défense) ──────────────────────────────────
    elif nom_att == "Sprint Bouclier":
        attaque_avant = pokemon.get("vitesse", 50) > cible.get("vitesse", 50)
        if attaque_avant:
            appliquer_bonus(pokemon, "bonus_defense", 30)
            logs.append(f"    🛡️ {nom} [Sprint Bouclier] : +30 Bonus Défense (attaque en premier)")

    # ── SI ATTAQUE AVANT (+20 dégâts) ─────────────────────────────────────
    elif nom_att == "Trépignement":
        attaque_avant = pokemon.get("vitesse", 50) > cible.get("vitesse", 50)
        if attaque_avant:
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    ⚡ {nom} [Trépignement] : +20 dégâts (attaque en premier)")

    # ── COUP BAS (si avant + cible support) ───────────────────────────────
    elif nom_att == "Coup Bas":
        attaque_avant = pokemon.get("vitesse", 50) > cible.get("vitesse", 50)
        if attaque_avant:
            appliquer_bonus(pokemon, "bonus_attaque", 10)
            support = _support_adverse(cible, equipe_adv)
            if support and not support.get("ko"):
                logs.append(f"    ⚡ {nom} [Coup Bas] : +10 dégâts, cible support {support['nom']}")
                return support
            logs.append(f"    ⚡ {nom} [Coup Bas] : +10 dégâts (attaque en premier)")

    # ── CROCS (statut + peur) ─────────────────────────────────────────────
    elif nom_att in {"Crocs Eclair", "Crocs Éclair"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, "[Crocs Éclair] tente paralysie"):
            ok, _ = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé !")
        if not cible.get("peur") and _jet_de(6, logs, nom, "[Crocs Éclair] tente peur"):
            cible["peur"] = True
            logs.append(f"    😨 {cible['nom']} a peur !")

    elif nom_att in {"Crocs Feu"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, "[Crocs Feu] tente brûlure"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")
        if not cible.get("peur") and _jet_de(6, logs, nom, "[Crocs Feu] tente peur"):
            cible["peur"] = True
            logs.append(f"    😨 {cible['nom']} a peur !")

    elif nom_att in {"Crocs Givre"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, "[Crocs Givre] tente gel"):
            ok, _ = appliquer_statut(cible, "FRZ")
            if ok: logs.append(f"    ❄️ {cible['nom']} est gelé !")
        if not cible.get("peur") and _jet_de(6, logs, nom, "[Crocs Givre] tente peur"):
            cible["peur"] = True
            logs.append(f"    😨 {cible['nom']} a peur !")

    # ── FUREUR ARDENTE (peur + brûlure) ───────────────────────────────────
    elif nom_att == "Fureur Ardente":
        if not cible.get("peur") and _jet_de(5, logs, nom, "[Fureur Ardente] tente peur"):
            cible["peur"] = True
            logs.append(f"    😨 {cible['nom']} a peur !")
        if not cible.get("statut") and _jet_de(5, logs, nom, "[Fureur Ardente] tente brûlure"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")

    # ── GRIFFES FUNESTES (statut variable + dégâts) ───────────────────────
    elif nom_att == "Griffes Funestes":
        if not cible.get("statut"):
            de = random.randint(1, 6)
            if de == 4:
                ok, _ = appliquer_statut(cible, "PSN")
                if ok: logs.append(f"    ☠️ {cible['nom']} est empoisonné ! (dé: {de})")
            elif de == 5:
                ok, _ = appliquer_statut(cible, "PAR")
                if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé ! (dé: {de})")
            elif de == 6:
                ok, _ = appliquer_statut(cible, "SLP")
                if ok: logs.append(f"    😴 {cible['nom']} s'endort ! (dé: {de})")
        if _jet_de(5, logs, nom, "[Griffes Funestes] tente +20 dégâts"):
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    💥 {nom} [Griffes Funestes] : +20 dégâts")

    # ── PIED BRÛLEUR (+20 dégâts + brûlure) ──────────────────────────────
    elif nom_att == "Pied Bruleur":
        if _jet_de(5, logs, nom, "[Pied Brûleur] tente +20 dégâts"):
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    💥 {nom} [Pied Brûleur] : +20 dégâts")
        if not cible.get("statut") and _jet_de(6, logs, nom, "[Pied Brûleur] tente brûlure"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")

    # ── PIQUÉ (peur + dégâts) ─────────────────────────────────────────────
    elif nom_att == "Piqué":
        if not cible.get("peur") and _jet_de(5, logs, nom, "[Piqué] tente peur"):
            cible["peur"] = True
            logs.append(f"    😨 {cible['nom']} a peur !")
        if _jet_de(5, logs, nom, "[Piqué] tente +20 dégâts"):
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    💥 {nom} [Piqué] : +20 dégâts")

    # ── POISON-CROIX (+20 dégâts + poison) ───────────────────────────────
    elif nom_att == "Poison-Croix":
        if _jet_de(5, logs, nom, "[Poison-Croix] tente +20 dégâts"):
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    💥 {nom} [Poison-Croix] : +20 dégâts")
        if not cible.get("statut") and _jet_de(6, logs, nom, "[Poison-Croix] tente poison"):
            ok, _ = appliquer_statut(cible, "PSN")
            if ok: logs.append(f"    ☠️ {cible['nom']} est empoisonné !")

    # ── BALLON BRULANT (brûlure + échange position) ───────────────────────
    elif nom_att == "Ballon Brulant":
        if not cible.get("statut") and _jet_de(5, logs, nom, "[Ballon Brûlant] tente brûlure"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")
        if _jet_de(5, logs, nom, "[Ballon Brûlant] tente échange"):
            support = _support_adverse(cible, equipe_adv)
            if support and not support.get("ko"):
                cible["position"], support["position"] = support["position"], cible["position"]
                logs.append(f"    🔄 {cible['nom']} et {support['nom']} échangent leur position !")

    # ── TUNNEL (cible le support adverse) ─────────────────────────────────
    elif nom_att == "Tunnel":
        support = _support_adverse(cible, equipe_adv)
        if support and not support.get("ko"):
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    🕳️ {nom} [Tunnel] : cible support {support['nom']} +20 dégâts")
            return support

    # ── QUEUE-POISON (dé 5-6 poison + dé 5-6 dégâts sup) ─────────────────
    elif nom_att in {"Queue-Poison", "Queue-Poison (Séviper)"}:
        if not cible.get("statut") and _jet_de(5, logs, nom, "[Queue-Poison] tente poison"):
            ok, _ = appliquer_statut(cible, "PSN")
            if ok: logs.append(f"    ☠️ {cible['nom']} est empoisonné !")
        if _jet_de(5, logs, nom, "[Queue-Poison] tente dégâts sup"):
            appliquer_bonus(pokemon, "bonus_attaque", X)
            logs.append(f"    💥 {nom} [Queue-Poison] : +{X} dégâts supplémentaires")

    # ── PLUMO-QUEUE (dé variable) ──────────────────────────────────────────
    elif nom_att == "Plumo-Queue":
        de = random.randint(1, 6)
        bonus = 0 if de <= 2 else 10 if de <= 4 else 20 if de == 5 else 30
        if bonus:
            appliquer_bonus(pokemon, "bonus_attaque", bonus)
            logs.append(f"    🎲 {nom} [Plumo-Queue] : +{bonus} dégâts (dé: {de})")

    # ── DÉGÂTS SUR SUPPORT ADVERSE ────────────────────────────────────────
    elif nom_att in {"Damoclès", "Lumière du Néant", "Caboche-Kaboum",
                     "Fracass'Tête", "Roc Boulet"}:
        pokemon["_degats_support_actif"] = True

    # ── VOL DE VIE (soin = moitié des dégâts infligés) ────────────────────
    elif nom_att in {"Vol-Vie", "Méga-Sangsue", "Mega-Sangsue", "Giga-Sangsue",
                     "Vampirisme", "Vampibaiser", "Vampipoing",
                     "Encornebois", "Lame en Peine", "Parabocharge"}:
        pokemon["_vol_vie_actif"] = True

    # ── BÉLIER ────────────────────────────────────────────────────────────
    elif nom_att == "Bélier":
        pokemon["_belier_actif"] = True

    # ── ATTAQUES GIGAMAX (10 dégâts à tous les adversaires hors type) ─────
    elif nom_att in {"Canonnade G-Max", "Combustion G-Max", "Fouet G-Max",
                     "Fournaise G-Max", "Enlisement G-Max", "Percée G-Max",
                     "Téphra G-Max", "Récif G-Max"}:
        _type_gmax = {
            "Canonnade G-Max": "eau", "Combustion G-Max": "feu",
            "Fouet G-Max": "plante", "Fournaise G-Max": "feu",
            "Enlisement G-Max": "sol", "Percée G-Max": "acier",
            "Téphra G-Max": "feu", "Récif G-Max": "roche",
        }.get(nom_att, "normal")
        for ennemi in equipe_adv:
            if ennemi.get("ko"):
                continue
            types_ennemi = [_normaliser_type(t) for t in ennemi.get("types", [])]
            if _type_gmax not in types_ennemi:
                ennemi["pv"] = max(0, ennemi.get("pv", 0) - 10)
                logs.append(f"    💥 {nom_att} : {ennemi['nom']} subit 10 dégâts !")

    # ══════════════════════════════════════════════════════════════════════
    # MALUS DÉFENSE ADVERSE
    # ══════════════════════════════════════════════════════════════════════

    # Supprime défense sur dé 6
    elif nom_att in {"Ball'Ombre", "Bourdon", "Eco-Sphère", "Luminocanon",
                     "Psyko", "Telluriforce"}:
        if _jet_de(6, logs, nom, f"[{nom_att}] tente suppression défense"):
            appliquer_bonus(cible, "bonus_defense", -cible.get("bonus_defense", 0) - 999)
            cible["bonus_defense"] = 0
            logs.append(f"    📉 {cible['nom']} : Bonus Défense supprimé !")

    # Supprime défense sur dé 5-6
    elif nom_att in {"Machouille", "Telluriforce"}:
        if _jet_de(5, logs, nom, f"[{nom_att}] tente suppression défense"):
            cible["bonus_defense"] = 0
            logs.append(f"    📉 {cible['nom']} : Bonus Défense supprimé !")

    # Supprime défense sans condition
    elif nom_att in {"Bombe Acide", "Canon Blindé", "Lumino-Impact"}:
        cible["bonus_defense"] = 0
        logs.append(f"    📉 {nom} [{nom_att}] : Bonus Défense supprimé !")

    # Réduit défense de X sans condition
    elif nom_att in {"Groz'Yeux"}:
        appliquer_bonus(cible, "bonus_defense", -X)
        logs.append(f"    📉 {nom} [{nom_att}] : {cible['nom']} -{X} Bonus Défense")

    # Réduit défense de 20 sans condition
    elif nom_att in {"Fouet de Feu"}:
        appliquer_bonus(cible, "bonus_defense", -20)
        logs.append(f"    📉 {nom} [{nom_att}] : {cible['nom']} -20 Bonus Défense")

    # Réduit défense de 30 sans condition
    elif nom_att in {"Coup Fulgurant", "Triple Flèche"}:
        appliquer_bonus(cible, "bonus_defense", -30)
        logs.append(f"    📉 {nom} [{nom_att}] : {cible['nom']} -30 Bonus Défense")

    # Réduit défense via pièce (face = -10)
    elif nom_att == "Coquilame":
        if _jet_de(4, logs, nom, "[Coquilame] tente réduction défense"):
            appliquer_bonus(cible, "bonus_defense", -10)
            logs.append(f"    📉 {cible['nom']} : -10 Bonus Défense")

    # Réduit défense via pièce (face = -50)
    elif nom_att == "Lumi-Eclat":
        if _jet_de(4, logs, nom, "[Lumi-Eclat] tente réduction défense"):
            appliquer_bonus(cible, "bonus_defense", -50)
            logs.append(f"    📉 {cible['nom']} : -50 Bonus Défense")

    # Réduit défense + attaque (Chatouille, Close Combat)
    elif nom_att in {"Chatouille", "Close Combat"}:
        appliquer_bonus(cible, "bonus_defense", -X)
        appliquer_bonus(cible, "bonus_attaque", -X)
        logs.append(f"    📉 {nom} [{nom_att}] : {cible['nom']} -{X} Défense et -{X} Attaque")

    # Réduit défense des 2 Pokemon de la colonne
    elif nom_att in {"Croco Larme", "Strido-Son", "Rafale G-Max"}:
        for c in _cibles_colonne():
            c["bonus_defense"] = 0
            logs.append(f"    📉 {nom} [{nom_att}] : {c['nom']} Bonus Défense supprimé !")

    # Coup Fulgurant : -30 défense + dé 5-6 paralysie
    elif nom_att == "Coup Fulgurant":
        appliquer_bonus(cible, "bonus_defense", -30)
        logs.append(f"    📉 {cible['nom']} : -30 Bonus Défense")
        if not cible.get("statut") and _jet_de(5, logs, nom, "[Coup Fulgurant] tente paralysie"):
            ok, _ = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé !")

    # Malédiction : +X att +X def -X vitesse
    elif nom_att == "Malédiction":
        appliquer_bonus(pokemon, "bonus_attaque", X)
        appliquer_bonus(pokemon, "bonus_defense", X)
        appliquer_bonus(pokemon, "bonus_vitesse", -X)
        pokemon["vitesse"] = max(5, pokemon.get("vitesse", 50) - X)
        logs.append(f"    🔮 {nom} [Malédiction] : +{X} Att, +{X} Déf, -{X} Vit")

    # Habanerage : supprime sa propre défense → ajoute à l'attaque
    elif nom_att == "Habanerage":
        bonus_def = max(0, pokemon.get("bonus_defense", 0))
        pokemon["bonus_defense"] = 0
        appliquer_bonus(pokemon, "bonus_attaque", X + bonus_def)
        logs.append(f"    🌶️ {nom} [Habanerage] : +{X + bonus_def} Attaque (dont {bonus_def} de Déf)")

    # ══════════════════════════════════════════════════════════════════════
    # BOOST ATTAQUE
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att == "Chargeur":
        bonus = X * 2 if attaquant.get("att_off_type", "").lower() == "electrik" else X
        appliquer_bonus(pokemon, "bonus_attaque", bonus)
        logs.append(f"    ⚔️ {nom} [Chargeur] : +{bonus} Attaque")

    # ══════════════════════════════════════════════════════════════════════
    # MALUS ATTAQUE ADVERSE
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Charme", "Feu Ensorcelé"}:
        appliquer_bonus(cible, "bonus_attaque", -X)
        logs.append(f"    📉 {nom} [{nom_att}] : {cible['nom']} -{X} Attaque")

    elif nom_att == "Survinsecte":
        appliquer_bonus(cible, "bonus_attaque", -10)
        logs.append(f"    📉 {cible['nom']} : -10 Attaque")

    elif nom_att in {"Calinerie", "Ondes Boréales"}:
        if _jet_de(6, logs, nom, f"[{nom_att}] tente malus attaque"):
            appliquer_bonus(cible, "bonus_attaque", -X)
            logs.append(f"    📉 {cible['nom']} : -{X} Attaque")

    elif nom_att == "Ball'Brume":
        if _jet_de(4, logs, nom, "[Ball'Brume] tente malus attaque"):
            appliquer_bonus(cible, "bonus_attaque", -50)
            logs.append(f"    📉 {cible['nom']} : -50 Attaque")

    elif nom_att == "Patati-Patattrape":
        if _jet_de(5, logs, nom, "[Patati-Patattrape] tente malus attaque"):
            appliquer_bonus(cible, "bonus_attaque", -30)
            logs.append(f"    📉 {cible['nom']} : -30 Attaque")

    # ══════════════════════════════════════════════════════════════════════
    # BOOST VITESSE
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att == "Danse Draco":
        offensif = next((p for p in equipe_att if p.get("position") == "off"
                        and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_attaque", X)
            appliquer_bonus(offensif, "bonus_vitesse", X)
            offensif["vitesse"] = offensif.get("vitesse", 50) + X
            logs.append(f"    🐉 {nom} [Danse Draco] : {offensif['nom']} +{X} Att/Vit")
            if "dragon" in [_normaliser_type(t) for t in offensif.get("types", [])]:
                appliquer_bonus(pokemon, "bonus_attaque", X)
                appliquer_bonus(pokemon, "bonus_vitesse", X)
                pokemon["vitesse"] = pokemon.get("vitesse", 50) + X
                logs.append(f"    🐉 [Danse Draco] : {nom} reçoit aussi +{X} Att/Vit (offensif Dragon)")

    elif nom_att in {"Hate", "Hâte"}:
        appliquer_bonus(pokemon, "bonus_vitesse", X)
        pokemon["vitesse"] = pokemon.get("vitesse", 50) + X
        logs.append(f"    💨 {nom} [{nom_att}] : +{X} Vitesse")

    elif nom_att == "Nitrocharge":
        appliquer_bonus(pokemon, "bonus_vitesse", 10)
        pokemon["vitesse"] = pokemon.get("vitesse", 50) + 10
        logs.append(f"    💨 {nom} [Nitrocharge] : +10 Vitesse")

    elif nom_att == "Poliroche":
        bonus_vit = X + 10 if "roche" in [_normaliser_type(t) for t in pokemon.get("types", [])] else X
        appliquer_bonus(pokemon, "bonus_vitesse", bonus_vit)
        pokemon["vitesse"] = pokemon.get("vitesse", 50) + bonus_vit
        logs.append(f"    💨 {nom} [Poliroche] : +{bonus_vit} Vitesse")

    elif nom_att == "Roue Libre":
        cnt = pokemon.get("_roue_libre_cnt", 0)
        if cnt < 3:
            pokemon["_roue_libre_cnt"] = cnt + 1
            appliquer_bonus(pokemon, "bonus_vitesse", 20)
            pokemon["vitesse"] = pokemon.get("vitesse", 50) + 20
            logs.append(f"    💨 {nom} [Roue Libre] : +20 Vitesse ({cnt+1}/3)")

    elif nom_att == "Danse Aquatique":
        cnt = pokemon.get("_danse_aq_cnt", 0)
        if cnt < 3:
            pokemon["_danse_aq_cnt"] = cnt + 1
            appliquer_bonus(pokemon, "bonus_vitesse", 10)
            pokemon["vitesse"] = pokemon.get("vitesse", 50) + 10
            logs.append(f"    💨 {nom} [Danse Aquatique] : +10 Vitesse ({cnt+1}/3)")

    elif nom_att == "Papillodance":
        appliquer_bonus(pokemon, "bonus_attaque", X)
        appliquer_bonus(pokemon, "bonus_defense", X)
        appliquer_bonus(pokemon, "bonus_vitesse", X)
        pokemon["vitesse"] = pokemon.get("vitesse", 50) + X
        logs.append(f"    🦋 {nom} [Papillodance] : +{X} Att/Déf/Vit")

    elif nom_att == "Engrenage":
        appliquer_bonus(pokemon, "bonus_attaque", X)
        logs.append(f"    ⚔️ {nom} [Engrenage] : +{X} Attaque")
        if "acier" in [_normaliser_type(t) for t in pokemon.get("types", [])]:
            appliquer_bonus(pokemon, "bonus_vitesse", X)
            pokemon["vitesse"] = pokemon.get("vitesse", 50) + X
            logs.append(f"    💨 {nom} [Engrenage] : +{X} Vitesse (type Acier)")

    elif nom_att == "Aurasphère":
        if _jet_de(5, logs, nom, "[Aurasphère] tente boost vitesse"):
            appliquer_bonus(pokemon, "bonus_vitesse", X)
            pokemon["vitesse"] = pokemon.get("vitesse", 50) + X
            logs.append(f"    💨 {nom} [Aurasphère] : +{X} Vitesse")
        if pokemon.get("pv", 100) < pokemon.get("pv_max", 100) * 0.5:
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    ⚔️ {nom} [Aurasphère] : +20 dégâts (<50% PV)")

    # ══════════════════════════════════════════════════════════════════════
    # MALUS VITESSE ADVERSE
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Dérapage", "Marteau de Glace", "Marto-Poing"}:
        appliquer_bonus(cible, "bonus_vitesse", -40)
        cible["vitesse"] = max(5, cible.get("vitesse", 50) - 40)
        logs.append(f"    🐢 {nom} [{nom_att}] : {cible['nom']} -40 Vitesse")

    elif nom_att in {"Grimace", "Sécrétion"}:
        appliquer_bonus(cible, "bonus_vitesse", -X)
        cible["vitesse"] = max(5, cible.get("vitesse", 50) - X)
        logs.append(f"    🐢 {nom} [{nom_att}] : {cible['nom']} -{X} Vitesse")

    elif nom_att in {"Tir de Boue", "Toile Elek"}:
        appliquer_bonus(cible, "bonus_vitesse", -10)
        cible["vitesse"] = max(5, cible.get("vitesse", 50) - 10)
        logs.append(f"    🐢 {nom} [{nom_att}] : {cible['nom']} -10 Vitesse")

    elif nom_att == "Tomberoche":
        appliquer_bonus(cible, "bonus_vitesse", -20)
        cible["vitesse"] = max(5, cible.get("vitesse", 50) - 20)
        logs.append(f"    🐢 {cible['nom']} : -20 Vitesse")

    elif nom_att == "Tambour Battant":
        appliquer_bonus(cible, "bonus_vitesse", -40)
        cible["vitesse"] = max(5, cible.get("vitesse", 50) - 40)
        logs.append(f"    🐢 {cible['nom']} : -40 Vitesse")

    elif nom_att in {"Bulles d'0", "Bulles d'O"}:
        if _jet_de(6, logs, nom, "[Bulles d'O] tente malus vitesse"):
            appliquer_bonus(cible, "bonus_vitesse", -X)
            cible["vitesse"] = max(5, cible.get("vitesse", 50) - X)
            logs.append(f"    🐢 {cible['nom']} : -{X} Vitesse")

    # Zone malus vitesse
    elif nom_att in {"Piétisol", "Spore Coton"}:
        for c in _cibles_colonne():
            appliquer_bonus(c, "bonus_vitesse", -X if nom_att == "Spore Coton" else -20)
            c["vitesse"] = max(5, c.get("vitesse", 50) - (X if nom_att == "Spore Coton" else 20))
            logs.append(f"    🐢 {c['nom']} : -{X if nom_att == 'Spore Coton' else 20} Vitesse")

    elif nom_att == "Bulles G-Max":
        for c in _cibles_colonne():
            appliquer_bonus(c, "bonus_vitesse", -40)
            c["vitesse"] = max(5, c.get("vitesse", 50) - 40)
            logs.append(f"    🐢 {c['nom']} : -40 Vitesse")

    # ══════════════════════════════════════════════════════════════════════
    # SOINS
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Vibra Soin", "Soin Floral"}:
        soin = X
        pokemon["pv"] = min(pokemon.get("pv_max", 100), pokemon.get("pv", 0) + soin)
        logs.append(f"    💚 {nom} [{nom_att}] : +{soin} PV")

    elif nom_att in {"Aromathérapie", "Glas de Soin", "Régénération"}:
        soigner_statuts(pokemon)
        logs.append(f"    💚 {nom} [{nom_att}] : statut soigné")

    elif nom_att in {"Aria de I'Ecume", "Aria de l'Ecume"}:
        soigner_statuts(pokemon)
        support = next((p for p in equipe_att if p.get("position") == "def"
                       and p.get("slot") == pokemon.get("slot") and not p.get("ko")), None)
        if support:
            soigner_statuts(support)
            logs.append(f"    💚 {nom} : statuts soignés ({pokemon['nom']} + {support['nom']})")
        else:
            logs.append(f"    💚 {nom} : statut soigné")

    elif nom_att in {"Extravaillance"}:
        if pokemon.get("statut"):
            soigner_statuts(pokemon)
            appliquer_bonus(pokemon, "bonus_attaque", X)
            appliquer_bonus(pokemon, "bonus_defense", X)
            logs.append(f"    💚 {nom} [Extravaillance] : statut soigné +{X} Att/Déf")

    elif nom_att in {"Lait a Boire", "Lait à Boire"}:
        degats_pris = pokemon.get("pv_max", 100) - pokemon.get("pv", 0)
        soin = X + degats_pris
        pokemon["pv"] = min(pokemon.get("pv_max", 100), pokemon.get("pv", 0) + soin)
        logs.append(f"    💚 {nom} [Lait à Boire] : +{soin} PV")

    elif nom_att in {"Cure G-Max"}:
        support = next((p for p in equipe_att if p.get("position") == "def"
                       and p.get("slot") == pokemon.get("slot") and not p.get("ko")), None)
        if support:
            support["pv"] = support.get("pv_max", 100)
            logs.append(f"    💚 {support['nom']} soigné intégralement !")

    elif nom_att in {"Nectar G-Max"}:
        for p in equipe_att:
            if p.get("slot") == pokemon.get("slot") and not p.get("ko"):
                soigner_statuts(p)
                logs.append(f"    💚 {p['nom']} : statut soigné")

    elif nom_att == "Paresse":
        soin = X
        pokemon["pv"] = min(pokemon.get("pv_max", 100), pokemon.get("pv", 0) + soin)
        pokemon["_skip_next_combat"] = True
        logs.append(f"    💚 {nom} [Paresse] : +{soin} PV (ne combat pas au prochain tour)")

    elif nom_att == "Racines":
        soin = X
        pokemon["pv"] = min(pokemon.get("pv_max", 100), pokemon.get("pv", 0) + soin)
        pokemon["_racines_actif"] = True
        logs.append(f"    💚 {nom} [Racines] : +{soin} PV (ne peut plus être retiré)")

    elif nom_att in {"Amass'Sable"}:
        soin = X
        pokemon["pv"] = min(pokemon.get("pv_max", 100), pokemon.get("pv", 0) + soin)
        appliquer_bonus(pokemon, "bonus_defense", X)
        logs.append(f"    💚 {nom} [Amass'Sable] : +{soin} PV +{X} Défense")

    # ══════════════════════════════════════════════════════════════════════
    # STATUTS PAR (avec variantes)
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Dracosouffle", "Etincelle", "Fatal-Foudre", "Forte-Paume",
                     "Léchouille", "Plaquage", "Typhon Fulgurant"}:
        if not cible.get("statut") and _jet_de(5, logs, nom, f"[{nom_att}] tente paralysie"):
            ok, _ = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé !")

    elif nom_att in {"Eclair", "Poing Eclair"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente paralysie"):
            ok, _ = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé !")

    elif nom_att in {"Electro-Surf Survolté", "Elécanon", "Frotte-Frimousse",
                     "Regard Médusant"}:
        if not cible.get("statut"):
            ok, _ = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé !")

    elif nom_att == "Charge Foudre":
        if not cible.get("statut") and _jet_de(5, logs, nom, "[Charge Foudre] tente paralysie"):
            ok, _ = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé !")
        support_all = next((p for p in equipe_att if p.get("position") == "def"
                           and p.get("slot") == pokemon.get("slot") and not p.get("ko")), None)
        if support_all and "feu" in [_normaliser_type(t) for t in support_all.get("types", [])]:
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    ⚡ {nom} [Charge Foudre] : +20 dégâts (support Feu)")

    elif nom_att == "Foudre G-Max":
        for c in _cibles_colonne():
            if not c.get("statut"):
                ok, _ = appliquer_statut(c, "PAR")
                if ok: logs.append(f"    ⚡ {c['nom']} est paralysé !")

    elif nom_att == "Eclair Croix":
        if not cible.get("statut") and _jet_de(4, logs, nom, "[Eclair Croix] tente paralysie"):
            ok, _ = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé !")
        if cible.get("statut") == "FRZ":
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    ⚡ [Eclair Croix] : +20 dégâts (cible gelée)")

    elif nom_att == "Electacle":
        if not cible.get("statut") and _jet_de(6, logs, nom, "[Electacle] tente paralysie"):
            ok, _ = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé !")
        pokemon["_degats_support_actif"] = True

    # ══════════════════════════════════════════════════════════════════════
    # STATUTS FRZ
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Poudreuse", "Typhon Hivernal"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente gel"):
            ok, _ = appliquer_statut(cible, "FRZ")
            if ok: logs.append(f"    ❄️ {cible['nom']} est gelé !")

    elif nom_att in {"Cœur de Rancœur", "Regard Glaçant"}:
        if not cible.get("statut") and _jet_de(5, logs, nom, f"[{nom_att}] tente gel"):
            ok, _ = appliquer_statut(cible, "FRZ")
            if ok: logs.append(f"    ❄️ {cible['nom']} est gelé !")
        if cible.get("statut"):
            appliquer_bonus(pokemon, "bonus_attaque", 30 if nom_att == "Cœur de Rancœur" else 10)
            logs.append(f"    💥 [{nom_att}] : dégâts bonus (cible avec statut)")

    elif nom_att == "Feu Sacré":
        if not cible.get("statut") and _jet_de(4, logs, nom, "[Feu Sacré] tente brûlure"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")
        if pokemon.get("statut") == "FRZ":
            retirer_statut(pokemon)
            logs.append(f"    ❄️ {pokemon['nom']} est dégelé par Feu Sacré !")

    # ══════════════════════════════════════════════════════════════════════
    # STATUTS BRN
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Flamméche", "Poing de Feu", "Roue de Feu"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente brûlure"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")

    elif nom_att in {"Lance-Flammes", "Ebullition", "Cortège Funèbre"}:
        if not cible.get("statut") and _jet_de(5, logs, nom, f"[{nom_att}] tente brûlure"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")
        if nom_att == "Cortège Funèbre" and cible.get("statut"):
            appliquer_bonus(pokemon, "bonus_attaque", 30)
            logs.append(f"    💥 [Cortège Funèbre] : +30 dégâts (cible avec statut)")

    elif nom_att == "Feu d'Enfer":
        if not cible.get("statut"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")

    elif nom_att == "Pyroball G-Max":
        for c in _cibles_colonne():
            if not c.get("statut"):
                ok, _ = appliquer_statut(c, "BRN")
                if ok: logs.append(f"    🔥 {c['nom']} est brûlé !")

    elif nom_att in {"Boutefeu", "Boutefeu (Solaroc)"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente brûlure"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")
        # 10 dégâts aux Pokémon adjacents
        col = cible.get("slot", 0)
        for adj in equipe_adv:
            if abs(adj.get("slot", 0) - col) == 1 and not adj.get("ko"):
                adj["pv"] = max(0, adj.get("pv", 0) - 10)
                logs.append(f"    🔥 {adj['nom']} (adjacent) subit 10 dégâts de feu !")

    elif nom_att == "Ebullilave":
        for c in _cibles_colonne():
            if not c.get("statut") and _jet_de(5, logs, nom, f"[Ebullilave] tente brûlure sur {c['nom']}"):
                ok, _ = appliquer_statut(c, "BRN")
                if ok: logs.append(f"    🔥 {c['nom']} est brûlé !")

    elif nom_att == "Mortier Matcha":
        for c in _cibles_colonne():
            if not c.get("statut") and _jet_de(5, logs, nom, f"[Mortier Matcha] tente brûlure"):
                ok, _ = appliquer_statut(c, "BRN")
                if ok: logs.append(f"    🔥 {c['nom']} est brûlé !")
        pokemon["_vol_vie_actif"] = True

    elif nom_att == "Flamme Croix":
        if not cible.get("statut") and _jet_de(4, logs, nom, "[Flamme Croix] tente brûlure"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")
        if cible.get("statut") == "FRZ":
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    💥 [Flamme Croix] : +20 dégâts (cible gelée)")

    # ══════════════════════════════════════════════════════════════════════
    # STATUTS PSN
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Direct Toxik", "Détricanon", "Détritus"}:
        if not cible.get("statut") and _jet_de(5, logs, nom, f"[{nom_att}] tente poison"):
            ok, _ = appliquer_statut(cible, "PSN")
            if ok: logs.append(f"    ☠️ {cible['nom']} est empoisonné !")

    elif nom_att == "Crochet Venin":
        if not cible.get("statut") and _jet_de(4, logs, nom, "[Crochet Venin] tente poison"):
            ok, _ = appliquer_statut(cible, "PSN")
            if ok: logs.append(f"    ☠️ {cible['nom']} est empoisonné !")

    elif nom_att in {"Toxik", "Toupie Eclat"}:
        if not cible.get("statut"):
            ok, _ = appliquer_statut(cible, "PSN")
            if ok: logs.append(f"    ☠️ {cible['nom']} est empoisonné !")
        if nom_att == "Toupie Eclat":
            pokemon.pop("piege", None)
            logs.append(f"    🔓 {nom} n'est plus piégé !")

    elif nom_att == "Pestilence G-Max":
        for c in _cibles_colonne():
            if not c.get("statut"):
                ok, _ = appliquer_statut(c, "PSN")
                if ok: logs.append(f"    ☠️ {c['nom']} est empoisonné !")

    elif nom_att == "Cradovague":
        for c in _cibles_colonne():
            if not c.get("statut") and _jet_de(6, logs, nom, f"[Cradovague] tente poison sur {c['nom']}"):
                ok, _ = appliquer_statut(c, "PSN")
                if ok: logs.append(f"    ☠️ {c['nom']} est empoisonné !")

    elif nom_att == "Double-Dard":
        for c in _cibles_colonne():
            if not c.get("statut") and _jet_de(5, logs, nom, f"[Double-Dard] tente poison"):
                ok, _ = appliquer_statut(c, "PSN")
                if ok: logs.append(f"    ☠️ {c['nom']} est empoisonné !")

    elif nom_att == "Chaîne Malsaine":
        if not cible.get("statut") and _jet_de(4, logs, nom, "[Chaîne Malsaine] tente poison+confusion"):
            ok, _ = appliquer_statut(cible, "PSN")
            if ok: logs.append(f"    ☠️ {cible['nom']} est empoisonné !")
            ok2, _ = appliquer_statut(cible, "CNF")
            if ok2: logs.append(f"    😵 {cible['nom']} est confus !")

    # ══════════════════════════════════════════════════════════════════════
    # STATUTS SLP
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att == "Spore":
        if not cible.get("statut"):
            ok, _ = appliquer_statut(cible, "SLP")
            if ok: logs.append(f"    😴 {cible['nom']} s'endort !")

    elif nom_att == "Torpeur G-Max":
        for c in _cibles_colonne():
            if not c.get("statut"):
                ok, _ = appliquer_statut(c, "SLP")
                if ok: logs.append(f"    😴 {c['nom']} s'endort !")

    elif nom_att in {"Trou Noir"}:
        if _jet_de(4, logs, nom, "[Trou Noir] tente sommeil zone"):
            for c in _cibles_colonne():
                if not c.get("statut"):
                    ok, _ = appliquer_statut(c, "SLP")
                    if ok: logs.append(f"    😴 {c['nom']} s'endort !")

    # ══════════════════════════════════════════════════════════════════════
    # STATUTS CNF
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Danse-Fleur", "Rafale Psy", "Rayon Signal", "Vibraqua"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente confusion"):
            ok, _ = appliquer_statut(cible, "CNF")
            if ok: logs.append(f"    😵 {cible['nom']} est confus !")

    elif nom_att in {"Colére", "Grand Courroux"}:
        de = random.randint(1, 6)
        if de >= 5:
            if not cible.get("statut"):
                ok, _ = appliquer_statut(cible, "CNF")
                if ok: logs.append(f"    😵 {cible['nom']} est confus ! (dé: {de})")
        elif de == 1:
            if not pokemon.get("statut"):
                ok, _ = appliquer_statut(pokemon, "CNF")
                if ok: logs.append(f"    😵 {pokemon['nom']} est confus ! (dé: {de})")

    elif nom_att == "Dynamopoing":
        if not cible.get("statut") and _jet_de(4, logs, nom, "[Dynamopoing] tente confusion"):
            ok, _ = appliquer_statut(cible, "CNF")
            if ok: logs.append(f"    😵 {cible['nom']} est confus !")

    elif nom_att == "Onde Folie":
        if not cible.get("statut"):
            ok, _ = appliquer_statut(cible, "CNF")
            if ok: logs.append(f"    😵 {cible['nom']} est confus !")

    elif nom_att in {"Pactole G-Max", "Percussion G-Max", "Sentence G-Max"}:
        for c in _cibles_colonne():
            if not c.get("statut"):
                ok, _ = appliquer_statut(c, "CNF")
                if ok: logs.append(f"    😵 {c['nom']} est confus !")

    elif nom_att == "Uppercut":
        if not cible.get("statut") and _jet_de(5, logs, nom, "[Uppercut] tente confusion"):
            ok, _ = appliquer_statut(cible, "CNF")
            if ok: logs.append(f"    😵 {cible['nom']} est confus !")

    elif nom_att == "Vapeur Féerique":
        if not cible.get("statut") and _jet_de(5, logs, nom, "[Vapeur Féerique] tente confusion"):
            ok, _ = appliquer_statut(cible, "CNF")
            if ok: logs.append(f"    😵 {cible['nom']} est confus !")

    elif nom_att == "Vantardise":
        appliquer_bonus(cible, "bonus_attaque", X)
        logs.append(f"    ⚔️ {cible['nom']} +{X} Attaque (Vantardise)")
        if not cible.get("statut"):
            ok, _ = appliquer_statut(cible, "CNF")
            if ok: logs.append(f"    😵 {cible['nom']} est confus !")

    elif nom_att == "Talon-Marteau":
        de = random.randint(1, 6)
        if de == 1:
            perte = pokemon.get("pv_max", 100) // 2
            pokemon["pv"] = max(0, pokemon.get("pv", 0) - perte)
            logs.append(f"    💥 [Talon-Marteau] rate ! {pokemon['nom']} perd {perte} PV")
        elif de >= 5:
            if not cible.get("statut"):
                ok, _ = appliquer_statut(cible, "CNF")
                if ok: logs.append(f"    😵 {cible['nom']} est confus ! (dé: {de})")

    # ══════════════════════════════════════════════════════════════════════
    # PIÈGE
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Danse Flamme", "Harcélement", "Siphon", "Voltageôle", "Vortex Magma"}:
        for c in _cibles_colonne() if nom_att in {"Danse Flamme", "Harcélement", "Siphon"} else [cible]:
            if not c.get("piege"):
                ok, _ = appliquer_statut(c, "PIE")
                if ok: logs.append(f"    🔗 {c['nom']} est piégé !")

    elif nom_att == "Hache de Pierre":
        if _jet_de(5, logs, nom, "[Hache de Pierre] tente +20 dégâts"):
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    💥 [Hache de Pierre] : +20 dégâts")
        if not cible.get("piege"):
            ok, _ = appliquer_statut(cible, "PIE")
            if ok: logs.append(f"    🔗 {cible['nom']} est piégé !")

    elif nom_att == "Vagues à Lames":
        if _jet_de(5, logs, nom, "[Vagues à Lames] tente +20 dégâts"):
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    💥 [Vagues à Lames] : +20 dégâts")
        if not cible.get("piege"):
            ok, _ = appliquer_statut(cible, "PIE")
            if ok: logs.append(f"    🔗 {cible['nom']} est piégé !")

    elif nom_att == "Salaison":
        if not cible.get("piege"):
            ok, _ = appliquer_statut(cible, "PIE")
            if ok: logs.append(f"    🔗 {cible['nom']} est piégé !")

    elif nom_att in {"Métalliroue"}:
        pokemon.pop("piege", None)
        appliquer_bonus(pokemon, "bonus_attaque", 30)
        logs.append(f"    🔓 {nom} : piège retiré + 30 dégâts")

    elif nom_att == "Tour Rapide":
        for p in list(equipe_att) + [pokemon]:
            if p.get("piege"):
                p.pop("piege", None)
                appliquer_bonus(p, "bonus_vitesse", 10)
                p["vitesse"] = p.get("vitesse", 50) + 10
                logs.append(f"    🔓 {p['nom']} : piège retiré +10 Vitesse")
                break

    elif nom_att == "Tourbi-Sable":
        for c in _cibles_colonne():
            if not c.get("piege"):
                ok, _ = appliquer_statut(c, "PIE")
                if ok: logs.append(f"    🔗 {c['nom']} est piégé !")

    # ══════════════════════════════════════════════════════════════════════
    # IGNORE DÉFENSE
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Apocalypsis Luminis", "Coup Final G-Max", "Lux Nihilum",
                     "Magie Florale", "Multicoup G-Max", "Souffle Glacé",
                     "Lame Sainte", "Draco Ascension"}:
        ancien = cible.get("bonus_defense", 0)
        if ancien > 0:
            cible["bonus_defense"] = 0
            logs.append(f"    🗡️ {nom} [{nom_att}] : ignore Bonus Défense de {cible['nom']}")
        if nom_att == "Lame Sainte":
            pokemon["_ne_peut_echouer"] = True

    elif nom_att == "Tranch'Herb":
        ancien = cible.get("bonus_defense", 0)
        if ancien > 0:
            cible["bonus_defense"] = 0
        for c in _cibles_colonne():
            c["bonus_defense"] = 0
        logs.append(f"    🗡️ {nom} [Tranch'Herb] : ignore défense, zone")

    # ══════════════════════════════════════════════════════════════════════
    # SI AVANT
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att == "Vitesse Extrême":
        attaque_avant = pokemon.get("vitesse", 50) > cible.get("vitesse", 50)
        # Attaque en premier dans le combat = plus rapide de tous
        equipe_totale = equipe_att + equipe_adv
        plus_rapide = pokemon.get("vitesse", 50) >= max(p.get("vitesse", 50) for p in equipe_totale)
        if plus_rapide:
            appliquer_bonus(pokemon, "bonus_attaque", 30)
            logs.append(f"    ⚡ [Vitesse Extrême] : +30 dégâts (plus rapide du combat)")
        elif attaque_avant:
            appliquer_bonus(pokemon, "bonus_attaque", 10)
            logs.append(f"    ⚡ [Vitesse Extrême] : +10 dégâts (attaque avant)")

    elif nom_att == "Sheauriken":
        attaque_avant = pokemon.get("vitesse", 50) > cible.get("vitesse", 50)
        if attaque_avant:
            appliquer_bonus(pokemon, "bonus_attaque", 10)
            logs.append(f"    ⚡ [Sheauriken] : +10 dégâts (attaque avant)")
        de = random.randint(1, 6)
        bonus = 10 if de in [3, 4] else 20 if de >= 5 else 0
        if bonus:
            appliquer_bonus(pokemon, "bonus_attaque", bonus)
            logs.append(f"    🎲 [Sheauriken] : +{bonus} dégâts (dé: {de})")

    # ══════════════════════════════════════════════════════════════════════
    # ZONE COLONNE (attaques simples qui touchent les 2 Pokémon adverses)
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {
        "Coup Double", "Double Baffe", "Double Pied", "Draco-Flèches",
        "Draco-Fléches", "Eboulement", "Osmerang", "Tornade",
        "Lancécrou", "Lame Tachyonique", "Force Chtonienne",
        "Ocroupi", "Peignée", "Triple Pied", "Triple Plongeon",
        "Tranch'Air", "Eruption", "Giclédo", "Ecrous d'Poing",
    }:
        # Marquer pour toucher aussi le support adverse (traité après calcul dégâts)
        pokemon["_zone_colonne"] = True

    return None
def init_pool(partie):
    pool = [p["id"] for p in POKEMONS_DB]
    random.shuffle(pool)
    partie["pool"] = pool

def piocher_depuis_pool(partie, niveau_joueur, n=5, niveau_max_pool=10):
    """Pioche n Pokémon stade 0 de niveau <= niveau_max_pool, choix aléatoire."""
    max_niv = min(niveau_joueur, niveau_max_pool)
    pool = partie.get("pool", [])
    eligibles = [pid for pid in pool
                 if (lambda p: p
                     and p.get("stade", 0) == 0
                     and p["id"] not in _EXCLUS_POOL
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

def est_tour_caroussel(partie):
    """Retourne True si le tour actuel est un tour carrousel (4, 8, 12...)."""
    return partie.get("tour", 0) > 0 and partie["tour"] % 4 == 0

def preparer_caroussel(partie):
    """
    Prépare le carrousel : pioche N+1 Pokémon (N = nb joueurs vivants)
    dans le pool jusqu'au niveau max des joueurs. Stocke dans partie["caroussel"].
    """
    joueurs_vivants = {p: j for p, j in partie["joueurs"].items() if j.get("en_vie", True)}
    nb_joueurs = len(joueurs_vivants)
    # Niveau max parmi les joueurs vivants
    niveau_max = max((j["niveau"] for j in joueurs_vivants.values()), default=1)
    # Pioche N+1 Pokémon éligibles jusqu'au niveau max
    pool = partie.get("pool", [])
    eligibles = [pid for pid in pool
                 if (lambda p: p
                     and p.get("stade", 0) == 0
                     and pid not in _IDS_INTERMEDIAIRES
                     and p["niveau"] <= niveau_max)(_get_poke(pid))]
    random.shuffle(eligibles)
    nb_a_piocher = min(nb_joueurs + 1, len(eligibles))
    choix_ids = eligibles[:nb_a_piocher]
    for pid in choix_ids:
        pool.remove(pid)
    # Ordre de sélection : PV croissants (le moins de PV choisit en premier)
    ordre = sorted(joueurs_vivants.keys(), key=lambda p: joueurs_vivants[p]["pv"])
    # Timer par position
    def timer_pour(idx, total):
        if idx == 0:          return 30
        if idx == total - 1:  return 8
        return 15
    caroussel = {
        "pokemon":   [{"id": pid, "nom": _get_poke(pid)["nom"],
                       "types": _get_poke(pid)["types"],
                       "niveau": _get_poke(pid)["niveau"]} for pid in choix_ids],
        "ordre":     ordre,
        "index":     0,       # indice du joueur courant dans ordre
        "choisis":   {},      # {pseudo: pokemon_id}
        "timers":    {ordre[i]: timer_pour(i, len(ordre)) for i in range(len(ordre))},
        "actif":     True,
    }
    partie["caroussel"] = caroussel
    return caroussel

def valeur_caroussel(pokemon_id):
    """Valeur d'un Pokémon pour le choix automatique (niveau = valeur)."""
    p = _get_poke(pokemon_id)
    return p["niveau"] if p else 0

async def avancer_caroussel(code, partie, gestionnaire):
    """
    Gère le tour du joueur courant dans le carrousel.
    Envoie un message caroussel_tour au joueur actif.
    Lance le timer et passe automatiquement si pas de réponse.
    """
    caroussel = partie.get("caroussel")
    if not caroussel or not caroussel.get("actif"):
        return
    ordre  = caroussel["ordre"]
    index  = caroussel["index"]
    if index >= len(ordre):
        await terminer_caroussel(code, partie, gestionnaire)
        return
    pseudo_actif = ordre[index]
    timer = caroussel["timers"].get(pseudo_actif, 15)
    # Pokémon encore disponibles
    dispo = [p for p in caroussel["pokemon"]
             if p["id"] not in caroussel["choisis"].values()]
    # Notifier tout le monde + le joueur actif
    await gestionnaire.diffuser(code, {
        "type":         "caroussel_tour",
        "pseudo_actif": pseudo_actif,
        "pokemon":      caroussel["pokemon"],
        "dispo":        [p["id"] for p in dispo],
        "choisis":      caroussel["choisis"],
        "ordre":        ordre,
        "timer":        timer,
    })
    # Lancer le timer — annulable si le joueur choisit avant
    caroussel["_timer_task"] = asyncio.create_task(
        _timer_caroussel(code, partie, gestionnaire, pseudo_actif, timer, dispo))

async def _timer_caroussel(code, partie, gestionnaire, pseudo, duree, dispo):
    """Attend duree secondes puis choisit automatiquement le meilleur Pokémon disponible."""
    try:
        await asyncio.sleep(duree)
        if code not in parties:
            return
        caroussel = partie.get("caroussel")
        if not caroussel or not caroussel.get("actif"):
            return
        # Vérifier que c'est toujours ce joueur qui doit choisir
        if caroussel["ordre"][caroussel["index"]] != pseudo:
            return
        # Choix auto : Pokémon de plus haute valeur (niveau le plus élevé)
        dispo_ids = [p["id"] for p in dispo if p["id"] not in caroussel["choisis"].values()]
        if not dispo_ids:
            return
        meilleur = max(dispo_ids, key=lambda pid: (valeur_caroussel(pid), random.random()))
        await _appliquer_choix_caroussel(code, partie, gestionnaire, pseudo, meilleur, auto=True)
    except asyncio.CancelledError:
        pass  # Timer annulé proprement
    except Exception as e:
        print(f"[ERREUR timer carrousel] {e}")

async def _appliquer_choix_caroussel(code, partie, gestionnaire, pseudo, pokemon_id, auto=False):
    """Applique le choix d'un joueur et passe au joueur suivant."""
    caroussel = partie.get("caroussel")
    if not caroussel or not caroussel.get("actif"):
        return
    # Verrou anti double-appel : si ce joueur a déjà choisi, ignorer
    if pseudo in caroussel.get("choisis", {}):
        return
    # Annuler le timer en cours
    task = caroussel.pop("_timer_task", None)
    if task and not task.done():
        task.cancel()
    # Enregistrer le choix
    caroussel["choisis"][pseudo] = pokemon_id
    # Ajouter le Pokémon au banc du joueur avec 1 XP
    joueur = partie["joueurs"].get(pseudo)
    if joueur:
        poke_data = _get_poke(pokemon_id)
        if poke_data:
            slots_banc = {p["slot"] for p in joueur["pokemon"] if p["position"] == "banc"}
            slot_libre = next((i for i in range(10) if i not in slots_banc), 0)
            nouveau = {k: poke_data.get(k) for k in poke_data}
            nouveau["position"]    = "banc"
            nouveau["slot"]        = slot_libre
            nouveau["pv"]          = poke_data.get("pv_max", 100)
            nouveau["xp_combats"]  = 1  # 1 XP offert
            nouveau["ko"]          = False
            joueur["pokemon"].append(nouveau)
            appliquer_bonus_pv_synergies(joueur)
    msg_auto = " (automatique)" if auto else ""
    await gestionnaire.diffuser(code, {
        "type":    "caroussel_choix",
        "pseudo":  pseudo,
        "pokemon": pokemon_id,
        "auto":    auto,
        "msg":     f"🎠 {pseudo} choisit {_get_poke(pokemon_id)['nom']}{msg_auto}",
    })
    # Passer au joueur suivant
    caroussel["index"] += 1
    await avancer_caroussel(code, partie, gestionnaire)

async def terminer_caroussel(code, partie, gestionnaire):
    """Termine le carrousel : retourne le Pokémon restant au pool."""
    caroussel = partie.get("caroussel", {})
    caroussel["actif"] = False
    # Annuler le timer en cours s'il existe
    task = caroussel.pop("_timer_task", None)
    if task and not task.done():
        task.cancel()
    # Retourner le(s) Pokémon non choisi(s) au pool
    choisis = set(caroussel.get("choisis", {}).values())
    restants = [p["id"] for p in caroussel.get("pokemon", []) if p["id"] not in choisis]
    retourner_au_pool(partie, restants)
    partie.pop("caroussel", None)
    # Signaler la fin et ouvrir la boutique
    await gestionnaire.diffuser(code, {
        "type": "caroussel_termine", "etat": partie,
        "msg":  "🎠 Carrousel terminé !",
    })
    # Envoyer la boutique à chaque joueur
    for pj, j in partie["joueurs"].items():
        await gestionnaire.envoyer_a(code, pj, {
            "type":          "boutique_offre", "pour": pj,
            "offre":         j["boutique_offre"],
            "tour":          partie["tour"],
            "tour1_gratuit": False,
            "auto":          True,
        })

def generer_offre_boutique(partie, niveau_joueur, ancienne_offre=None, locked=False, niveau_max_pool=10):
    if locked and ancienne_offre:
        return ancienne_offre
    if ancienne_offre:
        retourner_au_pool(partie, [p["id"] for p in ancienne_offre])
    pokes = piocher_depuis_pool(partie, niveau_joueur, niveau_max_pool=niveau_max_pool)
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
def _normaliser_type(t):
    """Normalise un type Pokémon en minuscules sans accents."""
    return (t.lower()
             .replace("é", "e").replace("è", "e").replace("ê", "e")
             .replace("à", "a").replace("â", "a")
             .replace("ù", "u").replace("û", "u")
             .replace("î", "i").replace("ï", "i")
             .replace("ô", "o"))

def calculer_synergies(joueur):
    terrain = [p for p in joueur.get("pokemon", []) if p["position"] in ("off", "def")]
    compteur = {}
    for poke in terrain:
        for t in poke.get("types", []):
            tn = _normaliser_type(t)
            compteur[tn] = compteur.get(tn, 0) + 1
    synergies = {}
    for t, count in compteur.items():
        if count >= 9:   synergies[t] = 9
        elif count >= 6: synergies[t] = 6
        elif count >= 3: synergies[t] = 3
    return synergies

def calculer_evoli_forme(joueur):
    """Retourne l'ID de l'évolition si une synergie 6+ est active, sinon None."""
    synergies = calculer_synergies(joueur)
    for syn, palier in synergies.items():
        if palier >= 6 and syn in EVOLITIONS_MAP:
            return EVOLITIONS_MAP[syn]
    return None

def palier_synergie(joueur, type_poke):
    """Retourne le palier de synergie (3/6/9) pour un type donné, ou 0."""
    return joueur.get("synergies", {}).get(type_poke, 0)

def seuil_de(palier):
    """Retourne le seuil de dé (sur 6) pour 1/3, 2/3, 3/3."""
    if palier >= 9: return 0   # 3/3 = automatique (toujours)
    if palier >= 6: return 2   # 2/3 = dé >= 3
    if palier >= 3: return 4   # 1/3 = dé >= 5
    return 7  # jamais

def jet_synergie(palier):
    """Lance un dé, retourne True si l'effet se déclenche."""
    seuil = seuil_de(palier)
    if seuil >= 7: return False
    if seuil == 0: return True
    return random.randint(1, 6) > seuil

def appliquer_effets_synergies_debut(j1, j2, equipe1, equipe2, logs):
    """
    Applique les effets de synergies permanents AVANT le combat :
    Eau (+vitesse), Dragon (+dégâts), Normal (+PV max).
    Ces effets sont temporaires pour le combat (on les retire après).
    """
    for joueur, equipe in [(j1, equipe1), (j2, equipe2)]:
        for poke in equipe:
            types = [_normaliser_type(t) for t in poke.get("types", [])]
            # Eau : +vitesse selon palier
            for t in types:
                pal = palier_synergie(joueur, "eau")
                if pal and t == "eau":
                    bonus = {3: 10, 6: 20, 9: 40}.get(pal, 0)
                    poke["_vit_bonus"] = bonus
                    poke["vitesse"] = poke.get("vitesse", 50) + bonus
                # Dragon : +dégâts offensifs
                pal_dragon = palier_synergie(joueur, "dragon")
                if pal_dragon and t == "dragon":
                    bonus = {3: 10, 6: 20, 9: 40}.get(pal_dragon, 0)
                    poke["_dmg_bonus"] = bonus
                # Normal : +PV max (et PV courants)
                pal_normal = palier_synergie(joueur, "normal")
                if pal_normal and t == "normal":
                    bonus = {3: 10, 6: 20, 9: 40}.get(pal_normal, 0)
                    if not poke.get("_normal_applique"):
                        poke["pv_max"] = poke.get("pv_max", 100) + bonus
                        poke["pv"]     = min(poke.get("pv", 100) + bonus, poke["pv_max"])
                        poke["_normal_applique"] = bonus

def retirer_effets_synergies_debut(equipe1, equipe2):
    """Retire les bonus temporaires de début de combat."""
    for equipe in [equipe1, equipe2]:
        for poke in equipe:
            if "_vit_bonus" in poke:
                poke["vitesse"] = max(1, poke.get("vitesse", 50) - poke["_vit_bonus"])
                del poke["_vit_bonus"]
            poke.pop("_dmg_bonus", None)
            if "_normal_applique" in poke:
                bonus = poke["_normal_applique"]
                poke["pv_max"] = max(1, poke.get("pv_max", 100) - bonus)
                poke["pv"]     = min(poke.get("pv", 100), poke["pv_max"])
                del poke["_normal_applique"]

def appliquer_effets_post_attaque(attaquant, defenseur, joueur_att, joueur_def, logs):
    """
    Effets de synergies déclenchés après une attaque réussie :
    Electrik/Feu/Glace/Poison/Psy/Sol/Ténèbre (statuts), Vol (ciblage géré ailleurs).
    Retourne le defenseur réel (peut changer avec Vol).
    """
    if defenseur.get("ko"):
        return
    types_att = [_normaliser_type(t) for t in attaquant.get("types", [])]
    for t in types_att:
        # Electrik → PAR
        pal = palier_synergie(joueur_att, "electrik")
        if pal and t == "electrik" and not defenseur.get("statut") and jet_synergie(pal):
            ok, msg = appliquer_statut(defenseur, "PAR")
            if ok: logs.append(f"    ⚡ Synergie Electrik : {msg}")
        # Feu → BRN
        pal = palier_synergie(joueur_att, "feu")
        if pal and t == "feu" and not defenseur.get("statut") and jet_synergie(pal):
            ok, msg = appliquer_statut(defenseur, "BRN")
            if ok: logs.append(f"    🔥 Synergie Feu : {msg}")
        # Glace → FRZ
        pal = palier_synergie(joueur_att, "glace")
        if pal and t == "glace" and not defenseur.get("statut") and jet_synergie(pal):
            ok, msg = appliquer_statut(defenseur, "FRZ")
            if ok: logs.append(f"    ❄️ Synergie Glace : {msg}")
        # Poison → PSN
        pal = palier_synergie(joueur_att, "poison")
        if pal and t == "poison" and not defenseur.get("statut") and jet_synergie(pal):
            ok, msg = appliquer_statut(defenseur, "PSN")
            if ok: logs.append(f"    ☠️ Synergie Poison : {msg}")
        # Psy → CNF
        pal = palier_synergie(joueur_att, "psy")
        if pal and t == "psy" and not defenseur.get("statut") and jet_synergie(pal):
            ok, msg = appliquer_statut(defenseur, "CNF")
            if ok: logs.append(f"    🌀 Synergie Psy : {msg}")
        # Sol → PIE
        pal = palier_synergie(joueur_att, "sol")
        if pal and t == "sol" and not defenseur.get("piege") and jet_synergie(pal):
            ok, msg = appliquer_statut(defenseur, "PIE")
            if ok: logs.append(f"    🪤 Synergie Sol : {msg}")
        # Ténèbre → FER (peur — seulement si défenseur moins rapide)
        pal = palier_synergie(joueur_att, "tenebres")
        if pal and t == "ténèbre" and not defenseur.get("peur") and jet_synergie(pal):
            if defenseur.get("vitesse", 50) < attaquant.get("vitesse", 50):
                defenseur["peur"] = True
                logs.append(f"    😨 Synergie Ténèbre : {defenseur['nom']} a peur !")

def appliquer_effets_ko_synergie(ko_poke, equipe_ko, equipe_adv, joueur_ko, joueur_adv, partie, logs):
    """
    Effets déclenchés à chaque KO :
    - Combat : soigne Pokémon Combat de la colonne vainqueur
    - Spectre : inflige dégâts à la colonne adverse miroir
    """
    types_ko = [_normaliser_type(t) for t in ko_poke.get("types", [])]
    col_ko   = ko_poke["slot"]
    col_miroir = 4 - col_ko

    # Spectre : le pokemon KO inflige des dégâts à la colonne adverse miroir
    pal_spectre = palier_synergie(joueur_ko, "spectre")
    if pal_spectre and "spectre" in types_ko:
        dmg_base = {3: 10, 6: 20, 9: 30}.get(pal_spectre, 0)
        dmg_total = dmg_base * ko_poke.get("niveau", 1)
        cibles = [p for p in equipe_adv if p["slot"] == col_miroir and not p.get("ko")]
        for cible in cibles:
            cible["pv"] = max(0, cible.get("pv", 0) - dmg_total)
            logs.append(f"    👻 Synergie Spectre : {ko_poke['nom']} inflige {dmg_total} à {cible['nom']} → {cible['pv']}PV")
            if cible["pv"] <= 0 and not cible.get("ko"):
                cible["ko"] = True
                logs.append(f"    💀 {cible['nom']} est KO (spectre) !")

    # Combat : soigne les Pokémon Combat de la colonne adverse (vainqueur)
    pal_combat = palier_synergie(joueur_adv, "combat")
    if pal_combat:
        soin_base = {3: 10, 6: 20, 9: 30}.get(pal_combat, 0)
        soin_total = soin_base * ko_poke.get("niveau", 1)
        colonne_adv = [p for p in equipe_adv if p["slot"] == col_miroir and not p.get("ko")]
        for poke in colonne_adv:
            if "combat" in [_normaliser_type(t) for t in poke.get("types", [])]:
                ancien_pv = poke.get("pv", 0)
                poke["pv"] = min(poke.get("pv", 0) + soin_total, poke.get("pv_max", 100))
                logs.append(f"    🥊 Synergie Combat : {poke['nom']} soigné de {poke['pv']-ancien_pv} PV → {poke['pv']}PV")

def appliquer_effets_post_combat(j1, p1, j2, p2, equipe1, equipe2, partie, logs):
    """
    Effets appliqués après la résolution complète du combat :
    - Plante : soin PV
    - Fée : pièces
    - Insecte : force bonus (dégâts directs supplémentaires)
    Retourne (bonus_force_j1, bonus_force_j2).
    """
    bonus_force_j1, bonus_force_j2 = 0, 0

    for joueur, equipe, pseudo, adv_pv_key, j_adv in [
        (j1, equipe1, p1, "pv", j2),
        (j2, equipe2, p2, "pv", j1)
    ]:
        synergies = joueur.get("synergies", {})
        vivants = [p for p in equipe if not p.get("ko")]

        # Plante : soin post-combat
        pal_plante = synergies.get("plante", 0)
        if pal_plante:
            soin = {3: 10, 6: 20, 9: 40}.get(pal_plante, 0)
            for poke in vivants:
                if "plante" in [_normaliser_type(t) for t in poke.get("types", [])]:
                    poke["pv"] = min(poke.get("pv", 0) + soin, poke.get("pv_max", 100))
                    logs.append(f"    🌿 Synergie Plante : {poke['nom']} +{soin} PV → {poke['pv']}PV")

        # Fée : pièces
        pal_fee = synergies.get("fee", 0)
        if pal_fee:
            pieces = {3: 1, 6: 2, 9: 4}.get(pal_fee, 0)
            joueur["pieces"] = joueur.get("pieces", 0) + pieces
            logs.append(f"    🧚 Synergie Fée : {pseudo} gagne {pieces} pièce(s)")

        # Insecte : force bonus
        pal_insecte = synergies.get("insecte", 0)
        if pal_insecte:
            bonus = {3: 1, 6: 2, 9: 4}.get(pal_insecte, 0)
            if joueur is j1: bonus_force_j1 += bonus
            else:            bonus_force_j2 += bonus
            if bonus:
                logs.append(f"    🐛 Synergie Insecte : {pseudo} +{bonus} pts de force")

    return bonus_force_j1, bonus_force_j2

def points_force_total(poke):
    """Points de force avec bonus stade."""
    base  = points_force(poke)
    stade = poke.get("stade", 0)
    return base + (1 if stade == 1 else 2 if stade >= 2 else 0)

def appliquer_bonus_pv_synergies(joueur):
    synergies = calculer_synergies(joueur)
    joueur["synergies"]   = synergies
    joueur["evoli_forme"] = calculer_evoli_forme(joueur)
    pal_normal = synergies.get("normal", 0)
    for poke in joueur.get("pokemon", []):
        # Bonus PV général : meilleur palier parmi toutes les synergies actives du Pokémon
        meilleur = 0
        for t in poke.get("types", []):
            if t in synergies:
                meilleur = max(meilleur, BONUS_PV_SYNERGIE.get(synergies[t], 0))
        # Bonus supplémentaire pour la synergie Normal (cumulatif)
        if "normal" in [_normaliser_type(t) for t in poke.get("types", [])] and pal_normal:
            meilleur += BONUS_PV_SYNERGIE.get(pal_normal, 0)
        ancien = poke.get("bonus_pv_synergie", 0)
        if meilleur != ancien:
            diff = meilleur - ancien
            poke["pv_max"] = poke.get("pv_max", 100) + diff
            poke["pv"]     = min(poke.get("pv", 100) + diff, poke["pv_max"])
            poke["bonus_pv_synergie"] = meilleur

def nb_emplacements_centre(niveau):
    """Nombre d'emplacements Centre Pokémon selon le niveau du dresseur."""
    if niveau >= 10: return 4
    if niveau >= 8:  return 3
    if niveau >= 5:  return 2
    return 1

# ── Statuts ───────────────────────────────────────────────────────────────────
STATUTS_UNIQUES = {"PAR", "PSN", "FRZ", "SLP", "CNF", "BRN"}  # exclusifs entre eux

def appliquer_statut(poke, statut):
    """Applique un statut à un Pokémon. Respecte l'exclusivité et les effets immédiats."""
    if poke.get("ko"):
        return False, ""
    statut_actuel = poke.get("statut")
    # Déjà un statut unique → immunisé (sauf Piégé et Peur qui sont séparés)
    if statut in STATUTS_UNIQUES and statut_actuel in STATUTS_UNIQUES:
        return False, f"{poke['nom']} est déjà {statut_actuel}, statut {statut} ignoré"
    if statut == "PAR":
        poke["statut"] = "PAR"
        poke["vitesse"] = max(1, poke.get("vitesse", 50) // 2)
        return True, f"⚡ {poke['nom']} est paralysé ! (vitesse ÷2)"
    elif statut == "PSN":
        poke["statut"] = "PSN"
        return True, f"☠️ {poke['nom']} est empoisonné !"
    elif statut == "FRZ":
        poke["statut"] = "FRZ"
        return True, f"❄️ {poke['nom']} est gelé !"
    elif statut == "SLP":
        poke["statut"] = "SLP"
        poke["slp_tours"] = 0  # compteur de tours de sommeil
        return True, f"💤 {poke['nom']} s'endort !"
    elif statut == "CNF":
        poke["statut"] = "CNF"
        return True, f"🌀 {poke['nom']} est confus !"
    elif statut == "BRN":
        poke["statut"] = "BRN"
        poke["degats"] = max(1, poke.get("degats", 20) // 2)
        return True, f"🔥 {poke['nom']} est brûlé ! (dégâts ÷2)"
    elif statut == "PIE":  # Piégé — cumulable
        poke["piege"] = True
        return True, f"🪤 {poke['nom']} est piégé !"
    elif statut == "FER":  # Peur — temporaire, géré dans la file
        poke["peur"] = True
        return True, f"😨 {poke['nom']} a peur !"
    return False, ""

def retirer_statut(poke):
    """Supprime le statut principal et restaure les stats modifiées."""
    statut = poke.get("statut")
    if not statut:
        return
    if statut == "PAR":
        # Restaurer la vitesse depuis la DB
        from_db = _DB_MAP.get(poke.get("id"), {})
        poke["vitesse"] = from_db.get("vitesse", poke.get("vitesse", 50) * 2)
    elif statut == "BRN":
        from_db = _DB_MAP.get(poke.get("id"), {})
        poke["degats"] = from_db.get("degats", poke.get("degats", 20) * 2)
    poke.pop("statut", None)
    poke.pop("slp_tours", None)

def retirer_piege(poke):
    poke.pop("piege", None)

def soigner_statuts(poke):
    """Soin complet : supprime statut, piège, peur."""
    retirer_statut(poke)
    retirer_piege(poke)
    poke.pop("peur", None)

def verifier_peut_attaquer(poke, logs):
    """
    Vérifie si le Pokémon peut attaquer selon son statut.
    Retourne True si l'attaque peut avoir lieu, False sinon.
    Modifie les statuts en conséquence (FRZ dégel, SLP réveil, etc.)
    """
    statut = poke.get("statut")
    nom = poke["nom"]

    if poke.get("peur"):
        logs.append(f"    😨 {nom} a peur et ne peut pas attaquer !")
        poke.pop("peur", None)
        return False

    if statut == "PAR":
        de = random.randint(1, 6)
        if de <= 2:
            logs.append(f"    ⚡ {nom} est paralysé et ne peut pas attaquer ! (dé: {de})")
            return False
        logs.append(f"    ⚡ {nom} est paralysé mais attaque quand même (dé: {de})")
        return True

    if statut == "FRZ":
        de = random.randint(1, 6)
        if de == 6:
            retirer_statut(poke)
            logs.append(f"    ❄️ {nom} est dégelé et attaque ! (dé: {de})")
            return True
        logs.append(f"    ❄️ {nom} est gelé et ne peut pas attaquer (dé: {de})")
        return False

    if statut == "SLP":
        tours = poke.get("slp_tours", 0)
        if tours >= 5:
            retirer_statut(poke)
            logs.append(f"    💤 {nom} se réveille !")
            return True
        # Probabilité de réveil : tour 0→1/6, 1→2/6, 2→3/6, 3→4/6, 4→5/6
        seuil = tours + 1
        de = random.randint(1, 6)
        poke["slp_tours"] = tours + 1
        if de > seuil:
            logs.append(f"    💤 {nom} se réveille et attaque ! (dé: {de})")
            retirer_statut(poke)
            return True
        logs.append(f"    💤 {nom} dort et ne peut pas attaquer (dé: {de}, seuil>{seuil})")
        return False

    if statut == "CNF":
        de = random.randint(1, 6)
        if de == 6:
            retirer_statut(poke)
            logs.append(f"    🌀 {nom} n'est plus confus ! (dé: {de})")
            return True
        if de >= 3:
            logs.append(f"    🌀 {nom} est confus mais attaque normalement (dé: {de})")
            return True
        # 1-2 : se blesse avec sa propre attaque
        degats_auto = poke.get("degats", 20)
        poke["pv"] = max(0, poke.get("pv", 0) - degats_auto)
        logs.append(f"    🌀 {nom} est confus et se blesse ! -{degats_auto} PV → {poke['pv']}PV (dé: {de})")
        return False

    return True

# ── Transformations conditionnelles ──────────────────────────────────────────
# Mapping type déclencheur → id variante Cheniti
_CHENITI_FORMES = {"acier": "0412b", "sol": "0412c", "plante": "0412d"}
_CHENITI_FORMES_IDS = set(_CHENITI_FORMES.values())

_DB_MAP = {p["id"]: p for p in POKEMONS_DB}

def appliquer_transformations(joueur):
    """
    Cheniti (0412) : se transforme dès qu'un Pokémon de type acier/sol/plante
    est dans la même colonne. Irréversible une fois transformé.
    En cas de double type déclencheur, on prend le type 1 du partenaire.
    """
    pokemon = joueur.get("pokemon", [])
    terrain = [p for p in pokemon if p["position"] in ("off", "def")]

    for poke in terrain:
        if poke.get("id") not in ("0412", "0412b", "0412c", "0412d"):
            continue
        # Déjà transformé → irréversible
        col = poke["slot"]
        # Chercher un partenaire dans la même colonne (hors lui-même)
        partenaires = [p for p in terrain if p["slot"] == col and p is not poke]
        forme = None
        for partenaire in partenaires:
            types = partenaire.get("types", [])
            # Priorité : type 1 (index 0)
            for t in types:
                if t in _CHENITI_FORMES:
                    forme = _CHENITI_FORMES[t]
                    break
            if forme:
                break
        if not forme:
            continue
        # Transformation : remplacer l'id, le nom, l'evolution_id
        nouvelle_db = _DB_MAP.get(forme)
        if not nouvelle_db:
            continue
        poke["id"]           = forme
        poke["nom"]          = nouvelle_db["nom"]
        poke["evolution_id"] = nouvelle_db.get("evolution_id")
        poke["evolution_nom"]= nouvelle_db.get("evolution_nom")
        poke["evolution_ko"] = nouvelle_db.get("evolution_ko")
        poke["att_off_type"] = nouvelle_db.get("att_off_type")
        poke["att_def_type"] = nouvelle_db.get("att_def_type")

# ── Combat ────────────────────────────────────────────────────────────────────
def valeur_x(niveau):
    """Valeur X (PV, bonus défense, dégâts sup...) selon le niveau du Pokémon."""
    if niveau <= 3:   return 10
    elif niveau <= 6: return 20
    elif niveau <= 9: return 30
    elif niveau <= 12: return 40
    else:             return 50

def valeur_y(niveau):
    """Valeur Y (précision uniquement) selon le niveau du Pokémon."""
    if niveau <= 3:   return 1
    elif niveau <= 6: return 2
    elif niveau <= 9: return 3
    elif niveau <= 12: return 4
    else:             return 5

def appliquer_bonus(poke, champ, valeur):
    """
    Applique un bonus/malus sur un champ (bonus_attaque, bonus_defense,
    bonus_vitesse, bonus_precision). Plafonnement : la valeur nette
    ne peut pas dépasser la valeur absolue maximale jamais appliquée.
    - Si valeur > 0 : bonus, plafond = valeur
    - Si valeur < 0 : malus, on retire sans dépasser le minimum possible
    La valeur nette peut être négative (malus net après compensation).
    """
    actuel = poke.get(champ, 0)
    if valeur > 0:
        # Ne pas dépasser le plafond haut (valeur du bonus)
        nouveau = min(actuel + valeur, valeur)
    else:
        # Malus : appliquer sans plancher fixe, mais ne pas doubler le même malus
        nouveau = max(actuel + valeur, valeur)
    poke[champ] = nouveau

def jet_precision(attaquant, logs):
    """
    Vérifie si l'attaque touche selon le malus de précision.
    Retourne True si l'attaque touche, False sinon.
    Malus N : doit faire >= (6 - N + 1) sur 1d6.
    """
    malus = -attaquant.get("bonus_precision", 0)  # négatif = malus
    if malus <= 0:
        return True  # Précision parfaite
    seuil = 6 - malus + 1
    if seuil > 6:
        logs.append(f"    🎯 {attaquant['nom']} rate son attaque (malus précision {malus} trop élevé) !")
        return False
    de = random.randint(1, 6)
    if de >= seuil:
        return True
    logs.append(f"    🎯 {attaquant['nom']} rate son attaque ! (dé: {de}, besoin: {seuil}+)")
    return False

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
    # Appliquer bonus/malus d'attaque
    degats_base  = max(0, degats_base + attaquant.get("bonus_attaque", 0))
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
            multiplicateur *= 0.5  # Immunité = résistance ×0.5 dans PKChess
        if t_low in [x.lower() for x in faiblesses]:
            multiplicateur = max(multiplicateur, 2.0)
        elif t_low in [x.lower() for x in resistances]:
            multiplicateur = min(multiplicateur, 0.5)

    # Appliquer bonus_defense du défenseur (réduit les dégâts reçus)
    degats_final = max(0, int(degats_base * multiplicateur) - max(0, defenseur.get("bonus_defense", 0)))
    if multiplicateur >= 2.0:   effet = "super efficace"
    elif multiplicateur <= 0.5: effet = "pas très efficace"
    else:                       effet = "normal"
    return degats_final, effet

def resoudre_duel_complet(partie, p1, j1, p2, j2):
    equipe1 = [p for p in j1.get("pokemon", []) if p["position"] in ("off", "def") and not p.get("ko")]
    equipe2 = [p for p in j2.get("pokemon", []) if p["position"] in ("off", "def") and not p.get("ko")]

    # Flag anti-double-XP : chaque pokemon ne peut gagner qu'1 XP par combat
    for p in equipe1 + equipe2:
        p["_xp_ko_ids"] = set()  # IDs des Pokémon mis KO par ce Pokémon ce combat
        # Réinitialiser les bonus temporaires de combat
        p.setdefault("bonus_attaque",   0)
        p.setdefault("bonus_defense",   0)
        p.setdefault("bonus_vitesse",   0)
        p.setdefault("bonus_precision", 0)

    logs = [f"⚔️ {p1} vs {p2}"]
    pts1, pts2 = 0, 0

    # Appariement par colonne : offensif vs offensif adverse (miroir), sinon défensif adverse
    offs1 = {p["slot"]: p for p in equipe1 if p["position"] == "off"}
    offs2 = {p["slot"]: p for p in equipe2 if p["position"] == "off"}
    defs1 = {p["slot"]: p for p in equipe1 if p["position"] == "def"}
    defs2 = {p["slot"]: p for p in equipe2 if p["position"] == "def"}
    paires, apparies1, apparies2 = [], set(), set()
    for s in range(5):
        col_adv = 4 - s
        a = offs1.get(s)
        if not a: continue
        b = offs2.get(col_adv) or defs2.get(col_adv)
        if b and id(a) not in apparies1 and id(b) not in apparies2:
            paires.append((a, b)); apparies1.add(id(a)); apparies2.add(id(b))
    for s in range(5):
        col_adv = 4 - s
        a = offs2.get(s)
        if not a or id(a) in apparies2: continue
        b = offs1.get(col_adv) or defs1.get(col_adv)
        if b and id(b) not in apparies1:
            paires.append((b, a)); apparies1.add(id(b)); apparies2.add(id(a))

    sans_adv1 = [p for p in equipe1 if id(p) not in apparies1]
    sans_adv2 = [p for p in equipe2 if id(p) not in apparies2]

    # Log de présentation des duels
    for (a, b) in paires:
        logs.append(f"  🔸 {a['nom']} [{a['position']}] (⚡{a.get('vitesse',50)}, {a.get('pv',0)}PV)"
                    f" vs {b['nom']} [{b['position']}] (⚡{b.get('vitesse',50)}, {b.get('pv',0)}PV)")

    # Effets synergies de début de combat (Eau, Dragon, Normal)
    appliquer_effets_synergies_debut(j1, j2, equipe1, equipe2, logs)

    # File d'attaque globale triée par vitesse décroissante
    # Chaque entrée = (attaquant, defenseur)
    file_attaques = []
    for (a, b) in paires:
        file_attaques.append((a, b))
        file_attaques.append((b, a))
    file_attaques.sort(key=lambda x: x[0].get("vitesse", 50), reverse=True)

    idx_file = 0
    while idx_file < len(file_attaques):
        attaquant, defenseur = file_attaques[idx_file]
        idx_file += 1
        # Ne pas attaquer si déjà KO
        if attaquant.get("ko") or defenseur.get("ko"):
            continue
        # Vérifier statuts bloquants
        if not verifier_peut_attaquer(attaquant, logs):
            # KO auto possible (confusion)
            if attaquant.get("pv", 1) <= 0 and not attaquant.get("ko"):
                attaquant["ko"] = True
                attaquant["pv"] = 0
                soigner_statuts(attaquant)  # KO supprime tous les statuts
                logs.append(f"    💀 {attaquant['nom']} est KO (confusion) !")
                attaquant["xp_combats"] = max(0, attaquant.get("xp_combats", 0) - 1)
                equipe_ko_cnf  = equipe1 if attaquant in equipe1 else equipe2
                equipe_vict_cnf = equipe2 if attaquant in equipe1 else equipe1
                joueur_ko_cnf  = j1 if attaquant in equipe1 else j2
                joueur_vict_cnf = j2 if attaquant in equipe1 else j1
                col_vainqueur    = 4 - attaquant["slot"]
                colonne_vainqueur = [x for x in equipe_vict_cnf if x["slot"] == col_vainqueur]
                if attaquant in equipe1: pts2 += 1
                else: pts1 += 1
                for vainqueur in colonne_vainqueur:
                    ko_id = id(attaquant)
                    if vainqueur.get("ko") or ko_id in vainqueur.get("_xp_ko_ids", set()):
                        continue
                    vainqueur.setdefault("_xp_ko_ids", set()).add(ko_id)
                    vainqueur["xp_combats"] = vainqueur.get("xp_combats", 0) + 1
                    xp = vainqueur["xp_combats"]
                    evol_ko = vainqueur.get("evolution_ko")
                    evols_cond = vainqueur.get("evolutions_conditionnelles", [])
                    ko_requis = evol_ko or (evols_cond[0].get("evolution_ko") if evols_cond else None)
                    logs.append(f"    ⭐ {vainqueur['nom']} gagne 1 XP combat !" +
                                (f" ({xp}/{ko_requis} KO)" if ko_requis else ""))
                appliquer_effets_ko_synergie(
                    attaquant, equipe_ko_cnf, equipe_vict_cnf,
                    joueur_ko_cnf, joueur_vict_cnf, partie, logs)
            continue
        # Synergie Vol : cibler le défensif adverse si disponible
        joueur_att = j1 if attaquant in equipe1 else j2
        joueur_def = j2 if attaquant in equipe1 else j1
        equipe_att = equipe1 if attaquant in equipe1 else equipe2
        equipe_adv = equipe2 if attaquant in equipe1 else equipe1
        cible_reelle = defenseur

        # ── Déterminer le mode selon la POSITION du Pokémon ───────────────
        # Un Pokémon en position "off" utilise att_off
        # Un Pokémon en position "def" utilise att_def
        mode_attaquant = "off" if attaquant.get("position") == "off" else "def"

        # ── Jet de précision (sauf si attaque ne peut pas échouer) ────────
        att_nom = attaquant.get("att_off_nom" if mode_attaquant == "off" else "att_def_nom", "")
        ne_peut_echouer = att_nom in ATTAQUES_NE_PEUVENT_ECHOUER
        if not ne_peut_echouer and not jet_precision(attaquant, logs):
            continue  # Attaque ratée

        # ── Synergie Vol (seulement pour les offensifs) ───────────────────
        pal_vol = palier_synergie(joueur_att, "vol")
        types_norm_att = [_normaliser_type(t) for t in attaquant.get("types", [])]
        if mode_attaquant == "off" and pal_vol and "vol" in types_norm_att and jet_synergie(pal_vol):
            col_def = defenseur["slot"]
            support_adv = next((p for p in equipe_adv
                                if p["slot"] == col_def
                                and p["position"] == "def"
                                and not p.get("ko")), None)
            if support_adv:
                cible_reelle = support_adv
                bonus_vol = {3: 10, 6: 20, 9: 30}.get(pal_vol, 0)
                logs.append(f"    🦅 Synergie Vol : {attaquant['nom']} cible {support_adv['nom']} (support) +{bonus_vol} dégâts")
            else:
                logs.append(f"    🦅 Synergie Vol : pas de support adverse en col.{defenseur['slot']+1}, attaque normale")
                bonus_vol = 0
        else:
            bonus_vol = 0

        # ── Effet de l'attaque selon la position ──────────────────────────
        nouvelle_cible = appliquer_effet_attaque(
            attaquant, cible_reelle, joueur_att, joueur_def,
            equipe_att, equipe_adv, equipe_att,
            mode_attaquant, logs, partie
        )
        if nouvelle_cible:
            cible_reelle = nouvelle_cible

        # ── Un Pokémon défensif n'inflige pas de dégâts de base ───────────
        # Ses effets (att_def) sont déjà appliqués ci-dessus
        if mode_attaquant == "def":
            continue

        type_att = attaquant.get("att_off_type")
        dmg, eff  = calculer_degats(attaquant, cible_reelle, type_attaque=type_att)
        # Bonus Dragon
        if "dragon" in [_normaliser_type(t) for t in attaquant.get("types", [])]:
            pal_dragon = palier_synergie(joueur_att, "dragon")
            dmg += attaquant.get("_dmg_bonus", 0) if pal_dragon else 0
        # Bonus Vol
        dmg += bonus_vol
        # Réduction Roche côté défenseur
        pal_roche = palier_synergie(joueur_def, "roche")
        if pal_roche and "roche" in [_normaliser_type(t) for t in cible_reelle.get("types", [])]:
            reduction = {3: 10, 6: 20, 9: 30}.get(pal_roche, 0)
            dmg = max(0, dmg - reduction)
        cible_reelle["pv"] = max(0, cible_reelle.get("pv", 0) - dmg)
        logs.append(f"    ➤ {attaquant['nom']} attaque ({eff}) → {dmg} dégâts → {cible_reelle['nom']} {cible_reelle['pv']}PV")

        # ── Effets post-dégâts ────────────────────────────────────────────
        # Damoclès / Lumière du Néant / Caboche-Kaboum / Fracass'Tête / Roc Boulet
        if attaquant.pop("_degats_support_actif", False) and dmg > 0:
            equipe_adv_post = equipe2 if attaquant in equipe1 else equipe1
            support = _support_adverse(cible_reelle, equipe_adv_post)
            if support and not support.get("ko"):
                degats_support = dmg // 2
                support["pv"] = max(0, support.get("pv", 0) - degats_support)
                logs.append(f"    💥 {attaquant['nom']} : support {support['nom']} subit {degats_support} dégâts !")

        # Bélier : 10 dégâts fixes au support adverse
        if attaquant.pop("_belier_actif", False):
            equipe_adv_post = equipe2 if attaquant in equipe1 else equipe1
            support = _support_adverse(cible_reelle, equipe_adv_post)
            if support and not support.get("ko"):
                support["pv"] = max(0, support.get("pv", 0) - 10)
                logs.append(f"    💥 Bélier : support {support['nom']} subit 10 dégâts !")

        # Vol de vie : soin = moitié des dégâts infligés
        if attaquant.pop("_vol_vie_actif", False) and dmg > 0:
            soin = dmg // 2
            pv_avant = attaquant.get("pv", 0)
            attaquant["pv"] = min(attaquant.get("pv_max", 100), pv_avant + soin)
            logs.append(f"    💚 {attaquant['nom']} se soigne de {soin} PV ({pv_avant}→{attaquant['pv']})")

        # Zone colonne : les mêmes dégâts sur le support adverse
        if attaquant.pop("_zone_colonne", False) and dmg > 0:
            equipe_adv_post = equipe2 if attaquant in equipe1 else equipe1
            support = _support_adverse(cible_reelle, equipe_adv_post)
            if support and not support.get("ko"):
                support["pv"] = max(0, support.get("pv", 0) - dmg)
                logs.append(f"    💥 Zone : {support['nom']} subit aussi {dmg} dégâts !")

        # Effets post-attaque (statuts synergies)
        if dmg > 0:
            appliquer_effets_post_attaque(attaquant, cible_reelle, joueur_att, joueur_def, logs)
        defenseur = cible_reelle

        # Vérification KO après chaque attaque
        if cible_reelle["pv"] <= 0 and not cible_reelle.get("ko"):
            cible_reelle["ko"] = True
            cible_reelle["pv"] = 0
            soigner_statuts(cible_reelle)  # KO supprime tous les statuts
            logs.append(f"    💀 {cible_reelle['nom']} est KO !")
            cible_reelle["xp_combats"] = max(0, cible_reelle.get("xp_combats", 0) - 1)
            equipe_ko      = equipe1 if cible_reelle in equipe1 else equipe2
            equipe_vict    = equipe2 if cible_reelle in equipe1 else equipe1
            joueur_ko_ici  = j1 if cible_reelle in equipe1 else j2
            joueur_vict    = j2 if cible_reelle in equipe1 else j1
            col_vainqueur  = 4 - cible_reelle["slot"]
            colonne_vainqueur = [x for x in equipe_vict if x["slot"] == col_vainqueur]
            if cible_reelle in equipe1: pts2 += 1
            else:                       pts1 += 1
            for vainqueur in colonne_vainqueur:
                ko_id = id(cible_reelle)
                if vainqueur.get("ko") or ko_id in vainqueur.get("_xp_ko_ids", set()):
                    continue
                vainqueur.setdefault("_xp_ko_ids", set()).add(ko_id)
                vainqueur["xp_combats"] = vainqueur.get("xp_combats", 0) + 1
                xp = vainqueur["xp_combats"]
                evol_ko = vainqueur.get("evolution_ko")
                evols_cond = vainqueur.get("evolutions_conditionnelles", [])
                ko_requis = evol_ko or (evols_cond[0].get("evolution_ko") if evols_cond else None)
                logs.append(f"    ⭐ {vainqueur['nom']} gagne 1 XP combat !" +
                            (f" ({xp}/{ko_requis} KO)" if ko_requis else ""))
            # Synergies KO : Spectre + Combat
            appliquer_effets_ko_synergie(
                cible_reelle, equipe_ko, equipe_vict,
                joueur_ko_ici, joueur_vict, partie, logs)
            # Avancement immédiat : si l'offensif KO a un défensif derrière,
            # il avance en position offensive et peut encore attaquer ce tour
            if cible_reelle["position"] == "off":
                joueur_ko_obj = j1 if cible_reelle in equipe1 else j2
                defensif = next((p for p in joueur_ko_obj.get("pokemon", [])
                                 if p["position"] == "def"
                                 and p["slot"] == cible_reelle["slot"]
                                 and not p.get("ko")), None)
                if defensif:
                    defensif["position"] = "off"
                    equipe_ko.append(defensif)
                    logs.append(f"    ↑ {defensif['nom']} avance en position offensive (col. {defensif['slot'] + 1})")
                    # Chercher son adversaire (offensif miroir ou défensif)
                    col_def = 4 - defensif["slot"]
                    equipe_adv_ko = equipe_vict
                    adv = next((p for p in equipe_adv_ko
                                if p["slot"] == col_def and p["position"] == "off"
                                and not p.get("ko")), None) or                           next((p for p in equipe_adv_ko
                                if p["slot"] == col_def and p["position"] == "def"
                                and not p.get("ko")), None)
                    if adv:
                        # Insérer dans la file à la bonne position selon vitesse
                        vit = defensif.get("vitesse", 50)
                        insert_pos = idx_file
                        while insert_pos < len(file_attaques) and                               file_attaques[insert_pos][0].get("vitesse", 50) > vit:
                            insert_pos += 1
                        file_attaques.insert(insert_pos, (defensif, adv))

    # Effets post-combat synergies : Plante, Fée, Insecte
    bonus_force_j1, bonus_force_j2 = appliquer_effets_post_combat(
        j1, p1, j2, p2, equipe1, equipe2, partie, logs)

    # ── Résultat du combat : comparaison des forces totales ───────────────
    # Seuls les Pokémon encore en vie comptent
    def force_equipe(equipe):
        return sum(points_force_total(p) for p in equipe if not p.get("ko"))

    force1 = force_equipe(equipe1)
    force2 = force_equipe(equipe2)

    if force1 > force2:
        ecart = force1 - force2
        j2["pv"] = max(0, j2["pv"] - ecart)
        j1["serie_vic"] = j1.get("serie_vic", 0) + 1; j1["serie_def"] = 0
        j2["serie_def"] = j2.get("serie_def", 0) + 1; j2["serie_vic"] = 0
        gagnant, perdant = p1, p2
        logs.append(f"🏆 {p1} gagne ! (force {force1} vs {force2}) → {p2} perd {ecart} PV → {j2['pv']} PV")
    elif force2 > force1:
        ecart = force2 - force1
        j1["pv"] = max(0, j1["pv"] - ecart)
        j2["serie_vic"] = j2.get("serie_vic", 0) + 1; j2["serie_def"] = 0
        j1["serie_def"] = j1.get("serie_def", 0) + 1; j1["serie_vic"] = 0
        gagnant, perdant = p2, p1
        logs.append(f"🏆 {p2} gagne ! (force {force2} vs {force1}) → {p1} perd {ecart} PV → {j1['pv']} PV")
    else:
        gagnant, perdant = None, None
        logs.append(f"🤝 Égalité ! (force {force1} chacun)")

    # ── Dégâts directs : uniquement les offensifs sans adversaire ─────────
    degats_directs_j1, degats_directs_j2 = 0, 0
    for poke in sans_adv1:
        if poke.get("position") != "off" or poke.get("ko"):
            continue
        dmg = points_force_total(poke)
        degats_directs_j2 += dmg
        logs.append(f"  💥 {poke['nom']} (off) sans adversaire → {dmg} dégâts directs à {p2}")
    for poke in sans_adv2:
        if poke.get("position") != "off" or poke.get("ko"):
            continue
        dmg = points_force_total(poke)
        degats_directs_j1 += dmg
        logs.append(f"  💥 {poke['nom']} (off) sans adversaire → {dmg} dégâts directs à {p1}")

    # Bonus force Insecte (sur les dégâts directs)
    degats_directs_j2 += bonus_force_j1
    degats_directs_j1 += bonus_force_j2
    if bonus_force_j1: logs.append(f"  🐛 Bonus Insecte {p1} : +{bonus_force_j1} dégâts directs à {p2}")
    if bonus_force_j2: logs.append(f"  🐛 Bonus Insecte {p2} : +{bonus_force_j2} dégâts directs à {p1}")

    if degats_directs_j2 > 0:
        j2["pv"] = max(0, j2["pv"] - degats_directs_j2)
        logs.append(f"💢 {p2} subit {degats_directs_j2} dégâts directs → {j2['pv']} PV")
    if degats_directs_j1 > 0:
        j1["pv"] = max(0, j1["pv"] - degats_directs_j1)
        logs.append(f"💢 {p1} subit {degats_directs_j1} dégâts directs → {j1['pv']} PV")

    # Retirer les effets temporaires de début de combat (Eau, Dragon, Normal)
    retirer_effets_synergies_debut(equipe1, equipe2)

    # Réinitialiser compteurs Roulade/Taillade si Pokemon retiré ou KO
    for joueur_check in [j1, j2]:
        for poke in joueur_check.get("pokemon", []):
            if poke.get("ko") or poke.get("position") not in ("off", "def"):
                poke.pop("_roulade_compteur", None)
                poke.pop("_roulade_actif", None)
                poke.pop("_taillade_compteur", None)

    # Effets post-combat : PSN, BRN, Piégé
    for joueur_check in [j1, j2]:
        for poke in joueur_check.get("pokemon", []):
            if poke.get("ko"):
                continue
            statut = poke.get("statut")
            if statut == "PSN":
                poke["pv"] = max(0, poke.get("pv", 0) - 20)
                logs.append(f"    ☠️ {poke['nom']} est empoisonné → -20 PV → {poke['pv']}PV")
                if poke["pv"] <= 0:
                    poke["ko"] = True; poke["pv"] = 0
                    soigner_statuts(poke)
                    logs.append(f"    💀 {poke['nom']} est KO (poison) !")
            elif statut == "BRN":
                poke["pv"] = max(0, poke.get("pv", 0) - 10)
                logs.append(f"    🔥 {poke['nom']} est brûlé → -10 PV → {poke['pv']}PV")
                if poke["pv"] <= 0:
                    poke["ko"] = True; poke["pv"] = 0
                    soigner_statuts(poke)
                    logs.append(f"    💀 {poke['nom']} est KO (brûlure) !")
            if poke.get("piege") and not poke.get("ko"):
                poke["pv"] = max(0, poke.get("pv", 0) - 10)
                logs.append(f"    🪤 {poke['nom']} est piégé → -10 PV → {poke['pv']}PV")
                if poke["pv"] <= 0:
                    poke["ko"] = True; poke["pv"] = 0
                    soigner_statuts(poke)
                    logs.append(f"    💀 {poke['nom']} est KO (piège) !")

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

    # Cas spécial Évoli : évolution via synergie active (EVOLITIONS_MAP)
    if poke.get("id") == "0133":
        evol_id_evoli = calculer_evoli_forme(joueur)
        if evol_id_evoli and poke.get("xp_combats", 0) >= 3:
            evol_data = _get_poke(evol_id_evoli)
            if evol_data:
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
                return True, f"🌟 Évoli évolue en {evol_data['nom']} ! (+{diff_pv} PV → {poke['pv']}/{nouveau_pv_max})"
        return False, ""

    # Cas standard
    if not evol_id or evol_ko is None:
        # Vérifier evolutions_conditionnelles (ex: Leuphorie, Gourmelet)
        evols_cond = poke.get("evolutions_conditionnelles", [])
        if evols_cond:
            xp = poke.get("xp_combats", 0)
            synergies = calculer_synergies(joueur)
            for ec in evols_cond:
                if xp < ec.get("evolution_ko", 99):
                    continue
                cond = ec.get("condition", "")
                ok = False
                # Pas de condition → juste les KO suffisent
                if not cond:
                    ok = True
                # synergie_TYPE_N
                elif cond.startswith("synergie_") and "_ou_" not in cond and not cond.startswith("synergie_any_") and cond != "synergies_differentes_6":
                    parts = cond.split("_")
                    try:
                        palier_requis = int(parts[-1])
                        type_requis = "_".join(parts[1:-1])
                        ok = synergies.get(type_requis, 0) >= palier_requis
                    except ValueError:
                        pass
                # synergie_TYPE1_N_ou_TYPE2_N (double condition)
                elif "_ou_" in cond:
                    parts = cond.split("_ou_")
                    def check_syn(s):
                        p = s.replace("synergie_", "").rsplit("_", 1)
                        if len(p) == 2:
                            try:
                                return synergies.get(p[0], 0) >= int(p[1])
                            except ValueError:
                                pass
                        return False
                    ok = check_syn(parts[0]) or check_syn(parts[1])
                # synergie_any_N : n'importe quel type au palier N
                elif cond.startswith("synergie_any_"):
                    try:
                        palier = int(cond.split("_")[-1])
                        ok = any(v >= palier for v in synergies.values())
                    except ValueError:
                        pass
                # synergies_differentes_6 : au moins 6 types différents actifs
                elif cond == "synergies_differentes_6":
                    ok = len([v for v in synergies.values() if v >= 3]) >= 6
                elif cond == "position_offensive":
                    ok = poke.get("position") == "off"
                elif cond == "position_defensive":
                    ok = poke.get("position") == "def"
                if ok:
                    evol_data = _get_poke(ec["id"])
                    if evol_data:
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
                        appliquer_transformations(joueur)
                        return True, f"🌟 {ancien_nom} évolue en {ec['nom']} ! (+{diff_pv} PV → {poke['pv']}/{nouveau_pv_max})"
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
    appliquer_transformations(joueur)
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
        appliquer_transformations(j)
        # Centre Pokémon
        poke_centre = next((p for p in j.get("pokemon", []) if p["position"] == "centre"), None)
        if poke_centre:
            tours = poke_centre.get("soin_tours_restants", 1) - 1
            poke_centre["soin_tours_restants"] = tours
            if tours <= 0:
                poke_centre["pv"]       = poke_centre.get("pv_max", 100)
                soigner_statuts(poke_centre)
                poke_centre["position"] = "banc"
                slots_banc = {p["slot"] for p in j.get("pokemon", []) if p["position"] == "banc"}
                poke_centre["slot"] = next((i for i in range(10) if i not in slots_banc), 0)
                poke_centre.pop("soin_tours_restants", None)
                messages.append(f"💊 {poke_centre['nom']} de {pj} est soigné !")
        # Évolutions après le combat
        for msg_evol in verifier_evolutions(partie, j):
            messages.append(msg_evol)
        locked = j.get("boutique_locked", False)
        j["boutique_offre"]  = generer_offre_boutique(partie, j["niveau"],
                                                       ancienne_offre=j["boutique_offre"], locked=locked,
                                                       niveau_max_pool=j.get("niveau_max_pool", 10))
        j["boutique_locked"] = False
        j["a_achete_tour1"]  = False
    # Piocher le climat du prochain tour — visible au début du tour suivant
    piocher_climat(partie)
    return messages

def collecter_evolutions_a_venir(partie):
    """
    Retourne la liste des Pokémon qui vont évoluer ce tour,
    AVANT que l'évolution soit appliquée.
    [{pseudo, slot, position, id_avant, nom_avant, id_apres, nom_apres}]
    """
    evolutions = []
    for pj, j in partie["joueurs"].items():
        if not j.get("en_vie", True):
            continue
        for poke in j.get("pokemon", []):
            if poke.get("ko"):
                continue
            evol_id  = poke.get("evolution_id")
            evol_ko  = poke.get("evolution_ko")
            evol_nom = poke.get("evolution_nom")
            if not evol_id or evol_ko is None:
                continue
            if poke.get("xp_combats", 0) < evol_ko:
                continue
            evol_data = _get_poke(evol_id)
            if not evol_data:
                continue
            evolutions.append({
                "pseudo":    pj,
                "slot":      poke["slot"],
                "position":  poke["position"],
                "id_avant":  poke["id"],
                "nom_avant": poke["nom"],
                "id_apres":  evol_id,
                "nom_apres": evol_nom or evol_data.get("nom", evol_id),
            })
    return evolutions

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
    return templates.TemplateResponse(request, "index.html")

@app.get("/jeu/{code}", response_class=HTMLResponse)
async def jeu(request: Request, code: str):
    return templates.TemplateResponse(request, "jeu.html", {"code": code})

@app.post("/creer")
async def creer_partie(data: dict):
    pseudo = data.get("pseudo", "Joueur")
    code   = generer_code()
    joueur = etat_initial_joueur(pseudo)
    partie = {
        "code":          code,
        "tour":          0,
        "phase":         "attente",
        "hote":          pseudo,
        "joueurs":       {pseudo: joueur},
        "pool":          [],
        "pool_climat":   init_pool_climat(),
        "climat_actuel": "Ensoleillé",
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
            try:
                await traiter_action(code, pseudo, data)
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                print(f"[ERREUR] action={data.get('type','?')} pseudo={pseudo}\n{err}")
                await gestionnaire.envoyer_a(code, pseudo, {
                    "type": "erreur",
                    "msg": f"Erreur serveur : {e}",
                    "pour": pseudo,
                })
    except WebSocketDisconnect:
        gestionnaire.deconnecter(code, pseudo)
        await gestionnaire.diffuser(code, {"type": "joueur_deconnecte", "pseudo": pseudo})

# ── Actions WebSocket ─────────────────────────────────────────────────────────
async def traiter_action(code, pseudo, action):
    if code not in parties:
        return
    partie = parties[code]
    partie["derniere_activite"] = time.time()
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
        # Déblocage progressif : achat d'un Pokémon au niveau max actuel → débloque le suivant
        niv_poke = poke_data.get("niveau", 1)
        nmp = joueur.get("niveau_max_pool", 10)
        if niv_poke >= nmp and nmp < 15:
            joueur["niveau_max_pool"] = nmp + 1
        appliquer_bonus_pv_synergies(joueur)
        appliquer_transformations(joueur)
        await gestionnaire.diffuser(code, {
            "type": "etat_mis_a_jour", "etat": partie,
            "msg": f"⚡ {pseudo} capture {poke_data['nom']} !",
        })

    elif t == "forcer_fermeture_combat":
        if partie.get("hote") != pseudo:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Seul l'hôte peut forcer la fermeture !", "pour": pseudo})
            return
        await gestionnaire.diffuser(code, {
            "type": "forcer_fermeture_combat",
            "msg": f"⚡ {pseudo} a forcé la fermeture du combat.",
        })

    elif t == "choix_caroussel":
        pokemon_id = action.get("pokemon_id")
        caroussel  = partie.get("caroussel")
        if not caroussel or not caroussel.get("actif"):
            return
        ordre  = caroussel["ordre"]
        index  = caroussel["index"]
        if index >= len(ordre) or ordre[index] != pseudo:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Ce n'est pas votre tour de choisir !", "pour": pseudo})
            return
        dispo_ids = [p["id"] for p in caroussel["pokemon"]
                     if p["id"] not in caroussel["choisis"].values()]
        if pokemon_id not in dispo_ids:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Ce Pokémon n'est plus disponible !", "pour": pseudo})
            return
        await _appliquer_choix_caroussel(code, partie, gestionnaire, pseudo, pokemon_id)

    elif t == "vendre_pokemon":
        position = action.get("position")
        slot     = action.get("slot")
        poke = next((p for p in joueur["pokemon"]
                     if p["position"] == position and p["slot"] == slot), None)
        if not poke:
            return
        gain = poke.get("niveau", 1) + poke.get("xp_combats", 0)
        joueur["pokemon"].remove(poke)
        joueur["pieces"] += gain
        retourner_au_pool(partie, [poke["id"]])
        appliquer_bonus_pv_synergies(joueur)
        appliquer_transformations(joueur)
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
            nb_centres_max = nb_emplacements_centre(joueur["niveau"])
            nb_centres_occ = sum(1 for p in joueur["pokemon"] if p["position"] == "centre")
            if nb_centres_occ >= nb_centres_max:
                await gestionnaire.envoyer_a(code, pseudo, {
                    "type": "erreur", "msg": "Centre Pokémon plein !", "pour": pseudo})
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
                # Assigner le slot Centre libre correspondant à la case ciblée
                slots_centre = {p["slot"] for p in joueur["pokemon"] if p["position"] == "centre"}
                slot_centre  = ts if ts not in slots_centre else next((i for i in range(4) if i not in slots_centre), 0)
                poke_src["soin_tours_restants"] = points_force(poke_src)

        poke     = next((p for p in joueur["pokemon"] if p["position"] == fp and p["slot"] == fs), None)
        if not poke:
            return
        # Blocage KO vers terrain
        if poke.get("ko") and tp in ("off", "def"):
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": f"{poke['nom']} est KO et ne peut pas être placé sur le terrain !", "pour": pseudo})
            return
        # Blocage déplacement si piégé (sauf vente)
        if poke.get("piege") and tp != "vente":
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": f"{poke['nom']} est piégé et ne peut pas être déplacé !", "pour": pseudo})
            return
        # Pour le Centre, utiliser le slot libre calculé
        if tp == "centre":
            slots_centre_occ = {p["slot"] for p in joueur["pokemon"] if p["position"] == "centre"}
            ts = ts if ts not in slots_centre_occ else next((i for i in range(4) if i not in slots_centre_occ), 0)
        occupant = next((p for p in joueur["pokemon"] if p["position"] == tp and p["slot"] == ts), None)
        if occupant:
            occupant["position"] = fp
            occupant["slot"]     = fs
        poke["position"] = tp
        poke["slot"]     = ts
        appliquer_bonus_pv_synergies(joueur)
        appliquer_transformations(joueur)
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
            # Avancement automatique : si on retire un offensif, le défensif avance
            if position == "off":
                defensif = next((p for p in joueur["pokemon"]
                                 if p["position"] == "def" and p["slot"] == slot
                                 and not p.get("ko")), None)
                if defensif:
                    defensif["position"] = "off"
            appliquer_bonus_pv_synergies(joueur)
            appliquer_transformations(joueur)
            await gestionnaire.diffuser(code, {
                "type": "etat_mis_a_jour", "etat": partie,
                "msg": f"↩️ {pseudo} retire {poke['nom']} vers le banc",
            })

    elif t == "debug_capturer_evoli":
        evoli = _get_poke("0133")
        if evoli:
            slot_libre = next((i for i in range(10)
                if not any(p["slot"] == i and p["position"] == "banc"
                           for p in joueur.get("pokemon", []))), 0)
            nouveau = dict(evoli)
            nouveau["pv"]          = evoli["pv_max"]
            nouveau["position"]    = "banc"
            nouveau["slot"]        = slot_libre
            nouveau["xp_combats"]  = 0
            joueur.setdefault("pokemon", []).append(nouveau)
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "fin_tour", "etat": partie,
                "msg": "🧪 DEBUG : Évoli ajouté au banc !"
            })

    elif t == "lancer_combat":
        if partie.get("hote") != pseudo:
            await gestionnaire.envoyer_a(code, pseudo, {
                "type": "erreur", "msg": "Seul l'hôte peut lancer le combat !", "pour": pseudo})
            return
        partie["phase"] = "combat"
        try:
            # Snapshot léger AVANT le combat — uniquement les données nécessaires à l'arène
            def snapshot_joueur(j):
                return {
                    "niveau": j.get("niveau", 1),
                    "pokemon": [
                        {k: p.get(k) for k in ("id","nom","pv","pv_max","slot","position","ko","types")}
                        for p in j.get("pokemon", [])
                    ]
                }
            etat_avant_combat = {
                "joueurs": {pj: snapshot_joueur(j) for pj, j in partie["joueurs"].items()},
                "tour": partie.get("tour", 0),
                "climat_actuel": partie.get("climat_actuel", "Ensoleillé"),
            }
            resultats = lancer_combat(partie)
            partie["phase"] = "preparation"

            await gestionnaire.diffuser(code, {
                "type": "resultat_combat",
                "etat_avant": etat_avant_combat,
                "etat": partie,
                "resultats": resultats,
                "tour": partie["tour"],
            })

            evolutions_anim = collecter_evolutions_a_venir(partie)
            messages = appliquer_fin_tour(partie)
            await gestionnaire.diffuser(code, {
                "type": "fin_tour", "etat": partie,
                "msg": f"⏱️ Tour {partie['tour']} — " + " | ".join(messages),
                "evolutions": evolutions_anim,
            })
            # Carrousel tous les 4 tours (avant la boutique)
            if est_tour_caroussel(partie):
                preparer_caroussel(partie)
                await avancer_caroussel(code, partie, gestionnaire)
                # La boutique sera envoyée par terminer_caroussel()
            else:
                for pj, j in partie["joueurs"].items():
                    await gestionnaire.envoyer_a(code, pj, {
                        "type": "boutique_offre", "pour": pj,
                        "offre": j["boutique_offre"],
                        "tour": partie["tour"],
                        "tour1_gratuit": partie["tour"] <= 1,
                        "auto": True,
                    })
        except Exception as e:
            import traceback
            err = traceback.format_exc()
            print(f"[ERREUR COMBAT] tour={partie.get('tour','?')} code={code}\n{err}")
            partie["phase"] = "preparation"
            await gestionnaire.diffuser(code, {
                "type": "erreur",
                "msg": f"Erreur combat : {e}",
                "pour": None,
            })
