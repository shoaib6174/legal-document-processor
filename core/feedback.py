import json
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
        conn.commit()
        conn.close()

    def capture_edit(self, original: dict, edited: dict) -> None:
        """Capture differences between original and edited drafts."""
        diffs = self._deep_diff(original, edited)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for field_path, orig_val, edit_val in diffs:
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
                    SET frequency = frequency + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (row[0],),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO corrections (field_path, original_value, edited_value)
                    VALUES (?, ?, ?)
                    """,
                    (field_path, orig_val, edit_val),
                )

        conn.commit()
        conn.close()

    def get_rules(self, limit: int = 3) -> List[str]:
        """Get top correction rules by frequency."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT field_path, original_value, edited_value, frequency
            FROM corrections
            ORDER BY frequency DESC, updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()

        rules = []
        for field_path, orig_val, edit_val, freq in rows:
            rule = (
                f"When generating '{field_path}', prefer '{edit_val}' "
                f"over '{orig_val}'. (seen {freq} time{'s' if freq > 1 else ''})"
            )
            rules.append(rule)
        return rules

    def get_stats(self) -> dict:
        """Return feedback store statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(frequency), 0) FROM corrections")
        count, total_freq = cursor.fetchone()
        conn.close()
        return {"rule_count": count, "total_frequency": total_freq}

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
