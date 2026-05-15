# Edit Session Demonstration

**Document:** `complex_litigation_clean.pdf` — Stipulation and Settlement Agreement  
**Date:** 2026-05-15  
**Purpose:** Demonstrate the feedback loop: operator edits → rule extraction → future improvement

---

## Document Overview

The synthetic document exercises all 8 entity types:

| Entity Type | Examples in Document |
|---|---|
| **Party** | OMEGA PHARMACEUTICALS INC., THETA DISTRIBUTION LLC |
| **Individual** | Alexander Mercer (Plaintiff) |
| **Date** | October 14, 2024, June 3, 2024 |
| **Amount** | $3,250,000, $875,000, $312,000, $425,000 |
| **Case Number** | 3:24-cv-00421 |
| **Case Citation** | Mercer v. Omega Pharmaceuticals Inc., 2024 WL 2847561 |
| **Statute Citation** | 815 ILCS 505/1 |
| **Court** | United States District Court for the Central District of Illinois |
| **Judge** | Hon. Judge Margaret Chen |

---

## Initial Generated Draft

```json
{
  "document_summary": "Stipulation and Settlement Agreement between Alexander Mercer, Omega Pharmaceuticals Inc., and Theta Distribution LLC.",
  "parties": [
    {"name": "Omega Pharmaceuticals Inc.", "role": "defendant"},
    {"name": "Theta Distribution LLC", "role": "defendant"}
  ],
  "key_facts": [
    {
      "statement": "The settlement agreement was entered into as of October 14, 2024.",
      "supporting_evidence": ["complex_litigation_clean.pdf_p1_c0"]
    },
    {
      "statement": "The parties shall bear their own attorneys' fees and costs, except as provided in Section 4.",
      "supporting_evidence": ["complex_litigation_clean.pdf_p2_c0"]
    },
    {
      "statement": "Defendants shall pay $425,000 to the Law Firm of Harrison & Doyle for attorneys' fees.",
      "supporting_evidence": ["complex_litigation_clean.pdf_p2_c0"]
    }
  ],
  "dates": [
    {"date": "October 14, 2024", "event": "Settlement agreement entered into"}
  ],
  "claims": [],
  "uncertainties": [
    "The exact terms of the mutual release of claims are unclear from the evidence."
  ],
  "financial_summary": [
    {
      "amount": "$425,000",
      "description": "Payment to the Law Firm of Harrison & Doyle for attorneys' fees",
      "supporting_evidence": ["complex_litigation_clean.pdf_p2_c0"]
    },
    {
      "amount": "$312,000",
      "description": "Estimated applicable employer payroll taxes",
      "supporting_evidence": ["complex_litigation_clean.pdf_p1_c1"]
    }
  ]
}
```

**Issues identified by operator:**
1. **Missing plaintiff** — Alexander Mercer is not listed in parties
2. **Missing settlement amounts** — The main payments ($3.25M and $875K) are absent from financial_summary
3. **Missing court date** — June 3, 2024 court opinion not in dates
4. **Missing claims** — Breach of contract, fraudulent misrepresentation, Consumer Fraud Act violation not listed

---

## Operator Edits

### Edit 1: Add Plaintiff Party

Added Alexander Mercer as plaintiff:

```json
{"name": "Alexander Mercer", "role": "plaintiff"}
```

### Edit 2: Add Missing Settlement Amounts

Added the two main settlement payments to financial_summary:

```json
{
  "amount": "$3,250,000",
  "description": "Settlement payment from Omega Pharmaceuticals to Plaintiff",
  "supporting_evidence": ["complex_litigation_clean.pdf_p1_c0"]
}
```

```json
{
  "amount": "$875,000",
  "description": "Settlement payment from Theta Distribution to Plaintiff",
  "supporting_evidence": ["complex_litigation_clean.pdf_p1_c0"]
}
```

### Edit 3: Add Court Opinion Date

Added the motion-to-dismiss ruling date:

```json
{"date": "June 3, 2024", "event": "Court issued Memorandum Opinion and Order on motion to dismiss"}
```

---

## Corrected Draft

```json
{
  "document_summary": "Stipulation and Settlement Agreement between Alexander Mercer, Omega Pharmaceuticals Inc., and Theta Distribution LLC.",
  "parties": [
    {"name": "Alexander Mercer", "role": "plaintiff"},
    {"name": "Omega Pharmaceuticals Inc.", "role": "defendant"},
    {"name": "Theta Distribution LLC", "role": "defendant"}
  ],
  "key_facts": [...],
  "dates": [
    {"date": "October 14, 2024", "event": "Settlement agreement entered into"},
    {"date": "June 3, 2024", "event": "Court issued Memorandum Opinion and Order on motion to dismiss"}
  ],
  "claims": [],
  "uncertainties": [...],
  "financial_summary": [
    {
      "amount": "$3,250,000",
      "description": "Settlement payment from Omega Pharmaceuticals to Plaintiff",
      "supporting_evidence": ["complex_litigation_clean.pdf_p1_c0"]
    },
    {
      "amount": "$875,000",
      "description": "Settlement payment from Theta Distribution to Plaintiff",
      "supporting_evidence": ["complex_litigation_clean.pdf_p1_c0"]
    },
    {
      "amount": "$425,000",
      "description": "Payment to the Law Firm of Harrison & Doyle for attorneys' fees",
      "supporting_evidence": ["complex_litigation_clean.pdf_p2_c0"]
    },
    {
      "amount": "$312,000",
      "description": "Estimated applicable employer payroll taxes",
      "supporting_evidence": ["complex_litigation_clean.pdf_p1_c1"]
    }
  ]
}
```

---

## Feedback Results

After submitting the edited draft:

```json
{
  "status": "success",
  "rules_learned": 3,
  "total_diffs": 5,
  "active_rules": [
    "Do not include facts without supporting evidence citations. Every fact must be traceable to a specific evidence passage.",
    "Do not generate content without strong supporting evidence. Remove unsupported items.",
    "Verify that every fact and claim cites evidence chunks that actually support the stated content. Do not cite chunks that do not contain the relevant information."
  ]
}
```

### Rules Extracted from This Edit Session

The feedback engine performed a deep-diff between original and edited drafts, then generalized the differences into reusable rules:

| Rule | Source Edit | Type |
|---|---|---|
| "Do not include facts without supporting evidence citations..." | Financial items added with citations | evidence_fix |
| "Do not generate content without strong supporting evidence..." | Missing settlement amounts | removal |
| "Verify that every fact and claim cites evidence chunks that actually support the stated content..." | Party added with supporting context | evidence_fix |

These rules are now stored in SQLite with frequency counters. On the next document generation, the top 3 rules by confidence score will be injected into the LLM system prompt as "CORRECTION RULES."

---

## How This Demonstrates the Feedback Loop

1. **Capture:** The system stored the original draft and compared it to the operator's edited version
2. **Extract:** 3 reusable rules were generalized from 5 specific diffs using heuristics + LLM fallback
3. **Score:** Previously-applied rules were evaluated for effectiveness (success/failure counters updated)
4. **Inject:** The top rules are now queued for injection into the next generation prompt
5. **Improve:** Future drafts will include these rules, reducing the likelihood of the same errors

---

## Evidence Retrieved

The retrieval layer surfaced these chunks (hybrid dense + sparse + RRF):

| Chunk | Page | Method | RRF Score |
|---|---|---|---|
| `complex_litigation_clean.pdf_p3_c0` | 3 | hybrid | 0.0323 |
| `complex_litigation_clean.pdf_p2_c0` | 2 | hybrid | 0.0320 |
| `complex_litigation_clean.pdf_p1_c0` | 1 | hybrid | 0.0320 |
| `complex_litigation_clean.pdf_p2_c1` | 2 | hybrid | 0.0318 |
| `complex_litigation_clean.pdf_p1_c1` | 1 | hybrid | 0.0308 |

Every fact in the draft cites at least one of these chunks, and the grounding verifier confirmed semantic alignment.
