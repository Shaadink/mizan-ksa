# LinkedIn post draft

(Attach the 2:30 video. Under 200 words.)

---

Every halala, reconciled.

I built MIZAN-KSA: a Saudi commerce and payments data platform on Microsoft Fabric that follows one transaction
end to end: the order, the ZATCA Phase-2 e-invoice, the mada/SADAD T+1 bank settlement and the ERP general ledger.

What it does:
- Reconciles SAR 22.39M across 2,233 merchant-days to exactly 0.00, and refuses to call a day "balanced" before
  its bank file arrives.
- Keeps an unbroken ZATCA hash chain through timeouts and a worker crash: 25,001 documents, zero breaks.
- Erases a person under PDPL by shredding their keys, while the signed tax records stay on legal hold.
- Resolves five Arabic spellings of one customer without merging two brothers.

Stack: Fabric Lakehouse, Warehouse and Eventhouse, PySpark, dbt, Airflow, OpenLineage, and a live Fabric App
(Rayfin) that queries the semantic model with DAX, in English and Arabic. 468 Python tests and 184 app tests run on
every push.

All data is synthetic; this is an engineering reference, not a certified tax product.

#MicrosoftFabric #DataEngineering #ZATCA #SaudiArabia #dbt #PowerBI

---

Word count (body, without hashtags): about 160.
