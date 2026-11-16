# M: inactive reinsurers for the Reactivate checks (2026-11-16). Synthetic, written by hand in the shape of older records:
# a Lloyd's syndicate stored with the older 'AM Best' spelling and no abbreviation (the screen fills in market details,
# so reactivating it also changes its saved details), and a plain reinsurer whose details do not change.
from masterdata.models import MasterRecord
old = {'ratings': [{'grade': 'A+', 'agency': 'AM Best', 'status': '', 'outlook': '', 'asOfDate': '', 'checkedAt': '2026-10-19',
       'sourceUrl': 'https://www.lloyds.com/about-lloyds/investor-relations/ratings', 'ratingType': 'Financial Strength', 'legalEntity': "Lloyd's of London"}]}
for name, payload in (("Lloyd's Underwriter Syndicate No. 9901 UIR", old), ("UI Plain Inactive Re", {'abbreviation': 'UPI', 'fixedClauses': [], 'ratings': []})):
    MasterRecord.objects.update_or_create(entity_type='reinsurer', name=name, defaults=dict(is_active=False, payload=payload, created_by='ui-seed', updated_by='ui-seed'))
print('mdm reactivate seeded')
