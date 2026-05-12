"""
Filename generation utilities for Aetna policies.

Extracts policy identifiers from source URLs and generates clean filenames.
"""

import re
import structlog

logger = structlog.get_logger(__name__)


def extract_policy_identifier(url: str) -> str:
    """
    Extract policy identifier from Aetna URL.
    
    Example:
        https://www.aetna.com/cpb/medical/data/700_799/0743.html
        → "0743"
    
    Args:
        url: Aetna policy URL
        
    Returns:
        Policy identifier extracted from URL
    """
    # Pattern: /cpb/medical/data/{folder}/{identifier}.html
    match = re.search(r'/cpb/.*?/(\w+)\.html', url)
    
    if match:
        identifier = match.group(1)
        logger.debug("Extracted policy identifier", url=url, identifier=identifier)
        return identifier
    
    # Fallback: use last part of path before .html
    parts = url.rstrip('/').split('/')
    for part in reversed(parts):
        if part and part != 'html':
            clean_part = part.replace('.html', '')
            logger.warning(
                "Using fallback identifier extraction",
                url=url,
                identifier=clean_part
            )
            return clean_part
    
    # Last resort: use hash of URL
    import hashlib
    url_hash = hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()[:8]
    logger.warning("Could not extract identifier, using hash", url=url, hash=url_hash)
    return url_hash


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename by removing special characters.
    
    Args:
        filename: Raw filename
        
    Returns:
        Sanitized filename safe for filesystem
    """
    # Replace spaces with underscores
    sanitized = filename.replace(' ', '_')
    
    # Remove special characters (keep alphanumeric, underscore, hyphen, period)
    sanitized = re.sub(r'[^a-zA-Z0-9_\-\.]', '', sanitized)
    
    # Remove multiple consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    
    return sanitized


def generate_filename(url: str, payor_prefix: str, extension: str = "md") -> str:
    """
    Generate filename for Aetna policy.
    
    Format: {PayorPrefix}_{PolicyIdentifier}.{extension}
    Example: AetnaPolicy_0743.md
    
    Args:
        url: Policy source URL
        payor_prefix: Payor prefix (e.g., "AetnaPolicy")
        extension: File extension (default: "md" for markdown)
        
    Returns:
        Generated filename
    """
    identifier = extract_policy_identifier(url)
    sanitized_identifier = sanitize_filename(identifier)
    filename = f"{payor_prefix}_{sanitized_identifier}.{extension}"
    
    logger.info(
        "Generated filename",
        url=url,
        filename=filename,
        extension=extension
    )
    
    return filename
