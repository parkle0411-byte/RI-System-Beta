"""Supported currencies (owner decision 2026-11-18).

TWD is the base currency (its FX rate is always 1). The 15 foreign currencies keep this order
everywhere (FX Rates, every currency menu and validation); RMB uses the ISO code CNY. Every
monthly FX entry must contain all 15 rates. Rates keep six decimal places.
Plain constants only, so any module can import this without loading Django models.
"""
FOREIGN = ("USD", "THB", "CNY", "AUD", "HKD", "EUR", "JPY", "GBP", "CAD", "IDR", "VND", "CHF", "SGD", "MYR", "INR")
ALL = ("TWD",) + FOREIGN
