# apps/backend/src/app/core/temp_docs/extract.py
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

def extract_text_from_bytes(
    file_bytes: bytes, 
    filename: str,
    max_pages: int = 50,
    max_chars: int = 1_000_000
) -> str:
    """
    Simple text extractor with limits.
    Supports .txt, .pdf, .docx.
    """
    text = ""
    
    # TXT
    if filename.lower().endswith(".txt"):
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = file_bytes.decode("latin-1")
            except Exception as e:
                logger.warning(f"Failed to decode text file {filename}: {e}")
                return ""
    
    # PDF
    elif filename.lower().endswith(".pdf"):
        try:
            import io
            from pypdf import PdfReader
            
            reader = PdfReader(io.BytesIO(file_bytes))
            
            # Limit Pages
            if len(reader.pages) > max_pages:
                logger.warning(f"PDF {filename} exceeds max pages ({len(reader.pages)} > {max_pages})")
                # Truncate or Reject? Truncate for MVP.
                pages_to_read = reader.pages[:max_pages]
            else:
                pages_to_read = reader.pages
                
            extracted = []
            for page in pages_to_read:
                extracted.append(page.extract_text() or "")
            text = "\n".join(extracted)
            
        except Exception as e:
            logger.warning(f"Failed to extract PDF {filename}: {e}")
            return ""

    # DOCX
    elif filename.lower().endswith(".docx"):
        try:
            import io
            import docx
            
            doc = docx.Document(io.BytesIO(file_bytes))
            # DOCX doesn't have "pages" easily, check paragraphs?
            # Just extract and check char limit later.
            text = "\n".join([p.text for p in doc.paragraphs])
        except Exception as e:
            logger.warning(f"Failed to extract DOCX {filename}: {e}")
            return ""

    # Fallback
    else:
        try:
            text = file_bytes.decode("utf-8")
        except Exception:
            return ""
            
    # Limit Chars
    if len(text) > max_chars:
        logger.warning(f"Extracted text from {filename} exceeds max chars ({len(text)} > {max_chars})")
        text = text[:max_chars] + "...(truncated)"
        
    return text
