import streamlit as st
import uuid
from openai import OpenAI
from functions import services
from PIL import Image
import os
import pandas as pd
import base64
from io import BytesIO
import streamlit.components.v1 as components

# ======================================================
# CONFIG STREAMLIT
# ======================================================
st.set_page_config(
    page_title="Nuvia Digital Product Passport",
    page_icon="functions/favicon.jpeg",
    layout="centered"
)

# ======================================================
# LOGO + STILE
# ======================================================
logo = Image.open("functions/logo_nuvia.jpeg")
logo_base64 = services.image_to_base64(logo)

st.markdown(f"""
<style>
body {{background-color:#f5f1ed; color:#3a2607; font-family:Nunito Sans;}}
.stButton>button {{background-color:#25ce6c; color:white; border-radius:8px;}}
.required-field {{font-weight:bold; color:#d9534f;}}
</style>
<img src="data:image/jpeg;base64,{logo_base64}" width="350">
""", unsafe_allow_html=True)

# ======================================================
# OPENAI CLIENT
# ======================================================
client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# SESSION STATE OTTIMIZZATO
# ======================================================
for key in ["uploaded_pdf_bytes", "uploaded_images_bytes", "uploaded_cert_bytes",
            "pdf_data", "image_data", "cert_data",
            "validated_pdf", "validated_image", "validated_cert", "images", "cert_files"]:
    if key not in st.session_state:
        st.session_state[key] = None

# ======================================================
# PUBLIC VIEW (QR LINK)
# ======================================================
passport_id = st.query_params.get("passport_id")
if passport_id:
    passport = services.load_passport_from_file(passport_id)
    if not passport:
        st.error("Passport non trovato")
        st.stop()

    st.title("🇪🇺 Digital Product Passport")
    st.write(f"**ID:** {passport['id']}")
    st.write(f"**Tipo:** {passport['product_type']}")

    for sec_name, sec in passport["sections"].items():
        st.subheader(f"{sec_name} ({sec['section_rating']*100:.0f}%)")
        for fname, f in sec["fields"].items():
            conf = f.get("confidence", 0)
            st.write(f"**{fname}**: {f['value']} {f['color']} (conf: {conf})")
            if conf < 0.5:
                st.caption("Bassa confidenza")
            if f.get("explanation"):
                st.caption(f["explanation"])

    if "certificates" in passport and passport["certificates"]:
        st.subheader("Certificati")
        for cert in passport["certificates"]:
            st.write(f"**Nome:** {cert.get('nome_certificato', {}).get('value')}")
            st.write(f"**Ente:** {cert.get('ente_emittente', {}).get('value')}")
            st.write(f"**Numero:** {cert.get('numero_certificato', {}).get('value')}")
            st.write(f"**Emissione:** {cert.get('data_emissione', {}).get('value')}")
            st.write(f"**Scadenza:** {cert.get('data_scadenza', {}).get('value')}")
            st.write("---")

    services.render_espr_compliance(passport)
    st.progress(passport.get("overall_rating", 0))
    st.metric("Reliability", f"{int(passport.get('overall_rating', 0)*100)}%")
    st.metric("Sustainability", f"{int(passport.get('sustainability_score', 0)*100)}%")

    if passport.get("images"):
        for img in passport["images"]:
            st.image(f"data:image/jpeg;base64,{img['file_base64']}")

    st.stop()

# ======================================================
# SELEZIONE TIPO PRODOTTO
# ======================================================
tipo = st.selectbox("Tipo prodotto", ["mobile", "lampada", "bicicletta"])
fields = [f["name"] for f in services.PRODUCT_FIELDS[tipo]["pdf"]]

tabs = st.tabs(["📤 Upload & Analisi", "📝 Validazione", "🔗 Pubblica", "📚 Archivio"])

# ======================================================
# TAB 1 — UPLOAD + AI
# ======================================================
with tabs[0]:
    pdf_file = st.file_uploader("PDF prodotto", type=["pdf"])
    image_files = st.file_uploader("Immagini prodotto", type=["jpg", "png"], accept_multiple_files=True)
    cert_files = st.file_uploader("Certificati (PDF o immagini)", type=["pdf","jpg","png"], accept_multiple_files=True)

    if st.button("Analizza"):
        if not pdf_file or not image_files:
            st.warning("Carica PDF e almeno un'immagine")
        else:
            st.session_state.uploaded_pdf_bytes = pdf_file.read()
            st.session_state.uploaded_images_bytes = [img.read() for img in image_files]
            st.session_state.images = image_files
            st.session_state.cert_files = cert_files or []
            st.session_state.uploaded_cert_bytes = [c.read() for c in st.session_state.cert_files] if cert_files else []

            with st.spinner("Analisi in corso..."):
                # PDF
                pdf_text = services.extract_text_from_pdf(BytesIO(st.session_state.uploaded_pdf_bytes))
                st.session_state.pdf_data = services.gpt_extract_from_pdf(pdf_text, client, tipo, fields)

                # Immagini
                img_data = {}
                for img_bytes in st.session_state.uploaded_images_bytes:
                    res = services.gpt_analyze_image(BytesIO(img_bytes), client, tipo)
                    img_data.update(res)
                st.session_state.image_data = img_data

                # Certificati
                cert_data_list = []
                for cert_bytes in st.session_state.uploaded_cert_bytes:
                    res = services.gpt_extract_cert_info(BytesIO(cert_bytes), client)
                    cert_data_list.append(res)
                st.session_state.cert_data = cert_data_list

            st.success("Analisi completata ✅")

# ======================================================
# TAB 2 — VALIDAZIONE
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data and st.session_state.image_data:
        st.subheader("Validazione dati PDF")
        validated_pdf = {
            k: {"value": st.text_input(f"{k} (conf: {v.get('confidence',0)})", v["value"], help=v.get("explanation","")), 
                "confidence": v.get("confidence",0)}
            for k,v in st.session_state.pdf_data.items()
        }
        st.session_state.validated_pdf = validated_pdf

        st.subheader("Validazione dati Immagini")
        validated_img = {
            k: {"value": st.text_input(f"{k} (conf: {v.get('confidence',0)})", v["value"], help=v.get("explanation","")),
                "confidence": v.get("confidence",0)}
            for k,v in st.session_state.image_data.items()
        }
        st.session_state.validated_image = validated_img

        # Certificati
        if st.session_state.cert_data:
            st.subheader("Validazione certificati")
            validated_cert_list = []
            for i, cert in enumerate(st.session_state.cert_data):
                validated_cert = {}
                st.markdown(f"**Certificato {i+1}**")
                for k, v in cert.items():
                    validated_cert[k] = {
                        "value": st.text_input(f"{k} (conf: {v.get('confidence',0)})", v["value"], key=f"cert_{i}_{k}"),
                        "confidence": v.get("confidence",0)
                    }
                validated_cert_list.append(validated_cert)
            st.session_state.validated_cert = validated_cert_list

        if st.button("Completa validazione"):
            st.success("Validazione completata ✅")
    else:
        st.info("Esegui prima l’analisi PDF e immagini")

# ======================================================
# TAB 3 — PUBBLICA
# ======================================================
with tabs[2]:
    if st.session_state.validated_pdf and st.session_state.validated_image:
        if st.button("Pubblica Digital Product Passport"):
            pid = f"{tipo.upper()}-{uuid.uuid4().hex[:6]}"
            passport = services.initialize_passport(pid, tipo, fields)
            services.merge_data(passport, st.session_state.validated_pdf, st.session_state.validated_image, st.session_state.validated_cert)

            # Immagini
            for img_bytes in st.session_state.uploaded_images_bytes:
                services.add_product_image(passport, BytesIO(img_bytes))

            # Salvataggio
            services.save_passport_to_file(passport)
            services.save_passport_to_excel_append(passport)

            # QR
            url = f"{st.secrets['APP_URL']}?passport_id={pid}"
            qr = services.generate_qr_from_url(url)
            st.success("DPP pubblicato ✅")
            st.image(qr)
            st.download_button("Scarica QR code", data=qr.getvalue(), file_name=f"{pid}_qr.png", mime="image/png")
            st.code(url)
    else:
        st.info("Completa prima la validazione PDF e immagini")

# ======================================================
# TAB 4 — ARCHIVIO
# ======================================================
with tabs[3]:
    st.header("Archivio Passport")
    if os.path.exists(services.EXCEL_FILE):
        try:
            df_passport = pd.read_excel(services.EXCEL_FILE, sheet_name="passport").pipe(lambda df: df.rename(columns=str.strip))
            df_fields = pd.read_excel(services.EXCEL_FILE, sheet_name="fields").pipe(lambda df: df.rename(columns=str.strip))
            df_images = pd.read_excel(services.EXCEL_FILE, sheet_name="images").pipe(lambda df: df.rename(columns=str.strip))

            if df_passport.empty:
                st.info("Nessun passport disponibile")
            else:
                df_full = df_passport.merge(
                    df_fields.pivot_table(index="passport_id", columns="field_name", values="value", aggfunc="first").reset_index(),
                    left_on="id", right_on="passport_id", how="left"
                )

                # Filtri interattivi
                nome = st.text_input("Nome prodotto")
                luogo = st.text_input("Luogo produzione")
                prezzo_min, prezzo_max = st.number_input("Prezzo minimo", 0), st.number_input("Prezzo massimo", 10000)
                data_min, data_max = st.date_input("Data da"), st.date_input("Data a")

                df_filtered = df_full.copy()
                if nome: df_filtered = df_filtered[df_filtered["Nome prodotto"].astype(str).str.contains(nome, case=False, na=False)]
                if luogo: df_filtered = df_filtered[df_filtered["Luogo di produzione"].astype(str).str.contains(luogo, case=False, na=False)]
                if "Prezzo" in df_filtered.columns:
                    df_filtered["Prezzo_num"] = pd.to_numeric(df_filtered["Prezzo"].astype(str).str.replace("€","").str.replace(",","."), errors='coerce')
                    df_filtered = df_filtered[(df_filtered["Prezzo_num"] >= prezzo_min) & (df_filtered["Prezzo_num"] <= prezzo_max)]
                if "created_at" in df_filtered.columns:
                    df_filtered["created_at"] = pd.to_datetime(df_filtered["created_at"], errors='coerce')
                    df_filtered = df_filtered[(df_filtered["created_at"].dt.date >= data_min) & (df_filtered["created_at"].dt.date <= data_max)]

                st.subheader("Risultati filtrati")
                st.dataframe(df_filtered)

                selected_id = st.selectbox("Seleziona Passport", df_filtered["id"]) if not df_filtered.empty else None
                if selected_id:
                    st.subheader("Dettaglio")
                    st.dataframe(df_passport[df_passport["id"]==selected_id])
                    st.subheader("Fields")
                    st.dataframe(df_fields[df_fields["passport_id"]==selected_id])
                    st.subheader("Immagini")
                    for _, row in df_images[df_images["passport_id"]==selected_id].iterrows():
                        st.image(f"data:image/jpeg;base64,{row['file_base64']}", caption=row.get("caption",""))

        except Exception as e:
            st.error(f"Errore archivio: {e}")
    else:
        st.info("Nessun file Excel trovato")
