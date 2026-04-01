<p align="center">
  <img src="functions/logo_nuvia.jpeg" alt="Nuvia Logo" width="160"/>
</p>

<h2 align="center">Nuvia Digital Product Passport</h2>

---

## 🧾 Nuvia — Piattaforma Digital Product Passport (ESPR‑ready)

**Nuvia** è una piattaforma avanzata per la gestione del **Digital Product Passport (DPP)**, progettata per supportare la **compliance al Regolamento UE ESPR (Reg. UE 2024/1781)** tramite dati di prodotto **strutturati, verificabili e orientati al ciclo di vita**.

A differenza delle soluzioni DPP basate esclusivamente su QR o storytelling, Nuvia è costruita come un **sistema compliance‑first**, pensato per produrre **passaporti di prodotto audit‑ready**, validi e affidabili lungo **tutto il ciclo di vita del prodotto**, inclusi gli eventi **post‑market**.

---

## ✨ Funzionalità principali

### ✅ Digital Product Passport ESPR‑ready
- Creazione di un **Digital Product Passport** per ciascun prodotto  
- **Doppia persistenza**:
  - **JSON** come fonte legale primaria (“legal truth”)
  - **Excel** per audit, reportistica e controlli  
- Struttura progettata per allinearsi ai requisiti ESPR e ai futuri *delegated acts*

---

### 🤖 Estrazione dati assistita da AI con validazione umana
- Estrazione automatica di informazioni da:
  - PDF di prodotto
  - Immagini
  - Certificati (PDF o immagini)  
- Ogni dato è accompagnato da:
  - `value`
  - `confidence`
  - `explanation`  
- **Human‑in‑the‑loop**: l’operatore valida e corregge i dati prima della pubblicazione

---

### 🔐 Certificati verificabili e integrità delle evidenze
- Ogni certificato è associato a un’**evidenza crittografica**
- I documenti originali sono hashati tramite **SHA‑256**
- L’hash è salvato come **riferimento immutabile** nel DPP  
- Consente di dimostrare che:
  - il certificato esisteva  
  - non è stato alterato  
  - corrispondeva al DPP al momento della firma  

---

### ♻️ Modello di ciclo di vita del prodotto
Nuvia tratta il DPP come un **oggetto digitale vivo**, non come un documento statico.

**Eventi di lifecycle supportati**:
- `manufactured`
- `placed_on_market`
- `certified`
- `updated`
- `repaired`
- `component_replaced`
- `resold`
- `withdrawn`
- `end_of_life`

Ogni evento è:
- timestampato  
- versionato  
- tracciabile  
- riflesso nello stato corrente del DPP  

---

### 🔗 Legame fisico‑digitale formalizzato
- Collegamento esplicito tra prodotto fisico e DPP digitale  
- Supporto a **QR code** (estendibile a NFC / RFID)  
- Registrazione di:
  - tipo di carrier  
  - posizione sul prodotto  
  - URL pubblico  
  - livello di rischio di manomissione  

Pensato per **market surveillance** e **controlli doganali**.

---

### 🛡️ Integrità, responsabilità e auditabilità
- Serializzazione JSON canonica  
- Hash di integrità **SHA‑256** del passaporto  
- Versioning con **change log completo**  
- Attestazione legale dell’issuer  
- Progettato per **audit regolatori**, non solo per visualizzazione consumer  

---

### ✍️ Sigillo elettronico qualificato (QeSeal / QES)
- Integrazione opzionale con **Sigillo Elettronico Qualificato UE**  
- Firma di un PDF ufficiale del DPP  
- Metadati salvati nel passport:
  - provider  
  - ID del sigillo  
  - stato della firma  

Adatto a contesti ad **alta esposizione regolatoria**.

---

### 🖥️ Interfacce operatore e pubblica

**UI Operatore (Streamlit)**:
- upload documenti  
- analisi AI  
- validazione umana  
- pubblicazione del DPP  

**Vista pubblica**:
- accesso via QR / URL  
- visualizzazione del lifecycle  
- certificati ed evidenze  
- stato di conformità  

---

## 🏗️ Architettura
- Core in **Python**
- Service layer modulare (`services.py`)
- Separazione chiara tra:
  - estrazione dati  
  - validazione  
  - gestione del lifecycle  
  - integrità crittografica  
  - firma esterna  

Pronta per:
- API  
- integrazione **ERP / PLM**  
- scalabilità **multi‑prodotto**

---

## 🎯 Differenze rispetto alle soluzioni DPP tradizionali

| Soluzioni DPP tradizionali | Nuvia |
|---------------------------|-------|
| Pagine prodotto statiche | Oggetti digitali con ciclo di vita |
| Orientate al marketing | Orientate alla regolazione |
| Documenti non verificati | Evidenze hashate |
| QR come semplice link | Legame fisico‑digitale formalizzato |
| Audit limitato | Audit‑grade by design |

---

## 🚦 Stato del progetto
- ✅ Creazione DPP  
- ✅ Lifecycle e post‑market  
- ✅ Certificati verificabili  
- ✅ Legame fisico‑digitale  
- ✅ Integrazione QeSeal (sandbox / production‑ready)  

---

## 📌 Destinatari
- Produttori UE soggetti a ESPR  
- Filiere regolamentate (elettronica, arredo, infrastrutture, utility)  
- Team compliance, legali e sustainability  
- Auditor e autorità di vigilanza  

---
``
