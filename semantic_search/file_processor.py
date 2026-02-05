"""
Multi-format file processor for PDFs, images, documents, etc.
Extracts text content for embedding.
"""
from pathlib import Path
from typing import List, Union, Optional
from PIL import Image
import io
import logging

logger = logging.getLogger(__name__)


def extract_text(file_path: str) -> Optional[str]:
    """
    Extract text from any supported file type.

    Args:
        file_path: Path to the file

    Returns:
        Extracted text content or None if extraction fails
    """
    file_path = Path(file_path)
    extension = file_path.suffix.lower()

    try:
        if extension == '.pdf':
            return extract_pdf_text(file_path)
        elif extension in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
            return extract_image_text(file_path)
        elif extension in ['.docx', '.doc']:
            return extract_docx_text(file_path)
        elif extension in ['.pptx', '.ppt']:
            return extract_pptx_text(file_path)
        elif extension in ['.xlsx', '.xls', '.csv']:
            return extract_excel_text(file_path)
        elif extension in ['.txt', '.md', '.rtf']:
            return extract_plain_text(file_path)
        else:
            logger.warning(f"Unsupported file type: {extension}")
            return None
    except Exception as e:
        logger.error(f"Failed to extract text from {file_path}: {e}")
        return None


def extract_pdf_text(file_path: Path) -> Optional[str]:
    """
    Extract text from PDF with TEXT-FIRST approach.
    Falls back to OCR for scanned documents.
    """
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(file_path)
        all_text = []

        for page in doc:
            text = page.get_text()
            if text.strip():
                all_text.append(text)

        doc.close()

        full_text = '\n'.join(all_text)

        # If we got substantial text, use it
        if len(full_text.strip()) > 100:
            logger.debug(f"Extracted {len(full_text)} chars from PDF: {file_path.name}")
            return full_text

        # Fallback to OCR for scanned PDFs
        logger.info(f"No text found in PDF, trying OCR: {file_path.name}")
        return extract_pdf_ocr(file_path)

    except Exception as e:
        logger.error(f"Failed to process PDF {file_path}: {e}")
        return None


def extract_pdf_ocr(file_path: Path) -> Optional[str]:
    """Extract text from PDF using OCR (for scanned documents)."""
    try:
        import fitz
        import pytesseract

        doc = fitz.open(file_path)
        all_text = []

        for page_num, page in enumerate(doc):
            # Render page as image
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x scale for better OCR
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # Run OCR
            text = pytesseract.image_to_string(img)
            if text.strip():
                all_text.append(text)

            # Limit to first 10 pages for performance
            if page_num >= 9:
                break

        doc.close()

        full_text = '\n'.join(all_text)
        if full_text.strip():
            logger.debug(f"OCR extracted {len(full_text)} chars from PDF: {file_path.name}")
            return full_text

        return None

    except ImportError:
        logger.warning("pytesseract not installed - OCR unavailable")
        return None
    except Exception as e:
        logger.error(f"OCR failed for {file_path}: {e}")
        return None


def extract_image_text(file_path: Path) -> Optional[str]:
    """Extract text from image using OCR."""
    try:
        import pytesseract

        image = Image.open(file_path)
        text = pytesseract.image_to_string(image)

        if text.strip():
            logger.debug(f"OCR extracted {len(text)} chars from image: {file_path.name}")
            return text

        # Return image description as fallback
        return f"Image file: {file_path.name} ({image.size[0]}x{image.size[1]} pixels)"

    except ImportError:
        logger.warning("pytesseract not installed - returning image description")
        try:
            image = Image.open(file_path)
            return f"Image file: {file_path.name} ({image.size[0]}x{image.size[1]} pixels)"
        except:
            return f"Image file: {file_path.name}"
    except Exception as e:
        logger.error(f"Failed to process image {file_path}: {e}")
        return None


def extract_docx_text(file_path: Path) -> Optional[str]:
    """Extract text from Word document."""
    try:
        from docx import Document

        doc = Document(file_path)
        text_parts = []

        # Extract from paragraphs
        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)

        # Extract from tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        text_parts.append(cell.text)

        full_text = '\n'.join(text_parts)

        if full_text.strip():
            logger.debug(f"Extracted {len(full_text)} chars from DOCX: {file_path.name}")
            return full_text

        return None

    except Exception as e:
        logger.error(f"Failed to process DOCX {file_path}: {e}")
        return None


def extract_pptx_text(file_path: Path) -> Optional[str]:
    """Extract text from PowerPoint presentation."""
    try:
        from pptx import Presentation

        prs = Presentation(file_path)
        text_parts = []

        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, 'text') and shape.text.strip():
                    text_parts.append(shape.text)

        full_text = '\n'.join(text_parts)

        if full_text.strip():
            logger.debug(f"Extracted {len(full_text)} chars from PPTX: {file_path.name}")
            return full_text

        return None

    except Exception as e:
        logger.error(f"Failed to process PPTX {file_path}: {e}")
        return None


def extract_excel_text(file_path: Path) -> Optional[str]:
    """Extract text from Excel spreadsheet."""
    try:
        extension = file_path.suffix.lower()

        if extension == '.csv':
            # Read CSV directly
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()

        from openpyxl import load_workbook

        wb = load_workbook(file_path, read_only=True, data_only=True)
        text_parts = []

        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                row_text = ' '.join([str(cell) for cell in row if cell is not None])
                if row_text.strip():
                    text_parts.append(row_text)

        wb.close()

        full_text = '\n'.join(text_parts)

        if full_text.strip():
            logger.debug(f"Extracted {len(full_text)} chars from Excel: {file_path.name}")
            return full_text

        return None

    except Exception as e:
        logger.error(f"Failed to process Excel {file_path}: {e}")
        return None


def extract_plain_text(file_path: Path) -> Optional[str]:
    """Extract text from plain text or markdown file."""
    try:
        # Try UTF-8 first
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
        except UnicodeDecodeError:
            # Fallback to latin-1
            with open(file_path, 'r', encoding='latin-1', errors='ignore') as f:
                text = f.read()

        if text.strip():
            logger.debug(f"Read {len(text)} chars from text file: {file_path.name}")
            return text

        return None

    except Exception as e:
        logger.error(f"Failed to read text file {file_path}: {e}")
        return None


def get_supported_extensions() -> List[str]:
    """Get list of supported file extensions."""
    return [
        '.pdf',
        '.png', '.jpg', '.jpeg', '.gif', '.webp',
        '.docx', '.doc',
        '.pptx', '.ppt',
        '.xlsx', '.xls', '.csv',
        '.txt', '.rtf'
        # Note: .md excluded - typically code/developer files, not user documents
    ]


def is_supported_file(file_path: Union[str, Path]) -> bool:
    """Check if file type is supported and not a system file."""
    path = Path(file_path)
    path_str = str(path).lower()

    # Skip system/thumbnail files
    skip_extensions = ['.thm', '.tmp', '.cache', '.ds_store']
    if path.suffix.lower() in skip_extensions:
        return False

    # Skip hidden files and developer/system folders
    skip_folders = [
        '/.git/', '/node_modules/', '/venv/', '/.venv/',
        '/site-packages/', '/dist-info/', '/__pycache__/',
        '/build/', '/dist/', '/.idea/', '/.vscode/',
        '/electron/dist/', '/Gnome.app/'
    ]
    if path.name.startswith('.') or any(skip in path_str for skip in skip_folders):
        return False

    return path.suffix.lower() in get_supported_extensions()


# ============ Legacy compatibility functions ============

def process_file(file_path: str, voyage_client=None) -> List[float]:
    """
    Legacy function for backward compatibility.
    Now uses extract_text + embedding engine.

    Args:
        file_path: Path to the file
        voyage_client: Ignored (uses global embedding engine)

    Returns:
        1024-dimensional embedding vector
    """
    from .voyage_embeddings import get_embedding_engine

    text = extract_text(file_path)
    if not text:
        raise ValueError(f"Could not extract text from {file_path}")

    engine = get_embedding_engine()
    return engine.embed_document(text)


def embed_text(text: str, voyage_client=None) -> List[float]:
    """
    Legacy function for backward compatibility.

    Args:
        text: Text to embed
        voyage_client: Ignored (uses global embedding engine)

    Returns:
        1024-dimensional embedding vector
    """
    from .voyage_embeddings import get_embedding_engine

    engine = get_embedding_engine()
    return engine.embed_document(text)
