---
authority: eiopa
qa_id: "3568"
joint_id: ""
legal_act: "DORA"
legal_act_ref: "(EU) 2022/2554"
legal_act_raw: "Risk-Free Interest Rate - General questions"
article: ""
topic: "Risk Free Rate (RFR)"
status: "Final"
date_date_of_submission: "13 May 2026"
date_date_of_submission_iso: "2026-05-13"
source_url: "https://www.eiopa.europa.eu/qa-regulation/questions-and-answers-database/3568_en"
retrieved_at: "2026-07-08T09:30:22+00:00"
---

# EIOPA Q&A 3568

## Question

Could you please provide clarification on the stressed last liquid forward rate used for the computation of the SCR interest rate up/down curves? In item (43) that amends Article 166 (page 33), it says that "the stress to the last liquid forward rates shall be determined by applying the weights used for the determination of the current last liquid forward rate referred to in Article 46(1c) to the stresses applied to the interest rates corresponding to maturities referred to in points (a) and (b) of that Article, under the assumption that paragraph 2 of this Article applies to those maturities." Does this mean the following? First, apply the formula from (43) (a) 2 to the base RFR curve for all maturities. Then take the difference of the resulting curve and the base RFR curve. Then define the LLFR stress to be the weighted average of the resulting differences in spot curves and compute the stressed LLFR additively to be equal to the base LLFR plus the LLFR stress. Or does one take weighted averages of forward curves and otherwise as above? Or is the weighted average taken over the s_m and b_m and the stressed LLFR is base LLFR * (1+weighed average s_m)+weighted average b_m?

## Answer

Please find an example of the calculation in our recently published Excel workbook at

https://www.eiopa.europa.eu/document/download/01e0930c-d78d-4806-8e83-a…

The sheets ‘IRR Up Shock’ and ‘IRR Down Shock’ exemplify how to calculate these curves.

---

> **Disclaimer.** Unofficial, automatically generated mirror copy — no guarantee and no liability is accepted for accuracy, completeness or timeliness; conversion errors are possible. Before any use or reliance, verify against the original: <https://www.eiopa.europa.eu/qa-regulation/questions-and-answers-database/3568_en> — the authority's portal version prevails. Content © the respective authority; reuse subject to its legal notice.
