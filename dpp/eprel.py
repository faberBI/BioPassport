EPREL_REQUIRED = [
    "Nome prodotto",
    "Numero di modello",
    "Produttore",
    "Classe energetica"
]

def generate_eprel_block(passport):
    pdf = passport.get("sections", {}).get("PDF", {})
    return {
        "eprel:model": pdf.get("Numero di modello", {}).get("value"),
        "eprel:brand": pdf.get("Produttore", {}).get("value"),
        "eprel:energyClass": pdf.get("Classe energetica", {}).get("value", "N/A")
    }

def validate_eprel(passport):
    pdf = passport.get("sections", {}).get("PDF", {})
    missing = [f for f in EPREL_REQUIRED if not pdf.get(f, {}).get("value")]
    return missing
