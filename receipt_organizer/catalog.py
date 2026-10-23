"""Default categories from the user's merchant table (editable in config.json overrides) + safe naming."""
import re, datetime
DEFAULTS = {
 "MR.DIY": ("Household & maintenance", "Hardware & supplies"), "ACE Hardware": ("Household & maintenance", "Hardware & supplies"),
 "Bel Pasto Pizza": ("Food & beverages", "Dining out"), "Xiao Li Jia": ("Food & beverages", "Dining out"),
 "Chong Qing Impression": ("Food & beverages", "Dining out"), "Sushi Mentai": ("Food & beverages", "Dining out"), "KFC": ("Food & beverages", "Dining out"),
 "Bistro Fiore": ("Food & beverages", "Dining out"), "Cempedak Bay": ("Food & beverages", "Dining out"), "Bingxue": ("Food & beverages", "Drinks & desserts"),
 "AEON": ("Groceries", "Food & household essentials"), "AEON Big": ("Groceries", "Food & household essentials"), "Wheat Mart": ("Groceries", "Food & household essentials"),
 "Jaya Grocer": ("Groceries", "Food & household essentials"), "NSK Grocer": ("Groceries", "Food & household essentials"), "Oriental Mart": ("Groceries", "Food & household essentials"),
 "Pantai Selamat": ("Groceries", "Food & household essentials"), "Bilabila Mart": ("Groceries", "Food & household essentials"), "99 Speedmart": ("Groceries", "Food & household essentials"),
 "Tunas Manja": ("Groceries", "Food & household essentials"),
 "Shell": ("Transport", "Fuel"), "Petron": ("Transport", "Fuel"), "Petronas": ("Transport", "Fuel"), "Caltex": ("Transport", "Fuel"),
 "United Tyre Service": ("Transport", "Tyres & vehicle maintenance"), "OptiSaver": ("Health & medical", "Eyewear"),
 "Galaxy Sports": ("Shopping", "Sportswear & equipment"), "Adidas": ("Shopping", "Clothing & footwear"), "Apple": ("Shopping", "Electronics & accessories"),
 "TNB": ("Utilities", "Electricity"), "PAIP": ("Utilities", "Water"), "Air Selangor": ("Utilities", "Water"), "Indah Water": ("Utilities", "Sewerage"),
 "Unifi": ("Utilities", "Internet & phone"), "Maxis": ("Utilities", "Internet & phone"), "CelcomDigi": ("Utilities", "Internet & phone"), "U Mobile": ("Utilities", "Internet & phone"),
 "TIME": ("Utilities", "Internet & phone"), "Astro": ("Utilities", "TV & streaming"), "Gas Malaysia": ("Utilities", "Gas"),
 "Cukai Tanah (land tax)": ("Utilities", "Assessment & land tax"), "Cukai Taksiran (assessment)": ("Utilities", "Assessment & land tax"),
 # not in the user's table: sensible suggestions, shown as 'suggested' in the index so the user can confirm
 "Village Grocer": ("Groceries", "Food & household essentials"), "Gula Cakery": ("Food & beverages", "Drinks & desserts"),
 "Nando's": ("Food & beverages", "Dining out"), "Burger King/Cosmo": ("Food & beverages", "Dining out"), "LH Foodcraft": ("Food & beverages", "Dining out"),
 "Yang Claypot": ("Food & beverages", "Dining out"),
 # medicine: pharmacy chains (Watsons/Guardian also sell toiletries - change per receipt if needed)
 "Guardian": ("Medicine", "Pharmacy & medicine"), "Watsons": ("Medicine", "Pharmacy & medicine"), "Caring Pharmacy": ("Medicine", "Pharmacy & medicine"),
 "Big Pharmacy": ("Medicine", "Pharmacy & medicine"), "Alpro Pharmacy": ("Medicine", "Pharmacy & medicine"), "AA Pharmacy": ("Medicine", "Pharmacy & medicine"),
 "Health Lane": ("Medicine", "Pharmacy & medicine"), "Sunway Pharmacy": ("Medicine", "Pharmacy & medicine"), "Pharmacy": ("Medicine", "Pharmacy & medicine"),
 # pets
 "Pet Lovers Centre": ("Pets", "Pet food & supplies"), "Pets Wonderland": ("Pets", "Pet food & supplies"), "Petsmore": ("Pets", "Pet food & supplies"),
 "Pet World": ("Pets", "Pet food & supplies"), "Pet Shop": ("Pets", "Pet food & supplies"), "Veterinary Clinic": ("Pets", "Vet & pet clinic"),
}
NEW_SUGGESTED = {"Guardian", "Watsons", "Caring Pharmacy", "Big Pharmacy", "Alpro Pharmacy", "AA Pharmacy", "Health Lane", "Sunway Pharmacy", "Pharmacy",
 "Pet Lovers Centre", "Pets Wonderland", "Petsmore", "Pet World", "Pet Shop", "Veterinary Clinic"}
FROM_USER_TABLE = {"Village Grocer", "Gula Cakery", "Nando's", "Burger King/Cosmo", "LH Foodcraft", "Yang Claypot"} | NEW_SUGGESTED
KEYWORDS = [
 (r"\bRESORT\b", ("Hotel & accommodation", "Resort")),
 (r"HOMESTAY|AIRBNB|\bVILLA\b|GUEST\s*HOUSE|GUESTHOUSE|CHALET", ("Hotel & accommodation", "Homestay & Airbnb")),
 (r"HOTEL|\bINN\b|\bLODGE\b|HOSTEL|MOTEL|\bSUITES?\b|AGODA|BOOKING\.COM|TRIP\.COM|\bHILTON|MARRIOTT|SHERATON|HYATT|IBIS\b|NOVOTEL|HOLIDAY\s*INN|TUNE\s*HOTEL|DORSETT|DOUBLETREE", ("Hotel & accommodation", "Hotel")),
 (r"PHARMACY|FARMASI", ("Medicine", "Pharmacy & medicine")),
 (r"\bPETS?\b|VETERINAR|KLINIK\s*HAIWAN", ("Pets", "Pet food & supplies")),
]
MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']
def category(merchant, overrides=None):
    if overrides and merchant in overrides: return tuple(overrides[merchant]), 'override'
    if merchant in DEFAULTS: return DEFAULTS[merchant], ('suggested' if merchant in FROM_USER_TABLE else 'default')
    for pat, cs in KEYWORDS:                                   # name not in the list: guess from words in the name (shown as 'suggested')
        if merchant and re.search(pat, merchant, re.I): return cs, 'suggested'
    return ("Uncategorised", "Needs category"), 'none'
def slug(s): return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', (s or '').lower().replace('&', ' ').replace("'", ''))).strip('_')
def filename(date, cat, sub, merchant, n, ext='.jpg'):
    d = date.strftime('%y%m%d') if date else 'undated'
    return f"{d}_{slug(cat)}_{slug(sub)}_{slug(merchant)}_{n}{ext}"
def month_folder(d): return MONTHS[d.month - 1]
