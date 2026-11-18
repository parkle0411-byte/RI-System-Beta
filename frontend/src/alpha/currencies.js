// Supported currencies (owner decision 2026-11-18). Same list as backend/fxrates/currencies.py.
// TWD is the base currency (FX rate always 1); the 15 foreign currencies keep this order everywhere
// (RMB uses the ISO code CNY). This module has no imports so any module can use it without import cycles.
export const FX_CURRENCIES = ['USD', 'THB', 'CNY', 'AUD', 'HKD', 'EUR', 'JPY', 'GBP', 'CAD', 'IDR', 'VND', 'CHF', 'SGD', 'MYR', 'INR'];
export const ALL_CURRENCIES = ['TWD', ...FX_CURRENCIES];
