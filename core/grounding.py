"""Post-generation grounding verification.

Ensures every generated fact is semantically supported by retrieved evidence.
Moves unsupported facts to uncertainties with an explanation.
"""

from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

from .models import CaseFactSummary, Claim, Fact, FinancialItem, RetrievedEvidence


class GroundingVerifier:
    """Verify that generated facts are grounded in retrieved evidence.

    Uses semantic similarity to check whether each fact/claim is actually
    supported by the chunks it cites (or by any retrieved chunk).
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.encoder = SentenceTransformer(model_name)
        self.threshold = 0.55  # Cosine similarity threshold for grounding

    def verify(self, draft: CaseFactSummary, evidence: List[RetrievedEvidence]) -> CaseFactSummary:
        """Verify and fix grounding issues in a draft.

        For each fact/claim/financial item:
        1. Encode the statement
        2. Encode all evidence chunks
        3. Check max similarity against cited chunks AND all chunks
        4. If below threshold, move to uncertainties with explanation
        5. If cited chunks are not the most similar ones, flag in uncertainties
        """
        if not evidence:
            return draft

        evidence_texts = [e.text for e in evidence]
        evidence_embeddings = self.encoder.encode(evidence_texts)
        chunk_id_to_idx = {e.chunk_id: i for i, e in enumerate(evidence)}

        new_facts: List[Fact] = []
        new_claims: List[Claim] = []
        new_financial: List[FinancialItem] = []
        new_uncertainties = list(draft.uncertainties)

        # Verify key_facts
        for fact in draft.key_facts:
            grounded, reason = self._check_grounding(
                fact.statement, fact.supporting_evidence,
                evidence, evidence_embeddings, chunk_id_to_idx
            )
            if grounded:
                new_facts.append(fact)
            else:
                new_uncertainties.append(
                    f"[Grounding check] Fact moved to uncertainties: {fact.statement} ({reason})"
                )

        # Verify claims
        for claim in draft.claims:
            grounded, reason = self._check_grounding(
                claim.description, claim.supporting_evidence,
                evidence, evidence_embeddings, chunk_id_to_idx
            )
            if grounded:
                new_claims.append(claim)
            else:
                new_uncertainties.append(
                    f"[Grounding check] Claim moved to uncertainties: {claim.description} ({reason})"
                )

        # Verify financial_summary
        for item in draft.financial_summary:
            grounded, reason = self._check_grounding(
                f"{item.amount} — {item.description}",
                item.supporting_evidence,
                evidence, evidence_embeddings, chunk_id_to_idx
            )
            if grounded:
                new_financial.append(item)
            else:
                new_uncertainties.append(
                    f"[Grounding check] Financial item moved to uncertainties: {item.amount} — {item.description} ({reason})"
                )

        return CaseFactSummary(
            document_summary=draft.document_summary,
            parties=draft.parties,
            key_facts=new_facts,
            dates=draft.dates,
            claims=new_claims,
            uncertainties=new_uncertainties,
            financial_summary=new_financial,
        )

    def _check_grounding(
        self,
        statement: str,
        cited_chunk_ids: List[str],
        evidence: List[RetrievedEvidence],
        evidence_embeddings: np.ndarray,
        chunk_id_to_idx: dict,
    ) -> tuple[bool, str]:
        """Check if a statement is grounded in evidence.

        Returns (is_grounded, reason_if_not).
        """
        if not cited_chunk_ids:
            return False, "no citations provided"

        if evidence_embeddings.size == 0:
            return False, "no evidence available"

        statement_embedding = self.encoder.encode([statement])

        # Compute similarities to all evidence
        similarities = np.dot(evidence_embeddings, statement_embedding.T).flatten()
        max_sim = float(np.max(similarities))
        max_idx = int(np.argmax(similarities))
        best_chunk = evidence[max_idx].chunk_id

        # Check 1: Is the statement semantically similar to ANY evidence?
        if max_sim < self.threshold:
            return False, f"low semantic similarity ({max_sim:.2f}) to all evidence"

        # Check 2: Are the cited chunks among the most similar ones?
        cited_indices = []
        for cid in cited_chunk_ids:
            if cid in chunk_id_to_idx:
                cited_indices.append(chunk_id_to_idx[cid])

        if not cited_indices:
            return False, f"cited chunks not found in evidence"

        cited_sims = similarities[cited_indices]
        avg_cited_sim = float(np.mean(cited_sims))

        # If cited chunks are significantly worse than the best chunk, flag it
        if avg_cited_sim < max_sim - 0.15:
            return False, (
                f"cited chunks have low similarity ({avg_cited_sim:.2f}) "
                f"compared to best evidence ({max_sim:.2f}, {best_chunk})"
            )

        return True, ""

    def get_grounding_scores(
        self, draft: CaseFactSummary, evidence: List[RetrievedEvidence]
    ) -> dict:
        """Return grounding scores for each section without modifying the draft.

        Useful for displaying confidence indicators in the UI.
        """
        if not evidence:
            return {"overall": 0.0, "facts": [], "claims": [], "financial": []}

        evidence_texts = [e.text for e in evidence]
        evidence_embeddings = self.encoder.encode(evidence_texts)
        chunk_id_to_idx = {e.chunk_id: i for i, e in enumerate(evidence)}

        def score_item(statement: str, cited_ids: List[str]) -> dict:
            emb = self.encoder.encode([statement])
            sims = np.dot(evidence_embeddings, emb.T).flatten()
            max_sim = float(np.max(sims))
            max_idx = int(np.argmax(sims))

            cited_indices = [chunk_id_to_idx[c] for c in cited_ids if c in chunk_id_to_idx]
            cited_sims = sims[cited_indices] if cited_indices else [0.0]
            avg_cited = float(np.mean(cited_sims))

            return {
                "max_similarity": round(max_sim, 3),
                "avg_cited_similarity": round(avg_cited, 3),
                "best_chunk_id": evidence[max_idx].chunk_id if evidence else None,
                "grounded": max_sim >= self.threshold and avg_cited >= max_sim - 0.15,
            }

        return {
            "overall": round(
                np.mean([
                    score_item(f.statement, f.supporting_evidence)["max_similarity"]
                    for f in draft.key_facts
                ] + [
                    score_item(c.description, c.supporting_evidence)["max_similarity"]
                    for c in draft.claims
                ] + [
                    score_item(f"{fi.amount} {fi.description}", fi.supporting_evidence)["max_similarity"]
                    for fi in draft.financial_summary
                ]),
                3,
            ) if (draft.key_facts or draft.claims or draft.financial_summary) else 1.0,
            "facts": [
                score_item(f.statement, f.supporting_evidence)
                for f in draft.key_facts
            ],
            "claims": [
                score_item(c.description, c.supporting_evidence)
                for c in draft.claims
            ],
            "financial": [
                score_item(f"{fi.amount} {fi.description}", fi.supporting_evidence)
                for fi in draft.financial_summary
            ],
        }
