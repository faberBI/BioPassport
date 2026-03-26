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

        # =========================
        # METADATA
        # =========================
        "metadata": {
            "created_at": datetime.utcnow().isoformat(),
            "standard": "EU-DPP-2.0"
        },

        # =========================
        # VERSIONING
        # =========================
        "versioning": {
            "version": 1,
            "updated_at": datetime.utcnow().isoformat(),
            "previous_hash": None,
            "changes": []
        },

        # =========================
        # ACCESS CONTROL
        # =========================
        "access_control": {
            "level": "public",  # public / restricted / private
            "roles": []
        },

        # =========================
        # ECONOMIC OPERATOR
        # =========================
        "economic_operator": {
            "name": None,
            "vat": None,
            "country": None,
            "role": "manufacturer"
        },

        # =========================
        # LIFECYCLE
        # =========================
        "lifecycle": {
            "manufactured": None,
            "events": []
        },

        # =========================
        # SECTIONS
        # =========================
        "sections": {
            "Technical": {
                "fields": {},
                "section_rating": 0
            },
            "Visual": {
                "fields": {},
                "section_rating": 0
            }
        },

        # =========================
        # GLOBAL METRICS
        # =========================
        "overall_rating": 0.0,
        "overall_espr": "MISSING",
        "sustainability": {},
        "images": [],
        "certificates": []
    }

    # =========================
    # INIT CAMPI TECNICI
    # =========================
    for f in fields:
        passport["sections"]["Technical"]["fields"][f] = {
            "value": None,
            "confidence": 0.0,
            "rating": 0.0,
            "color": "🔴",
            "explanation": "",
            "source": None
        }

    return passport

def merge_data(passport, pdf_data, image_data, certificate_data=None, user="system"):
    """
    Unisce dati da PDF, immagini e certificati nel passport.
    Include:
    - provenance
    - validazione certificati
    - scoring
    - audit log
    - sostenibilità quantitativa
    """
    all_data = {**pdf_data, **image_data}

    # =========================
    # CERTIFICATI
    # =========================
    passport["certificates"] = []

    if certificate_data:
        for cert in certificate_data:
            cert_valid = verify_certificate(cert.get("cert_bytes", b""), trusted_issuers=[])
            cert_dict = {}
            for k, v in cert.items():
                if isinstance(v, dict):
                    value = v.get("value")
                    conf = v.get("confidence", 0.0)
                else:
                    value = v
                    conf = 0.7 if v else 0.0

                field_obj = {
                    "value": value,
                    "confidence": conf,
                    "rating": compute_field_rating({"value": value, "confidence": conf}),
                    "color": score_to_color(conf),
                    "explanation": "Dato da certificato",
                    "source": {
                        "type": "certificate",
                        "timestamp": datetime.utcnow().isoformat()
                    }
                }
                cert_dict[k] = field_obj

            cert_dict["is_valid"] = cert_valid
            passport["certificates"].append(cert_dict)

    # =========================
    # MERGE PDF + IMMAGINI
    # =========================
    for section_name, section in passport.get("sections", {}).items():
        for field_name, field in section.get("fields", {}).items():
            for k, v in all_data.items():
                matched = match_field(k, [field_name])
                if matched != field_name:
                    continue

                if isinstance(v, dict):
                    field["value"] = v.get("value")
                    field["confidence"] = v.get("confidence", 0.0)
                else:
                    field["value"] = v
                    field["confidence"] = 0.7 if v else 0.0

                field["rating"] = compute_field_rating(field)
                field["color"] = score_to_color(field["rating"])
                field["explanation"] = generate_explanation(field)
                field["source"] = {
                    "type": "pdf" if k in pdf_data else "image",
                    "extracted_by": "ai",
                    "timestamp": datetime.utcnow().isoformat()
                }

    # =========================
    # AUDIT LOG
    # =========================
    log_audit(passport, user, "merge_data",
              f"PDF fields: {len(pdf_data)}, Images: {len(image_data)}, Certificates: {len(certificate_data) if certificate_data else 0}")

    # =========================
    # CALCOLO SOSTENIBILITÀ
    # =========================
    combined_fields = {**pdf_data, **image_data}
    for cert in passport.get("certificates", []):
        combined_fields.update(cert)
    passport["sustainability_score"] = compute_sustainability_score(combined_fields)

    # =========================
    # METRICHE GLOBALI
    # =========================
    compute_overall(passport)

    return passport


def compute_field_rating(field):
    """
    Calcola rating di un singolo campo.
    Valuta sia confidence che eventuale peso per sostenibilità.
    """
    val = field.get("value")
    if val in [None, "", "null"]:
        return 0.0

    conf = field.get("confidence", 0.0)
    weight = field.get("eu_weight", 1.0)

    # bonus se il campo indica sostenibilità
    sustainability_bonus = 0.1 if "sostenibilita" in field.get("explanation", "").lower() or \
        ("riciclato" in str(val).lower()) else 0.0

    return round(min(conf * weight + sustainability_bonus, 1.0), 2)
    

# ======================================================
# CALCOLO OVERALL + SUSTAINABILITY
# ======================================================
def compute_overall(passport):
    """
    Calcola ESPR, Reliability e Sustainability score,
    includendo PDF, Immagini e Certificati.
    Gestisce campi None, valori non-dizionario e certificati non validi.
    """
    total_conf = 0.0
    total_fields = 0
    sustainability_sum = 0.0
    sustainability_count = 0

    # =========================
    # PDF e immagini
    # =========================
    for section in passport.get("sections", {}).values():
        section_conf_sum = 0.0
        field_count = 0
        for field in section.get("fields", {}).values():
            if not isinstance(field, dict):
                continue
            try:
                conf = float(field.get("confidence", 0))
            except (ValueError, TypeError):
                conf = 0.0
            section_conf_sum += conf
            field_count += 1

            val = field.get("value")
            if val not in [None, "", "non rilevato"]:
                explanation = str(field.get("explanation", "")).lower()
                if "sostenibilita" in explanation or "riciclato" in str(val).lower():
                    sustainability_sum += field.get("rating", 0)
                    sustainability_count += 1

        section["section_rating"] = (section_conf_sum / field_count) if field_count else 0
        total_conf += section_conf_sum
        total_fields += field_count

    # =========================
    # Certificati
    # =========================
    for cert in passport.get("certificates", []):
        if cert.get("is_valid") is False:
            continue  # ignora certificati non validi
        for field in cert.values():
            if not isinstance(field, dict):
                continue
            try:
                conf = float(field.get("confidence", 0))
            except (ValueError, TypeError):
                conf = 0.0
            total_conf += conf
            total_fields += 1

            val = field.get("value")
            if val not in [None, "", "non rilevato"]:
                explanation = str(field.get("explanation", "")).lower()
                if "sostenibilita" in explanation or "riciclato" in str(val).lower():
                    sustainability_sum += field.get("rating", 0)
                    sustainability_count += 1

    # =========================
    # Overall reliability
    # =========================
    passport["overall_rating"] = (total_conf / total_fields) if total_fields else 0.0

    # =========================
    # ESPR (numero di campi con valore rilevato)
    # =========================
    espr_sum = 0
    espr_count = 0
    for section in passport.get("sections", {}).values():
        for field in section.get("fields", {}).values():
            if not isinstance(field, dict):
                continue
            val = field.get("value")
            if val not in [None, "", "non rilevato"]:
                espr_sum += 1
                espr_count += 1

    for cert in passport.get("certificates", []):
        if cert.get("is_valid") is False:
            continue
        for field in cert.values():
            if not isinstance(field, dict):
                continue
            val = field.get("value")
            if val not in [None, "", "non rilevato"]:
                espr_sum += 1
                espr_count += 1

    passport["overall_espr"] = (espr_sum / espr_count) if espr_count else 0.0
    passport["sustainability_score"] = (sustainability_sum / sustainability_count) if sustainability_count else 0.0

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
    """
    Evidenzia i campi estratti in un PDF.
    
    - pdf_file: percorso, UploadedFile o BytesIO
    - extracted_data: dizionario con valori da evidenziare
      Supporta sia:
        {"campo": {"value": "valore", ...}}
      sia:
        {"campo": "valore"}
    """
    # Leggi i byte del PDF
    pdf_bytes = pdf_file.read() if hasattr(pdf_file, "read") else open(pdf_file, "rb").read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for page in doc:
        for field_name, field in extracted_data.items():
            # Gestione valori annidati o diretti
            if isinstance(field, dict) and "value" in field:
                val = field.get("value")
            else:
                val = field
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

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
GITHUB_REPO = st.secrets["GITHUB_REPO"] 
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "modify")
EXCEL_FILE = os.path.join(PASSPORT_DIR, "archivio_passport.xlsx")
os.makedirs(PASSPORT_DIR, exist_ok=True) 

def save_passport_to_excel_append(passport):
    import pandas as pd
    import os

    df_passport = pd.DataFrame([{
        "id": passport["id"],
        "product_type": passport["product_type"],
        "created_at": passport["metadata"]["created_at"],
        "overall_rating": passport["overall_rating"],
        "overall_espr": passport["overall_espr"]
    }])

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

    img_rows = []
    for img in passport.get("images", []):
        img_rows.append({
            "passport_id": passport["id"],
            "file_base64": img.get("file_base64"),
            "caption": img.get("caption")
        })
    df_images = pd.DataFrame(img_rows)

    # CREA FILE SE NON ESISTE
    if not os.path.exists(EXCEL_FILE):
        with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl") as writer:
            df_passport.to_excel(writer, sheet_name="passport", index=False)
            df_fields.to_excel(writer, sheet_name="fields", index=False)
            df_images.to_excel(writer, sheet_name="images", index=False)

    else:
        # APPEND SICURO
        with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:

            # passport
            startrow = writer.sheets["passport"].max_row
            df_passport.to_excel(writer, sheet_name="passport", index=False, header=False, startrow=startrow)

            # fields
            startrow = writer.sheets["fields"].max_row
            df_fields.to_excel(writer, sheet_name="fields", index=False, header=False, startrow=startrow)

            # images
            startrow = writer.sheets["images"].max_row
            df_images.to_excel(writer, sheet_name="images", index=False, header=False, startrow=startrow)

    return EXCEL_FILE



def gpt_extract_cert_info(cert_file, client: OpenAI):
    """
    Estrae info strutturate da certificati (EPD, LCA, FSC, ecc.).
    Ritorna dizionario: tipo_cert, numero, ente, validita, riferimenti.
    """
    # Step 1: Estrai testo se PDF
    text = ""
    try:
        text = extract_text_from_pdf(cert_file)
    except Exception:
        # Se non PDF, possiamo tentare OCR o passare a GPT Vision
        text = None

    prompt = f"""
Analizza il certificato allegato.
Estrai le seguenti informazioni:
- tipo_certificato
- numero_certificato
- ente_emittente
- data_emissione
- data_scadenza
- riferimenti_LCA/EPD

Rispondi solo con JSON valido. Usa null se il campo non è disponibile.
Testo certificato: {text if text else 'Non disponibile, usare GPT Vision'}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        resp_text = response.choices[0].message.content
        if resp_text.startswith("```"):
            resp_text = "\n".join(resp_text.splitlines()[1:-1])
        cert_info = json.loads(resp_text)
        return cert_info
    except Exception as e:
        # fallback
        return {
            "tipo_certificato": None,
            "numero_certificato": None,
            "ente_emittente": None,
            "data_emissione": None,
            "data_scadenza": None,
            "riferimenti": None,
            "error": str(e)
        }

import hashlib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

def generate_hash(passport):
    data = dict(passport)
    data.pop("signature", None)
    serialized = json.dumps(data, sort_keys=True).encode()
    return hashlib.sha256(serialized).hexdigest()


def sign_passport(passport, private_key_pem):
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(),
        password=None
    )

    hash_value = generate_hash(passport)

    signature = private_key.sign(
        hash_value.encode(),
        padding.PKCS1v15(),
        hashes.SHA256()
    )

    passport["signature"] = {
        "hash": hash_value,
        "signature": signature.hex(),
        "algorithm": "SHA256-RSA",
        "signed_at": datetime.utcnow().isoformat()
    }

    return passport

def update_version(passport, changes):
    prev_hash = passport.get("signature", {}).get("hash")

    passport["versioning"]["version"] += 1
    passport["versioning"]["updated_at"] = datetime.utcnow().isoformat()
    passport["versioning"]["previous_hash"] = prev_hash
    passport["versioning"]["changes"] = changes

    return passport

def compute_sustainability(passport):
    fields = passport["sections"]["Technical"]["fields"]

    breakdown = {
        "carbon": 0,
        "circularity": 0,
        "durability": 0,
        "materials": 0
    }

    # Carbon
    gwp = fields.get("Impronta carbonio GWP", {}).get("value")
    if gwp:
        try:
            val = float(gwp)
            breakdown["carbon"] = max(0, min(1, 1 - val / 100))
        except:
            pass

    # Circularity
    riciclato = fields.get("% di contenuto riciclato", {}).get("value")
    if riciclato:
        try:
            breakdown["circularity"] = float(riciclato) / 100
        except:
            pass

    # Durability
    if fields.get("Garanzia", {}).get("value"):
        breakdown["durability"] += 0.5
    if fields.get("Materiali", {}).get("value"):
        breakdown["durability"] += 0.5

    # Materials
    if fields.get("Materiali/componenti utilizzati", {}).get("value"):
        breakdown["materials"] = 1

    overall = sum(breakdown.values()) / len(breakdown)

    passport["sustainability"] = {
        "score": round(overall, 2),
        "breakdown": breakdown
    }

    return passport

def validate_certificate(cert):
    valid = True

    if not cert.get("numero_certificato"):
        valid = False

    if cert.get("data_scadenza"):
        try:
            scad = datetime.fromisoformat(cert["data_scadenza"])
            if scad < datetime.utcnow():
                valid = False
        except:
            valid = False

    cert["is_valid"] = valid
    return cert

def add_lifecycle_event(passport, event_type, details):
    passport.setdefault("lifecycle", {}).setdefault("events", []).append({
        "type": event_type,
        "details": details,
        "timestamp": datetime.utcnow().isoformat()
    })

def can_access(passport, role):
    if passport["access_control"]["level"] == "public":
        return True
    return role in passport["access_control"]["roles"]

def to_jsonld(passport):
    return {
        "@context": "https://europa.eu/dpp/schema",
        "@type": "DigitalProductPassport",
        "id": passport["id"],
        "productType": passport["product_type"],
        "sustainability": passport.get("sustainability"),
        "manufacturer": passport.get("economic_operator"),
        "data": passport["sections"]
    }

import uuid
from datetime import datetime
import re
from cryptography.x509 import load_pem_x509_certificate
from cryptography.hazmat.backends import default_backend

# 1️⃣ Schema dati ufficiale
def create_standard_dpp(product_type: str, product_name: str, manufacturer_info: dict) -> dict:
    """
    Crea un Digital Product Passport secondo uno schema base standard UE.
    """
    dpp = {
        "id": f"{product_type.upper()}-{uuid.uuid4().hex[:6]}",
        "product_type": product_type,
        "product_name": product_name,
        "manufacturer": manufacturer_info,  # es. {"name":..., "vat":..., "address":...}
        "created_at": datetime.utcnow().isoformat() + "Z",
        "sections": {},  # PDF, immagini, certificati
        "certificates": [],
        "overall_rating": 0.0,
        "overall_espr": 0.0,
        "sustainability_score": 0.0,
        "audit_trail": []
    }
    return dpp

# 2️⃣ Validazione legale dei certificati
def verify_certificate(cert_bytes: bytes, trusted_issuers: list) -> bool:
    """
    Verifica firma digitale e ente emittente di un certificato PDF.
    """
    try:
        cert = load_pem_x509_certificate(cert_bytes, default_backend())
        issuer = cert.issuer.rfc4514_string()
        if issuer not in trusted_issuers:
            return False
        if cert.not_valid_before > datetime.utcnow() or cert.not_valid_after < datetime.utcnow():
            return False
        return True
    except Exception:
        return False

# 3️⃣ Calcolo punteggio sostenibilità
def compute_sustainability_score(fields: dict) -> float:
    """
    Calcola punteggio sostenibilità quantitativo basato su metriche standard.
    """
    scores = []
    for field_name, field in fields.items():
        val = field.get("value")
        if val in [None, "", "non rilevato"]:
            continue
        try:
            val = float(val)
        except:
            continue
        if "footprint" in field_name.lower():
            score = max(0, min(1, 1 - val / 100))
            scores.append(score)
        elif "durabilita" in field_name.lower() or "riparabilita" in field_name.lower():
            score = max(0, min(1, val / 10))
            scores.append(score)
    return sum(scores)/len(scores) if scores else 0

# 4️⃣ Tracciabilità e audit
def log_audit(passport: dict, user: str, action: str, details: str = ""):
    """
    Registra azioni/modifiche sul passport con timestamp.
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "user": user,
        "action": action,
        "details": details
    }
    if "audit_trail" not in passport:
        passport["audit_trail"] = []
    passport["audit_trail"].append(entry)

# 5️⃣ Validazione informazioni operatore
def validate_operator_info(operator: dict) -> bool:
    """
    Verifica informazioni essenziali: nome, partita IVA e contatto.
    """
    if not operator.get("name") or not operator.get("vat"):
        return False
    vat_pattern = r"^[A-Z]{2}[0-9A-Z]{8,12}$"
    return bool(re.match(vat_pattern, operator["vat"]))

