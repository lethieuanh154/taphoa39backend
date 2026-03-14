"""
ZIP file extraction utility for invoice email attachments.
Extracts XML and PDF files from ZIP archives.
"""

import zipfile
import io
from typing import Optional, Tuple


def extract_xml_from_zip(zip_bytes: bytes) -> Optional[Tuple[bytes, str]]:
    """
    Find and extract first XML file from ZIP archive.

    Args:
        zip_bytes: Raw ZIP file content

    Returns:
        Tuple of (xml_content_bytes, filename) or None if no XML found
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if name.lower().endswith('.xml') and not name.startswith('__MACOSX'):
                    return (zf.read(name), name)
        return None
    except (zipfile.BadZipFile, Exception) as e:
        print(f"Error extracting XML from ZIP: {e}")
        return None


def extract_pdf_from_zip(zip_bytes: bytes) -> Optional[Tuple[bytes, str]]:
    """
    Find and extract first PDF file from ZIP archive.

    Args:
        zip_bytes: Raw ZIP file content

    Returns:
        Tuple of (pdf_content_bytes, filename) or None if no PDF found
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if name.lower().endswith('.pdf') and not name.startswith('__MACOSX'):
                    return (zf.read(name), name)
        return None
    except (zipfile.BadZipFile, Exception) as e:
        print(f"Error extracting PDF from ZIP: {e}")
        return None


def list_zip_contents(zip_bytes: bytes) -> list:
    """
    List all files inside a ZIP archive.

    Returns:
        List of dicts with filename and size
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            return [
                {'filename': info.filename, 'size': info.file_size}
                for info in zf.infolist()
                if not info.is_dir() and not info.filename.startswith('__MACOSX')
            ]
    except (zipfile.BadZipFile, Exception) as e:
        print(f"Error listing ZIP contents: {e}")
        return []