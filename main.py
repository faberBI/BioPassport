import streamlit as st
import uuid
import os
import base64
import pandas as pd
from io import BytesIO
from PIL import Image
from openai import OpenAI

from functions import services

# ======================================================
# CONFIG STREAMLIT
# ======================================================
st.set_page_config(
    page_title="Nuvia Digital Product Passport",
    page_icon="functions/favicon.jpeg",
    layout="centered"
)

# ======================================================
# HEADER / LOGO
# ======================================================
try:
    st.image("functions/logo_nuvia.jpeg", width=220)
except Exception:
    pass

st.title("🇪🇺 Digital Product Passport")

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
    "uploaded_cert_names": None,  # ✅ NEW
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

    st.subheader("📌 Metadata principali")
    st.markdown(
        f"""
**ID:** {passport.get("id")}  
**Tipo:** {passport.get("product_type")}  
**Versione:** {passport.get("version")}  
**Issuer:** {(passport.get("issuer") or {}).get("legal_name")}  
**Lifecycle:** {(passport.get("lifecycle") or {}).get("status", "—")}  
**Hash (integrità):** `{(passport.get("digital_signature") or {}).get("hash","")[:16]}…`
"""
    )

    # --- Sigillo QeSeal (preferito) ---
    if passport.get("qualified_seal"):
        seal = passport["qualified_seal"]
        st.subheader("🔐 Sigillo elettronico qualificato (QeSeal)")
        st.write(f"Provider: {seal.get('provider')}")
        st.write(f"Servizio: {seal.get('service')}")
        st.write(f"Seal ID: {seal.get('seal_id')}")
        st.write(f"Stato: {seal.get('state')}")
    elif passport.get("qualified_signature"):
        qs = passport["qualified_signature"]
        st.subheader("🔐 Firma qualificata (QES)")
        st.write(f"Provider: {qs.get('provider')}")
        st.write(f"Servizio: {qs.get('service')}")
        st.write(f"Signature ID: {qs.get('signature_id')}")
        st.write(f"Stato: {qs.get('state')}")
    else:
        st.info("Nessun sigillo/firma qualificata presente")

    # --- Legame fisico-digitale ---
    if passport.get("physical_binding"):
        pb = passport["physical_binding"]
        st.subheader("🔗 Legame fisico‑digitale")
        st.write(f"Carrier: {pb.get('carrier')}")
        st.write(f"Location: {pb.get('location')}")
        st.write(f"URL: {pb.get('public_url')}")
        st.write(f"Tamper risk: {pb.get('tamper_risk')}")

    # --- Sezioni DPP ---
    st.subheader("🧩 Contenuti (sezioni)")
    for sec_name, sec in passport.get("sections", {}).items():
        st.markdown(f"### {sec_name}")
        if isinstance(sec, dict):
            for fname, f in sec.items():
                val = f.get("value") if isinstance(f, dict) else f
                conf = f.get("confidence", 0) if isinstance(f, dict) else 0
                exp = f.get("explanation", "") if isinstance(f, dict) else ""
                st.write(f"**{fname}**: {val}  _(conf: {conf})_")
                if conf is not None and float(conf) < 0.5:
                    st.caption("⚠️ Bassa confidenza")
                if exp:
                    st.caption(exp)

    # --- Certificati + evidence hash ---
    if passport.get("certificates"):
        st.subheader("📜 Certificati (verificabili)")
        for idx, cert in enumerate(passport["certificates"], start=1):
            st.markdown(f"**Certificato {idx}**")
            if isinstance(cert, dict) and cert.get("evidence"):
                ev = cert["evidence"]
                st.caption(f"Evidence ID: {ev.get('evidence_id')}")
                st.caption(f"Evidence hash: {str(ev.get('hash',''))[:16]}…")
            for k, v in (cert.items() if isinstance(cert, dict) else []):
                if k == "evidence":
                    continue
                if isinstance(v, dict):
                    st.write(f"- {k}: {v.get('value','')}")
                else:
                    st.write(f"- {k}: {v}")

    # --- Immagini ---
    if passport.get("images"):
        st.subheader("🖼️ Immagini")
        for img in passport.get("images", []):
            st.image(f"data:image/jpeg;base64,{img['file_base64']}", caption=img.get("caption", ""))

    st.divider()
    services.render_espr_compliance(passport)
    st.stop()

# ======================================================
# SELEZIONE TIPO PRODOTTO
# ======================================================
tipo = st.selectbox("Tipo prodotto", ["mobile", "lampada", "bicicletta"])
fields = list(services.PRODUCT_FIELDS.get(tipo, {}).get("pdf", []))

tabs = st.tabs(["📤 Upload & Analisi", "📝 Validazione", "🚀 Pubblica", "📚 Archivio"])

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
            st.stop()

        st.session_state.uploaded_pdf_bytes = pdf_file.read()
        st.session_state.uploaded_images_bytes = [i.read() for i in image_files]

        st.session_state.uploaded_cert_bytes = [c.read() for c in (cert_files or [])]
        st.session_state.uploaded_cert_names = [getattr(c, "name", f"cert_{i+1}") for i, c in enumerate(cert_files or [])]

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

    pdf_data = st.session_state.get("pdf_data")
    image_data = st.session_state.get("image_data")

    if pdf_data and image_data:

        # -------------------------------
        # PDF
        # -------------------------------
        st.subheader("Validazione PDF")

        validated_pdf = {}
        for k, v in pdf_data.items():
            validated_pdf[k] = {
                "value": st.text_input(
                    f"PDF · {k}",
                    v.get("value", ""),
                    help=v.get("explanation", ""),
                    key=f"pdf_{k}"
                ),
                "confidence": v.get("confidence", 0),
                "explanation": v.get("explanation", "")
            }

        st.session_state.validated_pdf = validated_pdf

        # -------------------------------
        # IMMAGINI
        # -------------------------------
        st.subheader("Validazione Immagini")

        validated_image = {}
        for k, v in image_data.items():
            validated_image[k] = {
                "value": st.text_input(
                    f"IMG · {k}",
                    v.get("value", ""),
                    help=v.get("explanation", ""),
                    key=f"img_{k}"
                ),
                "confidence": v.get("confidence", 0),
                "explanation": v.get("explanation", "")
            }

        st.session_state.validated_image = validated_image

        # -------------------------------
        # CERTIFICATI
        # -------------------------------
        cert_data = st.session_state.get("cert_data")

        if cert_data:
            st.subheader("Certificati")

            validated_certs = []

            for i, cert in enumerate(cert_data):
                st.markdown(f"**Certificato {i+1}**")
                row = {}

                for k, v in cert.items():
                    val = v.get("value", "") if isinstance(v, dict) else v

                    row[k] = {
                        "value": st.text_input(
                            f"CERT {i+1} · {k}",
                            val,
                            key=f"cert_{i}_{k}"
                        ),
                        "confidence": v.get("confidence", 0) if isinstance(v, dict) else 0,
                        "explanation": v.get("explanation", "") if isinstance(v, dict) else ""
                    }

                validated_certs.append(row)

            st.session_state.validated_cert = validated_certs

        st.success("Validazione pronta ✅")

    else:
        st.info("Esegui prima l’analisi")


# ======================================================
# POST-PUBBLICAZIONE + FIRMA
# ======================================================

pp = st.session_state.get("published_passport")

if pp:

    # -------------------------------
    # OUTPUT PUBBLICO
    # -------------------------------
    st.subheader("🌐 Passport pubblico")

    url = f"{st.secrets.get('APP_URL')}?passport_id={pp['id']}"
    st.code(url)

    try:
        qr_img = services.generate_qr_from_url(url)
        st.image(qr_img, caption="QR DPP")
    except Exception as e:
        st.warning(f"QR non generato: {e}")

    # -------------------------------
    # FIRMA SES (OTP)
    # -------------------------------
    if ENABLE_SES:
        st.divider()
        st.subheader("✍️ Firma elettronica semplice (OTP)")

        # Default valori
        st.session_state.setdefault("ses_name", "Nuvia")
        st.session_state.setdefault("ses_surname", "srls")
        st.session_state.setdefault("ses_email", "informazioni.nuvia@gmail.com")
        st.session_state.setdefault("ses_mobile", "+393296482656")

        with st.form("ses_form"):
            st.text_input("Nome", key="ses_name")
            st.text_input("Cognome", key="ses_surname")
            st.text_input("Email OTP", key="ses_email")
            st.text_input("Cellulare OTP", key="ses_mobile")
            submit = st.form_submit_button("Invia richiesta firma SES")

        # -------------------------------
        # INVIO FIRMA
        # -------------------------------
        if submit:
            with st.spinner("Invio richiesta firma SES..."):
                try:
                    services.sign_passport_pdf_ses_openapi(
                        pp,
                        signer_name=st.session_state["ses_name"],
                        signer_surname=st.session_state["ses_surname"],
                        signer_email=st.session_state["ses_email"],
                        signer_mobile=st.session_state["ses_mobile"]
                    )

                    services.save_passport_to_file(pp)
                    st.success("✅ Richiesta firma SES inviata")

                except Exception as e:
                    st.error(f"❌ Errore SES: {e}")

        # -------------------------------
        # LINK FIRMA
        # -------------------------------
        ses = pp.get("simple_signature") or {}
        urls = ses.get("signing_urls") or []

        if urls:
            st.markdown("### 🔗 Link firma")
            for u in urls:
                st.link_button("Vai alla firma", u)

        # -------------------------------
        # VERIFICA STATO
        # -------------------------------
        if ses and ses.get("request_id"):

            st.divider()

            if st.button("🔄 Verifica stato firma"):
                try:
                    status = services.openapi_get_signature_status(
                        bearer_token=st.secrets.get("OPENAPI_BEARER_PROD"),
                        signature_id=ses["request_id"]
                    )

                    ses["status"] = status["data"]["state"]
                    pp["simple_signature"] = ses

                    services.save_passport_to_file(pp)

                    st.info(f"Stato firma: {ses['status']}")

                except Exception as e:
                    st.error(f"Errore stato firma: {e}")

            # -------------------------------
            # DOWNLOAD PDF FIRMATO
            # -------------------------------
            if ses.get("status") == "SIGNED":
                try:
                    pdf_signed = services.openapi_download_signed_pdf(
                        bearer_token=st.secrets.get("OPENAPI_BEARER_PROD"),
                        signature_id=ses["request_id"]
                    )

                    st.download_button(
                        "⬇️ Scarica Passport firmato",
                        data=pdf_signed,
                        file_name=f"{pp['id']}_signed.pdf",
                        mime="application/pdf"
                    )

                except Exception as e:
                    st.error(f"Errore download PDF firmato: {e}")
# TAB 3 — PUBBLICA
# ======================================================
with tabs[2]:

    # --------------------------------------------------
    # Guard-rail: serve prima validazione completata
    # --------------------------------------------------
    if not (st.session_state.get("validated_pdf") and st.session_state.get("validated_image")):
        st.info("Completa prima la validazione")
        st.stop()

    # --------------------------------------------------
    # Feature flag
    # --------------------------------------------------
    ENABLE_QESEAL = False   # ✅ True solo con certificato QeSeal
    ENABLE_SES = True       # ✅ SES (OTP) – demo / prod light

    # --------------------------------------------------
    # PUBBLICAZIONE DPP
    # --------------------------------------------------
    if st.button("🚀 Pubblica Digital Product Passport"):

        # 1) CREAZIONE PASSPORT
        pid = f"{tipo.upper()}-{uuid.uuid4().hex[:6]}"
        passport = services.initialize_passport(pid, tipo, fields)

        # 2) URL pubblico + binding fisico-digitale
        url = f"{st.secrets['APP_URL']}?passport_id={pid}"
        services.set_physical_binding(
            passport,
            public_url=url,
            carrier="qr",
            location="product_label",
            tamper_risk="medium"
        )

        # 3) MERGE DATI VALIDATI
        if tipo == "mobile":
            services.merge_data_with_ecolabel(
                passport,
                pdf_file=BytesIO(st.session_state.uploaded_pdf_bytes),
                image_data=st.session_state.validated_image,
                cert_data=None,
                client=client
            )
        else:
            services.merge_data(
                passport,
                st.session_state.validated_pdf,
                st.session_state.validated_image,
                None
            )

        # 4) IMMAGINI
        for b in (st.session_state.uploaded_images_bytes or []):
            services.add_product_image(passport, BytesIO(b))

        # 5) CERTIFICATI + EVIDENZE
        if st.session_state.get("uploaded_cert_bytes") and st.session_state.get("validated_cert"):
            for i, raw in enumerate(st.session_state.uploaded_cert_bytes):
                parsed = (
                    st.session_state.validated_cert[i]
                    if i < len(st.session_state.validated_cert)
                    else {}
                )
                fname = (
                    st.session_state.uploaded_cert_names[i]
                    if st.session_state.get("uploaded_cert_names") and i < len(st.session_state.uploaded_cert_names)
                    else f"cert_{i+1}"
                )
                services.add_certificate_evidence(
                    passport,
                    cert_parsed=parsed,
                    raw_bytes=raw,
                    filename=fname,
                    source="uploaded_certificate"
                )

        # 6) VALIDAZIONE ESPR (BLOCCANTE)
        check = services.validate_espr_furniture(passport)

        if check.get("warnings"):
            st.warning("⚠️ Warning di qualità dati")
            for w in check["warnings"]:
                st.write(f"- {w}")


# ======================================================
# TAB 4 — ARCHIVIO
# ======================================================
with tabs[3]:
    st.header("📚 Archivio Passport")

    if not os.path.exists(services.EXCEL_FILE):
        st.info("Nessun file Excel trovato")
        st.stop()

    try:
        df_passport = pd.read_excel(services.EXCEL_FILE, sheet_name="passport").rename(columns=str.strip)
        df_fields = pd.read_excel(services.EXCEL_FILE, sheet_name="fields").rename(columns=str.strip)
        df_images = pd.read_excel(services.EXCEL_FILE, sheet_name="images").rename(columns=str.strip)

        if df_passport.empty:
            st.info("Nessun passport disponibile")
            st.stop()

        df_passport["version"] = pd.to_numeric(df_passport["version"], errors="coerce")
        df_latest = (
            df_passport.sort_values(["id", "version"])
            .groupby("id", as_index=False)
            .tail(1)
        )

        st.subheader("📊 Elenco Passport (ultima versione)")
        st.dataframe(df_latest, use_container_width=True)

        selected_id = st.selectbox("Seleziona Passport", df_latest["id"])
        if not selected_id:
            st.stop()

        passport = services.load_passport_from_file(selected_id)
        if not passport:
            st.error("Passport JSON non trovato")
            st.stop()

        st.subheader("🧾 Dettaglio Passport")
        st.json({
            "id": passport.get("id"),
            "type": passport.get("product_type"),
            "version": passport.get("version"),
            "lifecycle": (passport.get("lifecycle") or {}).get("status"),
            "hash": (passport.get("digital_signature") or {}).get("hash"),
            "seal_id": (passport.get("qualified_seal") or {}).get("seal_id"),
            "seal_state": (passport.get("qualified_seal") or {}).get("state"),
            "evidences": len(passport.get("evidences", [])),
        })

        st.subheader("🧩 Campi (tutte le sezioni)")
        st.dataframe(df_fields[df_fields["passport_id"] == selected_id], use_container_width=True)

        st.subheader("🖼️ Immagini prodotto")
        imgs = df_images[df_images["passport_id"] == selected_id]
        if imgs.empty:
            st.info("Nessuna immagine associata")
        else:
            for _, row in imgs.iterrows():
                st.image(f"data:image/jpeg;base64,{row['file_base64']}", caption=row.get("caption", ""))

    except Exception as e:
        st.error(f"Errore archivio: {e}")
