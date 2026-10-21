"""Edit the one Lloyd's rating profile with MDM permissions and version checks."""
from django.db import IntegrityError, transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from, object_body
from .lloyds_market import SOURCE_NAME, market_profile
from .models import MarketRatingProfile
from .views import validate_payload


def profile_state(profile):
    return dict(marketCode="lloyds", ratingsSource=SOURCE_NAME,
                ratings=profile.ratings, rowVersion=profile.row_version)


class LloydsRatingsView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "mdm.read", "PUT": "mdm.write"}

    def get(self, request):
        return Response(dict(ok=True, profile=market_profile()))

    def put(self, request):
        body = object_body(request)
        version = body.get("rowVersion")
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            return Response(dict(error="version_required", message="A valid rating profile version is required."), status=400)
        ratings = body.get("ratings")
        if not isinstance(ratings, list) or not ratings:
            return Response(dict(error="invalid_ratings", message="Enter at least one rating with an agency and a grade."), status=400)
        payload, err = validate_payload("reinsurer", {"ratings": ratings})
        if err:
            return Response(dict(error="invalid_ratings", message=err), status=400)
        ratings = payload["ratings"]
        for row in ratings:
            row["legalEntity"] = SOURCE_NAME
            row["ratingType"] = row["ratingType"] or "Financial Strength"
            # Manual edits do not imply a new official-source review.
            row["checkedAt"] = ""
        actor = actor_from(request.ri_principal)
        with transaction.atomic():
            current = MarketRatingProfile.objects.select_for_update().filter(market_code="lloyds").first()
            actual = 0 if current is None else current.row_version
            if version != actual:
                return Response(dict(error="version_conflict", message="Lloyd's Market ratings changed elsewhere. Reload the ratings before saving.", currentRowVersion=actual), status=409)
            before = None if current is None else profile_state(current)
            if current is None:
                try:
                    with transaction.atomic():
                        current = MarketRatingProfile.objects.create(market_code="lloyds", ratings=ratings,
                            created_by=actor["id"], updated_by=actor["id"])
                except IntegrityError:
                    return Response(dict(error="version_conflict", message="Lloyd's Market ratings changed elsewhere. Reload the ratings before saving."), status=409)
            else:
                current.ratings = ratings
                current.row_version += 1
                current.updated_by = actor["id"]
                current.save(update_fields=["ratings", "row_version", "updated_by", "updated_at"])
            after = profile_state(current)
            record_snapshot(entity_type="market_rating_profile", entity_id="lloyds", version=current.row_version,
                reason="market_ratings_updated", data=after, created_by=actor["id"])
            record_audit(entity_type="market_rating_profile", entity_id="lloyds", action="update_market_ratings",
                actor=actor, before=before, after=after, request_id=request_id_from(request))
            result = market_profile()
        return Response(dict(ok=True, profile=result))
