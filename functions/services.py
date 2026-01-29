import pdfplumber
import json
import base64
import qrcode
import os
from io import BytesIO
from openai import OpenAI
import streamlit as st
from PIL import Image
import io

# ======================================================
# CONFIG
# ======================================================
PASSPORT_DIR = "passports"

PRODUCT_FIELDS = {
    "mobile": {
        "pdf": ["Nome prodotto","Numero di modello","Produttore","Materiali","Dimensioni","Lotto di produzione ","Anno di produzione", "Certificazione di sicurezza", "Certificazione di sostenibilita", "Descrizione prodotto", "Luogo di produzione", "Manutenzione e cura", "Materiali/componenti utilizzati", "Specie legnosa","% di contenuto riciclato", "Sostanze preoccupanti", "Finitura superficiale", "Marchio", "Garanzia", "Certificazioni materiale", " Impronta carbonio gwp" ,  "Prezzo",
               "Identificativo operatore", "Conformità tecnica", "Gestione fine vita (codice CER)"],
        "image": ["Colore","Condizioni"]
    },
    "lampada": {
        "pdf": ["nome_prodotto","produttore","materiale","wattaggio"],
        "image": ["tipologia_prodotto","colore","stile"]
    },
    "bicicletta": {
        "pdf": ["nome_prodotto","produttore","modello","anno_produzione"],
        "image": ["colore_telaio","condizioni"]
    }
}

# ======================================================
# PDF / IMAGE UTILITIES
# ======================================================
def extract_text_from_pdf(pdf_file):
    """Estrae tutto il testo da un PDF."""
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def image_to_base64(image_file):
    """Converte un file o un PIL Image in base64 per invio a GPT o salvataggio."""
    import io
    import base64

    if hasattr(image_file, "getvalue"):  # file-like object
        return base64.b64encode(image_file.getvalue()).decode()
    else:  # probabilmente un PIL.Image
        buf = io.BytesIO()
        image_file.save(buf, format="JPEG")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()


# ======================================================
# GPT EXTRACTION
# ======================================================
def gpt_extract_from_pdf(text, client: OpenAI, tipo):
    """Estrae dati tecnici dal PDF tramite GPT, in modo robusto."""
    campi = PRODUCT_FIELDS[tipo]["pdf"]
    prompt = f"""
Estrai dati tecnici di un {tipo}.
Se un dato manca usa null.
NON inventare.
Restituisci SOLO JSON con: {', '.join(campi)}

TESTO:
{text}
"""
    try:
        r = client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        resp_text = r.choices[0].message.content.strip()

        # Rimuove eventuali blocchi ```json ... ```
        if resp_text.startswith("```"):
            resp_text = "\n".join(resp_text.split("\n")[1:-1]).strip()

        data = json.loads(resp_text)
        # Assicura che tutti i campi siano presenti
        for c in campi:
            if c not in data:
                data[c] = None

        return data

    except json.JSONDecodeError:
        st.error("GPT non ha restituito JSON valido. Ecco la risposta grezza:")
        st.code(resp_text)
        # Ritorna comunque un dizionario con tutti i campi a None
        return {c: None for c in campi}
    except Exception as e:
        st.error(f"Errore GPT: {e}")
        st.stop()


import json
import streamlit as st
from openai import OpenAI

def gpt_analyze_image(image_file, client: "OpenAI", tipo: str):
    import json
    import streamlit as st

    # Chiavi come devono essere nel form / passport
    campi = ["Tipologia di prodotto", "Colore", "Condizioni"]

    prompt = f"""
Analizza visivamente l'immagine del prodotto di tipo "{tipo}".

Restituisci SOLO JSON valido con i campi:
- colore
- condizioni

Se non determinabile, usa null.
NON scrivere altro testo.

Esempio:
{{"tipologia prodotto": "mobile", "colore": "bianco", "condizioni": "nuovo"}}
"""

    def safe_json_parse(text):
        """Rimuove blocchi ``` e testo extra da GPT e ritorna dict"""
        # Rimuove ```json ... ``` se presenti
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()

        # Rimuove eventuale testo extra prima/dopo JSON
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1:
            text = text[first_brace:last_brace+1]

        return json.loads(text)

    try:
        # 1️⃣ upload immagine su OpenAI
        file_id = upload_image_to_openai(image_file, client)

        # 2️⃣ chiedi a GPT di analizzare l'immagine
        response = client.responses.create(
            model="gpt-4o",
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "file_id": file_id}
                ]
            }]
        )

        result_text = response.output_text.strip()
        data_raw = safe_json_parse(result_text)

        # 🔹 mapping GPT → chiavi form
        mapping = {
            "colore": "Colore",
            "condizioni": "Condizioni"
        }

        data = {}
        for gpt_key, form_key in mapping.items():
            val = data_raw.get(gpt_key, None)
            if val is None or str(val).strip().lower() in ["null", ""]:
                data[form_key] = "non rilevato"
            else:
                data[form_key] = str(val).strip()

        return data

    except json.JSONDecodeError:
        st.error("GPT non ha restituito JSON valido")
        st.code(result_text)
        return {k: "non rilevato" for k in campi}

    except Exception as e:
        st.error(f"Errore GPT Image: {e}")
        st.stop()




# ======================================================
# VALIDATION FORM
# ======================================================

def render_validation_form(data, title: str):
    """
    Crea un form Streamlit per validare manualmente i dati estratti.
    Supporta:
    - valori singoli
    - liste
    - dizionari annidati
    Con expander per ogni livello annidato.
    """
    st.subheader(title)
    validated = {}

    def render_item(key, value, parent=""):
        full_key = f"{parent} > {key}" if parent else key

        if isinstance(value, dict):
            # Crea un expander per ogni dizionario annidato
            with st.expander(full_key, expanded=False):
                for k, v in value.items():
                    render_item(k, v, full_key)
        elif isinstance(value, list):
            # Mostra lista come testo modificabile
            val_str = ", ".join(map(str, value)) if value else "non rilevato"
            validated[full_key] = st.text_area(full_key, val_str, height=50)
        else:
            # Valore singolo
            validated[full_key] = st.text_input(full_key, "" if value is None else str(value))

    for k, v in data.items():
        render_item(k, v)

    return validated



# ======================================================
# PASSPORT STORAGE
# ======================================================
def save_passport_to_file(passport):
    """Salva passport JSON su disco."""
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    path = os.path.join(PASSPORT_DIR, f"{passport['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(passport, f, indent=2, ensure_ascii=False)

def load_passport_from_file(passport_id):
    """Carica passport JSON da disco."""
    path = os.path.join(PASSPORT_DIR, f"{passport_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ======================================================
# QR CODE
# ======================================================
def generate_qr_from_url(url):
    """Genera QR code da un URL e ritorna BytesIO pronto per Streamlit."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4
    )
    qr.add_data(url)
    qr.make(fit=True)
    buf = BytesIO()
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(buf)
    buf.seek(0)
    return buf

def upload_image_to_openai(image_file, client):
    resized = resize_image_for_vision(image_file)

    uploaded = client.files.create(
        file=resized,
        purpose="vision"
    )
    return uploaded.id


from PIL import Image
from io import BytesIO

def resize_image_for_vision(image_file, max_size=512):
    img = Image.open(image_file).convert("RGB")
    img.thumbnail((max_size, max_size))

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)

    # risalva in formato jpg
    buf.name = "image.jpg"

    return buf

def safe_json_parse(text):
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    return json.loads(text)

# ======================================================
# RATING / COMPLIANCE
# ======================================================
def compute_field_rating(field, type_weight_map=None):
    """
    Calcola il rating di un campo (0-1) basato su:
    - presenza/valore reale
    - confidence
    - tipo campo
    - peso EU
    """
    if type_weight_map is None:
        type_weight_map = {"technical":1.0, "declaration":0.6, "lca":0.5, "visual":0.4}

    # Se il campo è vuoto o None → rating 0
    value = field.get("value")
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return 0.0

    confidence = field.get("confidence", 0.0) or 0.0
    field_type = field.get("field_type", "declaration")
    eu_weight = field.get("eu_weight", 1.0)

    type_weight = type_weight_map.get(field_type, 0.5)
    rating = round(confidence * type_weight * eu_weight, 2)
    return rating



def score_to_color(score):
    """
    Converte il rating numerico in colore:
    🟢 >= 0.7
    🟡 >= 0.4
    🔴 < 0.4
    """
    if score >= 0.7:
        return "🟢"
    elif score >= 0.4:
        return "🟡"
    else:
        return "🔴"


def compute_espr_compliance(section_fields, section_schema):
    """
    Calcola lo stato di compliance di una sezione:
    - OK: tutti i campi obbligatori >= 0.5
    - PARTIAL: almeno 50% dei campi obbligatori >=0.5
    - MISSING: meno del 50% dei campi obbligatori
    """
    if not isinstance(section_fields, dict):
        return "MISSING"

    required_fields = [k for k, v in section_schema.items() if isinstance(v, dict) and v.get("required", False)]
    if not required_fields:
        return "OK"

    ratings = []
    for f in required_fields:
        field = section_fields.get(f)
        if field is None:
            ratings.append(0.0)
        else:
            ratings.append(compute_field_rating(field))

    if not ratings:
        return "MISSING"

    n_ok = sum(1 for r in ratings if r >= 0.5)
    pct_ok = n_ok / len(required_fields)

    if pct_ok == 1.0:
        return "OK"
    elif pct_ok >= 0.5:
        return "PARTIAL"
    else:
        return "MISSING"


def score_to_judgment(score):
    """
    Converte punteggio complessivo (0-1) in giudizio qualitativo globale
    """
    if score >= 0.9:
        return "🌟 Eccellente"
    elif score >= 0.7:
        return "👍 Buono"
    elif score >= 0.5:
        return "🟡 Sufficiente"
    elif score >= 0.3:
        return "⚠️ Scarso"
    else:
        return "❌ Critico"


def compute_overall_judgment(sections):
    """
    Calcola il giudizio globale del prodotto sulla base dei rating dei campi obbligatori ESPR.
    Ritorna:
    - giudizio qualitativo (emoji + testo)
    - punteggio numerico (0-1)
    """
    section_scores = []
    for section_name, section in sections.items():
        fields = section.get("fields", {})
        if not isinstance(fields, dict):
            continue

        mandatory_scores = [compute_field_rating(f) for f in fields.values() if isinstance(f, dict) and f.get("eu_weight", 1.0) >= 1.0]
        if mandatory_scores:
            section_scores.append(sum(mandatory_scores)/len(mandatory_scores))

    overall = sum(section_scores)/len(section_scores) if section_scores else 0.0
    return score_to_judgment(overall), overall

# ======================================================
# NUOVE FUNZIONI DPP COMPLETO
# ======================================================

from PIL import Image
from io import BytesIO
import base64

def initialize_passport(product_id, tipo_prodotto):
    """Crea struttura DPP completa con sezioni e campi obbligatori/opzionali"""
    sections = {
        "Technical": {
            "fields": {
                "Nome prodotto": {"value": None, "required": True, "confidence": 0.0, "field_type":"technical"},
                "Numero di modello": {"value": None, "required": True, "confidence": 0.0, "field_type":"technical"},
                "Produttore": {"value": None, "required": True, "confidence": 0.0, "field_type":"technical"},
                "Dimensioni": {"value": None, "required": False, "confidence": 0.0, "field_type":"technical"},
            },
            "section_rating": 0.0
        },
        "Materials & Sustainability": {
            "fields": {
                "Materiali": {"value": None, "required": True, "confidence": 0.0, "field_type":"lca"},
                "Composizione dettagliata": {"value": None, "required": True, "confidence": 0.0, "field_type":"lca"},
                "Origine materiali": {"value": None, "required": True, "confidence": 0.0, "field_type":"lca"},
                "Percentuale riciclato": {"value": None, "required": True, "confidence": 0.0, "field_type":"lca"},
                "Certificazioni ambientali": {"value": None, "required": False, "confidence": 0.0, "field_type":"lca"},
                "Gestione fine vita": {"value": None, "required": True, "confidence": 0.0, "field_type":"lca"},
            },
            "section_rating": 0.0
        },
        "Visual": {
            "fields": {
                "Colore": {"value": None, "required": True, "confidence": 0.0, "field_type":"visual"},
                "Condizioni": {"value": None, "required": True, "confidence": 0.0, "field_type":"visual"},
                "Dettagli immagini": []
            },
            "section_rating": 0.0
        }
    }

    return {
        "id": product_id,
        "product_type": tipo_prodotto,
        "metadata": {
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": None,
            "version": "EU-DPP-1.0",
            "validated_by": None,
            "language": "it",
            "country_of_origin": None,
            "batch_number": None
        },
        "sections": sections,
        "overall_rating": 0.0,
        "images": []
    }


def compute_section_rating(section):
    """Calcola rating medio dei campi di una sezione"""
    fields = section.get("fields", {})
    ratings = []
    for f in fields.values():
        if isinstance(f, dict):
            ratings.append(compute_field_rating(f))
    return round(sum(ratings)/len(ratings), 2) if ratings else 0.0


def compute_overall_rating(passport):
    """Calcola rating per sezione e overall del passport"""
    sections = passport.get("sections", {})
    for section_name, section in sections.items():
        section["section_rating"] = compute_section_rating(section)
    section_ratings = [s["section_rating"] for s in sections.values()]
    overall = round(sum(section_ratings)/len(section_ratings), 2) if section_ratings else 0.0
    passport["overall_rating"] = overall
    return overall


def add_product_image(passport, image_file, caption="Frontale", annotation=None):
    """Aggiunge immagine con annotazione e salva in base64"""
    if not image_file:
        return

    if hasattr(image_file, "getvalue"):  # UploadedFile
        img = Image.open(image_file).convert("RGB")
    else:  # PIL Image
        img = image_file.convert("RGB")

    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode()

    passport["images"].append({
        "file_base64": img_base64,
        "caption": caption,
        "annotation": annotation
    })


def reset_session_state(keys=None):
    """Reset chiavi dello session_state per nuovo prodotto"""
    if keys is None:
        keys = ["pdf_data","image_data","validated_pdf","validated_image","uploaded_image_file"]
    for k in keys:
        st.session_state[k] = None


