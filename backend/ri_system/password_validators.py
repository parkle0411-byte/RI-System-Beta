import re

from django.core.exceptions import ValidationError

RULE_TEXT_ZH = "密碼至少需要 8 個字元，且必須同時包含英文字母與數字。"


class LetterAndDigitValidator:
    """密碼必須至少包含一個英文字母（A-Z、a-z）與一個數字（0-9）。其他符號可以有，但不能取代這兩者。"""

    def validate(self, password, user=None):
        if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
            raise ValidationError("密碼必須同時包含英文字母與數字。", code="password_no_letter_and_digit")

    def get_help_text(self):
        return "密碼必須同時包含英文字母與數字。"
