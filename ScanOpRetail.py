import json
import os
import time
import random
import requests
from scipy.optimize import minimize_scalar

# =====================================================================
# 1. PARAMÈTRES GLOBAUX & CONFIGURATION
# =====================================================================

CHEMIN_DB = os.path.join(os.path.dirname(__file__), 'database.json')

BONUS_UI = 1.02      
QUANTITE_LOT = 1     

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
}

CONFIG_BATIMENTS = {
    "Groceries Store": {
        "niv_bat": 5,
        "salaire_bat": 755,
        "ids": ["3", "4", "5", "7", "8", "9", "119", "122", "123", "124", "125", "126", "127"]
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

try:
    with open(CHEMIN_DB, 'r', encoding='utf-8') as f:
        data = json.load(f)
except FileNotFoundError:
    print(f"Erreur : Le fichier {CHEMIN_DB} est introuvable.")
    exit(1)


# =====================================================================
# 2. MOTEUR MATHÉMATIQUE
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
    Uor = 370
    Kor_table = {"B": 2.28}
    RETAIL_MODELING_QUALITY_WEIGHT = 0.3 
    
    facteur_sat = min(max(2 - saturation, 0), 2)
    volume_min = max(0.9, facteur_sat / 2 + 0.5)
    
    L = stats["buildingLevelsNeededPerUnitPerHour"]
    Um = stats["modeledUnitsSoldAnHour"]
    k_val = Kor_table.get(str(id_obj), 1)
    
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
# 3. OPTIMISATEUR DE PROFIT
# =====================================================================

def trouver_profit_maximum(id_obj, stats, qualite, saturation, bonus_ui, prix_achat, quantite, salaire_horaire_batiment, niv_batiment):
    def objective(prix_test):
        temps_sec = calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix_test, quantite, niv_batiment)
        if temps_sec <= 0: return 1e9 
        
        temps_heures = temps_sec / 3600
        marge_totale = (prix_test - prix_achat) * quantite
        profit_horaire = (marge_totale / temps_heures) - salaire_horaire_batiment
        return -profit_horaire 

    res = minimize_scalar(
        objective, 
        bracket=(prix_achat + 0.01, prix_achat + 1000), 
        method='brent'
    )
    
    prix_optimal = round(res.x, 2)
    temps_sec = calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix_optimal, quantite, niv_batiment)
    
    if temps_sec <= 0:
        return prix_optimal, 0, {"temps_vente": 0, "profit_net_total": 0}
        
    temps_heures = temps_sec / 3600
    marge_totale = (prix_optimal - prix_achat) * quantite
    profit_max_reel = (marge_totale / temps_heures) - salaire_horaire_batiment
    
    return prix_optimal, profit_max_reel, {
        "temps_vente": temps_sec,
        "profit_net_total": marge_totale - (salaire_horaire_batiment * temps_heures)
    }


# =====================================================================
# 4. INTERFACES API MARCHÉ
# =====================================================================

def get_all_saturations():
    url = "https://www.simcompanies.com/api/v4/0/resources-retail-info/"
    saturations = {}
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status() 
        data_json = response.json()
        
        if isinstance(data_json, list):
            for item in data_json:
                item_id = str(item.get('dbLetter', ''))
                if item_id:
                    saturations[item_id] = float(item.get('saturation', 0.5))
        return saturations
    except Exception as e:
        print(f"  [!] Erreur réseau lors de la récupération des saturations globales : {e}")
        return {}

def get_best_offers_by_quality(id_obj, retries=4):
    url = f"https://www.simcompanies.com/api/v3/market/0/{id_obj}/"
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code == 429:
                wait_time = (2 ** attempt) * 5 + random.uniform(1, 3)
                print(f"  [!] Limite API (429). Pause de {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            if response.status_code != 200:
                time.sleep(2)
                continue
                
            data_json = response.json()
            if isinstance(data_json, list): offres = data_json
            elif isinstance(data_json, dict): offres = data_json.get("sellOrders", [])
            else: offres = []
                
            if not offres: return {}

            best_prices = {}
            for offre in offres:
                q = offre.get('quality', 0)
                p = offre.get('price', 0)
                if p <= 0: continue
                if q not in best_prices or p < best_prices[q]['price']:
                    best_prices[q] = {'price': p, 'quantity': offre.get('quantity', 0)}
            return best_prices
            
        except requests.exceptions.RequestException as e:
            wait_time = (2 ** attempt) * 2
            time.sleep(wait_time)
            
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
    print(f"\n{'='*80}")
    print(f"🚀 LANCEMENT DU SCAN MULTI-BÂTIMENTS")
    print(f"{'='*80}")
    
    print("\n📥 Téléchargement des saturations de marché...")
    saturations_globales = get_all_saturations()
    if not saturations_globales:
        print("⚠️ Attention : Impossible de récupérer les saturations globales. Utilisation de 0.5 par défaut.")
    else:
        print(f"✅ Saturations récupérées pour {len(saturations_globales)} ressources !")

    top_opportunites_batiments = {}
    
    for nom_batiment, config in CONFIG_BATIMENTS.items():
        print(f"\n>>> 🏬 RECHERCHE POUR : {nom_batiment.upper()} (Niv {config['niv_bat']}, Salaires {config['salaire_bat']}$/h) <<<")
        
        meilleure_opp_batiment = None
        profit_max_batiment = -float('inf')
        
        for obj_id in config["ids"]:
            if str(obj_id) not in data["phase_1"]:
                continue
                
            stats = data["phase_1"][str(obj_id)]
            item_name = stats.get("name", f"Item_{obj_id}")
            sat_reelle = saturations_globales.get(str(obj_id), 0.5)
            
            meilleures_offres = get_best_offers_by_quality(obj_id)
            time.sleep(random.uniform(2.0, 4.0)) 
            
            if not meilleures_offres:
                print(f"  - {item_name:<22} | Sat: {sat_reelle:6.1%} | Aucune offre en vente.")
                continue
                
            # Variables pour pister le meilleur profit de cet objet précis
            profit_max_item = -float('inf')
            meilleure_q_item = None
            
            for qualite, info in meilleures_offres.items():
                prix_achat = info['price']
                
                prix_vente_opt, profit_h, stats_opt = trouver_profit_maximum(
                    str(obj_id), stats, qualite, sat_reelle, BONUS_UI, 
                    prix_achat, QUANTITE_LOT, config['salaire_bat'], config['niv_bat']
                )
                
                # Mise à jour du meilleur profit pour cet objet
                if profit_h > profit_max_item:
                    profit_max_item = profit_h
                    meilleure_q_item = qualite
                
                # Mise à jour du meilleur profit GLOBAL pour le bâtiment
                if profit_h > profit_max_batiment:
                    profit_max_batiment = profit_h
                    meilleure_opp_batiment = {
                        "id": obj_id,
                        "name": item_name,
                        "q": qualite, 
                        "achat": prix_achat, 
                        "vente": prix_vente_opt, 
                        "profit": profit_h, 
                        "temps": stats_opt['temps_vente']
                    }
            
            # --- AFFICHAGE LORS DU DÉFILEMENT ---
            if profit_max_item > -float('inf'):
                print(f"  - {item_name:<22} | Sat: {sat_reelle:6.1%} | {len(meilleures_offres):>2} qualités | Max: {profit_max_item:8.2f} $/h (Q{meilleure_q_item})")
            else:
                print(f"  - {item_name:<22} | Sat: {sat_reelle:6.1%} | {len(meilleures_offres):>2} qualités | Aucun profit possible.")
        
        if meilleure_opp_batiment:
            top_opportunites_batiments[nom_batiment] = meilleure_opp_batiment

    # --- AFFICHAGE DES RÉSULTATS ---
    print(f"\n\n{'='*80}\n🏆 TABLEAU DE BORD : LES MEILLEURS COUPS PAR BÂTIMENT 🏆\n{'='*80}")
    
    if not top_opportunites_batiments:
        print("Aucune opportunité rentable trouvée sur l'ensemble des marchés.")
    else:
        for nom_bat, res in top_opportunites_batiments.items():
            print(f"\n📍 {nom_bat.upper()} :")
            print(f"   👉 Produit idéal : {res['name']} (ID {res['id']}, Qualité Q{res['q']})")
            print(f"   🛒 Acheter à : {res['achat']:.2f} $")
            print(f"   🏷️ Revendre à : {res['vente']:.2f} $")
            print(f"   ⏱️ Temps estimé : {format_temps(res['temps'])}")
            print(f"   💰 PROFIT MAX : {res['profit']:.2f} $/heure")
            
    print(f"\n{'='*80}")

if __name__ == "__main__":
    lancer_scan_complet()