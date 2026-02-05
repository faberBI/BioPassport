import pdfplumber
import json
import base64
import qrcode
import os
from io import BytesIO
from openai import OpenAI
import streamlit as st
from PIL import Image
from datetime import datetime

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
    else:
        buf = BytesIO()
        image_file.save(buf, format="JPEG")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()

def resize_image_for_vision(image_file, max_size=512):
    img = Image.open(image_file).convert("RGB")
    img.thumbnail((max_size, max_size))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    buf.name = "image.jpg"
    return buf

# ======================================================
# GPT EXTRACTION
# ======================================================
def gpt_extract_from_pdf(text, client: OpenAI, tipo):
    campi = [c["name"] for c in PRODUCT_FIELDS[tipo]["pdf"]]
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
        if resp_text.startswith("```"):
            resp_text = "\n".join(resp_text.split("\n")[1:-1]).strip()
        data = json.loads(resp_text)
        for c in campi:
            if c not in data:
                data[c] = None
        return data
    except Exception as e:
        st.error(f"Errore GPT PDF: {e}")
        return {c: None for c in campi}

def gpt_analyze_image(image_file, client: OpenAI, tipo):
    campi = ["colore", "condizioni"]
    prompt = f"""
Analizza immagine del prodotto {tipo}.
Restituisci JSON con campi colore e condizioni.
Se non determinabile usa null.
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
            input=[{"role":"user","content":[{"type":"input_text","text":prompt},{"type":"input_image","file_id":file_id}]}]
        )
        data_raw = safe_json_parse(resp.output_text.strip())
        data = {}
        mapping = {"colore":"Colore","condizioni":"Condizioni"}
        for k,v in mapping.items():
            val = data_raw.get(k,None)
            data[v] = val if val not in [None,"null",""] else "non rilevato"
        return data
    except Exception as e:
        st.error(f"Errore GPT Image: {e}")
        return {v:"non rilevato" for v in mapping.values()}

def upload_image_to_openai(image_file, client):
    resized = resize_image_for_vision(image_file)
    uploaded = client.files.create(file=resized, purpose="vision")
    return uploaded.id

# ======================================================
# VALIDATION FORM
# ======================================================
def render_validation_form(data, title: str):
    st.subheader(title)
    validated = {}
    def render_item(key, value, parent=""):
        full_key = f"{parent} > {key}" if parent else key
        if isinstance(value, dict):
            with st.expander(full_key, expanded=False):
                for k,v in value.items():
                    render_item(k,v,full_key)
        elif isinstance(value,list):
            validated[full_key] = st.text_area(full_key,", ".join(map(str,value)) if value else "non rilevato",height=50)
        else:
            validated[full_key] = st.text_input(full_key,"" if value is None else str(value))
    for k,v in data.items():
        render_item(k,v)
    return validated

# ======================================================
# PASSPORT STORAGE
# ======================================================
def save_passport_to_file(passport):
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    path = os.path.join(PASSPORT_DIR, f"{passport['id']}.json")
    with open(path,"w",encoding="utf-8") as f:
        json.dump(passport,f,indent=2,ensure_ascii=False)

def load_passport_from_file(passport_id):
    path = os.path.join(PASSPORT_DIR, f"{passport_id}.json")
    if not os.path.exists(path):
        return None
    with open(path,"r",encoding="utf-8") as f:
        return json.load(f)

# ======================================================
# QR CODE
# ======================================================
def generate_qr_from_url(url: str):
    qr = qrcode.QRCode(version=1,error_correction=qrcode.constants.ERROR_CORRECT_H,box_size=10,border=4)
    qr.add_data(url)
    qr.make(fit=True)
    buf = BytesIO()
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(buf)
    buf.seek(0)
    return buf

# ======================================================
# RATING / COMPLIANCE
# ======================================================
def compute_field_rating(field, type_weight_map=None):
    if type_weight_map is None:
        type_weight_map = {"technical":1.0,"declaration":0.6,"lca":0.5,"visual":0.4}
    val = field.get("value")
    if val is None or (isinstance(val,str) and val.strip()==""):
        return 0.0
    conf = field.get("confidence",0.0) or 0.0
    ftype = field.get("field_type","declaration")
    eu = field.get("eu_weight",1.0)
    w = type_weight_map.get(ftype,0.5)
    return round(conf*w*eu,2)

def score_to_color(score):
    if score>=0.7: return "🟢"
    elif score>=0.4: return "🟡"
    else: return "🔴"

def compute_section_rating(section):
    """Calcola rating medio dei campi di una sezione"""
    fields = section.get("fields", {})
    ratings = [compute_field_rating(f) for f in fields.values() if isinstance(f, dict)]
    avg = round(sum(ratings)/len(ratings), 2) if ratings else 0.0
    section["section_rating"] = avg
    return avg

def compute_overall_rating(passport: dict):

    total_scores = []
    section_scores = []

    for section in passport.get("sections", {}).values():

        field_scores = []

        for field in section.get("fields", {}).values():

            r = compute_field_rating(field)

            field["rating"] = r
            field["color"] = score_to_color(r)

            field_scores.append(r)
            total_scores.append(r)

        # ⭐ CALCOLO RATING SEZIONE
        if field_scores:
            section_rating = sum(field_scores) / len(field_scores)
        else:
            section_rating = 0.0

        section["section_rating"] = round(section_rating, 2)
        section_scores.append(section_rating)

    passport["overall_rating"] = (
        round(sum(section_scores) / len(section_scores), 2)
        if section_scores else 0.0
    )


def compute_espr_compliance(section_fields):
    required = [f for f,v in section_fields.items() if isinstance(v,dict) and v.get("required",False)]
    ratings = [section_fields[f]["rating"] if f in section_fields else 0.0 for f in required]
    if not ratings: return "MISSING"
    n_ok=sum(1 for r in ratings if r>=0.5)
    pct_ok=n_ok/len(ratings)
    if pct_ok==1.0: return "OK"
    elif pct_ok>=0.5: return "PARTIAL"
    else: return "MISSING"

def score_to_judgment(score):
    if score>=0.9: return "🌟 Eccellente"
    elif score>=0.7: return "👍 Buono"
    elif score>=0.5: return "🟡 Sufficiente"
    elif score>=0.3: return "⚠️ Scarso"
    else: return "❌ Critico"

# ======================================================
# PASSPORT MANAGEMENT
# ======================================================
def initialize_passport(product_id: str, product_type: str) -> dict:

    passport = {
        "id": product_id,
        "product_type": product_type,
        "metadata": {
            "created_at": datetime.utcnow().isoformat(),
            "version": "EU-DPP-1.0"
        },
        "sections": {},
        "overall_rating": 0.0,
        "overall_espr_status": "MISSING",
        "images": []
    }

    pdf_fields = PRODUCT_FIELDS.get(product_type, {}).get("pdf", [])
    image_fields = PRODUCT_FIELDS.get(product_type, {}).get("image", [])

    # ✅ CREA SEZIONI LOGICHE (NON un campo = una sezione)
    passport["sections"] = {
        "Technical Data": {
            "fields": {},
            "section_rating": 0.0
        },
        "Sustainability": {
            "fields": {},
            "section_rating": 0.0
        },
        "Visual Inspection": {
            "fields": {},
            "section_rating": 0.0
        }
    }

    # -------------------------
    # PDF → Technical + Sustainability
    # -------------------------
    sustainability_keywords = [
        "riciclato",
        "sostanze",
        "carbon",
        "fine vita",
        "cer",
        "sostenibil",
        "materiale"
    ]

    for field in pdf_fields:

        name = field["name"]
        required = field.get("required", False)

        # decide se sostenibilità
        is_sustainability = any(k.lower() in name.lower() for k in sustainability_keywords)

        section_name = "Sustainability" if is_sustainability else "Technical Data"

        passport["sections"][section_name]["fields"][name] = {
            "value": None,
            "confidence": 0.0,
            "required": required,
            "field_type": "lca" if is_sustainability else "technical",
            "eu_weight": 2.0 if required else 1.0,
            "rating": 0.0,
            "color": "🔴"
        }

    # -------------------------
    # IMAGE → Visual
    # -------------------------
    for field in image_fields:

        name = field["name"]
        required = field.get("required", False)

        passport["sections"]["Visual Inspection"]["fields"][name] = {
            "value": None,
            "confidence": 0.0,
            "required": required,
            "field_type": "visual",
            "eu_weight": 2.0 if required else 1.0,
            "rating": 0.0,
            "color": "🔴"
        }

    return passport



def add_product_image(passport: dict, image_file, caption: str = "", annotation: str = ""):
    img_base64 = image_to_base64(image_file)
    passport["images"].append({"file_base64":img_base64,"caption":caption,"annotation":annotation})

def reset_session_state(keys=None):
    if keys is None:
        keys=["pdf_data","image_data","validated_pdf","validated_image","uploaded_image_file"]
    for k in keys:
        st.session_state[k]=None


def merge_validated_data(passport, validated_pdf, validated_image):
    """
    Aggiorna i campi del passport con i dati validati (PDF + Immagine),
    ricalcola rating dei campi, rating delle sezioni e ESPR compliance basata sui rating delle sezioni.
    """

    merged_data = {**validated_pdf, **validated_image}

    # 1️⃣ Aggiorna i valori dei campi
    for section in passport["sections"].values():
        for field_name, field in section["fields"].items():
            val = None
            # cerca la chiave corrispondente tra i dati validati
            for k, v in merged_data.items():
                if k.strip().lower() == field_name.strip().lower():
                    val = v
                    break

            if val is not None:
                if not isinstance(val, dict):
                    val = {
                        "value": val,
                        "confidence": 1.0,
                        "field_type": field.get("field_type", "technical"),
                        "eu_weight": field.get("eu_weight", 1.0)
                    }
                field.update(val)
                # ⭐ ricalcola rating e colore del campo
                rating = compute_field_rating(field)
                field["rating"] = rating
                field["color"] = score_to_color(rating)

    # 2️⃣ Ricalcola rating delle sezioni
    for section in passport["sections"].values():
        field_ratings = [f["rating"] for f in section["fields"].values() if isinstance(f, dict)]
        section["section_rating"] = round(sum(field_ratings)/len(field_ratings), 2) if field_ratings else 0.0

    # 3️⃣ Calcola lo stato ESPR di ciascuna sezione basandosi sul rating della sezione
    passport["overall_espr_status"] = compute_overall_espr_from_sections(passport)

    # 4️⃣ Ricalcola rating complessivo generale
    compute_overall_rating(passport)




def compute_espr_status(section, threshold_ok=0.5):
    required_fields = [
        f for f in section["fields"].values()
        if f.get("required")
    ]

    if not required_fields:
        return "OK"

    n_ok = sum(1 for f in required_fields if f.get("rating", 0) >= threshold_ok)
    ratio = n_ok / len(required_fields)

    if ratio == 1.0:
        return "OK"
    elif ratio >= 0.5:
        return "PARTIAL"
    else:
        return "MISSING"

def compute_overall_espr_compliance(passport):
    statuses = []
    for section in passport["sections"].values():
        status = compute_espr_status(section)
        section["espr_compliance"] = status
        statuses.append(status)

    if "MISSING" in statuses:
        return "MISSING"
    elif "PARTIAL" in statuses:
        return "PARTIAL"
    else:
        return "OK"

def compute_overall_espr(passport):
    statuses = [
        section["espr_status"]
        for section in passport["sections"].values()
    ]

    if "MISSING" in statuses:
        return "MISSING"
    if "PARTIAL" in statuses:
        return "PARTIAL"
    return "OK"

def compute_espr_status_from_section_rating(section):
    """Restituisce lo stato ESPR di una sezione basandosi sul suo rating già calcolato"""
    r = section.get("section_rating", 0.0)
    if r >= 0.7:
        return "OK"
    elif r >= 0.4:
        return "PARTIAL"
    else:
        return "MISSING"

def compute_overall_espr_from_sections(passport):
    """Calcola lo stato ESPR complessivo basandosi sui rating delle sezioni"""
    statuses = []
    for section in passport.get("sections", {}).values():
        status = compute_espr_status_from_section_rating(section)
        section["espr_status"] = status
        statuses.append(status)

    if "MISSING" in statuses:
        return "MISSING"
    elif "PARTIAL" in statuses:
        return "PARTIAL"
    else:
        return "OK"
        
# ======================================================
# FUNZIONE PER MOSTRARE ESPR COMPLIANCE
# ======================================================
def render_espr_compliance(passport):
    st.subheader("🧩 ESPR COMPLIANCE")
    st.markdown("---")
    for section_name, section in passport["sections"].items():
        # Usa rating della sezione, non i campi obbligatori
        rating = section.get("section_rating", 0.0)
        if rating >= 0.7:
            emoji = "✅"
            status = "OK"
        elif rating >= 0.4:
            emoji = "⚠️"
            status = "PARTIAL"
        else:
            emoji = "❌"
            status = "MISSING"
        st.write(f"{section_name:<20} {emoji} {status}")
    
    # Overall ESPR basata sui rating delle sezioni
    overall_rating = passport.get("overall_rating", 0.0)
    if overall_rating >= 0.7:
        emoji_overall = "✅"
        overall_status = "OK"
    elif overall_rating >= 0.4:
        emoji_overall = "⚠️"
        overall_status = "PARTIAL"
    else:
        emoji_overall = "❌"
        overall_status = "MISSING"
    st.markdown(f"**Overall ESPR Status:** {emoji_overall} {overall_status}")


