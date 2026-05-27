import importlib
import streamlit as st

print('Starting tests')
try:
    app = importlib.import_module('streamlit_app')
except Exception as e:
    print('Import error:', e)
    raise

# Ensure session_state config exists
if 'custom_config' not in st.session_state:
    st.session_state.custom_config = {name: cfg.copy() for name, cfg in app.CONFIG_BATIMENTS.items()}

print('Loaded module, custom_config set')

# Load database
data = app.load_database()
print('Database phase_1 entries:', len(data.get('phase_1', {})))

# Fetch saturation data
sat_data = app.fetch_saturation_data()
print('Saturation API items:', len(sat_data))

# Test trends
try:
    rising, falling = app.get_api_saturation_trends(sat_data, top_n=10)
    print('Rising sample:', rising[:5])
    print('Falling sample:', falling[:5])
except Exception as e:
    print('Error in get_api_saturation_trends:', e)

# Test contract table for Groceries Store with first 3 ids
try:
    building = list(app.CONFIG_BATIMENTS.keys())[0]
    ids = app.CONFIG_BATIMENTS[building]['ids'][:3]
    df_contract = app.build_contract_negotiation_table(data, building, ids, bonus_ui=1.02)
    print('Contract table rows:', len(df_contract))
    print(df_contract.head().to_dict())
except Exception as e:
    print('Error in build_contract_negotiation_table:', e)

# Test director financier plan with small budget
try:
    plan, rem = app.compute_director_financier_plan(1000, 8, list(app.CONFIG_BATIMENTS.keys())[:2], data, 1.02)
    print('Plan size:', len(plan), 'Remaining:', rem)
except Exception as e:
    print('Error in compute_director_financier_plan:', e)

print('Tests completed')
