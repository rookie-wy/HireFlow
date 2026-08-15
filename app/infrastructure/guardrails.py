"""输入/输出安全防护：PII 脱敏。

guardrails-ai（第三方毒性检测模型）已从依赖移除，改用轻量 PII 脱敏：
- 进入 LLM 的输入：身份证号脱敏（非业务必需），email/phone 保留（候选人去重/联系需要）。
- LLM 输出：全文脱敏（输出不应含任何 PII）。

企业如需更强的内容安全（毒性/越权检测），可重新启用 guardrails-ai 并在此接入。
"""
import logging
from app.core.config import settings
from app.utils.pii_utils import mask_pii, mask_id_card

logger = logging.getLogger(__name__)


def scan_input(text: str) -> str:
    """对进入 LLM 的输入做安全处理，返回脱敏后的文本。"""
    if not text:
        return text
    if not settings.ENABLE_PII_MASKING:
        return text
    masked = mask_id_card(text)
    if masked != text:
        logger.warning("输入含身份证号，已脱敏")
    return masked


def scan_output(text: str) -> str:
    """对 LLM 输出做安全处理，返回脱敏后的文本。"""
    if not text:
        return text
    if not settings.ENABLE_PII_MASKING:
        return text
    return mask_pii(text)
