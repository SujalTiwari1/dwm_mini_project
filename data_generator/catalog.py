"""Static reference pools (medicine catalog, branch/supplier names).

The first 20 catalog entries cover all 10 categories (two each) and are used
for the prototype. Later entries and strength/manufacturer variants are used
when num_medicines grows.
"""
from collections import namedtuple

Entry = namedtuple(
    "Entry", "key generic category form strengths manufacturer price profile shelf_months"
)


def _e(key, generic, category, form, strengths, manufacturer, price, profile, shelf):
    return Entry(key, generic, category, form, strengths, manufacturer, price, profile, shelf)


CATALOG = [
    # ---- first 20: prototype set (2 per category) -------------------------
    _e("paracetamol_500", "Paracetamol", "CAT001", "Tablet", ["500mg", "250mg"], "MedNova Labs", 25.00, "HIGH", 36),
    _e("diclofenac_50", "Diclofenac", "CAT001", "Tablet", ["50mg", "100mg"], "PharmaCore India", 42.00, "MEDIUM", 36),
    _e("amoxicillin_500", "Amoxicillin", "CAT002", "Capsule", ["500mg", "250mg"], "HealthAxis Pharma", 92.00, "MEDIUM", 24),
    _e("azithromycin_500", "Azithromycin", "CAT002", "Tablet", ["500mg", "250mg"], "NovaMed Laboratories", 119.50, "MEDIUM", 24),
    _e("paracetamol_650", "Paracetamol", "CAT003", "Tablet", ["650mg"], "CureLine Healthcare", 30.00, "HIGH", 36),
    _e("paracetamol_susp", "Paracetamol Suspension", "CAT003", "Suspension", ["250mg/5ml", "125mg/5ml"], "MedNova Labs", 48.00, "LOW", 12),
    _e("cetirizine_10", "Cetirizine", "CAT004", "Tablet", ["10mg", "5mg"], "HealthAxis Pharma", 22.00, "HIGH", 36),
    _e("fexofenadine_120", "Fexofenadine", "CAT004", "Tablet", ["120mg", "180mg"], "MediSphere", 190.00, "LOW", 36),
    _e("pantoprazole_40", "Pantoprazole", "CAT005", "Tablet", ["40mg", "20mg"], "ApexLife Pharma", 78.00, "HIGH", 24),
    _e("ondansetron_4", "Ondansetron", "CAT005", "Tablet", ["4mg", "8mg"], "HealthAxis Pharma", 56.00, "LOW", 36),
    _e("amlodipine_5", "Amlodipine", "CAT006", "Tablet", ["5mg", "2.5mg", "10mg"], "CureLine Healthcare", 36.00, "HIGH", 36),
    _e("atorvastatin_10", "Atorvastatin", "CAT006", "Tablet", ["10mg", "20mg", "40mg"], "VitaCure Remedies", 98.00, "MEDIUM", 24),
    _e("metformin_500", "Metformin", "CAT007", "Tablet", ["500mg", "850mg", "1000mg"], "Zenith BioPharma", 32.00, "HIGH", 36),
    _e("glimepiride_2", "Glimepiride", "CAT007", "Tablet", ["2mg", "1mg", "3mg"], "MediSphere", 142.00, "MEDIUM", 36),
    _e("ambroxol_levosalbutamol", "Ambroxol + Levosalbutamol Syrup", "CAT008", "Syrup", ["100ml", "60ml"], "LifeSpring Pharma", 118.00, "MEDIUM", 18),
    _e("salbutamol_inhaler", "Salbutamol Inhaler", "CAT008", "Inhaler", ["100mcg", "200mcg"], "HealthAxis Pharma", 165.00, "LOW", 18),
    _e("vitamin_c_500", "Vitamin C Chewable", "CAT009", "Tablet", ["500mg", "1000mg"], "CarePlus Laboratories", 28.00, "MEDIUM", 24),
    _e("vitamin_d3_60k", "Vitamin D3", "CAT009", "Capsule", ["60000IU", "1000IU"], "Aarogya Formulations", 140.00, "LOW", 18),
    _e("clotrimazole_cream", "Clotrimazole Cream", "CAT010", "Cream", ["1%", "2%"], "LifeSpring Pharma", 85.00, "MEDIUM", 18),
    _e("mupirocin_oint", "Mupirocin Ointment", "CAT010", "Ointment", ["2%"], "MedNova Labs", 135.00, "LOW", 18),
    # ---- additional entries for larger datasets --------------------------
    _e("ibuprofen_400", "Ibuprofen", "CAT001", "Tablet", ["400mg", "200mg", "600mg"], "CarePlus Laboratories", 34.00, "MEDIUM", 36),
    _e("aceclofenac_para", "Aceclofenac + Paracetamol", "CAT001", "Tablet", ["100mg/325mg"], "Aarogya Formulations", 68.00, "MEDIUM", 24),
    _e("naproxen_250", "Naproxen", "CAT001", "Tablet", ["250mg", "500mg"], "ApexLife Pharma", 74.00, "LOW", 36),
    _e("cefixime_200", "Cefixime", "CAT002", "Tablet", ["200mg", "100mg"], "BlueCrest Pharma", 110.00, "MEDIUM", 24),
    _e("ciprofloxacin_500", "Ciprofloxacin", "CAT002", "Tablet", ["500mg", "250mg"], "HealthAxis Pharma", 58.00, "MEDIUM", 36),
    _e("doxycycline_100", "Doxycycline", "CAT002", "Capsule", ["100mg"], "TrueLife Remedies", 72.00, "LOW", 24),
    _e("amoxiclav_625", "Amoxicillin + Clavulanic Acid", "CAT002", "Tablet", ["625mg", "375mg"], "MedNova Labs", 204.00, "MEDIUM", 24),
    _e("mefenamic_250", "Mefenamic Acid", "CAT003", "Tablet", ["250mg", "500mg"], "Kavach Healthcare", 45.00, "LOW", 36),
    _e("paracetamol_drops", "Paracetamol Drops", "CAT003", "Drops", ["100mg/ml"], "HealthAxis Pharma", 38.00, "LOW", 18),
    _e("levocetirizine_5", "Levocetirizine", "CAT004", "Tablet", ["5mg", "2.5mg"], "ApexLife Pharma", 62.00, "MEDIUM", 36),
    _e("montelukast_levocet", "Montelukast + Levocetirizine", "CAT004", "Tablet", ["10mg/5mg"], "BlueCrest Pharma", 195.00, "MEDIUM", 24),
    _e("chlorpheniramine_4", "Chlorpheniramine", "CAT004", "Tablet", ["4mg"], "Meridian Pharma Works", 12.00, "LOW", 36),
    _e("omeprazole_20", "Omeprazole", "CAT005", "Capsule", ["20mg", "40mg"], "Summit Lifesciences", 52.00, "HIGH", 24),
    _e("domperidone_10", "Domperidone", "CAT005", "Tablet", ["10mg"], "Aarogya Formulations", 48.00, "MEDIUM", 36),
    _e("ors_powder", "ORS Powder", "CAT005", "Powder", ["21.8g"], "HydraCare Labs", 21.00, "MEDIUM", 12),
    _e("loperamide_2", "Loperamide", "CAT005", "Capsule", ["2mg"], "HealthAxis Pharma", 29.00, "LOW", 36),
    _e("telmisartan_40", "Telmisartan", "CAT006", "Tablet", ["40mg", "20mg", "80mg"], "LifeSpring Pharma", 122.00, "HIGH", 36),
    _e("losartan_50", "Losartan", "CAT006", "Tablet", ["50mg", "25mg"], "Stellar Formulations", 84.00, "MEDIUM", 36),
    _e("metoprolol_50", "Metoprolol", "CAT006", "Tablet", ["50mg", "25mg"], "Everwell Pharma", 68.00, "MEDIUM", 36),
    _e("rosuvastatin_10", "Rosuvastatin", "CAT006", "Tablet", ["10mg", "5mg", "20mg"], "ApexLife Pharma", 165.00, "MEDIUM", 24),
    _e("clopidogrel_75", "Clopidogrel", "CAT006", "Tablet", ["75mg"], "Summit Lifesciences", 96.00, "LOW", 36),
    _e("aspirin_75", "Aspirin", "CAT006", "Tablet", ["75mg", "150mg"], "Helix Pharma", 8.00, "MEDIUM", 36),
    _e("glimepiride_metformin", "Glimepiride + Metformin", "CAT007", "Tablet", ["2mg/500mg", "1mg/500mg"], "Zenith BioPharma", 150.00, "HIGH", 24),
    _e("sitagliptin_100", "Sitagliptin", "CAT007", "Tablet", ["100mg", "50mg"], "Crestview Pharma", 380.00, "LOW", 36),
    _e("gliclazide_80", "Gliclazide", "CAT007", "Tablet", ["80mg", "40mg"], "Lumina Pharma", 75.00, "LOW", 36),
    _e("montelukast_10", "Montelukast", "CAT008", "Tablet", ["10mg", "5mg"], "HealthAxis Pharma", 190.00, "MEDIUM", 24),
    _e("budesonide_inhaler", "Budesonide Inhaler", "CAT008", "Inhaler", ["200mcg", "100mcg"], "HealthAxis Pharma", 270.00, "LOW", 24),
    _e("dextromethorphan_syrup", "Dextromethorphan Syrup", "CAT008", "Syrup", ["100ml"], "Carewell Pharmaceuticals", 96.00, "MEDIUM", 24),
    _e("multivitamin_cap", "Multivitamin", "CAT009", "Capsule", ["B-complex+C"], "Carewell Pharmaceuticals", 45.00, "MEDIUM", 24),
    _e("calcium_d3", "Calcium + Vitamin D3", "CAT009", "Tablet", ["500mg/250IU"], "Stellar Formulations", 118.00, "MEDIUM", 24),
    _e("iron_folic", "Iron + Folic Acid", "CAT009", "Tablet", ["100mg/500mcg"], "Vedant Remedies", 82.00, "LOW", 24),
    _e("hydrocortisone_cream", "Hydrocortisone Cream", "CAT010", "Cream", ["1%"], "MedNova Labs", 62.00, "LOW", 24),
    _e("fusidic_acid_cream", "Fusidic Acid Cream", "CAT010", "Cream", ["2%"], "Summit Lifesciences", 155.00, "LOW", 24),
    _e("calamine_lotion", "Calamine Lotion", "CAT010", "Lotion", ["100ml"], "Harbor Lifesciences", 70.00, "LOW", 36),
    _e("ketoconazole_shampoo", "Ketoconazole Shampoo", "CAT010", "Shampoo", ["2%"], "HealthAxis Pharma", 210.00, "LOW", 36),
]

# Extra manufacturers used when generating strength/manufacturer variants.
MANUFACTURERS = [
    "HealthAxis Pharma", "ApexLife Pharma", "BlueCrest Pharma", "VitaCure Remedies", "Aarogya Formulations", "LifeSpring Pharma", "TrueLife Remedies",
    "Stellar Formulations", "CarePlus Laboratories", "Summit Lifesciences", "CureLine Healthcare", "NovaMed Laboratories",
]

BRANCH_POOL = [
    ("MedStock Central", "Andheri"),
    ("MedStock West", "Bandra"),
    ("MedStock North", "Borivali"),
    ("MedStock East", "Chembur"),
    ("MedStock Harbour", "Dadar"),
    ("MedStock Lake", "Powai"),
    ("MedStock Coast", "Malad"),
    ("MedStock South", "Colaba"),
    ("MedStock Hills", "Ghatkopar"),
    ("MedStock Park", "Goregaon"),
]

SUPPLIER_POOL = [
    ("Sai Pharma Distributors", "Mumbai"),
    ("Shree Ganesh Medico", "Mumbai"),
    ("Konkan Healthcare Traders", "Thane"),
    ("Western Drugs & Surgicals", "Mumbai"),
    ("Mahalaxmi Pharma Agencies", "Navi Mumbai"),
    ("Om Sai Medicorp", "Vasai"),
    ("Bombay Medi Supply", "Mumbai"),
    ("Dadar Wholesale Drugs", "Mumbai"),
    ("Vashi Pharma Hub", "Navi Mumbai"),
    ("Thane Medico Traders", "Thane"),
    ("Deccan Drug House", "Pune"),
    ("Maharashtra Pharma Link", "Mumbai"),
    ("Pioneer Healthcare Distributors", "Mumbai"),
    ("Kalyan Medical Stores", "Kalyan"),
    ("Navkar Pharma Agency", "Mumbai"),
    ("Bhiwandi Drug Depot", "Bhiwandi"),
    ("Lifeline Medico Distributors", "Mumbai"),
    ("Arihant Pharma Traders", "Mumbai"),
    ("Siddhivinayak Drug Agency", "Mumbai"),
    ("Panvel Pharma Supplies", "Navi Mumbai"),
    ("Goregaon Medi Wholesale", "Mumbai"),
    ("Malad Healthcare Supply", "Mumbai"),
    ("Sahyadri Pharma Distributors", "Pune"),
    ("Ulhasnagar Drug Centre", "Ulhasnagar"),
    ("Vasai Virar Medico", "Vasai"),
    ("Chembur Pharma Depot", "Mumbai"),
    ("Mira Road Drug House", "Mira Bhayandar"),
    ("Neelkanth Pharma Link", "Mumbai"),
    ("Jai Hind Medical Agencies", "Thane"),
    ("Apex Pharma Wholesale", "Mumbai"),
    ("Lokmanya Drug Traders", "Thane"),
    ("Kurla Medico Supply", "Mumbai"),
    ("Byculla Pharma Distributors", "Mumbai"),
    ("Dombivli Healthcare Agency", "Dombivli"),
    ("Rajesh Medical Wholesale", "Mumbai"),
    ("Airoli Pharma Hub", "Navi Mumbai"),
    ("Kharghar Drug Distributors", "Navi Mumbai"),
    ("Nashik Road Pharma Link", "Nashik"),
    ("Tulsi Healthcare Traders", "Mumbai"),
    ("Samarth Medico Agencies", "Mumbai"),
]
