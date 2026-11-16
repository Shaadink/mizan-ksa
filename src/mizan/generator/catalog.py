r"""Static reference catalogue for the synthetic generator.

All Arabic literals are \uXXXX escapes (CLAUDE.md rule: right-to-left text reverses in PDFs/editors).
Prices, fee rates and names are synthetic and stated as such in HONESTY.md.
"""

from decimal import Decimal

MALE_FIRST = (
    ("\u0645\u062D\u0645\u062F", "Mohammed"),
    ("\u0639\u0628\u062F\u0627\u0644\u0644\u0647", "Abdullah"),
    ("\u0641\u0647\u062F", "Fahad"),
    ("\u062E\u0627\u0644\u062F", "Khalid"),
    ("\u0633\u0639\u0648\u062F", "Saud"),
    ("\u0641\u064A\u0635\u0644", "Faisal"),
    ("\u0639\u0628\u062F\u0627\u0644\u0631\u062D\u0645\u0646", "Abdulrahman"),
    ("\u0633\u0644\u0637\u0627\u0646", "Sultan"),
    ("\u0646\u0627\u0635\u0631", "Nasser"),
    ("\u062A\u0631\u0643\u064A", "Turki"),
    ("\u0628\u0646\u062F\u0631", "Bandar"),
    ("\u0645\u0627\u062C\u062F", "Majid"),
    ("\u0639\u0645\u0631", "Omar"),
    ("\u064A\u0648\u0633\u0641", "Yousef"),
    ("\u0625\u0628\u0631\u0627\u0647\u064A\u0645", "Ibrahim"),
    ("\u0623\u062D\u0645\u062F", "Ahmed"),
    ("\u0633\u0644\u0645\u0627\u0646", "Salman"),
    ("\u0646\u0627\u064A\u0641", "Nayef"),
    ("\u0628\u0644\u0627\u0644", "Bilal"),
    ("\u0639\u0644\u064A", "Ali"),
)
FEMALE_FIRST = (
    ("\u0646\u0648\u0631\u0629", "Noura"),
    ("\u0633\u0627\u0631\u0629", "Sarah"),
    ("\u0641\u0627\u0637\u0645\u0629", "Fatimah"),
    ("\u0631\u064A\u0645", "Reem"),
    ("\u0647\u064A\u0641\u0627\u0621", "Haifa"),
    ("\u0645\u0646\u0649", "Mona"),
    ("\u0644\u0637\u064A\u0641\u0629", "Latifa"),
    ("\u0639\u0628\u064A\u0631", "Abeer"),
    ("\u0623\u0645\u0644", "Amal"),
    ("\u0647\u0646\u062F", "Hind"),
)
FAMILY = (
    ("\u0627\u0644\u0639\u062A\u064A\u0628\u064A", "Al Otaibi"),
    ("\u0627\u0644\u0642\u062D\u0637\u0627\u0646\u064A", "Al Qahtani"),
    ("\u0627\u0644\u0634\u0645\u0631\u064A", "Al Shammari"),
    ("\u0627\u0644\u062F\u0648\u0633\u0631\u064A", "Al Dosari"),
    ("\u0627\u0644\u062D\u0631\u0628\u064A", "Al Harbi"),
    ("\u0627\u0644\u063A\u0627\u0645\u062F\u064A", "Al Ghamdi"),
    ("\u0627\u0644\u0632\u0647\u0631\u0627\u0646\u064A", "Al Zahrani"),
    ("\u0627\u0644\u0645\u0637\u064A\u0631\u064A", "Al Mutairi"),
    ("\u0627\u0644\u0633\u0628\u064A\u0639\u064A", "Al Subaie"),
    ("\u0627\u0644\u0639\u0646\u0632\u064A", "Al Anazi"),
    ("\u0627\u0644\u0634\u0647\u0631\u064A", "Al Shehri"),
    ("\u0627\u0644\u0631\u0634\u064A\u062F", "Al Rasheed"),
    ("\u0627\u0644\u0633\u062F\u064A\u0631\u064A", "Al Sudairi"),
    ("\u0627\u0644\u0628\u0642\u0645\u064A", "Al Buqami"),
    ("\u0627\u0644\u064A\u0627\u0645\u064A", "Al Yami"),
)
ORG_WORDS = (
    ("\u0627\u0644\u0646\u062E\u0628\u0629", "Al Nukhba"),
    ("\u0627\u0644\u0623\u0641\u0642", "Al Ufuq"),
    ("\u0627\u0644\u0631\u0648\u0627\u062F", "Al Rowad"),
    ("\u0627\u0644\u0635\u0641\u0648\u0629", "Al Safwa"),
    ("\u0627\u0644\u0645\u062F\u0627\u0631", "Al Madar"),
    ("\u0627\u0644\u0631\u064A\u0627\u062F\u0629", "Al Riyada"),
)
ORG_FORMS = (
    ("\u0634\u0631\u0643\u0629 {} \u0644\u0644\u062A\u062C\u0627\u0631\u0629", "{} Trading Co."),
    ("\u0645\u0624\u0633\u0633\u0629 {} \u0644\u0644\u0645\u0642\u0627\u0648\u0644\u0627\u062A", "{} Contracting Est."),
    ("\u0645\u062C\u0645\u0648\u0639\u0629 {} \u0627\u0644\u0642\u0627\u0628\u0636\u0629", "{} Holding Group"),
)
CITIES = (
    ("\u0627\u0644\u0631\u064A\u0627\u0636", "Riyadh"),
    ("\u062C\u062F\u0629", "Jeddah"),
    ("\u0627\u0644\u062F\u0645\u0627\u0645", "Dammam"),
    ("\u0645\u0643\u0629 \u0627\u0644\u0645\u0643\u0631\u0645\u0629", "Makkah"),
    ("\u0627\u0644\u0645\u062F\u064A\u0646\u0629 \u0627\u0644\u0645\u0646\u0648\u0631\u0629", "Madinah"),
)
DISTRICTS = (
    ("\u0627\u0644\u0639\u0644\u064A\u0627", "Al Olaya"),
    ("\u0627\u0644\u0646\u062E\u064A\u0644", "Al Nakheel"),
    ("\u0627\u0644\u0645\u0644\u0632", "Al Malaz"),
    ("\u0627\u0644\u0633\u0644\u0627\u0645\u0629", "Al Salamah"),
    ("\u0627\u0644\u0631\u0648\u0636\u0629", "Al Rawdah"),
    ("\u0627\u0644\u0634\u0627\u0637\u0626", "Al Shatie"),
)
ITEMS = (
    ("\u062A\u0645\u0631 \u062E\u0644\u0627\u0635 1 \u0643\u062C\u0645", "Khalas dates 1kg"),
    ("\u0642\u0647\u0648\u0629 \u0639\u0631\u0628\u064A\u0629 500 \u062C\u0645", "Arabic coffee 500g"),
    ("\u062F\u0647\u0646 \u0639\u0648\u062F", "Oud oil"),
    ("\u0634\u0645\u0627\u063A", "Shemagh"),
    ("\u062B\u0648\u0628", "Thobe"),
    ("\u0639\u0628\u0627\u064A\u0629", "Abaya"),
    ("\u0633\u062C\u0627\u062F\u0629 \u0635\u0644\u0627\u0629", "Prayer rug"),
    ("\u0647\u0627\u062A\u0641 \u0630\u0643\u064A", "Smartphone"),
    ("\u0633\u0645\u0627\u0639\u0627\u062A \u0644\u0627\u0633\u0644\u0643\u064A\u0629", "Wireless headphones"),
    ("\u062D\u0644\u064A\u0628 \u0637\u0627\u0632\u062C", "Fresh milk"),
    ("\u0623\u0631\u0632 \u0628\u0633\u0645\u062A\u064A 5 \u0643\u062C\u0645", "Basmati rice 5kg"),
    ("\u0645\u064A\u0627\u0647 12 \u0639\u0628\u0648\u0629", "Water 12-pack"),
    ("\u0634\u0627\u064A", "Tea"),
    ("\u0639\u0633\u0644 \u0633\u062F\u0631", "Sidr honey"),
    ("\u062D\u0627\u0633\u0628 \u0645\u062D\u0645\u0648\u0644", "Laptop"),
    ("\u0633\u0627\u0639\u0629 \u064A\u062F", "Wristwatch"),
    ("\u0643\u062A\u0627\u0628", "Book"),
    ("\u0641\u0627\u0646\u0648\u0633 \u0631\u0645\u0636\u0627\u0646", "Ramadan lantern"),
    ("\u0645\u0643\u0633\u0631\u0627\u062A \u0645\u0634\u0643\u0644\u0629", "Mixed nuts"),
    ("\u0632\u064A\u062A \u0632\u064A\u062A\u0648\u0646", "Olive oil"),
)
GOLDEN = (
    ("\u0645\u062D\u0645\u062F \u0628\u0644\u0627\u0644 \u0627\u0644\u0639\u062A\u064A\u0628\u064A", "Mohammed Bilal Al Otaibi"),
)
BROTHERS = (
    ("\u0639\u0628\u062F\u0627\u0644\u0631\u062D\u0645\u0646 \u0639\u0628\u062F\u0627\u0644\u0644\u0647 \u0627\u0644\u0642\u062D\u0637\u0627\u0646\u064A", "Abdulrahman Abdullah Al Qahtani"),
    ("\u0639\u0628\u062F\u0627\u0644\u0631\u062D\u064A\u0645 \u0639\u0628\u062F\u0627\u0644\u0644\u0647 \u0627\u0644\u0642\u062D\u0637\u0627\u0646\u064A", "Abdulraheem Abdullah Al Qahtani"),
)

# Unit prices excl. VAT (SAR), aligned with ITEMS by index. Electronics skew to e-commerce.
# Every price is a multiple of 0.20 SAR so that 15% VAT lands exactly on the halala. ZATCA's BR-KSA-50
# compares the line VAT to net x rate/100 with NO rounding, so a price like 89.90 (VAT 13.485) can never
# satisfy it: 13.485 is not expressible in halalas. Real Saudi retailers price around the same constraint.
# This is a data choice only -- money stays Decimal with ROUND_HALF_UP everywhere.
ITEM_PRICES = tuple(Decimal(p) for p in (
    "35.00", "48.00", "260.00", "120.00", "210.00", "340.00", "75.00", "2199.00",
    "399.00", "6.40", "42.80", "10.00", "18.20", "90.00", "3499.00",
    "899.00", "45.00", "59.00", "64.40", "38.40",
))
ECOM_ITEM_IDX = (2, 5, 7, 8, 13, 14, 15, 16, 0, 1, 3, 4)
STORE_ITEM_IDX = tuple(range(20))

VAT_RATE = Decimal("0.15")

SELLER_NAME = "Najd Omnichannel Commerce Group"
SELLER_NAME_AR = "\u0645\u062C\u0645\u0648\u0639\u0629 \u0646\u062C\u062F \u0644\u0644\u062A\u062C\u0627\u0631\u0629"
SELLER_VAT = "300000000000003"
SELLER_CR = "1010000001"
# Seller postal address (BG-5). EN 16931 rule BR-08 requires it on every invoice, and ZATCA's SDK
# rejects the document without it. Synthetic, like every other address in this project: ZATCA expects
# a 4-digit building number and a 5-digit postal zone.
SELLER_STREET_AR = "\u0637\u0631\u064A\u0642 \u0627\u0644\u0645\u0644\u0643 \u0641\u0647\u062F"
SELLER_BUILDING_NUMBER = "8721"
SELLER_ADDITIONAL_NUMBER = "2345"   # KSA-23, must be 4 digits (BR-KSA-64)
SELLER_DISTRICT_AR = "\u062D\u064A \u0627\u0644\u0639\u0644\u064A\u0627"
SELLER_CITY_AR = "\u0627\u0644\u0631\u064A\u0627\u0636"
SELLER_POSTAL_ZONE = "12212"
SELLER_REGION_AR = "\u0645\u0646\u0637\u0642\u0629 \u0627\u0644\u0631\u064A\u0627\u0636"
SELLER_COUNTRY_CODE = "SA"

# Acquirer fee schedule (synthetic). The BANK applies it and sends fees in the file;
# MIZAN only re-uses it to estimate IN_TRANSIT expectation rows (spec Module 3).
# scheme -> (MDR rate on purchases, fee cap or None)
FEE_SCHEDULE = {
    "MADA": (Decimal("0.0080"), Decimal("200.00")),
    "VISA": (Decimal("0.0195"), None),
    "MASTERCARD": (Decimal("0.0195"), None),
    "BNPL": (Decimal("0.0400"), None),
    "SADAD": (Decimal("0.0050"), Decimal("10.00")),
}
CHARGEBACK_FEE = Decimal("50.00")
VAT_ON_FEE_RATE = Decimal("0.15")

ECOM_SCHEME_MIX = (("MADA", 55), ("VISA", 20), ("MASTERCARD", 12), ("BNPL", 10), ("SADAD", 3))
STORE_SCHEME_MIX = (("MADA", 75), ("VISA", 15), ("MASTERCARD", 10))

# ACDOCA-shaped GL: account -> (gl_account_role, normal side S=debit / H=credit)
GL_ACCOUNTS = {
    "100100": ("CASH_ON_HAND", "S"),
    "113100": ("CARD_CLEARING", "S"),
    "400000": ("REVENUE", "H"),
    "220100": ("VAT_OUTPUT", "H"),
    "680100": ("CHARGEBACK_LOSS", "S"),
}
COMPANY_CODE = "NJD1"
LEDGER = "0L"
