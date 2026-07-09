import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 尝试导入 MinerU (magic-pdf)
try:
    from magic_pdf import do_parse
    MAGIC_PDF_AVAILABLE = True
    logger.info("MinerU (magic-pdf) loaded successfully")
except ImportError:
    MAGIC_PDF_AVAILABLE = False
    logger.warning("magic-pdf not installed, will use pdfplumber as fallback")

# 后备 pdfplumber
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.error("pdfplumber not installed, PDF parsing will be very limited")


def parse_pdf(pdf_path: str) -> str:
    """
    解析 PDF 文件并返回全部文本。
    优先使用 MinerU (magic-pdf)，失败或不可用时自动回退至 pdfplumber。
    """
    # 1. 优先使用 MinerU
    if MAGIC_PDF_AVAILABLE:
        try:
            # 调用 magic_pdf 的 do_parse，它返回一个字典，包含 'content' 等字段
            result = do_parse(pdf_path)
            if result and isinstance(result, dict):
                # 常见的返回结构：{'content': '...', 'images': [...]}
                full_text = result.get('content', '')
                if full_text and len(full_text.strip()) > 50:
                    logger.info(f"MinerU extracted {len(full_text)} chars from PDF")
                    return full_text.strip()
                else:
                    logger.warning("MinerU returned little or no text content")
            else:
                logger.warning("MinerU returned unexpected result format")
        except Exception as e:
            logger.error(f"MinerU parsing failed: {e}", exc_info=True)

    # 2. 后备：pdfplumber
    if PDFPLUMBER_AVAILABLE:
        try:
            text_parts = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            combined = "\n".join(text_parts)
            if combined.strip():
                logger.info(f"pdfplumber extracted {len(combined)} chars from PDF")
                return combined.strip()
        except Exception as e:
            logger.error(f"pdfplumber extraction failed: {e}")

    # 3. 彻底失败
    logger.error("All PDF parsing methods failed, unable to extract any text")
    return ""