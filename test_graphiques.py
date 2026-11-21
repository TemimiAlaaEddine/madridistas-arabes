"""Vérification rapide, sans navigateur ni réseau : python test_graphiques.py (le rendu PNG se vérifie avec graphiques.py)."""
import graphiques as g

stats = {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
    {"key": "ballPossession", "homeValue": 32, "awayValue": 68}, {"key": "expectedGoals", "homeValue": 0.18, "awayValue": 2.34}]}]}]}
svg = g.comparaison(stats, rm_dom=False, noms=("ريال مدريد", "فالنسيا"))
assert "68%" in svg and "2.34" in svg and "0.18" in svg, "valeurs du Real Madrid (à l'extérieur) bien lues"

joueur = lambda nom: {"name": nom, "fieldTranslations": {"shortNameTranslation": {"ar": f"ك. {nom}"}}}
tirs = [{"isHome": False, "time": 28, "xg": 0.1, "shotType": "goal", "player": joueur("فالفيردي"), "playerCoordinates": {"x": 20, "y": 40}},
        {"isHome": True, "time": 60, "xg": 0.05, "shotType": "miss", "player": joueur("سادق"), "playerCoordinates": {"x": 15, "y": 50}},
        {"isHome": False, "time": 75, "xg": 0.5, "shotType": "goal", "goalType": "own", "player": joueur("غايا"), "playerCoordinates": {"x": 5, "y": 50}}]
courbe = g.chronologie(tirs, rm_dom=False, noms=("ريال مدريد", "فالنسيا"), officiel={True: 0.6, False: 0.05})
assert "فالفيردي د28" in courbe and "غايا" not in courbe, "but marqué nommé, but contre son camp sans point"
assert "0.60" in courbe, "total officiel affiché en bout de courbe"
resume, carte = g.carte_tirs(tirs, rm_dom=False, xg_officiel=0.6)
assert resume.startswith("2 تسديدة") and carte.count("<circle cx") == 2 + 1, "seulement les tirs du Real Madrid (+ point de penalty)"
assert g.nom_court(joueur("كورتوا")) == "كورتوا"
print("OK")
