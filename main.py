import streamlit as st
import uuid
from openai import OpenAI
from functions import services
from PIL import Image
import os
import pandas as pd
from io import BytesIO

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
# SESSION STATE INIT
# ======================================================
DEFAULT_STATE = {
    "uploaded_pdf_bytes": None,
    "uploaded_images_bytes": None,
    "uploaded_cert_bytes": None,
    "pdf_data": None,
    "image_data": None,
    "cert_data": None,
    "validated_pdf": None,
    "validated_image": None,
    "validated_cert": None,
}

for k, v in DEFAULT_STATE.items():
    st.session_state.setdefault(k, v)

# ======================================================
# PUBLIC VIEW (?passport_id=...)
# ======================================================
passport_id = st.query_params.get("passport_id")
if passport_id:
    passport = services.load_passport_from_file(passport_id)
    if not passport:
        st.error("Passport non trovato")
        st.stop()

    st.title("🇪🇺 Digital Product Passport")

    st.markdown(f"""
**ID:** {passport.get("id")}  
**Tipo:** {passport.get("product_type")}  
**Versione:** {passport.get("version")}  
**Issuer:** {(passport.get("issuer") or {}).get("legal_name")}  
**Firma hash:** `{(passport.get("digital_signature") or {}).get("hash","")[:16]}…`
""")

    for sec_name, sec in passport.get("sections", {}).items():
        st.subheader(sec_name)
        for fname, f in sec.items():
            val = f.get("value") if isinstance(f, dict) else f
            conf = f.get("confidence", 0) if isinstance(f, dict) else 0
            exp = f.get("explanation", "") if isinstance(f, dict) else ""
            st.write(f"**{fname}**: {val} (conf: {conf})")
            if conf < 0.5:
                st.caption("⚠️ Bassa confidenza")
            if exp:
                st.caption(exp)

    if passport.get("certificates"):
        st.subheader("Certificati")
        for cert in passport["certificates"]:
            for k, v in cert.items():
                st.write(f"**{k}**: {v.get('value','') if isinstance(v,dict) else v}")
            st.divider()

    services.render_espr_compliance(passport)

    st.progress(passport.get("overall_rating", 0))
    st.metric("Reliability", f"{int(passport.get('overall_rating',0)*100)}%")
    st.metric("Sustainability", f"{int(passport.get('sustainability_score',0)*100)}%")

    for img in passport.get("images", []):
        st.image(f"data:image/jpeg;base64,{img['file_base64']}", caption=img.get("caption",""))

    st.stop()

# ======================================================
# SELEZIONE TIPO PRODOTTO
# ======================================================
tipo = st.selectbox("Tipo prodotto", ["mobile", "lampada", "bicicletta"])
fields = list(services.PRODUCT_FIELDS.get(tipo, {}).get("pdf", []))

tabs = st.tabs(["📤 Upload & Analisi", "📝 Validazione", "🔗 Pubblica", "📚 Archivio"])

# ======================================================
# TAB 1 — UPLOAD & AI
# ======================================================
with tabs[0]:
    pdf_file = st.file_uploader("PDF prodotto", type=["pdf"])
    image_files = st.file_uploader("Immagini prodotto", type=["jpg", "png"], accept_multiple_files=True)
    cert_files = st.file_uploader("Certificati", type=["pdf", "jpg", "png"], accept_multiple_files=True)

    if st.button("Analizza"):
        if not pdf_file or not image_files:
            st.warning("Carica PDF e almeno un'immagine")
        else:
            st.session_state.uploaded_pdf_bytes = pdf_file.read()
            st.session_state.uploaded_images_bytes = [i.read() for i in image_files]
            st.session_state.uploaded_cert_bytes = [c.read() for c in (cert_files or [])]

            with st.spinner("Analisi in corso..."):
                pdf_text = services.extract_text_from_pdf(BytesIO(st.session_state.uploaded_pdf_bytes))
                st.session_state.pdf_data = services.gpt_extract_from_pdf(pdf_text, client, tipo, fields)

                img_data = {}
                for b in st.session_state.uploaded_images_bytes:
                    img_data.update(services.gpt_analyze_image(BytesIO(b), client, tipo))
                st.session_state.image_data = img_data

                cert_list = []
                for b in st.session_state.uploaded_cert_bytes:
                    cert_list.append(services.gpt_extract_cert_info(BytesIO(b), client))
                st.session_state.cert_data = cert_list

            st.success("Analisi completata ✅")

# ======================================================
# TAB 2 — VALIDAZIONE
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data and st.session_state.image_data:
        st.subheader("Validazione PDF")
        st.session_state.validated_pdf = {
            k: {
                "value": st.text_input(k, v.get("value",""), help=v.get("explanation","")),
                "confidence": v.get("confidence",0)
            }
            for k, v in st.session_state.pdf_data.items()
        }

        st.subheader("Validazione Immagini")
        st.session_state.validated_image = {
            k: {
                "value": st.text_input(k, v.get("value",""), help=v.get("explanation","")),
                "confidence": v.get("confidence",0)
            }
            for k, v in st.session_state.image_data.items()
        }

        if st.session_state.cert_data:
            st.subheader("Certificati")
            validated = []
            for i, cert in enumerate(st.session_state.cert_data):
                st.markdown(f"**Certificato {i+1}**")
                row = {}
                for k, v in cert.items():
                    val = v.get("value","") if isinstance(v,dict) else v
                    row[k] = {"value": st.text_input(k, val, key=f"c{i}_{k}"), "confidence": v.get("confidence",0)}
                validated.append(row)
            st.session_state.validated_cert = validated

        st.success("Validazione pronta ✅")
    else:
        st.info("Esegui prima l’analisi")

# ======================================================
# TAB 3 — PUBBLICA
# ======================================================
with tabs[2]:
    if st.session_state.validated_pdf and st.session_state.validated_image:
        if st.button("Pubblica DPP"):
            pid = f"{tipo.upper()}-{uuid.uuid4().hex[:6]}"
            passport = services.initialize_passport(pid, tipo, fields)

            # === merge dati ===
            if tipo == "mobile":
                services.merge_data_with_ecolabel(
                    passport,
                    pdf_file=BytesIO(st.session_state.uploaded_pdf_bytes),
                    image_data=st.session_state.validated_image,
                    cert_data=st.session_state.validated_cert,
                    client=client
                )
            else:
                services.merge_data(
                    passport,
                    st.session_state.validated_pdf,
                    st.session_state.validated_image,
                    st.session_state.validated_cert
                )

            # === immagini ===
            for b in st.session_state.uploaded_images_bytes:
                services.add_product_image(passport, BytesIO(b))

            # === ESPR stamp ===
            services.espr_stamp(
                passport,
                actor="manufacturer",
                action="finalize",
                reason="Final publication"
            )

            # ==================================================
            # 🔐 FIRMA QES OPENAPI (QUESTA È LA PARTE NUOVA)
            # ==================================================
            with st.spinner("Firma qualificata QES in corso..."):
                try:
                    services.sign_passport_qes_openapi(passport)
                except Exception as e:
                    st.error(f"Errore firma QES: {e}")
                    st.stop()

            # === salvataggi ===
            services.save_passport_to_file(passport)
            services.save_passport_to_excel_append(passport)

            st.success("✅ Digital Product Passport pubblicato e firmato")

            # === output ===
            url = f"{st.secrets['APP_URL']}?passport_id={pid}"
            st.code(url)
            qr = services.generate_qr_from_url(url)
            st.image(qr)

            # info firma
            sig = passport.get("qualified_signature", {})
            if sig:
                st.info(
                    f"Firma QES OpenAPI\n"
                    f"ID: {sig.get('signature_id')}\n"
                    f"Stato: {sig.get('state')}"
                )
    else:
        st.info("Completa prima la validazione")

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
                # 1) Tieni SOLO l’ultima versione per ogni id
                df_passport["version"] = pd.to_numeric(df_passport["version"], errors="coerce")
                df_latest = df_passport.sort_values(["id", "version"]).groupby("id", as_index=False).tail(1)

                # 2) Crea una chiave unica per pivot: section__field_name
                if "section" in df_fields.columns:
                    df_fields["field_key"] = df_fields["section"].astype(str) + "__" + df_fields["field_name"].astype(str)
                else:
                    df_fields["field_key"] = df_fields["field_name"].astype(str)

                # 3) Pivot "safe"
                df_pivot = df_fields.pivot_table(
                    index="passport_id",
                    columns="field_key",
                    values="value",
                    aggfunc="first"
                ).reset_index()

                # 4) Merge con i meta
                df_full = df_latest.merge(df_pivot, left_on="id", right_on="passport_id", how="left")

                st.subheader("Risultati")
                st.dataframe(df_full, use_container_width=True)

                # Dettaglio
                selected_id = st.selectbox("Seleziona Passport", df_full["id"]) if not df_full.empty else None
                if selected_id:
                    st.subheader("Dettaglio Passport (meta)")
                    st.dataframe(df_latest[df_latest["id"] == selected_id])

                    st.subheader("Campi (tutte le sezioni)")
                    st.dataframe(df_fields[df_fields["passport_id"] == selected_id])

                    st.subheader("Immagini")
                    for _, row in df_images[df_images["passport_id"] == selected_id].iterrows():
                        st.image(f"data:image/jpeg;base64,{row['file_base64']}", caption=row.get("caption", ""))

        except Exception as e:
            st.error(f"Errore archivio: {e}")
    else:
        st.info("Nessun file Excel trovato")
