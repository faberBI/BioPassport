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
import fitz 
import pandas as pd
import openpyxl
from openpyxl import load_workbook
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
    """
    Calcola la confidenza di un campo basandosi sui valori estratti.
    Restituisce 0 se la lista è vuota.
    """
    if not values:
        return 0.0  # Nessun dato → confidenza 0
    most_common = max(set(values), key=values.count)
    confidence = values.count(most_common) / len(values)
    return confidence

# ======================================================
# GPT PDF EXTRACTION
# ======================================================
def gpt_extract_from_pdf(text, client: OpenAI, tipo, fields):
    chunks = split_text(text)
    results = []

    for chunk in chunks:
        prompt = f"""
Estrai dati tecnici del prodotto ({tipo}).
Rispondi SOLO con JSON valido. Usa null se non presente.
Campi: {json.dumps(fields)}

Testo: {chunk}
"""
        try:
            r = client.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            resp_text = r.choices[0].message.content
            if resp_text.startswith("```"):
                resp_text = "\n".join(resp_text.splitlines()[1:-1])
            results.append(json.loads(resp_text))
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
    """
    Analizza l'immagine del prodotto e restituisce un dizionario completo
    con value, confidence e explanation per ogni campo.
    """
    campi = ["colore", "condizioni", "materiale_probabile", "categoria_visiva", "segni_usura"]

    prompt = f"""
Analizza immagine prodotto {tipo}.
Estrai i seguenti campi: colore, condizioni, materiale_probabile, categoria_visiva, segni_usura.
Rispondi con JSON valido.
Usa null se non determinabile.
"""

    def safe_json_parse(text):
        if text.startswith("```"):
            text = "\n".join([l for l in text.splitlines() if not l.strip().startswith("```")])
        first, last = text.find("{"), text.rfind("}")
        return json.loads(text[first:last+1])

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
        data_raw = safe_json_parse(resp.output_text.strip())

        # costruzione dizionario completo
        result = {}
        for c in campi:
            val = data_raw.get(c, None)
            result[c.capitalize()] = {
                "value": val if val not in [None, "", "null"] else "non rilevato",
                "confidence": 0.7 if val not in [None, "", "null"] else 0.0,
                "explanation": "Dato estratto da immagine" if val not in [None, "", "null"] else "Non rilevabile"
            }

        return result

    except Exception as e:
        st.error(f"Errore GPT Image: {e}")
        # se fallisce ritorna dizionario "vuoto"
        result = {}
        for c in campi:
            result[c.capitalize()] = {
                "value": "non rilevato",
                "confidence": 0.0,
                "explanation": "Non rilevabile"
            }
        return result

def upload_image_to_openai(image_file, client):
    resized = resize_image_for_vision(image_file)
    uploaded = client.files.create(file=resized, purpose="vision")
    return uploaded.id

# ======================================================
# FIELD RATING / EXPLAINABILITY
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
# ADD PRODUCT IMAGE
# ======================================================
def add_product_image(passport, image_file, caption=None):
    """
    Aggiunge un'immagine al passport.
    image_file può essere un UploadedFile (Streamlit) o PIL Image.
    """
    try:
        # Se è UploadedFile di Streamlit
        if hasattr(image_file, "read"):
            img = Image.open(image_file).convert("RGB")
        else:
            img = image_file

        buf = BytesIO()
        img.save(buf, format="JPEG")
        img_base64 = base64.b64encode(buf.getvalue()).decode()

        passport.setdefault("images", []).append({
            "file_base64": img_base64,
            "caption": caption or "Immagine prodotto",
            "annotation": ""
        })
    except Exception as e:
        import streamlit as st
        st.error(f"Errore add_product_image: {e}")

# ======================================================
# PASSPORT
# ======================================================
def initialize_passport(product_id, product_type, fields):
    passport = {
        "id": product_id,
        "product_type": product_type,
        "metadata": {"created_at": datetime.utcnow().isoformat(), "version": "EU-DPP-2.0"},
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

def compute_overall(passport):
    """
    Calcola l'overall ESPR e Reliability del passport
    sulla base dei campi validati.
    Aggiorna passport["overall_espr"] e passport["overall_rating"].
    """
    total_conf = 0
    total_fields = 0

    # Cicla tutte le sezioni e campi
    for section_name, section in passport["sections"].items():
        section_conf_sum = 0
        field_count = 0
        for fname, field in section["fields"].items():
            conf = field.get("confidence", 0)
            # Se confidence non è presente, default a 0
            try:
                conf = float(conf)
            except:
                conf = 0
            section_conf_sum += conf
            field_count += 1

        # Aggiorna rating se ci sono campi
        if field_count > 0:
            section["section_rating"] = section_conf_sum / field_count
        else:
            section["section_rating"] = 0

        total_conf += section_conf_sum
        total_fields += field_count

    # Overall reliability
    passport["overall_rating"] = (total_conf / total_fields) if total_fields > 0 else 0

    # Calcolo ESPR: media dei valori dei campi qualitativi
    # Se vuoi usare un criterio più avanzato, puoi mappare i valori testuali a punteggi numerici
    espr_sum = 0
    espr_count = 0
    for section in passport["sections"].values():
        for field in section["fields"].values():
            val = field.get("value")
            # esempio semplificato: se il campo ha valore 'ok' = 1, altro = 0
            if val is not None:
                espr_sum += 1 if str(val).lower() not in ["non rilevato", "missing", ""] else 0
                espr_count += 1
    passport["overall_espr"] = (espr_sum / espr_count) if espr_count > 0 else 0

    return passport

# ======================================================
# STORAGE FILE / ACCESS
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

def get_db_connection():
    conn = pyodbc.connect(
        r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=database/dpp.accdb;'
    )
    return conn

def save_passport_to_access(passport):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO passports (id, product_type, created_at, overall_rating, overall_espr) VALUES (?, ?, ?, ?, ?)",
        passport["id"], passport["product_type"], passport["metadata"]["created_at"], passport["overall_rating"], passport["overall_espr"]
    )
    for section_name, section in passport["sections"].items():
        for field_name, field in section["fields"].items():
            cursor.execute(
                "INSERT INTO fields (passport_id, section, field_name, value, confidence, rating, explanation) VALUES (?, ?, ?, ?, ?, ?, ?)",
                passport["id"], section_name, field_name, str(field.get("value")), field.get("confidence",0), field.get("rating",0), field.get("explanation","")
            )
    for img in passport.get("images", []):
        cursor.execute("INSERT INTO images (passport_id, image_base64) VALUES (?, ?)", passport["id"], img["file_base64"])
    conn.commit()
    conn.close()

# ======================================================
# QR CODE
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
# UI / ESPR
# ======================================================
def render_espr_compliance(passport):
    st.subheader("ESPR Compliance")
    for name, section in passport["sections"].items():
        score = section["section_rating"]
        emoji = "🟢" if score >= 0.7 else "🟡" if score >= 0.4 else "🔴"
        st.write(f"{name}: {emoji} {score}")
    st.markdown(f"**Overall:** {passport['overall_espr']}")

# ======================================================
# HIGHLIGHT PDF FIELDS
# ======================================================
def highlight_pdf_fields(pdf_file, extracted_data):
    # Supporta UploadedFile o path
    pdf_bytes = pdf_file.read() if hasattr(pdf_file, "read") else open(pdf_file, "rb").read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        for field_name, field in extracted_data.items():
            val = field.get("value")
            if val:
                text_instances = page.search_for(str(val))
                for inst in text_instances:
                    highlight = page.add_highlight_annot(inst)
                    highlight.set_colors(stroke=(1, 1, 0))  # giallo
                    highlight.update()
    out = BytesIO()
    doc.save(out)
    out.seek(0)
    doc.close()
    return out



# ======================================================
# CREAZIONE ARCHIVO SU EXCEL
# ======================================================
EXCEL_FILE = os.path.join(DATA_DIR, "archivio_passport.xlsx")

def save_passport_to_excel_append(passport):
    df_passport = pd.DataFrame([{
        "id": passport["id"],
        "product_type": passport["product_type"],
        "created_at": passport["metadata"]["created_at"],
        "overall_rating": passport["overall_rating"],
        "overall_espr": passport["overall_espr"]
    }])
    # Fields sheet
    rows = []
    for section_name, section in passport["sections"].items():
        for field_name, field in section["fields"].items():
            rows.append({
                "passport_id": passport["id"],
                "section": section_name,
                "field_name": field_name,
                "value": field.get("value"),
                "confidence": field.get("confidence"),
                "rating": field.get("rating"),
                "explanation": field.get("explanation")
            })
    df_fields = pd.DataFrame(rows)

    # Images sheet
    img_rows = []
    for img in passport.get("images", []):
        img_rows.append({
            "passport_id": passport["id"],
            "file_base64": img.get("file_base64"),
            "caption": img.get("caption")
        })
    df_images = pd.DataFrame(img_rows)

    # Se il file non esiste, crealo da zero
    if not os.path.exists(EXCEL_FILE):
        with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl") as writer:
            df_passport.to_excel(writer, sheet_name="passport", index=False)
            df_fields.to_excel(writer, sheet_name="fields", index=False)
            df_images.to_excel(writer, sheet_name="images", index=False)
    else:
        # Apri il workbook esistente
        wb = load_workbook(EXCEL_FILE)
        with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl") as writer:
            writer.book = wb
            writer.sheets = {ws.title: ws for ws in wb.worksheets}

            startrow_passport = wb["passport"].max_row
            df_passport.to_excel(writer, sheet_name="passport", index=False, header=False, startrow=startrow_passport)

            startrow_fields = wb["fields"].max_row
            df_fields.to_excel(writer, sheet_name="fields", index=False, header=False, startrow=startrow_fields)

            startrow_images = wb["images"].max_row
            df_images.to_excel(writer, sheet_name="images", index=False, header=False, startrow=startrow_images)

            writer.save()

    return EXCEL_FILE
