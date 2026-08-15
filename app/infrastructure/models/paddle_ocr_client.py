import logging
try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

logger = logging.getLogger(__name__)
_ocr_instance = None  # 惰性初始化，避免 PaddleOCR 未安装时模块加载崩溃


def get_ocr():
    global _ocr_instance
    if _ocr_instance is None and PaddleOCR is not None:
        try:
            _ocr_instance = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)
            logger.info("PaddleOCR initialized")
        except Exception as e:
            logger.error(f"PaddleOCR init failed: {e}")
            _ocr_instance = None
    return _ocr_instance


def parse_image(image_path: str) -> str:
    ocr = get_ocr()
    if ocr is None:
        logger.warning("PaddleOCR not available")
        return ""
    try:
        result = ocr.ocr(image_path, cls=True)
        if not result or not result[0]:
            return ""
        texts = [line[1][0] for line in result[0]]
        return "\n".join(texts)
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return ""
