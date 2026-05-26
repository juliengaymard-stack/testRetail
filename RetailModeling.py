import json
import os
import requests
from scipy.optimize import minimize_scalar

# --- CHARGEMENT ---
chemin = os.path.join(os.path.dirname(__file__), 'database.json')
with open(chemin, 'r', encoding='utf-8') as f:
    data = json.load(f)

# --- 1. FONCTIONS DU MOTEUR ÉCONOMIQUE ---
# Ces fonctions sont la traduction exacte de la logique serveur (ex-G7r, V7r...)

def calculer_prix_reference(resistivite, cout_prod, capacite_vente, salaire_magasin):
    """Calcule le 'v' : le prix d'équilibre théorique du marché."""
    return cout_prod + (resistivite + salaire_magasin) / capacite_vente

def calculer_resistance_prix(resistivite, prix_ref, prix_vente, salaire, cout_prod):
    """Calcule le 'b' : la vélocité ajustée (parabole)."""
    # Équation de l'élasticité (a)
    elasticite_prix = (salaire + resistivite) / ((prix_ref - cout_prod)**2)
    # Calcul de la courbe parabolique
    return resistivite - (prix_vente - prix_ref)**2 * elasticite_prix

def calculer_temps_vente_secondes(velocite, cout_prod, salaire, prix, multiplicateur_bonus):
    """Calcule le temps en secondes pour 1 unité (q7r)."""
    # Note: Le bonus est ici appliqué sous sa forme inverse (1 / bonus_ui)
    return (multiplicateur_bonus * ((prix - cout_prod) * 3600) - salaire) / (velocite + salaire)

def get_market_saturation(id_obj):
    """Récupère la saturation actuelle du marché pour un ID donné."""
    # Le endpoint API standard pour les infos de marché (saturation, prix moyen, etc.)
    url = f"https://www.simcompanies.com/api/v3/market/info/{id_obj}/"
    try:
        response = requests.get(url).json()
        # On extrait la clé 'marketSaturation' (ou valeur par défaut 0.5 si échec)
        # Attention : s'assurer que la clé est bien nommée comme cela dans ton retour JSON
        return float(response.get('marketSaturation', 0.5))
    except Exception as e:
        print(f"Erreur lors de la récupération de la saturation pour {id_obj}: {e}")
        return 0.5 # Valeur neutre de sécurité

# --- 2. FONCTION PRINCIPALE ---
def calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix, quantite, niveau_bat):
    
    # 1. Préparation des variables
    # Le moteur utilise un multiplicateur de bonus inversé
    multiplicateur_bonus = 1 / bonus_ui 
    
    # Constantes du moteur
    Uor = 370
    Kor_table = {"B": 2.28}
    QUALITE_WEIGHT = 0.3
    
    # 2. Calculs de physique du marché
    # Facteur de saturation clampé entre 0 et 2
    facteur_sat = min(max(2 - saturation, 0), 2)
    volume_min = max(0.9, facteur_sat / 2 + 0.5)
    
    # Calcul des variables de base (L = niveaux, Um = unités/h)
    L = stats["buildingLevelsNeededPerUnitPerHour"]
    Um = stats["modeledUnitsSoldAnHour"]
    k_val = Kor_table.get(id_obj, 1) # Valeur de catégorie (1 par défaut)
    
    # Calcul de la résistivité globale (g)
    resistivite = Uor * (L * Um + 1) * k_val * (facteur_sat / 2 * (1 + (qualite / 12) * QUALITE_WEIGHT))
    capacite_vente = Um * volume_min
    
    # 3. Exécution de la chaîne mathématique
    salaire = stats.get("modeledStoreWages", 0)
    
    prix_ref = calculer_prix_reference(resistivite, stats["modeledProductionCostPerUnit"], capacite_vente, salaire)
    velocite = calculer_resistance_prix(resistivite, prix_ref, prix, salaire, stats["modeledProductionCostPerUnit"])
    
    temps_sec = calculer_temps_vente_secondes(velocite, stats["modeledProductionCostPerUnit"], salaire, prix, multiplicateur_bonus)
    
    # 4. Application finale (Quantité et Niveau)
    return (temps_sec * quantite) / niveau_bat

# Affichage
def format_temps(s):
    h, m = divmod(int(s), 3600)
    m, s = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def trouver_profit_maximum(id_obj, stats, qualite, saturation, bonus_ui, prix_achat, quantite, salaire_horaire_batiment, niv_batiment):
    """
    Optimisation libre : le solveur cherche le sommet naturel de la courbe 
    sans être bloqué par des bornes artificielles.
    """
    
    def objective(prix_test):
        # 1. Calcul temps de vente
        temps_sec = calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix_test, quantite, niv_batiment)
        
        # 2. Gestion sécurité : Si le prix est aberrant ou temps impossible
        if temps_sec <= 0: return 1e9 
        
        # 3. Calcul profit horaire
        temps_heures = temps_sec / 3600
        marge_totale = (prix_test - prix_achat) * quantite
        profit_horaire = (marge_totale / temps_heures) - salaire_horaire_batiment
        
        # On retourne le négatif pour maximiser
        return -profit_horaire

    # On utilise 'brent' qui n'a pas besoin de limites strictes (bounds)
    # On donne juste un bracket de départ très large [achat+1, achat+50000]
    # Le solveur explorera au-delà si nécessaire.
    res = minimize_scalar(
        objective, 
        bracket=(prix_achat + 1, prix_achat + 1000), 
        method='brent'
    )
    
    prix_optimal = res.x
    profit_max = -res.fun
    
    # Recalcul final
    temps_sec = calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix_optimal, quantite, niv_batiment)
    
    return prix_optimal, profit_max, {
        "temps_vente": temps_sec,
        "profit_net_total": ((prix_optimal - prix_achat) * quantite) - (salaire_horaire_batiment * (temps_sec/3600))
    }

def get_best_offers_by_quality(id_obj):
    """Récupère les meilleures offres du marché par qualité, avec gestion du format API."""
    url = f"https://www.simcompanies.com/api/v3/market/0/{id_obj}/"
    try:
        response = requests.get(url).json()
        
        # --- CORRECTION ICI ---
        # Si la réponse est une liste, c'est que l'API renvoie directement les ordres
        if isinstance(response, list):
            offres = response
        # Si c'est un dictionnaire, on cherche "sellOrders"
        elif isinstance(response, dict):
            offres = response.get("sellOrders", [])
        else:
            offres = []
        
        if not offres:
            return {}

        # Dictionnaire pour stocker le min prix par qualité : {qualite: prix}
        best_prices = {}
        
        for offre in offres:
            # Assure-toi que les clés existent (l'API peut renvoyer des structures variées)
            q = offre.get('quality', 0)
            p = offre.get('price', 0)
            
            # On ignore les offres à prix 0 ou invalides
            if p <= 0: continue
            
            if q not in best_prices or p < best_prices[q]['price']:
                best_prices[q] = {'price': p, 'quantity': offre.get('quantity', 0)}
                
        return best_prices
        
    except Exception as e:
        print(f"Erreur API Marché : {e}")
        return {}


def analyser_opportunites(id_obj, stats, saturation, bonus, salaire_bat, niv_bat, quantite):
    """
    Récupère les offres du marché, et pour chaque qualité, 
    calcule le prix de vente optimal pour maximiser le profit horaire.
    """
    # 1. Récupérer les meilleures offres par qualité
    meilleures_offres = get_best_offers_by_quality(id_obj)
    
    if not meilleures_offres:
        print("Aucune offre trouvée sur le marché.")
        return

    resultats = []

    print(f"\n--- ANALYSE DES OPPORTUNITÉS (ID {id_obj}) ---")
    
    # 2. Boucle sur chaque qualité disponible sur le marché
    for qualite, info in meilleures_offres.items():
        prix_achat = info['price']
        
        # On lance l'optimiseur pour CETTE qualité spécifique
        # Note: 'qualite' ici provient de l'offre marché, donc on l'injecte dans le moteur
        prix_vente_opt, profit_h, stats_opt = trouver_profit_maximum(
            id_obj, stats, qualite, saturation, bonus, prix_achat, quantite, salaire_bat, niv_bat
        )
        
        # Stockage pour comparaison
        resultats.append({
            "qualite": qualite,
            "prix_achat": prix_achat,
            "prix_vente_opt": prix_vente_opt,
            "profit_h": profit_h,
            "stats": stats_opt
        })
        
        print(f"Qualité Q{qualite} | Achat: {prix_achat}$ | Vente opt: {prix_vente_opt:.0f}$ | Profit: {profit_h:.2f}$/h")

    # 3. Trier pour trouver la MEILLEURE opportunité
    # On trie par profit_h décroissant
    meilleur_choix = max(resultats, key=lambda x: x['profit_h'])
    
    print(f"\n✅ MEILLEUR COUP À JOUER :")
    print(f"-> Acheter Qualité Q{meilleur_choix['qualite']} à {meilleur_choix['prix_achat']}$")
    print(f"-> Revendre à {meilleur_choix['prix_vente_opt']:.0f}$")
    print(f"-> Profit Horaire Net : {meilleur_choix['profit_h']:.2f}$/h")
    print(f"-> Temps de vente : {format_temps(meilleur_choix['stats']['temps_vente'])}")

def lancer_scan_complet():
    print(f"\n{'='*50}")
    print(f"LANCEMENT DU SCAN AUTOMATISÉ AVEC SATURATION DYNAMIQUE")
    print(f"{'='*50}")
    
    rapport_global = []
    
    for obj_id in items_a_scanner:
        if obj_id not in data["phase_1"]:
            continue
            
        stats = data["phase_1"][obj_id]
        
        # --- RÉCUPÉRATION DYNAMIQUE DE LA SATURATION ---
        saturation_reelle = get_market_saturation(obj_id)
        print(f"\n--- Analyse ID: {obj_id} (Saturation: {saturation_reelle:.2%}) ---")
        
        # Récupération des opportunités
        meilleures_offres = get_best_offers_by_quality(obj_id)
        
        if not meilleures_offres:
            continue
            
        # Comparaison des qualités
        meilleure_opportunite_item = None
        profit_max_item = -float('inf')
        
        for qualite, info in meilleures_offres.items():
            prix_achat = info['price']
            
            # --- PASSAGE DE LA SATURATION RÉELLE ICI ---
            prix_vente_opt, profit_h, stats_opt = trouver_profit_maximum(
                obj_id, stats, qualite, saturation_reelle, bonus, prix_achat, quantite, salaire_bat, niv_bat
            )
            
            if profit_h > profit_max_item:
                profit_max_item = profit_h
                meilleure_opportunite_item = {
                    "q": qualite, "achat": prix_achat, "vente": prix_vente_opt, 
                    "profit": profit_h, "temps": stats_opt['temps_vente']
                }
        
        if meilleure_opportunite_item:
            rapport_global.append((obj_id, meilleure_opportunite_item))
            print(f"Meilleur coup: Q{meilleure_opportunite_item['q']} | Profit: {meilleure_opportunite_item['profit']:.2f}$/h")

    # --- SYNTHÈSE FINALE ---
    print(f"\n\n{'='*50}\nSYNTHÈSE DU MARCHÉ\n{'='*50}")
    for item_id, res in rapport_global:
        print(f"Item {item_id}: Achète Q{res['q']} à {res['achat']}$ -> Revends {res['vente']:.0f}$ => {res['profit']:.2f}$/h")

# --- LANCEMENT ---
lancer_scan_complet()

# --- LANCEMENT DE L'ANALYSE ---
# Utilise les mêmes variables que ton script
analyser_opportunites(
    id_obj="57", 
    stats=data["phase_1"]["57"], 
    saturation=0.37917, 
    bonus=1.02, 
    salaire_bat=830, 
    niv_bat=2, 
    quantite=1
)
