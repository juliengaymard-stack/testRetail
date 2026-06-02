import json
import os
import time
import random
import requests
import itertools
from scipy.optimize import minimize_scalar, brentq

# =====================================================================
# 1. PARAMÈTRES GLOBAUX & CONFIGURATION
# =====================================================================

CHEMIN_DB = os.path.join(os.path.dirname(__file__), 'database.json')

BONUS_UI = 1.02      
QUANTITE_LOT = 1     

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# --- TON EMPIRE IMMOBILIER RÉEL ---
# Chaque bâtiment est une entité unique. Facilement modifiable via une UI plus tard.
CONFIG_BATIMENTS = {
    "Car Retail Store #1": {"niv_bat": 3, "salaire_bat": 1259, "ids": ["53", "54", "55", "56", "57"]},
    "Car Retail Store #2": {"niv_bat": 3, "salaire_bat": 1259, "ids": ["53", "54", "55", "56", "57"]},
    "Car Retail Store #3": {"niv_bat": 3, "salaire_bat": 1259, "ids": ["53", "54", "55", "56", "57"]},
    "Car Retail Store #4": {"niv_bat": 3, "salaire_bat": 1259, "ids": ["53", "54", "55", "56", "57"]},
    "Fashion Store #1":    {"niv_bat": 2, "salaire_bat": 687,  "ids": ["60", "61", "62", "63", "64", "65"]},
    "Groceries Store #1":  {"niv_bat": 5, "salaire_bat": 763,  "ids": ["3", "4", "5", "8", "9", "119", "122", "123", "124", "125", "126", "127"]}
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
    denominateur = velocite + salaire
    if denominateur <= 0:
        return -1
    return (multiplicateur_bonus * (prix - cout_prod) * 3600) / denominateur

def calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix, quantite, niveau_bat):
    multiplicateur_bonus = 1 / bonus_ui 
    Uor = 370
    Kor_table = {"B": 2.28}
    RETAIL_WEIGHT = 0.3 
    
    facteur_sat = min(max(2 - saturation, 0), 2)
    volume_min = max(0.9, facteur_sat / 2 + 0.5)
    
    L = stats["buildingLevelsNeededPerUnitPerHour"]
    Um = stats["modeledUnitsSoldAnHour"]
    k_val = Kor_table.get(str(id_obj), 1)
    
    f = qualite / 12
    resistivite = Uor * (L * Um + 1) * k_val * (facteur_sat / 2 * (1 + f * RETAIL_WEIGHT))
    capacite_vente = Um * volume_min
    
    salaire = stats.get("modeledStoreWages", 0)
    cout_prod = stats["modeledProductionCostPerUnit"]
    
    prix_ref = calculer_prix_reference(resistivite, cout_prod, capacite_vente, salaire)
    velocite = calculer_resistance_prix(resistivite, prix_ref, prix, salaire, cout_prod)
    temps_sec = calculer_temps_vente_secondes(velocite, cout_prod, salaire, prix, multiplicateur_bonus)
    
    return (temps_sec * quantite) / niveau_bat

def trouver_profit_maximum(id_obj, stats, qualite, saturation, bonus_ui, prix_achat, quantite, salaire_horaire_batiment, niv_batiment):
    def objective(prix_test):
        temps_sec = calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix_test, quantite, niv_batiment)
        if temps_sec <= 0: return 1e9 
        temps_heures = temps_sec / 3600
        profit_horaire = (((prix_test - prix_achat) * quantite) / temps_heures) - salaire_horaire_batiment
        return -profit_horaire 

    res = minimize_scalar(objective, bracket=(prix_achat + 0.01, prix_achat + 1000), method='brent')
    prix_optimal = round(res.x, 2)
    temps_sec = calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix_optimal, quantite, niv_batiment)
    
    if temps_sec <= 0: return prix_optimal, 0, {"temps_vente": 0, "profit_net_total": 0}
        
    temps_heures = temps_sec / 3600
    profit_max_reel = (((prix_optimal - prix_achat) * quantite) / temps_heures) - salaire_horaire_batiment
    
    return prix_optimal, profit_max_reel, {"temps_vente": temps_sec}


# =====================================================================
# 3. INTERFACES API MARCHÉ
# =====================================================================

def get_all_saturations():
    url = "https://www.simcompanies.com/api/v4/0/resources-retail-info/"
    saturations = {}
    try:
        res = requests.get(url, headers=HEADERS, timeout=10).json()
        if isinstance(res, list):
            for item in res:
                item_id = str(item.get('dbLetter', ''))
                if item_id: saturations[item_id] = float(item.get('saturation', 0.5))
        return saturations
    except:
        return {}

def get_best_offers_by_quality(id_obj):
    url = f"https://www.simcompanies.com/api/v3/market/0/{id_obj}/"
    for attempt in range(4):
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 429:
                time.sleep((2 ** attempt) * 1 + 0.5)
                continue
            if res.status_code != 200:
                time.sleep(0.2)
                continue
            
            offres = res.json()
            if isinstance(offres, dict): offres = offres.get("sellOrders", [])
            
            best_prices = {}
            for o in offres:
                q, p = o.get('quality', 0), o.get('price', 0)
                if p > 0 and (q not in best_prices or p < best_prices[q]['price']):
                    best_prices[q] = p
            return best_prices
        except:
            time.sleep(0.1)
    return {}


# =====================================================================
# 4. L'OPTIMISEUR COMBINATOIRE DE PORTEFEUILLE 
# =====================================================================

def evaluer_combinaison(combo, budget_total):
    choix_tries = sorted(combo, key=lambda x: x['roce'], reverse=True)
    
    profit_total = 0
    budget_restant = budget_total
    details = []

    for choix in choix_tries:
        if choix['cost'] == 0:
            details.append({"choix": choix, "ratio": 0, "statut": "Vide (Volontaire)"})
            continue
            
        if budget_restant >= choix['cost']:
            profit_total += choix['profit']
            budget_restant -= choix['cost']
            details.append({"choix": choix, "ratio": 1.0, "statut": "✅ Plein (100%)"})
        elif budget_restant > 0:
            ratio = budget_restant / choix['cost']
            profit_total += choix['profit'] * ratio
            details.append({"choix": choix, "ratio": ratio, "statut": f"⚠️ Partiel ({ratio:.0%})"})
            budget_restant = 0
        else:
            details.append({"choix": choix, "ratio": 0.0, "statut": "❌ Manque de Cash"})
            
    return profit_total, details, budget_restant

def optimiser_allocation_budget(budget_total, heures_cibles):
    print(f"\n{'='*80}")
    print(f"🧠 DIRECTEUR FINANCIER : ALLOCATION DU CAPITAL")
    print(f"🏢 Empire : {len(CONFIG_BATIMENTS)} Bâtiments | 💵 Cash : {budget_total:,.0f} $ | ⏱️ Temps : {heures_cibles}h")
    print(f"{'='*80}")

    print("📥 1. Scan global du marché en cours...")
    saturations = get_all_saturations()
    
    # Pour ne pas requêter l'API 4 fois pour les 4 Car Retail Stores, 
    # on met en cache les offres récupérées.
    cache_offres = {} 
    toutes_options_par_batiment = {}

    for nom_batiment, config in CONFIG_BATIMENTS.items():
        options_batiment = []
        options_batiment.append({"batiment": nom_batiment, "item_name": "Aucun", "cost": 0, "profit": 0, "roce": 0})
        
        for obj_id in config["ids"]:
            if str(obj_id) not in data["phase_1"]: continue
            stats = data["phase_1"][str(obj_id)]
            item_name = stats.get("name", f"Item_{obj_id}")
            sat_reelle = saturations.get(str(obj_id), 0.5)
            
            if obj_id not in cache_offres:
                cache_offres[obj_id] = get_best_offers_by_quality(obj_id)
                time.sleep(0.1)
            
            offres = cache_offres[obj_id]
            
            for q, prix_achat in offres.items():
                prix_vente, profit_h, stats_opt = trouver_profit_maximum(
                    str(obj_id), stats, q, sat_reelle, BONUS_UI, prix_achat, 1, config['salaire_bat'], config['niv_bat']
                )
                
                t_sec = stats_opt["temps_vente"]
                if t_sec <= 0 or profit_h <= 0: continue
                
                unites_totales = (3600 / t_sec) * heures_cibles
                cout_total = unites_totales * prix_achat
                profit_total = profit_h * heures_cibles
                roce = profit_total / cout_total if cout_total > 0 else 0
                
                options_batiment.append({
                    "batiment": nom_batiment, "id": obj_id, "item_name": item_name, "q": q,
                    "prix_achat": prix_achat, "prix_vente": prix_vente, 
                    "quantite": unites_totales, "cost": cout_total, 
                    "profit": profit_total, "roce": roce
                })
                
        # Frontière de Pareto stricte pour éviter l'explosion combinatoire
        options_batiment.sort(key=lambda x: x['cost'])
        options_epurees = []
        max_profit_vu = -1
        
        for opt in options_batiment:
            if opt['profit'] > max_profit_vu:
                options_epurees.append(opt)
                max_profit_vu = opt['profit']
                
        toutes_options_par_batiment[nom_batiment] = options_epurees
    
    # 2. Simulation Mathématique
    # On calcule combien de combinaisons on va tester pour le log.
    nb_combinaisons = 1
    for opt_list in toutes_options_par_batiment.values():
        nb_combinaisons *= len(opt_list)
        
    print(f"🧮 2. Analyse combinatoire : {nb_combinaisons:,.0f} scénarios stratégiques testés...")
    
    listes_options = list(toutes_options_par_batiment.values())
    combinaisons = list(itertools.product(*listes_options))
    
    meilleur_profit_global = -1
    meilleur_plan_action = None
    cash_restant_final = 0

    for combo in combinaisons:
        profit, details, cash_rest = evaluer_combinaison(combo, budget_total)
        if profit > meilleur_profit_global:
            meilleur_profit_global = profit
            meilleur_plan_action = details
            cash_restant_final = cash_rest

    # 3. Affichage du résultat
    print(f"\n{'='*80}")
    print(f"🏆 PLAN D'ACTION STRATÉGIQUE OPTIMAL")
    print(f"{'='*80}")
    
    meilleur_plan_action.sort(key=lambda x: list(CONFIG_BATIMENTS.keys()).index(x['choix']['batiment']))
    
    for action in meilleur_plan_action:
        c = action['choix']
        ratio = action['ratio']
        print(f"\n📍 {c['batiment'].upper()} : {action['statut']}")
        
        if c['cost'] > 0 and ratio > 0:
            q_reelle = c['quantite'] * ratio
            cout_reel = c['cost'] * ratio
            profit_reel = c['profit'] * ratio
            heures_reelles = heures_cibles * ratio
            
            print(f"   👉 Produit    : {c['item_name']} (Qualité Q{c['q']})")
            print(f"   🛒 Ordre      : {q_reelle:.0f} unités à {c['prix_achat']:.2f}$ (Total: {cout_reel:,.0f} $)")
            print(f"   🏷️ Revente    : {c['prix_vente']:.2f} $")
            print(f"   ⏱️ Durée      : {heures_reelles:.1f} heures")
            print(f"   💰 Profit Net : {profit_reel:,.0f} $ (ROCE: {c['roce']*100:.1f}%)")
        elif c['cost'] > 0 and ratio == 0:
            print(f"   ❌ Ignoré pour privilégier la trésorerie d'autres bâtiments plus rentables.")

    print(f"\n{'-'*80}")
    print(f"💵 Trésorerie dormante (inutilisée) : {cash_restant_final:,.0f} $")
    print(f"🚀 PROFIT NET TOTAL GÉNÉRÉ        : {meilleur_profit_global:,.0f} $")
    print(f"{'='*80}\n")


# =====================================================================
# MENU DE LANCEMENT
# =====================================================================
if __name__ == "__main__":
    
    # Règle ici ton Cash en banque et le temps que tu veux couvrir
    optimiser_allocation_budget(budget_total=250000, heures_cibles=8)