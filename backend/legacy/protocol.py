"""Trusted in-memory Finance payloads; JSON clients cannot manufacture this type."""

class LegacyPayload(dict):
    pass


def is_legacy_payload(payload):
    return isinstance(payload,LegacyPayload) and bool(payload.get('legacyTransactionUID'))
