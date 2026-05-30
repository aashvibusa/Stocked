"""Mock medication inventory database for Stocked.

Each pharmacy has its own inventory. The mock pharmacy bots look up
medications here to give realistic responses with real prices and
stock status.
"""

# Medication catalog — common prescriptions with typical retail prices
MEDICATIONS = {
    "amoxicillin 500mg": {"generic": "Amoxicillin", "brand": "Amoxil", "form": "capsule", "quantity": 30, "price_range": (4.00, 12.99)},
    "amoxicillin 250mg": {"generic": "Amoxicillin", "brand": "Amoxil", "form": "capsule", "quantity": 30, "price_range": (4.00, 9.99)},
    "lisinopril 10mg": {"generic": "Lisinopril", "brand": "Zestril", "form": "tablet", "quantity": 30, "price_range": (4.00, 15.00)},
    "lisinopril 20mg": {"generic": "Lisinopril", "brand": "Zestril", "form": "tablet", "quantity": 30, "price_range": (4.00, 18.00)},
    "metformin 500mg": {"generic": "Metformin", "brand": "Glucophage", "form": "tablet", "quantity": 60, "price_range": (4.00, 12.00)},
    "metformin 850mg": {"generic": "Metformin", "brand": "Glucophage", "form": "tablet", "quantity": 60, "price_range": (4.00, 15.00)},
    "atorvastatin 20mg": {"generic": "Atorvastatin", "brand": "Lipitor", "form": "tablet", "quantity": 30, "price_range": (9.00, 25.00)},
    "atorvastatin 40mg": {"generic": "Atorvastatin", "brand": "Lipitor", "form": "tablet", "quantity": 30, "price_range": (12.00, 30.00)},
    "omeprazole 20mg": {"generic": "Omeprazole", "brand": "Prilosec", "form": "capsule", "quantity": 30, "price_range": (8.00, 22.00)},
    "amlodipine 5mg": {"generic": "Amlodipine", "brand": "Norvasc", "form": "tablet", "quantity": 30, "price_range": (4.00, 12.00)},
    "amlodipine 10mg": {"generic": "Amlodipine", "brand": "Norvasc", "form": "tablet", "quantity": 30, "price_range": (4.00, 15.00)},
    "levothyroxine 50mcg": {"generic": "Levothyroxine", "brand": "Synthroid", "form": "tablet", "quantity": 30, "price_range": (4.00, 20.00)},
    "levothyroxine 100mcg": {"generic": "Levothyroxine", "brand": "Synthroid", "form": "tablet", "quantity": 30, "price_range": (4.00, 25.00)},
    "azithromycin 250mg": {"generic": "Azithromycin", "brand": "Zithromax", "form": "tablet", "quantity": 6, "price_range": (8.00, 18.00)},
    "ciprofloxacin 500mg": {"generic": "Ciprofloxacin", "brand": "Cipro", "form": "tablet", "quantity": 20, "price_range": (6.00, 20.00)},
    "prednisone 10mg": {"generic": "Prednisone", "brand": "Deltasone", "form": "tablet", "quantity": 21, "price_range": (4.00, 10.00)},
    "ibuprofen 800mg": {"generic": "Ibuprofen", "brand": "Motrin", "form": "tablet", "quantity": 30, "price_range": (4.00, 12.00)},
    "gabapentin 300mg": {"generic": "Gabapentin", "brand": "Neurontin", "form": "capsule", "quantity": 90, "price_range": (10.00, 30.00)},
    "hydrochlorothiazide 25mg": {"generic": "Hydrochlorothiazide", "brand": "Microzide", "form": "tablet", "quantity": 30, "price_range": (4.00, 10.00)},
    "sertraline 50mg": {"generic": "Sertraline", "brand": "Zoloft", "form": "tablet", "quantity": 30, "price_range": (4.00, 15.00)},
}

# Per-pharmacy inventory — determines what each mock pharmacy has in stock
# Maps pharmacy name -> set of medication keys that are IN STOCK
PHARMACY_INVENTORY = {
    "CVS Pharmacy": {
        "amoxicillin 500mg", "amoxicillin 250mg", "lisinopril 10mg",
        "metformin 500mg", "atorvastatin 20mg", "omeprazole 20mg",
        "amlodipine 5mg", "levothyroxine 50mcg", "azithromycin 250mg",
        "sertraline 50mg", "ibuprofen 800mg",
    },
    "Walgreens": {
        "lisinopril 10mg", "lisinopril 20mg", "metformin 500mg",
        "metformin 850mg", "atorvastatin 40mg", "amlodipine 10mg",
        "levothyroxine 100mcg", "ciprofloxacin 500mg", "prednisone 10mg",
        "gabapentin 300mg", "hydrochlorothiazide 25mg",
    },
    "Rite Aid": {
        "amoxicillin 500mg", "omeprazole 20mg", "ibuprofen 800mg",
        "prednisone 10mg",
    },
    "Costco Pharmacy": {
        "amoxicillin 500mg", "amoxicillin 250mg", "lisinopril 10mg",
        "lisinopril 20mg", "metformin 500mg", "metformin 850mg",
        "atorvastatin 20mg", "atorvastatin 40mg", "omeprazole 20mg",
        "amlodipine 5mg", "amlodipine 10mg", "levothyroxine 50mcg",
        "levothyroxine 100mcg", "azithromycin 250mg", "ciprofloxacin 500mg",
        "prednisone 10mg", "ibuprofen 800mg", "gabapentin 300mg",
        "hydrochlorothiazide 25mg", "sertraline 50mg",
    },
    "Safeway Pharmacy": {
        "amoxicillin 500mg", "lisinopril 10mg", "metformin 500mg",
        "omeprazole 20mg", "levothyroxine 50mcg", "ibuprofen 800mg",
    },
    "Target Pharmacy": {
        "metformin 500mg", "atorvastatin 20mg", "amlodipine 5mg",
        "sertraline 50mg", "gabapentin 300mg",
    },
    "Walmart Pharmacy": {
        "amoxicillin 500mg", "amoxicillin 250mg", "lisinopril 10mg",
        "metformin 500mg", "metformin 850mg", "atorvastatin 20mg",
        "omeprazole 20mg", "ibuprofen 800mg", "prednisone 10mg",
        "hydrochlorothiazide 25mg",
    },
    "Kaiser Pharmacy": {
        "lisinopril 20mg", "metformin 850mg", "atorvastatin 40mg",
        "levothyroxine 100mcg", "sertraline 50mg",
    },
}

# Default inventory for pharmacies not in the map above
_DEFAULT_STOCK = {
    "amoxicillin 500mg", "lisinopril 10mg", "metformin 500mg", "ibuprofen 800mg",
}


def lookup_medication(pharmacy_name: str, medication: str, dosage: str) -> dict:
    """Look up a medication at a specific pharmacy.

    Args:
        pharmacy_name: Name of the pharmacy (e.g. "CVS Pharmacy").
        medication: Medication name (e.g. "Amoxicillin").
        dosage: Dosage string (e.g. "500mg").

    Returns:
        Dict with keys: in_stock, price, generic, brand, form, quantity.
    """
    key = f"{medication.lower().strip()} {dosage.lower().strip()}"

    med_info = MEDICATIONS.get(key)
    if not med_info:
        # Try fuzzy match on generic name
        for k, v in MEDICATIONS.items():
            if medication.lower() in k or medication.lower() == v["generic"].lower():
                if dosage.lower() in k:
                    med_info = v
                    key = k
                    break

    if not med_info:
        return {"in_stock": False, "reason": "medication not found in catalog"}

    # Check pharmacy inventory
    inventory = PHARMACY_INVENTORY.get(pharmacy_name, _DEFAULT_STOCK)
    in_stock = key in inventory

    import random
    price = f"{random.uniform(*med_info['price_range']):.2f}" if in_stock else None

    return {
        "in_stock": in_stock,
        "price": price,
        "generic": med_info["generic"],
        "brand": med_info["brand"],
        "form": med_info["form"],
        "quantity": med_info["quantity"],
    }
