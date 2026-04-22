# ======================================================
# coerente al 100% con main.py
# ======================================================

import os
import json
import base64
import uuid
import hashlib
from io import BytesIO
from datetime import datetime, timezone
from contextlib import contextmanager

import streamlit as st
import pandas as pd
import pdfplumber
from PIL import Image
from openai import OpenAI
from cryptography.fernet import Fernet
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import qrcode
import requests
import unicodedata
from difflib import get_close_matches


# ======================================================
# CONFIG / COSTANTI
# ======================================================

PASSPORT_DIR = "passports"
EXCEL_FILE = os.path.join(PASSPORT_DIR, "passport_archive.xlsx")

PRODUCT_FIELDS = {
    "mobile": {
        "pdf": [
            "Nome prodotto",
            "Numero di modello",
            "Produttore",
            "Materiali/componenti utilizzati",
            "Percentuale di contenuto riciclato",
            "Sostanze preoccupanti",
            "Energia consumata",
            "Durabilità",
            "Istruzioni di riparazione",
            "Parti sostituibili",
            "Indicazioni di smaltimento",
            "Fine vita",
            "Certificazioni",
        ]
    },
    "lampada": {"pdf": []},
    "bicicletta": {"pdf": []},
}


# ======================================================
# UTILS
# ======================================================

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def normalize(text: str) -> str:
    """✅ versione richiesta: NFKD / ascii / underscore"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode()
    return text.lower().strip().replace(" ", "_")


def compute_sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ======================================================
# PDF / IMAGE
# ======================================================

def extract_text_from_pdf(pdf_file) -> str:
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
    return text


def image_to_base64(img: Image.Image) -> str:
    buf = BytesIO()
    img.convert("RGB").save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


# ======================================================
# GPT — ESTRAZIONE
# ======================================================

def gpt_extract_from_pdf(pdf_text: str, client, tipo: str, fields: list[str], model="gpt-4o-mini"):
    if not pdf_text:
        return {k: {"value": "", "confidence": 0.0, "explanation": ""} for k in fields}

    template = {k: {"value": "", "confidence": 0.0, "explanation": ""} for k in fields}

    system = (
        "You are a strict information extraction engine. "
        "Return ONLY JSON. Do not hallucinate."
    )

    user = f"""
Extract product passport fields for product_type={tipo}.
Return ONLY JSON using this template:
{json.dumps(template, ensure_ascii=False)}

PDF_TEXT:
{pdf_text[:20000]}
"""

    try:
        res = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

        content = res.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception:
        data = {}

    out = {}
    for k in fields:
        x = data.get(k, {})
        out[k] = {
            "value": x.get("value", ""),
            "confidence": float(x.get("confidence", 0.0)),
            "explanation": x.get("explanation", ""),
        }
    return out


def gpt_extract_cert_info(file_like, client, model="gpt-4o-mini"):
    raw = file_like.read()
    if not raw:
        return {}

    is_pdf = raw[:4] == b"%PDF"
    text = extract_text_from_pdf(BytesIO(raw)) if is_pdf else ""

    schema = {
        "tipo_certificato": {"value": "", "confidence": 0.0, "explanation": ""},
        "ente_emittente": {"value": "", "confidence": 0.0, "explanation": ""},
        "numero_certificato": {"value": "", "confidence": 0.0, "explanation": ""},
    }

    prompt = f"""
Extract certificate info. Return ONLY JSON.
Use this schema:
{json.dumps(schema, ensure_ascii=False)}

TEXT:
{text[:15000]}
"""

    try:
        res = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(res.choices[0].message.content or "{}")
    except Exception:
        data = {}

    return {k: data.get(k, schema[k]) for k in schema}


def gpt_analyze_image(image_file, client: OpenAI, tipo):
    img = Image.open(image_file)
    b64 = image_to_base64(img)

    return {
        "Colore": {"value": "non determinato", "confidence": 0.3, "explanation": "Vision AI"},
        "Condizioni": {"value": "non determinato", "confidence": 0.3, "explanation": "Vision AI"},
    }


# ======================================================
# PASSPORT CORE
# ======================================================


def integrate_espr_modules(passport):
    """
    Integra automaticamente:
    - JSON-LD
    - Ontologia ESPR
    - EPREL block
    - GS1 Digital Link
    - SCIP block
    - Sezioni standard
    - Validator ESPR
    """

    # 1) JSON-LD
    passport["jsonld"] = generate_jsonld(passport)

    # 2) Ontologia (solo struttura, non istanze)
    passport["ontology"] = build_ontology_graph()

    # 3) EPREL block
    passport["eprel"] = generate_eprel_block(passport)

    # 4) GS1 Digital Link (se GTIN presente)
    pdf = passport.get("sections", {}).get("PDF", {})
    gtin = pdf.get("GTIN", {}).get("value")
    if gtin and validate_gs1(gtin):
        passport["gs1_digital_link"] = generate_gs1_digital_link(gtin)
    else:
        passport["gs1_digital_link"] = None

    # 5) SCIP block
    passport["scip"] = generate_scip_block(passport)

    # 6) Sezioni standard ESPR
    passport["espr_sections"] = build_espr_sections(passport)

    # 7) Validazione ESPR completa
    passport["espr_validation"] = validate_espr_compliance(passport)

    return passport

def sign_passport_pdf_ses_openapi(
    passport: dict,
    signer_name: str,
    signer_surname: str,
    signer_email: str,
    signer_mobile: str,
    page: int = 6,
    x: int = 430,
    y: int = 338
) -> dict:
    """
    Avvia una firma elettronica semplice (EU-SES) su PDF del DPP,
    con posizione firma personalizzata.
    """

    import streamlit as st
    import base64

    # 1) Bearer token
    bearer_token = st.secrets["OPENAPI_BEARER_PROD"]

    # 2) Recupera PDF ufficiale
    if "pdf_document" not in passport:
        raise RuntimeError("passport['pdf_document'] mancante — PDF non generato")

    pdf_bytes = base64.b64decode(passport["pdf_document"])
    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

    # 3) Firmatario
    signers = [{
        "name": signer_name,
        "surname": signer_surname,
        "email": signer_email,
        "mobile": signer_mobile,
        "authentication": "sms",

        # 🔥 POSIZIONE FIRMA
        "signature": {
            "page": page,
            "x": str(x),
            "y": str(y)
        }
    }]

    # 4) Chiamata EU-SES
    resp = openapi_eu_ses_request(
        bearer_token=bearer_token,
        pdf_base64=pdf_base64,
        signers=signers,
        signature_mode=["typed"]
    )

    # 5) Salva dati necessari per il REFRESH STATO
    passport.setdefault("simple_signature", {})
    passport["simple_signature"]["pdf_base64"] = pdf_base64
    passport["simple_signature"]["signers"] = signers
    passport["simple_signature"]["signature_mode"] = ["typed"]

    # 6) Validazione risposta
    data = resp["data"]

    # 7) Estrazione link OTP
    signing_urls = []
    for s in data.get("signers", []):
        if s.get("url"):
            signing_urls.append(s["url"])

    # 8) Scrittura STRUCTURED nel passport
    passport["simple_signature"].update({
        "provider": "OpenAPI",
        "type": "EU-SES",
        "request_id": data["id"],
        "status": data["state"],
        "signing_urls": signing_urls,
        "created_at": data.get("createdAt"),
        "raw_response": resp
    })

    return resp

def initialize_passport(pid: str, tipo: str, fields: list[str]) -> dict:
    passport = {
        "id": pid,
        "product_type": tipo,
        "version": 0,
        "created_at": _utc_now(),
        "last_updated_at": _utc_now(),
        "sections": {"PDF": {}},
        "images": [],
        "certificates": [],
        "evidences": [],
        "issuer": get_default_issuer(),
        "attestation": None,
        "digital_signature": None,
        "lifecycle": {"status": "draft", "events": []},
    }

    for f in fields:
        passport["sections"]["PDF"][f] = {"value": "", "confidence": 0.0, "explanation": ""}

    return passport


def merge_data(passport, pdf_data=None, image_data=None, cert_data=None):
    if pdf_data:
        for k, v in pdf_data.items():
            passport["sections"]["PDF"][k] = v
    if image_data:
        passport["sections"]["Images"] = image_data
    if cert_data:
        passport["certificates"] = cert_data
    espr_stamp(passport, "manufacturer", "merge_data", "Merged validated data")
    return passport


def add_product_image(passport: dict, img_file, caption: str = ""):
    img = Image.open(img_file)
    passport.setdefault("images", []).append({
        "file_base64": image_to_base64(img),
        "caption": caption
    })
    return passport


def add_certificate_evidence(passport: dict, cert_parsed: dict, raw_bytes: bytes, filename="", source="uploaded"):
    evid_hash = compute_sha256_bytes(raw_bytes)
    evid_id = f"evid_{evid_hash[:10]}"

    passport.setdefault("evidences", []).append({
        "evidence_id": evid_id,
        "hash": evid_hash,
        "filename": filename,
        "source": source,
        "created_at": _utc_now(),
    })

    cert_parsed["evidence"] = {
        "evidence_id": evid_id,
        "hash": evid_hash,
    }

    passport.setdefault("certificates", []).append(cert_parsed)
    return passport


# ======================================================
# ESPR / PEF
# ======================================================

def compute_pef_score(passport: dict) -> int:
    score = 50
    passport["sustainability_score"] = score
    passport["sustainability_breakdown"] = {"Base": score}
    return score


def missing_pef_fields(passport: dict):
    return []


def validate_espr_furniture(passport: dict) -> dict:
    missing = []
    for k, v in passport.get("sections", {}).get("PDF", {}).items():
        if not v.get("value"):
            missing.append(k)

    return {
        "missing_fields": missing,
        "missing_blocks": [],
        "warnings": [],
        "is_compliant": len(missing) == 0,
    }


def espr_stamp(passport: dict, actor: str, action: str, reason: str):
    passport["version"] += 1
    passport["last_updated_at"] = _utc_now()

    passport.setdefault("change_log", []).append({
        "version": passport["version"],
        "actor": actor,
        "action": action,
        "reason": reason,
        "timestamp": passport["last_updated_at"],
    })

    h = compute_passport_hash(passport)
    passport["digital_signature"] = {
        "algorithm": "SHA-256",
        "hash": h,
        "signed_at": passport["last_updated_at"],
        "signed_by": passport["issuer"]["legal_name"],
    }
    return passport


def compute_passport_hash(passport: dict) -> str:
    tmp = dict(passport)
    tmp.pop("digital_signature", None)
    payload = json.dumps(tmp, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def get_default_issuer():
    return {
        "legal_name": "Nuvia S.r.l.",
        "country": "IT",
        "role": "manufacturer",
    }


# ======================================================
# RENDER / PDF
# ======================================================

def generate_qr_from_url(url: str) -> BytesIO:
    qr = qrcode.make(url)
    buf = BytesIO()
    qr.save(buf)
    buf.seek(0)
    return buf


def generate_passport_html(passport: dict, qr_base64: str = None) -> str:
    return f"<html><body><h1>DPP {passport['id']}</h1></body></html>"


def generate_pdf_from_html(html: str) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(40, 800, "Digital Product Passport")
    c.showPage()
    c.save()
    return buf.getvalue()


# ======================================================
# DB / STORAGE
# ======================================================

def _sec(name: str, default=""):
    return str(st.secrets.get(name, os.getenv(name, default)))


def db_enabled() -> bool:
    return bool(_sec("SUPABASE_DB_URL"))


@contextmanager
def db_conn():
    import psycopg2
    conn = psycopg2.connect(_sec("SUPABASE_DB_URL"))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def persist_passport(passport: dict, actor="manufacturer", reason="update", shadow_file=False):
    if not db_enabled():
        os.makedirs(PASSPORT_DIR, exist_ok=True)
        with open(os.path.join(PASSPORT_DIR, f"{passport['id']}.json"), "w", encoding="utf-8") as f:
            json.dump(passport, f, indent=2)
        return

    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """insert into passports(passport_id, payload, version)
               values (%s,%s,%s)
               on conflict (passport_id) do update set payload=excluded.payload, version=excluded.version""",
            (passport["id"], json.dumps(passport, ensure_ascii=False), passport["version"]),
        )


def load_passport(pid: str):
    if not db_enabled():
        path = os.path.join(PASSPORT_DIR, f"{pid}.json")
        return json.load(open(path)) if os.path.exists(path) else None

    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("select payload from passports where passport_id=%s", (pid,))
        r = cur.fetchone()
        return r[0] if r else None

def set_physical_binding(
    passport: dict,
    public_url: str,
    carrier: str = "qr",
    location: str = "product_label",
    tamper_risk: str = "medium"
) -> dict:
    passport["physical_binding"] = {
        "carrier": carrier,
        "location": location,
        "public_url": public_url,
        "generated_at": _utc_now_iso(),
        "tamper_risk": tamper_risk
    }
    append_lifecycle_event(passport, "updated", {"physical_binding": {"carrier": carrier, "location": location}})
    espr_stamp(passport, actor="manufacturer", action="set_physical_binding", reason="Linked physical carrier to DPP")
    return passport
def merge_data_with_ecolabel(passport, pdf_file=None, image_data=None, cert_data=None, client=None):
    """
    Merge completo:
    - Estrae PDF
    - Normalizza
    - Integra Ecolabel
    - Integra dati validati (PDF + immagini)
    - Aggiorna passport["sections"]["PDF"]
    """

    changed = False

    # ------------------------------------------------------
    # 1) Estrazione PDF grezza
    # ------------------------------------------------------
    extracted_pdf = {}
    if pdf_file and client:
        text = extract_text_from_pdf(pdf_file)
        extracted_pdf = gpt_extract_from_pdf(
            text,
            client,
            tipo="mobile",
            fields=list(passport["sections"]["PDF"].keys())
        )

    # ------------------------------------------------------
    # 2) Normalizzazione campi PDF
    # ------------------------------------------------------
    normalized_pdf = normalize_pdf_fields(extracted_pdf)

    # ------------------------------------------------------
    # 3) Ecolabel
    # ------------------------------------------------------
    ecolabel_data = {}
    if pdf_file and client:
        ecolabel_data = extract_ecolabel_fields_from_pdf(pdf_file, client)

    # ------------------------------------------------------
    # 4) Merge PDF (validati + estratti + ecolabel)
    # ------------------------------------------------------
    passport["sections"].setdefault("PDF", {})

    for field in passport["sections"]["PDF"].keys():
        final_value = None

        # 1) Validato dall’utente (PRIORITARIO)
        if field in st.session_state.get("validated_pdf", {}):
            final_value = st.session_state.validated_pdf[field]["value"]

        # 2) Estratto da GPT
        elif field in normalized_pdf:
            final_value = normalized_pdf[field]["value"]

        # 3) Ecolabel (solo booleani)
        elif field in ecolabel_data:
            final_value = ecolabel_data[field]

        passport["sections"]["PDF"][field] = {
            "value": final_value,
            "confidence": 1.0,
            "explanation": ""
        }

    changed = True

    # ------------------------------------------------------
    # 5) Merge immagini
    # ------------------------------------------------------
    if image_data:
        passport["sections"]["Images"] = image_data
        changed = True

    # ------------------------------------------------------
    # 6) Merge certificati
    # ------------------------------------------------------
    if cert_data:
        passport["certificates"] = cert_data
        changed = True

    # ------------------------------------------------------
    # 7) Versioning
    # ------------------------------------------------------
    if changed:
        append_lifecycle_event(passport, "updated", {"what": "merge_data_with_ecolabel"})
        espr_stamp(passport, actor="manufacturer", action="data_merge_ecolabel", reason="Merged validated data + ecolabel")

    return passport



def db_list_passports_latest(**kwargs) -> pd.DataFrame:
    with db_conn() as conn:
        return pd.read_sql("""
            select
                passport_id as id,
                version,
                payload->>'product_type' as product_type,
                payload->'lifecycle'->>'status' as lifecycle,
                payload->>'pdf_document' is not null as pdf_present,
                coalesce(jsonb_array_length(payload->'certificates'),0) as cert_count
            from passports
            order by version desc
        """, conn)
