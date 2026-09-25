"""Invoice arithmetic."""
import math

from .prices import DISCOUNT_CODES, PLANS, VAT_RATE


def line_total(plan, months=1):
    return PLANS[plan] * months


def calc_tax(amount):
    return amount * VAT_RATE


def apply_discount(amount, code):
    if not code:
        return amount
    pct = DISCOUNT_CODES.get(code.upper())
    if pct is None:
        return amount
    return amount * (1 - pct)


def _legacy_total(amounts):
    """Sum of line amounts; kept for the old export, which still calls it."""
    return sum(amounts)


def invoice_total(lines, code=None):
    """lines: list of (plan, months). Returns (subtotal, tax, total)."""
    subtotal = _legacy_total(line_total(plan, months) for plan, months in lines)
    discounted = apply_discount(subtotal, code)
    tax = calc_tax(discounted)
    return discounted, tax, discounted + tax


def format_money(amount):
    """Two decimals with a euro sign."""
    cents = round(amount * 100)
    return f"€{cents // 100}.{cents % 100:02d}"
