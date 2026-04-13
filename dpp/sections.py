ESPR_SECTIONS = [
    "Identità prodotto",
    "Produzione",
    "Materiali",
    "Sostanze pericolose",
    "Riparabilità",
    "Fine vita",
    "Certificazioni",
    "Evidenze",
    "Firma digitale",
    "QR & GS1"
]

def build_espr_sections(passport):
    return {sec: {} for sec in ESPR_SECTIONS}
