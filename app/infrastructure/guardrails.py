import logging
from app.core.exceptions import SecurityException

logger = logging.getLogger(__name__)

import logging

logger = logging.getLogger(__name__)

# 暂时禁用 Guardrails，避免模型加载和解析异常
def scan_input(text: str) -> bool:
    # TODO: 生产环境启用 Guardrails ToxicLanguage 检测
    return True

def scan_output(text: str) -> bool:
    # TODO: 生产环境启用 Guardrails ToxicLanguage 检测
    return True

# # 尝试初始化有毒语言检测，失败则置为 None
# try:
#     _input_guard = Guard().use(ToxicLanguage(on_fail="exception"))
#     _output_guard = Guard().use(ToxicLanguage(on_fail="exception"))
#     _toxicity_enabled = True
#     logger.info("ToxicLanguage guard initialized successfully")
# except Exception as e:
#     logger.warning(f"ToxicLanguage guard initialization failed, toxicity scanning disabled: {e}")
#     _input_guard = None
#     _output_guard = None
#     _toxicity_enabled = False
#
# def scan_input(text: str) -> bool:
#     if not _toxicity_enabled or _input_guard is None:
#         return True  # 跳过检测
#     try:
#         _input_guard.validate(text)
#         return True
#     except Exception as e:
#         logger.warning(f"Input security violation: {str(e)}")
#         raise SecurityException(f"输入包含不当内容: {str(e)}")
#
# def scan_output(text: str) -> bool:
#     if not _toxicity_enabled or _output_guard is None:
#         return True
#     try:
#         _output_guard.validate(text)
#         return True
#     except Exception as e:
#         logger.warning(f"Output security violation: {str(e)}")
#         raise SecurityException(f"输出包含不当内容: {str(e)}")