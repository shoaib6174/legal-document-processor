"""Generate synthetic legal documents for testing the document processor."""

import io
import math
import random
from pathlib import Path

import fitz  # pymupdf
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from document_templates import TEMPLATES


def create_text_pdf(text: str, output_path: Path, title: str = "Document") -> None:
    """Create a clean text-based PDF with native text layer."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Letter size

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


def _apply_skew(img: Image.Image, max_angle: float = 2.0) -> Image.Image:
    """Apply slight rotation to simulate skewed scan."""
    angle = random.uniform(-max_angle, max_angle)
    return img.rotate(angle, resample=Image.BICUBIC, fillcolor="white")


def _apply_blur(img: Image.Image) -> Image.Image:
    """Apply Gaussian blur to simulate out-of-focus scan."""
    if random.random() < 0.5:
        radius = random.uniform(0.3, 0.8)
        return img.filter(ImageFilter.GaussianBlur(radius=radius))
    return img


def _apply_salt_and_pepper(img: Image.Image, density: float = 0.002) -> Image.Image:
    """Add salt-and-pepper noise."""
    pixels = img.load()
    width, height = img.size
    num_noise = int(width * height * density)
    for _ in range(num_noise):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        if random.random() < 0.5:
            pixels[x, y] = (0, 0, 0)  # black (pepper)
        else:
            pixels[x, y] = (255, 255, 255)  # white (salt)
    return img


def _apply_random_noise(img: Image.Image) -> Image.Image:
    """Apply subtle random noise to simulate scanner sensor noise."""
    pixels = img.load()
    width, height = img.size
    for _ in range(800):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        r, g, b = pixels[x, y]
        noise = random.randint(-12, 12)
        pixels[x, y] = (
            max(0, min(255, r + noise)),
            max(0, min(255, g + noise)),
            max(0, min(255, b + noise)),
        )
    return img


def _add_watermark(img: Image.Image, text: str = "CONFIDENTIAL") -> Image.Image:
    """Add a diagonal watermark."""
    if random.random() < 0.7:
        overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
        except (OSError, IOError):
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        # Draw diagonally across the page
        for i in range(-2, 4):
            y_pos = i * 200 + 100
            draw.text((100, y_pos), text, font=font, fill=(200, 200, 200, 80))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img


def _add_header_footer(
    img: Image.Image, page_num: int, total_pages: int, doc_title: str = ""
) -> Image.Image:
    """Add header and footer text."""
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 9)
    except (OSError, IOError):
        font = ImageFont.load_default()

    width, height = img.size
    # Header
    header_text = doc_title if doc_title else ""
    if header_text:
        draw.text((50, 20), header_text, fill=(128, 128, 128), font=font)
    # Footer with page number
    footer_text = f"Page {page_num} of {total_pages}"
    bbox = draw.textbbox((0, 0), footer_text, font=font)
    text_width = bbox[2] - bbox[0]
    draw.text((width - 50 - text_width, height - 30), footer_text, fill=(128, 128, 128), font=font)
    return img


def create_scanned_pdf(
    text: str, output_path: Path, title: str = "Document", add_watermark: bool = True
) -> None:
    """Create a scanned-style PDF by rendering text as images with realistic degradation."""
    lines = text.split("\n")
    lines_per_page = 42
    margin = 60
    line_height = 16
    page_width = 612
    page_height = 792

    doc = fitz.open()
    total_pages = math.ceil(len(lines) / lines_per_page)

    for page_idx in range(total_pages):
        page_start = page_idx * lines_per_page
        page_lines = lines[page_start : page_start + lines_per_page]

        img = Image.new("RGB", (page_width, page_height), color="white")
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 11)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11
                )
            except (OSError, IOError):
                font = ImageFont.load_default()

        y = margin
        for line in page_lines:
            draw.text((margin, y), line, fill="black", font=font)
            y += line_height

        # Add header/footer
        img = _add_header_footer(img, page_idx + 1, total_pages, title)

        # Apply degradation effects
        img = _apply_random_noise(img)
        img = _apply_salt_and_pepper(img, density=0.0015)
        img = _apply_skew(img, max_angle=1.5)
        img = _apply_blur(img)

        if add_watermark:
            img = _add_watermark(img, random.choice(["CONFIDENTIAL", "DRAFT", " attorney -client privilege "]))

        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        page = doc.new_page(width=page_width, height=page_height)
        rect = fitz.Rect(0, 0, page_width, page_height)
        page.insert_image(rect, stream=img_bytes.read())

    doc.save(str(output_path))
    doc.close()
    print(f"Created scanned PDF: {output_path}")


def main():
    output_dir = Path(__file__).parent / "synthetic_docs"
    output_dir.mkdir(exist_ok=True)

    for name, template in TEMPLATES.items():
        # Clean text PDF
        create_text_pdf(template, output_dir / f"{name}_clean.pdf", title=name.replace("_", " ").title())
        # Scanned/image PDF with degradation
        create_scanned_pdf(template, output_dir / f"{name}_scanned.pdf", title=name.replace("_", " ").title())

    count = len(list(output_dir.glob("*.pdf")))
    print(f"\nGenerated {count} synthetic PDFs in {output_dir}")


if __name__ == "__main__":
    main()
