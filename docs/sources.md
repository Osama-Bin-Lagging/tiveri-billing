# Source notes

The ERP Group article provided with the assignment informed the list of workflows to consider for a small or mid-sized hospital. Its numerical performance claims, universal GST statements, and product claims are not treated as evidence. The slides and implementation separate what the prototype demonstrates from what a live deployment would require.

- [IRDAI health insurance department](https://irdai.gov.in/health-dept): cashless preauthorisation, final authorisation and claims context.
- [National Health Authority PM-JAY operational manual](https://nha.gov.in/img/resources/Operation%20Manual%20for%20AB%20PM-JAY.pdf): beneficiary, transaction management, package and claim workflow.
- [NHA HBP 2.2 manual](https://nha.gov.in/img/resources/HBP-2.2-manual.pdf): selected packages require preauthorisation; actual rates and requirements depend on scheme configuration.
- [CGHS approved rates](https://dgehs.delhi.gov.in/dghs/cghs-approved-rates-treatment-and-investigative-procedures): reference list for a scheme-specific rate card.
- [NRCeS ABDM FHIR R4 guide](https://www.nrces.in/ndhm/fhir/r4/): India health record and insurance exchange profiles, including Claim and ClaimResponse bundles.
- [CBIC goods and services rates](https://cbic-gst.gov.in/hindi/gst-goods-services-rates.html): healthcare service and specified room service entries. The supplied marketing article's blanket 18% rate for non-ICU rooms above Rs 5,000/day conflicts with the current official rate table's 5% entry subject to conditions.
- [GST Council / PIB 2025 medicine FAQ](https://gstcouncil.gov.in/sites/default/files/2025-09/faq_0.pdf): drugs and medicines are generally 5% except specified nil-rated medicines; medical devices are generally 5% except specifically exempted items. The demo's nil item is a training category, not a named real medicine.
- [CBIC GST goods and services rates](https://cbic-gst.gov.in/hindi/gst-goods-services-rates.html): HSN 3006 lists all types of contraceptives at nil rate. The demo uses an unnamed contraceptive product as its nil training SKU.
- [GST Council AAR discussion of inpatient treatment supplies](https://gstcouncil.gov.in/sites/default/files/AAR/gst_ara_order_in_case_of_laxmi_health_care_center_iccu_order_2_11zon_compressed_1.pdf): medicine and consumable supplies during qualifying inpatient treatment can form part of an exempt composite healthcare supply, while separate outpatient pharmacy supplies are taxable by item. The prototype models this distinction as a teaching example; actual treatment requires case-specific review.
- [GST portal GSTR-1 guide](https://tutorial.gst.gov.in/userguide/returns/GSTR_1.htm): includes Table 8 for nil-rated, exempt and non-GST outward supplies. The supplied article's claim that exempt supplies are not reported in GSTR-1 is therefore not used.
- [MoHFW Patients' Rights Charter](https://clinicalestablishments.mohfw.gov.in/sites/default/files/2023-07/8431.pdf): patients should receive an itemised bill and payment receipts.
- [WHO ICD classification](https://www.who.int/classifications/classification-of-diseases): ICD-10 classification context for the doctor's provisional diagnosis code.
- DH 308 lecture slides supplied with the assignment: ER modelling, database concepts, HIS, HL7, ICD/LOINC and ABDM context.

The friend group's presentation is used for visual direction only. The separate `ER_Diagram.pptx` supplied by the user provides the final presentation's Chen notation conceptual ER image. Its broader LIS and RIS entities are design context, not claims that those modules are implemented in the website.
