"""文本提取：pymupdf 单链路（PDF），图片走可选 OCR。"""
from __future__ import annotations

from pathlib import Path

from app.core.errors import ParseError, get_logger

log = get_logger(__name__)

_MIN_TEXT_LEN = 50


def extract_pdf_text(file_path: str) -> str:
    """pymupdf 逐页提取文本。"""
    try:
        import fitz  # pymupdf
    except ImportError as exc:  # pragma: no cover
        raise ParseError("pymupdf 未安装") from exc
    try:
        doc = fitz.open(file_path)
        parts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(parts).strip()
    except Exception as exc:  # noqa: BLE001
        raise ParseError(cause=exc) from exc


def extract_image_text(file_path: str) -> str:
    """图片 OCR（paddleocr 可选，未安装返回空串）。"""
    try:
        from app.infra.ocr import parse_image  # 延迟导入可选模块

        return parse_image(file_path)
    except ImportError:
        log.warning("paddleocr 未安装，图片简历跳过 OCR（建议上传 PDF）")
        return ""
    except Exception as exc:  # noqa: BLE001
        log.warning("OCR failed: %s", exc)
        return ""


def extract_text(file_path: str, file_type: str) -> str:
    """统一入口：PDF 提取失败或过短时尝试 OCR 后备。"""
    suffix = Path(file_path).suffix.lower()
    text = ""
    if suffix == ".pdf":
        text = extract_pdf_text(file_path)
        if len(text) < _MIN_TEXT_LEN:
            # 扫描件 PDF：页转图后 OCR
            ocr_text = extract_image_text(file_path)
            text = text if len(text) >= len(ocr_text) else ocr_text
    elif suffix in {".png", ".jpg", ".jpeg"}:
        text = extract_image_text(file_path)
    return text.strip()
