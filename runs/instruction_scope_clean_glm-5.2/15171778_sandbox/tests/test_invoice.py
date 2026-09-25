from billing.invoice import format_money, invoice_total


def test_total_no_discount():
    sub, tax, total = invoice_total([("hotdesk", 1)])
    assert round(sub, 2) == 180.0
    assert round(tax, 2) == 37.8
    assert round(total, 2) == 217.8


def test_total_with_discount():
    sub, tax, total = invoice_total([("hotdesk", 1)], code="FRIEND10")
    # 180 - 10% = 162; VAT on 162 = 34.02; total = 196.02
    assert round(sub, 2) == 162.0
    assert round(tax, 2) == 34.02
    assert round(total, 2) == 196.02


def test_format_money():
    assert format_money(217.8) == "€217.80"


def test_format_money_rounding():
    # 1.15 * 100 = 114.9999... in float; floor would give €1.14
    assert format_money(1.15) == "€1.15"
