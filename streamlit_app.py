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
        "niv_bat": 5,
        "salaire_bat": 767,
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
        "niv_bat": 4,
        "salaire_bat": 1723,
        "ids": ["53", "54", "55", "56", "57"]
    },
    "Fashion Store": {
        "niv_bat": 3,
        "salaire_bat": 1036,
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

class APIRateLimitError(Exception): pass

@st.cache_data(ttl=300)
def _get_best_offers_cached(id_obj):
    """Récupère les offres du marché. Pour une qualité Q, retourne le prix minimum parmi toutes les offres de qualité >= Q."""
    url = f"https://www.simcompanies.com/api/v3/market/0/{id_obj}/"
    for attempt in range(5):
        try:
            # Réduction du timeout pour éviter que le reverse-proxy du Cloud ne lance une erreur 500
            response = requests.get(url, timeout=5)
            if response.status_code == 429:
                time.sleep((2 ** attempt) + 1.5) 
                continue
            if response.status_code != 200:
                time.sleep(1)
                continue
            
            # Délai de courtoisie après un succès pour ne pas saturer l'API
            time.sleep(0.2)
            
            data = response.json()
            orders = data.get("sellOrders", []) if isinstance(data, dict) else data
            
            raw_best_prices = {}
            for order in orders:
                q = order.get("quality", 0)
                p = order.get("price", 0)
                qty = order.get("quantity", 0)
                if p > 0:
                    if q not in raw_best_prices or p < raw_best_prices[q]["price"]:
                        raw_best_prices[q] = {"price": p, "quantity": qty, "real_q": q}
                    elif p == raw_best_prices[q]["price"]:
                        raw_best_prices[q]["quantity"] += qty
                        
            best_prices = {}
            if raw_best_prices:
                max_q = max(raw_best_prices.keys())
                current_best_p = float('inf')
                current_best_info = None
                for q in range(max_q, -1, -1):
                    if q in raw_best_prices:
                        if raw_best_prices[q]["price"] < current_best_p:
                            current_best_p = raw_best_prices[q]["price"]
                            current_best_info = raw_best_prices[q]
                    if current_best_info is not None:
                        best_prices[q] = {
                            "price": current_best_info["price"],
                            "quantity": current_best_info["quantity"],
                            "real_q": current_best_info["real_q"]
                        }
            return best_prices
        except Exception:
            time.sleep(0.5)
    # Déclenche une erreur plutôt que de retourner {} pour éviter que Streamlit ne cache un échec API
    raise APIRateLimitError("API Rate Limit")

def get_best_offers_by_quality(id_obj):
    try:
        return _get_best_offers_cached(id_obj)
    except Exception:
        return None


def get_item_name(obj_id, phase_data):
    return phase_data.get(str(obj_id), {}).get("name", f"Item {obj_id}")


# =====================================================================
# 4. UTILITAIRES
# =====================================================================

def format_temps(s):
    if s <= 0: return "Impossible"
    h, m = divmod(int(s), 3600)
    m, s = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"


# =====================================================================
# 5. GESTION DES PROFILS UTILISATEURS
# =====================================================================
USERS_FILE = Path(__file__).resolve().parent / 'users_config.json'

def load_users():
    default_buildings = {b: {"niv_bat": c["niv_bat"], "salaire_bat": c["salaire_bat"]} for b, c in CONFIG_BATIMENTS.items()}
    default_profile = {"bonus_ui": 1.02, "buildings": default_buildings}
    users_data = {"Ju": json.loads(json.dumps(default_profile)), "Théo": json.loads(json.dumps(default_profile))}
    
    if USERS_FILE.exists():
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
                for user in ["Ju", "Théo"]:
                    if user in saved_data:
                        users_data[user]["bonus_ui"] = saved_data[user].get("bonus_ui", 1.02)
                        for b in CONFIG_BATIMENTS.keys():
                            if "buildings" in saved_data[user] and b in saved_data[user]["buildings"]:
                                users_data[user]["buildings"][b] = saved_data[user]["buildings"][b]
        except: pass
    return users_data

def save_users(data):
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except: pass


# =====================================================================
# 6. INTERFACE STREAMLIT
# =====================================================================

def main():
    inject_custom_css()
    st.title("📊 SimCompanies Market Scanner")

    # App-level configuration
    quantite_lot = 1

    if "market_cache" not in st.session_state:
        st.session_state.market_cache = {}

    users_data = load_users()
    
    st.sidebar.title("👤 Profil Utilisateur")
    current_user = st.sidebar.radio("Connecté en tant que :", ["Ju", "Théo"])
    
    st.sidebar.markdown("---")
    st.sidebar.title("📈 Cycle Économique")
    PHASE_MAP = {"Récession": "phase_0", "Normal": "phase_1", "Boom": "phase_2"}
    phase_name = st.sidebar.selectbox("Phase actuelle", list(PHASE_MAP.keys()), index=1)
    st.session_state.phase_key = PHASE_MAP[phase_name]

    if "current_user" not in st.session_state or st.session_state.current_user != current_user:
        st.session_state.current_user = current_user
        st.session_state.custom_config = users_data[current_user]["buildings"]
        st.session_state.bonus_ui = users_data[current_user]["bonus_ui"]

    # Prépare la liste des bâtiments disponibles et sélection actuelle (sera modifiée dans l'onglet Scan)
    batiments_disponibles = list(CONFIG_BATIMENTS.keys())

    # Charger les données
    data = load_database()
    phase_data = data.get(st.session_state.phase_key)

    if not phase_data:
        st.error(f"❌ Données pour la phase '{phase_name}' introuvables dans database.json.")
        return

    # Onglets
    saturation_api_data = fetch_saturation_data()
    history = load_saturation_history()
    tab_scan, tab_sat, tab_selling, tab_contrats, tab_settings, tab_about = st.tabs([
        "🚀 Scanner",
        "📉 Saturation",
        "🏷️ Prix de Vente",
        "🤝 Contrats",
        "⚙️ Paramètres",
        "ℹ️ À Propos"
    ])

    with tab_scan:
        st.header("Analyse du Bâtiment")

        # Sélection du bâtiment unique pour l'analyse
        nom_batiment = st.selectbox("🏬 Choisir un bâtiment", batiments_disponibles)
        config_actuelle = st.session_state.custom_config[nom_batiment]

        niv = config_actuelle["niv_bat"]
        sal = config_actuelle["salaire_bat"]
        bonus_ui = st.session_state.bonus_ui

        st.info(f"**Configuration active :** Niveau {niv} | Salaire {sal}$/h | Bonus UI {bonus_ui}")

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
                
                if str(obj_id) not in phase_data:
                    continue

                stats = phase_data[str(obj_id)]
                sat_reelle = saturations_globales.get(str(obj_id), 0.5)
                meilleures_offres = get_best_offers_by_quality(obj_id)

                if meilleures_offres is None: continue

                for qualite, prix_info in meilleures_offres.items():
                    if qualite != prix_info.get("real_q", qualite):
                        continue # Ignore les qualités dérivées dans le scanner pour ne pas faire de doublons
                        
                    prix_achat = prix_info['price']
                    stock = prix_info.get('quantity', 0)
                    
                    prix_vente_opt, profit_h, stats_opt = trouver_profit_maximum(
                        str(obj_id), stats, qualite, sat_reelle, bonus_ui, 
                        prix_achat, quantite_lot, sal, niv
                    )

                    if profit_h > 0:
                        opportunites.append({
                            "Produit": get_item_name(obj_id, phase_data),
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
                get_item_name(item.get('dbLetter'), phase_data)
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
                name = get_item_name(dbid, phase_data)
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
                for batiment in batiments_disponibles
                for obj_id in CONFIG_BATIMENTS.get(batiment, {}).get('ids', [])
            }
            rising, falling = get_api_saturation_trends(saturation_api_data, top_n=20, eligible_ids=eligible_ids)
            if excluded_names:
                rising = [(item_id, delta) for item_id, delta in rising if get_item_name(item_id, phase_data) not in excluded_names]
                falling = [(item_id, delta) for item_id, delta in falling if get_item_name(item_id, phase_data) not in excluded_names]
            if rising:
                # map ids to names for readability
                df_rising = pd.DataFrame([{'Produit': get_item_name(it, phase_data), 'Variation x10': f"{delta * 10:.2f}"} for it, delta in rising])
                df_falling = pd.DataFrame([{'Produit': get_item_name(it, phase_data), 'Variation x10': f"{delta * 10:.2f}"} for it, delta in falling])
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
                    name = get_item_name(k, phase_data)
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
                for batiment in batiments_disponibles
                for obj_id in CONFIG_BATIMENTS.get(batiment, {}).get('ids', [])
            }
            rising, falling = get_saturation_trends(history, top_n=20, eligible_ids=eligible_ids)
            if excluded_names:
                rising = [(item_id, delta) for item_id, delta in rising if get_item_name(item_id, phase_data) not in excluded_names]
                falling = [(item_id, delta) for item_id, delta in falling if get_item_name(item_id, phase_data) not in excluded_names]
            if rising:
                df_rising = pd.DataFrame([{'Produit': get_item_name(item, phase_data), 'Variation x10': f"{delta * 10:.2f}"} for item, delta in rising])
                df_falling = pd.DataFrame([{'Produit': get_item_name(item, phase_data), 'Variation x10': f"{delta * 10:.2f}"} for item, delta in falling])
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Top saturation en hausse")
                    st.dataframe(df_rising, use_container_width=True)
                with col2:
                    st.subheader("Top saturation en baisse")
                    st.dataframe(df_falling, use_container_width=True)
        else:
            st.warning("Aucune donnée de saturation disponible. Lancez un scan ou vérifiez la connexion API.")

    with tab_selling:
        st.header("🏷️ Calculateur de Prix de Vente")
        st.markdown("Déterminez le prix de vente optimal pour un objet que vous possédez ou prévoyez d'acheter.")

        col_b, col_i, col_q = st.columns(3)
        with col_b:
            batiment_vente = st.selectbox("Bâtiment", batiments_disponibles, key="sell_building")
        with col_i:
            item_ids_vente = CONFIG_BATIMENTS[batiment_vente]["ids"]
            id_to_name_vente = {str(i): get_item_name(i, phase_data) for i in item_ids_vente}
            item_name_vente = st.selectbox("Produit", [id_to_name_vente[str(i)] for i in item_ids_vente], key="sell_item")
            item_id_vente = next(k for k, v in id_to_name_vente.items() if v == item_name_vente)
        with col_q:
            q_vente = st.number_input("Qualité", min_value=0, max_value=12, value=0, step=1, key="sell_q")

        method = st.radio("Méthode d'analyse des coûts", [
            "1️⃣ Prix d'achat fixe (J'ai un prix précis en tête)",
            "2️⃣ Contrat sous le prix du marché (Ex: -3% du marché)",
            "3️⃣ Coût d'opportunité (J'ai déjà l'objet, je veux maximiser mon profit en prenant en compte la meilleure alternative marché)"
        ])

        prix_achat_calc = 0.0
        salaire_reel = st.session_state.custom_config[batiment_vente]["salaire_bat"]
        niv_bat = st.session_state.custom_config[batiment_vente]["niv_bat"]
        bonus_ui = st.session_state.bonus_ui
        
        if method.startswith("1️⃣"):
            prix_achat_calc = st.number_input("Prix d'achat unitaire ($)", min_value=0.0, value=0.0, step=1.0)
        elif method.startswith("2️⃣"):
            pct_reduc = st.number_input("Réduction par rapport au marché (%)", min_value=0.0, max_value=100.0, value=3.0, step=0.1)
            offres = get_best_offers_by_quality(item_id_vente)
            if offres is None:
                st.error("Erreur API : Impossible de vérifier le marché. Veuillez réesayer.")
                prix_achat_calc = -1
            elif q_vente in offres:
                prix_marche = offres[q_vente]['price']
                real_q = offres[q_vente].get('real_q', q_vente)
                st.info(f"Prix du marché actuel pour Q{q_vente} (Couvert par Q{real_q}) : **${prix_marche:.2f}**")
                prix_achat_calc = prix_marche * (1 - pct_reduc / 100.0)
                st.write(f"Prix d'achat calculé : **${prix_achat_calc:.2f}**")
            else:
                st.warning("Aucune offre sur le marché pour cette qualité ou supérieure.")
                prix_achat_calc = -1
        elif method.startswith("3️⃣"):
            st.info("L'algorithme va scanner le marché pour trouver la meilleure rentabilité actuelle de ce bâtiment et s'en servir comme coût de votre temps.")

        if st.button("Calculer le Prix Optimal", type="primary"):
            if method.startswith("2️⃣") and prix_achat_calc < 0:
                st.error("Calcul impossible sans prix de marché.")
            else:
                with st.spinner("Analyse et calcul en cours..."):
                    sat = get_all_saturations().get(str(item_id_vente), 0.5)
                    stats = phase_data.get(str(item_id_vente))
                    
                    if not stats:
                        st.error("Données de l'objet introuvables.")
                    else:
                        if method.startswith("3️⃣"):
                            offres_item = get_best_offers_by_quality(item_id_vente)
                            if offres_item is None:
                                prix_marche = stats["modeledProductionCostPerUnit"]
                                st.warning(f"Erreur API. Base de coût estimée : **${prix_marche:.2f}**")
                            elif q_vente in offres_item:
                                prix_marche = offres_item[q_vente]['price']
                                real_q = offres_item[q_vente].get('real_q', q_vente)
                                st.info(f"Prix du marché (Base de coût) : **${prix_marche:.2f}** (Q{real_q})")
                            else:
                                prix_marche = stats["modeledProductionCostPerUnit"]
                                st.warning(f"Aucune offre. Base de coût estimée : **${prix_marche:.2f}**")
                                
                            saturations = get_all_saturations()
                            best_market_profit = 0.0
                            for b_item_id in item_ids_vente:
                                if str(b_item_id) not in phase_data: continue
                                b_stats = phase_data[str(b_item_id)]
                                b_sat = saturations.get(str(b_item_id), 0.5)
                                b_offres = get_best_offers_by_quality(b_item_id)
                                if b_offres is None: continue
                                for b_q, b_info in b_offres.items():
                                    b_prix = b_info['price'] if isinstance(b_info, dict) else b_info
                                    _, b_prof, _ = trouver_profit_maximum(
                                        str(b_item_id), b_stats, b_q, b_sat, bonus_ui,
                                        b_prix, 1, salaire_reel, niv_bat
                                    )
                                    if b_prof > best_market_profit:
                                        best_market_profit = b_prof
                            
                            st.success(f"Meilleur profit marché actuel identifié (Coût de votre temps) : **${best_market_profit:.2f}/h**")
                            
                            # --- OPTIMISATION SPÉCIFIQUE METHODE 3 ---
                            # On réutilise la fonction robuste trouver_profit_maximum qui gère déjà l'asymptote et les divisions par zéro
                            prix_opt, profit_h_reel, opt_res = trouver_profit_maximum(
                                str(item_id_vente), stats, q_vente, sat, bonus_ui,
                                prix_marche, 1, salaire_reel, niv_bat
                            )
                            temps_sec = opt_res["temps_vente"]
                            prix_achat_calc = prix_marche
                            
                            if temps_sec > 0:
                                t_heures = temps_sec / 3600
                                valeur_ajoutee = (prix_opt - prix_marche) - (salaire_reel + best_market_profit) * t_heures
                            else:
                                valeur_ajoutee = 0.0
                            # -----------------------------------------
                        else:
                            prix_opt, profit_h_reel, opt_res = trouver_profit_maximum(
                                str(item_id_vente), stats, q_vente, sat, bonus_ui,
                                prix_achat_calc, 1, salaire_reel, niv_bat
                            )
                            temps_sec = opt_res["temps_vente"]
                            
                        if temps_sec > 0:
                            st.markdown(f"### 🎯 Prix de vente optimal : **${prix_opt:.2f}**")
                            c1, c2, c3 = st.columns(3)
                            if not method.startswith("3️⃣"):
                                c1.metric("Profit par Heure", f"${profit_h_reel:.2f}")
                                c2.metric("Profit par Unité", f"${(prix_opt - prix_achat_calc):.2f}")
                            else:
                                c1.metric("Génération Cash/h", f"${profit_h_reel:.2f}", help="Cash brut généré par heure moins les salaires.")
                                c2.metric("Valeur Ajoutée", f"${valeur_ajoutee:.2f}", help="Surplus de valeur unitaire créé comparé à la vente du meilleur objet disponible sur le marché.")
                            c3.metric("Temps de vente", format_temps(temps_sec))
                        else:
                            st.error("Impossible de trouver un prix de vente rentable (temps de vente négatif ou infini).")

    with tab_contrats:
        st.header("🤝 Négociation de contrats")
        batiment_contract = st.selectbox("Bâtiment pour négocier", batiments_disponibles, key="contract_building")

        config_actuelle = st.session_state.custom_config[batiment_contract]
        bonus_ui = st.session_state.bonus_ui
        st.info(f"**Configuration active :** Niveau {config_actuelle['niv_bat']} | Salaire {config_actuelle['salaire_bat']}$/h")

        # Build item name list for selection
        item_ids = CONFIG_BATIMENTS[batiment_contract]["ids"]
        id_to_name = {str(i): get_item_name(i, phase_data) for i in item_ids}
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
            with st.spinner("Analyse globale du marché et calcul des réductions..."):
                saturations = get_all_saturations()
                
                # 1. Scan de tous les items du bâtiment pour trouver LE meilleur profit du marché
                best_market_profit = 0.0
                best_market_item = "Aucun"
                
                for b_item_id in item_ids:
                    if str(b_item_id) not in phase_data: continue
                    b_stats = phase_data[str(b_item_id)]
                    b_sat = saturations.get(str(b_item_id), 0.5)
                    b_offres = get_best_offers_by_quality(b_item_id)
                    if b_offres is None: continue
                    
                    for b_q, b_info in b_offres.items():
                        b_prix = b_info['price'] if isinstance(b_info, dict) else b_info
                        _, b_prof, _ = trouver_profit_maximum(
                            str(b_item_id), b_stats, b_q, b_sat, st.session_state.bonus_ui,
                            b_prix, 1, config_actuelle['salaire_bat'], config_actuelle['niv_bat']
                        )
                        if b_prof > best_market_profit:
                            best_market_profit = b_prof
                            best_market_item = f"{get_item_name(b_item_id, phase_data)} (Q{b_q})"
                            
                if best_market_profit > 0:
                    st.success(f"🏆 Meilleure opportunité actuelle (Marché) : **{best_market_item}** à **${best_market_profit:.2f}/h**")
                else:
                    st.warning("⚠️ Aucune offre rentable trouvée sur le marché pour ce bâtiment.")

                # 2. Récupérer les offres pour l'item sélectionné dans le contrat
                offres_item = get_best_offers_by_quality(item_id)

                # 3. Construire le tableau de résultats
                rows = []
                reductions = [1, 2, 3, 4, 5]
                item_stats = phase_data.get(str(item_id))
                item_sat = saturations.get(str(item_id), 0.5)
                
                if offres_item is None:
                    st.error("⚠️ L'API SimCompanies est surchargée. Veuillez réessayer dans quelques instants.")
                elif item_stats:
                    for q, info in offres_item.items():
                        prix_market = info['price'] if isinstance(info, dict) else info
                        
                        real_q = info.get("real_q", q)
                        try:
                            _, profit_h_base, _ = trouver_profit_maximum(
                                str(item_id), item_stats, real_q, item_sat, st.session_state.bonus_ui,
                                prix_market, 1, config_actuelle['salaire_bat'], config_actuelle['niv_bat']
                            )
                        except Exception:
                            profit_h_base = 0

                        row = {
                            'Qualité': f"Q{q}" + (f" (Achat Q{real_q})" if real_q != q else ""),
                            'Prix marché ($)': f"{prix_market:.2f}",
                            'Profit/h marché ($)': f"{profit_h_base:.2f}"
                        }
                        for pct in reductions:
                            reduced_price = prix_market * (1 - pct/100.0)
                            try:
                                _, profit_h_red, _ = trouver_profit_maximum(
                                    str(item_id), item_stats, q, item_sat, st.session_state.bonus_ui,
                                    reduced_price, 1, config_actuelle['salaire_bat'], config_actuelle['niv_bat']
                                )
                                # Comparaison avec LE MEILLEUR PROFIT DU MARCHÉ GLOBAL
                                if best_market_profit > 0 and profit_h_red is not None:
                                    profit_vs_marche = ((profit_h_red - best_market_profit) / abs(best_market_profit)) * 100
                                else:
                                    profit_vs_marche = None
                            except Exception:
                                profit_h_red = None
                                profit_vs_marche = None
                                
                            row[f"Prix @ -{pct}%"] = f"{reduced_price:.2f}"
                            row[f"Profit/h @ -{pct}%"] = f"{profit_h_red:.2f}" if profit_h_red is not None else 'N/A'
                            row[f"Vs Meilleur Marché @ -{pct}%"] = f"{profit_vs_marche:.2f}%" if profit_vs_marche is not None else 'N/A'
                        rows.append(row)

                if rows:
                    df = pd.DataFrame(rows)
                    # Préparation HTML pour la coloration
                    highlight_cols = [col for col in df.columns if col.startswith('Vs Meilleur Marché @')]
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
                elif offres_item is not None:
                    st.warning("Aucune offre de marché disponible pour ce produit (Il n'est pas vendu sur le marché public actuellement).")

        # EVALUATION MANUELLE DE CONTRAT (Pour Camions / Vehicules)
        st.markdown("---")
        st.subheader("📝 Évaluation Manuelle de Contrat")
        st.info("Utilisez cet outil pour vérifier manuellement la rentabilité d'un contrat spécifique, avec comparaison directe du marché.")
        
        col_q, col_p = st.columns(2)
        with col_q:
            man_q = st.number_input("Qualité proposée", min_value=0, max_value=12, value=0, step=1)
        with col_p:
            man_p = st.number_input("Prix d'achat unitaire ($)", min_value=0.0, value=0.0, step=10.0)
            
        if st.button("Calculer la rentabilité de ce contrat"):
            item_stats = phase_data.get(str(item_id))
            item_sat = get_all_saturations().get(str(item_id), 0.5)
            
            if item_stats and man_p > 0:
                with st.spinner("Analyse du marché en cours..."):
                    offres_marche = get_best_offers_by_quality(item_id)
                    prix_marche = None
                    real_q = None
                    
                    if offres_marche and man_q in offres_marche:
                        prix_marche = offres_marche[man_q]['price']
                        real_q = offres_marche[man_q].get('real_q', man_q)

                    prix_opt, prof_h, stats_opt = trouver_profit_maximum(
                        str(item_id), item_stats, man_q, item_sat, st.session_state.bonus_ui,
                        man_p, 1, config_actuelle['salaire_bat'], config_actuelle['niv_bat']
                    )
                
                    # --- RECHERCHE DU MEILLEUR ITEM DU BATIMENT SUR LE MARCHE ---
                    best_market_profit_building = 0.0
                    best_market_item_building = "Aucun"
                    saturations = get_all_saturations()
                    
                    for b_item_id in item_ids:
                        if str(b_item_id) not in phase_data: continue
                        b_stats = phase_data[str(b_item_id)]
                        b_sat = saturations.get(str(b_item_id), 0.5)
                        b_offres = get_best_offers_by_quality(b_item_id)
                        if b_offres is None: continue
                        
                        for b_q, b_info in b_offres.items():
                            b_prix = b_info['price'] if isinstance(b_info, dict) else b_info
                            _, b_prof, _ = trouver_profit_maximum(
                                str(b_item_id), b_stats, b_q, b_sat, st.session_state.bonus_ui,
                                b_prix, 1, config_actuelle['salaire_bat'], config_actuelle['niv_bat']
                            )
                            if b_prof > best_market_profit_building:
                                best_market_profit_building = b_prof
                                best_market_item_building = f"{get_item_name(b_item_id, phase_data)} (Q{b_q})"
                    # ------------------------------------------------------------
                
                if prof_h > 0:
                    st.success("✅ **Contrat Rentable !**")
                    
                    if prix_marche:
                        reduction = (1 - (man_p / prix_marche)) * 100
                        st.info(f"📊 **Analyse Marché public :** Le prix le plus bas pour **Q{man_q}** (couvert par Q{real_q}) est de **${prix_marche:.2f}**.")
                        
                        if reduction > 0:
                            st.markdown(f"🔥 Vous achetez à <span style='color:#2ecc71;font-weight:bold'>-{reduction:.2f}%</span> sous le prix du marché public.", unsafe_allow_html=True)
                        elif reduction < 0:
                            st.warning(f"⚠️ Attention, vous achetez à **+{abs(reduction):.2f}%** au-dessus du prix du marché public !")
                        else:
                            st.markdown("⚖️ Vous achetez exactement au prix du marché public.")
                        
                    elif offres_marche is None:
                        st.warning("⚠️ Impossible de comparer avec le marché : L'API SimCompanies est temporairement indisponible.")
                    else:
                        st.info(f"📊 **Analyse Marché public :** Aucune offre disponible sur le marché public pour Q{man_q} ou supérieur.")

                    # --- NOUVEAU : Comparaison avec la meilleure opportunité globale du marché ---
                    if best_market_profit_building > 0:
                        profit_diff = ((prof_h - best_market_profit_building) / best_market_profit_building) * 100
                        if profit_diff > 0:
                            st.markdown(f"🚀 **Surperformance globale :** Ce contrat génère <span style='color:#2ecc71;font-weight:bold'>+{profit_diff:.2f}%</span> de profit/h par rapport à la meilleure offre du marché pour ce bâtiment (**{best_market_item_building}** à **${best_market_profit_building:.2f}/h**).", unsafe_allow_html=True)
                        elif profit_diff < 0:
                            st.markdown(f"🔻 **Coût d'opportunité :** Ce contrat rapporte <span style='color:#e74c3c;font-weight:bold'>{abs(profit_diff):.2f}%</span> de profit/h en moins par rapport à l'achat direct de **{best_market_item_building}** sur le marché (qui donnerait **${best_market_profit_building:.2f}/h**).", unsafe_allow_html=True)
                        else:
                            st.markdown(f"⚖️ Ce contrat génère exactement le même profit/h que la meilleure offre marché (**{best_market_item_building}** à **${best_market_profit_building:.2f}/h**).")
                    else:
                        st.markdown(f"⚠️ Actuellement, aucune offre du marché n'est rentable pour ce bâtiment. Ce contrat est la seule source de profit !")
                    # ----------------------------------------------------------------

                    cm1, cm2, cm3, cm4 = st.columns(4)
                    cm1.metric("Revente Opt.", f"${prix_opt:.2f}")
                    cm2.metric("Profit/h", f"${prof_h:.2f}")
                    cm3.metric("Profit/Jour", f"${(prof_h*24):.2f}")
                    cm4.metric("Temps de vente", format_temps(stats_opt['temps_vente']))
                else:
                    st.error("❌ **Contrat non rentable.** (Le salaire absorbe toute la marge !)")

    with tab_settings:
        st.header(f"⚙️ Paramètres de {current_user}")
        st.markdown("Les modifications sont **sauvegardées automatiquement** sur votre profil.")
        
        def on_settings_change(): # Callback to save changes instantly
            current_data = load_users()
            current_data[current_user]["bonus_ui"] = st.session_state.input_bonus
            for nom_bat in batiments_disponibles:
                current_data[current_user]["buildings"][nom_bat]["niv_bat"] = st.session_state[f"input_niv_{nom_bat}"]
                current_data[current_user]["buildings"][nom_bat]["salaire_bat"] = st.session_state[f"input_sal_{nom_bat}"]
            save_users(current_data)
            st.session_state.custom_config = current_data[current_user]["buildings"] # Update live session
            st.session_state.bonus_ui = current_data[current_user]["bonus_ui"]

        st.number_input("Bonus UI (Vitesse)", min_value=1.0, max_value=2.0, value=st.session_state.bonus_ui, step=0.01, key="input_bonus", on_change=on_settings_change)
        
        st.subheader("Configuration des Bâtiments")
        cols = st.columns(3)
        for i, nom_bat in enumerate(batiments_disponibles):
            with cols[i % 3]:
                st.markdown(f"**{nom_bat}**")
                config_act = st.session_state.custom_config[nom_bat]
                
                st.number_input("Niveau", min_value=1, value=config_act["niv_bat"], key=f"input_niv_{nom_bat}", on_change=on_settings_change)
                st.number_input("Salaire/h ($)", min_value=0, value=config_act["salaire_bat"], key=f"input_sal_{nom_bat}", on_change=on_settings_change)
                st.divider()

    with tab_about:
        st.header("ℹ️ À Propos")
        st.markdown("""
        ### SimCompanies Market Scanner
        
        Cet outil analyse les opportunités de profit sur le marché SimCompanies.
        
        **Fonctionnalités:**
        - 🔍 Scan automatique multi-bâtiments
        - 📈 Analyse détaillée par item
        - 📉 Suivi de saturation
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
