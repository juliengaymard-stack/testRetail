import streamlit as st
import json
import time
import requests
from scipy.optimize import minimize_scalar
import pandas as pd
from datetime import datetime

# =====================================================================
# CONFIGURATION STREAMLIT
# =====================================================================
st.set_page_config(
    page_title="SimCompanies Market Scanner",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS personnalisé
st.markdown("""
    <style>
    .metric-card { 
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .profit-high { color: #2ecc71; font-weight: bold; }
    .profit-low { color: #e74c3c; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# =====================================================================
# 1. PARAMÈTRES GLOBAUX & CONFIGURATION
# =====================================================================

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
# 3. INTERFACES API (AVEC CACHE)
# =====================================================================

@st.cache_data(ttl=3600)
def load_database():
    """Charge la base de données locale."""
    try:
        with open('database.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        st.error("❌ Fichier database.json introuvable. Veuillez le placer dans le répertoire.")
        return {"phase_1": {}}

@st.cache_data(ttl=300)
def get_all_saturations():
    """Récupère les saturations du marché (cache 5 min)."""
    url = "https://www.simcompanies.com/api/v4/0/resources-retail-info/"
    
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
                item_id = str(item.get('dbLetter', ''))
                if item_id:
                    saturations[item_id] = float(item.get('saturation', 0.5))
                    
        return saturations
    except Exception as e:
        st.warning(f"⚠️ Erreur lors de la récupération des saturations: {e}")
        return {}

@st.cache_data(ttl=300)
def get_best_offers_by_quality(id_obj):
    """Récupère les meilleures offres pour un produit."""
    url = f"https://www.simcompanies.com/api/v3/market/0/{id_obj}/"
    try:
        response = requests.get(url, timeout=10).json()
        
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
        return {}


# =====================================================================
# 4. UTILITAIRES
# =====================================================================

def format_temps(s):
    if s <= 0: return "Impossible"
    h, m = divmod(int(s), 3600)
    m, s = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"


# =====================================================================
# 5. INTERFACE STREAMLIT
# =====================================================================

def main():
    # Header
    st.title("📊 SimCompanies Market Scanner")
    st.markdown("*Analysez les opportunités de profit en temps réel*")
    
    # Sidebar - Configuration
    st.sidebar.header("⚙️ Configuration")
    
    bonus_ui = st.sidebar.slider(
        "Bonus UI (vitesse de vente)",
        min_value=1.0,
        max_value=2.0,
        value=1.02,
        step=0.01
    )
    
    quantite_lot = st.sidebar.number_input(
        "Quantité par lot",
        min_value=1,
        value=1
    )
    
    # Charger les données
    data = load_database()
    
    if not data.get("phase_1"):
        st.error("❌ La base de données ne contient pas de données 'phase_1'.")
        return
    
    # Onglets
    tab1, tab2, tab3 = st.tabs(["🚀 Scanner", "📈 Détails", "ℹ️ À Propos"])
    
    with tab1:
        st.header("Lancement du Scan Complet")
        
        if st.button("🔍 LANCER LE SCAN", key="launch_scan", type="primary"):
            with st.spinner("📥 Téléchargement des données de marché..."):
                saturations_globales = get_all_saturations()
            
            if not saturations_globales:
                st.warning("⚠️ Impossible de récupérer les saturations. Utilisation des valeurs par défaut.")
                saturations_globales = {k: 0.5 for k in range(1, 200)}
            
            progress_bar = st.progress(0)
            results_placeholder = st.empty()
            
            top_opportunites_batiments = {}
            total_items = sum(len(config["ids"]) for config in CONFIG_BATIMENTS.values())
            current_item = 0
            
            # Boucle principale
            for nom_batiment, config in CONFIG_BATIMENTS.items():
                meilleure_opp_batiment = None
                profit_max_batiment = -float('inf')
                
                with st.spinner(f"🏬 Analyse {nom_batiment}..."):
                    for obj_id in config["ids"]:
                        current_item += 1
                        progress_bar.progress(current_item / total_items)
                        
                        if str(obj_id) not in data["phase_1"]:
                            continue
                        
                        stats = data["phase_1"][str(obj_id)]
                        sat_reelle = saturations_globales.get(str(obj_id), 0.5)
                        
                        meilleures_offres = get_best_offers_by_quality(obj_id)
                        time.sleep(0.5)  # Rate limiting
                        
                        if not meilleures_offres:
                            continue
                        
                        for qualite, info in meilleures_offres.items():
                            prix_achat = info['price']
                            
                            prix_vente_opt, profit_h, stats_opt = trouver_profit_maximum(
                                str(obj_id), stats, qualite, sat_reelle, bonus_ui, 
                                prix_achat, quantite_lot, config['salaire_bat'], config['niv_bat']
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
                
                if meilleure_opp_batiment:
                    top_opportunites_batiments[nom_batiment] = meilleure_opp_batiment
            
            # Affichage des résultats
            st.success("✅ Scan terminé!")
            
            if not top_opportunites_batiments:
                st.info("Aucune opportunité rentable trouvée.")
            else:
                # Cards de résultats
                for nom_bat, res in top_opportunites_batiments.items():
                    with st.container():
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            st.metric("Bâtiment", nom_bat)
                        with col2:
                            st.metric("Produit ID", f"Q{res['q']}")
                        with col3:
                            st.metric("Achat", f"${res['achat']:.0f}")
                        with col4:
                            st.metric("Vente", f"${res['vente']:.0f}")
                        
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.metric("Profit/h", f"${res['profit']:.2f}", delta=f"+{(res['profit'])*100/100:.0f}%")
                        with col2:
                            st.metric("Temps", format_temps(res['temps']))
                        with col3:
                            st.metric("Profit Total", f"${res['profit'] * 10:.2f}")
                        
                        st.divider()
                
                # Tableau récapitulatif
                df_results = pd.DataFrame([
                    {
                        "Bâtiment": nom_bat,
                        "Produit ID": res['id'],
                        "Qualité": res['q'],
                        "Achat ($)": res['achat'],
                        "Vente ($)": f"{res['vente']:.0f}",
                        "Profit/h ($)": f"{res['profit']:.2f}",
                        "Temps": format_temps(res['temps'])
                    }
                    for nom_bat, res in top_opportunites_batiments.items()
                ])
                
                st.dataframe(df_results, use_container_width=True)
    
    with tab2:
        st.header("📊 Données Détaillées")
        
        batiment_selected = st.selectbox("Sélectionnez un bâtiment", list(CONFIG_BATIMENTS.keys()))
        
        st.write(f"**Configuration:** Niveau {CONFIG_BATIMENTS[batiment_selected]['niv_bat']} | "
                f"Salaire: ${CONFIG_BATIMENTS[batiment_selected]['salaire_bat']}/h")
        
        ids_selected = st.multiselect(
            "IDs de produits à analyser",
            CONFIG_BATIMENTS[batiment_selected]["ids"],
            default=CONFIG_BATIMENTS[batiment_selected]["ids"][:3]
        )
        
        if st.button("Analyser"):
            saturations_globales = get_all_saturations()
            
            results = []
            for obj_id in ids_selected:
                if str(obj_id) not in data["phase_1"]:
                    continue
                
                stats = data["phase_1"][str(obj_id)]
                sat = saturations_globales.get(str(obj_id), 0.5)
                offres = get_best_offers_by_quality(obj_id)
                time.sleep(0.3)
                
                for qualite, info in offres.items():
                    prix_vente_opt, profit_h, _ = trouver_profit_maximum(
                        str(obj_id), stats, qualite, sat, bonus_ui,
                        info['price'], quantite_lot, 
                        CONFIG_BATIMENTS[batiment_selected]['salaire_bat'],
                        CONFIG_BATIMENTS[batiment_selected]['niv_bat']
                    )
                    
                    results.append({
                        "ID": obj_id,
                        "Qualité": qualite,
                        "Saturation": f"{sat:.1%}",
                        "Achat": f"${info['price']:.0f}",
                        "Vente Optimal": f"${prix_vente_opt:.0f}",
                        "Profit/h": f"${profit_h:.2f}"
                    })
            
            if results:
                st.dataframe(pd.DataFrame(results), use_container_width=True)
    
    with tab3:
        st.header("ℹ️ À Propos")
        st.markdown("""
        ### SimCompanies Market Scanner
        
        Cet outil analyse les opportunités de profit sur le marché SimCompanies.
        
        **Fonctionnalités:**
        - 🔍 Scan automatique multi-bâtiments
        - 📈 Calcul du profit maximal par produit
        - 💾 Cache des données (optimisation API)
        - 📊 Tableau de bord interactif
        
        **Données mises en cache:**
        - Saturations du marché: 5 minutes
        - Base de données: 1 heure
        - Offres de marché: 5 minutes
        
        **Créé avec:**
        - Streamlit
        - Python 3.8+
        - API SimCompanies
        """)


if __name__ == "__main__":
    main()
