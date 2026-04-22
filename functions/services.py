# ======================================================#/Pubblica/Archivio + Public View + SES)
# ======================================================

import os
import json
import base64
import hashlib
from io import BytesIO
from datetime import datetime, timezone
from contextlib import contextmanager
from urllib.parse import urlparse

import streamlit as st
import pandas as pd
import pdfplumber
from PIL import Image
from openai import OpenAI
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import request
from typing import Optional, Dict

# ======================================================
# CONFIG
# ======================================================

PASSPORT_DIR = "passports"
EXCEL_FILE = os.path.join(PASSPORT_DIR, "passport_archive.xlsx")  # fallback legacy (non usato se DB attivo)

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
            "Luogo di Produzione",
            "Durabilità",
            "Istruzioni di riparazione",
            "Parti sostituibili",
            "Indicazioni di smaltimento",
            "Fine vita",
            "Certificazioni",
            "Prezzo in euro",
            "Peso",
            "Dimensioni",
            # opzionali per estensioni
            "GTIN",
        ],
        "image": ["Colore", "Condizioni"],
    },
    "lampada": {"pdf": [], "image": []},
    "bicicletta": {"pdf": [], "image": []},
}


# ======================================================
# UTILS
# ======================================================

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize(text: str) -> str:
    """
    ✅ versione richiesta: NFKD / ascii / underscore
    """
    import unicodedata
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode()
    return text.lower().strip().replace(" ", "_")


def compute_sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_passport_hash(passport: dict) -> str:
    tmp = dict(passport)
    tmp.pop("digital_signature", None)
    return hashlib.sha256(_canonical_json(tmp)).hexdigest()


def get_default_issuer() -> dict:
    return {
        "legal_name": os.getenv("ISSUER_LEGAL_NAME", "Nuvia S.r.l."),
        "country": os.getenv("ISSUER_COUNTRY", "IT"),
        "role": os.getenv("ISSUER_ROLE", "manufacturer"),
    }


def ensure_lifecycle(passport: dict) -> dict:
    passport.setdefault("lifecycle", {"status": "draft", "events": []})
    passport["lifecycle"].setdefault("status", "draft")
    passport["lifecycle"].setdefault("events", [])
    return passport


def append_lifecycle_event(passport: dict, event: str, data: dict | None = None) -> dict:
    ensure_lifecycle(passport)
    ev = {"event": event, "timestamp": _utc_now_iso(), "data": data or {}}
    passport["lifecycle"]["events"].append(ev)
    passport["lifecycle"]["status"] = event
    return passport


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
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def generate_qr_from_url(url: str) -> BytesIO:
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ======================================================
# GPT — ESTRAZIONE
# ======================================================

def gpt_extract_from_pdf(pdf_text: str, client, tipo: str, fields: list[str], model: str = "gpt-4o-mini") -> dict:
    """
    Output: {field: {value, confidence, explanation}}
    """
    if not pdf_text:
        return {k: {"value": "", "confidence": 0.0, "explanation": ""} for k in fields}

    template = {k: {"value": "", "confidence": 0.0, "explanation": ""} for k in fields}

    system = (
        "You are a strict information extraction engine. "
        "Return ONLY valid JSON. No markdown. No commentary. "
        "Do not hallucinate values."
    )

    user = (
        f"Extract product passport fields for product_type={tipo}.\n"
        "Return ONLY JSON using this template:\n"
        f"{json.dumps(template, ensure_ascii=False)}\n\n"
        "PDF_TEXT:\n"
        f"{pdf_text[:20000]}"
    )

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
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    out = {}
    for k in fields:
        x = data.get(k, {}) if isinstance(data.get(k, {}), dict) else {}
        out[k] = {
            "value": x.get("value", "") if x.get("value", "") is not None else "",
            "confidence": float(x.get("confidence", 0.0) or 0.0),
            "explanation": x.get("explanation", "") if x.get("explanation", "") is not None else "",
        }
    return out


def gpt_analyze_image(image_file, client: OpenAI, tipo: str) -> dict:
    """
    Stub robusto: evita crash. (Puoi sostituirlo con Vision “vera” quando vuoi.)
    Output: {"Colore": {...}, "Condizioni": {...}}
    """
    # Non facciamo chiamate Vision per evitare complessità/permessi.
    return {
        "Colore": {"value": "non rilevato", "confidence": 0.0, "explanation": "Non determinato"},
        "Condizioni": {"value": "non rilevato", "confidence": 0.0, "explanation": "Non determinato"},
    }


def gpt_extract_cert_info(file_like, client, model: str = "gpt-4o-mini") -> dict:
    """
    Estrae un set base di campi certificato.
    """
    raw = file_like.read()
    if not raw:
        return {}

    is_pdf = raw[:4] == b"%PDF"
    text = extract_text_from_pdf(BytesIO(raw)) if is_pdf else ""

    schema = {
        "tipo_certificato": {"value": "", "confidence": 0.0, "explanation": ""},
        "ente_emittente": {"value": "", "confidence": 0.0, "explanation": ""},
        "numero_certificato": {"value": "", "confidence": 0.0, "explanation": ""},
        "data_emissione": {"value": "", "confidence": 0.0, "explanation": ""},
        "data_scadenza": {"value": "", "confidence": 0.0, "explanation": ""},
        "norma_riferimento": {"value": "", "confidence": 0.0, "explanation": ""},
    }

    user = (
        "Extract certificate info. Return ONLY JSON.\n"
        f"Use this schema:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"TEXT:\n{text[:15000]}"
    )

    try:
        res = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[{"role": "user", "content": user}],
        )
        data = json.loads(res.choices[0].message.content or "{}")
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    out = {}
    for k, tpl in schema.items():
        v = data.get(k, tpl)
        if not isinstance(v, dict):
            v = tpl
        out[k] = {
            "value": v.get("value", ""),
            "confidence": float(v.get("confidence", 0.0) or 0.0),
            "explanation": v.get("explanation", ""),
        }
    return out


# ======================================================
# NORMALIZZAZIONE CAMPI PDF (PEF)
# ======================================================

def normalize_pdf_fields(pdf_data: dict) -> dict:
    """
    Normalizza SOLO i campi PEF, senza perdere gli altri campi PDF.
    (Niente '...': liste vere di varianti.)
    """
    FIELD_MAP = {
        "Percentuale di contenuto riciclato": [
            "Percentuale di contenuto riciclato", "% di contenuto riciclato", "% riciclato", "Contenuto riciclato"
        ],
        "Sostanze preoccupanti": [
            "Sostanze preoccupanti", "Sostanze pericolose", "SVHC", "Sostanze"
        ],
        "Energia consumata": [
            "Energia consumata", "Consumo energetico", "Energia"
        ],
        "Luogo di Produzione": [
            "Luogo di Produzione", "Luogo di produzione", "Produzione", "Made in", "Prodotto in"
        ],
        "Durabilità": [
            "Durabilità", "Durata", "Resistenza"
        ],
        "Istruzioni di riparazione": [
            "Istruzioni di riparazione", "Riparabilità", "Riparazione"
        ],
        "Parti sostituibili": [
            "Parti sostituibili", "Componenti sostituibili", "Parti di ricambio"
        ],
        "Indicazioni di smaltimento": [
            "Indicazioni di smaltimento", "Smaltimento", "Disposal"
        ],
        "Fine vita": [
            "Fine vita", "End of life", "EoL"
        ],
        "Certificazioni": [
            "Certificazioni", "Certificato", "Certificazione"
        ],
    }

    normalized = dict(pdf_data or {})

    for canonical, variants in FIELD_MAP.items():
        found = False
        for v in variants:
            if v in (pdf_data or {}) and isinstance((pdf_data or {})[v], dict) and (pdf_data or {})[v].get("value"):
                normalized[canonical] = (pdf_data or {})[v]
                found = True
                break

        if not found:
            normalized.setdefault(canonical, {"value": "", "confidence": 0.0, "explanation": ""})

    return normalized


# ======================================================
# PASSPORT CORE
# ======================================================

def initialize_passport(pid: str, tipo: str, fields: list[str]) -> dict:
    passport = {
        "id": pid,
        "product_type": tipo,
        "version": 0,
        "created_at": _utc_now_iso(),
        "last_updated_at": _utc_now_iso(),
        "sections": {"PDF": {}},
        "images": [],
        "certificates": [],
        "evidences": [],
        "physical_binding": None,
        "issuer": get_default_issuer(),
        "attestation": None,
        "digital_signature": None,
        "lifecycle": {"status": "draft", "events": []},
    }

    for f in fields:
        passport["sections"]["PDF"][f] = {"value": "", "confidence": 0.0, "explanation": ""}

    append_lifecycle_event(passport, "draft", {"reason": "initialization"})
    espr_stamp(passport, actor="manufacturer", action="initial_creation", reason="Initial creation")
    return passport


def merge_data(passport: dict, pdf_data=None, image_data=None, cert_data=None):
    if pdf_data:
        passport.setdefault("sections", {}).setdefault("PDF", {})
        passport["sections"]["PDF"].update(pdf_data)

    if image_data:
        passport.setdefault("sections", {})["Images"] = image_data

    if cert_data is not None:
        passport["certificates"] = cert_data

    append_lifecycle_event(passport, "updated", {"what": "merge_data"})
    espr_stamp(passport, actor="manufacturer", action="merge_data", reason="Merged validated data")
    return passport


def add_product_image(passport: dict, img_file, caption: str = ""):
    img = Image.open(img_file)
    passport.setdefault("images", []).append({
        "file_base64": image_to_base64(img),
        "caption": caption or ""
    })
    append_lifecycle_event(passport, "updated", {"what": "add_product_image"})
    return passport


def add_certificate_evidence(passport: dict, cert_parsed: dict, raw_bytes: bytes, filename: str = "", source: str = "uploaded_certificate"):
    evid_hash = compute_sha256_bytes(raw_bytes)
    evid_id = f"evid_{evid_hash[:16]}"

    passport.setdefault("evidences", []).append({
        "evidence_id": evid_id,
        "hash_algorithm": "SHA-256",
        "hash": evid_hash,
        "filename": filename or "",
        "source": source,
        "created_at": _utc_now_iso(),
    })

    cert_obj = cert_parsed if isinstance(cert_parsed, dict) else {"raw": {"value": str(cert_parsed)}}
    cert_obj["evidence"] = {"evidence_id": evid_id, "hash": evid_hash, "hash_algorithm": "SHA-256", "filename": filename or "", "source": source}

    passport.setdefault("certificates", []).append(cert_obj)

    append_lifecycle_event(passport, "certified", {"evidence_id": evid_id, "filename": filename})
    espr_stamp(passport, actor="manufacturer", action="add_certificate_evidence", reason=f"Added certificate evidence {evid_id}")
    return passport


def set_physical_binding(passport: dict, public_url: str, carrier: str = "qr", location: str = "product_label", tamper_risk: str = "medium"):
    passport["physical_binding"] = {
        "carrier": carrier,
        "location": location,
        "public_url": public_url,
        "generated_at": _utc_now_iso(),
        "tamper_risk": tamper_risk,
    }
    append_lifecycle_event(passport, "updated", {"physical_binding": {"carrier": carrier, "location": location}})
    espr_stamp(passport, actor="manufacturer", action="set_physical_binding", reason="Linked physical carrier to DPP")
    return passport


def merge_data_with_ecolabel(passport, pdf_file=None, image_data=None, cert_data=None, client=None):
    """
    Versione robusta e coerente col main.py:
    - se ho pdf_file+client: estraggo campi dal PDF
    - normalizzo campi PEF
    - merge con image_data/cert_data
    """
    extracted_pdf = {}
    if pdf_file and client:
        text = extract_text_from_pdf(pdf_file)
        fields = list((passport.get("sections", {}).get("PDF") or {}).keys())
        extracted_pdf = gpt_extract_from_pdf(text, client, tipo="mobile", fields=fields)

    normalized_pdf = normalize_pdf_fields(extracted_pdf)
    return merge_data(passport, pdf_data=normalized_pdf, image_data=image_data, cert_data=cert_data)


# ======================================================
# PEF + ESPR validation (stub robusto)
# ======================================================

def compute_pef_score(passport: dict) -> int:
    # Stub: puoi sostituire con il tuo scoring reale quando vuoi
    score = int(passport.get("sustainability_score") or 0)
    if score <= 0:
        score = 50
    passport["sustainability_score"] = score
    passport["sustainability_breakdown"] = passport.get("sustainability_breakdown") or {"Base": score}
    return score


def missing_pef_fields(passport: dict):
    # Stub minimal: torna lista vuota (nessun blocco)
    return []


def validate_espr_furniture(passport: dict) -> dict:
    # Stub coerente col main (missing_fields / missing_blocks / warnings / is_compliant)
    missing_fields = []
    pdf = passport.get("sections", {}).get("PDF", {}) or {}
    for k, v in pdf.items():
        if isinstance(v, dict) and str(v.get("value", "")).strip() == "" and k in PRODUCT_FIELDS.get(passport.get("product_type","mobile"), {}).get("pdf", []):
            # qui potresti applicare una true mandatory list; per ora è soft
            pass

    # blocchi minimi
    missing_blocks = []
    if not (passport.get("issuer") or {}).get("legal_name"):
        missing_blocks.append("issuer.legal_name")
    if not (passport.get("physical_binding") or {}).get("public_url"):
        missing_blocks.append("physical_binding.public_url")

    return {
        "missing_fields": missing_fields,
        "missing_blocks": missing_blocks,
        "warnings": [],
        "is_compliant": (len(missing_fields) == 0 and len(missing_blocks) == 0),
    }


def espr_stamp(passport: dict, actor: str, action: str, reason: str):
    passport.setdefault("version", 0)
    passport["version"] = int(passport["version"]) + 1
    passport["last_updated_at"] = _utc_now_iso()
    passport.setdefault("change_log", []).append({
        "version": passport["version"],
        "timestamp": passport["last_updated_at"],
        "actor": actor,
        "action": action,
        "reason": reason,
    })
    passport.setdefault("issuer", get_default_issuer())
    passport["attestation"] = {
        "statement": "The issuer declares that the information contained in this Digital Product Passport is accurate and compliant with ESPR Regulation (EU) 2024/1781.",
        "timestamp": passport["last_updated_at"],
    }
    h = compute_passport_hash(passport)
    passport["digital_signature"] = {
        "algorithm": "SHA-256",
        "hash": h,
        "signed_at": passport["last_updated_at"],
        "signed_by": (passport.get("issuer") or {}).get("legal_name", "unknown"),
    }
    return passport


def integrate_espr_modules(passport: dict):
    """
    Versione safe: popola i campi che il Public View mostra, senza dipendenze esterne (dpp.*).
    """
    passport["jsonld"] = passport.get("jsonld") or {}
    passport["ontology"] = passport.get("ontology") or {}
    passport["eprel"] = passport.get("eprel") or {}
    passport["gs1_digital_link"] = passport.get("gs1_digital_link") or None
    passport["scip"] = passport.get("scip") or {}
    passport["espr_sections"] = passport.get("espr_sections") or {}
    passport["espr_validation"] = passport.get("espr_validation") or validate_espr_furniture(passport)
    return passport


# ======================================================
# HTML + PDF (per il main)
# ======================================================

def generate_passport_html(passport: dict, qr_base64: str | None = None) -> str:
    # HTML semplice e robusto (basta per la conversione PDF)
    pid = passport.get("id", "")
    ptype = passport.get("product_type", "")
    ver = passport.get("version", 0)

    qr_html = f"<img src='data:image/png;base64,{qr_base64}' style='width:160px'/>" if qr_base64 else ""

    rows = ""
    for section, fields in (passport.get("sections", {}) or {}).items():
        if not isinstance(fields, dict):
            continue
        for k, v in fields.items():
            val = v.get("value") if isinstance(v, dict) else v
            rows += f"<tr><td><b>{k}</b></td><td>{val}</td></tr>"

    return f"""
    <html><head><meta charset="utf-8"></head>
    <body style="font-family:Arial; margin:40px">
      <h1>Digital Product Passport</h1>
      <p><b>ID:</b> {pid} &nbsp; <b>Type:</b> {ptype} &nbsp; <b>Version:</b> {ver}</p>
      {qr_html}
      <h2>Sections</h2>
      <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse; width:100%">
        {rows}
      </table>
    </body></html>
    """


def generate_pdf_from_html(html: str) -> bytes:
    """
    Conversione HTML->PDF “locale” (stub): crea un PDF semplice.
    Se vuoi usare OpenAPI PDF, sostituisci qui.
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, 800, "Digital Product Passport")
    c.setFont("Helvetica", 10)
    c.drawString(40, 780, "PDF generated by Nuvia (local stub).")
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


# ======================================================
# SES SIGN (obbligatoria nel main)
# ======================================================

def sign_passport_pdf_ses_openapi(
    passport: dict,
    signer_name: str,
    signer_surname: str,
    signer_email: str,
    signer_mobile: str,
):
    """
    Versione safe: se hai OPENAPI_BEARER_PROD prova a chiamare EU-SES,
    altrimenti crea uno stub che non crasha la UI.
    """
    bearer = st.secrets.get("OPENAPI_BEARER_PROD", "")

    # Stub se manca bearer
    if not bearer:
        passport["simple_signature"] = {
            "provider": "OpenAPI",
            "type": "EU-SES",
            "status": "requested",
            "signing_urls": [],
            "raw_response": {},
        }
        return passport

    # serve pdf_document
    if "pdf_document" not in passport:
        raise RuntimeError("passport['pdf_document'] mancante — PDF non generato")

    pdf_bytes = base64.b64decode(passport["pdf_document"])
    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

    url = "https://esignature.openapi.com/EU-SES"
    payload = {
        "title": "Nuvia",
        "description": "EU-SES request",
        "inputDocuments": pdf_base64,
        "signers": [{
            "name": signer_name,
            "surname": signer_surname,
            "email": signer_email,
            "mobile": signer_mobile,
            "authentication": "sms"
        }],
        "options": {"timezone": "UTC", "signatureMode": ["typed"]},
    }

    headers = {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    r = requests.post(url, json=payload, headers=headers, timeout=30)
    if not r.ok:
        raise RuntimeError(f"EU-SES ERROR {r.status_code}: {r.text}")

    resp = r.json()
    data = resp.get("data", {}) if isinstance(resp, dict) else {}
    signing_urls = []
    for s in (data.get("signers") or []):
        if isinstance(s, dict) and s.get("url"):
            signing_urls.append(s["url"])

    passport["simple_signature"] = {
        "provider": "OpenAPI",
        "type": "EU-SES",
        "request_id": data.get("id"),
        "status": data.get("state"),
        "signing_urls": signing_urls,
        "raw_response": resp,
    }
    return passport


# ======================================================
# DB / STORAGE (Supabase Postgres)
# ======================================================

def _sec(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return str(os.getenv(name, default))


def db_enabled() -> bool:
    return bool(_sec("SUPABASE_DB_URL"))


@contextmanager
def db_conn():
    """
    psycopg2 se disponibile; fallback pg8000.
    """
    url = _sec("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("SUPABASE_DB_URL mancante")

    # psycopg2
    try:
        import psycopg2
        conn = psycopg2.connect(url)
        conn.autocommit = False
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return
    except ImportError:
        pass

    # pg8000 fallback
    import pg8000
    u = urlparse(url)
    conn = pg8000.connect(
        user=u.username,
        password=u.password,
        host=u.hostname,
        port=u.port or 5432,
        database=(u.path or "/postgres").lstrip("/"),
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_DB_SCHEMA_READY = False

def ensure_db_schema():
    """
    Crea tabelle minime se non esistono.
    """
    global _DB_SCHEMA_READY
    if _DB_SCHEMA_READY or not db_enabled():
        return

    ddl = """
    create table if not exists passports (
      passport_id text primary key,
      payload jsonb not null,
      version integer not null default 0,
      created_at timestamptz default now(),
      updated_at timestamptz default now()
    );
    """

    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute(ddl)

    _DB_SCHEMA_READY = True


def _to_dict(payload):
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return None
    return payload


def persist_passport(passport: dict, actor: str = "manufacturer", reason: str = "update", shadow_file: bool = False):
    """
    DB-first. Fallback su file se DB non configurato.
    """
    if not db_enabled():
        os.makedirs(PASSPORT_DIR, exist_ok=True)
        with open(os.path.join(PASSPORT_DIR, f"{passport['id']}.json"), "w", encoding="utf-8") as f:
            json.dump(passport, f, indent=2, ensure_ascii=False)
        return

    ensure_db_schema()

    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            insert into passports(passport_id, payload, version, updated_at)
            values (%s,%s::jsonb,%s,now())
            on conflict (passport_id) do update set
              payload = excluded.payload,
              version = excluded.version,
              updated_at = now()
            """,
            (passport["id"], json.dumps(passport, ensure_ascii=False), int(passport.get("version", 0)))
        )

    if shadow_file:
        os.makedirs(PASSPORT_DIR, exist_ok=True)
        with open(os.path.join(PASSPORT_DIR, f"{passport['id']}.json"), "w", encoding="utf-8") as f:
            json.dump(passport, f, indent=2, ensure_ascii=False)


def load_passport(pid: str):
    """
    DB-first, fallback file.
    """
    if not db_enabled():
        path = os.path.join(PASSPORT_DIR, f"{pid}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    ensure_db_schema()

    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("select payload from passports where passport_id=%s", (pid,))
        row = cur.fetchone()
        return _to_dict(row[0]) if row else None


def db_list_passports_latest(
    search: str = "",
    product_type: str = "ALL",
    lifecycle: str = "ALL",
    min_version: int = 1,
    has_pdf: bool = False,
    has_cert: bool = False,
    sort_col: str = "updated_at",
    sort_asc: bool = False,
    limit: int = 5000
) -> pd.DataFrame:
    """
    Restituisce la vista archivio con le colonne usate nel main:
    id, product_type, version, lifecycle, pdf_present, cert_count, created_at, updated_at
    """
    ensure_db_schema()

    allowed_sort = {"created_at", "updated_at", "version"}
    if sort_col not in allowed_sort:
        sort_col = "updated_at"
    order = "ASC" if sort_asc else "DESC"

    where = ["1=1"]
    params = []

    if search:
        where.append("(passport_id ILIKE %s OR payload->>'product_type' ILIKE %s OR payload->'issuer'->>'legal_name' ILIKE %s)")
        like = f"%{search}%"
        params += [like, like, like]

    if product_type and product_type != "ALL":
        where.append("(payload->>'product_type') = %s")
        params.append(product_type)

    if lifecycle and lifecycle != "ALL":
        where.append("(payload->'lifecycle'->>'status') = %s")
        params.append(lifecycle)

    if min_version and int(min_version) > 1:
        where.append("version >= %s")
        params.append(int(min_version))

    if has_pdf:
        where.append("(payload ? 'pdf_document')")

    if has_cert:
        where.append("coalesce(jsonb_array_length(payload->'certificates'),0) > 0")

    sql = f"""
        select
            passport_id as id,
            payload->>'product_type' as product_type,
            version as version,
            payload->'lifecycle'->>'status' as lifecycle,
            (payload ? 'pdf_document') as pdf_present,
            coalesce(jsonb_array_length(payload->'certificates'),0) as cert_count,
            created_at,
            updated_at
        from passports
        where {" and ".join(where)}
        order by {sort_col} {order}
        limit %s
    """

    params.append(int(limit))

    with db_conn() as conn:
        return pd.read_sql(sql, conn, params=params)
# services.py — Nuvia Digital Product Passport
