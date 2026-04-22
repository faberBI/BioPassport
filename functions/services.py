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


def db_list_passports_latest(**kwargs) -> pd.DataFrame:
    with db_conn() as conn:
        return pd.read_sql("select passport_id as id, version from passports", conn)
