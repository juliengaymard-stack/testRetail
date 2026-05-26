import json
import os
import time
import requests
from scipy.optimize import minimize_scalar

# =====================================================================
# 1. PARAMÈTRES GLOBAUX & CONFIGURATION
# =====================================================================

CHEMIN_DB = os.path.join(os.path.dirname(__file__), 'database.json')

# Paramètres de ton compte
BONUS_UI = 1.02      # Ton bonus affiché en jeu (ex: 2% de vitesse = 1.02)
QUANTITE_LOT = 1     # Base de calcul unitaire pour la rentabilité

# Configuration de tes bâtiments (Niveaux, Salaires horaires réels, IDs vendus)
CONFIG_BATIMENTS = {
    "Groceries Store": {
        "niv_bat": 5,
        "salaire_bat": 755,
        "ids": ["3", "4", "5", "8", "9", "119", "122", "123", "124", "125", "126", "127"]
    },
    "Fashion Store": {
        "niv_bat": 2,
        "salaire_bat": 679,
        "ids": ["60", "61", "62", "63", "64", "65"]
    },
    "Car Retail Store": {
        "niv_bat": 3,
        "salaire_bat": 1246,
        "ids": ["53", "54", "55", "56", "57"]
    }
}

# Chargement de la base de données locale
try:
    with open(CHEMIN_DB, 'r', encoding='utf-8') as f:
        data = json.load(f)
except FileNotFoundError:
    print(f"Erreur : Le fichier {CHEMIN_DB} est introuvable.")
    exit(1)


# =====================================================================
# 2. MOTEUR MATHÉMATIQUE (CALIBRÉ SUR LE CODE SERVEUR)
# =====================================================================

def calculer_prix_reference(resistivite, cout_prod, capacite_vente, salaire_magasin):
    return cout_prod + (resistivite + salaire_magasin) / capacite_vente

def calculer_resistance_prix(resistivite, prix_ref, prix_vente, salaire, cout_prod):
    elasticite_prix = (salaire + resistivite) / ((prix_ref - cout_prod)**2)
    return resistivite - (prix_vente - prix_ref)**2 * elasticite_prix

def calculer_temps_vente_secondes(velocite, cout_prod, salaire, prix, multiplicateur_bonus):
    return (multiplicateur_bonus * ((prix - cout_prod) * 3600) - salaire) / (velocite + salaire)

def calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix, quantite, niveau_bat):
    multiplicateur_bonus = 1 / bonus_ui 
    
    # Constantes serveur
    Uor = 370
    Kor_table = {"B": 2.28}
    RETAIL_MODELING_QUALITY_WEIGHT = 0.3 # La constante serveur vitale pour la précision
    
    # Physique du marché
    facteur_sat = min(max(2 - saturation, 0), 2)
    volume_min = max(0.9, facteur_sat / 2 + 0.5)
    
    L = stats["buildingLevelsNeededPerUnitPerHour"]
    Um = stats["modeledUnitsSoldAnHour"]
    k_val = Kor_table.get(str(id_obj), 1)
    
    # Application du poids de la qualité
    f = qualite / 12
    resistivite = Uor * (L * Um + 1) * k_val * (facteur_sat / 2 * (1 + f * RETAIL_MODELING_QUALITY_WEIGHT))
    capacite_vente = Um * volume_min
    
    salaire = stats.get("modeledStoreWages", 0)
    cout_prod = stats["modeledProductionCostPerUnit"]
    
    prix_ref = calculer_prix_reference(resistivite, cout_prod, capacite_vente, salaire)
    velocite = calculer_resistance_prix(resistivite, prix_ref, prix, salaire, cout_prod)
    
    temps_sec = calculer_temps_vente_secondes(velocite, cout_prod, salaire, prix, multiplicateur_bonus)
    
    return (temps_sec * quantite) / niveau_bat


# =====================================================================
# 3. OPTIMISATEUR DE PROFIT (ALGORITHME BRENT)
# =====================================================================

def trouver_profit_maximum(id_obj, stats, qualite, saturation, bonus_ui, prix_achat, quantite, salaire_horaire_batiment, niv_batiment):
    def objective(prix_test):
        temps_sec = calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix_test, quantite, niv_batiment)
        
        # Pénalité si le prix rend la vente impossible
        if temps_sec <= 0: return 1e9 
        
        temps_heures = temps_sec / 3600
        marge_totale = (prix_test - prix_achat) * quantite
        profit_horaire = (marge_totale / temps_heures) - salaire_horaire_batiment
        
        return -profit_horaire # Inversé pour que minimize_scalar trouve le maximum

    # Solveur non borné pour trouver le sommet naturel
    res = minimize_scalar(
        objective, 
        bracket=(prix_achat + 1, prix_achat + 1000), 
        method='brent'
    )
    
    prix_optimal = res.x
    profit_max = -res.fun
    
    temps_sec = calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix_optimal, quantite, niv_batiment)
    
    return prix_optimal, profit_max, {
        "temps_vente": temps_sec,
        "profit_net_total": ((prix_optimal - prix_achat) * quantite) - (salaire_horaire_batiment * (temps_sec/3600))
    }


# =====================================================================
# 4. INTERFACES API MARCHÉ
# =====================================================================
'''
def get_all_saturations():
    """Récupère la saturation de TOUTES les ressources en une seule requête."""
    url = "https://www.simcompanies.com/api/v4/0/resources-retail-info/"
    saturations = {}
    try:
        response = requests.get(url).json()
        
        if isinstance(response, list):
            for item in response:
                # L'API peut utiliser différentes clés selon les versions (kind, db_letter, id)
                item_id = str(item.get('kind', item.get('db_letter', item.get('id', ''))))
                if item_id:
                    saturations[item_id] = float(item.get('saturation', 0.5))
        elif isinstance(response, dict):
            for k, v in response.items():
                saturations[str(k)] = float(v.get('saturation', 0.5))
                
        return saturations
    except Exception as e:
        print(f"Erreur API Globale Saturation : {e}")
        return {}
'''
def get_all_saturations():
    """Récupère la saturation de TOUTES les ressources en une seule requête."""
    url = "https://www.simcompanies.com/api/v4/0/resources-retail-info/"
    
    # Fausse identité pour éviter le blocage
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    saturations = {}
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status() 
        
        data_json = response.json()
        
        if isinstance(data_json, list):
            for item in data_json:
                # --- CORRECTION ICI : dbLetter avec un L majuscule ---
                item_id = str(item.get('dbLetter', ''))
                if item_id:
                    saturations[item_id] = float(item.get('saturation', 0.5))
                    
        return saturations
    except Exception as e:
        print(f"  [!] Erreur réseau lors de la récupération des saturations globales : {e}")
        return {}

def get_best_offers_by_quality(id_obj):
    """Récupère les offres de marché pour un objet spécifique."""
    url = f"https://www.simcompanies.com/api/v3/market/0/{id_obj}/"
    try:
        response = requests.get(url).json()
        
        if isinstance(response, list):
            offres = response
        elif isinstance(response, dict):
            offres = response.get("sellOrders", [])
        else:
            offres = []
            
        if not offres: return {}

        best_prices = {}
        for offre in offres:
            q = offre.get('quality', 0)
            p = offre.get('price', 0)
            if p <= 0: continue
            
            if q not in best_prices or p < best_prices[q]['price']:
                best_prices[q] = {'price': p, 'quantity': offre.get('quantity', 0)}
                
        return best_prices
        
    except Exception as e:
        print(f"Erreur API Offres (ID {id_obj}) : {e}")
        return {}


# =====================================================================
# 5. UTILITAIRES & BOUCLE PRINCIPALE
# =====================================================================

def format_temps(s):
    if s <= 0: return "Impossible"
    h, m = divmod(int(s), 3600)
    m, s = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"

def lancer_scan_complet():
    print(f"\n{'='*70}")
    print(f"🚀 LANCEMENT DU SCAN MULTI-BÂTIMENTS")
    print(f"{'='*70}")
    
    # --- 1. CHARGEMENT DE LA SATURATION GLOBALE ---
    print("\n📥 Téléchargement des saturations de marché...")
    saturations_globales = get_all_saturations()
    if not saturations_globales:
        print("⚠️ Attention : Impossible de récupérer les saturations globales. Utilisation de 0.5 par défaut.")
    else:
        print(f"✅ Saturations récupérées pour {len(saturations_globales)} ressources !")

    top_opportunites_batiments = {}
    
    # --- 2. ANALYSE PAR BÂTIMENT ---
    for nom_batiment, config in CONFIG_BATIMENTS.items():
        print(f"\n>>> 🏬 RECHERCHE POUR : {nom_batiment.upper()} (Niv {config['niv_bat']}, Salaires {config['salaire_bat']}$/h) <<<")
        
        meilleure_opp_batiment = None
        profit_max_batiment = -float('inf')
        
        for obj_id in config["ids"]:
            if str(obj_id) not in data["phase_1"]:
                continue
                
            stats = data["phase_1"][str(obj_id)]
            
            # Récupération de la saturation depuis le dictionnaire téléchargé
            sat_reelle = saturations_globales.get(str(obj_id), 0.5)
            
            # Seule requête externe à l'intérieur de la boucle
            meilleures_offres = get_best_offers_by_quality(obj_id)
            
            time.sleep(1.2) # Temporisation cruciale pour éviter d'être bloqué par le serveur
            
            if not meilleures_offres:
                print(f"  - ID {obj_id:>3} | Sat: {sat_reelle:6.1%} | Aucune offre en vente.")
                continue
                
            print(f"  - ID {obj_id:>3} | Sat: {sat_reelle:6.1%} | {len(meilleures_offres)} qualités analysées...")
            
            for qualite, info in meilleures_offres.items():
                prix_achat = info['price']
                
                prix_vente_opt, profit_h, stats_opt = trouver_profit_maximum(
                    str(obj_id), stats, qualite, sat_reelle, BONUS_UI, 
                    prix_achat, QUANTITE_LOT, config['salaire_bat'], config['niv_bat']
                )
                
                if profit_h > profit_max_batiment:
                    profit_max_batiment = profit_h
                    meilleure_opp_batiment = {
                        "id": obj_id,
                        "q": qualite, 
                        "achat": prix_achat, 
                        "vente": prix_vente_opt, 
                        "profit": profit_h, 
                        "temps": stats_opt['temps_vente']
                    }
        
        # Sauvegarde du grand vainqueur de ce bâtiment
        if meilleure_opp_batiment:
            top_opportunites_batiments[nom_batiment] = meilleure_opp_batiment

    # --- 3. AFFICHAGE DES RÉSULTATS ---
    print(f"\n\n{'='*70}\n🏆 TABLEAU DE BORD : LES MEILLEURS COUPS PAR BÂTIMENT 🏆\n{'='*70}")
    
    if not top_opportunites_batiments:
        print("Aucune opportunité rentable trouvée sur l'ensemble des marchés.")
    else:
        for nom_bat, res in top_opportunites_batiments.items():
            print(f"\n📍 {nom_bat.upper()} :")
            print(f"   👉 Produit idéal : ID {res['id']} (Qualité Q{res['q']})")
            print(f"   🛒 Acheter à : {res['achat']} $")
            print(f"   🏷️ Revendre à : {res['vente']:.0f} $")
            print(f"   ⏱️ Temps estimé : {format_temps(res['temps'])}")
            print(f"   💰 PROFIT MAX : {res['profit']:.2f} $/heure")
            
    print(f"\n{'='*70}")

# Exécution du script
if __name__ == "__main__":
    lancer_scan_complet()