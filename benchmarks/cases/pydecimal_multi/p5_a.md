In `plain.py`, add a method `Decimal.quantize_to_places(n, rounding=None, context=None)`
that quantizes to exactly `n` decimal places (equivalent to
`self.quantize(Decimal(10) ** -n, rounding, context)`).
Implement minimally, placing it immediately after the existing `quantize` method.
Show the unified diff.
