import pdfplumber
import json
import base64
import qrcode
import os
import unicodedata
from difflib import get_close_matches
from io import BytesIO
from openai import OpenAI
import streamlit as st
from PIL import Image
from datetime import datetime

# ======================================================
# CONFIG
# ======================================================
PASSPORT_DIR = "passports"

# ======================================================
# NORMALIZATION / MATCHING
# ======================================================
def normalize(text):
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return text.replace(" ", "_")

def match_field(input_key, field_names):
    norm_input = normalize(input_key)
    norm_fields = {normalize(f): f for f in field_names}

    if norm_input in norm_fields:
        return norm_fields[norm_input]

    matches = get_close_matches(norm_input, norm_fields.keys(), n=1, cutoff=0.8)
    if matches:
        return norm_fields[matches[0]]

    return None

# ======================================================
# PDF CHUNKING
# ======================================================
def split_text(text, max_chars=3000, overlap=300):
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start += max_chars - overlap
    return chunks

# ======================================================
# PDF / IMAGE UTILITIES
# ======================================================
def extract_text_from_pdf(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def image_to_base64(image_file):
    if hasattr(image_file, "getvalue"):
        return base64.b64encode(image_file.getvalue()).decode()
    buf = BytesIO()
    image_file.save(buf, format="JPEG")
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
    return round(values.count(most_common) / len(values), 2)

# ======================================================
# GPT PDF EXTRACTION (ROBUST)
# ======================================================
def gpt_extract_from_pdf(text, client: OpenAI, tipo, fields):

    chunks = split_text(text)
    results = []

    for chunk in chunks:
        prompt = f"""
Estrai dati tecnici del prodotto ({tipo}).

Regole:
- SOLO JSON valido
- Usa null se non presente
- NON inventare

Campi:
{json.dumps(fields, indent=2)}

Testo:
{chunk}
"""
        try:
            r = client.chat.completions.create(
                model="gpt-4.1",
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            results.append(json.loads(r.choices[0].message.content))
        except Exception:
            continue

    final = {}

    for campo in fields:
        values = [r.get(campo) for r in results if r.get(campo)]
        final[campo] = {
            "value": values[0] if values else None,
            "confidence": compute_confidence(values),
            "explanation": "Dato estratto da PDF" if values else "Dato non trovato nel PDF"
        }

    return final

# ======================================================
# GPT IMAGE ANALYSIS (ENHANCED)
# ======================================================
def gpt_analyze_image(image_file, client: OpenAI, tipo):

    prompt = f"""
Analizza immagine prodotto ({tipo}).

Estrai:
- colore
- condizioni
- materiale_probabile
- categoria_visiva
- segni_usura

Rispondi con JSON valido.
Usa null se non determinabile.
"""

    try:
        file_id = upload_image_to_openai(image_file, client)

        resp = client.responses.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "file_id": file_id}
                ]
            }]
        )

        data = json.loads(resp.output_text)

        result = {}
        for k, v in data.items():
            result[k] = {
                "value": v,
                "confidence": 0.7 if v else 0.0,
                "explanation": "Dato estratto da immagine" if v else "Non rilevabile"
            }

        return result

    except Exception as e:
        st.error(f"Errore GPT Image: {e}")
        return {}

def upload_image_to_openai(image_file, client):
    resized = resize_image_for_vision(image_file)
    uploaded = client.files.create(file=resized, purpose="vision")
    return uploaded.id

# ======================================================
# RATING + EXPLAINABILITY
# ======================================================
def compute_field_rating(field):
    val = field.get("value")
    if val in [None, "", "null"]:
        return 0.0

    conf = field.get("confidence", 0.0)
    weight = field.get("eu_weight", 1.0)

    return round(conf * weight, 2)

def generate_explanation(field):
    if field["value"] in [None, "", "null"]:
        return "Dato mancante"
    if field["confidence"] < 0.5:
        return "Bassa confidenza"
    return "Dato affidabile"

def score_to_color(score):
    if score >= 0.7:
        return "🟢"
    elif score >= 0.4:
        return "🟡"
    return "🔴"

# ======================================================
# PASSPORT CORE
# ======================================================
def initialize_passport(product_id, product_type, fields):

    passport = {
        "id": product_id,
        "product_type": product_type,
        "metadata": {
            "created_at": datetime.utcnow().isoformat(),
            "version": "EU-DPP-2.0"
        },
        "sections": {
            "Technical": {"fields": {}, "section_rating": 0},
            "Visual": {"fields": {}, "section_rating": 0}
        },
        "overall_rating": 0.0,
        "overall_espr": "MISSING",
        "images": []
    }

    for f in fields:
        passport["sections"]["Technical"]["fields"][f] = {
            "value": None,
            "confidence": 0.0,
            "rating": 0.0,
            "color": "🔴",
            "explanation": ""
        }

    return passport

# ======================================================
# MERGE DATA (SMART)
# ======================================================
def merge_data(passport, pdf_data, image_data):

    all_data = {**pdf_data, **image_data}

    for section in passport["sections"].values():
        for field_name, field in section["fields"].items():

            for k, v in all_data.items():
                matched = match_field(k, [field_name])
                if matched == field_name:

                    if isinstance(v, dict):
                        field.update(v)
                    else:
                        field["value"] = v

                    field["rating"] = compute_field_rating(field)
                    field["color"] = score_to_color(field["rating"])
                    field["explanation"] = generate_explanation(field)

    compute_overall(passport)

# ======================================================
# OVERALL + ESPR
# ======================================================
def compute_overall(passport):

    section_scores = []

    for section in passport["sections"].values():
        ratings = [f["rating"] for f in section["fields"].values()]
        section["section_rating"] = round(sum(ratings)/len(ratings), 2) if ratings else 0
        section_scores.append(section["section_rating"])

    passport["overall_rating"] = round(sum(section_scores)/len(section_scores), 2)

    # ESPR semplice e coerente
    if passport["overall_rating"] >= 0.7:
        passport["overall_espr"] = "OK"
    elif passport["overall_rating"] >= 0.4:
        passport["overall_espr"] = "PARTIAL"
    else:
        passport["overall_espr"] = "MISSING"

# ======================================================
# STORAGE
# ======================================================
def save_passport_to_file(passport):
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    path = os.path.join(PASSPORT_DIR, f"{passport['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(passport, f, indent=2, ensure_ascii=False)

def load_passport_from_file(passport_id):
    path = os.path.join(PASSPORT_DIR, f"{passport_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ======================================================
# QR
# ======================================================
def generate_qr_from_url(url):
    qr = qrcode.QRCode()
    qr.add_data(url)
    img = qr.make_image()
    buf = BytesIO()
    img.save(buf)
    buf.seek(0)
    return buf

# ======================================================
# UI
# ======================================================
def render_espr_compliance(passport):
    st.subheader("ESPR Compliance")

    for name, section in passport["sections"].items():
        score = section["section_rating"]
        emoji = "🟢" if score >= 0.7 else "🟡" if score >= 0.4 else "🔴"
        st.write(f"{name}: {emoji} {score}")

    st.markdown(f"**Overall:** {passport['overall_espr']}")
