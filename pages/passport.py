import streamlit as st
from functions import services

st.set_page_config(
    page_title="EU Digital Product Passport",
    layout="centered"
)

passport_id = st.query_params.get("id")

if not passport_id:
    st.error("Digital Product Passport not found")
    st.stop()

passport = services.load_passport_from_file(passport_id)

if not passport:
    st.error("Passport does not exist")
    st.stop()

# =========================
# HEADER
# =========================
st.title("🇪🇺 Digital Product Passport")
st.caption("Regulation (EU) – Ecodesign for Sustainable Products (ESPR)")

st.markdown(f"""
**Product ID:** `{passport['id']}`  
**Product type:** {passport['tipo_prodotto']}  
**Created:** {passport['metadata']['creato_il']}  
**Version:** {passport['metadata']['versione']}
""")

st.divider()

# =========================
# 1. PRODUCT IDENTITY
# =========================
st.subheader("1️⃣ Product Identity")
for k, v in passport["dati_certificati_pdf"].items():
    st.write(f"**{k}**: {v}")

st.divider()

# =========================
# 2. VISUAL / ESTIMATED DATA
# =========================
st.subheader("2️⃣ Visual & Estimated Information")
st.caption("Automatically estimated from product image")

for k, v in passport["dati_visivi_stimati"].items():
    st.write(f"**{k}**: {v}")

st.divider()

# =========================
# 3. SUSTAINABILITY (PLACEHOLDER)
# =========================
st.subheader("3️⃣ Sustainability & Circularity")
st.write("Repairability: N/A")
st.write("Recyclability: N/A")
st.write("Recycled content: N/A")

st.divider()

# =========================
# 4. END OF LIFE
# =========================
st.subheader("4️⃣ End of Life Information")
st.write("Disposal instructions: N/A")
st.write("Recycling streams: N/A")

st.divider()

# =========================
# METADATA
# =========================
st.subheader("📑 Metadata & Compliance")
st.json(passport["metadata"])

st.caption(
    "This Digital Product Passport is provided for transparency, traceability "
    "and compliance with EU sustainability regulations. Public read-only access."
)
