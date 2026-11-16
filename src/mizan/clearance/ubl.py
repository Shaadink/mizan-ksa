"""UBL 2.1 invoice XML builder (ZATCA Phase-2 shape, simplified; see HONESTY.md).

Two-step build so the hash can be computed BEFORE the signature exists:
  1. build_unsigned_xml(): invoice with ICV + PIH references, no UBLExtensions / cac:Signature / QR;
  2. attach_signature_and_qr(): adds exactly the three parts zatca_invoice_hash() removes, so
     hash(unsigned) == hash(signed) by construction (tested).
Built with the lxml element API (values are escaped, nothing is string-spliced).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from lxml import etree

from mizan.clearance.tlv_qr_and_state_machine import parse_invoice_xml

INV = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
EXT = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
DS = "http://www.w3.org/2000/09/xmldsig#"
# ZATCA wraps the XML signature in UBL's signature components (BR-KSA-28 / BR-KSA-29).
SIG = "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2"
SAC = "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2"
SBC = "urn:oasis:names:specification:ubl:schema:xsd:SignatureBasicComponents-2"
NSMAP = {None: INV, "cac": CAC, "cbc": CBC, "ext": EXT}
# BR-KSA-28 wants this exact SignatureInformation ID; BR-KSA-29 wants this exact referenced/cac ID.
SIGNATURE_INFORMATION_ID = "urn:oasis:names:specification:ubl:signature:1"
REFERENCED_SIGNATURE_ID = "urn:oasis:names:specification:ubl:signature:Invoice"
KSA = timezone(timedelta(hours=3))

TYPE_CODE = {"INVOICE": "388", "CREDIT_NOTE": "381"}
TYPE_NAME = {"CLEARANCE": "0100000", "REPORTING": "0200000"}  # standard (B2B) / simplified (B2C)


def _el(parent, ns: str, tag: str, text: str | None = None, **attrib):
    e = etree.SubElement(parent, f"{{{ns}}}{tag}", attrib)
    if text is not None:
        e.text = text
    return e


def issue_ts_ksa(issue_ts_utc: str) -> datetime:
    return datetime.strptime(issue_ts_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone(KSA)


def _vat_percent(req: dict) -> str:
    """The single VAT rate on the document. Every line is standard-rated; a mix would need a
    TaxSubtotal per rate, so refuse rather than silently report one rate for all of them."""
    rates = {ln["vat_rate"] for ln in req["lines"]}
    if len(rates) != 1:
        raise ValueError(f"document {req.get('invoice_uuid')} mixes VAT rates {sorted(rates)}; "
                         "one cac:TaxSubtotal per rate is required")
    return rates.pop()


def build_unsigned_xml(req: dict, *, icv: int, pih: str) -> bytes:
    flow, doc = req["invoice_flow"], req["document_type"]
    if flow not in TYPE_NAME or doc not in TYPE_CODE:
        raise ValueError(f"unknown flow/document {flow!r}/{doc!r}")
    ts = issue_ts_ksa(req["issue_ts_utc"])
    root = etree.Element(f"{{{INV}}}Invoice", nsmap=NSMAP)
    _el(root, CBC, "ProfileID", "reporting:1.0")
    _el(root, CBC, "ID", req["request_id"])
    _el(root, CBC, "UUID", req["invoice_uuid"])
    _el(root, CBC, "IssueDate", ts.strftime("%Y-%m-%d"))
    _el(root, CBC, "IssueTime", ts.strftime("%H:%M:%S"))
    _el(root, CBC, "InvoiceTypeCode", TYPE_CODE[doc], name=TYPE_NAME[flow])
    _el(root, CBC, "DocumentCurrencyCode", "SAR")
    _el(root, CBC, "TaxCurrencyCode", "SAR")
    if req.get("billing_reference_uuid"):
        br = _el(root, CAC, "BillingReference")
        _el(_el(br, CAC, "InvoiceDocumentReference"), CBC, "ID", req["billing_reference_uuid"])
    icv_ref = _el(root, CAC, "AdditionalDocumentReference")
    _el(icv_ref, CBC, "ID", "ICV")
    _el(icv_ref, CBC, "UUID", str(icv))
    pih_ref = _el(root, CAC, "AdditionalDocumentReference")
    _el(pih_ref, CBC, "ID", "PIH")
    _el(_el(pih_ref, CAC, "Attachment"), CBC, "EmbeddedDocumentBinaryObject", pih, mimeCode="text/plain")

    seller = req["seller"]
    sp = _el(_el(root, CAC, "AccountingSupplierParty"), CAC, "Party")
    _el(_el(sp, CAC, "PartyIdentification"), CBC, "ID", seller["cr_number"], schemeID="CRN")
    # BG-5 seller postal address (EN 16931 BR-08). UBL fixes the order: PostalAddress before
    # PartyTaxScheme, and the fields below in exactly this sequence.
    addr = seller.get("address")
    if addr:
        pa = _el(sp, CAC, "PostalAddress")
        _el(pa, CBC, "StreetName", addr["street_ar"])
        _el(pa, CBC, "BuildingNumber", addr["building_number"])
        # KSA-23 "additional number": the 4-digit secondary number of the Saudi national address
        # (BR-KSA-09 requires it, BR-KSA-64 requires exactly 4 digits).
        _el(pa, CBC, "PlotIdentification", addr["additional_number"])
        _el(pa, CBC, "CitySubdivisionName", addr["district_ar"])
        _el(pa, CBC, "CityName", addr["city_ar"])
        _el(pa, CBC, "PostalZone", addr["postal_zone"])
        _el(pa, CBC, "CountrySubentity", addr["region_ar"])
        _el(_el(pa, CAC, "Country"), CBC, "IdentificationCode", addr["country_code"])
    pts = _el(sp, CAC, "PartyTaxScheme")
    _el(pts, CBC, "CompanyID", seller["vat_number"])
    _el(_el(pts, CAC, "TaxScheme"), CBC, "ID", "VAT")
    _el(_el(sp, CAC, "PartyLegalEntity"), CBC, "RegistrationName", seller["name_ar"])

    cp = _el(_el(root, CAC, "AccountingCustomerParty"), CAC, "Party")
    buyer = req.get("buyer")
    if buyer:
        bts = _el(cp, CAC, "PartyTaxScheme")
        _el(bts, CBC, "CompanyID", buyer["vat_number"])
        _el(_el(bts, CAC, "TaxScheme"), CBC, "ID", "VAT")
        _el(_el(cp, CAC, "PartyLegalEntity"), CBC, "RegistrationName", buyer["name_ar"])

    # BG-23 VAT breakdown (EN 16931 BR-CO-18): one TaxSubtotal per VAT category/rate. Every line here is
    # standard-rated 15%, so there is exactly one subtotal, and its amounts are the invoice totals --
    # which is also what BR-CO-15 cross-checks (TaxInclusive = TaxExclusive + TaxAmount).
    tt = _el(root, CAC, "TaxTotal")
    _el(tt, CBC, "TaxAmount", req["vat_total_sar"], currencyID="SAR")
    sub = _el(tt, CAC, "TaxSubtotal")
    _el(sub, CBC, "TaxableAmount", req["total_excl_vat_sar"], currencyID="SAR")
    _el(sub, CBC, "TaxAmount", req["vat_total_sar"], currencyID="SAR")
    tc = _el(sub, CAC, "TaxCategory")
    _el(tc, CBC, "ID", "S", schemeID="UN/ECE 5305", schemeAgencyID="6")
    _el(tc, CBC, "Percent", _vat_percent(req))
    _el(_el(tc, CAC, "TaxScheme"), CBC, "ID", "VAT", schemeID="UN/ECE 5153", schemeAgencyID="6")
    # BR-KSA-EN16931-09: with cbc:TaxCurrencyCode present, ZATCA wants a second TaxTotal carrying only
    # the amount in the tax currency, with no subtotals. SAR is both currencies here, so same figure.
    _el(_el(root, CAC, "TaxTotal"), CBC, "TaxAmount", req["vat_total_sar"], currencyID="SAR")
    lmt = _el(root, CAC, "LegalMonetaryTotal")
    _el(lmt, CBC, "LineExtensionAmount", req["total_excl_vat_sar"], currencyID="SAR")
    _el(lmt, CBC, "TaxExclusiveAmount", req["total_excl_vat_sar"], currencyID="SAR")
    _el(lmt, CBC, "TaxInclusiveAmount", req["total_incl_vat_sar"], currencyID="SAR")
    _el(lmt, CBC, "PayableAmount", req["total_incl_vat_sar"], currencyID="SAR")
    for ln in req["lines"]:
        il = _el(root, CAC, "InvoiceLine")
        _el(il, CBC, "ID", str(ln["line_id"]))
        _el(il, CBC, "InvoicedQuantity", str(ln["qty"]), unitCode="PCE")
        _el(il, CBC, "LineExtensionAmount", ln["line_net_sar"], currencyID="SAR")
        ltt = _el(il, CAC, "TaxTotal")
        _el(ltt, CBC, "TaxAmount", ln["line_vat_sar"], currencyID="SAR")
        line_total = Decimal(ln["line_net_sar"]) + Decimal(ln["line_vat_sar"])
        _el(ltt, CBC, "RoundingAmount", f"{line_total:.2f}", currencyID="SAR")
        item = _el(il, CAC, "Item")
        _el(item, CBC, "Name", ln["item_ar"])
        ctc = _el(item, CAC, "ClassifiedTaxCategory")
        _el(ctc, CBC, "ID", "S")
        _el(ctc, CBC, "Percent", ln["vat_rate"])
        _el(_el(ctc, CAC, "TaxScheme"), CBC, "ID", "VAT")
        _el(_el(il, CAC, "Price"), CBC, "PriceAmount", ln["unit_price_sar"], currencyID="SAR")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


# XMLDSig requires ds:Signature children in this order: SignedInfo, SignatureValue, KeyInfo, Object.
# ZATCA's SDK rejects the invoice at XSD validation if SignedInfo is missing.
C14N11 = "http://www.w3.org/2006/12/xml-c14n11"
ECDSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"
SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
XPATH_TRANSFORM = "http://www.w3.org/TR/1999/REC-xpath-19991116"
# The three nodes excluded from the signed data are exactly the ones invoice_digest() strips, so the
# DigestValue below equals ctl.invoice_outbox.invoice_hash.
EXCLUDED_XPATHS = (
    "not(//ancestor-or-self::ext:UBLExtensions)",
    "not(//ancestor-or-self::cac:Signature)",
    "not(//ancestor-or-self::cac:AdditionalDocumentReference[cbc:ID='QR'])",
)


def _signed_info(sig, invoice_hash: str) -> None:
    """ds:SignedInfo naming the canonicalisation, the ECDSA/SHA-256 suite and the invoice digest."""
    si = _el(sig, DS, "SignedInfo")
    etree.SubElement(si, f"{{{DS}}}CanonicalizationMethod", Algorithm=C14N11)
    etree.SubElement(si, f"{{{DS}}}SignatureMethod", Algorithm=ECDSA_SHA256)
    ref = etree.SubElement(si, f"{{{DS}}}Reference", Id="invoiceSignedData", URI="")
    transforms = _el(ref, DS, "Transforms")
    for xp in EXCLUDED_XPATHS:
        t = etree.SubElement(transforms, f"{{{DS}}}Transform", Algorithm=XPATH_TRANSFORM)
        _el(t, DS, "XPath", xp)
    etree.SubElement(transforms, f"{{{DS}}}Transform", Algorithm=C14N11)
    etree.SubElement(ref, f"{{{DS}}}DigestMethod", Algorithm=SHA256)
    _el(ref, DS, "DigestValue", invoice_hash)


def attach_signature_and_qr(unsigned_xml: bytes, *, signature_b64: str, certificate_b64: str, qr_b64: str,
                            invoice_hash: str) -> bytes:
    """Add UBLExtensions (SignedInfo + signature value + cert), cac:Signature, and the QR reference.

    invoice_hash is the already-computed base64 digest; it goes in ds:DigestValue. Everything added here
    lives inside UBLExtensions / cac:Signature / the QR reference, all of which invoice_digest() strips,
    so nothing here can change any invoice_hash or the PIH chain.
    """
    root = parse_invoice_xml(unsigned_xml)
    exts = etree.Element(f"{{{EXT}}}UBLExtensions")
    ext = _el(exts, EXT, "UBLExtension")
    _el(ext, EXT, "ExtensionURI", "urn:oasis:names:specification:ubl:dsig:enveloped:xades")
    content = _el(ext, EXT, "ExtensionContent")
    # ZATCA's wrapper: UBLDocumentSignatures > SignatureInformation > ds:Signature, carrying the two IDs
    # that BR-KSA-28 and BR-KSA-29 check.
    docsigs = etree.SubElement(content, f"{{{SIG}}}UBLDocumentSignatures",
                               nsmap={"sig": SIG, "sac": SAC, "sbc": SBC})
    info = etree.SubElement(docsigs, f"{{{SAC}}}SignatureInformation")
    _el(info, CBC, "ID", SIGNATURE_INFORMATION_ID)
    _el(info, SBC, "ReferencedSignatureID", REFERENCED_SIGNATURE_ID)
    sig = etree.SubElement(info, f"{{{DS}}}Signature", nsmap={"ds": DS}, Id="signature")
    _signed_info(sig, invoice_hash)
    _el(sig, DS, "SignatureValue", signature_b64)
    _el(_el(_el(sig, DS, "KeyInfo"), DS, "X509Data"), DS, "X509Certificate", certificate_b64)
    root.insert(0, exts)

    # QR reference goes right after the PIH reference; cac:Signature right after it
    pih_ref = root.xpath("cac:AdditionalDocumentReference[cbc:ID='PIH']", namespaces={"cac": CAC, "cbc": CBC})[0]
    qr_ref = etree.Element(f"{{{CAC}}}AdditionalDocumentReference")
    _el(qr_ref, CBC, "ID", "QR")
    _el(_el(qr_ref, CAC, "Attachment"), CBC, "EmbeddedDocumentBinaryObject", qr_b64, mimeCode="text/plain")
    pih_ref.addnext(qr_ref)
    s = etree.Element(f"{{{CAC}}}Signature")
    # BR-KSA-29 requires this exact ID on cac:Signature (the SignatureInformation ID differs; see above).
    _el(s, CBC, "ID", REFERENCED_SIGNATURE_ID)
    _el(s, CBC, "SignatureMethod", "urn:oasis:names:specification:ubl:dsig:enveloped:xades")
    qr_ref.addnext(s)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def read_refs(xml_bytes: bytes) -> dict:
    """Extract ICV, PIH, UUID and the QR payload from a signed invoice (for the verifier and mock)."""
    root = parse_invoice_xml(xml_bytes)
    ns = {"cac": CAC, "cbc": CBC}

    def one(xp: str) -> str | None:
        r = root.xpath(xp, namespaces=ns)
        return r[0] if r else None

    att = "cac:Attachment/cbc:EmbeddedDocumentBinaryObject/text()"
    return {"uuid": one("cbc:UUID/text()"),
            "icv": one("cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID/text()"),
            "pih": one(f"cac:AdditionalDocumentReference[cbc:ID='PIH']/{att}"),
            "qr": one(f"cac:AdditionalDocumentReference[cbc:ID='QR']/{att}"),
            "vat_total": one("cac:TaxTotal/cbc:TaxAmount/text()"),
            "line_vats": [str(v) for v in
                          root.xpath("cac:InvoiceLine/cac:TaxTotal/cbc:TaxAmount/text()", namespaces=ns)]}
