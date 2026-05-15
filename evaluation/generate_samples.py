"""Generate synthetic legal documents for testing the document processor."""

from pathlib import Path
import fitz  # pymupdf
from PIL import Image, ImageDraw, ImageFont


SAMPLE_CONTRACT = """SERVICE AGREEMENT

This Service Agreement ("Agreement") is entered into as of March 15, 2024,
by and between:

ACME INDUSTRIES LLC, a Delaware limited liability company ("Provider")
and
SMITH VENTURES INC., a California corporation ("Client")

Case No. PSL-2024-0042

1. SERVICES. Provider agrees to deliver consulting services related to
   software development for a total fee of $125,000.

2. TERM. The term of this Agreement shall commence on April 1, 2024 and
   continue through March 31, 2025.

3. LIABILITY. Provider's liability shall be limited to the amount paid
   by Client under this Agreement. Provider shall not be liable for
   indirect, incidental, or consequential damages exceeding $50,000.

4. TERMINATION. Either party may terminate this Agreement with 30 days
   written notice. Upon termination, Client shall pay for all services
   rendered through the termination date.

5. GOVERNING LAW. This Agreement shall be governed by the laws of the
   State of Delaware.

IN WITNESS WHEREOF, the parties have executed this Agreement as of the
Effective Date.

/s/ John Doe                    /s/ Jane Smith
John Doe, CEO                   Jane Smith, CFO
ACME INDUSTRIES LLC             SMITH VENTURES INC.
"""

SAMPLE_PLEADING = """IN THE SUPERIOR COURT OF THE STATE OF DELAWARE

JAMES RICHARDSON,                    )
                                     )
    Plaintiff,                       )
                                     )
    v.                               )    Case No. PSL-2024-0089
                                     )
ATLANTIC CONSTRUCTION CORP.,         )
                                     )
    Defendant.                       )
_____________________________________)

PLAINTIFF'S COMPLAINT FOR BREACH OF CONTRACT

COMES NOW the Plaintiff, James Richardson, by and through counsel, and
for his Complaint against Defendant, Atlantic Construction Corp., states
as follows:

PARTIES

1. Plaintiff James Richardson is an individual residing at 123 Main
   Street, Wilmington, Delaware.

2. Defendant Atlantic Construction Corp. is a Delaware corporation with
   its principal place of business at 456 Commerce Blvd, Newark, Delaware.

FACTUAL ALLEGATIONS

3. On or about January 10, 2024, Plaintiff and Defendant entered into a
   written Construction Contract (the "Contract") for renovation of
   Plaintiff's residential property.

4. The total contract price was $250,000, payable in installments.

5. On February 15, 2024, Plaintiff paid the initial deposit of $75,000.

6. Defendant failed to commence work by the agreed start date of
   March 1, 2024.

7. Despite repeated demands, Defendant has not performed and refuses to
   return the deposit.

COUNT I - BREACH OF CONTRACT

8. Plaintiff incorporates by reference all preceding paragraphs.

9. Defendant's failure to perform constitutes a material breach of the
   Contract.

10. As a result of Defendant's breach, Plaintiff has suffered damages in
    the amount of $75,000 plus additional costs of $12,500.

WHEREFORE, Plaintiff demands judgment against Defendant in the amount of
$87,500, plus interest, costs, and attorney fees.

Respectfully submitted this 15th day of April, 2024.

/s/ Attorney Name
COUNSEL FOR PLAINTIFF
"""


def create_text_pdf(text: str, output_path: Path, title: str = "Document") -> None:
    """Create a clean text-based PDF with native text layer."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Letter size

    # Add text with proper formatting
    margin = 72
    y = 72
    line_height = 14

    for line in text.split("\n"):
        if y > 720:
            page = doc.new_page(width=612, height=792)
            y = 72
        page.insert_text((margin, y), line, fontsize=11, fontname="helv")
        y += line_height

    doc.save(str(output_path))
    doc.close()
    print(f"Created text PDF: {output_path}")


def create_scanned_pdf(text: str, output_path: Path) -> None:
    """Create a scanned-style PDF by rendering text as images."""
    lines = text.split("\n")
    lines_per_page = 45
    margin = 50
    line_height = 18
    page_width = 612
    page_height = 792

    doc = fitz.open()

    for page_start in range(0, len(lines), lines_per_page):
        page_lines = lines[page_start : page_start + lines_per_page]
        page_text = "\n".join(page_lines)

        # Render page as image
        img_height = page_height
        img = Image.new("RGB", (page_width, img_height), color="white")
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            except (OSError, IOError):
                font = ImageFont.load_default()

        y = margin
        for line in page_lines:
            draw.text((margin, y), line, fill="black", font=font)
            y += line_height

        # Add slight noise to simulate scan artifacts
        import random
        pixels = img.load()
        for _ in range(500):
            x = random.randint(0, page_width - 1)
            y = random.randint(0, img_height - 1)
            r, g, b = pixels[x, y]
            noise = random.randint(-10, 10)
            pixels[x, y] = (
                max(0, min(255, r + noise)),
                max(0, min(255, g + noise)),
                max(0, min(255, b + noise)),
            )

        # Save image to temporary bytes
        import io
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        # Add image to PDF page
        page = doc.new_page(width=page_width, height=page_height)
        rect = fitz.Rect(0, 0, page_width, page_height)
        page.insert_image(rect, stream=img_bytes.read())

    doc.save(str(output_path))
    doc.close()
    print(f"Created scanned PDF: {output_path}")


def main():
    output_dir = Path(__file__).parent / "synthetic_docs"
    output_dir.mkdir(exist_ok=True)

    # Clean text PDFs
    create_text_pdf(SAMPLE_CONTRACT, output_dir / "contract_clean.pdf", "Service Agreement")
    create_text_pdf(SAMPLE_PLEADING, output_dir / "pleading_clean.pdf", "Complaint")

    # Scanned/image PDFs (tests OCR fallback)
    create_scanned_pdf(SAMPLE_CONTRACT, output_dir / "contract_scanned.pdf")
    create_scanned_pdf(SAMPLE_PLEADING, output_dir / "pleading_scanned.pdf")

    print(f"\nGenerated {len(list(output_dir.glob('*.pdf')))} synthetic PDFs in {output_dir}")


if __name__ == "__main__":
    main()
