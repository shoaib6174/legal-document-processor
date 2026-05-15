import json
import os
from typing import List

from groq import Groq

from .models import CaseFactSummary, CitationError, RetrievedEvidence


class DraftGenerator:
    """Generate grounded Case Fact Summaries via Groq LLM.

    Uses a two-stage pipeline for complex documents:
    Stage 1: Analyze evidence → document_summary + key themes
    Stage 2: Generate structured CaseFactSummary with stage-1 context
    """

    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is required")
        self.client = Groq(api_key=api_key)
        self.model = model

    def generate(
        self,
        query: str,
        evidence: List[RetrievedEvidence],
        correction_rules: List[str] | None = None,
        max_retries: int = 2,
        use_two_stage: bool = True,
    ) -> CaseFactSummary:
        """Generate a draft with validation and retry logic.

        Args:
            query: The generation query (e.g. "Generate a case fact summary")
            evidence: Retrieved evidence passages with chunk IDs
            correction_rules: Optional feedback-derived rules to inject
            max_retries: Number of retry attempts on validation failure
            use_two_stage: If True, run stage-1 analysis before structured generation.
                          This improves accuracy for complex documents.
        """
        evidence_text = self._format_evidence(evidence)
        valid_chunk_ids = {ev.chunk_id for ev in evidence}
        rules_text = self._format_rules(correction_rules or [])
        retry_errors: List[str] = []

        # Stage 1: Document analysis (optional, for complex docs)
        stage1_analysis = ""
        if use_two_stage and len(evidence) >= 3:
            try:
                stage1_analysis = self._stage1_analyze(
                    query, evidence_text, rules_text
                )
            except Exception:
                # If stage 1 fails, fall back to single-stage
                stage1_analysis = ""

        for attempt in range(max_retries + 1):
            try:
                draft = self._generate_once(
                    query,
                    evidence_text,
                    rules_text,
                    retry_errors,
                    attempt,
                    stage1_analysis,
                )
                self._validate_output(draft, valid_chunk_ids)
                return draft
            except (json.JSONDecodeError, CitationError) as e:
                if attempt == max_retries:
                    raise
                retry_errors.append(str(e))

        # Should never reach here, but type checker needs it
        raise RuntimeError("Max retries exceeded without raising")

    def _stage1_analyze(
        self, query: str, evidence_text: str, rules_text: str
    ) -> str:
        """Stage 1: Analyze evidence to produce a document overview.

        This gives the model a chance to "read" and understand the document
        before being asked to produce structured output. Returns a free-form
        analysis string that stage 2 uses as context.
        """
        system_prompt = """You are a legal document analyst. Read the evidence passages and produce a concise analysis.

Your output should be 3-5 bullet points covering:
1. What type of document this is and who the parties are
2. Key dates and deadlines mentioned
3. Any monetary amounts, fees, or financial terms
4. The main purpose or conflict of the document
5. Any ambiguous or unclear information

Be factual. Only mention information explicitly present in the evidence.
Do NOT invent information."""

        user_prompt = f"""Query: {query}

Evidence passages:
{evidence_text}

Provide a concise analysis."""

        if rules_text:
            user_prompt += f"\n\n{rules_text}"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=1024,
        )

        return response.choices[0].message.content

    def _generate_once(
        self,
        query: str,
        evidence_text: str,
        rules_text: str,
        retry_errors: List[str],
        attempt: int,
        stage1_analysis: str = "",
    ) -> CaseFactSummary:
        system_prompt = self._build_system_prompt(
            rules_text, retry_errors, attempt
        )
        user_prompt = self._build_user_prompt(
            query, evidence_text, stage1_analysis
        )

        # Dynamic token limit based on evidence length
        max_tokens = min(4096, 500 + len(evidence_text) // 3)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        raw_json = response.choices[0].message.content
        parsed = json.loads(raw_json)
        return CaseFactSummary(**parsed)

    def _build_system_prompt(
        self, rules_text: str, retry_errors: List[str], attempt: int
    ) -> str:
        base_prompt = """You are a legal document assistant. Generate a structured Case Fact Summary based ONLY on the provided evidence.

CRITICAL RULES:
1. Every fact MUST cite at least one evidence chunk_id in supporting_evidence.
2. If a fact cannot be supported by evidence, put it in "uncertainties" instead.
3. Do NOT make up information not present in the evidence.
4. Be concise and factual.
5. Use only the chunk_ids provided in the evidence — do not invent chunk_ids.
6. For parties, include only organizational entities (companies, corporations, LLCs). Do NOT include individual officers, attorneys, or signatories as parties.
7. For claims, only include claims that are explicitly stated in the evidence. Do NOT infer claims.
8. For dates, use only dates explicitly mentioned in the evidence. Do not infer or assume dates.
9. document_summary: a 1-2 sentence description of what the document IS (e.g. "Employment agreement between..." or "Property dispute lawsuit filed by...").
10. financial_summary: list ALL monetary amounts mentioned (fees, settlements, damages, salaries, etc.) with descriptions. Empty list if no money mentioned.

Respond with a single valid JSON object matching this structure:
{
  "document_summary": "One or two sentences describing what the document is about.",
  "parties": [{"name": "...", "role": "..."}],
  "key_facts": [{"statement": "...", "supporting_evidence": ["chunk_id"]}],
  "dates": [{"date": "...", "event": "..."}],
  "claims": [{"description": "...", "supporting_evidence": ["chunk_id"]}],
  "uncertainties": ["..."],
  "financial_summary": [{"amount": "$...", "description": "...", "supporting_evidence": ["chunk_id"]}]
}"""

        few_shot = """
EXAMPLES:

Good output:
{
  "document_summary": "Employment agreement between ACME INDUSTRIES LLC and Dr. Amanda Park for a Senior VP role.",
  "parties": [{"name": "ACME INDUSTRIES LLC", "role": "employer"}],
  "key_facts": [{"statement": "The agreement fee is $125,000.", "supporting_evidence": ["doc1_p1_c0"]}],
  "dates": [{"date": "March 15, 2024", "event": "Agreement signed"}],
  "claims": [],
  "uncertainties": ["The exact scope of consulting services is unclear from the evidence."],
  "financial_summary": [{"amount": "$125,000", "description": "Annual consulting fee", "supporting_evidence": ["doc1_p1_c0"]}]
}

Bad output (missing citations):
{
  "document_summary": "",
  "parties": [{"name": "ACME LLC", "role": "provider"}],
  "key_facts": [{"statement": "The fee was negotiated down.", "supporting_evidence": []}],
  "dates": [{"date": "March 2024", "event": "Signing"}],
  "claims": [{"description": "Breach of contract", "supporting_evidence": []}],
  "uncertainties": [],
  "financial_summary": []
}

The bad output is wrong because: (1) facts have no citations, (2) "Breach of contract" is inferred, not stated, (3) the date is vague, (4) missing document_summary and financial info."""

        parts = [base_prompt, few_shot]

        if rules_text:
            parts.append(rules_text)

        if retry_errors:
            parts.append(
                f"PREVIOUS ATTEMPT(S) FAILED:\n"
                + "\n".join(f"- {e}" for e in retry_errors)
                + "\nPlease correct these issues in your response."
            )

        if attempt > 0:
            parts.append(
                f"This is attempt {attempt + 1}. Be extra careful with JSON validity and citations."
            )

        return "\n\n".join(parts)

    def _build_user_prompt(
        self, query: str, evidence_text: str, stage1_analysis: str = ""
    ) -> str:
        parts = [
            f"Query: {query}",
            "",
            "Evidence passages (ranked by relevance, highest first):",
            evidence_text,
        ]

        if stage1_analysis:
            parts.extend([
                "",
                "--- Pre-analysis (for context) ---",
                stage1_analysis,
                "",
                "Use the pre-analysis above as guidance, but base ALL facts strictly on the evidence passages with proper citations.",
            ])

        parts.extend([
            "",
            "Generate the Case Fact Summary.",
        ])

        return "\n".join(parts)

    def _format_evidence(self, evidence: List[RetrievedEvidence]) -> str:
        """Format evidence with confidence indicators and source grouping."""
        # Sort by score descending
        sorted_ev = sorted(evidence, key=lambda e: e.score, reverse=True)

        lines = []
        current_source = None

        for i, ev in enumerate(sorted_ev, 1):
            # Group by source document
            if ev.source_doc != current_source:
                current_source = ev.source_doc
                lines.append(f"\n--- Source: {ev.source_doc} ---")

            confidence = "HIGH" if ev.score > 0.02 else "MEDIUM" if ev.score > 0.01 else "LOW"
            lines.append(
                f"[{i}] chunk_id={ev.chunk_id} | page={ev.page_num} | confidence={confidence} | text: {ev.text[:500]}"
                + ("... [truncated]" if len(ev.text) > 500 else "")
            )

        return "\n".join(lines)

    def _format_rules(self, rules: List[str]) -> str:
        if not rules:
            return ""
        lines = ["CORRECTION RULES (apply these principles):"]
        for i, rule in enumerate(rules, 1):
            lines.append(f"{i}. {rule}")
        return "\n".join(lines)

    def _validate_output(
        self, draft: CaseFactSummary, valid_chunk_ids: set
    ) -> None:
        """Validate that all citations reference existing evidence chunks."""
        # Collect all cited chunk_ids
        all_citations: set = set()
        for fact in draft.key_facts:
            all_citations.update(fact.supporting_evidence)
        for claim in draft.claims:
            all_citations.update(claim.supporting_evidence)
        for item in draft.financial_summary:
            all_citations.update(item.supporting_evidence)

        # Check for hallucinated citations
        invalid = all_citations - valid_chunk_ids
        if invalid:
            raise CitationError(
                f"Draft contains invalid chunk_ids: {invalid}. "
                f"Valid chunk_ids are: {valid_chunk_ids}"
            )

        # Check that every fact/claim/financial item has at least one citation
        for i, fact in enumerate(draft.key_facts):
            if not fact.supporting_evidence:
                raise CitationError(
                    f"key_facts[{i}] ('{fact.statement[:50]}...') has no supporting_evidence"
                )

        for i, claim in enumerate(draft.claims):
            if not claim.supporting_evidence:
                raise CitationError(
                    f"claims[{i}] ('{claim.description[:50]}...') has no supporting_evidence"
                )

        for i, item in enumerate(draft.financial_summary):
            if not item.supporting_evidence:
                raise CitationError(
                    f"financial_summary[{i}] ('{item.amount} — {item.description[:50]}...') has no supporting_evidence"
                )
