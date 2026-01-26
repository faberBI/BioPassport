import streamlit as st
from functions import services

st.set_page_config(
    page_title="Digital Product Passport",
    layout="centered"
)

# =========================
# READ QUERY PARAM
# =========================
passport_id = st.query_params.get("id")

if not passport_id:
    st.error("Digital Product Passport not found")
    st.stop()

# =========================
# LOAD PASSPORT JSON
# =========================
passport = services.load_passport_from_file(passport_id)

if not passport:
    st.error("Passport does not exist")
    st.stop()

# =========================
# RENDER DPP (EU-STYLE)
# =========================
st.title("🇪🇺 Digital Product Passport")
st.caption("EU Ecodesign / ESPR Regulation")

st.markdown(f"""
**Product ID:** `{passport['id']}`  
**Product type:** {passport['tipo_prodotto']}  
**Created:** {passport['metadata']['creato_il']}  
**Version:** {passport['metadata']['versione']}
""")

st.divider()

st.subheader("📄 Certified Product Data")
for k, v in passport["dati_certificati_pdf"].items():
    st.write(f"**{k}**: {v}")

st.divider()

st.subheader("👁️ Visual / Estimated Data")
for k, v in passport["dati_visivi_stimati"].items():
    st.write(f"**{k}**: {v}")

st.divider()

st.caption("Public, read-only Digital Product Passport")
