import json

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from cases.oversea_reference_correction import apply_reference_correction, preview_reference_correction


class Command(BaseCommand):
    help = 'Preview one unbooked Oversea reference correction; --apply requires the reviewed preview signature.'

    def add_arguments(self, parser):
        parser.add_argument('--case-uid', required=True)
        parser.add_argument('--old-reference', required=True)
        parser.add_argument('--new-reference')
        parser.add_argument('--expected-signature')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        try:
            if options['apply']:
                result = apply_reference_correction(options['case_uid'], options['old_reference'],
                                                    options['new_reference'], options['expected_signature'])
            else:
                result = preview_reference_correction(options['case_uid'], options['old_reference'], options['new_reference'])
        except (ValueError, TypeError, LookupError, ObjectDoesNotExist, ValidationError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps({'apply': options['apply'], **result}, ensure_ascii=False))
