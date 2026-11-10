"""Preview or explicitly consolidate pre-existing permutations of one membership."""
import hashlib
import json
from collections import defaultdict
from django.core.management.base import BaseCommand, CommandError
from coordination.services import serialized, PRODUCTION_SOURCES
from cases import insured_master as im
from cases.models import Case
from masterdata.models import MasterRecord


def plan():
    groups = defaultdict(list)
    for record in MasterRecord.objects.filter(entity_type='insured', is_active=True).order_by('id'):
        if not (record.payload or {}).get('mergedInto'):
            groups[im.combination_key(record.name)].append(record)
    return [{'survivor': rows[0].pk, 'members': [{'id': r.pk, 'version': r.row_version,
             'caseCount': Case.objects.filter(insured_master_id=r.pk).count()} for r in rows]}
            for rows in groups.values() if len(rows) > 1]


class Command(BaseCommand):
    help = 'Preview duplicate insured combinations; --apply requires the preview signature.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--expected-signature')

    def handle(self, *args, **options):
        with serialized(PRODUCTION_SOURCES):
            groups = plan()
            signature = hashlib.sha256(json.dumps(groups, sort_keys=True).encode()).hexdigest()
            if options['apply'] and signature != options['expected_signature']:
                raise CommandError('Insured combinations changed; preview and review the current signature first.')
            if options['apply']:
                actor = {'id': 'insured-combination-consolidation', 'name': 'Insured combination consolidation'}
                for group in groups:
                    target = MasterRecord.objects.get(pk=group['survivor'])
                    for row in group['members'][1:]:
                        target = im.merge_records(MasterRecord.objects.get(pk=row['id']), target, actor)
            self.stdout.write(json.dumps({'applied': options['apply'], 'groups': groups, 'signature': signature}))
