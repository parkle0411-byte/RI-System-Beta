"""Shared Lloyd's market financial strength ratings, reviewed 2026-10-19.

Source: https://www.lloyds.com/about-lloyds/investor-relations/ratings
Default profile until the first MDM market update. Individual syndicates cannot override it.
"""
import re

SOURCE_NAME = "Lloyd's of London"
SOURCE_URL = "https://www.lloyds.com/about-lloyds/investor-relations/ratings"
CHECKED_AT = "2026-10-19"
_PATTERN = re.compile(r"^Lloyd['’]s\s+Underwriter\s+Syndicate\s+No\.", re.I)


def is_lloyds_market(name):
    return bool(_PATTERN.match(str(name or "").strip()))


def default_market_ratings():
    return [dict(agency=agency, grade=grade, outlook="", ratingType="Financial Strength",
                 asOfDate="", legalEntity=SOURCE_NAME, sourceUrl=SOURCE_URL,
                 checkedAt=CHECKED_AT, status="")
            for agency, grade in [("AM Best", "A+"), ("S&P Global", "AA-"),
                                  ("Fitch Ratings", "AA-"), ("KBRA", "AA-")]]


def market_profile():
    from .models import MarketRatingProfile
    saved = MarketRatingProfile.objects.filter(market_code="lloyds").first()
    return dict(name="Lloyd's Market", ratingsSource=SOURCE_NAME, sourceUrl=SOURCE_URL,
                checkedAt=CHECKED_AT if saved is None else "",
                ratings=default_market_ratings() if saved is None else saved.ratings,
                rowVersion=0 if saved is None else saved.row_version,
                updatedAt=None if saved is None else saved.updated_at.isoformat())


def market_ratings():
    return market_profile()["ratings"]


def effective_payload(entity_type, name, payload, ratings=None):
    if entity_type == "reinsurer" and is_lloyds_market(name):
        return {**(payload or {}), "ratingsSource": SOURCE_NAME, "ratings": market_ratings() if ratings is None else ratings}
    if isinstance(payload, dict) and payload.get("ratingsSource") == SOURCE_NAME:
        value = {**payload, "ratings": []}
        value.pop("ratingsSource", None)
        return value
    return payload
