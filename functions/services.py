import os
import json
import base64
import fitz  # PyMuPDF
import pdfplumber
import unicodedata
from difflib import get_close_matches
from io import BytesIO
from PIL import Image
import pandas as pd
from openai import OpenAI
import hashlib
from cryptography.fernet import Fernet
from openpyxl import load_workbook
import qrcode
from datetime import timezone, datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ======================================================
# CONFIG
# ======================================================
PASSPORT_DIR = "passports"
EXCEL_FILE = os.path.join(PASSPORT_DIR, "passport_archive.xlsx")
LOG_FILE = os.path.join(PASSPORT_DIR, "passport_log.jsonl")

TRUSTED_ISSUERS = ["Chambersign","InfoCert","Aruba PEC","GlobalSign EU","D-Trust"]

PRODUCT_FIELDS = {
    "mobile": {
        "pdf": [
            "Nome prodotto","Numero di modello","Produttore","Materiali/componenti utilizzati",
            "% di contenuto riciclato","Sostanze preoccupanti","Conformità tecnica",
            "Prezzo in euro","Luogo di Produzione","Data di produzione","Dimensioni",
            "Peso","Energia consumata"
        ],
        "image": ["Colore","Condizioni"]
    }
}

ECOLABEL_FIELDS = [
    "descrizione_prodotto","svhc_limitati","clp_conformita","legno_certificato",
    "plastica_conforme","metallo_conforme","rivestimenti_ok","formaldeide_bassa",
    "voc_bassi","facilmente_smortabile","produzione_basso_impatto","info_consumatore_ok"
]


# ======================================================
# ESPR – FURNITURE / WOOD FIELD PRIORITY MAP
# ======================================================

FIELD_PRIORITY_MAP = {
    # --- IDENTITÀ PRODOTTO ---
    "Nome prodotto": "essential",
    "Categoria prodotto": "essential",
    "Numero di modello": "essential",
    "Produttore": "essential",

    # --- PRODUZIONE ---
    "Luogo di Produzione": "essential",
    "Paese di Produzione": "essential",
    "Data di produzione": "essential",

    # --- MATERIALI & LEGNO ---
    "Materiali/componenti utilizzati": "essential",
    "Tipologia di legno": "essential",
    "Origine del legno": "essential",
    "Sostanze preoccupanti": "essential",

    # --- CERTIFICAZIONI ---
    "Conformità tecnica": "essential",
    "Certificazioni": "essential",
    "Ente certificatore": "essential",

    # --- FINE VITA ---
    "Indicazioni di smaltimento": "essential",
    "Fine vita": "essential",

    # --- STRONGLY RECOMMENDED ---
    "Percentuale di contenuto riciclato": "strongly_recommended",
    "Durabilità": "strongly_recommended",
    "Istruzioni di riparazione": "strongly_recommended",
    "Parti sostituibili": "strongly_recommended",

    # --- OPTIONAL ---
    "Prezzo in euro": "optional",
    "Peso": "optional",
    "Dimensioni": "optional",
}

# ======================================================
# NORMALIZATION / MATCHING
# ======================================================
def normalize(text):
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode()
    return text.replace(" ","_")

def match_field(input_key, field_names):
    norm_input = normalize(input_key)
    norm_fields = {normalize(f): f for f in field_names}
    if norm_input in norm_fields:
        return norm_fields[norm_input]
    matches = get_close_matches(norm_input, norm_fields.keys(), n=1, cutoff=0.8)
    return norm_fields[matches[0]] if matches else None


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def _canonical_json(obj) -> bytes:
    # serializzazione deterministica (per firma/hash stabile)
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def compute_passport_hash(passport: dict) -> str:
    # escludo la firma stessa per evitare ricorsione
    tmp = dict(passport)
    tmp.pop("digital_signature", None)
    payload = _canonical_json(tmp)
    return hashlib.sha256(payload).hexdigest()

def get_default_issuer():
    return {
        "legal_name": os.getenv("ISSUER_LEGAL_NAME", "Nuvia S.r.l."),
        "vat": os.getenv("ISSUER_VAT", "ITXXXXXXX"),
        "country": os.getenv("ISSUER_COUNTRY", "IT"),
        "role": os.getenv("ISSUER_ROLE", "manufacturer"),

        # 🔥 QUESTO È IL PUNTO CHIAVE
        "liability_statement": (
            "The issuer declares, under its sole legal responsibility, "
            "that the information contained in this Digital Product Passport "
            "is accurate and compliant with Regulation (EU) 2024/1781 (ESPR)."
        ),

        # opzionale ma molto apprezzato
        "contact": {
            "email": os.getenv("ISSUER_EMAIL", "compliance@nuvia.eu"),
            "website": os.getenv("ISSUER_WEBSITE", "https://nuvia.eu")
        }
    }

def espr_stamp(passport: dict, actor: str, action: str, reason: str, issuer: dict | None = None):
    """
    Applica versioning + audit + attestazione + firma hash.
    """
    now = _utc_now_iso()

    # Campi minimi
    passport.setdefault("version", 0)
    passport.setdefault("created_at", now)
    passport.setdefault("last_updated_at", now)
    passport.setdefault("change_log", [])

    # bump versione
    passport["version"] = int(passport.get("version") or 0) + 1
    passport["last_updated_at"] = now

    passport["change_log"].append({
        "version": passport["version"],
        "timestamp": now,
        "actor": actor,
        "action": action,
        "reason": reason
    })

    # issuer + attestation (solo se fornito o se non presente)
    if issuer is None and "issuer" not in passport:
        issuer = get_default_issuer()

    if issuer:
        passport["issuer"] = issuer
        passport["attestation"] = {
            "statement": "The issuer declares that the information contained in this Digital Product Passport is accurate and compliant with ESPR Regulation (EU) 2024/1781.",
            "timestamp": now
        }

    # firma integrità (hash)
    h = compute_passport_hash(passport)
    passport["digital_signature"] = {
        "algorithm": "SHA-256",
        "hash": h,
        "signed_at": now,
        "signed_by": (passport.get("issuer") or {}).get("legal_name", "unknown")
    }

    return passport



def _norm_field(x, field_name=None, default_conf=0.0):
    if isinstance(x, dict):
        value = "" if x.get("value") is None else str(x.get("value"))
        confidence = float(x.get("confidence", default_conf) or 0.0)
        explanation = "" if x.get("explanation") is None else str(x.get("explanation"))
    else:
        value = "" if x is None else str(x)
        confidence = float(default_conf)
        explanation = ""

    priority = FIELD_PRIORITY_MAP.get(field_name, "optional")
    mandatory = priority == "essential"

    return {
        "value": value,
        "confidence": confidence,
        "explanation": explanation,
        "priority": priority,
        "mandatory": mandatory
    }

def _norm_payload_cert(payload: dict) -> dict:
    # Normalizza output certificati (chiavi libere)
    if isinstance(payload, dict):
        return {k: _norm_field(v, field_name=k) for k, v in payload.items()}
    return {"raw": _norm_field(payload)}
    
def _norm_payload_pdf(payload: dict, expected_fields: list[str]) -> dict:
    # Normalizza output PDF sui campi attesi
    out = {k: {"value": "", "confidence": 0.0, "explanation": ""} for k in expected_fields}
    if isinstance(payload, dict):
        for k in expected_fields:
            out[k] = _norm_field(payload.get(k, out[k]), field_name=k)
    return out



def gpt_extract_from_pdf(pdf_text: str, client, tipo: str, fields: list[str], model: str = "gpt-4o-mini"):
    """
    Estrae campi dal testo PDF e ritorna SEMPRE un dict:
    {field: {value, confidence, explanation}}
    """
    if not pdf_text:
        return {k: {"value": "", "confidence": 0.0, "explanation": ""} for k in fields}

    # template output
    template = {k: {"value": "", "confidence": 0.0, "explanation": ""} for k in fields}

    system = (
        "You are a strict information extraction engine.\n"
        "Return ONLY JSON, no markdown, no commentary.\n"
        "For each field return an object with keys: value, confidence (0..1), explanation.\n"
        "If a field is unknown, leave value empty and confidence 0.\n"
    )

    user = (
        f"Extract product passport fields for product_type={tipo}.\n"
        "Use the following JSON template and populate fields from the text.\n"
        "Return ONLY JSON.\n\n"
        f"TEMPLATE:\n{json.dumps(template, ensure_ascii=False)}\n\n"
        f"PDF_TEXT:\n{pdf_text[:20000]}"
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

        content = resp.choices[0].message.content or "{}"

        # parse JSON robusto
        try:
            data = json.loads(content)
        except Exception:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                data = json.loads(content[start:end+1])
            else:
                data = {}

        return _norm_payload_pdf(data, fields)

    except Exception as e:
        # fallback senza crash
        return {k: {"value": "", "confidence": 0.0, "explanation": f"Extraction error: {e}"} for k in fields}

def passport_meta_row(passport: dict) -> dict:
    issuer = passport.get("issuer") or {}
    sig = passport.get("digital_signature") or {}
    att = passport.get("attestation") or {}
    lifecycle = passport.get("lifecycle") or {}
    pb = passport.get("physical_binding") or {}

    return {
        "id": passport.get("id"),
        "product_type": passport.get("product_type"),
        "version": passport.get("version"),
        "created_at": passport.get("created_at"),
        "last_updated_at": passport.get("last_updated_at"),

        "overall_rating": passport.get("overall_rating"),
        "sustainability_score": passport.get("sustainability_score"),

        "issuer_legal_name": issuer.get("legal_name"),
        "issuer_vat": issuer.get("vat"),
        "issuer_role": issuer.get("role"),
        "issuer_country": issuer.get("country"),

        "attestation_timestamp": att.get("timestamp"),
        "signature_algorithm": sig.get("algorithm"),
        "signature_hash": sig.get("hash"),
        "signature_signed_at": sig.get("signed_at"),
        "signature_signed_by": sig.get("signed_by"),

        # ✅ lifecycle
        "lifecycle_status": lifecycle.get("status"),

        # ✅ physical binding
        "binding_carrier": pb.get("carrier"),
        "binding_location": pb.get("location"),
        "binding_public_url": pb.get("public_url"),
        "binding_generated_at": pb.get("generated_at"),
        "binding_tamper_risk": pb.get("tamper_risk"),
    }


# ======================================================
# PDF / IMAGE UTILITIES
# ======================================================
def split_text(text, max_chars=3000, overlap=300):
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start += max_chars - overlap
    return chunks

def extract_text_from_pdf(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                text += txt + "\n"
    return text

def image_to_base64(image: Image.Image) -> str:
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    buf = BytesIO()
    image.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()

def resize_image_for_vision(image_file, max_size=512):
    img = Image.open(image_file).convert("RGB")
    img.thumbnail((max_size, max_size))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    buf.name = "image.jpg"
    return buf

# ======================================================
# CONFIDENCE
# ======================================================
def compute_confidence(values):
    if not values:
        return 0.0
    most_common = max(set(values), key=values.count)
    return values.count(most_common)/len(values)

# ======================================================
# CRITTOGRAFIA DATI SENSIBILI / SIGNATURE / VERSIONING
# ======================================================
def generate_key():
    return Fernet.generate_key()

def encrypt_sensitive_data(data: str, key: bytes) -> str:
    f = Fernet(key)
    return f.encrypt(data.encode()).decode()

def decrypt_sensitive_data(data: str, key: bytes) -> str:
    f = Fernet(key)
    return f.decrypt(data.encode()).decode()

def sign_passport(passport: dict, key: bytes):
    passport_copy = {k:v for k,v in passport.items() if k != "digital_signature"}
    serialized = json.dumps(passport_copy, sort_keys=True).encode()
    f = Fernet(key)
    signature = f.encrypt(hashlib.sha256(serialized).digest())
    passport["digital_signature"] = signature.decode()
    passport["version"] = passport.get("version",0) + 1
    passport["last_modified"] = datetime.utcnow().isoformat()
    return passport

def verify_passport_signature(passport: dict, key: bytes):
    signature = passport.get("digital_signature")
    if not signature:
        return False
    passport_copy = {k:v for k,v in passport.items() if k != "digital_signature"}
    serialized = json.dumps(passport_copy, sort_keys=True).encode()
    f = Fernet(key)
    try:
        decrypted = f.decrypt(signature.encode())
        return decrypted == hashlib.sha256(serialized).digest()
    except Exception:
        return False

# ======================================================
# GPT FUNCTIONS
# ======================================================

def gpt_extract_cert_info(file_like, client, model: str = "gpt-4o-mini"):
    """
    Estrae info da certificati (PDF o immagine) e restituisce SEMPRE
    un dict normalizzato: {campo: {value, confidence, explanation}}
    """
    # ---------- 1) leggi bytes ----------
    if hasattr(file_like, "read"):
        raw = file_like.read()
    else:
        raw = file_like

    if not raw:
        return {}

    is_pdf = raw[:4] == b"%PDF"

    # ---------- 2) prepara contenuto ----------
    if is_pdf:
        try:
            text = extract_text_from_pdf(BytesIO(raw))
        except Exception:
            text = ""
        input_block = {
            "type": "text",
            "text": (
                "You are extracting structured fields from a certificate document.\n"
                "Return ONLY valid JSON.\n\n"
                f"CERTIFICATE_TEXT:\n{text[:20000]}"
            )
        }
    else:
        try:
            img = Image.open(BytesIO(raw))
            img_b64 = image_to_base64(img)
        except Exception:
            img_b64 = None

        if img_b64:
            input_block = [
                {"type": "text", "text": "Extract certificate fields. Return ONLY JSON."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]
        else:
            input_block = {
                "type": "text",
                "text": "Extract certificate fields. Return ONLY JSON. If impossible return {}."
            }

    # ---------- 3) schema output ----------
    schema_hint = {
        "tipo_certificato": {"value": "", "confidence": 0.0, "explanation": ""},
        "ente_emittente": {"value": "", "confidence": 0.0, "explanation": ""},
        "numero_certificato": {"value": "", "confidence": 0.0, "explanation": ""},
        "data_emissione": {"value": "", "confidence": 0.0, "explanation": ""},
        "data_scadenza": {"value": "", "confidence": 0.0, "explanation": ""},
        "norma_riferimento": {"value": "", "confidence": 0.0, "explanation": ""},
        "prodotto_modello": {"value": "", "confidence": 0.0, "explanation": ""},
        "ambito_scopo": {"value": "", "confidence": 0.0, "explanation": ""},
        "note": {"value": "", "confidence": 0.0, "explanation": ""}
    }

    system = (
        "You are a strict information extraction engine.\n"
        "Return ONLY JSON, no markdown, no commentary.\n"
        "For each field return an object with keys: value, confidence (0..1), explanation.\n"
        "If a field is unknown, leave value empty and confidence 0.\n"
    )

    user = (
        "Extract certificate information. Use this JSON structure as output template:\n"
        f"{json.dumps(schema_hint, ensure_ascii=False)}\n"
        "Populate what you can from the document.\n"
        "IMPORTANT: return ONLY JSON.\n"
    )

    # ---------- 4) call OpenAI ----------
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "user", "content": [input_block] if isinstance(input_block, dict) else input_block},
            ],
        )

        content = resp.choices[0].message.content or "{}"

        # ---------- 5) parse JSON robusto ----------
        try:
            data = json.loads(content)
        except Exception:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                data = json.loads(content[start:end+1])
            else:
                data = {}

        # ✅ FIX: qui prima avevi _norm_payload_cert(data)(data) (sbagliato) [1](https://outlook.office365.com/owa/?ItemID=AAMkADc1NjAzMWI0LWVkZjUtNGNiYS1iZTc1LTk5Zjc2YTM0MmU0OABGAAAAAAC6gddaoK7mQ4ywo%2fiCrZUSBwAcOa%2fcmRsdS5%2fe2FZINWcxAAAAAAEMAAAcOa%2fcmRsdS5%2fe2FZINWcxAABcFD4yAAA%3d&exvsurl=1&viewmodel=ReadMessageItem)
        normalized = _norm_payload_cert(data)

        # completa campi mancanti
        for k in schema_hint.keys():
            normalized.setdefault(k, {"value": "", "confidence": 0.0, "explanation": ""})

        return normalized

    except Exception as e:
        return {k: {"value": "", "confidence": 0.0, "explanation": f"Extraction error: {e}"} for k in schema_hint.keys()}

def gpt_analyze_image(image_file, client: OpenAI, tipo):
    campi = ["colore","condizioni","materiale_probabile","categoria_visiva","segni_usura"]
    prompt = f"""
Analizza immagine prodotto {tipo}.
Estrai i seguenti campi: colore, condizioni, materiale_probabile, categoria_visiva, segni_usura.
Rispondi con JSON valido.
Usa null se non determinabile.
"""
    def safe_json_parse(text):
        if text.startswith("```"):
            text = "\n".join([l for l in text.splitlines() if not l.strip().startswith("```")])
        first,last = text.find("{"), text.rfind("}")
        return json.loads(text[first:last+1])
    try:
        file_id = upload_image_to_openai(image_file, client)
        resp = client.responses.create(
            model="gpt-4o",
            input=[{"role":"user","content":[{"type":"input_text","text":prompt},{"type":"input_image","file_id":file_id}]}]
        )
        data_raw = safe_json_parse(resp.output_text.strip())
        result = {}
        for c in campi:
            val = data_raw.get(c, None)
            result[c.capitalize()] = {
                "value": val if val not in [None,"","null"] else "non rilevato",
                "confidence": 0.7 if val not in [None,"","null"] else 0.0,
                "explanation": "Dato estratto da immagine" if val not in [None,"","null"] else "Non rilevabile"
            }
        return result
    except Exception:
        return {c.capitalize():{"value":"non rilevato","confidence":0.0,"explanation":"Non rilevabile"} for c in campi}

def upload_image_to_openai(image_file, client: OpenAI):
    resized = resize_image_for_vision(image_file)
    uploaded = client.files.create(file=resized, purpose="vision")
    return uploaded.id

# ======================================================
# PASSPORT MANAGEMENT
# ======================================================

def initialize_passport(pid, tipo, fields):
    passport = {
        "id": pid,
        "product_type": tipo,
        "sections": {},
        "certificates": [],
        "images": [],
        "evidences": [],              # ✅ nuovo
        "physical_binding": None,     # ✅ nuovo
        "lifecycle": {"status": "draft", "events": []},  # ✅ nuovo

        "overall_rating": 0,
        "sustainability_score": 0,
        "validated_by_operator": False,

        # audit/versioning
        "created_at": None,
        "last_updated_at": None,
        "change_log": [],

        # issuer/attestation/hash
        "issuer": None,
        "attestation": None,
        "digital_signature": None,

        "version": 0
    }

    # inizializza campi PDF attesi
    for field in fields:
        passport["sections"].setdefault("PDF", {})[field] = {
            "value": None,
            "confidence": 0,
            "explanation": ""
        }

    # evento lifecycle + prima timbratura
    append_lifecycle_event(passport, "draft", {"reason": "initialization"})
    espr_stamp(
        passport,
        actor="manufacturer",
        action="initial_creation",
        reason="Initial DPP publication",
        issuer=get_default_issuer()
    )
    return passport


def merge_data(passport, pdf_data=None, image_data=None, cert_data=None):
    changed = False

    if pdf_data:
        passport["sections"].setdefault("PDF", {}).update(pdf_data)
        changed = True
    if image_data:
        passport["sections"]["Images"] = image_data
        changed = True
    if cert_data is not None:
        passport["certificates"] = cert_data
        changed = True

    if changed:
        append_lifecycle_event(passport, "updated", {"what": "merge_data"})
        espr_stamp(passport, actor="manufacturer", action="data_merge", reason="Merged validated data")
    return passport

def save_passport_to_file(passport: dict):
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    path = os.path.join(PASSPORT_DIR, f"{passport['id']}.json")
    with open(path,"w",encoding="utf-8") as f:
        json.dump(passport,f,indent=2)

def load_passport_from_file(pid):
    path = os.path.join(PASSPORT_DIR, f"{pid}.json")
    if not os.path.exists(path):
        return None
    with open(path,"r",encoding="utf-8") as f:
        return json.load(f)

def log_passport_version(passport: dict):
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    hash_data = hashlib.sha256(json.dumps(passport, sort_keys=True).encode()).hexdigest()
    log_entry = {
        "passport_id": passport["id"],
        "timestamp": datetime.utcnow().isoformat(),
        "hash": hash_data
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry)+"\n")

# ======================================================
# QR CODE
# ======================================================
def generate_qr_from_url(url):
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

# ======================================================
# ECOLABEL
# ======================================================
def extract_ecolabel_fields_from_pdf(pdf_file, client: OpenAI):
    text = extract_text_from_pdf(pdf_file)
    extracted_data = gpt_extract_from_pdf(text, client, tipo="mobile", fields=ECOLABEL_FIELDS)
    ecolabel_data = {}
    for campo, info in extracted_data.items():
        val = info.get("value")
        if isinstance(val,bool):
            ecolabel_data[campo] = val
        elif isinstance(val,str):
            ecolabel_data[campo] = val.strip().lower() in ["sì","si","true","yes","conforme"]
        else:
            ecolabel_data[campo] = False
    return ecolabel_data

def merge_data_with_ecolabel(passport, pdf_file=None, image_data=None, cert_data=None, client=None):
    changed = False

    if pdf_file:
        ecolabel_data = extract_ecolabel_fields_from_pdf(pdf_file, client)
        passport["sections"]["Ecolabel_UE"] = ecolabel_data

        pdf_text = extract_text_from_pdf(pdf_file)
        pdf_text_data = gpt_extract_from_pdf(pdf_text, client, "mobile", ECOLABEL_FIELDS)
        passport["sections"]["PDF"] = pdf_text_data
        changed = True

    if image_data:
        passport["sections"]["Images"] = image_data
        changed = True

    if cert_data is not None:
        passport["certificates"] = cert_data
        changed = True

    if changed:
        append_lifecycle_event(passport, "updated", {"what": "merge_data_with_ecolabel"})
        espr_stamp(passport, actor="manufacturer", action="data_merge_ecolabel", reason="Merged validated data + ecolabel")
    return passport

# ======================================================
# EXCEL
# ======================================================

import os
import pandas as pd
from openpyxl import load_workbook

def save_passport_to_excel_append(passport: dict):
    # ======================================================
    # DATAFRAME DA SCRIVERE
    # ======================================================
    df_passport = pd.DataFrame([passport_meta_row(passport)])

    # fields
    fields_rows = []
    for section, fields in passport.get("sections", {}).items():
        if isinstance(fields, dict):
            for fname, f in fields.items():
                val = f.get("value") if isinstance(f, dict) else f
                fields_rows.append({
                    "passport_id": passport.get("id"),
                    "section": section,
                    "field_name": fname,
                    "value": val
                })
    df_fields = pd.DataFrame(fields_rows)

    # images
    images_rows = [
        {
            "passport_id": passport.get("id"),
            "file_base64": img.get("file_base64"),
            "caption": img.get("caption", "")
        }
        for img in passport.get("images", [])
    ]
    df_images = pd.DataFrame(images_rows)

    # certificates (flatten)
    cert_rows = []
    for cert in passport.get("certificates", []):
        if isinstance(cert, dict):
            evid = cert.get("evidence", {})
            for k, v in cert.items():
                if k == "evidence":
                    continue
                val = v.get("value") if isinstance(v, dict) else v
                cert_rows.append({
                    "passport_id": passport.get("id"),
                    "field_name": k,
                    "value": val,
                    "evidence_id": evid.get("evidence_id"),
                    "evidence_hash": evid.get("hash")
                })
    df_certs = pd.DataFrame(cert_rows)

    # change log (ultimo)
    log_rows = []
    if passport.get("change_log"):
        last = passport["change_log"][-1]
        log_rows.append({
            "passport_id": passport.get("id"),
            "version": last.get("version"),
            "timestamp": last.get("timestamp"),
            "actor": last.get("actor"),
            "action": last.get("action"),
            "reason": last.get("reason"),
        })
    df_log = pd.DataFrame(log_rows)

    # ✅ lifecycle events (tutti)
    lifecycle_rows = []
    for ev in (passport.get("lifecycle", {}) or {}).get("events", []):
        lifecycle_rows.append({
            "passport_id": passport.get("id"),
            "event": ev.get("event"),
            "timestamp": ev.get("timestamp"),
            "data": json.dumps(ev.get("data", {}), ensure_ascii=False)
        })
    df_lifecycle = pd.DataFrame(lifecycle_rows)

    # ✅ evidences
    evid_rows = []
    for evd in passport.get("evidences", []):
        evid_rows.append({
            "passport_id": passport.get("id"),
            "evidence_id": evd.get("evidence_id"),
            "type": evd.get("type"),
            "source": evd.get("source"),
            "filename": evd.get("filename"),
            "hash_algorithm": evd.get("hash_algorithm"),
            "hash": evd.get("hash"),
            "created_at": evd.get("created_at"),
        })
    df_evidences = pd.DataFrame(evid_rows)

    # ======================================================
    # CREA FILE SE NON ESISTE
    # ======================================================
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    if not os.path.exists(EXCEL_FILE):
        with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl") as writer:
            df_passport.to_excel(writer, sheet_name="passport", index=False)
            df_fields.to_excel(writer, sheet_name="fields", index=False)
            df_images.to_excel(writer, sheet_name="images", index=False)
            df_certs.to_excel(writer, sheet_name="certificates", index=False)
            df_log.to_excel(writer, sheet_name="change_log", index=False)

            # ✅ nuovi sheet
            df_lifecycle.to_excel(writer, sheet_name="lifecycle_events", index=False)
            df_evidences.to_excel(writer, sheet_name="evidences", index=False)
        return

    # ======================================================
    # APPEND SE ESISTE
    # ======================================================
    book = load_workbook(EXCEL_FILE)

    def _append_df(df, sheet):
        if df is None or df.empty:
            return
        startrow = book[sheet].max_row if sheet in book.sheetnames else 0
        header = startrow == 0
        with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:
            df.to_excel(writer, sheet_name=sheet, index=False, header=header, startrow=startrow)

    _append_df(df_passport, "passport")
    _append_df(df_fields, "fields")
    _append_df(df_images, "images")
    _append_df(df_certs, "certificates")
    _append_df(df_log, "change_log")
    _append_df(df_lifecycle, "lifecycle_events")
    _append_df(df_evidences, "evidences")

    # ======================================================
    # APPEND SE ESISTE
    # ======================================================
    book = load_workbook(EXCEL_FILE)

    def _append_df(df, sheet):
        if df.empty:
            return
        startrow = book[sheet].max_row if sheet in book.sheetnames else 0
        header = startrow == 0
        with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:
            df.to_excel(writer, sheet_name=sheet, index=False, header=header, startrow=startrow)

    _append_df(df_passport, "passport")
    _append_df(df_fields, "fields")
    _append_df(df_images, "images")
    _append_df(df_certs, "certificates")
    _append_df(df_log, "change_log")

# ======================================================
# IMAGE MANAGEMENT
# ======================================================

def add_product_image(passport: dict, img_file, caption: str = ""):
    try:
        image = Image.open(img_file if not isinstance(img_file, BytesIO) else img_file)
        img_b64 = image_to_base64(image)

        passport.setdefault("images", []).append({
            "file_base64": img_b64,
            "caption": caption or ""
        })

        espr_stamp(passport, actor="manufacturer", action="add_image", reason="Added product image")

        return passport
    except Exception as e:
        raise RuntimeError(f"Errore aggiungendo immagine: {e}")


# ======================================================
# COMPLIANCE RENDER
# ======================================================
def render_espr_compliance(passport, st=None):
    """
    Render completo della compliance ESPR in Streamlit.
    Mostra:
    - issuer
    - physical binding
    - lifecycle
    - esito validazione
    - campi mandatory / raccomandati / opzionali
    """

    if st is None:
        import streamlit as st

    st.subheader("📋 ESPR – Digital Product Passport Compliance")

    # ==================================================
    # 1) ISSUER
    # ==================================================
    st.markdown("### 🏭 Issuer")
    issuer = passport.get("issuer", {})
    if issuer:
        for k, v in issuer.items():
            st.write(f"**{k}**: {v}")
    else:
        st.error("❌ Issuer mancante (bloccante ESPR)")

    # ==================================================
    # 2) PHYSICAL BINDING
    # ==================================================
    st.markdown("### 🔗 Physical Binding")
    binding = passport.get("physical_binding", {})
    if binding:
        for k, v in binding.items():
            st.write(f"**{k}**: {v}")
    else:
        st.error("❌ Physical binding mancante (bloccante ESPR)")

    # ==================================================
    # 3) LIFECYCLE
    # ==================================================
    st.markdown("### ♻️ Lifecycle")
    lifecycle = passport.get("lifecycle", {})
    st.write(f"**Stato attuale**: {lifecycle.get('status', '—')}")

    events = lifecycle.get("events", [])
    if events:
        with st.expander("Eventi lifecycle"):
            for ev in events:
                st.write(f"- **{ev.get('event', '—')}** @ {ev.get('timestamp', '—')}")
    else:
        st.caption("Nessun evento lifecycle")

    # ==================================================
    # 4) VALIDAZIONE ESPR
    # ==================================================
    st.markdown("### ✅ Esito validazione ESPR")
    check = validate_espr_furniture(passport)

    if check.get("is_compliant"):
        st.success("✅ DPP conforme ai requisiti ESPR (ESSENTIAL)")
    else:
        st.error("❌ DPP NON conforme ai requisiti ESPR")

    if check.get("missing_blocks"):
        st.markdown("**Blocchi obbligatori mancanti:**")
        for b in check["missing_blocks"]:
            st.write(f"- ❌ {b}")

    if check.get("missing_fields"):
        st.markdown("**Campi obbligatori mancanti:**")
        for f in check["missing_fields"]:
            st.write(f"- ❌ {f}")

    # ==================================================
    # 5) CAMPI DEL PASSPORT
    # ==================================================
    st.markdown("### 🧾 Campi del Digital Product Passport")

    sections = passport.get("sections", {})
    if not sections:
        st.warning("Nessuna sezione presente nel passport")
        return

    for section_name, fields in sections.items():
        st.markdown(f"#### 📁 Sezione: {section_name}")

        for field_name, data in fields.items():
            # Normalizzazione: se non è dict → trasformalo
            if not isinstance(data, dict):
                data = {
                    "value": data,
                    "confidence": 0,
                    "explanation": "",
                    "mandatory": False,
                    "priority": "optional"
                }

            value = str(data.get("value", "")).strip()
            confidence = float(data.get("confidence", 0) or 0)
            explanation = data.get("explanation", "")
            mandatory = data.get("mandatory", False)
            priority = data.get("priority", "optional")

            # Stato del campo
            if mandatory and not value:
                st.error(f"❌ **{field_name}** · OBBLIGATORIO → MANCANTE")
            elif mandatory:
                st.success(f"✅ **{field_name}** · OBBLIGATORIO")
            elif priority == "strongly_recommended":
                st.warning(f"⚠️ **{field_name}** · Raccomandato")
            else:
                st.info(f"ℹ️ **{field_name}** · Opzionale")

            # Dettagli
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**Valore:** {value or '—'}")
                if explanation:
                    st.caption(f"Fonte: {explanation}")

            with col2:
                st.write(f"**Confidenza:** {round(confidence, 2)}")

        st.divider()

# ---------- FUNZIONE PRINCIPALE: quella che chiami dal main ----------
def sign_passport_pdf_qes_openapi(passport: dict, attach_signed_pdf: bool = True) -> dict:
    """
    ✅ Questa deve ESISTERE come attributo di services:
       services.sign_passport_pdf_qes_openapi(passport)

    - genera PDF del passport
    - firma via OpenAPI EU-QES_automatic in PAdES (PDF)
    - salva metadati in passport["qualified_signature"]
    - (opzionale) scarica e allega PDF firmato in passport["signed_pdf"] (base64)
    """
    tok = openapi_create_token(scopes=["POST:test.esignature.openapi.com/EU-QES_eseal"], ttl_seconds=3600)
    bearer_token = _bearer(tok)

    pdf_bytes = generate_passport_pdf(passport)
    #pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    #pdf_bytes = generate_passport_pdf(passport)

    # ✅ normalizza: se ti torna BytesIO invece di bytes
    if hasattr(pdf_bytes, "getvalue"):
        pdf_bytes = pdf_bytes.getvalue()

    # ✅ se per errore è stringa, la trasformo
    if isinstance(pdf_bytes, str):
        pdf_bytes = pdf_bytes.encode("utf-8")

    # ✅ safety check
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        raise TypeError(f"generate_passport_pdf() ha restituito {type(pdf_bytes)} invece di bytes")

    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    resp = openapi_qes_automatic_sign(
        bearer_token=bearer_token,
        input_documents=[{"sourceType": "base64", "payload": pdf_b64}],
        signature_type="cades",
        title=f"DPP {passport.get('id')} QES",
        description="Firma QES automatica del Digital Product Passport (PDF)"
    )

    data = resp.get("data") or {}
    passport["qualified_signature"] = {
        "provider": "OpenAPI",
        "service": "EU-QES_automatic",
        "signature_id": data.get("id"),
        "state": data.get("state"),
        "certificateType": data.get("certificateType"),
        "signatureType": data.get("signatureType"),
        "signed_at": _utc_now_iso(),
        "raw_response": resp
    }

    # Provo a scaricare e allegare il PDF firmato:
    # se state = WAIT_VALIDATION può non essere pronto, quindi non blocco.
    if attach_signed_pdf and passport["qualified_signature"].get("signature_id"):
        try:
            signed_bytes = openapi_get_signed_document(
                bearer_token,
                passport["qualified_signature"]["signature_id"]
            )
            passport["signed_pdf"] = base64.b64encode(signed_bytes).decode("utf-8")
        except Exception:
            passport["signed_pdf"] = None

    return passport["qualified_signature"]


# OPENAPI QES (OAuth + eSignature) + PDF firmato
# ======================================================
import os
import base64
import requests
from io import BytesIO
from datetime import datetime, timezone

def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def _sec(name: str, default: str = "") -> str:
    """
    Legge da Streamlit secrets se disponibili, altrimenti da env var.
    Così services.py funziona sia su Streamlit Cloud che in locale.
    """
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return str(os.getenv(name, default))

# ---------- OAuth: Basic Auth -> token ----------
def _openapi_basic_auth_header() -> str:
    email = _sec("OPENAPI_EMAIL")
    apikey = _sec("OPENAPI_APIKEY")
    if not email or not apikey:
        raise RuntimeError("Mancano OPENAPI_EMAIL / OPENAPI_APIKEY nei secrets/env")

    raw = f"{email}:{apikey}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("utf-8")

def openapi_create_token(scopes, ttl_seconds: int = 3600) -> dict:
    if not scopes or not isinstance(scopes, list):
        raise ValueError("scopes deve essere una lista non vuota")

    base = _sec("OPENAPI_OAUTH_BASE_URL").rstrip("/")
    url = f"{base}/token"

    headers = {
        "Authorization": _openapi_basic_auth_header(),  # email:APIKEY_PROD
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "scopes": scopes,
        "ttl": ttl_seconds
    }

    r = requests.post(url, json=payload, headers=headers, timeout=30)
    if not r.ok:
        raise RuntimeError(f"OAUTH ERROR {r.status_code}: {r.text}")

    return r.json()

def _bearer(token_resp: dict) -> str:
    if isinstance(token_resp, dict):
        if "data" in token_resp and isinstance(token_resp["data"], list):
            if token_resp["data"] and "token" in token_resp["data"][0]:
                return token_resp["data"][0]["token"]
        if "access_token" in token_resp:
            return token_resp["access_token"]
        if "token" in token_resp:
            return token_resp["token"]

    raise RuntimeError(f"Token OAuth non trovato: {token_resp}")

# ---------- eSignature: firma QES ----------
def openapi_qes_automatic_sign(
    bearer_token: str,
    input_documents: list,
    signature_type: str = "pades",
    title: str = "DPP Qualified Signature",
    description: str = "Firma QES automatica del Digital Product Passport"
) -> dict:
    """
    POST /EU-QES_automatic (eSignature).
    (Endpoint dichiarato nella doc eSignature) [3](https://runebook.dev/en/docs/pandas/reference/api/pandas.excelwriter)
    """
    base = _sec("OPENAPI_ESIGN_BASE_URL").rstrip("/")
    if not base:
        raise RuntimeError("Manca OPENAPI_ESIGN_BASE_URL nei secrets/env")

    cert_user = _sec("OPENAPI_CERT_USERNAME")
    cert_pass = _sec("OPENAPI_CERT_PASSWORD")
    if not cert_user or not cert_pass:
        raise RuntimeError("Mancano OPENAPI_CERT_USERNAME / OPENAPI_CERT_PASSWORD nei secrets/env")

    url = f"{base}/EU-QES_automatic"
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "inputDocuments": input_documents,
        "certificateUsername": cert_user,
        "certificatePassword": cert_pass,
        "title": title,
        "description": description,
        "signatureType": signature_type,  # pades|cades|xades|pkcs1
    }

    r = requests.post(url, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()

# ---------- download firmato ----------
def openapi_get_signed_document(bearer_token: str, signature_id: str) -> bytes:
    """
    GET /signatures/{id}/signedDocument (scarica il documento firmato)
    (Endpoint dichiarato nella doc eSignature) [3](https://runebook.dev/en/docs/pandas/reference/api/pandas.excelwriter)
    """
    base = _sec("OPENAPI_ESIGN_BASE_URL").rstrip("/")
    if not base:
        raise RuntimeError("Manca OPENAPI_ESIGN_BASE_URL nei secrets/env")

    url = f"{base}/signatures/{signature_id}/signedDocument"
    headers = {"Authorization": f"Bearer {bearer_token}", "Accept": "*/*"}
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    return r.content

# ---------- PDF del DPP (minimo firmabile) ----------
def generate_passport_pdf(passport: dict) -> bytes:
    """
    Genera un PDF minimale del passport (firmabile).
    Ritorna SEMPRE bytes.
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    w, h = A4
    y = h - 40

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, "Digital Product Passport")
    y -= 22

    c.setFont("Helvetica", 10)

    header = [
        ("ID", passport.get("id")),
        ("Tipo", passport.get("product_type")),
        ("Versione", passport.get("version")),
        ("Issuer", (passport.get("issuer") or {}).get("legal_name")),
        ("Hash", (passport.get("digital_signature") or {}).get("hash")),
    ]

    for label, value in header:
        c.drawString(40, y, f"{label}: {value or '-'}")
        y -= 14

    # ✅ CHIUSURA CORRETTA PDF
    c.showPage()
    c.save()

    buf.seek(0)
    return buf.getvalue()   # ✅ QUESTO È IL PUNTO CHIAVE



def openapi_qes_eseal_sign(bearer_token: str, input_documents: list, signature_type="cades",
                           title="QeSeal", description="Qualified Electronic Seal") -> dict:
    base = _sec("OPENAPI_ESIGN_BASE_URL").rstrip("/")
    url = f"{base}/EU-QES_eseal"  # ✅ endpoint sigillo [1](https://xlsxwriter.readthedocs.io/working_with_pandas.html)

    payload = {
        "inputDocuments": input_documents,
        "certificateUsername": _sec("OPENAPI_CERT_USERNAME"),
        "certificatePassword": _sec("OPENAPI_CERT_PASSWORD"),
        "title": title,
        "description": description,
        "signatureType": signature_type
    }

    r = requests.post(url, json=payload, headers={
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }, timeout=60)

    if not r.ok:
        raise RuntimeError(f"eSeal ERROR {r.status_code}: {r.text}")

    return r.json()


def seal_passport_pdf_qeseal_openapi(passport: dict, attach_signed: bool = False) -> dict:
    """
    Applica QeSeal (EU-QES) al PDF del passport.
    """
    # 1) token OAuth (scope produzione)
    tok = openapi_create_token(scopes=["POST:esignature.openapi.com/EU-QES_eseal"], ttl_seconds=3600)
    bearer_token = _bearer(tok)

    # 2) genera PDF -> bytes -> base64
    pdf_bytes = generate_passport_pdf(passport)
    if hasattr(pdf_bytes, "getvalue"):
        pdf_bytes = pdf_bytes.getvalue()
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        raise TypeError(f"generate_passport_pdf() ha restituito {type(pdf_bytes)} invece di bytes")

    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    # 3) chiamata eSeal
    resp = openapi_qes_eseal_sign(
        bearer_token=bearer_token,
        input_documents=[{"sourceType": "base64", "payload": pdf_b64}],
        signature_type="cades",
        title="Nuvia srls",
        description="Nuvia srls seal"
    )

    data = resp.get("data") or {}
    passport["qualified_seal"] = {
        "provider": "OpenAPI",
        "service": "EU-QES_eseal",
        "seal_id": data.get("id"),
        "state": data.get("state"),
        "signatureType": data.get("signatureType"),
        "raw_response": resp
    }

    # 4) opzionale: download documento sigillato (se vuoi)
    # if attach_signed and passport["qualified_seal"].get("seal_id"):
    #     signed_bytes = openapi_get_signed_document(bearer_token, passport["qualified_seal"]["seal_id"])
    #     passport["sealed_document"] = base64.b64encode(signed_bytes).decode("utf-8")

    return passport["qualified_seal"]

def openapi_list_scopes(skip: int = 0, limit: int = 100) -> dict:
    base = _sec("OPENAPI_OAUTH_BASE_URL").rstrip("/")
    url = f"{base}/scopes?skip={skip}&limit={limit}"

    headers = {
        "Authorization": _openapi_basic_auth_header(),
        "Accept": "application/json",
    }

    r = requests.get(url, headers=headers, timeout=30)

    # 🔍 DEBUG DI SICUREZZA
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(
            f"SCOPES NON JSON ({r.status_code}): {r.text}"
        )

    if not r.ok:
        raise RuntimeError(
            f"SCOPES ERROR {r.status_code}: {data}"
        )

    # ✅ GARANTIAMO DI RESTITUIRE SOLO UN DICT
    if not isinstance(data, dict):
        return {"raw": data}

    return data



def compute_sha256_bytes(raw: bytes) -> str:
    if raw is None:
        raise ValueError("raw bytes is None")
    return hashlib.sha256(raw).hexdigest()

LIFECYCLE_STATUS_MAP = {
    "draft": "draft",
    "manufactured": "manufactured",
    "placed_on_market": "placed_on_market",
    "certified": "certified",
    "signed": "signed",
    "updated": "updated",
    "repaired": "repaired",
    "component_replaced": "component_replaced",
    "resold": "resold",
    "withdrawn": "withdrawn",
    "end_of_life": "end_of_life",
}

def ensure_lifecycle(passport: dict) -> dict:
    passport.setdefault("lifecycle", {"status": "draft", "events": []})
    if "status" not in passport["lifecycle"]:
        passport["lifecycle"]["status"] = "draft"
    if "events" not in passport["lifecycle"]:
        passport["lifecycle"]["events"] = []
    return passport

def append_lifecycle_event(passport: dict, event: str, data: dict | None = None) -> dict:
    ensure_lifecycle(passport)
    now = _utc_now_iso()
    ev = {
        "event": event,
        "timestamp": now,
        "data": data or {}
    }
    passport["lifecycle"]["events"].append(ev)

    # status semantico
    passport["lifecycle"]["status"] = LIFECYCLE_STATUS_MAP.get(event, event)
    return passport

def ensure_evidence_store(passport: dict) -> dict:
    passport.setdefault("evidences", [])
    return passport

def add_certificate_evidence(
    passport: dict,
    cert_parsed: dict,
    raw_bytes: bytes,
    filename: str = "",
    source: str = "uploaded_certificate"
) -> dict:
    """
    Aggiunge un certificato normalizzato + evidenza verificabile (hash sha256 dei bytes originali).
    """
    ensure_evidence_store(passport)

    evid_hash = compute_sha256_bytes(raw_bytes)
    evid_id = f"evid_{evid_hash[:16]}"

    evidence_obj = {
        "evidence_id": evid_id,
        "type": "document",
        "source": source,
        "filename": filename or "",
        "hash_algorithm": "SHA-256",
        "hash": evid_hash,
        "created_at": _utc_now_iso(),
    }
    passport["evidences"].append(evidence_obj)

    # collega l’evidenza al certificato
    cert_obj = _norm_payload_cert(cert_parsed) if isinstance(cert_parsed, dict) else {"raw": _norm_field(cert_parsed)}
    cert_obj.setdefault("evidence", {})
    cert_obj["evidence"] = {
        "evidence_id": evid_id,
        "hash": evid_hash,
        "hash_algorithm": "SHA-256",
        "filename": filename or "",
        "source": source
    }

    passport.setdefault("certificates", [])
    passport["certificates"].append(cert_obj)

    # evento lifecycle + audit stamp
    append_lifecycle_event(passport, "certified", {"evidence_id": evid_id, "filename": filename})
    espr_stamp(passport, actor="manufacturer", action="add_certificate_evidence", reason=f"Added certificate evidence {evid_id}")

    return passport

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

def post_market_event(
    passport: dict,
    event: str,
    data: dict,
    actor: str = "service_partner",
    reason: str = "Post-market update"
) -> dict:
    """
    Eventi post-vendita: riparazioni, sostituzioni componenti, rivendita, ritiro, fine vita.
    """
    append_lifecycle_event(passport, event, data or {})
    espr_stamp(passport, actor=actor, action=f"post_market_{event}", reason=reason)
    return passport

def validate_espr_furniture(passport: dict) -> dict:
    """
    Valida i requisiti ESSENTIAL per DPP furniture/wood in modo robusto.
    Ritorna un dict con:
      - missing_fields: campi mandatory mancanti dentro sections
      - missing_blocks: blocchi mandatory mancanti a livello root (binding/issuer/evidences)
      - warnings: valori presenti ma non “validi” (placeholder)
    """
    missing_fields = []
    missing_blocks = []
    warnings = []

    # --- 1) controlla i campi nelle sections (PDF/Images/Ecolabel_UE ecc.) ---
    for sec_name, section in (passport.get("sections") or {}).items():
        if not isinstance(section, dict):
            continue

        for fname, f in section.items():
            if not isinstance(f, dict):
                continue

            if f.get("mandatory"):
                val = f.get("value")

                # considera vuoti anche placeholder comuni
                if val is None:
                    missing_fields.append(fname)
                    continue

                sval = str(val).strip().lower()
                if sval in ("", "none", "null", "non specificato", "non rilevato", "-"):
                    missing_fields.append(fname)

                # warning se confidenza molto bassa su campo mandatory
                conf = float(f.get("confidence", 0) or 0)
                if conf < 0.3:
                    warnings.append(f"{fname}: confidenza bassa ({conf})")

    # --- 2) controlli “root-level” essenziali per DPP ---
    # 2a) issuer/attestation
    issuer = passport.get("issuer") or {}
    if not issuer.get("legal_name"):
        missing_blocks.append("issuer.legal_name")
    if not passport.get("attestation"):
        missing_blocks.append("attestation")

    # 2b) legame fisico-digitale (carrier + url)
    pb = passport.get("physical_binding") or {}
    if not pb.get("carrier"):
        missing_blocks.append("physical_binding.carrier")
    if not pb.get("public_url"):
        missing_blocks.append("physical_binding.public_url")

    # 2c) lifecycle
    lc = passport.get("lifecycle") or {}
    if not lc.get("status"):
        missing_blocks.append("lifecycle.status")

    # 2d) certificati verificabili (evidences) — fondamentale per “wood/furniture”
    # se hai certificates ma nessuna evidence, è un problema
    certs = passport.get("certificates") or []
    evids = passport.get("evidences") or []
    if len(certs) > 0 and len(evids) == 0:
        missing_blocks.append("evidences (missing evidence hashes for certificates)")

    # se richiedi almeno 1 certificato in furniture/wood
    # (es. EUDR/EUTR/legno), puoi forzare questo check:
    if len(certs) == 0:
        warnings.append("Nessun certificato presente: per furniture/wood spesso è richiesto almeno un documento di tracciabilità/legality del legno.")

    return {
        "missing_fields": sorted(set(missing_fields)),
        "missing_blocks": sorted(set(missing_blocks)),
        "warnings": sorted(set(warnings)),
        "is_compliant": (len(missing_fields) == 0 and len(missing_blocks) == 0)
    }
def _scope_for_eu_ses() -> str:
    """
    Determina lo scope corretto per EU-SES in base all'ambiente (sandbox/prod).
    """
    base_esign = _sec("OPENAPI_ESIGN_BASE_URL").rstrip("/")
    if "test." in base_esign:
        return "POST:test.esignature.openapi.com/EU-SES"
    return "POST:esignature.openapi.com/EU-SES"


def openapi_eu_ses_request(
    bearer_token: str,
    pdf_base64: str,
    signers: list,
    signature_mode: list = None,
    ui_options: dict = None,
    title: str = "Nuvia srls",
    description: str = "prova",
) -> dict:
    """
    POST /EU-SES (PROD) - usa inputDocuments come stringa base64 (come nel playground).
    """
    import requests

    url = "https://esignature.openapi.com/EU-SES"

    payload = {
        "title": title,
        "description": description,
        "inputDocuments": pdf_base64,
        "signers": signers,
        "options": {
            "timezone": "UTC",
            "signatureMode": signature_mode or ["typed"]
        }
    }

    if ui_options:
        payload["options"]["ui"] = ui_options

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    r = requests.post(url, json=payload, headers=headers, timeout=30)
    if not r.ok:
        raise RuntimeError(f"EU-SES ERROR {r.status_code}: {r.text}")
    return r.json()

def sign_passport_pdf_ses_openapi(
    passport: dict,
    signer_name: str,
    signer_surname: str,
    signer_email: str,
    signer_mobile: str
) -> dict:

    import streamlit as st
    import base64

    # ✅ 1) Usa il bearer PROD
    bearer_token = st.secrets["OPENAPI_BEARER_PROD"]

    # ✅ 2) Genera PDF
    pdf_bytes = generate_passport_pdf(passport)

    # ✅ 3) Base64 PURO (come playground)
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    # ✅ 4) Signers
    signers = [
        {
            "name": signer_name,
            "surname": signer_surname,
            "email": signer_email,
            "mobile": signer_mobile,
            "authentication": "sms"
        }
    ]

    # ✅ 5) Chiamata IDENTICA al playground
    resp = openapi_eu_ses_request(
        bearer_token=bearer_token,
        pdf_base64=pdf_b64,
        signers=signers,
        signature_mode=["typed"]
    )

    # ✅ 6) Log nel passport
    passport["simple_signature"] = {
        "provider": "OpenAPI",
        "type": "EU-SES",
        "raw_response": resp
    }

    return resp
