import json
import os
from typing import List

from groq import Groq

from .models import CaseFactSummary, RetrievedEvidence


class DraftGenerator:
    """Generate grounded Case Fact Summaries via Groq LLM."""

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
    ) -> CaseFactSummary:
        evidence_text = self._format_evidence(evidence)
        rules_text = self._format_rules(correction_rules or [])

        system_prompt = f"""You are a legal document assistant. Generate a structured Case Fact Summary based ONLY on the provided evidence.

CRITICAL RULES:
1. Every fact MUST cite at least one evidence chunk_id in supporting_evidence.
2. If a fact cannot be supported by evidence, put it in "uncertainties" instead.
3. Do NOT make up information not present in the evidence.
4. Be concise and factual.

{rules_text}

Respond with a single valid JSON object matching this structure:
{{
  "parties": [{{"name": "...", "role": "plaintiff/defendant/other"}}],
  "key_facts": [{{"statement": "...", "supporting_evidence": ["chunk_id"]}}],
  "dates": [{{"date": "...", "event": "..."}}],
  "claims": [{{"description": "...", "supporting_evidence": ["chunk_id"]}}],
  "uncertainties": ["..."]
}}"""

        user_prompt = f"""Query: {query}

Evidence passages:
{evidence_text}

Generate the Case Fact Summary."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=2048,
            response_format={"type": "json_object"},
        )

        raw_json = response.choices[0].message.content
        parsed = json.loads(raw_json)
        return CaseFactSummary(**parsed)

    def _format_evidence(self, evidence: List[RetrievedEvidence]) -> str:
        lines = []
        for i, ev in enumerate(evidence, 1):
            lines.append(
                f"[{i}] chunk_id={ev.chunk_id} | source={ev.source_doc} page={ev.page_num} | text: {ev.text}"
            )
        return "\n".join(lines)

    def _format_rules(self, rules: List[str]) -> str:
        if not rules:
            return ""
        lines = ["CORRECTION RULES (apply these preferences):"]
        for i, rule in enumerate(rules, 1):
            lines.append(f"{i}. {rule}")
        return "\n".join(lines)
