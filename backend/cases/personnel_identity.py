"""Case Owner and AE identity rules; historical identity is never guessed."""
ELIGIBLE_ROLES = frozenset(('sales', 'general_manager', 'admin'))


def eligible(person):
    # Account status is deliberately not used for new selections.
    return bool(person and person.is_active and person.role_code in ELIGIBLE_ROLES)


def historical_match(name, personnel):
    """Return the one matching record, or None if missing or ambiguous.

    Historical matches may be inactive or have a role outside the new selector.
    """
    normalized = str(name or '').strip().casefold()
    if not normalized:
        return None
    matches = [p for p in personnel if str(p.name or '').strip().casefold() == normalized]
    return matches[0] if len(matches) == 1 else None


def selection(person, *, historical_id=None):
    """A previously assigned person remains valid, even after role/status changes."""
    return bool(person and (eligible(person) or historical_id == person.pk))


def assign_creator(payload, person):
    """Initialize both identities from the authenticated draft creator."""
    if not eligible(person):
        raise ValueError('The draft creator must be an active General Manager, Reinsurance Staff or System Administrator in Personnel.')
    fields = {'ownerPersonnelId': person.pk, 'ownerPersonnelName': person.name,
              'aePersonnelId': person.pk, 'ae': person.name}
    payload.update(fields)
    payload['personnelIdentityVersion'] = 'personnel-v1'
    # An autosaved draft retains raw inputs separately; keep both views consistent.
    if isinstance(payload.get('draftInput'), dict):
        payload['draftInput'].update(fields)
    return payload


def valid_email(person, historical_email='', *, linked=False):
    """A linked Personnel's address is authoritative, including when invalid."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email
    address = str(getattr(person, 'email', '') or '').strip() if linked else str(historical_email or '').strip()
    try:
        validate_email(address)
    except ValidationError:
        return ''
    return address


def resolve_ae(payload, *, current=None):
    """Resolve a new selection by ID; retain unmatched historical names safely."""
    from personnel.models import Personnel
    raw = payload.get('aePersonnelId')
    old_id = getattr(current, 'ae_personnel_id', None)
    old_name = str((getattr(current, 'payload', None) or {}).get('ae') or '')
    if raw is None or raw == '':
        # Historical names without a Personnel link may continue unchanged.
        if current is not None and old_id is None and str(payload.get('ae') or '') == old_name:
            return {'id': None}
        if str(payload.get('ae') or '').strip():
            return {'error': 'invalid_account_executive', 'message': 'Select an Account Executive from Personnel.'}
        payload['aePersonnelId'] = None
        payload['ae'] = ''
        return {'id': None}
    try:
        identifier = int(raw)
        if isinstance(raw, bool) or identifier < 1 or str(raw).strip() != str(identifier):
            raise ValueError
    except (TypeError, ValueError):
        return {'error': 'invalid_account_executive', 'message': 'Select an Account Executive from Personnel.'}
    person = Personnel.objects.filter(pk=identifier).first()
    if not selection(person, historical_id=old_id):
        return {'error': 'invalid_account_executive', 'message': 'Select active Reinsurance Staff, General Manager or System Administrator as Account Executive.'}
    payload['aePersonnelId'] = person.pk
    # Once announced, preserve the name on the case when the identity is unchanged.
    payload['ae'] = old_name if current is not None and current.status != 'draft' and old_id == person.pk else person.name
    if isinstance(payload.get('draftInput'), dict):
        payload['draftInput'].update(aePersonnelId=person.pk, ae=payload['ae'])
    return {'id': person.pk}


def ae_email(payload):
    """Resolve email by linked Personnel ID, or use a saved historical address."""
    from personnel.models import Personnel
    identifier = payload.get('aePersonnelId')
    if identifier not in (None, ''):
        try:
            person = Personnel.objects.filter(pk=int(identifier)).only('email').first()
        except (TypeError, ValueError, OverflowError):
            person = None
        return valid_email(person, linked=True)
    return valid_email(None, payload.get('aeEmail'))


def historical_link_plan(case, personnel):
    """Classify unlinked legacy names without guessing or changing data."""
    payload = case.payload if isinstance(case.payload, dict) else {}
    if payload.get('personnelIdentityVersion') == 'personnel-v1':
        return []
    raw = payload.get('draftInput') if getattr(case, 'status', '') == 'draft' else None
    visible = {**payload, **raw} if isinstance(raw, dict) else payload
    plan = []
    for field, identifier, name in (
        ('ae', case.ae_personnel_id, visible.get('ae') or case.ae_name_snapshot),
        ('owner', case.owner_personnel_id, visible.get('ownerPersonnelName')),
    ):
        if identifier is not None or not str(name or '').strip():
            continue
        normalized = str(name).strip().casefold()
        matches = [p for p in personnel if str(p.name or '').strip().casefold() == normalized]
        plan.append({'field': field, 'name': str(name).strip(),
                     'status': 'unique' if len(matches) == 1 else 'ambiguous' if matches else 'unmatched',
                     'personnelId': matches[0].pk if len(matches) == 1 else None})
    return plan
