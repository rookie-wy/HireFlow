import logging

logger = logging.getLogger(__name__)

# 精简说明：原 MinerU(magic-pdf) + pdfplumber 双实现已收敛为 pymupdf 单链路。
# 如需处理扫描件/图片型 PDF，由 resume_parser 调用 paddle_ocr_client 作为可选 OCR 后备。


def parse_pdf(pdf_path: str) -> str:
    """用 pymupdf 提取 PDF 全部文本。"""
    try:
        import fitz  # pymupdf
    except ImportError:
        logger.error("pymupdf not installed, PDF parsing unavailable")
        return ""

    try:
        text_parts = []
        with fitz.open(pdf_path) as doc:
            for page in doc:
                text_parts.append(page.get_text())
        combined = "\n".join(text_parts)
        if combined.strip():
            logger.info(f"pymupdf extracted {len(combined)} chars from PDF")
            return combined.strip()
        logger.warning("pymupdf returned no text (可能是扫描件，需 OCR 后备)")
    except Exception as e:
        logger.error(f"pymupdf parsing failed: {e}", exc_info=True)
    return ""
