---
authority: eiopa
qa_id: "DORA092 - 3076"
joint_id: "DORA092"
legal_act: "DORA"
legal_act_ref: "(EU) 2022/2554"
legal_act_raw: "DORA - Regulation (EU) 2022/2554"
article: "B_06.01.0010 and B_06.01.0020"
topic: "Register of Information (DORA)"
status: "Final"
date_date_of_submission: "18 Apr 2024"
date_date_of_submission_iso: "2024-04-18"
date_publication_final_answer: "2025-03-28"
date_publication_final_answer_iso: "2025-03-28"
date_submission_to_esas: "2024-04-18"
date_submission_to_esas_iso: "2024-04-18"
x_answered_by: "Joint ESAs"
source_url: "https://www.eiopa.europa.eu/qa-regulation/questions-and-answers-database/dora092-3076_en"
retrieved_at: "2026-07-08T20:14:52+00:00"
---

# EIOPA Q&A DORA092 - 3076

## Question

Could a same Function Identifier in field B_06.01.0010 be linked to multiple options/values (including the value ‘support functions’) in field B_06.01.0020?

What is the meaning of ‘linked’ in the instruction of the field B_06.01.0020?

## Background

We noticed that it is difficult to interpret whether functions such as 'Compliance', 'Legal', 'Risk Management', 'Audit', 'Anti-Money-Laundering', etc. should be included as a) (general) support functions, or b) function assigned to each business line, or c) potentially even both in the template.

## Answer

No, a function identifier in field B_06.01.0010 could not be linked to multiple options/values in field B_06.01.0020.

Regarding the meaning of ‘linked’ in field B_06.01.0020, each function reported in B_06.01.0010 shall be ‘linked’ to a ‘licenced activity’ listed in annex II (i.e. the function is part of the core licenced activity). In case the function could not be linked to a licenced activity (because it is not relevant), ‘support function’ shall be reported in B_06.01.0020 instead of the ‘licenced activity’. From a practical perspective, the taxonomy is provided in the data model (technical package for reporting the register of information on EBA website).

The FE should be careful from a data management perspective to ensure the unicity of the function identifier and its consistency within the Register of Information templates to avoid data quality issues. According to the data model ( Data Model for DORA RoI.pdf ), each combination of function identifier in field B_06.01.0010 and LEI of the financial entity in field B_06.01.0040 shall be unique. Therefore, to avoid triggering data quality errors, a unique function identifier should be used for every licenced activity in field B_06.01.0020 and function name in field B_06.01.0030 associated to the same LEI of the financial entity in field B_06.01.0040.

---

> **Disclaimer.** Unofficial, automatically generated mirror copy — no guarantee and no liability is accepted for accuracy, completeness or timeliness; conversion errors are possible. Before any use or reliance, verify against the original: <https://www.eiopa.europa.eu/qa-regulation/questions-and-answers-database/dora092-3076_en> — the authority's portal version prevails. Content © the respective authority; reuse subject to its legal notice.
