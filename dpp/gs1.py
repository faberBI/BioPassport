def generate_gs1_digital_link(gtin, serial=None):
    base = f"https://id.gs1.org/01/{gtin}"
    if serial:
        base += f"/21/{serial}"
    return base

def validate_gs1(gtin):
    return len(gtin) in [8, 12, 13, 14] and gtin.isdigit()
