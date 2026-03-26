import streamlit as st
import uuid
from openai import OpenAI
from functions import services
from PIL import Image
import os
import pandas as pd
import base64
from io import BytesIO
import streamlit.components.v1 as components

# ======================================================
# CONFIG STREAMLIT
# ======================================================
st.set_page_config(
    page_title="Nuvia Digital Product Passport",
    page_icon="functions/favicon.jpeg",
    layout="centered"
)

# ======================================================
# LOGO + STILE
# ======================================================
logo = Image.open("functions/logo_nuvia.jpeg")
logo_base64 = services.image_to_base64(logo)

st.markdown(f"""
<style>
body {{background-color:#f5f1ed; color:#3a2607; font-family:Nunito Sans;}}
.stButton>button {{background-color:#25ce6c; color:white; border-radius:8px;}}
.required-field {{font-weight:bold; color:#d9534f;}}
</style>
<img src="data:image/jpeg;base64,{logo_base64}" width="350">
""", unsafe_allow_html=True)

# ======================================================
# OPENAI CLIENT
# ======================================================
client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# SESSION STATE
# ======================================================
keys = ["uploaded_pdf_file", "uploaded_image_files",
        "pdf_data", "image_data", "validated_pdf",
        "validated_image", "images"]
for k in keys:
    if k not in st.session_state:
        st.session_state[k] = None

# ======================================================
# PUBLIC VIEW (QR LINK)
# ======================================================
passport_id = st.query_params.get("passport_id")
if passport_id:
    passport = services.load_passport_from_file(passport_id)
    if not passport:
        st.error("Passport non trovato")
        st.stop()

    st.title("🇪🇺 Digital Product Passport")
    st.write(f"**ID:** {passport['id']}")
    st.write(f"**Tipo:** {passport['product_type']}")

    for sec_name, sec in passport["sections"].items():
        st.subheader(f"{sec_name} ({sec['section_rating']*100:.0f}%)")
        for fname, f in sec["fields"].items():
            conf = f.get("confidence", 0)
            st.write(f"**{fname}**: {f['value']} {f['color']} (conf: {conf})")
            if conf < 0.5:
                st.caption("Bassa confidenza")
            if f.get("explanation"):
                st.caption(f["explanation"])

    services.render_espr_compliance(passport)
    st.progress(passport.get("overall_rating", 0))
    st.metric("Reliability", f"{int(passport.get('overall_rating', 0)*100)}%")

    if passport.get("images"):
        for img in passport["images"]:
            st.image(f"data:image/jpeg;base64,{img['file_base64']}")

    st.stop()

# ======================================================
# SELEZIONE TIPO PRODOTTO
# ======================================================
tipo = st.selectbox("Tipo prodotto", ["mobile","lampada","bicicletta"])
fields = [f["name"] for f in services.PRODUCT_FIELDS[tipo]["pdf"]]

tabs = st.tabs(["📤 Upload & Analisi", "📝 Validazione", "🔗 Pubblica", "📚 Archivio"])

# ======================================================
# TAB 1 — UPLOAD + AI
# ======================================================
with tabs[0]:
    pdf_file = st.file_uploader("PDF prodotto", type=["pdf"])
    image_files = st.file_uploader("Immagini prodotto", type=["jpg","png"], accept_multiple_files=True)

    highlighted_pdf_io = None

    if st.button("Analizza"):
        if not pdf_file or not image_files:
            st.warning("Carica PDF e almeno un'immagine")
        else:
            st.session_state.uploaded_pdf_file = pdf_file
            st.session_state.uploaded_image_files = image_files
            st.session_state.images = image_files

            with st.spinner("Analisi in corso..."):
                # PDF
                pdf_text = services.extract_text_from_pdf(pdf_file)
                st.session_state.pdf_data = services.gpt_extract_from_pdf(pdf_text, client, tipo, fields)

                # Immagini
                img_data = {}
                for img in image_files:
                    res = services.gpt_analyze_image(img, client, tipo)
                    img_data.update(res)
                st.session_state.image_data = img_data

            st.success("Analisi completata ✅")

# Evidenzia PDF e visualizza inline (pdf.js SAFE)
if st.session_state.pdf_data and pdf_file:
    if st.button("Evidenzia PDF"):

        import streamlit.components.v1 as components
        import base64

        pdf_file.seek(0)

        highlighted_pdf_io = services.highlight_pdf_fields(
            pdf_file,
            st.session_state.pdf_data
        )

        st.success("PDF evidenziato pronto!")

        pdf_bytes = highlighted_pdf_io.getvalue()
        b64 = base64.b64encode(pdf_bytes).decode()

        html_code = """
        <!DOCTYPE html>
        <html>
        <head>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.4.120/pdf.min.js"></script>
        </head>
        <body>

        <div id="pdf-container"></div>

        <script>
        var pdfData = atob("PDF_BASE64");

        var loadingTask = pdfjsLib.getDocument({data: pdfData});
        loadingTask.promise.then(function(pdf) {

            for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {

                pdf.getPage(pageNum).then(function(page) {

                    var scale = 1.2;
                    var viewport = page.getViewport({scale: scale});

                    var canvas = document.createElement("canvas");
                    var context = canvas.getContext("2d");

                    canvas.height = viewport.height;
                    canvas.width = viewport.width;

                    document.getElementById("pdf-container").appendChild(canvas);

                    page.render({
                        canvasContext: context,
                        viewport: viewport
                    });

                });
            }

        });
        </script>

        </body>
        </html>
        """

        # sostituzione base64 (NO f-string)
        html_code = html_code.replace("PDF_BASE64", b64)

        components.html(html_code, height=700)

        st.download_button(
            "Scarica PDF evidenziato",
            data=pdf_bytes,
            file_name="highlighted.pdf",
            mime="application/pdf"
        )
# ======================================================
# TAB 2 — VALIDAZIONE
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data and st.session_state.image_data:
        st.subheader("Validazione dati PDF")
        validated_pdf = {}
        for k,v in st.session_state.pdf_data.items():
            val = v["value"]
            conf = v.get("confidence", 0)
            explanation = v.get("explanation","")
            # Mantieni valore e confidence insieme
            validated_pdf[k] = {"value": st.text_input(f"{k} (conf: {conf})", val, help=explanation), "confidence": conf}
        st.session_state.validated_pdf = validated_pdf

        st.subheader("Validazione dati Immagini")
        validated_img = {}
        for k,v in st.session_state.image_data.items():
            val = v["value"]
            conf = v.get("confidence",0)
            explanation = v.get("explanation","")
            validated_img[k] = {"value": st.text_input(f"{k} (conf: {conf})", val, help=explanation), "confidence": conf}
        st.session_state.validated_image = validated_img

        if st.button("Completa validazione"):
            st.success("Validazione completata ✅")
    else:
        st.info("Esegui prima l’analisi PDF e immagini")

# ======================================================
# TAB 3 — PUBBLICA
# ======================================================
with tabs[2]:
    if st.session_state.validated_pdf and st.session_state.validated_image:

        if st.button("Pubblica Digital Product Passport"):

            # Crea ID passport
            pid = f"{tipo.upper()}-{uuid.uuid4().hex[:6]}"
            passport = services.initialize_passport(pid, tipo, fields)

            # Merge dati PDF + immagini (aggiornando i valori dai campi validati)
            services.merge_data(passport, st.session_state.validated_pdf, st.session_state.validated_image)

            # ======================================================
            # Aggiorna le confidenze dai valori validati
            # ======================================================
            for sec_name, sec in passport["sections"].items():
                for fname, field in sec["fields"].items():

                    # PDF
                    if fname in st.session_state.validated_pdf:
                        val_dict = st.session_state.validated_pdf[fname]
                        field["value"] = val_dict.get("value")
                        field["confidence"] = val_dict.get("confidence", 0)

                    # IMAGE
                    if fname in st.session_state.validated_image:
                        val_dict = st.session_state.validated_image[fname]
                        field["value"] = val_dict.get("value")
                        field["confidence"] = val_dict.get("confidence", 0)

            # ======================================================
            # Ricalcola punteggi overall e reliability aggiornati
            # ======================================================
            services.compute_overall(passport)

            # Salva immagini
            for img in st.session_state.images:
                services.add_product_image(passport, img)

            # Salva su file e Excel (con dati aggiornati)
            services.save_passport_to_file(passport)
            services.save_passport_to_excel_append(passport)

            # Genera QR pubblico
            url = f"{st.secrets['APP_URL']}?passport_id={pid}"
            qr = services.generate_qr_from_url(url)

            st.success("DPP pubblicato ✅")
            st.subheader("ESPR")
            st.write(passport.get("overall_espr", "MISSING"))
            st.subheader("Reliability")
            st.progress(passport.get("overall_rating", 0))

            st.image(qr)
            # Bottone per scaricare il QR code come immagine
            qr_bytes = qr.getvalue()
            st.download_button(
            label="Scarica QR code",
            data=qr_bytes,
            file_name=f"{pid}_qr.png",
            mime="image/png"
            )

            st.code(url)

    else:
        st.info("Completa prima la validazione PDF e immagini")


# ======================================================
# TAB 4 — ARCHIVIO
# ======================================================
with tabs[3]:
    st.header("Archivio Passport")

    if os.path.exists(services.EXCEL_FILE):
        try:
            df_passport = pd.read_excel(services.EXCEL_FILE, sheet_name="passport")
            df_fields = pd.read_excel(services.EXCEL_FILE, sheet_name="fields")

            # Pulizia colonne
            df_passport.columns = df_passport.columns.str.strip()
            df_fields.columns = df_fields.columns.str.strip()

            if df_passport.empty:
                st.info("Nessun passport disponibile")
            else:
                # ======================================================
                # COSTRUZIONE DATASET UNIFICATO
                # ======================================================
                df_pivot = df_fields.pivot_table(
                    index="passport_id",
                    columns="field_name",
                    values="value",
                    aggfunc="first"
                ).reset_index()

                df_full = df_passport.merge(
                    df_pivot,
                    left_on="id",
                    right_on="passport_id",
                    how="left"
                )

                # ======================================================
                # FILTRI
                # ======================================================
                st.subheader("Filtri")

                col1, col2 = st.columns(2)

                # Filtro nome prodotto
                nome = col1.text_input("Nome prodotto")

                # Filtro luogo produzione
                luogo = col2.text_input("Luogo di produzione")

                # Filtro prezzo
                prezzo_min = st.number_input("Prezzo minimo", value=0)
                prezzo_max = st.number_input("Prezzo massimo", value=10000)

                # Filtro data
                data_min = st.date_input("Data da")
                data_max = st.date_input("Data a")

                df_filtered = df_full.copy()

                # ======================================================
                # APPLICAZIONE FILTRI
                # ======================================================
                if nome:
                    df_filtered = df_filtered[
                        df_filtered["Nome prodotto"].astype(str).str.contains(nome, case=False, na=False)
                    ]

                if luogo:
                    df_filtered = df_filtered[
                        df_filtered["Luogo di produzione"].astype(str).str.contains(luogo, case=False, na=False)
                    ]

                if "Prezzo" in df_filtered.columns:
                    df_filtered["Prezzo_num"] = (
                        df_filtered["Prezzo"]
                        .astype(str)
                        .str.replace("€", "")
                        .str.replace(",", ".")
                        .str.extract(r'(\d+\.?\d*)')[0]
                        .astype(float)
                    )
                    df_filtered = df_filtered[
                        (df_filtered["Prezzo_num"] >= prezzo_min) &
                        (df_filtered["Prezzo_num"] <= prezzo_max)
                    ]

                if "created_at" in df_filtered.columns:
                    df_filtered["created_at"] = pd.to_datetime(df_filtered["created_at"], errors="coerce")
                    df_filtered = df_filtered[
                        (df_filtered["created_at"].dt.date >= data_min) &
                        (df_filtered["created_at"].dt.date <= data_max)
                    ]

                # ======================================================
                # RISULTATI
                # ======================================================
                st.subheader("Risultati filtrati")
                st.dataframe(df_filtered)

                # Selezione passport
                if not df_filtered.empty:
                    selected_id = st.selectbox("Seleziona Passport", df_filtered["id"])

                    if selected_id:
                        st.subheader("Dettaglio")

                        st.dataframe(df_passport[df_passport["id"] == selected_id])

                        st.subheader("Fields")
                        st.dataframe(df_fields[df_fields["passport_id"] == selected_id])

                        st.subheader("Immagini")
                        df_images = pd.read_excel(services.EXCEL_FILE, sheet_name="images")
                        df_images.columns = df_images.columns.str.strip()

                        images = df_images[df_images["passport_id"] == selected_id]

                        for _, row in images.iterrows():
                            st.image(
                                f"data:image/jpeg;base64,{row['file_base64']}",
                                caption=row.get("caption", "")
                            )

        except Exception as e:
            st.error(f"Errore archivio: {e}")
    else:
        st.info("Nessun file Excel trovato")
