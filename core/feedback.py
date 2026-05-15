import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, List, Tuple


class FeedbackEngine:
    """Capture operator edits and extract reusable correction rules."""

    def __init__(self, db_path: str = "./data/feedback.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

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
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Migrate: add new columns if they don't exist
        cursor.execute("PRAGMA table_info(corrections)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        new_cols = {
            "generalized_rule": "TEXT",
            "rule_type": "TEXT",
            "success_count": "INTEGER DEFAULT 0",
            "failure_count": "INTEGER DEFAULT 0",
            "last_applied": "TIMESTAMP",
        }
        for col, dtype in new_cols.items():
            if col not in existing_cols:
                cursor.execute(f"ALTER TABLE corrections ADD COLUMN {col} {dtype}")
        conn.commit()
        conn.close()

    def capture_edit(self, original: dict, edited: dict) -> None:
        """Capture differences between original and edited drafts."""
        diffs = self._deep_diff(original, edited)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for field_path, orig_val, edit_val in diffs:
            generalized = self._generalize_rule(field_path, orig_val, edit_val)
            rule_type = self._classify_rule_type(orig_val, edit_val)

            # Check if this correction already exists
            cursor.execute(
                """
                SELECT id, frequency FROM corrections
                WHERE field_path = ? AND original_value = ? AND edited_value = ?
                """,
                (field_path, orig_val, edit_val),
            )
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    """
                    UPDATE corrections
                    SET frequency = frequency + 1, updated_at = CURRENT_TIMESTAMP,
                        generalized_rule = COALESCE(?, generalized_rule),
                        rule_type = COALESCE(?, rule_type)
                    WHERE id = ?
                    """,
                    (generalized, rule_type, row[0]),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO corrections (field_path, original_value, edited_value, generalized_rule, rule_type)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (field_path, orig_val, edit_val, generalized, rule_type),
                )

        conn.commit()
        conn.close()

    def get_rules(self, limit: int = 3) -> List[str]:
        """Get top correction rules by weighted score (frequency * recency)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT generalized_rule, MAX(frequency) as freq,
                   MAX(success_count) as succ, MAX(failure_count) as fail,
                   MAX(
                       frequency *
                       (1.0 + COALESCE(success_count, 0)) /
                       (1.0 + COALESCE(success_count, 0) + COALESCE(failure_count, 0)) *
                       EXP(-(JULIANDAY('now') - JULIANDAY(updated_at)) / 30.0)
                   ) as score
            FROM corrections
            WHERE generalized_rule IS NOT NULL AND generalized_rule != ''
            GROUP BY generalized_rule
            ORDER BY score DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()

        rules = []
        for generalized, freq, success, failure, score in rows:
            if generalized and self._is_valid_rule(generalized):
                rules.append(generalized)
        return rules

    def get_stats(self) -> dict:
        """Return feedback store statistics."""
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
        return {
            "rule_count": count,
            "total_frequency": total_freq,
            "unique_generalized_rules": unique_rules,
            "total_success": total_success,
            "total_failure": total_failure,
        }

    def score_rule(self, rule_text: str, was_effective: bool) -> None:
        """Update rule score based on whether applying it reduced future edits."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if was_effective:
            cursor.execute(
                """
                UPDATE corrections
                SET success_count = success_count + 1, last_applied = CURRENT_TIMESTAMP
                WHERE generalized_rule = ?
                """,
                (rule_text,),
            )
        else:
            cursor.execute(
                """
                UPDATE corrections
                SET failure_count = failure_count + 1, last_applied = CURRENT_TIMESTAMP
                WHERE generalized_rule = ?
                """,
                (rule_text,),
            )
        conn.commit()
        conn.close()

    # ──────────────────────────────
    # Heuristic Generalizers
    # ──────────────────────────────

    def _generalize_rule(self, field_path: str, original: str, edited: str) -> str:
        """Transform a literal diff into a reusable principle."""
        orig_parsed = self._safe_parse(original)
        edit_parsed = self._safe_parse(edited)

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
        return "Do not generate content without strong supporting evidence. Remove unsupported items."

    def _is_party_filter(self, original: str, edited: str) -> bool:
        """Check if parties list shrank and removed items contain titles."""
        try:
            # Case 1: full list diff (both are lists)
            if original.startswith("[") and edited.startswith("["):
                orig_list = json.loads(original)
                edit_list = json.loads(edited)
                if not isinstance(orig_list, list) or not isinstance(edit_list, list):
                    return False
                if len(edit_list) >= len(orig_list):
                    return False
                removed = [item for item in orig_list if item not in edit_list]
            # Case 2: single item removed from list (edited is empty/null)
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
                # Check if name looks like a person (First Last, no corporate suffix)
                if re.match(r"^[A-Z][a-z]+\s+[A-Z][a-z]+$", name):
                    return True
            return False
        except (json.JSONDecodeError, TypeError):
            return False

    def _classify_rule_type(self, original: str, edited: str) -> str:
        """Classify the type of edit."""
        if self._is_removal(original, edited):
            return "removal"
        if self._is_removal(edited, original):
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
        # Reject rules containing document-specific temp filenames
        if re.search(r"tmp[a-z0-9]+\.(?:pdf|doc)", rule, re.IGNORECASE):
            return False
        # Reject rules with specific chunk_ids
        if re.search(r"_p\d+_c\d+", rule):
            return False
        # Reject rules that are just JSON blobs
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
            # Clean up common prefixes
            principle = re.sub(r"^(Principle:|Rule:|The principle is:?\s*)", "", principle, flags=re.IGNORECASE)
            return principle
        except Exception:
            return ""

    # ──────────────────────────────
    # Deep Diff (unchanged)
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
