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
        self.case_number_pattern = re.compile(
            r"\b(?:Case|No\.|#)\s*[:\-]?\s*([A-Z]{2,4}[-\s]?\d{2,4}[-\s]?\d{1,6})\b",
            re.IGNORECASE,
        )

    def process(self, file_path: Path) -> ProcessedDocument:
        """Process a document and return structured output."""
        file_path = Path(file_path)
        suffix = file_path.suffix.lower()

        if suffix == ".pdf":
            raw_text, chunks = self._process_pdf(file_path)
        elif suffix in (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"):
            raw_text, chunks = self._process_image(file_path)
        else:
            # Fallback: try to read as text
            raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
            chunks = self._chunk_text(raw_text, file_path.name, 1, 1.0)

        entities = self._extract_entities(raw_text, chunks)

        return ProcessedDocument(
            source_path=str(file_path),
            raw_text=raw_text,
            chunks=chunks,
            entities=entities,
        )

    def _process_pdf(self, file_path: Path) -> Tuple[str, List[TextChunk]]:
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
                    source_doc=file_path.name,
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
                    source_doc=file_path.name,
                    page_num=page_num + 1,
                    confidence=confidence,
                )
                chunks.extend(page_chunks)

        doc.close()
        return "\n".join(all_text_parts), chunks

    def _process_image(self, file_path: Path) -> Tuple[str, List[TextChunk]]:
        """Process a single image file with OCR."""
        img = Image.open(file_path)
        ocr_text = self._ocr_image(img)
        confidence = self._estimate_ocr_confidence(img)
        chunks = self._chunk_text(
            ocr_text,
            source_doc=file_path.name,
            page_num=1,
            confidence=confidence,
        )
        return ocr_text, chunks

    def _ocr_image(self, img: Image.Image) -> str:
        """Run OCR with basic preprocessing to improve accuracy."""
        # Convert to grayscale
        if img.mode != "L":
            img = img.convert("L")
        # Boost contrast — helps with faded scans
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        # Mild denoise
        img = img.filter(ImageFilter.MedianFilter(size=3))
        return pytesseract.image_to_string(img)

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
        """Split text into overlapping word chunks for retrieval."""
        words = text.split()
        if not words:
            return []

        chunks = []
        start = 0
        idx = 0

        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunk_text = " ".join(words[start:end])
            chunks.append(
                TextChunk(
                    chunk_id=f"{source_doc}_p{page_num}_c{idx}",
                    text=chunk_text,
                    source_doc=source_doc,
                    page_num=page_num,
                    confidence_score=confidence,
                )
            )
            next_start = end - overlap
            if next_start <= start:  # No forward progress — we're done
                break
            start = next_start
            idx += 1

        return chunks

    def _extract_entities(self, raw_text: str, chunks: List[TextChunk]) -> List[ExtractedEntity]:
        """Extract dates, amounts, parties, and case numbers from raw text with positions."""
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

        return entities

    def _find_chunk_for_offset(self, offset: int, chunks: List[TextChunk]) -> str:
        """Find which chunk contains the given character offset in raw_text."""
        pos = 0
        for chunk in chunks:
            chunk_len = len(chunk.text)
            if pos <= offset < pos + chunk_len:
                return chunk.chunk_id
            pos += chunk_len - 50  # account for overlap
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
