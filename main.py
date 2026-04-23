import streamlit as st
import uuid
import base64
import os
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

def compute_section_confidence(section: dict) -> float:
    vals = [
        v.get("confidence", 0)
        for v in section.values()
        if isinstance(v, dict)
    ]
    return round(sum(vals) / len(vals), 2) if vals else 0.0

def apply_mixed_confidence(validated: dict, extracted: dict):
    for k, v in validated.items():
        orig = (extracted.get(k) or {}).get("value", "")
        if not v.get("value"):
            continue
        v["confidence"] = 1.0 if v["value"] != orig else 0.8

def render_data_quality(passport: dict):
    st.subheader("📊 Qualità dei dati")

    pdf_section = (passport.get("sections", {}) or {}).get("PDF", {}) or {}
    img_section = (passport.get("sections", {}) or {}).get("Images", {}) or {}

    pdf_conf = compute_section_confidence(pdf_section)
    img_conf = compute_section_confidence(img_section)

    # media robusta: considera solo le sezioni presenti
    confs = []
    if pdf_section:
        confs.append(pdf_conf)
    if img_section:
        confs.append(img_conf)

    overall = round(sum(confs) / len(confs), 2) if confs else 0.0

    c1, c2, c3 = st.columns(3)
    c1.metric("PDF", f"{int(pdf_conf*100)}%")
    c2.metric("Immagini", f"{int(img_conf*100)}%")
    c3.metric("OVERALL", f"{int(overall*100)}%")
    
def render_dpp_status_bar(passport: dict):
    """
    Barra di stato DPP sempre visibile (audit-ready).
    """
    status = (passport.get("lifecycle") or {}).get("status", "draft")

    STATUS_MAP = {
        "draft": ("📝", "DRAFT", "#6c757d"),
        "validated": ("✅", "VALIDATED", "#0d6efd"),
        "published": ("🚀", "PUBLISHED", "#fd7e14"),
        "signed": ("✍️", "SIGNED (SES)", "#198754"),
        "sealed": ("🔐", "SEALED (QeSeal)", "#14532d"),
        "updated": ("🔄", "UPDATED", "#6f42c1"),
        "withdrawn": ("⛔", "WITHDRAWN", "#dc3545"),
        "certified": ("📜", "CERTIFIED", "#20c997"),
        "end_of_life": ("🏁", "END OF LIFE", "#343a40")

    }

    icon, label, color = STATUS_MAP.get(
        status,
        ("❓", status.upper(), "#6c757d")
    )

    st.markdown(
        f"""
<div style="
    padding:12px;
    border-radius:8px;
    background-color:{color};
    color:white;
    font-weight:700;
    font-size:18px;
    text-align:center;
    margin-bottom:15px">
    {icon} DPP STATUS — {label}
</div>
""",
        unsafe_allow_html=True,
    )
def render_espr_validation(passport: dict):
    """
    Render leggibile della validazione ESPR.
    Pensata per utenti NON tecnici (audit / compliance).
    """
    v = passport.get("espr_validation") or {}

    st.subheader("🛡️ Conformità ESPR")

    # -----------------------------    # -----------------------------
    if v.get("missing_fields"):
        st.error("### ❌ Campi obbligatori mancanti")
        for f in v["missing_fields"]:
            st.write(f"- {f}")

    if v.get("missing_blocks"):
        st.error("### ❌ Blocchi mancanti")
        for b in v["missing_blocks"]:
            st.write(f"- {b}")

    if v.get("warnings"):
        st.warning("### ⚠️ Warning")
        for w in v["warnings"]:
            st.write(f"- {w}")

    if v.get("is_compliant"):
        st.success("✅ DPP conforme ai requisiti ESPR ESSENTIAL")
    # KPI summary (semaforo)
    # -----------------------------
    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Mandatory fields",
        "❌" if v.get("missing_fields") else "✅",
        f"{len(v.get('missing_fields', []))} mancanti"
    )

    c2.metric(
        "Blocchi strutturali",
        "❌" if v.get("missing_blocks") else "✅",
        f"{len(v.get('missing_blocks', []))} mancanti"
    )

    c3.metric(
        "Warning",
        "⚠️" if v.get("warnings") else "✅",
        f"{len(v.get('warnings', []))}"
    )

    st.divider()




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
    "uploaded_cert_names": None,
    "pdf_data": None,
    "image_data": None,
    "cert_data": None,
    "validated_pdf": None,
    "validated_image": None,
    "validated_cert": None,
    "published_passport": None,
    "selected_passport": None,
}
for k, v in DEFAULT_STATE.items():
    st.session_state.setdefault(k, v)

# ======================================================
# PUBLIC VIEW (?passport_id=...)
# ======================================================
passport_id = st.query_params.get("passport_id")
if passport_id:
    # DB-first (wrapper), fallback file se DB non ha ancora quel record
    passport = services.load_passport(passport_id)
    if not passport:
        st.error("Passport non trovato")
        st.stop()
render_dpp_status_bar(passport)
    st.title("🇪🇺 Digital Product Passport — Public View")

    # ======================================================
    # METADATA PRINCIPALI
    # ======================================================
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

    # ======================================================
    # FIRME / SIGILLI
    # ======================================================
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
        st.info("🔐 Firma elettronica certificata presente")

    # ======================================================
    # LEGAME FISICO-DIGITALE
    # ======================================================
    if passport.get("physical_binding"):
        pb = passport["physical_binding"]
        st.subheader("🔗 Legame fisico‑digitale")
        st.write(f"Carrier: {pb.get('carrier')}")
        st.write(f"Location: {pb.get('location')}")
        st.write(f"URL: {pb.get('public_url')}")
        st.write(f"Tamper risk: {pb.get('tamper_risk')}")

    # ======================================================
    # SEZIONI DPP
    # ======================================================
    st.subheader("🧩 Contenuti del DPP")

    st.markdown("### 📄 Sezione PDF")
    for fname, f in (passport.get("sections", {}).get("PDF", {}) or {}).items():
        val = f.get("value") if isinstance(f, dict) else f
        conf = f.get("confidence") if isinstance(f, dict) else None
        exp = f.get("explanation") if isinstance(f, dict) else ""
        st.write(f"**{fname}**: {val} _(conf: {conf})_")
        if conf is not None and float(conf) < 0.5:
            st.caption("⚠️ Bassa confidenza")
        if exp:
            st.caption(exp)

    if passport.get("sections", {}).get("Images"):
        st.markdown("### 🖼️ Immagini (estratte)")
        for k, v in passport["sections"]["Images"].items():
            st.write(f"**{k}**: {v.get('value')}")
            st.caption(v.get("explanation", ""))

    if passport.get("certificates"):
        st.markdown("### 📜 Certificati")
        for idx, cert in enumerate(passport["certificates"], start=1):
            st.markdown(f"**Certificato {idx}**")
            for k, v in cert.items():
                if k == "evidence":
                    ev = v
                    st.caption(f"Evidence ID: {ev.get('evidence_id')}")
                    st.caption(f"Evidence hash: {str(ev.get('hash',''))[:16]}…")
                    continue
                if isinstance(v, dict):
                    st.write(f"- {k}: {v.get('value')}")
                else:
                    st.write(f"- {k}: {v}")

    # ======================================================
    # MODULI ESPR (se presenti)
    # ======================================================
    st.divider()
    st.subheader("🧠 Moduli ESPR")

    st.markdown("### 📘 JSON‑LD")
    st.json(passport.get("jsonld"))

    st.markdown("### 📚 Ontologia ESPR")
    st.json(passport.get("ontology"))

    st.markdown("### ⚡ EPREL")
    st.json(passport.get("eprel"))

    st.markdown("### 🔗 GS1 Digital Link")
    st.write(passport.get("gs1_digital_link") or "Nessun GTIN disponibile")

    st.markdown("### 🧪 SCIP / ECHA")
    st.json(passport.get("scip"))

    st.markdown("### 📑 Sezioni standard ESPR")
    st.json(passport.get("espr_sections"))

    st.markdown("### 🛡️ Validazione ESPR")
    st.json(passport.get("espr_validation"))

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
        st.session_state.uploaded_cert_names = [
            getattr(c, "name", f"cert_{i+1}") for i, c in enumerate(cert_files or [])
        ]

        with st.spinner("Analisi in corso..."):
            pdf_text = services.extract_text_from_pdf(BytesIO(st.session_state.uploaded_pdf_bytes))
            st.session_state.pdf_data = services.gpt_extract_from_pdf(pdf_text, client, tipo, fields)

            # Normalizza PEF fields se la funzione esiste nel tuo services
            if hasattr(services, "normalize_pdf_fields"):
                st.session_state.pdf_data = services.normalize_pdf_fields(st.session_state.pdf_data)

            img_data = {}
            for b in st.session_state.uploaded_images_bytes:
                img_data.update(services.gpt_analyze_image(BytesIO(b), client, tipo))
            st.session_state.image_data = img_data

            cert_list = []
            for b in st.session_state.uploaded_cert_bytes:
                # nome funzione nel tuo services.py: gpt_extract_cert_info
                cert_list.append(services.gpt_extract_cert_info(BytesIO(b), client))
            st.session_state.cert_data = cert_list

        st.success("Analisi completata ✅")

# ======================================================
# TAB 2 — VALIDAZIONE
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data and st.session_state.image_data:
        # ----------------------------
        # VALIDAZIONE PDF
        # ----------------------------
        st.subheader("Validazione PDF")
        validated_pdf = {}
        for k, v in st.session_state.pdf_data.items():
            original_val = v.get("value", "") if isinstance(v, dict) else str(v)
            user_val = st.text_input(
                f"PDF · {k}",
                value=original_val,
                help=(v.get("explanation", "") if isinstance(v, dict) else ""),
                key=f"pdf_{k}"
            )
            validated_pdf[k] = {
                "value": user_val,
                "confidence": 1.0 if user_val != original_val else (v.get("confidence", 0) if isinstance(v, dict) else 0),
                "explanation": (v.get("explanation", "") if isinstance(v, dict) else "")
            }
        st.session_state.validated_pdf = validated_pdf

        # ----------------------------
        # VALIDAZIONE IMMAGINI
        # ----------------------------
        st.subheader("Validazione Immagini")
        validated_image = {}
        for k, v in st.session_state.image_data.items():
            original_val = v.get("value", "") if isinstance(v, dict) else str(v)
            user_val = st.text_input(
                f"IMG · {k}",
                value=original_val,
                help=(v.get("explanation", "") if isinstance(v, dict) else ""),
                key=f"img_{k}"
            )
            validated_image[k] = {
                "value": user_val,
                "confidence": 1.0 if user_val != original_val else (v.get("confidence", 0) if isinstance(v, dict) else 0),
                "explanation": (v.get("explanation", "") if isinstance(v, dict) else "")
            }
        st.session_state.validated_image = validated_image

        # ----------------------------
        # VALIDAZIONE CERTIFICATI
        # ----------------------------
        if st.session_state.cert_data:
            st.subheader("Certificati")
            validated_cert = []
            for i, cert in enumerate(st.session_state.cert_data):
                st.markdown(f"**Certificato {i+1}**")
                row = {}
                for k, v in (cert or {}).items():
                    original_val = v.get("value", "") if isinstance(v, dict) else str(v)
                    user_val = st.text_input(
                        f"CERT {i+1} · {k}",
                        value=original_val,
                        key=f"cert_{i}_{k}"
                    )
                    row[k] = {
                        "value": user_val,
                        "confidence": 1.0 if user_val != original_val else (v.get("confidence", 0) if isinstance(v, dict) else 0),
                        "explanation": (v.get("explanation", "") if isinstance(v, dict) else "")
                    }
                validated_cert.append(row)
            st.session_state.validated_cert = validated_cert

        st.success("Validazione pronta ✅")
    else:
        st.info("Esegui prima l’analisi")

# ======================================================
# TAB 3 — PUBBLICA
# ======================================================
with tabs[2]:
    if not (st.session_state.get("validated_pdf") and st.session_state.get("validated_image")):
        st.info("Completa prima la validazione")
        st.stop()

    ENABLE_QESEAL = False
    ENABLE_SES = True
    if st.button("🚀 Finalizza e pubblica DPP"):
        apply_mixed_confidence(st.session_state.validated_pdf, st.session_state.pdf_data)
        apply_mixed_confidence(st.session_state.validated_image,st.session_state.image_data)
    
        # 1) CREA PASSPORT
        pid = f"{tipo.upper()}-{uuid.uuid4().hex[:6]}"
        passport = services.initialize_passport(pid, tipo, fields)
    
        # 2) URL    # 2) URL pubblico + binding
        url = f"{st.secrets['APP_URL']}?passport_id={pid}"
        if hasattr(services, "set_physical_binding"):
            services.set_physical_binding(
                passport,
                public_url=url,
                carrier="qr",
                location="product_label",
                tamper_risk="medium"
            )
    
        # 3) MERGE DATI
        if tipo == "mobile" and hasattr(services, "merge_data_with_ecolabel"):
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
        
        render_dpp_status_bar(passport)
        render_data_quality(passport)
        render_espr_validation(passport)

        # 4) PEF
        if hasattr(services, "compute_pef_score"):
            services.compute_pef_score(passport)      
    
    
        if hasattr(services, "missing_pef_fields"):
            missing_pef = services.missing_pef_fields(passport)
            if missing_pef:
                st.warning("⚠️ Campi mancanti per il calcolo PEF")
                for m in missing_pef:
                    st.write(f"- {m}")

        # 4) IMMAGINI
        for b in (st.session_state.uploaded_images_bytes or []):
            services.add_product_image(passport, BytesIO(b))

        # 5) CERTIFICATI + EVIDENCE (se presente la funzione)
        if hasattr(services, "add_certificate_evidence"):
            if st.session_state.get("uploaded_cert_bytes") and st.session_state.get("validated_cert"):
                for i, raw in enumerate(st.session_state.uploaded_cert_bytes):
                    parsed = st.session_state.validated_cert[i] if i < len(st.session_state.validated_cert) else {}
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

        # 6) VALIDAZIONE ESPR (se presente)
        if hasattr(services, "validate_espr_furniture"):
            check = services.validate_espr_furniture(passport)
            passport["espr_validation"] = check
            render_espr_validation(passport)
            if check.get("warnings"):
                st.warning("⚠️ Warning di qualità dati")
                for w in check["warnings"]:
                    st.write(f"- {w}")

            if not check.get("is_compliant", False):
                st.error("❌ DPP NON conforme ai requisiti ESSENTIAL")
                if check.get("missing_fields"):
                    st.write("### Campi mancanti")
                    for f in check["missing_fields"]:
                        st.write(f"- {f}")
                if check.get("missing_blocks"):
                    st.write("### Blocchi mancanti")
                    for b in check["missing_blocks"]:
                        st.write(f"- {b}")
                st.stop()

        # 7) FINALIZZAZIONE ESPR + moduli
        services.espr_stamp(
            passport,
            actor="manufacturer",
            action="finalize",
            reason="Final publication (ESPR compliant)"
        )
        if hasattr(services, "integrate_espr_modules"):
            services.integrate_espr_modules(passport)

        # 8) QeSeal (opzionale)
        qeseal_ok = False
        if ENABLE_QESEAL and hasattr(services, "seal_passport_pdf_qeseal_openapi"):
            with st.spinner("Applico QeSeal..."):
                try:
                    services.seal_passport_pdf_qeseal_openapi(passport)
                    qeseal_ok = True
                except Exception as e:
                    st.warning(f"⚠️ QeSeal non applicato: {e}")

        # 9) GENERA PDF UFFICIALE multipagina (se presenti funzioni)
        public_url = f"{st.secrets['APP_URL']}?passport_id={passport['id']}"
        st.info("Generazione PDF ufficiale del DPP in corso...")

        if hasattr(services, "generate_qr_from_url") and hasattr(services, "generate_passport_html") and hasattr(services, "generate_pdf_from_html"):
            qr_buf = services.generate_qr_from_url(public_url)
            qr_base64 = base64.b64encode(qr_buf.getvalue()).decode()
            html = services.generate_passport_html(passport, qr_base64=qr_base64)
            pdf_bytes = services.generate_pdf_from_html(html)
            passport["pdf_document"] = base64.b64encode(pdf_bytes).decode()

        # 10) SALVA SU DB (Passport Registry) — append-only
        services.persist_passport(passport, actor="manufacturer", reason="publish_final")
        services.save_passport_to_excel_append(passport)
        st.session_state["published_passport"] = passport

        if qeseal_ok:
            st.success("✅ DPP pubblicato e sigillato (QeSeal)")
        else:
            st.success("✅ DPP pubblicato")

    # --------------------------------------------------
    # Output + breakdown (se presente)
    # --------------------------------------------------
    pp = st.session_state.get("published_passport")
    if pp:
        render_dpp_status_bar(pp)
        breakdown = pp.get("sustainability_breakdown") or {}
        if breakdown:
            st.subheader("🔍 Breakdown PEF")
            for k, v in breakdown.items():
                st.write(f"**{k}**: {v}")

    # --------------------------------------------------
    # Firma elettronica semplice (SES) (se attiva)
    # --------------------------------------------------
    if ENABLE_SES:
        st.divider()
        st.subheader("✍️ Firma DPP")

        if not pp:
            st.info("Pubblica prima il DPP per poter avviare la firma.")
            st.stop()

        st.session_state.setdefault("ses_name", "Nuvia")
        st.session_state.setdefault("ses_surname", "srls")
        st.session_state.setdefault("ses_email", "informazioni.nuvia@gmail.com")
        st.session_state.setdefault("ses_mobile", "+393296482656")
        st.session_state.setdefault("ses_channel", "email")
        st.session_state.setdefault("ses_mode", "typed")
        st.session_state.setdefault("ses_allow_edit", False)

        with st.form("ses_form", clear_on_submit=False):
            col1, col2 = st.columns(2)
            with col1:
                st.text_input("Nome firmatario", key="ses_name")
                st.text_input("Cognome firmatario", key="ses_surname")
                st.text_input("Email OTP", key="ses_email")
            with col2:
                st.text_input("Cellulare OTP", key="ses_mobile")
                st.selectbox("Canale OTP", ["email", "sms"], key="ses_channel")
                st.selectbox("Modalità firma", ["typed", "drawn"], key="ses_mode")

            st.checkbox(
                "Consenti al firmatario di modificare nome/email/cellulare",
                key="ses_allow_edit"
            )

            submit_ses = st.form_submit_button("Invia richiesta firma SES")

        if submit_ses:
            with st.spinner("Invio richiesta di firma SES..."):
                try:
                    # la tua funzione SES deve esistere in services.py
                    services.sign_passport_pdf_ses_openapi(
                        pp,
                        signer_name=st.session_state["ses_name"],
                        signer_surname=st.session_state["ses_surname"],
                        signer_email=st.session_state["ses_email"],
                        signer_mobile=st.session_state["ses_mobile"]
                    )

                    services.espr_stamp(
                        pp,
                        actor="manufacturer",
                        action="request_ses_signature",
                        reason="Requested SES (OTP) signature"
                    )

                    services.persist_passport(pp, actor="manufacturer", reason="ses_requested")
                    st.session_state["published_passport"] = pp

                    st.success("✅ Richiesta SES inviata")
                except Exception as e:
                    st.error(f"❌ Errore SES: {e}")
                    st.stop()

        signing_urls = (pp.get("simple_signature") or {}).get("signing_urls") or []
        signing_urls = [u for u in signing_urls if u]
        if signing_urls:
            st.markdown("### 🔗 Link firma")
            for u in signing_urls:
                st.write(u)
        elif pp.get("simple_signature"):
            with st.expander("Debug risposta SES"):
                st.json(pp["simple_signature"].get("raw_response", {}))

# ======================================================
# TAB 4 — ARCHIVIO (POSTGRES / SUPABASE)
# ======================================================
with tabs[3]:
    st.header("📚 Passport Registry")

    # --------------------------------------------------
    # DB-first archive
    # --------------------------------------------------
    if services.db_enabled():
        st.sidebar.subheader("🔎 Filtri avanzati")

        f_search = st.sidebar.text_input("Cerca (ID, tipo, produttore)", key="arch_search")
        f_type = st.sidebar.selectbox("Tipo prodotto", ["ALL", "mobile", "lampada", "bicicletta"], key="arch_type")
        f_lifecycle = st.sidebar.selectbox(
            "Lifecycle",
            ["ALL", "draft", "updated", "signed", "certified", "withdrawn", "end_of_life"],
            key="arch_lifecycle"
        )
        f_version = st.sidebar.slider("Versione minima", 1, 50, 1, key="arch_ver")
        f_has_pdf = st.sidebar.checkbox("Solo con PDF generato", key="arch_pdf")
        f_has_cert = st.sidebar.checkbox("Solo con certificazioni", key="arch_cert")

        sort_options = {
                "Aggiornamento (recenti ↓)": ("updated_at", False),
                "Aggiornamento (vecchi ↑)": ("updated_at", True),
                "Creazione (recenti ↓)": ("created_at", False),
                "Creazione (vecchi ↑)": ("created_at", True),
                "Versione (alta ↓)": ("version", False),
                "Versione (bassa ↑)": ("version", True)
            }

        sort_choice = st.selectbox("Ordina per", list(sort_options.keys()), key="arch_sort")
        sort_col, sort_asc = sort_options[sort_choice]

        df_view = services.db_list_passports_latest(
            search=f_search,
            product_type=f_type,
            lifecycle=f_lifecycle,
            min_version=f_version,
            has_pdf=f_has_pdf,
            has_cert=f_has_cert,
            sort_col=sort_col,
            sort_asc=sort_asc
        )

        if df_view.empty:
            st.warning("Nessun passport trovato con i filtri correnti")
            st.stop()

        st.subheader("📊 Statistiche archivio")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Totale Passport", len(df_view))
        c2.metric("Con certificazioni", int((df_view["cert_count"] > 0).sum()))
        c3.metric("Con PDF", int(df_view["pdf_present"].sum()))
        c4.metric("Versione massima", int(df_view["version"].max()))

        st.divider()

        st.subheader("📤 Esporta archivio filtrato")
        csv_buf = df_view.to_csv(index=False).encode("utf-8")
        st.download_button("Scarica CSV", csv_buf, "passport_registry_filtered.csv", "text/csv")

        st.divider()

        st.subheader("📦 Passports")
        for _, row in df_view.iterrows():
            pid = row["id"]
            st.markdown(f"### {pid}")

            a1, a2, a3, a4 = st.columns([2, 1, 1, 2])
            a1.write(f"Tipo: {row.get('product_type', '-')}")
            a2.write(f"v{row.get('version', '-')}")
            a3.write(f"Lifecycle: {row.get('lifecycle', '-')}")

            open_col, pdf_col = a4.columns(2)

            if open_col.button("🔍 Apri", key=f"open_{pid}"):
                st.query_params["passport_id"] = pid
                st.rerun()

            if pdf_col.button("📄 PDF", key=f"pdf_{pid}"):
                passport = services.load_passport(pid)
                if passport and passport.get("pdf_document"):
                    pdf_bytes = base64.b64decode(passport["pdf_document"])
                    st.download_button(
                        label=f"Scarica {pid}.pdf",
                        data=pdf_bytes,
                        file_name=f"{pid}.pdf",
                        mime="application/pdf",
                        key=f"dl_{pid}"
                    )
                else:
                    st.warning("PDF non disponibile")

            st.divider()

        st.subheader("🔎 Dettaglio Passport")
        selected_id = st.session_state.get("selected_passport") or df_view.iloc[0]["id"]
        st.session_state["selected_passport"] = selected_id
        passport = services.load_passport(selected_id)
        
        render_dpp_status_bar(passport)
        if not passport:
            st.error("Passport non trovato")
            st.stop()

        st.markdown(f"## 📦 {passport.get('id')}")
        d1, d2, d3 = st.columns(3)
        d1.metric("Versione", passport.get("version"))
        d2.metric("Tipo", passport.get("product_type"))
        d3.metric("Lifecycle", (passport.get("lifecycle") or {}).get("status", "unknown"))
        
        st.divider()
        st.subheader("🔍 Confronto tra le versioni del DPP")
        
        # Se non esiste l’Excel, niente diff
        if not os.path.exists(services.EXCEL_FILE):
            st.info("Impossibile effettuare confronto.")
        else:
            try:
                df_p = pd.read_excel(services.EXCEL_FILE, sheet_name="passport").rename(columns=str.strip)
                df_f = pd.read_excel(services.EXCEL_FILE, sheet_name="fields").rename(columns=str.strip)
        
                # versioni disponibili per questo passport
                df_p = df_p[df_p["id"].astype(str).str.strip() == str(selected_id).strip()].copy()
                df_p["version"] = pd.to_numeric(df_p["version"], errors="coerce")
                versions = sorted(df_p["version"].dropna().unique().tolist())
        
                if len(versions) < 2:
                    st.info("Prima versione del DPP")
                else:
                    v_new_default = int(max(versions))
                    v_old_default = int(versions[-2])
        
                    cL, cR = st.columns(2)
                    with cL:
                        v_old = st.selectbox("Versione PRECEDENTE", versions, index=versions.index(v_old_default), key=f"diff_old_{selected_id}")
                    with cR:
                        v_new = st.selectbox("Versione CORRENTE", versions, index=versions.index(v_new_default), key=f"diff_new_{selected_id}")
        
                    if int(v_old) == int(v_new):
                        st.warning("Seleziona due versioni diverse per vedere le differenze.")
                    else:
                        diff_df = services.compute_diff_fields(selected_id, int(v_old), int(v_new))
        
                        if diff_df.empty:
                            st.success("✅ Nessuna differenza sui campi")
                        else:
                            st.caption(f"Campi cambiati: {len(diff_df)}")
                            st.dataframe(diff_df, use_container_width=True, hide_index=True)
        
            except Exception as e:
                st.error(f"Errore lettura Excel per diff: {e}")
        
        t1, t2, t3, t4 = st.tabs(["Overview", "Security", "Fields", "Media"])
        with t1:
            st.write("### Evidences")
            st.json(passport.get("evidences", []))
        with t2:
            st.write("### Digital Signature")
            st.json(passport.get("digital_signature"))
            st.write("### Qualified Seal")
            st.json(passport.get("qualified_seal"))
        with t3:
            st.json(passport.get("sections", {}))
        with t4:
            imgs = passport.get("images", [])
            if not imgs:
                st.info("Nessun media")
            else:
                cols = st.columns(5)
                for i, img in enumerate(imgs):
                    with cols[i % 5]:
                        st.image(
                            f"data:image/jpeg;base64,{img.get('file_base64','')}",
                            caption=img.get("caption", ""),
                            use_container_width=True
                        )

    # --------------------------------------------------
    # Fallback legacy (se DB non configurato)
    # --------------------------------------------------
    else:
        st.warning("DB non configurato: archivio legacy su Excel/file (fallback).")

        if not os.path.exists(services.EXCEL_FILE):
            st.error("Excel storage non disponibile")
            st.stop()

        @st.cache_data(show_spinner=False)
        def load_data(path):
            df_passport = pd.read_excel(path, sheet_name="passport").rename(columns=str.strip)
            df_fields = pd.read_excel(path, sheet_name="fields").rename(columns=str.strip)
            df_images = pd.read_excel(path, sheet_name="images").rename(columns=str.strip)
            return df_passport, df_fields, df_images

        df_passport, df_fields, df_images = load_data(services.EXCEL_FILE)

        if df_passport.empty:
            st.warning("Nessun passport presente")
            st.stop()

        df_passport["version"] = pd.to_numeric(df_passport["version"], errors="coerce")
        df_latest = (
            df_passport.sort_values(["id", "version"])
            .groupby("id", as_index=False)
            .tail(1)
            .reset_index(drop=True)
        )

        st.dataframe(df_latest, use_container_width=True)
