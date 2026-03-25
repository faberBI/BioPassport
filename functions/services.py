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
import pyodbc
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import yellow

# ======================================================
# CONFIG
# ======================================================
PASSPORT_DIR = "passports"
PRODUCT_FIELDS = {
    "mobile": {
        "pdf": [
            {"name":"Nome prodotto", "required": True},
            {"name":"Numero di modello", "required": True},
            {"name":"Produttore", "required": True},
            {"name":"Materiali", "required": True},
            {"name":"Dimensioni", "required": False},
            {"name":"Lotto di produzione", "required": False},
            {"name":"Anno di produzione", "required": False},
            {"name":"Certificazione di sicurezza", "required": True},
            {"name":"Certificazione di sostenibilita", "required": True},
            {"name":"Descrizione prodotto", "required": False},
            {"name":"Luogo di produzione", "required": False},
            {"name":"Manutenzione e cura", "required": False},
            {"name":"Materiali/componenti utilizzati", "required": True},
            {"name":"Specie legnosa", "required": False},
            {"name":"% di contenuto riciclato", "required": True},
            {"name":"Sostanze preoccupanti", "required": True},
            {"name":"Finitura superficiale", "required": False},
            {"name":"Marchio", "required": False},
            {"name":"Garanzia", "required": False},
            {"name":"Certificazioni materiale", "required": False},
            {"name":"Impronta carbonio GWP", "required": False},
            {"name":"Prezzo", "required": False},
            {"name":"Identificativo operatore", "required": False},
            {"name":"Conformità tecnica", "required": True},
            {"name":"Gestione fine vita (codice CER)", "required": True}
        ],
        "image": [
            {"name":"Colore", "required": True},
            {"name":"Condizioni", "required": True}
        ]
    },
    "lampada": {
        "pdf": [
            {"name":"nome_prodotto", "required": True},
            {"name":"produttore", "required": True},
            {"name":"materiale", "required": True},
            {"name":"wattaggio", "required": True}
        ],
        "image": [
            {"name":"tipologia_prodotto", "required": True},
            {"name":"colore", "required": True},
            {"name":"stile", "required": False}
        ]
    },
    "bicicletta": {
        "pdf": [
            {"name":"nome_prodotto", "required": True},
            {"name":"produttore", "required": True},
            {"name":"modello", "required": True},
            {"name":"anno_produzione", "required": False}
        ],
        "image": [
            {"name":"colore_telaio", "required": True},
            {"name":"condizioni", "required": True}
        ]
    }
}
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
    pages = []
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            pages.append({"page": i+1, "text": txt})
    return pages

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
# CONFIDENCE / EXPLANATION
# ======================================================
def compute_confidence(values):
    if not values:
        return 0.0
    most_common = max(set(values), key=values.count)
    return round(values.count(most_common) / len(values), 2)

def generate_explanation(field):
    if field["value"] in [None, "", "null"]:
        return "Dato mancante"
    if field.get("confidence", 0) < 0.5:
        return "Bassa confidenza"
    return "Dato affidabile"

# ======================================================
# GPT PDF EXTRACTION
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
# GPT IMAGE ANALYSIS
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
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "file_id": file_id}
                ]
            }]
        )

        # ✅ Usa resp.output_parsed se disponibile
        if hasattr(resp, "output_parsed") and resp.output_parsed:
            data = resp.output_parsed
        else:
            # fallback: estrai tutto il testo e prova a fare json.loads
            text = "".join([m.text for m in resp.output if hasattr(m, "text")])
            data = json.loads(text) if text else {}

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
# RATING / COLOR
# ======================================================
def compute_field_rating(field):
    val = field.get("value")
    if val in [None, "", "null"]:
        return 0.0
    conf = field.get("confidence", 0.0)
    weight = field.get("eu_weight", 1.0)
    return round(conf * weight, 2)

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
# MERGE DATA
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
    if passport["overall_rating"] >= 0.7:
        passport["overall_espr"] = "OK"
    elif passport["overall_rating"] >= 0.4:
        passport["overall_espr"] = "PARTIAL"
    else:
        passport["overall_espr"] = "MISSING"

# ======================================================
# STORAGE JSON
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
# ESPR UI
# ======================================================
def render_espr_compliance(passport):
    st.subheader("ESPR Compliance")
    for name, section in passport["sections"].items():
        score = section["section_rating"]
        emoji = "🟢" if score >= 0.7 else "🟡" if score >= 0.4 else "🔴"
        st.write(f"{name}: {emoji} {score}")
    st.markdown(f"**Overall:** {passport['overall_espr']}")

# ======================================================
# SAVE TO ACCESS DB
# ======================================================
def get_db_connection():
    conn = pyodbc.connect(
        r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};'
        r'DBQ=database/dpp.accdb;'
    )
    return conn

def save_passport_to_access(passport):
    conn = get_db_connection()
    cursor = conn.cursor()

    # passport
    cursor.execute("""
        INSERT INTO passports (id, product_type, created_at, overall_rating, overall_espr)
        VALUES (?, ?, ?, ?, ?)
    """,
    passport["id"],
    passport["product_type"],
    passport["metadata"]["created_at"],
    passport["overall_rating"],
    passport["overall_espr"])

    # fields
    for section_name, section in passport["sections"].items():
        for field_name, field in section["fields"].items():
            cursor.execute("""
                INSERT INTO fields (passport_id, section, field_name, value, confidence, rating, explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            passport["id"],
            section_name,
            field_name,
            str(field.get("value")),
            field.get("confidence", 0),
            field.get("rating", 0),
            field.get("explanation", ""))

    # images
    for img in passport.get("images", []):
        cursor.execute("""
            INSERT INTO images (passport_id, image_base64)
            VALUES (?, ?)
        """,
        passport["id"],
        img["file_base64"])

    conn.commit()
    conn.close()


import fitz  # PyMuPDF

def highlight_pdf_fields(pdf_file, fields_dict, output_path="highlighted.pdf"):
    """
    Evidenzia i valori dei campi estratti nel PDF.
    
    pdf_file: file-like o path del PDF originale
    fields_dict: dict dei campi estratti {field_name: {"value":..., "explanation":..., "confidence":...}}
    output_path: path PDF evidenziato
    """
    doc = fitz.open(pdf_file)

    for page in doc:
        text_instances = page.get_text("words")  # lista di tuple: x0, y0, x1, y1, "word", block_no, line_no, word_no

        for field_name, info in fields_dict.items():
            val = str(info.get("value") or "").strip()
            if not val:
                continue

            # cerca tutte le occorrenze del valore
            for inst in text_instances:
                x0, y0, x1, y1, word = inst[:5]
                if val.lower() in word.lower():
                    highlight = page.add_rect_annot([x0, y0, x1, y1])
                    highlight.set_colors(stroke=(1, 1, 0))  # giallo
                    highlight.update()

    doc.save(output_path)
    return output_path
