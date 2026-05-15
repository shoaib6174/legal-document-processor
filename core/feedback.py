import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Tuple


class FeedbackEngine:
    """Capture operator edits, extract reusable correction rules, and track effectiveness.

    The feedback loop works as follows:
    1. Generate draft with top-N rules injected into the prompt
    2. Operator edits the draft
    3. Deep-diff original vs edited to find changes
    4. Generalize each diff into a reusable rule
    5. Score previously applied rules: did they prevent the same mistake?
    6. Future generations only inject rules with proven effectiveness
    """

    def __init__(self, db_path: str = "./data/feedback.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._last_applied_rules: List[str] = []

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                field_path TEXT NOT NULL,
                original_value TEXT,
                edited_value TEXT,
                frequency INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                generalized_rule TEXT,
                rule_type TEXT,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                last_applied TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()

    def track_applied_rules(self, rules: List[str]) -> None:
        """Record which rules were injected into the last generation prompt.

        Call this BEFORE generation so capture_edit can score effectiveness.
        """
        self._last_applied_rules = list(rules)

    def capture_edit(
        self, original: dict, edited: dict, applied_rules: Optional[List[str]] = None
    ) -> dict:
        """Capture differences between original and edited drafts.

        Returns statistics about what was learned and how effective previous rules were.
        """
        diffs = self._deep_diff(original, edited)
        rules_to_score = applied_rules or self._last_applied_rules

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        new_rules_count = 0

        for field_path, orig_val, edit_val in diffs:
            generalized = self._generalize_rule(field_path, orig_val, edit_val)
            rule_type = self._classify_rule_type(orig_val, edit_val)

            # Check for semantic duplicates before inserting
            similar_id = self._find_similar_rule(cursor, generalized)

            if similar_id:
                # Merge with existing similar rule
                cursor.execute(
                    """
                    UPDATE corrections
                    SET frequency = frequency + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (similar_id,),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO corrections (field_path, original_value, edited_value, generalized_rule, rule_type)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (field_path, orig_val, edit_val, generalized, rule_type),
                )
                new_rules_count += 1

        # Score previously applied rules
        scored = self._score_applied_rules(cursor, diffs, rules_to_score)

        conn.commit()
        conn.close()

        return {
            "new_rules_learned": new_rules_count,
            "total_diffs": len(diffs),
            "rules_scored": scored,
        }

    def _score_applied_rules(
        self, cursor, diffs: List[Tuple[str, str, str]], applied_rules: List[str]
    ) -> int:
        """Score previously applied rules based on whether they prevented edits.

        If a rule was applied but the operator STILL had to make a similar edit,
        the rule failed. If no similar edit was needed, the rule succeeded.
        """
        if not applied_rules:
            return 0

        scored = 0
        for rule_text in applied_rules:
            # Find the rule in the database
            cursor.execute(
                "SELECT id FROM corrections WHERE generalized_rule = ?",
                (rule_text,),
            )
            row = cursor.fetchone()
            if not row:
                continue

            rule_id = row[0]

            # Check if any diff matches what this rule was supposed to prevent
            rule_failed = False
            for field_path, orig_val, edit_val in diffs:
                if self._rule_would_prevent(rule_text, field_path, orig_val, edit_val):
                    rule_failed = True
                    break

            if rule_failed:
                cursor.execute(
                    """
                    UPDATE corrections
                    SET failure_count = failure_count + 1, last_applied = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (rule_id,),
                )
            else:
                cursor.execute(
                    """
                    UPDATE corrections
                    SET success_count = success_count + 1, last_applied = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (rule_id,),
                )
            scored += 1

        return scored

    def _rule_would_prevent(
        self, rule_text: str, field_path: str, original: str, edited: str
    ) -> bool:
        """Check if a previously learned rule should have prevented this edit.

        Returns True if the rule was supposed to catch this but didn't.
        """
        rule_lower = rule_text.lower()

        # Party-related rules
        if "parties" in field_path:
            if "organizational" in rule_lower or "individual" in rule_lower or "officer" in rule_lower:
                # Rule says "only orgs" but an individual was present → rule failed
                if self._is_removal(original, edited):
                    return True
            if "full legal name" in rule_lower and ".name" in field_path:
                if original != edited:
                    return True

        # Claim-related rules
        if "claims" in field_path and "claim" in rule_lower:
            if self._is_removal(original, edited):
                return True

        # Fact-related rules
        if "key_facts" in field_path and "evidence" in rule_lower:
            if self._is_removal(original, edited):
                return True

        # Date-related rules
        if "dates" in field_path and "date" in rule_lower:
            if self._is_removal(original, edited) or original != edited:
                return True

        # Evidence/citation rules
        if "evidence" in rule_lower or "citation" in rule_lower:
            if self._is_evidence_correction(original, edited):
                return True

        # Financial rules
        if "financial" in rule_lower or "monetary" in rule_lower or "amount" in rule_lower:
            if "financial_summary" in field_path and original != edited:
                return True

        return False

    def get_rules(
        self, limit: int = 3, min_confidence: float = 0.3
    ) -> List[str]:
        """Get top correction rules by weighted score, filtering out low-confidence rules.

        Confidence = success_count / (success_count + failure_count)
        Rules with insufficient data (fewer than 2 applications) use frequency as proxy.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT generalized_rule, frequency, success_count, failure_count,
                   JULIANDAY('now') - JULIANDAY(updated_at) as days_old
            FROM corrections
            WHERE generalized_rule IS NOT NULL AND generalized_rule != ''
            """
        )
        rows = cursor.fetchall()
        conn.close()

        scored_rules = []
        for generalized, freq, success, failure, days_old in rows:
            if not generalized or not self._is_valid_rule(generalized):
                continue

            total = (success or 0) + (failure or 0)
            if total >= 2:
                # Enough data: use empirical success rate
                confidence = (success or 0) / total
            else:
                # Insufficient data: neutral confidence that increases with frequency
                confidence = min(0.6, 0.3 + freq * 0.05)

            # Recency decay: rules get stale over time
            recency_factor = max(0.5, 1.0 - (days_old or 0) / 90.0)

            # Score = confidence * frequency * recency
            score = confidence * freq * recency_factor

            if confidence >= min_confidence:
                scored_rules.append((generalized, score, confidence))

        # Sort by score descending
        scored_rules.sort(key=lambda x: x[1], reverse=True)

        # Store which rules we're about to apply (for later scoring)
        top_rules = [r[0] for r in scored_rules[:limit]]
        self._last_applied_rules = top_rules

        return top_rules

    def get_stats(self) -> dict:
        """Return feedback store statistics with effectiveness metrics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(frequency), 0),
                   COUNT(DISTINCT generalized_rule),
                   COALESCE(SUM(success_count), 0),
                   COALESCE(SUM(failure_count), 0)
            FROM corrections
            """
        )
        count, total_freq, unique_rules, total_success, total_failure = cursor.fetchone()
        conn.close()

        total_trials = (total_success or 0) + (total_failure or 0)
        effectiveness = (total_success / total_trials * 100) if total_trials > 0 else None

        return {
            "rule_count": count,
            "total_frequency": total_freq,
            "unique_generalized_rules": unique_rules,
            "total_success": total_success,
            "total_failure": total_failure,
            "effectiveness_pct": round(effectiveness, 1) if effectiveness is not None else None,
        }

    # ──────────────────────────────
    # Semantic Deduplication
    # ──────────────────────────────

    def _find_similar_rule(self, cursor, rule_text: str) -> Optional[int]:
        """Find an existing rule that is semantically similar to rule_text.

        Uses token overlap similarity. Returns the ID of the similar rule or None.
        """
        cursor.execute(
            """
            SELECT id, generalized_rule FROM corrections
            WHERE generalized_rule IS NOT NULL AND generalized_rule != ''
            """
        )
        best_id = None
        best_score = 0.0
        threshold = 0.6

        rule_tokens = set(self._tokenize(rule_text))
        if not rule_tokens:
            return None

        for row_id, existing in cursor.fetchall():
            existing_tokens = set(self._tokenize(existing))
            if not existing_tokens:
                continue

            # Jaccard similarity
            intersection = len(rule_tokens & existing_tokens)
            union = len(rule_tokens | existing_tokens)
            similarity = intersection / union if union > 0 else 0

            if similarity > best_score and similarity >= threshold:
                best_score = similarity
                best_id = row_id

        return best_id

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize rule text for similarity comparison."""
        # Lowercase, remove punctuation, split into meaningful words
        cleaned = re.sub(r"[^\w\s]", " ", text.lower())
        words = cleaned.split()
        # Filter out stop words
        stop_words = {"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or", "is", "are", "be", "do", "not"}
        return [w for w in words if len(w) > 2 and w not in stop_words]

    # ──────────────────────────────
    # Heuristic Generalizers
    # ──────────────────────────────

    def _generalize_rule(self, field_path: str, original: str, edited: str) -> str:
        """Transform a literal diff into a reusable principle."""
        # 1. Party filter FIRST: parties list shrinks, removed items contain titles
        if "parties" in field_path and self._is_party_filter(original, edited):
            return "In the parties list, include only organizational entities (companies, corporations, LLCs, partnerships). Remove individual officers, signatories, and attorneys."

        # 2. Removal pattern: original has content, edited is empty/null
        if self._is_removal(original, edited):
            return self._generalize_removal(field_path, original)

        # 3. Evidence correction: chunk_ids changed
        if self._is_evidence_correction(original, edited):
            return "Verify that every fact and claim cites evidence chunks that actually support the stated content. Do not cite chunks that do not contain the relevant information."

        # 4. Date correction: date string changed
        if self._is_date_correction(original, edited):
            return "Use only dates explicitly stated in the evidence. Do not infer, assume, or approximate dates. Use the exact format found in the source text."

        # 5. Amount correction: dollar amount changed
        if self._is_amount_correction(original, edited):
            return "Verify all monetary amounts against the evidence. Do not calculate, estimate, or round amounts. Use the exact figure stated in the source text."

        # 6. Officer added to parties
        if "parties" in field_path and self._is_officer_addition(original, edited):
            return "Do not add individual persons to the parties list unless they are sole proprietors or personally named parties. Organizational entities only."

        # 7. Uncertainty moved to fact (or vice versa)
        if "uncertainties" in field_path and original == '""':
            return "If a statement has supporting evidence, include it as a key_fact or claim with proper citations. Do not leave supported facts in uncertainties."
        if "uncertainties" in field_path and edited == '""':
            return "If a statement lacks supporting evidence, place it in uncertainties rather than including it as a confirmed fact or claim."

        # 8. Party name correction: use full legal name
        if "parties" in field_path and ".name" in field_path:
            return "Use the full legal name of each party as it appears in the evidence. Do not abbreviate or shorten party names."

        # 9. Role correction for parties
        if "parties" in field_path and ".role" in field_path:
            return "Assign accurate roles to parties based on their description in the evidence (e.g., plaintiff, defendant, provider, client)."

        # 10. Fact statement refinement
        if "key_facts" in field_path and ".statement" in field_path:
            return "Make factual statements precise and directly supported by evidence. Avoid vague or overly broad language."

        # 11. Financial summary item added
        if "financial_summary" in field_path and self._is_addition(original, edited):
            return "Always include monetary amounts mentioned in the evidence in the financial_summary section with descriptions and citations."

        # 12. Document summary refinement
        if "document_summary" in field_path:
            return "Provide a concise 1-2 sentence summary of what the document IS, based strictly on the evidence. Do not infer document type."

        # Fallback: try LLM generalization for complex cases
        llm_rule = self._llm_generalize(field_path, original, edited)
        if llm_rule:
            return llm_rule

        # Ultimate fallback: describe the field that was edited
        field_name = field_path.split(".")[-1] if "." in field_path else field_path.split("[")[0]
        return f"When generating '{field_name}', use the exact value from the evidence. Do not modify or paraphrase."

    def _is_removal(self, original: str, edited: str) -> bool:
        """Check if original had content and edited removed it."""
        orig_val = original.strip().strip('"')
        edit_val = edited.strip().strip('"')
        return (
            len(orig_val) > 10
            and (edit_val in ("", "null", "[]", "{}") or len(edit_val) < 3)
        )

    def _is_addition(self, original: str, edited: str) -> bool:
        """Check if edited added content where original was empty."""
        orig_val = original.strip().strip('"')
        edit_val = edited.strip().strip('"')
        return (
            orig_val in ("", "null", "[]", "{}")
            and len(edit_val) > 10
        )

    def _generalize_removal(self, field_path: str, original: str) -> str:
        """Generalize a removal edit."""
        if "claims" in field_path:
            return "Only include claims that are explicitly supported by evidence. Do not infer claims or include unsupported allegations."
        if "parties" in field_path:
            return "Remove parties that are not substantiated by the evidence. Include only entities clearly identified as parties in the document."
        if "key_facts" in field_path:
            return "Do not include facts without supporting evidence citations. Every fact must be traceable to a specific evidence passage."
        if "dates" in field_path:
            return "Do not include dates that are not explicitly mentioned in the evidence. Remove inferred or assumed dates."
        if "financial_summary" in field_path:
            return "Only include monetary amounts that are explicitly stated in the evidence. Do not estimate or calculate amounts."
        return "Do not generate content without strong supporting evidence. Remove unsupported items."

    def _is_party_filter(self, original: str, edited: str) -> bool:
        """Check if parties list shrank and removed items contain titles."""
        try:
            if original.startswith("[") and edited.startswith("["):
                orig_list = json.loads(original)
                edit_list = json.loads(edited)
                if not isinstance(orig_list, list) or not isinstance(edit_list, list):
                    return False
                if len(edit_list) >= len(orig_list):
                    return False
                removed = [item for item in orig_list if item not in edit_list]
            elif edited.strip().strip('"') in ("", "null", "[]", "{}"):
                removed = [json.loads(original)] if original.startswith("{") else []
            else:
                return False

            titles = ["CEO", "CFO", "CTO", "COO", "President", "Attorney", "Counsel",
                     "General Counsel", "Partner", "Managing Director"]
            for item in removed:
                name = item.get("name", "") if isinstance(item, dict) else str(item)
                if any(title in name for title in titles):
                    return True
            return False
        except (json.JSONDecodeError, TypeError):
            return False

    def _is_evidence_correction(self, original: str, edited: str) -> bool:
        """Check if chunk_ids in supporting_evidence were changed."""
        chunk_pattern = r"[a-zA-Z0-9_]+_p\d+_c\d+"
        orig_chunks = set(re.findall(chunk_pattern, original))
        edit_chunks = set(re.findall(chunk_pattern, edited))
        return bool(orig_chunks or edit_chunks) and orig_chunks != edit_chunks

    def _is_date_correction(self, original: str, edited: str) -> bool:
        """Check if a date value was corrected."""
        date_patterns = [
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
            r"\b\d{1,2}/\d{1,2}/\d{4}\b",
            r"\b\d{4}-\d{2}-\d{2}\b",
        ]
        orig_has_date = any(re.search(p, original) for p in date_patterns)
        edit_has_date = any(re.search(p, edited) for p in date_patterns)
        return orig_has_date and edit_has_date and original != edited

    def _is_amount_correction(self, original: str, edited: str) -> bool:
        """Check if a monetary amount was corrected."""
        amount_pattern = r"\$[\d,]+(?:\.\d{2})?"
        orig_has_amount = bool(re.search(amount_pattern, original))
        edit_has_amount = bool(re.search(amount_pattern, edited))
        return orig_has_amount and edit_has_amount and original != edited

    def _is_officer_addition(self, original: str, edited: str) -> bool:
        """Check if individual names were added to parties."""
        try:
            orig_list = json.loads(original) if original.startswith("[") else []
            edit_list = json.loads(edited) if edited.startswith("[") else []
            if not isinstance(orig_list, list) or not isinstance(edit_list, list):
                return False
            if len(edit_list) <= len(orig_list):
                return False
            added = [item for item in edit_list if item not in orig_list]
            for item in added:
                name = item.get("name", "") if isinstance(item, dict) else str(item)
                if re.match(r"^[A-Z][a-z]+\s+[A-Z][a-z]+$", name):
                    return True
            return False
        except (json.JSONDecodeError, TypeError):
            return False

    def _classify_rule_type(self, original: str, edited: str) -> str:
        """Classify the type of edit."""
        if self._is_removal(original, edited):
            return "removal"
        if self._is_addition(original, edited):
            return "addition"
        if self._is_evidence_correction(original, edited):
            return "evidence_fix"
        if self._is_date_correction(original, edited) or self._is_amount_correction(original, edited):
            return "correction"
        return "modification"

    def _is_valid_rule(self, rule: str) -> bool:
        """Validate that a rule is actionable and not too specific."""
        if not rule or len(rule) < 20 or len(rule) > 300:
            return False
        if re.search(r"tmp[a-z0-9]+\.(?:pdf|doc)", rule, re.IGNORECASE):
            return False
        if re.search(r"_p\d+_c\d+", rule):
            return False
        if rule.startswith("{") or rule.startswith("["):
            return False
        return True

    # ──────────────────────────────
    # LLM Fallback Generalization
    # ──────────────────────────────

    def _llm_generalize(self, field_path: str, original: str, edited: str) -> str:
        """Use a small LLM to generalize complex edits."""
        try:
            from groq import Groq

            api_key = os.environ.get("GROQ_API_KEY")
            if not api_key:
                return ""

            client = Groq(api_key=api_key)
            prompt = f"""An operator edited a legal document draft.

Field: {field_path}
Original: {original[:200]}
Edited: {edited[:200]}

State the general principle behind this edit in one concise sentence (max 20 words).
Focus on what the system should do differently in future drafts.
Example: "Do not include officer names in the parties list."

Principle:"""

            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=60,
            )
            principle = response.choices[0].message.content.strip().strip('"').strip("'")
            principle = re.sub(r"^(Principle:|Rule:|The principle is:?\s*)", "", principle, flags=re.IGNORECASE)
            return principle
        except Exception:
            return ""

    # ──────────────────────────────
    # Deep Diff
    # ──────────────────────────────

    def _deep_diff(
        self, original: Any, edited: Any, path: str = ""
    ) -> List[Tuple[str, str, str]]:
        """Recursively find differences between two structures."""
        diffs: List[Tuple[str, str, str]] = []

        if isinstance(original, dict) and isinstance(edited, dict):
            all_keys = set(original.keys()) | set(edited.keys())
            for key in sorted(all_keys):
                current_path = f"{path}.{key}" if path else key
                diffs.extend(
                    self._deep_diff(original.get(key), edited.get(key), current_path)
                )
        elif isinstance(original, list) and isinstance(edited, list):
            max_len = max(len(original), len(edited))
            for i in range(max_len):
                current_path = f"{path}[{i}]"
                if i < len(original) and i < len(edited):
                    diffs.extend(
                        self._deep_diff(original[i], edited[i], current_path)
                    )
                elif i < len(original):
                    diffs.append(
                        (current_path, json.dumps(original[i], default=str), "")
                    )
                else:
                    diffs.append(
                        (current_path, "", json.dumps(edited[i], default=str))
                    )
        else:
            if original != edited:
                diffs.append(
                    (
                        path,
                        json.dumps(original, default=str) if original is not None else "null",
                        json.dumps(edited, default=str) if edited is not None else "null",
                    )
                )

        return diffs

    def _safe_parse(self, value: str) -> Any:
        """Safely parse a JSON string."""
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
