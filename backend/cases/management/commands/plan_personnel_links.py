"""Dry-run by default; applying historical links is a separate operation."""
from collections import Counter
import copy

from django.core.management.base import BaseCommand
from django.utils import timezone

from audit.services import record_audit, record_snapshot
from coordination.services import PRODUCTION_SOURCES, serialized
from personnel.models import Personnel
from cases.models import Case
from cases.personnel_identity import historical_link_plan


class Command(BaseCommand):
    help = 'Count unique, ambiguous and unmatched historical Personnel names; --apply links unique matches.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Apply unique links after the required separate authorization and backup.')

    def handle(self, *args, **options):
        apply = options['apply']
        counts = Counter()
        ids = list(Case.objects.order_by('id').values_list('id', flat=True))
        # Serialize each batch with existing case workflows and recheck all matches.
        for offset in range(0, len(ids), 100):
            with serialized(PRODUCTION_SOURCES):
                people = list(Personnel.objects.select_for_update().order_by('id'))
                names = {person.pk: person.name for person in people}
                cases = Case.objects.select_for_update().filter(pk__in=ids[offset:offset + 100]).order_by('id')
                for case in cases:
                    plan = historical_link_plan(case, people)
                    for item in plan:
                        counts[item['field'] + '_' + item['status']] += 1
                    selected = [item for item in plan if item['status'] == 'unique']
                    if not apply or not selected:
                        continue
                    payload = copy.deepcopy(case.payload or {})
                    before = {'aePersonnelId': case.ae_personnel_id, 'ownerPersonnelId': case.owner_personnel_id}
                    now = timezone.now().isoformat()
                    for item in selected:
                        key = 'aePersonnelId' if item['field'] == 'ae' else 'ownerPersonnelId'
                        if item['field'] == 'ae': case.ae_personnel_id = item['personnelId']
                        else: case.owner_personnel_id = item['personnelId']
                        payload[key] = item['personnelId']
                        if isinstance(payload.get('draftInput'), dict): payload['draftInput'][key] = item['personnelId']
                        payload.setdefault('personnelIdentityHistory', []).append({
                            'field':item['field'], 'beforePersonnelId':None, 'afterPersonnelId':item['personnelId'],
                            'historicalName':item['name'], 'personnelName':names[item['personnelId']], 'reason':'Unique historical name match',
                            'changedBy':'system:personnel-link-migration', 'changedByName':'Personnel link migration', 'changedAt':now})
                    case.payload = payload
                    case.row_version += 1
                    case.updated_by = 'system:personnel-link-migration'
                    case.save()
                    record_snapshot(entity_type='case', entity_id=case.case_uid, version=case.row_version, reason='historical_personnel_auto_link', data={'caseUid':str(case.case_uid), 'payload':payload}, created_by=case.updated_by)
                    record_audit(entity_type='case', entity_id=case.case_uid, action='historical_personnel_auto_link', before=before,
                                 after={'aePersonnelId':case.ae_personnel_id, 'ownerPersonnelId':case.owner_personnel_id},
                                 actor={'id':case.updated_by, 'name':'Personnel link migration', 'role':'system'}, source='migration', metadata={})
                    counts['cases_updated'] += 1
        self.stdout.write(('APPLIED' if apply else 'DRY RUN') + ' ' + ' '.join(f'{key}={counts[key]}' for key in sorted(counts)))
