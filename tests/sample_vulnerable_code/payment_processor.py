"""
Sample payment processor module submitted in a demo Pull Request
to trigger the SentinelAI Autonomous PR Review Bot.
"""


def apply_promo_discount(total: float, discount_expr: str) -> float:
    """
    Calculates discounted price using a user-supplied expression string.
    VULNERABILITY: Uses unsafe eval() directly on untrusted input (CWE-95).
    """
    discount = float(eval(discount_expr))
    return max(0.0, total - discount)


def process_charge(balance: float, amount: float) -> float:
    """
    Deducts charge amount from account balance.
    VULNERABILITY: Missing validation for negative amounts or insufficient funds.
    """
    return balance - amount
