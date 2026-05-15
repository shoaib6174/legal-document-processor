import re
from pathlib import Path
from typing import List, Tuple

import fitz
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

from .models import ProcessedDocument, TextChunk, ExtractedEntity


class DocumentProcessor:
    """Extract text and structured entities from PDFs and images."""

    def __init__(self):
        # Regex patterns for structured extraction
        date_numeric = r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}"
        date_written = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}"
        self.date_pattern = re.compile(
            rf"\b(?:{date_numeric}|{date_written})\b"
        )
        self.amount_pattern = re.compile(r"\$[\d,]+(?:\.\d{2})?")
        _titles = r"CEO|CFO|CTO|COO|President|VP|Attorney|Counsel|The"
        _suffix = r"[Ll][Ll][Cc]|[Ii][Nn][Cc]|[Cc][Oo][Rr][Pp]|[Ll][Tt][Dd]|[Ll][Ll][Pp]|[Ll]\.[Pp]|[Cc][Oo][Mm][Pp][Aa][Nn][Yy]"
        self.party_pattern = re.compile(
            rf"\b(?!({_titles})\b)[A-Z][A-Z&]*(?: +[A-Z][A-Z&]*)*? +(?:{_suffix})\b"
        )
        # Individual parties explicitly labeled: "ELENA MARTINEZ, an individual"
        # Negative lookbehind prevents matching after title prefixes like "Dr. "
        self.individual_party_pattern = re.compile(
            r"(?<!\.\s)\b([A-Z]{2,}(?:\s+[A-Z]{2,}){1,2})\s*,\s*an\s+individual\b"
        )
        self.individual_title_pattern = re.compile(
            r"\b((?:Dr\.|Mr\.|Ms\.|Mrs\.)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*,\s*an\s+individual\b",
            re.IGNORECASE,
        )
        self.case_number_pattern = re.compile(
            r"\b(?:Case\s+(?:No\.?|number)|No\.|#)\s*[:\-]?\s*(\d{1,2}:\d{2}-[a-z]{2}-\d{4,5}|[A-Z]{2,4}[-\s]?\d{2,4}[-\s]?\d{1,6})\b",
            re.IGNORECASE,
        )

        # Legal-specific entity patterns
        # Case citations: "Smith v. Jones, 123 F.3d 456 (9th Cir. 2024)" or "Mercer v. Omega, 2024 WL 2847567"
        self.case_citation_pattern = re.compile(
            r"\b([A-Z][a-zA-Z.]+(?:\s+[A-Z][a-zA-Z.]+)*\s+v\.\s+[A-Z][a-zA-Z.]+(?:\s+[A-Z][a-zA-Z.]+)*,\s+(?:\d+\s+[A-Z]\.\d+[a-z]?\s+\d+(?:\s*\([^)]*\d{4}\))?|\d+\s+WL\s+\d+)|(\d{4}\s+WL\s+\d+))\b"
        )
        # Statute citations: "15 U.S.C. § 1", "815 ILCS 505/1", "28 U.S.C. § 1331(a)"
        self.statute_citation_pattern = re.compile(
            r"(\d+)\s+(U\.S\.C\.|ILCS)\s+§*\s*(\d+[a-z]?(?:\([^)]*\))?)",
            re.IGNORECASE,
        )
        # Court names
        self.court_name_pattern = re.compile(
            r"\b((?:United States|U\.S\.)\s+(?:District|Circuit|Bankruptcy|Court of Appeals|Supreme)\s+Court(?:\s+(?:for\s+the\s+[A-Za-z]+\s+(?:District|Circuit)|of\s+[A-Za-z]+))?|(?:Supreme|Superior|Appellate)\s+Court\s+(?:of\s+[A-Za-z]+|of\s+the\s+State\s+of\s+[A-Za-z]+)?)\b",
            re.IGNORECASE,
        )
        # Judge names: "Hon. John Smith", "Judge Jane Doe", "The Honorable Robert Johnson"
        self.judge_name_pattern = re.compile(
            r"\b((?:The\s+)?(?:Hon\.?|Honorable|Judge|Justice)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
            re.IGNORECASE,
        )

    def process(self, file_path: Path, source_doc: str | None = None) -> ProcessedDocument:
        """Process a document and return structured output."""
        file_path = Path(file_path)
        suffix = file_path.suffix.lower()
        doc_name = source_doc or file_path.name

        if suffix == ".pdf":
            raw_text, chunks = self._process_pdf(file_path, doc_name)
        elif suffix in (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"):
            raw_text, chunks = self._process_image(file_path, doc_name)
        else:
            # Fallback: try to read as text
            raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
            chunks = self._chunk_text(raw_text, doc_name, 1, 1.0)

        entities = self._extract_entities(raw_text, chunks)

        return ProcessedDocument(
            source_path=str(file_path),
            raw_text=raw_text,
            chunks=chunks,
            entities=entities,
        )

    def _process_pdf(self, file_path: Path, source_doc: str) -> Tuple[str, List[TextChunk]]:
        """Extract text from PDF. Uses native text if available, OCR fallback for scans."""
        doc = fitz.open(file_path)
        all_text_parts = []
        chunks = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()

            # Heuristic: if page has substantial native text, use it
            if text.strip() and len(text.strip()) > 50:
                all_text_parts.append(text)
                page_chunks = self._chunk_text(
                    text,
                    source_doc=source_doc,
                    page_num=page_num + 1,
                    confidence=1.0,
                )
                chunks.extend(page_chunks)
            else:
                # Scanned page — render to image and OCR
                pix = page.get_pixmap(dpi=300)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_text = self._ocr_image(img)
                confidence = self._estimate_ocr_confidence(img)
                all_text_parts.append(ocr_text)
                page_chunks = self._chunk_text(
                    ocr_text,
                    source_doc=source_doc,
                    page_num=page_num + 1,
                    confidence=confidence,
                )
                chunks.extend(page_chunks)

        doc.close()
        return "\n".join(all_text_parts), chunks

    def _process_image(self, file_path: Path, source_doc: str) -> Tuple[str, List[TextChunk]]:
        """Process a single image file with OCR."""
        img = Image.open(file_path)
        ocr_text = self._ocr_image(img)
        confidence = self._estimate_ocr_confidence(img)
        chunks = self._chunk_text(
            ocr_text,
            source_doc=source_doc,
            page_num=1,
            confidence=confidence,
        )
        return ocr_text, chunks

    def _ocr_image(self, img: Image.Image) -> str:
        """Run OCR with preprocessing to improve accuracy on messy scans."""
        # Deskew if needed
        img = self._deskew_image(img)

        # Convert to grayscale
        if img.mode != "L":
            img = img.convert("L")

        # Boost contrast — helps with faded scans
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)

        # Adaptive thresholding for better binarization on uneven lighting
        img = img.filter(ImageFilter.MedianFilter(size=3))

        return pytesseract.image_to_string(img)

    def _deskew_image(self, img: Image.Image) -> Image.Image:
        """Detect and correct skew angle using Tesseract OSD."""
        try:
            osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
            angle = osd.get("rotate", 0)
            if angle and angle != 0:
                # PIL rotates counter-clockwise, so negate the angle
                img = img.rotate(-angle, expand=True, fillcolor="white")
        except Exception:
            # OSD can fail on small images or already-clean text — safe to ignore
            pass
        return img

    def _estimate_ocr_confidence(self, img: Image.Image) -> float:
        """Estimate OCR confidence from tesseract word-level confidence data."""
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data["conf"] if int(c) > 0]
        if confidences:
            avg_conf = sum(confidences) / len(confidences) / 100.0
            return round(min(avg_conf, 1.0), 2)
        return 0.5

    def _chunk_text(
        self,
        text: str,
        source_doc: str,
        page_num: int,
        confidence: float,
        chunk_size: int = 300,
        overlap: int = 50,
    ) -> List[TextChunk]:
        """Split text into overlapping sentence-aware chunks for retrieval.

        Sentences are never split across chunks — this ensures each chunk
        contains complete thoughts, which dramatically improves retrieval
        quality and downstream generation coherence.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return []

        chunks = []
        idx = 0
        current_sentences = []
        current_word_count = 0
        overlap_sentences = []  # sentences to carry over for overlap
        overlap_word_count = 0

        for sentence in sentences:
            sentence_word_count = len(sentence.split())

            # If adding this sentence would exceed chunk_size, finalize current chunk
            if current_word_count + sentence_word_count > chunk_size and current_sentences:
                chunk_text = " ".join(current_sentences)
                chunks.append(
                    TextChunk(
                        chunk_id=f"{source_doc}_p{page_num}_c{idx}",
                        text=chunk_text,
                        source_doc=source_doc,
                        page_num=page_num,
                        confidence_score=confidence,
                    )
                )
                idx += 1

                # Build overlap: carry sentences from the end that fit within overlap word budget
                overlap_sentences = []
                overlap_word_count = 0
                for s in reversed(current_sentences):
                    sw = len(s.split())
                    if overlap_word_count + sw <= overlap:
                        overlap_sentences.insert(0, s)
                        overlap_word_count += sw
                    else:
                        break

                current_sentences = list(overlap_sentences) + [sentence]
                current_word_count = overlap_word_count + sentence_word_count
            else:
                current_sentences.append(sentence)
                current_word_count += sentence_word_count

        # Don't forget the last chunk
        if current_sentences:
            chunk_text = " ".join(current_sentences)
            chunks.append(
                TextChunk(
                    chunk_id=f"{source_doc}_p{page_num}_c{idx}",
                    text=chunk_text,
                    source_doc=source_doc,
                    page_num=page_num,
                    confidence_score=confidence,
                )
            )

        return chunks

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences using regex. Handles common abbreviations."""
        # Protect common abbreviations to avoid false sentence splits
        protected = text
        abbreviations = {
            r"Mr\.": "{{MR}}",
            r"Mrs\.": "{{MRS}}",
            r"Ms\.": "{{MS}}",
            r"Dr\.": "{{DR}}",
            r"Prof\.": "{{PROF}}",
            r"Jr\.": "{{JR}}",
            r"Sr\.": "{{SR}}",
            r"Inc\.": "{{INC}}",
            r"Corp\.": "{{CORP}}",
            r"LLC\.": "{{LLC}}",
            r"Ltd\.": "{{LTD}}",
            r"U\.S\.C\.": "{{USC}}",
            r"U\.S\.": "{{US}}",
            r"v\.": "{{V}}",
            r"Hon\.": "{{HON}}",
            r"No\.": "{{NO}}",
            r"et\s+al\.": "{{ETAL}}",
            r"e\.g\.": "{{EG}}",
            r"i\.e\.": "{{IE}}",
            r"etc\.": "{{ETC}}",
            r"vs\.": "{{VS}}",
            r"Fig\.": "{{FIG}}",
            r"pp\.": "{{PP}}",
            r"vol\.": "{{VOL}}",
            r"Vol\.": "{{VOL2}}",
        }
        for abbrev, placeholder in abbreviations.items():
            protected = re.sub(abbrev, placeholder, protected)

        # Split on sentence boundaries: period, question mark, exclamation followed by space or end
        sentence_pattern = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'])')
        raw_sentences = sentence_pattern.split(protected)

        # Restore abbreviations and clean up
        reverse_map = {v: k.replace("\\", "").replace("?", ".") for k, v in abbreviations.items()}
        # Fix specific replacements
        reverse_map = {
            "{{MR}}": "Mr.",
            "{{MRS}}": "Mrs.",
            "{{MS}}": "Ms.",
            "{{DR}}": "Dr.",
            "{{PROF}}": "Prof.",
            "{{JR}}": "Jr.",
            "{{SR}}": "Sr.",
            "{{INC}}": "Inc.",
            "{{CORP}}": "Corp.",
            "{{LLC}}": "LLC.",
            "{{LTD}}": "Ltd.",
            "{{USC}}": "U.S.C.",
            "{{US}}": "U.S.",
            "{{V}}": "v.",
            "{{HON}}": "Hon.",
            "{{NO}}": "No.",
            "{{ETAL}}": "et al.",
            "{{EG}}": "e.g.",
            "{{IE}}": "i.e.",
            "{{ETC}}": "etc.",
            "{{VS}}": "vs.",
            "{{FIG}}": "Fig.",
            "{{PP}}": "pp.",
            "{{VOL}}": "vol.",
            "{{VOL2}}": "Vol.",
        }

        sentences = []
        for s in raw_sentences:
            s = s.strip()
            for placeholder, abbrev in reverse_map.items():
                s = s.replace(placeholder, abbrev)
            if s:
                sentences.append(s)

        return sentences

    def _extract_entities(self, raw_text: str, chunks: List[TextChunk]) -> List[ExtractedEntity]:
        """Extract dates, amounts, parties, case numbers, and legal entities from raw text with positions."""
        entities = []
        seen = set()

        # Dates
        for match in self.date_pattern.finditer(raw_text):
            val = match.group()
            key = ("date", val)
            if key not in seen:
                seen.add(key)
                chunk_id = self._find_chunk_for_offset(match.start(), chunks)
                entities.append(
                    ExtractedEntity(
                        type="date", value=val, source_chunk_id=chunk_id,
                        start=match.start(), end=match.end()
                    )
                )

        # Dollar amounts
        for match in self.amount_pattern.finditer(raw_text):
            val = match.group()
            key = ("amount", val)
            if key not in seen:
                seen.add(key)
                chunk_id = self._find_chunk_for_offset(match.start(), chunks)
                entities.append(
                    ExtractedEntity(
                        type="amount", value=val, source_chunk_id=chunk_id,
                        start=match.start(), end=match.end()
                    )
                )

        # Party names (ALL CAPS + company suffix)
        for match in self.party_pattern.finditer(raw_text):
            val = match.group()
            key = ("party", val)
            if key not in seen:
                seen.add(key)
                chunk_id = self._find_chunk_for_offset(match.start(), chunks)
                entities.append(
                    ExtractedEntity(
                        type="party", value=val, source_chunk_id=chunk_id,
                        start=match.start(), end=match.end()
                    )
                )

        # Individual parties explicitly labeled (e.g., "ELENA MARTINEZ, an individual")
        for match in self.individual_party_pattern.finditer(raw_text):
            val = match.group(1)
            key = ("party", val)
            if key not in seen:
                seen.add(key)
                chunk_id = self._find_chunk_for_offset(match.start(), chunks)
                entities.append(
                    ExtractedEntity(
                        type="party", value=val, source_chunk_id=chunk_id,
                        start=match.start(), end=match.end()
                    )
                )

        # Individual parties with title prefix (e.g., "DR. AMANDA PARK, an individual")
        for match in self.individual_title_pattern.finditer(raw_text):
            val = match.group(1)
            key = ("party", val)
            if key not in seen:
                seen.add(key)
                chunk_id = self._find_chunk_for_offset(match.start(), chunks)
                entities.append(
                    ExtractedEntity(
                        type="party", value=val, source_chunk_id=chunk_id,
                        start=match.start(), end=match.end()
                    )
                )

        # Case numbers
        for match in self.case_number_pattern.finditer(raw_text):
            val = match.group(1)
            key = ("case_number", val)
            if key not in seen:
                seen.add(key)
                chunk_id = self._find_chunk_for_offset(match.start(), chunks)
                entities.append(
                    ExtractedEntity(
                        type="case_number",
                        value=val,
                        source_chunk_id=chunk_id,
                        start=match.start(), end=match.end()
                    )
                )

        # Case citations (e.g., "Smith v. Jones, 123 F.3d 456")
        for match in self.case_citation_pattern.finditer(raw_text):
            val = match.group(1) or match.group(2)
            if not val:
                continue
            key = ("case_citation", val)
            if key not in seen:
                seen.add(key)
                chunk_id = self._find_chunk_for_offset(match.start(), chunks)
                entities.append(
                    ExtractedEntity(
                        type="case_citation", value=val, source_chunk_id=chunk_id,
                        start=match.start(), end=match.end()
                    )
                )

        # Statute citations (e.g., "15 U.S.C. § 1", "815 ILCS 505/1")
        for match in self.statute_citation_pattern.finditer(raw_text):
            code_type = match.group(2)
            val = f"{match.group(1)} {code_type} § {match.group(3)}"
            key = ("statute_citation", val)
            if key not in seen:
                seen.add(key)
                chunk_id = self._find_chunk_for_offset(match.start(), chunks)
                entities.append(
                    ExtractedEntity(
                        type="statute_citation", value=val, source_chunk_id=chunk_id,
                        start=match.start(), end=match.end()
                    )
                )

        # Court names
        for match in self.court_name_pattern.finditer(raw_text):
            val = match.group(1)
            key = ("court_name", val)
            if key not in seen:
                seen.add(key)
                chunk_id = self._find_chunk_for_offset(match.start(), chunks)
                entities.append(
                    ExtractedEntity(
                        type="court_name", value=val, source_chunk_id=chunk_id,
                        start=match.start(), end=match.end()
                    )
                )

        # Judge names
        for match in self.judge_name_pattern.finditer(raw_text):
            val = match.group(1)
            key = ("judge_name", val)
            if key not in seen:
                seen.add(key)
                chunk_id = self._find_chunk_for_offset(match.start(), chunks)
                entities.append(
                    ExtractedEntity(
                        type="judge_name", value=val, source_chunk_id=chunk_id,
                        start=match.start(), end=match.end()
                    )
                )

        return entities

    def _find_chunk_for_offset(self, offset: int, chunks: List[TextChunk]) -> str:
        """Find which chunk contains the given character offset in raw_text."""
        pos = 0
        for chunk in chunks:
            chunk_len = len(chunk.text)
            if pos <= offset < pos + chunk_len:
                return chunk.chunk_id
            # account for overlap: chunks share content, so advance by (chunk_len - overlap_chars)
            # We estimate overlap chars as proportional to overlap words
            overlap_chars = min(chunk_len // 2, 200)
            pos += chunk_len - overlap_chars
        return chunks[0].chunk_id if chunks else "unknown"

    def render_pages(self, file_path: Path, output_dir: Path) -> List[str]:
        """Render each PDF page to a PNG image. Returns list of relative filenames."""
        doc = fitz.open(file_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        rendered = []
        for i in range(len(doc)):
            page = doc[i]
            pix = page.get_pixmap(dpi=150)
            img_path = output_dir / f"page_{i + 1}.png"
            pix.save(str(img_path))
            rendered.append(f"page_{i + 1}.png")

        doc.close()
        return rendered
