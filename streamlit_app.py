import streamlit as st
import json, os
import time
import requests
from scipy.optimize import minimize_scalar
import pandas as pd
from datetime import datetime
import altair as alt
from pathlib import Path

# =====================================================================
# CONFIGURATION STREAMLIT
# =====================================================================
st.set_page_config(
    page_title="SimCompanies Market Scanner",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

def inject_custom_css():
    st.markdown("""
        <style>
        .metric-card { 
            background: #262730;
            padding: 20px;
            border-radius: 10px;
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
        "niv_bat": 1,
        "salaire_bat": 152,
        "ids": ["3", "4", "5", "7", "8", "9", "119", "122", "123", "124", "125", "126", "127", "140", "152"]
    },
    "Gas Station": {
        "niv_bat": 1,
        "salaire_bat": 380,
        "ids": ["11", "12"]
    },
    "Electronics Store": {
        "niv_bat": 1,
        "salaire_bat": 190,
        "ids": ["24", "25", "26", "27", "28", "98"]
    },
    "Car Dealership": {
        "niv_bat": 1,
        "salaire_bat": 417,
        "ids": ["53", "54", "55", "56", "57"]
    },
    "Fashion Store": {
        "niv_bat": 1,
        "salaire_bat": 342,
        "ids": ["60", "61", "62", "63", "64", "65", "70", "71"]
    },
    "Hardware Store": {
        "niv_bat": 1,
        "salaire_bat": 190,
        "ids": ["102", "103", "108", "109", "110"]
    }
}

SATURATION_HISTORY_FILE = "saturation_history.json"
SATURATION_API_URL = "https://www.simcompanies.com/api/v4/0/resources-retail-info/"

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
    return (multiplicateur_bonus * ((prix - cout_prod) * 3600) - salaire) / denominateur

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
    
    if temps_sec <= 0:
        return -1
    return (temps_sec * quantite) / niveau_bat


@st.cache_data(ttl=300, show_spinner=False)
def trouver_profit_maximum(id_obj, stats, qualite, saturation, bonus_ui, prix_achat, quantite, salaire_horaire_batiment, niv_batiment):
    # 1. Calcul de la limite mathématique absolue (Asymptote du temps de vente infini)
    Uor = 370
    facteur_sat = min(max(2 - saturation, 0), 2)
    volume_min = max(0.9, facteur_sat / 2 + 0.5)
    L = stats["buildingLevelsNeededPerUnitPerHour"]
    Um = stats["modeledUnitsSoldAnHour"]
    k_val = 2.28 if str(id_obj) == "B" else 1
    resistivite = Uor * (L * Um + 1) * k_val * (facteur_sat / 2 * (1 + (qualite / 12) * 0.3))
    capacite_vente = Um * volume_min
    salaire = stats.get("modeledStoreWages", 0)
    cout_prod = stats["modeledProductionCostPerUnit"]
    
    prix_ref = cout_prod + (resistivite + salaire) / capacite_vente
    prix_max_theorique = 2 * prix_ref - cout_prod
    
    if prix_achat >= prix_max_theorique - 0.02:
        return float(prix_achat), 0.0, {"temps_vente": 0.0, "profit_net_total": 0.0}

    def objective(prix_test):
        temps_sec = calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix_test, quantite, niv_batiment)
        
        if temps_sec <= 0: return 1e9 
        
        temps_heures = temps_sec / 3600
        marge_totale = (prix_test - prix_achat) * quantite
        profit_horaire = (marge_totale / temps_heures) - salaire_horaire_batiment
        
        return -profit_horaire

    try:
        res = minimize_scalar(
            objective, 
            bounds=(prix_achat + 0.01, prix_max_theorique - 0.01), 
            method='bounded'
        )
        # CRITIQUE : Conversion forcée en float natif Python. SciPy renvoie des numpy.float64
        # qui provoquent un crash silencieux (Erreur 500) dans le cache de Streamlit !
        prix_optimal = float(res.x)
        profit_max = float(-res.fun)
    except Exception:
        return float(prix_achat), 0.0, {"temps_vente": 0.0, "profit_net_total": 0.0}
    
    temps_sec = calculer_temps_final(id_obj, stats, qualite, saturation, bonus_ui, prix_optimal, quantite, niv_batiment)
    if temps_sec <= 0:
        return float(prix_achat), 0.0, {"temps_vente": 0.0, "profit_net_total": 0.0}
        
    profit_net = ((prix_optimal - prix_achat) * quantite) - (salaire_horaire_batiment * (temps_sec/3600))
    
    return prix_optimal, profit_max, {
        "temps_vente": float(temps_sec),
        "profit_net_total": float(profit_net)
    }

@st.cache_data(ttl=300)
def fetch_saturation_data():
    try:
        response = requests.get(
            SATURATION_API_URL,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def get_all_saturations(api_data=None):
    api_data = api_data if api_data is not None else fetch_saturation_data()
    saturations = {}
    for item in api_data:
        item_id = str(item.get("dbLetter", ""))
        if item_id:
            saturations[item_id] = float(item.get("saturation", 0.5))
    return saturations


def get_saturation_history_for_item(item_id, api_data):
    for item in api_data:
        if str(item.get("dbLetter", "")) == str(item_id):
            history = []
            for row in item.get("retailData", []):
                if row.get("date") is None:
                    continue
                history.append({
                    "date": row["date"],
                    "saturation": float(row.get("saturation", 0.0))
                })
            return sorted(history, key=lambda r: r["date"])
    return []


def get_api_saturation_trends(api_data, top_n=20, eligible_ids=None):
    deltas = {}
    for item in api_data:
        item_id = str(item.get("dbLetter", ""))
        if not item_id or item_id in deltas:
            continue
        if eligible_ids is not None and item_id not in eligible_ids:
            continue
        history = item.get("retailData", [])
        if len(history) < 2:
            continue
        latest = history[-1].get("saturation")
        previous = history[-2].get("saturation")
        if latest is None or previous is None:
            continue
        try:
            deltas[item_id] = float(latest) - float(previous)
        except Exception:
            continue

    sorted_items = sorted(deltas.items(), key=lambda x: x[1], reverse=True)
    rising = sorted_items[:top_n]
    falling = sorted_items[-top_n:][::-1]
    return rising, falling


# =====================================================================
# 3. INTERFACES API (AVEC CACHE)
# =====================================================================

@st.cache_data(ttl=3600)
def load_database():
    """Charge la base de données locale."""
    db_path = Path(__file__).resolve().parent / 'database.json'
    try:
        with open(db_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"phase_1": {}}


def load_saturation_history():
    path = Path(__file__).resolve().parent / SATURATION_HISTORY_FILE
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_saturation_snapshot(saturations):
    history = load_saturation_history()
    path = Path(__file__).resolve().parent / SATURATION_HISTORY_FILE
    date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    if history and history[-1]["date"] == date[:10]:
        history[-1]["saturations"] = saturations
    else:
        history.append({"date": date, "saturations": saturations})
        history = history[-15:]
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2)
    except:
        pass
    return history


def get_saturation_time_series(item_id, history):
    series = []
    for entry in history:
        value = entry["saturations"].get(str(item_id))
        if value is not None:
            series.append({"date": entry["date"], "saturation": value})
    return series


def render_saturation_chart(series):
    if not series:
        return False
    df = pd.DataFrame(series)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date'])
    if df.empty:
        return False
    df = df.sort_values('date')
    st.line_chart(df.set_index('date')['saturation'], use_container_width=True)
    return True


def get_saturation_trends(history, top_n=20, eligible_ids=None):
    if len(history) < 2:
        return [], []
    latest = history[-1]["saturations"]
    previous = history[-2]["saturations"]
    deltas = []
    for item_id, value in latest.items():
        if eligible_ids is not None and str(item_id) not in eligible_ids:
            continue
        prev_value = previous.get(item_id)
        if prev_value is None:
            continue
        deltas.append((item_id, value - prev_value))
    deltas.sort(key=lambda x: x[1], reverse=True)
    rising = deltas[:top_n]
    falling = deltas[-top_n:][::-1]
    return rising, falling


@st.cache_data(ttl=300)
def get_best_offers_by_quality(id_obj):
    """Récupère les offres du marché avec un cache global pour éviter les doublons."""
    url = f"https://www.simcompanies.com/api/v3/market/0/{id_obj}/"
    for attempt in range(4):
        try:
            # Réduction du timeout pour éviter que le reverse-proxy du Cloud ne lance une erreur 500
            response = requests.get(url, timeout=5)
            if response.status_code == 429:
                time.sleep(1) 
                continue
            if response.status_code != 200:
                time.sleep(0.5)
                continue
            data = response.json()
            orders = data.get("sellOrders", []) if isinstance(data, dict) else data
            
            best_prices = {}
            for order in orders:
                q = order.get("quality", 0)
                p = order.get("price", 0)
                qty = order.get("quantity", 0)
                if p > 0:
                    if q not in best_prices or p < best_prices[q]["price"]:
                        best_prices[q] = {"price": p, "quantity": qty}
                    elif p == best_prices[q]["price"]:
                        best_prices[q]["quantity"] += qty
            return best_prices
        except Exception:
            time.sleep(0.1)
    return {}


def get_item_name(obj_id, data):
    return data.get("phase_1", {}).get(str(obj_id), {}).get("name", f"Item {obj_id}")


def compute_director_financier_plan(budget_total, heures_cibles, batiments_selectionnes, data, bonus_ui):
    saturations = get_all_saturations()
    candidates = []

    for nom_batiment in batiments_selectionnes:
        config = st.session_state.custom_config[nom_batiment]
        for obj_id in CONFIG_BATIMENTS[nom_batiment]["ids"]:
            if str(obj_id) not in data["phase_1"]:
                continue
            stats = data["phase_1"][str(obj_id)]
            sat_reelle = saturations.get(str(obj_id), 0.5)
            offres = get_best_offers_by_quality(obj_id)
            for qualite, prix_info in offres.items():
                try:
                    q_int = int(qualite)
                except Exception:
                    continue
                # Ne traiter que la qualité 0 comme demandé
                if q_int != 0:
                    continue
                prix_achat = prix_info['price'] if isinstance(prix_info, dict) else prix_info
                prix_vente_opt, profit_h, stats_opt = trouver_profit_maximum(
                    str(obj_id), stats, qualite, sat_reelle, bonus_ui,
                    prix_achat, 1, config['salaire_bat'], config['niv_bat']
                )
                if profit_h <= 0 or stats_opt['temps_vente'] <= 0:
                    continue
                unites_totales = max(1, (3600 / stats_opt['temps_vente']) * heures_cibles)
                cost = unites_totales * prix_achat
                profit_total = profit_h * heures_cibles
                roce = profit_total / cost if cost > 0 else 0
                candidates.append({
                    "batiment": nom_batiment,
                    "id": obj_id,
                    "nom_produit": get_item_name(obj_id, data),
                    "qualite": qualite,
                    "prix_achat": prix_achat,
                    "prix_vente_opt": prix_vente_opt,
                    "profit_total": profit_total,
                    "cost": cost,
                    "roce": roce,
                    "quantite": unites_totales,
                    "saturation": sat_reelle
                })

    candidates.sort(key=lambda x: (x['roce'], x['profit_total']), reverse=True)
    plan = []
    remaining = budget_total
    used_batiments = set()

    for opt in candidates:
        if opt['batiment'] in used_batiments:
            continue
        if remaining <= 0:
            break
        if opt['cost'] <= remaining:
            opt['ratio'] = 1.0
            opt['used_cost'] = opt['cost']
            opt['used_profit'] = opt['profit_total']
            plan.append(opt)
            remaining -= opt['cost']
            used_batiments.add(opt['batiment'])
        else:
            ratio = remaining / opt['cost']
            if ratio >= 0.1:
                opt_copy = opt.copy()
                opt_copy['ratio'] = ratio
                opt_copy['used_cost'] = remaining
                opt_copy['used_profit'] = opt['profit_total'] * ratio
                opt_copy['used_quantite'] = opt['quantite'] * ratio
                plan.append(opt_copy)
                remaining = 0
                used_batiments.add(opt_copy['batiment'])
            break

    return plan, remaining


def build_contract_negotiation_table(data, batiment, ids_selected, bonus_ui):
    rows = []
    target_margins = [10, 20, 30, 50]
    saturations = get_all_saturations()

    for obj_id in ids_selected:
        if str(obj_id) not in data["phase_1"]:
            continue
        stats = data["phase_1"][str(obj_id)]
        sat = saturations.get(str(obj_id), 0.5)
        offres = get_best_offers_by_quality(obj_id)
        for qualite, prix_info in offres.items():
            try:
                q_int = int(qualite)
            except Exception:
                continue
            if q_int != 0:
                continue
            prix_achat = prix_info['price'] if isinstance(prix_info, dict) else prix_info
            prix_vente_opt, profit_h, _ = trouver_profit_maximum(
                str(obj_id), stats, qualite, sat, bonus_ui, prix_achat, 1,
                st.session_state.custom_config[batiment]['salaire_bat'],
                st.session_state.custom_config[batiment]['niv_bat']
            )
            if prix_vente_opt <= 0:
                continue
            row = {
                "Bâtiment": batiment,
                "Produit": get_item_name(obj_id, data),
                "Qualité": f"Q{qualite}",
                "Prix marché": prix_achat,
                "Prix vente optimisé": prix_vente_opt,
                "Marge actuelle (%)": (prix_vente_opt - prix_achat) / prix_achat * 100 if prix_achat > 0 else 0
            }
            for pct in target_margins:
                row[f"Prix max {pct}%"] = prix_vente_opt / (1 + pct / 100)
            rows.append(row)

    return pd.DataFrame(rows)


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
    inject_custom_css()
    st.title("📊 SimCompanies Market Scanner")

    # App-level configuration
    bonus_ui = 1.02
    quantite_lot = 1

    # Initialiser les paramètres modifiables en session state si nécessaire
    if "custom_config" not in st.session_state:
        st.session_state.custom_config = {name: config.copy() for name, config in CONFIG_BATIMENTS.items()}
    if "market_cache" not in st.session_state:
        st.session_state.market_cache = {}

    # Prépare la liste des bâtiments disponibles et sélection actuelle (sera modifiée dans l'onglet Scan)
    batiments_disponibles = list(CONFIG_BATIMENTS.keys())
    batiments_selectionnes = st.session_state.get("selected_buildings", batiments_disponibles)

    if not batiments_selectionnes:
        st.warning("⚠️ Sélectionnez au moins un bâtiment à scanner")
        return

    # Charger les données
    data = load_database()

    if not data or "phase_1" not in data or not data["phase_1"]:
        st.error("❌ La base de données est vide ou introuvable (database.json).")
        return

    # Onglets
    saturation_api_data = fetch_saturation_data()
    history = load_saturation_history()
    tab_scan, tab_sat, tab_contrats, tab_about = st.tabs([
        "🚀 Scanner",
        "📉 Saturation",
        "🤝 Contrats",
        "ℹ️ À Propos"
    ])

    with tab_scan:
        st.header("Analyse du Bâtiment")

        # Sélection du bâtiment unique pour l'analyse
        nom_batiment = st.selectbox("🏬 Choisir un bâtiment", batiments_disponibles)
        config_actuelle = st.session_state.custom_config[nom_batiment]

        # Paramètres dynamiques
        col1, col2, col3 = st.columns(3)
        with col1:
            niv = st.number_input("Niveau du bâtiment", min_value=1, value=config_actuelle["niv_bat"])
        with col2:
            sal = st.number_input("Salaire horaire ($)", min_value=0, value=config_actuelle["salaire_bat"])
        with col3:
            bonus_ui = st.number_input("Bonus UI (Vitesse)", min_value=1.0, max_value=2.0, value=bonus_ui, step=0.01)

        st.session_state.custom_config[nom_batiment]["niv_bat"] = niv
        st.session_state.custom_config[nom_batiment]["salaire_bat"] = sal

        col_btn, _ = st.columns([1, 3])
        with col_btn:
            if st.button("🔄 Actualiser les prix du marché (Vider Cache)"):
                st.cache_data.clear()
                st.rerun()

        with st.spinner("📥 Chargement et analyse des données..."):
            saturations_globales = get_all_saturations()
            save_saturation_snapshot(saturations_globales)
            
            ids_to_scan = CONFIG_BATIMENTS[nom_batiment]["ids"]
            opportunites = []

            # Pré-chargement / Calcul
            progress_bar = st.progress(0)
            for i, obj_id in enumerate(ids_to_scan):
                progress_bar.progress((i + 1) / len(ids_to_scan))
                
                if str(obj_id) not in data["phase_1"]:
                    continue

                stats = data["phase_1"][str(obj_id)]
                sat_reelle = saturations_globales.get(str(obj_id), 0.5)
                meilleures_offres = get_best_offers_by_quality(obj_id)

                for qualite, prix_info in meilleures_offres.items():
                    prix_achat = prix_info['price']
                    stock = prix_info.get('quantity', 0)
                    
                    prix_vente_opt, profit_h, stats_opt = trouver_profit_maximum(
                        str(obj_id), stats, qualite, sat_reelle, bonus_ui, 
                        prix_achat, quantite_lot, sal, niv
                    )

                    if profit_h > 0:
                        opportunites.append({
                            "Produit": get_item_name(obj_id, data),
                            "Qualité": f"Q{qualite}",
                            "Achat ($)": prix_achat,
                            "Vente ($)": prix_vente_opt,
                            "Profit/h ($)": profit_h,
                            "Profit/Jour ($)": profit_h * 24,
                            "Temps": stats_opt['temps_vente'],
                            "Stock dispo": stock
                        })
            
            progress_bar.empty()

        # Trier et prendre les 10 meilleurs
        if not opportunites:
            st.info("Aucune opportunité rentable trouvée avec ces paramètres.")
        else:
            opportunites.sort(key=lambda x: x["Profit/h ($)"], reverse=True)
            top_10 = opportunites[:10]
            
            st.subheader(f"🏆 Top 10 Opportunités - {nom_batiment}")
            
            df_results = pd.DataFrame(top_10)
            df_results["Achat ($)"] = df_results["Achat ($)"].map("{:.2f}".format)
            df_results["Vente ($)"] = df_results["Vente ($)"].map("{:.2f}".format)
            df_results["Profit/h ($)"] = df_results["Profit/h ($)"].map("{:.2f}".format)
            df_results["Profit/Jour ($)"] = df_results["Profit/Jour ($)"].map("{:.2f}".format)
            df_results["Temps"] = df_results["Temps"].apply(format_temps)
            
            st.dataframe(df_results, use_container_width=True)

    with tab_sat:
        st.header("📉 Suivi de la saturation")

        exclusion_defaults = [
            "WITCH_COSTUME",
            "TREE",
            "XMAS_CRACKERS",
            "RAMADAN_SWEETS",
            "XMAS_ORNAMENT",
            "EASTER_BUNNY"
        ]
        if "saturation_exclusions" not in st.session_state:
            st.session_state.saturation_exclusions = exclusion_defaults.copy()

        with st.expander("Filtres du classement de saturation"):
            all_names = sorted({
                get_item_name(item.get('dbLetter'), data)
                for item in saturation_api_data
                if item.get('dbLetter') is not None
            }) if saturation_api_data else []
            excluded_names = st.multiselect(
                "Items à exclure du classement",
                all_names,
                default=st.session_state.saturation_exclusions,
                key="saturation_exclusions"
            )
            if st.button("Recharger le classement", key="reload_saturation"):
                st.experimental_rerun()

        if saturation_api_data:
            st.write(f"Historique de saturation disponible depuis l'API : {len(saturation_api_data)} items analysés.")
            # Build name->id mapping and present names only
            name_to_id = {}
            choices = []
            for item in saturation_api_data:
                dbid = item.get('dbLetter')
                if dbid is None:
                    continue
                name = get_item_name(dbid, data)
                if name not in name_to_id:
                    name_to_id[name] = str(dbid)
                    choices.append(name)
            choices = sorted(choices)
            if not choices:
                st.info("Aucun item avec nom disponible dans l'API de saturation.")
                return
            item_name_selected = st.selectbox("Sélectionnez un item pour la courbe", choices, index=0)
            item_selected = name_to_id[item_name_selected]

            serie = get_saturation_history_for_item(item_selected, saturation_api_data)
            if serie and render_saturation_chart(serie):
                pass
            else:
                st.info("Aucune donnée historique pour cet item ou le graphique ne peut pas être tracé.")

            eligible_ids = {
                str(obj_id)
                for batiment in st.session_state.get('selected_buildings', batiments_disponibles)
                for obj_id in CONFIG_BATIMENTS.get(batiment, {}).get('ids', [])
            }
            rising, falling = get_api_saturation_trends(saturation_api_data, top_n=20, eligible_ids=eligible_ids)
            if excluded_names:
                rising = [(item_id, delta) for item_id, delta in rising if get_item_name(item_id, data) not in excluded_names]
                falling = [(item_id, delta) for item_id, delta in falling if get_item_name(item_id, data) not in excluded_names]
            if rising:
                # map ids to names for readability
                df_rising = pd.DataFrame([{'Produit': get_item_name(it, data), 'Variation x10': f"{delta * 10:.2f}"} for it, delta in rising])
                df_falling = pd.DataFrame([{'Produit': get_item_name(it, data), 'Variation x10': f"{delta * 10:.2f}"} for it, delta in falling])
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Top saturation en hausse")
                    st.dataframe(df_rising, use_container_width=True)
                with col2:
                    st.subheader("Top saturation en baisse")
                    st.dataframe(df_falling, use_container_width=True)
        elif history:
            st.warning("L'API historique n'est pas disponible, affichage des snapshots locaux.")
            st.write(f"Snapshots locaux : {len(history)} snapshots (max 15). Dernière mise à jour : {history[-1]['date']}.")
            # build choices by name
            name_to_id = {}
            choices = []
            for snap in history:
                for k in snap['saturations'].keys():
                    name = get_item_name(k, data)
                    if name not in name_to_id:
                        name_to_id[name] = str(k)
                        choices.append(name)
            choices = sorted(choices)
            if not choices:
                st.info("Aucun item disponible dans les snapshots locaux.")
                return
            item_name_selected = st.selectbox("Sélectionnez un item pour la courbe", choices, index=0)
            item_selected = name_to_id[item_name_selected]

            serie = get_saturation_time_series(item_selected, history)
            if serie and render_saturation_chart(serie):
                pass
            else:
                st.info("Aucune donnée historique pour cet item ou le graphique ne peut pas être tracé.")

            eligible_ids = {
                str(obj_id)
                for batiment in st.session_state.get('selected_buildings', batiments_disponibles)
                for obj_id in CONFIG_BATIMENTS.get(batiment, {}).get('ids', [])
            }
            rising, falling = get_saturation_trends(history, top_n=20, eligible_ids=eligible_ids)
            if excluded_names:
                rising = [(item_id, delta) for item_id, delta in rising if get_item_name(item_id, data) not in excluded_names]
                falling = [(item_id, delta) for item_id, delta in falling if get_item_name(item_id, data) not in excluded_names]
            if rising:
                df_rising = pd.DataFrame([{'Produit': get_item_name(item, data), 'Variation x10': f"{delta * 10:.2f}"} for item, delta in rising])
                df_falling = pd.DataFrame([{'Produit': get_item_name(item, data), 'Variation x10': f"{delta * 10:.2f}"} for item, delta in falling])
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Top saturation en hausse")
                    st.dataframe(df_rising, use_container_width=True)
                with col2:
                    st.subheader("Top saturation en baisse")
                    st.dataframe(df_falling, use_container_width=True)
        else:
            st.warning("Aucune donnée de saturation disponible. Lancez un scan ou vérifiez la connexion API.")

    with tab_contrats:
        st.header("🤝 Négociation de contrats")
        batiment_contract = st.selectbox("Bâtiment pour négocier", batiments_disponibles, key="contract_building")

        # Build item name list for selection
        item_ids = CONFIG_BATIMENTS[batiment_contract]["ids"]
        id_to_name = {str(i): get_item_name(i, data) for i in item_ids}
        choices = [id_to_name[str(i)] for i in item_ids]
        item_name = st.selectbox("Produit (un à la fois)", choices, key="contract_item")
        item_id = None
        # find id for chosen name (first match)
        for k, v in id_to_name.items():
            if v == item_name:
                item_id = k
                break

        st.markdown(f"**Produit choisi :** {item_name}")

        if st.button("Analyser les réductions (1%→5%)", key="contract_analyse"):
            with st.spinner("Calcul des profits pour différentes réductions..."):
                # Gather market offers for the selected item
                offres_item = get_best_offers_by_quality(item_id)
                # Determine best competitor profit in the same building
                best_competitor_profit = -float('inf')
                best_competitor_name = None
                for other_id in item_ids:
                    if other_id == item_id:
                        continue
                    offres_other = get_best_offers_by_quality(other_id)
                    for q, info in offres_other.items():
                        prix_market = info['price'] if isinstance(info, dict) else info
                        try:
                            prix_vente_opt, profit_h, _ = trouver_profit_maximum(
                                str(other_id), data['phase_1'][str(other_id)], q,
                                get_all_saturations().get(str(other_id), 0.5), bonus_ui,
                                prix_market, 1,
                                st.session_state.custom_config[batiment_contract]['salaire_bat'],
                                st.session_state.custom_config[batiment_contract]['niv_bat']
                            )
                        except Exception:
                            continue
                        if profit_h > best_competitor_profit:
                            best_competitor_profit = profit_h
                            best_competitor_name = get_item_name(other_id, data)

                if best_competitor_name:
                    st.markdown(f"**Meilleur profit concurrent dans {batiment_contract} :** {best_competitor_name} — ${best_competitor_profit:.2f}/h")
                else:
                    st.info("Aucun concurrent trouvé pour le bâtiment sélectionné.")

                # Build results table for the selected item across qualities and reductions
                rows = []
                reductions = [1,2,3,4,5]
                for q, info in offres_item.items():
                    prix_market = info['price'] if isinstance(info, dict) else info
                    
                    # Calcul pour le prix du marché normal (0% réduction)
                    try:
                        prix_vente_opt_base, profit_h_base, _ = trouver_profit_maximum(
                            str(item_id), data['phase_1'][str(item_id)], q,
                            get_all_saturations().get(str(item_id), 0.5), bonus_ui,
                            prix_market, 1,
                            st.session_state.custom_config[batiment_contract]['salaire_bat'],
                            st.session_state.custom_config[batiment_contract]['niv_bat']
                        )
                        marge_base = ((prix_vente_opt_base - prix_market) / prix_market * 100) if prix_market > 0 else 0
                    except Exception:
                        profit_h_base = 0
                        marge_base = 0

                    row = {
                        'Qualité': f"Q{q}",
                        'Prix marché ($)': f"{prix_market:.2f}",
                        'Profit/h marché ($)': f"{profit_h_base:.2f}",
                        'Marge marché (%)': f"{marge_base:.1f}%",
                        'Meilleur profit concurrent ($/h)': f"{best_competitor_profit:.2f}" if best_competitor_profit > -1e8 else 'N/A'
                    }
                    for pct in reductions:
                        reduced_price = prix_market * (1 - pct/100.0)
                        try:
                            prix_vente_opt, profit_h_red, _ = trouver_profit_maximum(
                                str(item_id), data['phase_1'][str(item_id)], q,
                                get_all_saturations().get(str(item_id), 0.5), bonus_ui,
                                reduced_price, 1,
                                st.session_state.custom_config[batiment_contract]['salaire_bat'],
                                st.session_state.custom_config[batiment_contract]['niv_bat']
                            )
                            margin_pct = ((prix_vente_opt - reduced_price) / reduced_price) * 100 if reduced_price > 0 else 0
                        except Exception:
                            profit_h_red = None
                            margin_pct = None
                        if best_competitor_profit == -float('inf') or best_competitor_profit == 0 or profit_h_red is None:
                            profit_vs_best = None
                        else:
                            profit_vs_best = (profit_h_red - best_competitor_profit) / abs(best_competitor_profit) * 100
                        row[f"Prix @ -{pct}%"] = f"{reduced_price:.2f}"
                        row[f"Profit/h @ -{pct}%"] = f"{profit_h_red:.2f}" if profit_h_red is not None else 'N/A'
                        row[f"Marge @ -{pct}%"] = f"{margin_pct:.1f}%" if margin_pct is not None else 'N/A'
                        row[f"Vs concurrent @ -{pct}%"] = f"{profit_vs_best:.2f}%" if profit_vs_best is not None else 'N/A'
                    rows.append(row)

                if rows:
                    df = pd.DataFrame(rows)
                    # Prepare HTML with colored percent cells for better compatibility
                    highlight_cols = [col for col in df.columns if col.startswith('Vs concurrent @')]
                    df_html = df.copy()
                    for col in highlight_cols:
                        def fmt(val):
                            if val is None or (isinstance(val, float) and pd.isna(val)):
                                return 'N/A'
                            # Handle strings like '12.34%'
                            if isinstance(val, str):
                                s = val.strip()
                                if s == '' or s.upper() == 'N/A':
                                    return 'N/A'
                                if s.endswith('%'):
                                    s_num = s[:-1].replace(',', '.')
                                    try:
                                        v = float(s_num)
                                    except Exception:
                                        return s
                                else:
                                    try:
                                        v = float(s.replace(',', '.'))
                                    except Exception:
                                        return s
                            else:
                                try:
                                    v = float(val)
                                except Exception:
                                    return str(val)

                            color = 'green' if v > 0 else 'red' if v < 0 else 'black'
                            return f'<span style="color:{color};font-weight:600">{v:.2f}%</span>'

                        df_html[col] = df[col].apply(fmt)

                        html = df_html.to_html(index=False, escape=False)
                        st.markdown(html, unsafe_allow_html=True)
                else:
                    st.warning("Aucune offre de marché disponible pour ce produit.")

    with tab_about:
        st.header("ℹ️ À Propos")
        st.markdown("""
        ### SimCompanies Market Scanner
        
        Cet outil analyse les opportunités de profit sur le marché SimCompanies.
        
        **Fonctionnalités:**
        - 🔍 Scan automatique multi-bâtiments
        - 📈 Analyse détaillée par item
        - 📉 Suivi historique de saturation
        - 💼 Directeur financier pour allocation de budget
        - 🤝 Tableau de négociation de contrats
        - 💾 Cache des données pour limiter les appels API
        
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
