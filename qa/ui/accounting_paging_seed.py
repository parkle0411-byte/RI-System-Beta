# Y: settled legacy history for the Accounting server-paging checks (2026-11-17). Synthetic only: 160 transactions that were
# settled before import (three accounts each), with their imported receipts, and a cedant that appears only in this history.
import uuid
from django.utils import timezone
from legacy.models import ImportBatch, LegacyTransaction
batch = ImportBatch.objects.create(filename='ui-paging-history.xlsx', sha256='a' * 64, storage_key='qa/ui-paging-history.xlsx', status='imported', created_by='ui-seed')
for n in range(1, 161):
    uid = uuid.uuid4(); number = f'UI-HIST-{n:03d}'; reference = f'UI-HIST-REF-{n:03d}'
    data = dict(reference=reference, currency='TWD', insured=f'UI History Insured {n:03d}', insuredCn='歷史分頁測試', cedant='UI History Only Cedant',
                party='UI History Reinsurer', ae='UI Legacy Sales', statementNo=f'UI-ST-{n:03d}', gross=10000, share=100, rule='ordinary', kind='premium',
                effectiveDate=f'2024-{(n % 12) + 1:02d}-01', expiryDate='2025-12-31', receiveReminder='2024-03-15', payReminder='2024-04-15',
                amounts=dict(premium=10000 + n, commission=0, tax=0, brokerage=500, claim=0, cedantNet=10000 + n, reinsurerNet=9500 + n))
    entries = [dict(id=str(uuid.uuid4()), entryType='payment', transactionNo=f'{number}-T{leg}', scheduleKey='single:' + key, partyType=typ, partyName=name,
                    paymentDirection=side, currency='TWD', amount=amount, nonCash=False, entryKind='legacy-import', batchId=f'legacy-import:{uid}:{number}-T{leg}',
                    importBatchId=str(batch.pk), paymentDate='2024-03-15', reference=f'UI-REC-{n:03d}-{leg}', note='Imported', createdAt=timezone.now().isoformat(),
                    createdBy='ui-seed', createdByName='UI Seed')
               for leg, key, typ, name, side, amount in ((1, 'cedant', 'cedant', 'UI History Only Cedant', 'receivable', 10000 + n),
                                                         (2, 'r1', 'reinsurer', 'UI History Reinsurer', 'payable', 9500 + n))]
    LegacyTransaction.objects.create(uid=uid, number=number, original_serial=number, reference=reference, currency='TWD', revenue_month='2024-03',
        status='confirmed', historical=True, batch=batch, first_confirmed_at=timezone.now(), data=data, fx_snapshot=dict(rate=1),
        financial={'paymentEntries': entries})
print('Accounting paging history seeded', LegacyTransaction.objects.filter(number__startswith='UI-HIST-').count())
