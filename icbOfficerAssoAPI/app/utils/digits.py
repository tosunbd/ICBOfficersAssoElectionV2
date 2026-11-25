"""Bangla (০-৯) and English (0-9) digits are both accepted wherever a number is typed."""

_TO_ENGLISH = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def to_english_digits(value: str) -> str:
    """'১২৩' / '১2৩' -> '123'; every other character is kept."""
    return value.translate(_TO_ENGLISH)


def english_digits_in(value):
    """Pydantic 'before' validator: a string with Bangla digits becomes one with English digits.

    Used on number fields too, so "১২" posted for an int is read as 12.
    """
    return to_english_digits(value) if isinstance(value, str) else value
