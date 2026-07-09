import re

def mask_phone(text: str) -> str:
    return re.sub(r'(1[3-9]\d)\d{4}(\d{4})', r'\1****\2', text)

def mask_email(text: str) -> str:
    return re.sub(r'([^@]{3})[^@]*(@[^@]+\.[^@]+)', r'\1****\2', text)

def mask_id_card(text: str) -> str:
    return re.sub(r'(\d{4})\d{10}(\d{3}[\dXx])', r'\1**********\2', text)

def mask_pii(text: str) -> str:
    text = mask_phone(text)
    text = mask_email(text)
    text = mask_id_card(text)
    return text