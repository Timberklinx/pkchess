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

ATT_DEF_CIBLE_ADVERSE = {
    "Attraction",
    "Baillement",
    "Balance",
    "Barrage",
    "Berceuse",
    "Bluff",
    "Boutefeu",
    "Boutefeu (Solaroc)",
    "Brouillard",
    "Cadeau",
    "Cage Eclair",
    "Cage Éclair",
    "Camaraderie",
    "Canicule",
    "Cataclysme",
    "Charme",
    "Chatouille",
    "Chaîne Malsaine",
    "Choc G-Max",
    "Choc Mental",
    "Choc Venin",
    "Clairvoyance",
    "Colére",
    "Confidence",
    "Copie",
    "Cortège Funèbre",
    "Cradovague",
    "Crochet Venin",
    "Croco Larme",
    "Cyclone",
    "Cœur de Rancœur",
    "Danse Flamme",
    "Danse Plumes",
    "Danse-Fleur",
    "Demi-Vie",
    "Dernier Mot",
    "Direct Toxik",
    "Double-Dard",
    "Doux Baiser",
    "Doux Parfum",
    "Dracosouffle",
    "Dynamopoing",
    "Décalcage",
    "Dépit",
    "Détrempage",
    "Détricanon",
    "Détritus",
    "Eboulement",
    "Ebullilave",
    "Ebullition",
    "Echange",
    "Eclair",
    "Eclair Croix",
    "Eclair Fou",
    "Ecrous d'Poing",
    "Electacle",
    "Electrisation",
    "Embargo",
    "Entrave",
    "Escarmouche",
    "Etincelle",
    "Etonnement",
    "Fatal-Foudre",
    "Feu Follet",
    "Feu Sacré",
    "Feu d'Enfer",
    "Fil Toxique",
    "Flair",
    "Flamme Croix",
    "Flamméche",
    "Flatterie",
    "Forte-Paume",
    "Foudre G-Max",
    "Frotte-Frimousse",
    "Fulmifer",
    "Garde Large",
    "Gaz Toxik",
    "Goudronnage",
    "Grand Courroux",
    "Gribouille",
    "Grimace",
    "Grincement",
    "Grobisou",
    "Groz'Yeux",
    "Hache de Pierre",
    "Halloween",
    "Harcélement",
    "Hurlement",
    "Hypnose",
    "Imitation",
    "Interversion",
    "Ire de la Nature",
    "Jet de Sable",
    "Lance-Flammes",
    "Léchouille",
    "Machination",
    "Malédiction (Spectre)",
    "Maléfice Sylvain",
    "Mimi-Queue",
    "Morphing",
    "Mortier Matcha",
    "Multitoxik",
    "Nuée de Poudre",
    "Octazooka",
    "Onde Folie",
    "Ondes Etranges",
    "Pactole G-Max",
    "Para-Spore",
    "Passe-Cadeau",
    "Percussion G-Max",
    "Pestilence G-Max",
    "Piege de Venin",
    "Piqué",
    "Plaquage",
    "Poing Eclair",
    "Poing de Feu",
    "Poudre Dodo",
    "Poudre Fureur",
    "Poudre Magique",
    "Poudre Toxik",
    "Poudreuse",
    "Provoc",
    "Pyroball G-Max",
    "Queue-Poison",
    "Queue-Poison (Séviper)",
    "Rafale Psy",
    "Rayon Signal",
    "Regard Glaçant",
    "Regard Médusant",
    "Regard Noir",
    "Regard Touchant",
    "Requiem",
    "Roue de Feu",
    "Rugissement",
    "Saisie",
    "Sentence G-Max",
    "Siffl'Herbe",
    "Siphon",
    "Soucigraine",
    "Spore",
    "Spore Coton",
    "Strido-Son",
    "Suc Digestif",
    "Sécrétion",
    "Séduction",
    "Talon-Marteau",
    "Thérémonie",
    "Toile",
    "Torpeur G-Max",
    "Toupie Eclat",
    "Tourbi-Sable",
    "Tourmente",
    "Toxik",
    "Troquenard",
    "Trou Noir",
    "Typhon Fulgurant",
    "Typhon Hivernal",
    "Télékinésie",
    "Téléport",
    "Ultrason",
    "Uppercut",
    "Vampigraine",
    "Vantardise",
    "Vapeur Féerique",
    "Verrou Enchanté",
    "Verrouillage",
    "Vibraqua",
    "Voile Miroir",
    "Vérouillage",
    "Zone Magique",
    "Étonnement",
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

def _jet_de(seuil, logs, nom, desc="", attaquant=None):
    """Lance un dé, retourne True si >= seuil. Si attaquant a _lire_esprit, +2 au résultat."""
    de = random.randint(1, 6)
    if attaquant and attaquant.get("_lire_esprit"):
        de = min(6, de + 2)
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

    # Si mode défensif et que la cible est None (pas d'adversaire en face)
    # → les attaques ciblant l'adversaire échouent, les attaques alliées continuent
    if mode == "def" and cible is None:
        if nom_att in ATT_DEF_CIBLE_ADVERSE:
            return None  # Pas d'adversaire, attaque échoue silencieusement
        # Attaque alliée : cible devient None, on continue

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
    elif nom_att == "Griffe Acier":
        if _jet_de(6, logs, nom, "[Griffe Acier] tente +10 attaque"):
            appliquer_bonus(pokemon, "bonus_attaque", 10)
            logs.append(f"    ⚔️ {nom} [Griffe Acier] : +10 Attaque")

    elif nom_att in {"Aiguisage", "Tranche", "Lame d'Acier", "Danse Lames",
                     "Boost", "Concentration", "Jackpot", "Coup d'Boue",
                     "Taillade"}:
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
    elif nom_att in {"Tonnerre", "Coup d'Jus",
                     "Crocs Eclair", "Crocs Éclair", "Stunt Spore",
                     "Para-Spore", "Onde Boréale"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente paralysie"):
            ok, msg = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé !")

    # ── Paralysie automatique (pas de dé) ─────────────────────────────────
    elif nom_att in {"Cage Eclair", "Cage Éclair", "Regard Médusant",
                     "Electro-Surf Survolté", "Elécanon", "Frotte-Frimousse"}:
        if not cible.get("statut"):
            ok, _ = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {cible['nom']} est paralysé !")

    # ── STATUT GEL ────────────────────────────────────────────────────────
    elif nom_att in {"Blizzard", "Laser Glace", "Crocs Givre", "Lyophilisation",
                     "Onde Glace", "Blizzard Poing", "Grêlon"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente gel"):
            ok, msg = appliquer_statut(cible, "FRZ")
            if ok: logs.append(f"    ❄️ {cible['nom']} est gelé !")

    # ── STATUT BRÛLURE ────────────────────────────────────────────────────
    elif nom_att in {"Lance-Flamme", "Crocs Feu",
                     "Déflagration", "Flammèche", "Flammeche"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente brûlure"):
            ok, msg = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")

    # ── Brûlure automatique (pas de dé) ───────────────────────────────────
    elif nom_att == "Feu Follet":
        if not cible.get("statut"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé !")

    # ── STATUT POISON ─────────────────────────────────────────────────────
    elif nom_att in {"Dard-Venin", "Bombe Beurk",
                     "Acide", "Fil Toxique", "Poudre Toxik"}:
        if not cible.get("statut") and _jet_de(6, logs, nom, f"[{nom_att}] tente poison"):
            ok, msg = appliquer_statut(cible, "PSN")
            if ok: logs.append(f"    ☠️ {cible['nom']} est empoisonné !")

    # ── Choc Venin : dégâts ×2 si cible PSN ──────────────────────────────
    elif nom_att == "Choc Venin":
        if cible.get("statut") == "PSN":
            appliquer_bonus(pokemon, "bonus_attaque", pokemon.get("degats", 20))
            logs.append(f"    ☠️ {nom} [Choc Venin] : dégâts doublés (cible empoisonnée) !")

    # ── Gaz Toxik : zone poison automatique ───────────────────────────────
    elif nom_att == "Gaz Toxik":
        for c in _cibles_colonne():
            if not c.get("statut"):
                ok, _ = appliquer_statut(c, "PSN")
                if ok: logs.append(f"    ☠️ {c['nom']} est empoisonné !")

    # ── STATUT SOMMEIL ────────────────────────────────────────────────────
    elif nom_att in {"Berceuse", "Grobisou",
                     "Chant", "Baillement"}:
        if not cible.get("statut"):
            ok, msg = appliquer_statut(cible, "SLP")
            if ok: logs.append(f"    😴 {cible['nom']} s'endort !")

    elif nom_att == "Hypnose":
        if not cible.get("statut") and _jet_de(4, logs, nom, "[Hypnose] tente sommeil"):
            ok, _ = appliquer_statut(cible, "SLP")
            if ok: logs.append(f"    😴 {cible['nom']} s'endort !")

    elif nom_att == "Poudre Dodo":
        de = random.randint(1, 6)
        if de <= 2:
            logs.append(f"    💨 [Poudre Dodo] échoue ! (dé: {de})")
        elif not cible.get("statut"):
            ok, _ = appliquer_statut(cible, "SLP")
            if ok: logs.append(f"    😴 {cible['nom']} s'endort ! [Poudre Dodo] (dé: {de})")

    # ── STATUT CONFUSION ──────────────────────────────────────────────────
    elif nom_att in {"Babil", "Danse Folle", "Doux Baiser",
                     "Onde Psy", "Tourbillon"}:
        if not cible.get("statut"):
            ok, msg = appliquer_statut(cible, "CNF")
            if ok: logs.append(f"    😵 {cible['nom']} est confus !")

    elif nom_att == "Choc Mental":
        if not cible.get("statut") and _jet_de(6, logs, nom, "[Choc Mental] tente confusion"):
            ok, _ = appliquer_statut(cible, "CNF")
            if ok: logs.append(f"    😵 {cible['nom']} est confus !")

    # ── ULTRASON (pièce → confusion, 50% = dé >= 4) ───────────────────────
    elif nom_att == "Octazooka":
        if _jet_de(4, logs, nom, "[Octazooka] tente malus précision"):
            appliquer_bonus(cible, "bonus_precision", -3)
            logs.append(f"    🎯 {cible['nom']} : -3 Précision (Octazooka)")

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
                if ok: logs.append(f"    ⚡ {c['nom']} est paralysé ! (Foudre G-Max)")
        pokemon["_zone_colonne"] = True

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

    elif nom_att == "Bec-Canon":
        # Brûlure si POKEMON attaque après l'adversaire
        attaque_apres = pokemon.get("vitesse", 50) < cible.get("vitesse", 50)
        if attaque_apres and not cible.get("statut"):
            ok, _ = appliquer_statut(cible, "BRN")
            if ok: logs.append(f"    🔥 {cible['nom']} est brûlé ! [Bec-Canon] (attaque après)")

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
                if ok: logs.append(f"    😴 {c['nom']} s'endort ! (Torpeur G-Max)")
        pokemon["_zone_colonne"] = True

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

    elif nom_att in {"Pactole G-Max", "Percussion G-Max"}:
        for c in _cibles_colonne():
            if not c.get("statut"):
                ok, _ = appliquer_statut(c, "CNF")
                if ok: logs.append(f"    😵 {c['nom']} est confus !")

    elif nom_att == "Sentence G-Max":
        for c in _cibles_colonne():
            if not c.get("statut"):
                ok, _ = appliquer_statut(c, "CNF")
                if ok: logs.append(f"    😵 {c['nom']} est confus ! (Sentence G-Max)")
        pokemon["_zone_colonne"] = True

    elif nom_att == "Uppercut":
        if not cible.get("statut") and _jet_de(5, logs, nom, "[Uppercut] tente confusion"):
            ok, _ = appliquer_statut(cible, "CNF")
            if ok: logs.append(f"    😵 {cible['nom']} est confus !")

    elif nom_att == "Vapeur Féerique":
        if not cible.get("statut") and _jet_de(4, logs, nom, "[Vapeur Féerique] tente confusion"):
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
        "Draco-Fléches", "Osmerang", "Tornade",
        "Lancécrou", "Lame Tachyonique", "Force Chtonienne",
        "Ocroupi", "Peignée", "Triple Pied", "Triple Plongeon",
        "Tranch'Air", "Eruption", "Giclédo",
        "Ecume", "Surf", "Bang Sonique",
    }:
        pokemon["_zone_colonne"] = True

    elif nom_att == "Explonuit":
        for c in _cibles_colonne():
            if _jet_de(4, logs, nom, f"[Explonuit] tente malus précision {c['nom']}"):
                appliquer_bonus(c, "bonus_precision", -3)
                logs.append(f"    🎯 {c['nom']} : -3 Précision (Explonuit)")
        pokemon["_zone_colonne"] = True

    elif nom_att == "Ouragan":
        for c in _cibles_colonne():
            if not c.get("peur") and _jet_de(6, logs, nom, f"[Ouragan] tente peur {c['nom']}"):
                c["peur"] = True
                logs.append(f"    😨 {c['nom']} a peur !")
        pokemon["_zone_colonne"] = True

    elif nom_att in {"Eboulement", "Ecrous d'Poing"}:
        for c in _cibles_colonne():
            if not c.get("peur") and _jet_de(5, logs, nom, f"[{nom_att}] tente peur {c['nom']}"):
                c["peur"] = True
                logs.append(f"    😨 {c['nom']} a peur !")
        pokemon["_zone_colonne"] = True

    elif nom_att == "Chant Antique":
        for c in _cibles_colonne():
            if not c.get("statut") and _jet_de(5, logs, nom, f"[Chant Antique] tente sommeil {c['nom']}"):
                ok, _ = appliquer_statut(c, "SLP")
                if ok: logs.append(f"    😴 {c['nom']} s'endort !")
        pokemon["_zone_colonne"] = True

    elif nom_att == "Canicule":
        for c in _cibles_colonne():
            if not c.get("statut") and _jet_de(6, logs, nom, f"[Canicule] tente brûlure {c['nom']}"):
                ok, _ = appliquer_statut(c, "BRN")
                if ok: logs.append(f"    🔥 {c['nom']} est brûlé !")
        pokemon["_zone_colonne"] = True

    # ── ZONE + effet supplémentaire ────────────────────────────────────────

    elif nom_att == "Aboiement":
        # Zone + malus attaque X sur les 2
        for c in _cibles_colonne():
            appliquer_bonus(c, "bonus_attaque", -X)
            logs.append(f"    📉 {c['nom']} : -{X} Attaque (Aboiement)")
        pokemon["_zone_colonne"] = True

    elif nom_att == "Bain de Smog":
        # Zone + supprime tous les boosts
        for c in _cibles_colonne():
            c["bonus_attaque"]   = 0
            c["bonus_defense"]   = 0
            c["bonus_vitesse"]   = 0
            c["bonus_precision"] = 0
            logs.append(f"    🧹 {c['nom']} : tous les boosts supprimés !")
        pokemon["_zone_colonne"] = True

    elif nom_att == "Boue-Bombe":
        # Zone + dé 5-6 malus précision Y
        for c in _cibles_colonne():
            if _jet_de(5, logs, nom, f"[Boue-Bombe] tente malus précision {c['nom']}"):
                appliquer_bonus(c, "bonus_precision", -Y)
                logs.append(f"    🎯 {c['nom']} : -{Y} Précision")
        pokemon["_zone_colonne"] = True

    elif nom_att == "Eclat Magique":
        # Zone + malus précision 2
        for c in _cibles_colonne():
            appliquer_bonus(c, "bonus_precision", -2)
            logs.append(f"    🎯 {c['nom']} : -2 Précision (Eclat Magique)")
        pokemon["_zone_colonne"] = True

    elif nom_att == "Ere Glaciaire":
        # Zone + malus vitesse 50
        for c in _cibles_colonne():
            appliquer_bonus(c, "bonus_vitesse", -50)
            c["vitesse"] = max(5, c.get("vitesse", 50) - 50)
            logs.append(f"    🐢 {c['nom']} : -50 Vitesse (Ere Glaciaire)")
        pokemon["_zone_colonne"] = True
        # Marquer pour toucher aussi le support adverse (traité après calcul dégâts)
        pokemon["_zone_colonne"] = True

    # ══════════════════════════════════════════════════════════════════════
    # ATT_DEF — BOOSTS SIMPLES (cible = offensif allié)
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Boul'Armure", "Cotogarde"}:
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_defense", X)
            logs.append(f"    🛡️ {nom} [{nom_att}] : {offensif['nom']} +{X} Défense")

    elif nom_att == "Aucune":
        pass  # Pas d'attaque défensive

    elif nom_att == "Trempette":
        pass  # Aucun effet

    elif nom_att == "Vigilance":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_vigilance"] = True
            logs.append(f"    👁️ {nom} [Vigilance] : {offensif['nom']} protégé du prochain changement de statut")

    elif nom_att == "Rune Protect":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_rune_protect"] = True
            logs.append(f"    🔮 {nom} [Rune Protect] : {offensif['nom']} protégé des statuts jusqu'au prochain combat")

    elif nom_att == "Ténacité":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and not offensif.get("_tenacite_used"):
            offensif["_tenacite"] = True
            logs.append(f"    💪 {nom} [Ténacité] : {offensif['nom']} ne peut pas tomber KO (min 5 PV)")

    elif nom_att in {"Voeu Soin", "Vœu Soin"}:
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_voeu_soin"] = True
            logs.append(f"    💚 {nom} [Vœu Soin] : {offensif['nom']} soigné intégralement si allié KO")

    elif nom_att == "Tourniquet":
        for p in list(equipe_att) + list(equipe_adv):
            if p.get("ko"): continue
            if _normaliser_type(p.get("att_off_type", "") or "") == "feu":
                appliquer_bonus(p, "bonus_attaque", -X)
                logs.append(f"    🌀 [Tourniquet] : {p['nom']} -{X} Attaque (att Feu)")

    elif nom_att == "Rempart Brûlant":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_defense", X)
            offensif["_rempart_brulant"] = True
            logs.append(f"    🔥 {nom} [Rempart Brûlant] : {offensif['nom']} +{X} Défense + brûle les attaquants")

    elif nom_att == "Souvenir":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_souvenir"] = X
            logs.append(f"    💭 {nom} [Souvenir] : si {offensif['nom']} KO → {cible['nom'] if cible else 'adversaire'} -{X} Attaque")

    elif nom_att == "Rale Male":
        pokemon["_rale_male"] = X
        logs.append(f"    😤 {nom} [Râle Mâle] : +{X} Attaque si {nom} subit des dégâts ce tour")

    elif nom_att == "Permuvitesse":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and cible:
            vit_off = offensif.get("vitesse", 50)
            vit_adv = cible.get("vitesse", 50)
            offensif["vitesse"] = vit_adv
            cible["vitesse"] = vit_off
            logs.append(f"    🔄 {nom} [Permuvitesse] : {offensif['nom']} ↔ {cible['nom']} vitesses échangées")

    elif nom_att == "Permuforce":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and cible:
            deg_off = offensif.get("degats", 20)
            deg_adv = cible.get("degats", 20)
            offensif["degats"] = deg_adv
            cible["degats"] = deg_off
            logs.append(f"    🔄 {nom} [Permuforce] : dégâts échangés ({deg_adv} ↔ {deg_off})")

    elif nom_att == "Echange Psy":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and offensif.get("statut") and cible and not cible.get("statut"):
            statut = offensif["statut"]
            appliquer_statut(cible, statut)
            retirer_statut(offensif)
            logs.append(f"    🔄 [Échange Psy] : statut {statut} transféré à {cible['nom']}")

    elif nom_att == "Géo-Contrôle":
        synergies_adv = joueur_def.get("synergies", {})
        if synergies_adv:
            type_max = max(synergies_adv, key=synergies_adv.get)
            palier_actuel = synergies_adv[type_max]
            nouveau = {9: 6, 6: 3, 3: 0}.get(palier_actuel, 0)
            if nouveau == 0:
                del joueur_def["synergies"][type_max]
            else:
                joueur_def["synergies"][type_max] = nouveau
            joueur_def.setdefault("_geo_controle_restore", []).append((type_max, palier_actuel))
            logs.append(f"    🌍 [Géo-Contrôle] : synergie {type_max} adverse {palier_actuel}→{nouveau}")

    elif nom_att == "Buée Noire":
        col = pokemon.get("slot", 0)
        for p in equipe_att + equipe_adv:
            if p.get("slot") == col and not p.get("ko"):
                p["bonus_attaque"] = 0; p["bonus_defense"] = 0
                p["bonus_vitesse"] = 0; p["bonus_precision"] = 0
                logs.append(f"    🌫️ [Buée Noire] : {p['nom']} tous les boosts annulés")

    elif nom_att == "Larme a I'Oeil":
        pokemon["_larme_oeil"] = True
        logs.append(f"    😢 {nom} [Larme à l'Œil] : prochaine attaque ciblant {nom} réduite de moitié")

    elif nom_att == "Pico-Défense":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_defense", X)
            offensif["_pico_defense"] = X
            logs.append(f"    🛡️ {nom} [Pico-Défense] : {offensif['nom']} +{X} Déf, attaquants -{X} PV")

    elif nom_att == "Piege de Fil":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_piege_fil"] = X
            logs.append(f"    🕸️ {nom} [Piège de Fil] : prochain attaquant -{X} Att/Vit")

    elif nom_att == "Rancune":
        pokemon["_rancune"] = True
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_rancune"] = True
        logs.append(f"    😡 {nom} [Rancune] : si KO → l'adversaire défausse un Pokémon du banc")

    elif nom_att == "Voile Aurore":
        for p in equipe_att:
            if not p.get("ko"):
                p["_voile_aurore"] = True
        logs.append(f"    🌅 {nom} [Voile Aurore] : dégâts reçus /2 pour toute l'équipe")

    elif nom_att == "Vol Magnétik":
        col = pokemon.get("slot", 0)
        for p in equipe_att:
            if p.get("slot") == col and not p.get("ko"):
                p["_vol_magnetik"] = True
        logs.append(f"    🧲 {nom} [Vol Magnétik] : colonne immunisée aux attaques Sol")

    elif nom_att == "Zone Etrange":
        col = pokemon.get("slot", 0)
        for p in equipe_att + equipe_adv:
            if p.get("slot") == col and not p.get("ko"):
                for champ in ["bonus_attaque", "bonus_defense", "bonus_vitesse"]:
                    p[champ] = -p.get(champ, 0)
                logs.append(f"    🔄 [Zone Étrange] : {p['nom']} bonus/malus inversés")

    elif nom_att == "Renversement":
        if cible:
            def_adv = next((p for p in equipe_adv if p.get("position") == "def"
                           and p.get("slot") == cible.get("slot") and not p.get("ko")), None)
            if def_adv:
                cible["position"], def_adv["position"] = def_adv["position"], cible["position"]
                logs.append(f"    🔄 {nom} [Renversement] : {cible['nom']} ↔ {def_adv['nom']} positions échangées")

    elif nom_att == "Repli":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["position"], pokemon["position"] = "def", "off"
            appliquer_bonus(offensif, "bonus_defense", X)
            logs.append(f"    🔄 {nom} [Repli] : {nom} avance, {offensif['nom']} recule +{X} Défense")

    elif nom_att == "Relais":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_vitesse", X)
            offensif["vitesse"] = offensif.get("vitesse", 50) + X
            pokemon["ko"] = True; pokemon["pv"] = 0  # se retire du combat
            logs.append(f"    🔄 {nom} [Relais] : {nom} se retire, {offensif['nom']} +{X} Vitesse")

    elif nom_att == "Astuce Force":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and cible:
            for champ in ["bonus_attaque", "bonus_defense", "bonus_vitesse"]:
                offensif[champ], cible[champ] = cible.get(champ, 0), offensif.get(champ, 0)
            logs.append(f"    🔄 [Astuce Force] : bonus échangés {offensif['nom']} ↔ {cible['nom']}")

    elif nom_att == "Camouflage":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            compteur = {}
            for p in equipe_att + equipe_adv:
                if not p.get("ko"):
                    for t in p.get("types", []):
                        tn = _normaliser_type(t)
                        compteur[tn] = compteur.get(tn, 0) + 1
            if compteur:
                type_max = max(compteur, key=compteur.get)
                offensif["_types_orig"] = offensif.get("types", [])
                offensif["types"] = [type_max]
                logs.append(f"    🎭 {nom} [Camouflage] : {offensif['nom']} devient type {type_max}")

    elif nom_att == "Conversion":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and offensif.get("types"):
            pokemon["_types_orig"] = pokemon.get("types", [])
            pokemon["types"] = [_normaliser_type(offensif["types"][0])]
            logs.append(f"    🎭 {nom} [Conversion] : {nom} devient type {offensif['types'][0]}")

    elif nom_att == "Copie-Type":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and cible:
            offensif["_types_orig"] = offensif.get("types", [])
            offensif["types"] = list(cible.get("types", []))
            logs.append(f"    🎭 {nom} [Copie-Type] : {offensif['nom']} copie le type de {cible['nom']}")

    elif nom_att == "Déluge Plasmique":
        for p in equipe_att:
            if not p.get("ko") and _normaliser_type(p.get("att_off_type", "") or "") == "normal":
                p["_att_type_override"] = "electrik"
                logs.append(f"    ⚡ [Déluge Plasmique] : {p['nom']} att Normal→Électrik ce tour")

    elif nom_att == "Abri":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_defense", X)
            logs.append(f"    🛡️ {nom} [Abri] : {offensif['nom']} +{X} Défense ce tour")

    elif nom_att == "Blocage":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_defense", X)
            logs.append(f"    🛡️ {nom} [Blocage] : {offensif['nom']} +{X} Défense ce tour")
            # Supprime un bonus au hasard sur l'adversaire ciblant l'offensif
            if cible:
                bonus_adv = [(k, v) for k, v in [
                    ("bonus_attaque", cible.get("bonus_attaque", 0)),
                    ("bonus_defense", cible.get("bonus_defense", 0)),
                    ("bonus_vitesse", cible.get("bonus_vitesse", 0)),
                ] if v > 0]
                if bonus_adv:
                    champ, val = random.choice(bonus_adv)
                    cible[champ] = 0
                    logs.append(f"    📉 [Blocage] : {cible['nom']} perd son {champ} ({val})")

    elif nom_att == "Blockhaus":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_blockhaus"] = X  # Réduit la prochaine attaque de X + empoisonne l'attaquant
            logs.append(f"    🏰 {nom} [Blockhaus] : prochaine attaque sur {offensif['nom']} réduite de {X} + poison")

    elif nom_att == "Tatamigaeshi":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_tatamigaeshi"] = True  # Protégé de tout sauf l'offensif adverse direct
            logs.append(f"    🥋 {nom} [Tatamigaeshi] : {offensif['nom']} protégé des dégâts indirects")

    elif nom_att == "Prévention":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_prevention"] = True  # Dégâts reçus divisés par 2 pour la suite du tour
            logs.append(f"    🛡️ {nom} [Prévention] : {offensif['nom']} dégâts réduits de 50% ce tour")
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_defense", X)
            logs.append(f"    🛡️ {nom} [{nom_att}] : {offensif['nom']} +{X} Défense")

    elif nom_att in {"Grondement", "Lumiqueue", "Rengorgement", "Yoga"}:
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_attaque", X)
            logs.append(f"    ⚔️ {nom} [{nom_att}] : {offensif['nom']} +{X} Attaque")

    elif nom_att == "Gonflette":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_attaque", X)
            appliquer_bonus(offensif, "bonus_defense", X)
            logs.append(f"    💪 {nom} [Gonflette] : {offensif['nom']} +{X} Att/Déf")

    elif nom_att == "Plénitude":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_attaque", X)
            appliquer_bonus(offensif, "bonus_defense", X)
            logs.append(f"    ✨ {nom} [Plénitude] : {offensif['nom']} +{X} Att/Déf")

    elif nom_att == "Enroulement":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_attaque", X)
            appliquer_bonus(offensif, "bonus_defense", X)
            appliquer_bonus(offensif, "bonus_precision", Y)
            logs.append(f"    🌀 {nom} [Enroulement] : {offensif['nom']} +{X} Att/Déf +{Y} Précision")

    elif nom_att == "Garde Florale":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            bonus = X * 2 if "plante" in [_normaliser_type(t) for t in offensif.get("types", [])] else X
            appliquer_bonus(offensif, "bonus_defense", bonus)
            logs.append(f"    🌸 {nom} [Garde Florale] : {offensif['nom']} +{bonus} Défense")

    elif nom_att == "Grand Nettoyage":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_attaque", X)
            appliquer_bonus(offensif, "bonus_vitesse", X)
            offensif["vitesse"] = offensif.get("vitesse", 50) + X
            offensif.pop("piege", None)
            logs.append(f"    🧹 {nom} [Grand Nettoyage] : {offensif['nom']} +{X} Att/Vit, piège retiré")

    elif nom_att == "Mur de Fer":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_defense", X)
            logs.append(f"    🏰 {nom} [Mur de Fer] : {offensif['nom']} +{X} Défense")
        # Colonnes adjacentes
        col = pokemon.get("slot", 0)
        for adj_col in [col - 1, col + 1]:
            adj = next((p for p in equipe_att if p.get("slot") == adj_col
                       and p.get("position") == "off" and not p.get("ko")), None)
            if adj:
                appliquer_bonus(adj, "bonus_defense", X)
                logs.append(f"    🏰 [Mur de Fer] : {adj['nom']} (adjacent) +{X} Défense")

    elif nom_att == "Mur Fumigène":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_defense", X)
            offensif["_malus_precision_entrant"] = 2
            logs.append(f"    🌫️ {nom} [Mur Fumigène] : {offensif['nom']} +{X} Déf, -2 précision attaquants")

    elif nom_att == "Nappage":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_attaque", X)
            if len(offensif.get("types", [])) < 2:
                offensif["types"] = offensif.get("types", []) + ["fee"]
            logs.append(f"    🧁 {nom} [Nappage] : {offensif['nom']} +{X} Att + type Fée")

    elif nom_att == "Neuf pour Un":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_attaque", X)
            appliquer_bonus(offensif, "bonus_defense", X)
            appliquer_bonus(offensif, "bonus_vitesse", X)
            offensif["vitesse"] = offensif.get("vitesse", 50) + X
            logs.append(f"    9️⃣ {nom} [Neuf pour Un] : {offensif['nom']} +{X} Att/Déf/Vit")
        # Bonus sur Évoli également
        evoli = next((p for p in equipe_att if p.get("id") == "0133" and not p.get("ko")), None)
        if evoli and evoli is not offensif:
            appliquer_bonus(evoli, "bonus_attaque", X)
            appliquer_bonus(evoli, "bonus_defense", X)
            appliquer_bonus(evoli, "bonus_vitesse", X)
            evoli["vitesse"] = evoli.get("vitesse", 50) + X
            logs.append(f"    9️⃣ [Neuf pour Un] : Évoli +{X} Att/Déf/Vit")

    elif nom_att == "Croissance":
        for p in equipe_att:
            if p.get("ko"): continue
            if "plante" in [_normaliser_type(t) for t in p.get("types", [])]:
                appliquer_bonus(p, "bonus_attaque", X)
                logs.append(f"    🌱 {nom} [Croissance] : {p['nom']} +{X} Attaque")

    elif nom_att == "Fertilisation":
        for p in equipe_att:
            if p.get("ko"): continue
            if "plante" in [_normaliser_type(t) for t in p.get("types", [])]:
                appliquer_bonus(p, "bonus_attaque", X)
                logs.append(f"    🌻 {nom} [Fertilisation] : {p['nom']} +{X} Attaque")

    elif nom_att == "Lance-Boue":
        for p in list(equipe_att) + list(equipe_adv):
            if p.get("ko"): continue
            att_type = _normaliser_type(p.get("att_off_type", "") or "")
            if att_type == "electrik":
                appliquer_bonus(p, "bonus_attaque", -X)
                logs.append(f"    💧 {nom} [Lance-Boue] : {p['nom']} -{X} Attaque (attaque Électrik)")

    # ── SOINS ─────────────────────────────────────────────────────────────

    elif nom_att == "E-Coque":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            soin = offensif.get("pv_max", 100) // 2
            offensif["pv"] = min(offensif.get("pv_max", 100), offensif.get("pv", 0) + soin)
            logs.append(f"    💚 {nom} [E-Coque] : {offensif['nom']} +{soin} PV")

    elif nom_att == "Purification":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            soigner_statuts(offensif)
            soin = offensif.get("pv_max", 100) // 2
            offensif["pv"] = min(offensif.get("pv_max", 100), offensif.get("pv", 0) + soin)
            logs.append(f"    💚 {nom} [Purification] : {offensif['nom']} statut soigné +{soin} PV")

    elif nom_att == "Aurore":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and not offensif.get("_att_def_annulee"):
            mult = appliquer_soins_climat(partie.get("climat_actuel"), nom_att)
            if mult == 0.0:
                logs.append(f"    🌙 [Nuit] : Aurore ne fonctionne pas !")
            else:
                soin = int(X * mult)
                offensif["pv"] = min(offensif.get("pv_max", 100), offensif.get("pv", 0) + soin)
                logs.append(f"    💚 {nom} [Aurore] : {offensif['nom']} +{soin} PV" +
                            (f" (×{mult} {partie.get('climat_actuel','')})" if mult != 1.0 else ""))

    elif nom_att in {"Rayon Lune"}:
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            mult = appliquer_soins_climat(partie.get("climat_actuel"), nom_att)
            soin = int(X * mult)
            offensif["pv"] = min(offensif.get("pv_max", 100), offensif.get("pv", 0) + soin)
            logs.append(f"    💚 {nom} [Rayon Lune] : {offensif['nom']} +{soin} PV" +
                        (f" (×{mult} {partie.get('climat_actuel','')})" if mult != 1.0 else ""))

    elif nom_att == "Synthése":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and not offensif.get("_att_def_annulee"):
            mult = appliquer_soins_climat(partie.get("climat_actuel"), nom_att)
            if mult == 0.0:
                logs.append(f"    🌙 [Nuit] : Synthèse ne fonctionne pas !")
            else:
                bonus_plante = 10 if "plante" in [_normaliser_type(t) for t in offensif.get("types", [])] else 0
                soin = int((X + bonus_plante) * mult)
                offensif["pv"] = min(offensif.get("pv_max", 100), offensif.get("pv", 0) + soin)
                logs.append(f"    💚 {nom} [Synthèse] : {offensif['nom']} +{soin} PV" +
                            (f" (×{mult} {partie.get('climat_actuel','')})" if mult != 1.0 else ""))

    elif nom_att == "Vol-Force":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and cible:
            soin = cible.get("degats", 20)
            offensif["pv"] = min(offensif.get("pv_max", 100), offensif.get("pv", 0) + soin)
            appliquer_bonus(cible, "bonus_attaque", -X)
            logs.append(f"    💚 {nom} [Vol-Force] : {offensif['nom']} +{soin} PV, {cible['nom']} -{X} Attaque")

    # ── EFFETS SPÉCIAUX SIMPLES ────────────────────────────────────────────

    elif nom_att == "Acupression":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            stat = random.choice(["bonus_attaque", "bonus_defense", "bonus_vitesse", "bonus_precision"])
            val = Y if stat == "bonus_precision" else X
            appliquer_bonus(offensif, stat, val)
            if stat == "bonus_vitesse":
                offensif["vitesse"] = offensif.get("vitesse", 50) + val
            logs.append(f"    🎯 {nom} [Acupression] : {offensif['nom']} +{val} {stat}")

    elif nom_att == "Air Veinard":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and offensif.get("faiblesses"):
            faiblesse = random.choice(offensif["faiblesses"])
            offensif["faiblesses"] = [f for f in offensif["faiblesses"] if f != faiblesse]
            offensif.setdefault("_faiblesses_temp_supprimees", []).append(faiblesse)
            logs.append(f"    🍀 {nom} [Air Veinard] : {offensif['nom']} perd faiblesse {faiblesse} ce tour")

    elif nom_att == "Amnésie":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["bonus_attaque"]   = max(0, offensif.get("bonus_attaque", 0))
            offensif["bonus_defense"]   = max(0, offensif.get("bonus_defense", 0))
            offensif["bonus_vitesse"]   = max(0, offensif.get("bonus_vitesse", 0))
            offensif["bonus_precision"] = max(0, offensif.get("bonus_precision", 0))
            soigner_statuts(offensif)
            logs.append(f"    🧠 {nom} [Amnésie] : {offensif['nom']} effets négatifs annulés")

    elif nom_att == "Anti-Soin":
        pokemon["_anti_soin_actif"] = True
        for p in equipe_att + equipe_adv:
            p["_anti_soin"] = True
        logs.append(f"    🚫 {nom} [Anti-Soin] : soins via attaques bloqués ce combat")

    elif nom_att == "Brume":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_brume"] = True
            logs.append(f"    🌫️ {nom} [Brume] : {offensif['nom']} protégé des baisses de stats")

    elif nom_att == "Cognobidon":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            perte = valeur_x(pokemon.get("niveau", 1))
            pokemon["pv"] = max(0, pokemon.get("pv", 0) - perte)
            appliquer_bonus(offensif, "bonus_attaque", perte)
            logs.append(f"    💥 {nom} [Cognobidon] : -{perte} PV sur {nom}, {offensif['nom']} +{perte} Attaque")

    elif nom_att == "Décharnement":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            perte = pokemon.get("pv", 0) // 2
            pokemon["pv"] = max(0, pokemon.get("pv", 0) - perte)
            appliquer_bonus(offensif, "bonus_attaque", perte)
            appliquer_bonus(offensif, "bonus_vitesse", perte)
            offensif["vitesse"] = offensif.get("vitesse", 50) + perte
            logs.append(f"    ⚡ {nom} [Décharnement] : -{perte} PV, {offensif['nom']} +{perte} Att/Vit")

    elif nom_att == "Force Cosmique":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and cible:
            type_att_adv = _normaliser_type(cible.get("att_off_type", "") or "")
            if type_att_adv and type_att_adv not in [_normaliser_type(r) for r in offensif.get("resistances", [])]:
                offensif.setdefault("resistances", []).append(type_att_adv)
                offensif.setdefault("_resistances_temp", []).append(type_att_adv)
                logs.append(f"    🌌 {nom} [Force Cosmique] : {offensif['nom']} résiste à {type_att_adv}")

    elif nom_att == "Garde-a-Joues":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_defense", X)
            logs.append(f"    🛡️ {nom} [Garde-à-Joues] : {offensif['nom']} +{X} Défense (objet sacrifié)")

    elif nom_att == "Gardomax":
        # POKEMON Gigamax encaisse les dégâts à la place de l'offensif
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_gardomax"] = id(pokemon)
            pokemon["_gardomax_actif"] = True
            logs.append(f"    🛡️ {nom} [Gardomax] : encaisse les dégâts à la place de {offensif['nom']}")

    elif nom_att == "Danse Folle":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and not offensif.get("statut"):
            ok, _ = appliquer_statut(offensif, "CNF")
            if ok: logs.append(f"    😵 {offensif['nom']} est confus ! (Danse Folle)")
        for c in _cibles_colonne():
            if not c.get("statut"):
                ok, _ = appliquer_statut(c, "CNF")
                if ok: logs.append(f"    😵 {c['nom']} est confus ! (Danse Folle)")

    # ══════════════════════════════════════════════════════════════════════
    # ATT_DEF COMPLEXES
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att == "Cri Draconique":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and _jet_de(5, logs, nom, "[Cri Draconique] tente bonus prochaine attaque"):
            est_dragon = "dragon" in [_normaliser_type(t) for t in offensif.get("types", [])]
            bonus = 40 if est_dragon else 20
            appliquer_bonus(offensif, "bonus_attaque", bonus)
            logs.append(f"    🐉 {nom} [Cri Draconique] : {offensif['nom']} +{bonus} sur prochaine attaque")

    elif nom_att == "Puissance":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_puissance_actif"] = True
            logs.append(f"    💥 {nom} [Puissance] : {offensif['nom']} lance le dé à son attaque ce tour")

    elif nom_att == "Danse Victoire":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_attaque", 30)
            appliquer_bonus(offensif, "bonus_defense", 30)
            offensif["_danse_victoire"] = True  # flag pour +10 par KO jusqu'à +50
            logs.append(f"    🏆 {nom} [Danse Victoire] : {offensif['nom']} +30 Att/Déf")

    elif nom_att == "Dracacophonie":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            pal_dragon = palier_synergie(joueur_att, "dragon")
            if pal_dragon < 9:
                offensif["pv"] = max(0, offensif.get("pv", 0) - 50)
                logs.append(f"    🐲 {offensif['nom']} perd 50 PV (Dracacophonie)")
            appliquer_bonus(offensif, "bonus_attaque", X)
            appliquer_bonus(offensif, "bonus_defense", X)
            appliquer_bonus(offensif, "bonus_vitesse", X)
            offensif["vitesse"] = offensif.get("vitesse", 50) + X
            logs.append(f"    🐲 {nom} [Dracacophonie] : {offensif['nom']} +{X} Att/Déf/Vit")

    elif nom_att == "Ultime Bastion":
        appliquer_bonus(pokemon, "bonus_attaque", 30)
        appliquer_bonus(pokemon, "bonus_defense", 30)
        appliquer_bonus(pokemon, "bonus_vitesse", 30)
        pokemon["vitesse"] = pokemon.get("vitesse", 50) + 30
        appliquer_bonus(pokemon, "bonus_precision", 3)
        pokemon["_ancrage"] = True  # Ne peut plus être retiré (sans dégâts de piège)
        logs.append(f"    🏰 {nom} [Ultime Bastion] : +30 Att/Déf/Vit +3 Précision, ancré !")

    elif nom_att == "Dernier mot":
        # Malus attaque X sur l'offensif adverse + swap POKEMON ↔ offensif allié
        if cible:
            appliquer_bonus(cible, "bonus_attaque", -X)
            logs.append(f"    📉 {nom} [Dernier Mot] : {cible['nom']} -{X} Attaque")
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["position"], pokemon["position"] = "def", "off"
            logs.append(f"    🔄 [Dernier Mot] : {nom} ↔ {offensif['nom']} échangent leurs positions")

    elif nom_att == "Neigeux de Mots":
        # Swap POKEMON ↔ offensif allié
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["position"], pokemon["position"] = "def", "off"
            logs.append(f"    🔄 {nom} [Neigeux de Mots] : {nom} ↔ {offensif['nom']} échangent leurs positions")

    elif nom_att == "Queulonage":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_bouclier"] = offensif.get("_bouclier", 0) + 30
            logs.append(f"    🛡️ {nom} [Queulonage] : {offensif['nom']} gagne un bouclier de 30 PV")
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            # Soigne intégralement si un allié a été KO ce tour
            ko_ce_tour = any(p.get("ko") for p in equipe_att)
            if ko_ce_tour:
                offensif["pv"] = offensif.get("pv_max", 100)
                soigner_statuts(offensif)
                logs.append(f"    🌙 {nom} [Danse Lune] : {offensif['nom']} soigné intégralement !")
            else:
                logs.append(f"    🌙 [Danse Lune] : aucun allié KO, pas d'effet")

    # ══════════════════════════════════════════════════════════════════════
    # ATT_DEF RESTANTES
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"hate", "Hâte", "Hate"}:
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            appliquer_bonus(offensif, "bonus_vitesse", X)
            offensif["vitesse"] = offensif.get("vitesse", 50) + X
            logs.append(f"    💨 {nom} [Hâte] : {offensif['nom']} +{X} Vitesse")

    elif nom_att == "Carapiége":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_carapie_ge"] = X
            logs.append(f"    🔥 {nom} [Carapiège] : prochain attaquant de {offensif['nom']} subit {X} dégâts Feu")

    elif nom_att == "Détection":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_detection"] = True
            logs.append(f"    👁️ {nom} [Détection] : {offensif['nom']} protégé des attaques d'autres colonnes")

    elif nom_att == "Lilliput":
        pokemon["_lilliput"] = True
        logs.append(f"    🌀 {nom} [Lilliput] : attaques ciblant {nom} subissent un malus de précision {Y}")

    elif nom_att == "Reflet":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        pokemon["_reflet"] = Y
        if offensif:
            offensif["_reflet"] = Y
        logs.append(f"    🪞 {nom} [Reflet] : attaques ciblant {nom}/offensif ont -{Y} précision ce tour")

    elif nom_att == "Magné-Contrôle":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_magne_controle"] = True
            logs.append(f"    🧲 {nom} [Magné-Contrôle] : {offensif['nom']} super efficace contre Acier")

    elif nom_att == "Reflet Magik":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        pokemon["_reflet_magik"] = True
        if offensif:
            offensif["_reflet_magik"] = True
        logs.append(f"    🪄 {nom} [Reflet Magik] : statuts renvoyés vers l'attaquant ce tour")

    elif nom_att == "Par Ici":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_par_ici"] = id(pokemon)  # redirige vers POKEMON
            logs.append(f"    ➡️ {nom} [Par Ici] : attaques ciblant {offensif['nom']} redirigées vers {nom}")

    elif nom_att == "Partage Garde":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_partage_garde"] = id(pokemon)  # lien vers POKEMON
            pokemon["_partage_garde_actif"] = True
            logs.append(f"    🛡️ {nom} [Partage Garde] : dégâts sur {offensif['nom']} partagés avec {nom}")

    elif nom_att == "Lien du Destin":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif:
            offensif["_lien_destin"] = True
            logs.append(f"    ⛓️ {nom} [Lien du Destin] : si {offensif['nom']} KO → son tueur KO aussi")

    elif nom_att == "Second Souffle":
        # Chercher le dernier pokemon KO de l'équipe
        ko_pokes = [p for p in equipe_att if p.get("ko")]
        if ko_pokes:
            dernier_ko = ko_pokes[-1]
            soin = dernier_ko.get("pv_max", 100) // 2
            dernier_ko["pv"] = soin
            dernier_ko["ko"] = False
            soigner_statuts(dernier_ko)
            dernier_ko["position"] = "banc"
            logs.append(f"    💨 {nom} [Second Souffle] : {dernier_ko['nom']} réanimé avec {soin} PV !")

    elif nom_att == "Change-Côté":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and cible:
            # Échange temporaire : l'offensif adverse rejoint l'équipe alliée et vice-versa
            offensif["_change_cote_original"] = id(equipe_att)
            cible["_change_cote_original"] = id(equipe_adv)
            # Swap dans les équipes
            if offensif in equipe_att and cible in equipe_adv:
                equipe_att.remove(offensif)
                equipe_adv.remove(cible)
                equipe_att.append(cible)
                equipe_adv.append(offensif)
                logs.append(f"    🔄 {nom} [Change-Côté] : {offensif['nom']} ↔ {cible['nom']} échangés pour ce combat")

    elif nom_att == "Gravité":
        col = pokemon.get("slot", 0)
        for p in equipe_att + equipe_adv:
            if p.get("slot") == col and not p.get("ko") and not p.get("_a_joue_ce_combat"):
                # Supprime résistance Sol
                p["_resistances_sans_sol"] = [r for r in p.get("resistances", []) if _normaliser_type(r) != "sol"]
                p["_resistances_orig"] = p.get("resistances", [])
                p["resistances"] = p["_resistances_sans_sol"]
                # Annule malus de précision
                if p.get("bonus_precision", 0) < 0:
                    p["bonus_precision"] = 0
                # Annule attaque Vol
                if _normaliser_type(p.get("att_off_type", "") or "") == "vol":
                    p["_att_vol_annulee"] = True
                p["_gravite"] = True
                logs.append(f"    🌍 [Gravité] : {p['nom']} résistance Sol supprimée, malus précision annulé")

    elif nom_att == "Encore":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and cible:
            for p, adv in [(offensif, cible), (cible, offensif)]:
                if p.get("_a_joue_ce_combat") and not p.get("ko"):
                    p["_encore"] = True
                    logs.append(f"    🔁 [Encore] : {p['nom']} va rejouer !")

    elif nom_att == "Lire-Esprit":
        for p in equipe_att:
            if not p.get("ko"):
                p["_lire_esprit"] = True
        logs.append(f"    🧠 {nom} [Lire-Esprit] : jets de dé alliés +2 ce tour")

    elif nom_att == "Possessif":
        # Empêche l'adverse d'utiliser son att si un allié a la même attaque
        if cible:
            att_adv = cible.get("att_off_nom", "")
            # Ignorer les parenthèses pour la comparaison
            att_adv_base = att_adv.split("(")[0].strip().lower()
            for p in equipe_att:
                att_allie = p.get("att_off_nom", "").split("(")[0].strip().lower()
                if att_allie and att_allie == att_adv_base and not p.get("ko"):
                    cible["_possessif_bloque"] = True
                    logs.append(f"    🚫 {nom} [Possessif] : {cible['nom']} ne peut pas utiliser {att_adv}")
                    break

    elif nom_att == "Ten-Danse":
        offensif = next((p for p in equipe_att if p.get("position") == "off" and not p.get("ko")), None)
        if offensif and cible:
            # Échange les attaques pour ce combat
            att_off_nom = offensif.get("att_off_nom")
            att_off_desc = offensif.get("att_off_desc")
            att_off_type = offensif.get("att_off_type")
            offensif["att_off_nom"] = cible.get("att_off_nom")
            offensif["att_off_desc"] = cible.get("att_off_desc")
            offensif["att_off_type"] = cible.get("att_off_type")
            cible["att_off_nom"] = att_off_nom
            cible["att_off_desc"] = att_off_desc
            cible["att_off_type"] = att_off_type
            offensif["_ten_danse_orig"] = (att_off_nom, att_off_desc, att_off_type)
            cible["_ten_danse_orig"] = (offensif.get("att_off_nom"), offensif.get("att_off_desc"), offensif.get("att_off_type"))
            logs.append(f"    💃 {nom} [Ten-Danse] : {offensif['nom']} ↔ {cible['nom']} attaques échangées")

    elif nom_att == "Sommation":
        # Utilise la dernière attaque utilisée avant ce tour
        # L'historique est dans les logs - chercher la dernière attaque
        derniere_att = None
        for log in reversed(logs):
            if "utilise" in log and "OFF" in log:
                # Extraire le nom de l'attaque du log
                import re
                m = re.search(r'utilise (.+?) →', log)
                if m:
                    derniere_att = m.group(1).strip()
                    break
        if derniere_att:
            pokemon["att_def_nom"] = derniere_att
            logs.append(f"    📋 {nom} [Sommation] : utilise {derniere_att}")

    # ══════════════════════════════════════════════════════════════════════
    # ATTAQUES BASÉES SUR LE POIDS
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Cavalerie Lourde", "Tacle Lourd"}:
        poids_att = pokemon.get("poids", 0) or 0
        poids_cib = cible.get("poids", 0) or 0
        if poids_att > poids_cib:
            appliquer_bonus(pokemon, "bonus_attaque", 10)
            logs.append(f"    ⚖️ {nom} [{nom_att}] : +10 dégâts ({poids_att}kg > {poids_cib}kg)")

    elif nom_att == "Tacle Feu":
        poids_att = pokemon.get("poids", 0) or 0
        poids_cib = cible.get("poids", 0) or 0
        if poids_att > poids_cib:
            appliquer_bonus(pokemon, "bonus_attaque", 10)
            logs.append(f"    🔥 {nom} [Tacle Feu] : +10 dégâts ({poids_att}kg > {poids_cib}kg)")

    elif nom_att == "Balayage":
        poids_att = pokemon.get("poids", 0) or 0
        poids_cib = cible.get("poids", 0) or 0
        if poids_cib > poids_att:
            appliquer_bonus(pokemon, "bonus_attaque", 10)
            logs.append(f"    ⚖️ {nom} [Balayage] : +10 dégâts (cible {poids_cib}kg > {poids_att}kg)")

    elif nom_att == "Souplesse":
        poids_att = pokemon.get("poids", 0) or 0
        poids_cib = cible.get("poids", 0) or 0
        if poids_att < poids_cib:
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    🤸 {nom} [Souplesse] : +20 dégâts ({poids_att}kg < {poids_cib}kg)")

    elif nom_att == "Gare au Ronflex":
        poids_att = pokemon.get("poids", 0) or 0
        poids_cib = cible.get("poids", 0) or 0
        if poids_cib < poids_att and not cible.get("statut"):
            ok, _ = appliquer_statut(cible, "PAR")
            if ok: logs.append(f"    ⚡ {nom} [Gare au Ronflex] : {cible['nom']} paralysé ({poids_cib}kg < {poids_att}kg)")

    elif nom_att == "Force G":
        poids_cib = cible.get("poids", 0) or 0
        appliquer_bonus(cible, "bonus_attaque", -20)
        logs.append(f"    📉 {nom} [Force G] : {cible['nom']} -20 Attaque")
        if poids_cib > 100:
            appliquer_bonus(pokemon, "bonus_attaque", 30)
            logs.append(f"    💥 [Force G] : +30 dégâts (cible {poids_cib}kg > 100kg)")

    elif nom_att == "Ondes G-Max":
        # Zone colonne : double le poids des 2 adverses + supprime type Vol
        for c in _cibles_colonne():
            poids_orig = c.get("poids", 0) or 0
            c["_poids_double"] = poids_orig * 2  # poids temporaire doublé
            if "vol" in [_normaliser_type(t) for t in c.get("types", [])]:
                c["_types_orig"] = c.get("types", [])
                c["types"] = [t for t in c.get("types", []) if _normaliser_type(t) != "vol"]
                logs.append(f"    🌊 [Ondes G-Max] : {c['nom']} poids doublé ({poids_orig}→{poids_orig*2}kg) + type Vol supprimé")
            else:
                logs.append(f"    🌊 [Ondes G-Max] : {c['nom']} poids doublé ({poids_orig}→{poids_orig*2}kg)")
        pokemon["_zone_colonne"] = True

    elif nom_att == "Bulldoboule":
        # Dé 5-6 → peur (déjà géré dans le bloc précédent, ici juste le bonus poids)
        poids_att = pokemon.get("poids", 0) or 0
        poids_cib = cible.get("poids", 0) or 0
        if not cible.get("peur") and _jet_de(5, logs, nom, "[Bulldoboule] tente peur"):
            cible["peur"] = True
            logs.append(f"    😨 {cible['nom']} a peur ! (Bulldoboule)")
        if poids_cib < poids_att:
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    ⚖️ [Bulldoboule] : +20 dégâts (cible {poids_cib}kg < {poids_att}kg)")

    # ══════════════════════════════════════════════════════════════════════
    # ATTAQUES BASÉES SUR LA TAILLE
    # ══════════════════════════════════════════════════════════════════════

    elif nom_att in {"Mégacorne", "Mégafouet", "Picpic"}:
        taille_att = pokemon.get("taille", 0) or 0
        taille_cib = cible.get("taille", 0) or 0
        if taille_att > taille_cib:
            appliquer_bonus(pokemon, "bonus_attaque", 10)
            logs.append(f"    📏 {nom} [{nom_att}] : +10 dégâts ({taille_att}m > {taille_cib}m)")

    elif nom_att == "Ombre Nocturne":
        taille_att = pokemon.get("taille", 0) or 0
        taille_cib = cible.get("taille", 0) or 0
        if taille_att > taille_cib:
            appliquer_bonus(pokemon, "bonus_attaque", 20)
            logs.append(f"    🌑 {nom} [Ombre Nocturne] : +20 dégâts ({taille_att}m > {taille_cib}m)")

    elif nom_att in {"Gladius Maximus", "Aegis Maxima"}:
        taille_att = pokemon.get("taille", 0) or 0
        taille_cib = cible.get("taille", 0) or 0
        if taille_cib > taille_att:
            bonus = 40 if taille_cib >= 10.0 else 20  # ×2 contre Gigamax (≥10m)
            appliquer_bonus(pokemon, "bonus_attaque", bonus)
            label = " (×2 Gigamax)" if taille_cib >= 10.0 else ""
            logs.append(f"    ⚔️ {nom} [{nom_att}] : +{bonus} dégâts ({taille_cib}m > {taille_att}m){label}")

    elif nom_att == "Rapace":
        taille_att = pokemon.get("taille", 0) or 0
        # Si l'offensif adverse est plus petit que POKEMON → il ne peut pas cibler POKEMON
        if cible:
            taille_cib = cible.get("taille", 0) or 0
            if taille_cib < taille_att:
                cible["_rapace_bloque"] = True
                logs.append(f"    🦅 {nom} [Rapace] : {cible['nom']} trop petit ({taille_cib}m < {taille_att}m) → bloqué")

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

# ── Config garantie boutique ─────────────────────────────────────────────────
# palier → (seuil_garantie, niv_min_garanti, niv_max_garanti)
GARANTIE_CONFIG = {
    11: (10, 10, 11),   # pool ≥11 : garantie à 10 rolls, force niv 10 ou 11
    12: (15, 12, 12),   # pool ≥12 : garantie à 15 rolls, force niv 12
    13: (20, 13, 13),   # pool ≥13 : garantie à 20 rolls, force niv 13
    14: (25, 14, 14),   # pool ≥14 : garantie à 25 rolls, force niv 14
    # niveau 15 : pas de garantie
}

def _palier_actif(niveau_max_pool):
    """Retourne le palier de garantie actif selon le niveau_max_pool."""
    for palier in sorted(GARANTIE_CONFIG.keys(), reverse=True):
        if niveau_max_pool >= palier:
            return palier
    return None

def _contient_niveau_garanti(offre, niv_min, niv_max):
    """Vérifie si l'offre contient déjà un pokémon du niveau garanti."""
    return any(niv_min <= p["niveau"] <= niv_max for p in offre)

def piocher_garantie(partie, niv_min, niv_max):
    """Pioche un pokémon stade 0 de niveau entre niv_min et niv_max dans le pool."""
    pool = partie.get("pool", [])
    eligibles = [pid for pid in pool
                 if (lambda p: p
                     and p.get("stade", 0) == 0
                     and p["id"] not in _EXCLUS_POOL
                     and p["id"] not in _IDS_INTERMEDIAIRES
                     and niv_min <= p["niveau"] <= niv_max)(_get_poke(pid))]
    if not eligibles:
        return None
    choix = random.choice(eligibles)
    pool.remove(choix)
    return _get_poke(choix)

def generer_offre_boutique(partie, niveau_joueur, ancienne_offre=None, locked=False,
                           niveau_max_pool=10, joueur=None, est_reroll=False):
    if locked and ancienne_offre:
        return ancienne_offre
    if ancienne_offre:
        retourner_au_pool(partie, [p["id"] for p in ancienne_offre])
    pokes = piocher_depuis_pool(partie, niveau_joueur, niveau_max_pool=niveau_max_pool)
    offre = [{"id": p["id"], "nom": p["nom"], "types": p["types"], "niveau": p["niveau"]} for p in pokes]

    # ── Système de garantie ───────────────────────────────────────────────────
    if joueur is not None and niveau_max_pool >= 11:
        palier = _palier_actif(niveau_max_pool)
        if palier and palier in GARANTIE_CONFIG:
            seuil, niv_min, niv_max = GARANTIE_CONFIG[palier]
            cle = str(palier)
            garantie_rolls = joueur.setdefault("garantie_rolls", {"11":0,"12":0,"13":0,"14":0})

            if est_reroll:
                # Incrémenter seulement si l'offre ne contient pas naturellement un pokémon garanti
                if not _contient_niveau_garanti(offre, niv_min, niv_max):
                    garantie_rolls[cle] = garantie_rolls.get(cle, 0) + 1
                else:
                    garantie_rolls[cle] = 0  # Reset : on en a vu un naturellement

            # Vérifier si la garantie se déclenche
            if garantie_rolls.get(cle, 0) >= seuil:
                if not _contient_niveau_garanti(offre, niv_min, niv_max):
                    poke_garanti = piocher_garantie(partie, niv_min, niv_max)
                    if poke_garanti:
                        # Remplacer une offre au hasard
                        idx = random.randrange(len(offre))
                        # Remettre le pokémon remplacé dans le pool
                        retourner_au_pool(partie, [offre[idx]["id"]])
                        offre[idx] = {
                            "id": poke_garanti["id"], "nom": poke_garanti["nom"],
                            "types": poke_garanti["types"], "niveau": poke_garanti["niveau"],
                            "_garanti": True,
                        }
                        garantie_rolls[cle] = 0  # Reset après déclenchement

    return offre

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
        "niveau_max_pool": 10,
        "garantie_rolls":  {"11": 0, "12": 0, "13": 0, "14": 0},
        "niveaux_achetes": [],
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

ATTAQUES_PRIORITE = {
    "Coup Bas", "Mach Punch", "Pisto-Poing", "Vive-Attaque", "Vitesse Extrême",
    "Onde Vide", "Bluff", "Escarmouche", "Aqua Jet", "Poing Sonique",
    "Vif-Éclair", "Vif Éclair", "Éclat Glace", "Eclat Glace",
    "Ombre Portée", "Sheauriken", "Vif Roc"
}

ATTAQUES_SOIN = {
    "Aurore", "Synthése", "Rayon Lune", "Soin", "E-Coque", "Purification",
    "Lait a Boire", "Lait à Boire", "Vibra Soin", "Soin Floral", "Repos",
    "Récupération", "Glas de Soin", "Aromathérapie", "Régénération",
    "Extravaillance", "Appel Soins", "Cure G-Max", "Nectar G-Max",
    "Fontaine de Vie", "Seve Salvatrice", "Voeu Soin", "Vœu Soin",
    "Danse Lune", "Second Souffle", "Paresse", "Racines",
}

def appliquer_effets_climat_debut(climat, j1, j2, equipe1, equipe2, logs):
    """Applique les effets du climat en début de combat."""
    if not climat or climat == "Ensoleillé":
        return

    tous = equipe1 + equipe2
    logs.append(f"  🌤️ Climat : {climat}")

    def boost_att(p, mult=0.5):
        appliquer_bonus(p, "bonus_attaque", int(p.get("degats", 20) * mult))

    def t(p): return [_normaliser_type(x) for x in p.get("types", [])]
    def att_t(p): return _normaliser_type(p.get("att_off_type", "") or "")

    # ── BROUILLARD ────────────────────────────────────────────────────────
    if climat == "Brouillard":
        for p in tous:
            if p.get("ko"): continue
            at = att_t(p)
            if at in ("fee", "psy"):
                boost_att(p, 0.5)
                logs.append(f"    🌫️ {p['nom']} +50% dégâts ({at})")
            elif at in ("tenebres", "spectre"):
                boost_att(p, -0.5)
                logs.append(f"    🌫️ {p['nom']} -50% dégâts ({at})")
            # -50% soin Aurore/Synthèse → géré dans appliquer_soins_climat
            # Attaques de priorité bloquées → flag
            if p.get("att_off_nom") in ATTAQUES_PRIORITE:
                p["_att_priorite_bloquee"] = True
            # Malus précision 1 si non Fée/Psy → dé spécial, géré dans boucle via flag
            if at not in ("fee", "psy"):
                p["_brouillard_malus_precision"] = True
            # Statuts bloqués
            p["_brouillard_no_statut"] = True

    # ── CANICULE ──────────────────────────────────────────────────────────
    elif climat == "Canicule":
        for p in tous:
            if p.get("ko"): continue
            at = att_t(p)
            tp = t(p)
            if at == "feu":
                boost_att(p, 0.5)
                logs.append(f"    ☀️ {p['nom']} +50% dégâts Feu")
            elif at in ("eau", "glace"):
                boost_att(p, -0.5)
                logs.append(f"    ☀️ {p['nom']} -50% dégâts ({at})")
            if p.get("att_off_nom") in {"Lance-Soleil", "Lame Solaire"}:
                boost_att(p, 0.5)
                logs.append(f"    ☀️ {p['nom']} +50% dégâts {p['att_off_nom']}")
            if at in ("electrik", "vol"):
                p["_canicule_malus_precision"] = True  # dé, échoue sur 1-2-3
            if "plante" in tp:
                p["vitesse"] = p.get("vitesse", 50) * 2
                logs.append(f"    ☀️ {p['nom']} vitesse ×2 (Plante)")
            if "glace" in tp:
                p["bonus_defense"] = 0
                logs.append(f"    ☀️ {p['nom']} Bonus Défense supprimé (Glace)")
            # -50% Pouvoir Lunaire
            if p.get("att_off_nom") == "Pouvoir Lunaire (Séléroc)":
                boost_att(p, -0.5)
            # Soins ×2 Synthèse/Aurore, -50% Rayon Lune → appliquer_soins_climat

    # ── DISTORSION ────────────────────────────────────────────────────────
    elif climat == "Distorsion":
        # Ordre inversé géré dans le tri de la file
        # Compteur déjà géré dans partie["distorsion_tours"]
        pass

    # ── GRÊLE ─────────────────────────────────────────────────────────────
    elif climat == "Grêle":
        for p in tous:
            if p.get("ko"): continue
            at = att_t(p)
            tp = t(p)
            if at == "eau":
                p["_att_type_override"] = "glace"
                logs.append(f"    🧊 {p['nom']} attaque Eau → Glace")
            if at == "glace":
                boost_att(p, 0.5)
                appliquer_bonus(p, "bonus_precision", 99)
                logs.append(f"    🧊 {p['nom']} +50% dégâts Glace + précision parfaite")
            elif at in ("feu", "plante"):
                boost_att(p, -0.5)
                logs.append(f"    🧊 {p['nom']} -50% dégâts ({at})")
            if "glace" in tp:
                p["vitesse"] = p.get("vitesse", 50) * 2
                logs.append(f"    🧊 {p['nom']} vitesse ×2 (Glace)")

    # ── NUAGEUX ───────────────────────────────────────────────────────────
    elif climat == "Nuageux":
        for p in tous:
            if p.get("ko"): continue
            if att_t(p) == "normal":
                boost_att(p, 0.5)
                logs.append(f"    ☁️ {p['nom']} +50% dégâts Normal")

    # ── NUIT ──────────────────────────────────────────────────────────────
    elif climat == "Nuit":
        for p in tous:
            if p.get("ko"): continue
            at = att_t(p)
            if at in ("tenebres", "spectre"):
                boost_att(p, 0.5)
                logs.append(f"    🌙 {p['nom']} +50% dégâts ({at})")
            elif at == "fee":
                boost_att(p, -0.5)
                logs.append(f"    🌙 {p['nom']} -50% dégâts Fée")
            # Malus précision 1 si non Ténèbre/Spectre
            if at not in ("tenebres", "spectre"):
                p["_nuit_malus_precision"] = True
            # Attaques bloquées
            if p.get("att_off_nom") in {"Lance-Soleil", "Lame Solaire"}:
                p["_att_vol_annulee"] = True
            if p.get("att_def_nom") in {"Aurore", "Synthése", "Rayon Lune"}:
                p["_att_def_annulee"] = True
            # Peur supplémentaire dé 6 → flag
            p["_nuit_peur"] = True

    # ── NUÉE ──────────────────────────────────────────────────────────────
    elif climat == "Nuée":
        for p in tous:
            if p.get("ko"): continue
            tp = t(p)
            at = att_t(p)
            if at == "insecte":
                boost_att(p, 0.5)
                logs.append(f"    🐛 {p['nom']} +50% dégâts Insecte")
            elif at == "plante":
                boost_att(p, -0.5)
                logs.append(f"    🐛 {p['nom']} -50% dégâts Plante")
            if "insecte" in tp:
                appliquer_bonus(p, "bonus_defense", 10)
                logs.append(f"    🐛 {p['nom']} +10 Défense (Insecte)")

    # ── ORAGE ─────────────────────────────────────────────────────────────
    elif climat == "Orage":
        for p in tous:
            if p.get("ko"): continue
            tp = t(p)
            at = att_t(p)
            if at == "electrik":
                boost_att(p, 0.5)
                logs.append(f"    ⛈️ {p['nom']} +50% dégâts Électrik")
                p["_orage_paralysie"] = True  # dé 6 → paralysie après attaque
            elif at == "vol":
                boost_att(p, -0.5)
                logs.append(f"    ⛈️ {p['nom']} -50% dégâts Vol")
            if "electrik" in tp or "acier" in tp:
                p["vitesse"] = p.get("vitesse", 50) * 2
                logs.append(f"    ⛈️ {p['nom']} vitesse ×2 (Électrik/Acier)")
        # Réveiller les endormis + bloquer sommeil
        for p in tous:
            if p.get("statut") == "SLP":
                retirer_statut(p)
                logs.append(f"    ⛈️ {p['nom']} réveillé par l'Orage !")
            p["_orage_no_sleep"] = True

    # ── PLUIE ─────────────────────────────────────────────────────────────
    elif climat == "Pluie":
        for p in tous:
            if p.get("ko"): continue
            tp = t(p)
            at = att_t(p)
            if at == "eau":
                boost_att(p, 0.5)
                logs.append(f"    🌧️ {p['nom']} +50% dégâts Eau")
            elif at in ("feu", "plante"):
                boost_att(p, -0.5)
                logs.append(f"    🌧️ {p['nom']} -50% dégâts ({at})")
            if p.get("att_off_nom") in {"Lance-Soleil", "Lame Solaire"}:
                boost_att(p, -0.5)
            if at in ("electrik", "vol"):
                appliquer_bonus(p, "bonus_precision", 99)
            if "eau" in tp:
                p["vitesse"] = p.get("vitesse", 50) * 2
                logs.append(f"    🌧️ {p['nom']} vitesse ×2 (Eau)")

    # ── SMOG ──────────────────────────────────────────────────────────────
    elif climat == "Smog":
        for p in tous:
            if p.get("ko"): continue
            at = att_t(p)
            if at == "eau":
                p["_att_type_override"] = "poison"
                logs.append(f"    🏭 {p['nom']} attaque Eau → Poison")
            if at == "poison":
                boost_att(p, 0.5)
                logs.append(f"    🏭 {p['nom']} +50% dégâts Poison")
            elif at == "fee":
                boost_att(p, -0.5)
                logs.append(f"    🏭 {p['nom']} -50% dégâts Fée")

    # ── TEMPÊTE DE SABLE ──────────────────────────────────────────────────
    elif climat == "Tempête de Sable":
        for p in tous:
            if p.get("ko"): continue
            tp = t(p)
            at = att_t(p)
            if at in ("roche", "sol", "acier"):
                boost_att(p, 0.5)
                logs.append(f"    🏜️ {p['nom']} +50% dégâts ({at})")
            elif at == "electrik":
                boost_att(p, -0.5)
                logs.append(f"    🏜️ {p['nom']} -50% dégâts Électrik")
            if "sol" in tp:
                p["vitesse"] = p.get("vitesse", 50) * 2
                logs.append(f"    🏜️ {p['nom']} vitesse ×2 (Sol)")
            if "roche" in tp:
                appliquer_bonus(p, "bonus_defense", 10)
                logs.append(f"    🏜️ {p['nom']} +10 Défense (Roche)")
            if at not in ("sol", "roche"):
                p["_sable_malus_precision"] = True  # dé, échoue sur 1
            if p.get("att_def_nom") in {"Aurore", "Synthése", "Rayon Lune"}:
                p["_att_def_annulee"] = True

    # ── VENT ──────────────────────────────────────────────────────────────
    elif climat == "Vent":
        for p in tous:
            if p.get("ko"): continue
            tp = t(p)
            at = att_t(p)
            if at == "vol":
                boost_att(p, 0.5)
                logs.append(f"    💨 {p['nom']} +50% dégâts Vol")
            if "vol" in tp:
                p["vitesse"] = p.get("vitesse", 50) * 2
                logs.append(f"    💨 {p['nom']} vitesse ×2 (Vol)")
            # Décalage cible → flag, géré dans la boucle combat
            p["_vent_decalage"] = True

    # ── TEMPÊTE ───────────────────────────────────────────────────────────
    elif climat == "Tempête":
        for p in tous:
            if p.get("ko"): continue
            tp = t(p)
            at = att_t(p)
            if at == "dragon":
                boost_att(p, 0.5)
                logs.append(f"    🌀 {p['nom']} +50% dégâts Dragon")
            if "dragon" in tp:
                p["vitesse"] = p.get("vitesse", 50) * 2
                logs.append(f"    🌀 {p['nom']} vitesse ×2 (Dragon)")
            # Annule tous les changements de stats
            p["bonus_attaque"] = 0
            p["bonus_defense"] = 0
            p["bonus_vitesse"] = 0
            p["bonus_precision"] = 0
            # Soins bloqués → flag
            p["_tempete_no_soin"] = True
            logs.append(f"    🌀 {p['nom']} : stats remises à 0 (Tempête)")


def appliquer_effets_climat_fin(climat, j1, j2, equipe1, equipe2, partie, logs):
    """Applique les effets du climat en fin de combat."""
    if not climat or climat == "Ensoleillé":
        return

    tous = equipe1 + equipe2
    def t(p): return [_normaliser_type(x) for x in p.get("types", [])]

    # ── CANICULE fin ──────────────────────────────────────────────────────
    if climat == "Canicule":
        for p in tous:
            if p.get("ko"): continue
            if "sol" in t(p):
                p["pv"] = min(p.get("pv_max", 100), p.get("pv", 0) + 20)
                logs.append(f"    ☀️ {p['nom']} +20 PV (Sol/Canicule)")

    # ── GRÊLE fin ─────────────────────────────────────────────────────────
    elif climat == "Grêle":
        for p in tous:
            if p.get("ko"): continue
            if "glace" in t(p):
                p["pv"] = min(p.get("pv_max", 100), p.get("pv", 0) + 20)
                logs.append(f"    🧊 {p['nom']} +20 PV (Glace/Grêle)")
            else:
                p["pv"] = max(0, p.get("pv", 0) - 10)
                logs.append(f"    🧊 {p['nom']} -10 PV (Grêle)")

    # ── NUÉE fin ──────────────────────────────────────────────────────────
    elif climat == "Nuée":
        for p in tous:
            if p.get("ko") and "insecte" in t(p):
                p["pv"] = p.get("pv_max", 100)
                p["ko"] = False
                # Reste sur le terrain dans sa position actuelle
                logs.append(f"    🐛 {p['nom']} réanimé intégralement ! (Nuée)")

    # ── ORAGE fin ─────────────────────────────────────────────────────────
    elif climat == "Orage":
        for p in tous:
            if p.get("ko"): continue
            if "vol" in t(p):
                p["pv"] = max(0, p.get("pv", 0) - 10)
                logs.append(f"    ⛈️ {p['nom']} -10 PV (Vol/Orage)")
        # Pokémon le plus grand (taille) parmi tous les Pokémon en jeu → KO
        tous_en_jeu = []
        for joueur in [j1, j2]:
            for p in joueur.get("pokemon", []):
                if not p.get("ko") and p.get("position") in ("off", "def"):
                    tous_en_jeu.append(p)
        if tous_en_jeu:
            plus_grand = max(tous_en_jeu, key=lambda p: p.get("taille", 0) or 0)
            if (plus_grand.get("taille") or 0) > 0:
                plus_grand["ko"] = True
                plus_grand["pv"] = 0
                soigner_statuts(plus_grand)
                logs.append(f"    ⛈️ [Orage] : {plus_grand['nom']} ({plus_grand.get('taille',0)}m) est le plus grand → KO !")

    # ── PLUIE fin ─────────────────────────────────────────────────────────
    elif climat == "Pluie":
        for p in tous:
            if p.get("ko"): continue
            if "eau" in t(p):
                p["pv"] = min(p.get("pv_max", 100), p.get("pv", 0) + 20)
                logs.append(f"    🌧️ {p['nom']} +20 PV (Eau/Pluie)")

    # ── SMOG fin ──────────────────────────────────────────────────────────
    elif climat == "Smog":
        for p in tous:
            if p.get("ko"): continue
            if "poison" not in t(p):
                p["pv"] = max(0, p.get("pv", 0) - 10)
                logs.append(f"    🏭 {p['nom']} -10 PV (Smog)")

    # ── TEMPÊTE DE SABLE fin ──────────────────────────────────────────────
    elif climat == "Tempête de Sable":
        for p in tous:
            if p.get("ko"): continue
            types_p = t(p)
            if not any(x in types_p for x in ("roche", "sol", "acier")):
                p["pv"] = max(0, p.get("pv", 0) - 10)
                logs.append(f"    🏜️ {p['nom']} -10 PV (Tempête de Sable)")

    # ── TEMPÊTE fin ───────────────────────────────────────────────────────
    elif climat == "Tempête":
        # Tous les Pokémon (y compris banc) non-Dragon perdent 10 PV
        for joueur in [j1, j2]:
            for p in joueur.get("pokemon", []):
                if p.get("ko"): continue
                if "dragon" not in t(p):
                    p["pv"] = max(0, p.get("pv", 0) - 10)
                    logs.append(f"    🌀 {p['nom']} -10 PV (Tempête)")

    # Nuit : flag pas de baie
    if climat == "Nuit":
        partie["_nuit_pas_baie"] = True
        logs.append(f"    🌙 Les joueurs ne piochent pas de Baie au prochain tour")

    # Nettoyage des flags temporaires climat
    for p in tous:
        for flag in ["_brouillard_no_statut", "_brouillard_malus_precision",
                     "_orage_no_sleep", "_orage_paralysie", "_nuit_malus_precision",
                     "_nuit_peur", "_canicule_malus_precision", "_sable_malus_precision",
                     "_att_def_annulee", "_att_priorite_bloquee", "_vent_decalage",
                     "_tempete_no_soin"]:
            p.pop(flag, None)


def appliquer_soins_climat(climat, nom_att):
    """Retourne le multiplicateur de soin selon le climat actif."""
    if not climat or not nom_att:
        return 1.0

    # Soins bloqués par Tempête
    if climat == "Tempête":
        return 0.0

    if climat == "Canicule":
        if nom_att in {"Synthése", "Aurore"}:
            return 2.0
        if nom_att == "Rayon Lune":
            return 0.5
    elif climat == "Nuit":
        if nom_att == "Rayon Lune":
            return 2.0
        if nom_att in {"Aurore", "Synthése"}:
            return 0.0
    elif climat in {"Brouillard", "Nuageux"}:
        if nom_att in {"Aurore", "Synthése"}:
            return 0.5
    elif climat == "Grêle":
        if nom_att in {"Aurore", "Synthése", "Rayon Lune"}:
            return 0.5
    elif climat == "Pluie":
        if nom_att in {"Aurore", "Synthése", "Rayon Lune"}:
            return 0.5
    elif climat == "Tempête de Sable":
        if nom_att in {"Aurore", "Synthése", "Rayon Lune"}:
            return 0.0

    return 1.0


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
    # Vigilance : protège du prochain changement de statut (ce combat)
    if poke.get("_vigilance") and statut in STATUTS_UNIQUES:
        poke.pop("_vigilance", None)
        return False, f"{poke['nom']} est protégé par Vigilance !"
    # Rune Protect : protège des statuts jusqu'au prochain combat
    if poke.get("_rune_protect") and statut in STATUTS_UNIQUES:
        return False, f"{poke['nom']} est protégé par Rune Protect !"
    # Brouillard : aucun statut ne peut être appliqué ce tour
    if poke.get("_brouillard_no_statut") and statut in STATUTS_UNIQUES:
        return False, f"{poke['nom']} est protégé par le Brouillard !"
    # Orage : aucun Pokémon ne peut s'endormir
    if poke.get("_orage_no_sleep") and statut == "SLP":
        return False, f"{poke['nom']} ne peut pas s'endormir pendant l'Orage !"
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


MORPHEO_FORMES = {
    "Canicule":         "0351d",  # Solaire
    "Orage":            "0351d",  # Solaire
    "Pluie":            "0351c",  # Pluie
    "Tempête":          "0351c",  # Pluie
    "Grêle":            "0351b",  # Blizzard
    "Vent":             "0351b",  # Blizzard
}

def appliquer_transformation_morpheo(joueur, climat):
    """Transforme Morphéo selon le climat actif. Revient à la forme normale sinon."""
    for poke in joueur.get("pokemon", []):
        if poke.get("id") not in ("0351", "0351b", "0351c", "0351d"):
            continue
        forme_cible = MORPHEO_FORMES.get(climat, "0351")
        if poke["id"] == forme_cible:
            continue
        nouvelle_db = _DB_MAP.get(forme_cible)
        if not nouvelle_db:
            continue
        poke["id"]           = forme_cible
        poke["nom"]          = nouvelle_db["nom"]
        poke["types"]        = nouvelle_db.get("types", poke["types"])
        poke["faiblesses"]   = nouvelle_db.get("faiblesses", poke.get("faiblesses", []))
        poke["resistances"]  = nouvelle_db.get("resistances", poke.get("resistances", []))
        poke["att_off_nom"]  = nouvelle_db.get("att_off_nom", poke.get("att_off_nom"))
        poke["att_off_type"] = nouvelle_db.get("att_off_type", poke.get("att_off_type"))
        poke["att_def_nom"]  = nouvelle_db.get("att_def_nom", poke.get("att_def_nom"))
        poke["att_def_type"] = nouvelle_db.get("att_def_type", poke.get("att_def_type"))


def gerer_distorsion(partie):
    """Gère le compteur de tours de Distorsion."""
    if partie.get("climat_actuel") == "Distorsion":
        tours = partie.get("distorsion_tours", 3)
        if tours <= 1:
            partie["distorsion_tours"] = 0
            partie["climat_actuel"] = "Ensoleillé"
        else:
            partie["distorsion_tours"] = tours - 1
    elif partie.get("distorsion_tours", 0) == 0 and partie.get("_distorsion_actif"):
        partie.pop("_distorsion_actif", None)
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

def jet_precision(attaquant, cible, logs):
    """
    Vérifie si l'attaque touche selon le malus de précision.
    Prend en compte Lilliput et Reflet sur la cible.
    """
    malus = -attaquant.get("bonus_precision", 0)
    # Lilliput sur la cible
    if cible and cible.get("_lilliput"):
        malus += valeur_y(cible.get("niveau", 1))
    # Reflet sur la cible
    if cible and cible.get("_reflet"):
        malus += cible.get("_reflet", 0)
        cible.pop("_reflet", None)
    if malus <= 0:
        return True
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

    # Magné-Contrôle : super efficace contre Acier
    if attaquant.get("_magne_controle"):
        if "acier" in [_normaliser_type(t) for t in defenseur.get("types", [])]:
            multiplicateur = max(multiplicateur, 2.0)

    # Appliquer bonus_defense du défenseur :
    # positif = réduit les dégâts, négatif = augmente les dégâts
    degats_final = max(0, int(degats_base * multiplicateur) - defenseur.get("bonus_defense", 0))
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
        p["_position_initiale"] = p.get("position", "off")  # Pour filtrer les dégâts directs
        p["_a_joue_ce_combat"] = False  # Un Pokémon ne peut jouer qu'une fois par combat
        # Réinitialiser les bonus temporaires de combat
        p["bonus_attaque"]   = 0
        p["bonus_defense"]   = 0
        p["bonus_vitesse"]   = 0
        p["bonus_precision"] = 0
        # Restaurer la vitesse de base
        if "_vitesse_base" not in p:
            p["_vitesse_base"] = p.get("vitesse", 50)
        p["vitesse"] = p["_vitesse_base"]

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



    # Effets synergies de début de combat (Eau, Dragon, Normal)
    appliquer_effets_synergies_debut(j1, j2, equipe1, equipe2, logs)

    # Effets climat de début de combat
    climat = partie.get("climat_actuel", "Ensoleillé")
    appliquer_effets_climat_debut(climat, j1, j2, equipe1, equipe2, logs)

    # File d'attaque globale triée par vitesse décroissante
    # Chaque entrée = (attaquant, defenseur_ou_None)
    file_attaques = []
    for (a, b) in paires:
        file_attaques.append((a, b))
        file_attaques.append((b, a))
    # Ajouter les Pokémon sans adversaire
    # - Offensifs sans adversaire → dégâts directs au dresseur
    # - Défensifs sans adversaire → att_def avec l'offensif adverse comme cible
    #   (ou None si vraiment personne en face)
    for p in sans_adv1 + sans_adv2:
        equipe_p = equipe1 if p in equipe1 else equipe2
        equipe_adv_p = equipe2 if p in equipe1 else equipe1
        # Chercher l'offensif adverse dans la colonne miroir
        col_miroir = 4 - p["slot"]
        adv_p = next((x for x in equipe_adv_p
                      if x["slot"] == col_miroir and x["position"] == "off"
                      and not x.get("ko")), None)
        file_attaques.append((p, adv_p))
    # Distorsion : inverser l'ordre de la file
    if climat == "Distorsion":
        file_attaques.sort(key=lambda x: x[0].get("vitesse", 50), reverse=False)
    else:
        file_attaques.sort(key=lambda x: x[0].get("vitesse", 50), reverse=True)

    idx_file = 0
    while idx_file < len(file_attaques):
        attaquant, defenseur = file_attaques[idx_file]
        idx_file += 1
        # Ne pas attaquer si déjà KO
        if attaquant.get("ko"):
            continue
        # Ne pas rejouer si déjà joué ce combat
        if attaquant.get("_a_joue_ce_combat"):
            continue

        # ── Cas sans adversaire ───────────────────────────────────────────
        if defenseur is None:
            attaquant["_a_joue_ce_combat"] = True
            if attaquant.get("_position_initiale") == "off" and not attaquant.get("ko"):
                joueur_att_dir = j1 if attaquant in equipe1 else j2
                joueur_def_dir = j2 if attaquant in equipe1 else j1
                pseudo_def_dir = p2 if attaquant in equipe1 else p1
                dmg_dir = points_force_total(attaquant)
                joueur_def_dir["pv"] = max(0, joueur_def_dir["pv"] - dmg_dir)
                logs.append(f"    💥 {attaquant['nom']} (off) sans adversaire → {dmg_dir} dégâts directs à {pseudo_def_dir} ({joueur_def_dir['pv']} PV)")
            elif attaquant.get("_position_initiale") == "def" and not attaquant.get("ko"):
                # Défensif sans adversaire : utilise quand même son att_def (dans le vide)
                logs.append(f"    🛡️ {attaquant['nom']} (def) sans adversaire — att_def ignorée")
            continue

        # Si le défenseur est KO → dégâts directs si offensif initial
        if defenseur.get("ko"):
            if attaquant.get("_position_initiale") == "off":
                joueur_att_dir = j1 if attaquant in equipe1 else j2
                joueur_def_dir = j2 if attaquant in equipe1 else j1
                pseudo_def_dir = p2 if attaquant in equipe1 else p1
                dmg_dir = points_force_total(attaquant)
                joueur_def_dir["pv"] = max(0, joueur_def_dir["pv"] - dmg_dir)
                logs.append(f"    💥 {attaquant['nom']} (off) sans adversaire → {dmg_dir} dégâts directs à {pseudo_def_dir} ({joueur_def_dir['pv']} PV)")
            attaquant["_a_joue_ce_combat"] = True
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
        if not ne_peut_echouer and not jet_precision(attaquant, cible_reelle, logs):
            continue  # Attaque ratée

        # ── Log de l'attaque utilisée ─────────────────────────────────────
        pos_label = "OFF" if mode_attaquant == "off" else "DEF"
        logs.append(f"  ⚡ {attaquant['nom']} [{pos_label}] utilise {att_nom or '(aucune)'} → {defenseur['nom']}")

        # Possessif : bloquer si un allié adverse possède la même attaque
        if attaquant.get("_possessif_bloque"):
            attaquant.pop("_possessif_bloque", None)
            logs.append(f"    🚫 [Possessif] : {attaquant['nom']} ne peut pas utiliser son attaque !")
            attaquant["_a_joue_ce_combat"] = True
            continue

        # Rapace : bloquer si l'attaquant est trop petit pour cibler POKEMON
        if attaquant.pop("_rapace_bloque", False):
            logs.append(f"    🦅 [Rapace] : {attaquant['nom']} ne peut pas cibler sa cible (trop petit) !")
            attaquant["_a_joue_ce_combat"] = True
            continue

        # ── Vérifications climatiques ─────────────────────────────────────
        # Attaques de priorité bloquées (Brouillard)
        if attaquant.pop("_att_priorite_bloquee", False):
            logs.append(f"    🌫️ [Brouillard] : {att_nom} (priorité) bloquée !")
            attaquant["_a_joue_ce_combat"] = True
            continue

        # Malus précision Brouillard : dé lancé, échoue sur 1
        if attaquant.get("_brouillard_malus_precision") and mode_attaquant == "off":
            de = random.randint(1, 6)
            if de == 1:
                logs.append(f"    🌫️ [Brouillard] : {attaquant['nom']} rate son attaque ! (dé: {de})")
                attaquant["_a_joue_ce_combat"] = True
                continue

        # Malus précision Nuit : dé lancé, échoue sur 1
        if attaquant.get("_nuit_malus_precision") and mode_attaquant == "off":
            de = random.randint(1, 6)
            if de == 1:
                logs.append(f"    🌙 [Nuit] : {attaquant['nom']} rate son attaque ! (dé: {de})")
                attaquant["_a_joue_ce_combat"] = True
                continue

        # Malus précision Canicule Électrik/Vol : dé lancé, échoue sur 1-2-3
        if attaquant.get("_canicule_malus_precision") and mode_attaquant == "off":
            de = random.randint(1, 6)
            if de <= 3:
                logs.append(f"    ☀️ [Canicule] : {attaquant['nom']} rate son attaque ! (dé: {de})")
                attaquant["_a_joue_ce_combat"] = True
                continue

        # Malus précision Tempête de Sable non-Sol/Roche : dé lancé, échoue sur 1
        if attaquant.get("_sable_malus_precision") and mode_attaquant == "off":
            de = random.randint(1, 6)
            if de == 1:
                logs.append(f"    🏜️ [Tempête de Sable] : {attaquant['nom']} rate ! (dé: {de})")
                attaquant["_a_joue_ce_combat"] = True
                continue

        # Décalage cible Vent : cible la colonne suivante (circulaire)
        if attaquant.get("_vent_decalage") and defenseur and mode_attaquant == "off":
            col_actuelle = defenseur.get("slot", 0)
            col_decalee = (col_actuelle + 1) % 5
            nouvelle_cible_vent = next((p for p in equipe_adv
                                        if p.get("slot") == col_decalee
                                        and p.get("position") == "off"
                                        and not p.get("ko")), None)
            if nouvelle_cible_vent:
                defenseur = nouvelle_cible_vent
                logs.append(f"    💨 [Vent] : cible décalée vers {nouvelle_cible_vent['nom']} (col. {col_decalee+1})")

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
        # Mais les effets de synergies post-attaque s'appliquent quand même
        if mode_attaquant == "def":
            appliquer_effets_post_attaque(attaquant, cible_reelle, joueur_att, joueur_def, logs)
            attaquant["_a_joue_ce_combat"] = True
            continue

        type_att = attaquant.get("att_off_type")

        # Gravité : annule les attaques Vol
        if attaquant.get("_att_vol_annulee") and type_att and _normaliser_type(type_att) == "vol":
            logs.append(f"    🌍 [Gravité] : attaque Vol de {attaquant['nom']} annulée !")
            attaquant["_a_joue_ce_combat"] = True
            continue

        dmg, eff = calculer_degats(attaquant, cible_reelle, type_attaque=type_att)

        # Puissance : dé 5-6 → +X dégâts ce tour
        if attaquant.pop("_puissance_actif", False):
            if _jet_de(5, logs, attaquant["nom"], "[Puissance] bonus dégâts"):
                bonus_p = valeur_x(attaquant.get("niveau", 1))
                dmg += bonus_p
                logs.append(f"    💥 [Puissance] : +{bonus_p} dégâts !")
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

        # ── Protections sur la cible ──────────────────────────────────────
        # Carapiège : l'attaquant subit X dégâts Feu
        if cible_reelle.get("_carapie_ge") and dmg > 0:
            val_c = cible_reelle.pop("_carapie_ge")
            attaquant["pv"] = max(0, attaquant.get("pv", 0) - val_c)
            logs.append(f"    🔥 [Carapiège] : {attaquant['nom']} subit {val_c} dégâts Feu !")

        # Détection : ignore les attaques venant d'autres colonnes
        if cible_reelle.get("_detection") and dmg > 0:
            col_att = attaquant.get("slot", 0)
            col_cib = cible_reelle.get("slot", 0)
            if col_att != 4 - col_cib:  # attaque d'une autre colonne
                logs.append(f"    👁️ [Détection] : {cible_reelle['nom']} bloque l'attaque d'une autre colonne")
                dmg = 0

        # Reflet Magik : renvoie le statut vers l'attaquant
        if cible_reelle.get("_reflet_magik") and dmg > 0:
            # Traité dans appliquer_statut via flag

            pass

        # Par Ici : redirige vers POKEMON support
        # (déjà géré via changement de cible_reelle si nécessaire)

        # Partage Garde : divise les dégâts entre offensif et POKEMON
        if cible_reelle.get("_partage_garde") and dmg > 0:
            # Trouver POKEMON (le défensif)
            support_pg = next((p for p in equipe_att if id(p) == cible_reelle["_partage_garde"]
                               and not p.get("ko")), None)
            if support_pg:
                dmg_partage = dmg // 2
                dmg = dmg_partage  # offensif reçoit moitié
                support_pg["pv"] = max(0, support_pg.get("pv", 0) - dmg_partage)
                logs.append(f"    🛡️ [Partage Garde] : dégâts partagés, {support_pg['nom']} subit {dmg_partage}")

        # Bouclier (Queulonage) : absorbe les dégâts avant les PV
        if cible_reelle.get("_bouclier") and dmg > 0:
            bouclier = cible_reelle["_bouclier"]
            if dmg <= bouclier:
                cible_reelle["_bouclier"] = bouclier - dmg
                logs.append(f"    🛡️ [Bouclier] : {cible_reelle['nom']} absorbe {dmg} dégâts (bouclier restant: {cible_reelle['_bouclier']})")
                dmg = 0
            else:
                dmg -= bouclier
                cible_reelle["_bouclier"] = 0
                logs.append(f"    🛡️ [Bouclier] : {cible_reelle['nom']} absorbe {bouclier} dégâts, {dmg} passent")

        # Blockhaus : réduit les dégâts de X + empoisonne l'attaquant
        if cible_reelle.get("_blockhaus") and dmg > 0:
            reduction_bk = cible_reelle.pop("_blockhaus")
            dmg = max(0, dmg - reduction_bk)
            logs.append(f"    🏰 [Blockhaus] : -{reduction_bk} dégâts sur {cible_reelle['nom']}")
            if not attaquant.get("statut"):
                ok, _ = appliquer_statut(attaquant, "PSN")
                if ok: logs.append(f"    ☠️ {attaquant['nom']} est empoisonné ! (Blockhaus)")

        # Prévention : dégâts divisés par 2
        if cible_reelle.pop("_prevention", False) and dmg > 0:
            dmg = dmg // 2
            logs.append(f"    🛡️ [Prévention] : dégâts réduits de 50% → {dmg}")

        # Tatamigaeshi : protège de tout sauf l'offensif adverse direct
        if cible_reelle.get("_tatamigaeshi") and dmg > 0:
            col_cible = cible_reelle.get("slot", 0)
            est_offensif_direct = (attaquant.get("position") == "off" and
                                   attaquant.get("slot") == 4 - col_cible)
            if not est_offensif_direct:
                logs.append(f"    🥋 [Tatamigaeshi] : {cible_reelle['nom']} bloque les dégâts de {attaquant['nom']}")
                dmg = 0

        # Voile Aurore : dégâts /2
        if cible_reelle.get("_voile_aurore") and dmg > 0:
            dmg = dmg // 2
            logs.append(f"    🌅 [Voile Aurore] : dégâts réduits de 50% → {dmg}")

        # Larme à l'Oeil : prochaine attaque réduite de moitié
        if cible_reelle.get("_larme_oeil") and dmg > 0:
            dmg = dmg // 2
            cible_reelle.pop("_larme_oeil", None)
            logs.append(f"    😢 [Larme à l'Œil] : dégâts réduits de 50% → {dmg}")

        # Rempart Brûlant : brûle l'attaquant
        if cible_reelle.get("_rempart_brulant") and dmg > 0 and attaquant.get("position") == "off":
            if not attaquant.get("statut"):
                ok, _ = appliquer_statut(attaquant, "BRN")
                if ok: logs.append(f"    🔥 [Rempart Brûlant] : {attaquant['nom']} est brûlé !")

        # Pico-Défense : l'attaquant perd X PV
        if cible_reelle.get("_pico_defense") and dmg > 0:
            perte = cible_reelle["_pico_defense"]
            attaquant["pv"] = max(0, attaquant.get("pv", 0) - perte)
            logs.append(f"    🛡️ [Pico-Défense] : {attaquant['nom']} perd {perte} PV")

        # Piège de Fil : malus att/vit sur l'attaquant
        if cible_reelle.get("_piege_fil") and dmg > 0:
            val = cible_reelle.pop("_piege_fil")
            appliquer_bonus(attaquant, "bonus_attaque", -val)
            appliquer_bonus(attaquant, "bonus_vitesse", -val)
            attaquant["vitesse"] = max(5, attaquant.get("vitesse", 50) - val)
            logs.append(f"    🕸️ [Piège de Fil] : {attaquant['nom']} -{val} Att/Vit")

        # Râle Mâle : POKEMON gagne X attaque s'il subit des dégâts
        if attaquant.get("_rale_male") and dmg > 0 and attaquant is cible_reelle:
            val = attaquant.pop("_rale_male")
            appliquer_bonus(attaquant, "bonus_attaque", val)
            logs.append(f"    😤 [Râle Mâle] : {attaquant['nom']} +{val} Attaque (a subi des dégâts)")

        cible_reelle["pv"] = max(0, cible_reelle.get("pv", 0) - dmg)
        logs.append(f"    ➤ {attaquant['nom']} attaque ({eff}) → {dmg} dégâts → {cible_reelle['nom']} {cible_reelle['pv']}PV")

        # Ténacité : l'offensif ne peut pas tomber KO
        if cible_reelle.get("_tenacite") and cible_reelle["pv"] <= 0:
            cible_reelle["pv"] = 5
            cible_reelle.pop("_tenacite", None)
            cible_reelle["_tenacite_used"] = True
            logs.append(f"    💪 [Ténacité] : {cible_reelle['nom']} survit avec 5 PV !")

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
            # Nuit : dé 6 → peur
            if attaquant.get("_nuit_peur") and mode_attaquant == "off":
                if not cible_reelle.get("peur") and random.randint(1, 6) == 6:
                    cible_reelle["peur"] = True
                    logs.append(f"    🌙 [Nuit] : {cible_reelle['nom']} a peur !")
            # Orage : attaque Électrik → dé 6 → paralysie
            if attaquant.get("_orage_paralysie") and mode_attaquant == "off":
                if not cible_reelle.get("statut") and random.randint(1, 6) == 6:
                    ok, _ = appliquer_statut(cible_reelle, "PAR")
                    if ok: logs.append(f"    ⛈️ [Orage] : {cible_reelle['nom']} est paralysé !")
        attaquant["_a_joue_ce_combat"] = True

        # Encore : si flag posé, réinsérer dans la file pour rejouer
        if attaquant.pop("_encore", False) and not attaquant.get("ko"):
            attaquant["_a_joue_ce_combat"] = False
            adv_encore = cible_reelle if not cible_reelle.get("ko") else None
            vit = attaquant.get("vitesse", 50)
            insert_pos = idx_file
            while insert_pos < len(file_attaques) and \
                  file_attaques[insert_pos][0].get("vitesse", 50) > vit:
                insert_pos += 1
            file_attaques.insert(insert_pos, (attaquant, adv_encore))
            logs.append(f"    🔁 [Encore] : {attaquant['nom']} est réinséré dans la file !")

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

            # Lien du Destin : si l'offensif est KO → son tueur KO aussi
            if cible_reelle.get("_lien_destin") and not attaquant.get("ko"):
                attaquant["ko"] = True
                attaquant["pv"] = 0
                soigner_statuts(attaquant)
                logs.append(f"    ⛓️ [Lien du Destin] : {attaquant['nom']} est mis KO en retour !")

            # Souvenir : si l'offensif KO → l'adversaire perd X attaque
            if cible_reelle.get("_souvenir"):
                val_souv = cible_reelle.pop("_souvenir")
                if attaquant and not attaquant.get("ko"):
                    appliquer_bonus(attaquant, "bonus_attaque", -val_souv)
                    logs.append(f"    💭 [Souvenir] : {attaquant['nom']} -{val_souv} Attaque")

            # Voeu Soin : allié KO → soigner l'offensif allié
            for allie in equipe_ko:
                if allie.get("_voeu_soin") and allie is not cible_reelle:
                    off_allie = next((p for p in equipe_ko if p.get("position") == "off"
                                     and not p.get("ko")), None)
                    if off_allie:
                        off_allie["pv"] = off_allie.get("pv_max", 100)
                        soigner_statuts(off_allie)
                        logs.append(f"    💚 [Vœu Soin] : {off_allie['nom']} soigné intégralement !")
                    allie.pop("_voeu_soin", None)
                    break
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
                # Danse Victoire : +10 par KO (max +50 total)
                if vainqueur.get("_danse_victoire"):
                    bonus_dv = vainqueur.get("_danse_victoire_bonus", 0)
                    if bonus_dv < 50:
                        gain = min(10, 50 - bonus_dv)
                        vainqueur["_danse_victoire_bonus"] = bonus_dv + gain
                        appliquer_bonus(vainqueur, "bonus_attaque", gain)
                        appliquer_bonus(vainqueur, "bonus_defense", gain)
                        logs.append(f"    🏆 [Danse Victoire] : {vainqueur['nom']} +{gain} Att/Déf (total: {bonus_dv+gain}/50)")
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
                    # N'insérer dans la file que s'il n'a pas encore joué ce combat
                    if not defensif.get("_a_joue_ce_combat"):
                        col_def = 4 - defensif["slot"]
                        equipe_adv_ko = equipe_vict
                        adv = next((p for p in equipe_adv_ko
                                    if p["slot"] == col_def and p["position"] == "off"
                                    and not p.get("ko")), None) or \
                              next((p for p in equipe_adv_ko
                                    if p["slot"] == col_def and p["position"] == "def"
                                    and not p.get("ko")), None)
                        if adv:
                            vit = defensif.get("vitesse", 50)
                            insert_pos = idx_file
                            while insert_pos < len(file_attaques) and \
                                  file_attaques[insert_pos][0].get("vitesse", 50) > vit:
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

    # ── Bonus Insecte sur les dégâts directs ──────────────────────────────
    if bonus_force_j1:
        j2["pv"] = max(0, j2["pv"] - bonus_force_j1)
        logs.append(f"  🐛 Bonus Insecte {p1} : +{bonus_force_j1} dégâts directs à {p2} → {j2['pv']} PV")
    if bonus_force_j2:
        j1["pv"] = max(0, j1["pv"] - bonus_force_j2)
        logs.append(f"  🐛 Bonus Insecte {p2} : +{bonus_force_j2} dégâts directs à {p1} → {j1['pv']} PV")

    # Retirer les effets temporaires de début de combat (Eau, Dragon, Normal)
    retirer_effets_synergies_debut(equipe1, equipe2)

    # Effets climat de fin de combat
    appliquer_effets_climat_fin(climat, j1, j2, equipe1, equipe2, partie, logs)

    # Nettoyer tous les champs temporaires non-JSON sur tous les Pokémon
    champs_temp = ["_xp_ko_ids", "_a_joue_ce_combat", "_position_initiale",
                   "_roulade_actif", "_skip_next_combat", "_danse_victoire",
                   "_danse_victoire_bonus", "_ancrage", "_brume", "_anti_soin",
                   "_gardomax_actif", "_faiblesses_temp_supprimees", "_resistances_temp",
                   "_malus_precision_entrant", "_puissance_actif",
                   "_blockhaus", "_prevention", "_tatamigaeshi",
                   "_vigilance", "_tenacite", "_tenacite_used", "_voeu_soin",
                   "_rempart_brulant", "_souvenir", "_rale_male", "_larme_oeil",
                   "_pico_defense", "_piege_fil", "_rancune", "_voile_aurore",
                   "_vol_magnetik", "_types_orig", "_att_type_override",
                   "_geo_controle_restore", "_rune_protect",
                   "_carapie_ge", "_detection", "_lilliput", "_reflet",
                   "_magne_controle", "_reflet_magik", "_par_ici",
                   "_partage_garde", "_partage_garde_actif", "_lien_destin",
                   "_gravite", "_resistances_sans_sol", "_resistances_orig",
                   "_att_vol_annulee", "_encore", "_lire_esprit",
                   "_possessif_bloque", "_ten_danse_orig",
                   "_rapace_bloque", "_poids_double"]
    for joueur_check in [j1, j2]:
        for poke in joueur_check.get("pokemon", []):
            for champ in champs_temp:
                poke.pop(champ, None)
            # Réinitialiser compteurs Roulade/Taillade si Pokemon retiré ou KO
            if poke.get("ko") or poke.get("position") not in ("off", "def"):
                poke.pop("_roulade_compteur", None)
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
                    poke.pop("_bouclier", None)  # bouclier perdu si déplacé

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
                                                       niveau_max_pool=j.get("niveau_max_pool", 10),
                                                       joueur=j, est_reroll=False)
        j["boutique_locked"] = False
        j["a_achete_tour1"]  = False
    # Piocher le climat du prochain tour — visible au début du tour suivant
    piocher_climat(partie)

    # Distorsion : décrémenter le compteur
    gerer_distorsion(partie)

    # Si Distorsion vient d'être pioché, initialiser le compteur
    if partie.get("climat_actuel") == "Distorsion" and not partie.get("distorsion_tours"):
        partie["distorsion_tours"] = 3

    # Morpheo : transformation selon le nouveau climat
    for j in partie["joueurs"].values():
        appliquer_transformation_morpheo(j, partie.get("climat_actuel", "Ensoleillé"))

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
                partie, joueur["niveau"], ancienne_offre=joueur["boutique_offre"],
                niveau_max_pool=joueur.get("niveau_max_pool", 10),
                joueur=joueur, est_reroll=True)
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
        # ── Déblocage palier et gestion garantie ─────────────────────────────
        niv_poke = poke_data.get("niveau", 1)
        nmp = joueur.get("niveau_max_pool", 10)
        joueur.setdefault("niveaux_achetes", []).append(niv_poke)
        garantie_rolls = joueur.setdefault("garantie_rolls", {"11":0,"12":0,"13":0,"14":0})

        # Déblocage : achat d'un pokémon du palier max → débloque le palier suivant
        # Règles de déblocage par palier :
        #   pool 10→11 : atteindre niveau joueur 10 (géré ailleurs)
        #   pool 11→12 : acheter un niv 10 ou 11
        #   pool 12→13 : acheter un niv 12
        #   pool 13→14 : acheter un niv 13
        #   pool 14→15 : acheter un niv 14
        DEBLOCAGE = {10: 12, 11: 12, 12: 13, 13: 14, 14: 15}
        if niv_poke in DEBLOCAGE:
            nouveau_max = DEBLOCAGE[niv_poke]
            if nmp < nouveau_max:
                joueur["niveau_max_pool"] = nouveau_max

        # Reset du compteur de garantie du palier correspondant au niveau acheté
        # Ex: acheter niv 11 → reset compteur "11" (palier 10/11)
        # Ex: acheter niv 12 → reset compteur "12"
        if niv_poke in (10, 11):
            garantie_rolls["11"] = 0
        elif str(niv_poke) in garantie_rolls:
            garantie_rolls[str(niv_poke)] = 0
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
                poke_src["soin_tours_restants"] = 1

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
                poke.pop("_bouclier", None)  # bouclier perdu si déplacé
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
