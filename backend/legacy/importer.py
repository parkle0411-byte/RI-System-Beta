import hashlib
import json
import uuid
from pathlib import Path
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from cases import storage
from coordination.services import serialized, PRODUCTION_SOURCES
from .excel import read_workbook, date_value, label
from .money import number, rounded
from .models import ImportBatch, LegacyTransaction, LegacyAudit
from .services import fail, audit
from .ledger import detect_rule

APPROVED_EXCLUSIONS=json.loads(Path(__file__).with_name('import_exclusions.json').read_text(encoding='utf-8'))


def excluded_row(row):
    serial=label(row['values'].get('流水號'))
    if serial in APPROVED_EXCLUSIONS or serial in getattr(settings,'LEGACY_IMPORT_EXCLUDED_SERIALS',()):
        return dict(row=row['row'],serial=serial,reason=APPROVED_EXCLUSIONS.get(serial,'Excluded by owner instruction; do not import.'))
    return None


def converted(row, rule_cache):
    v=row['values']; notes=[]
    def money(key, required=True):
        value=v.get(key)
        if value in (None,'') and not required:
            return None
        return number(value,key)
    serial=label(v.get('流水號')); reference=label(v.get('TW Ref. No.'))
    if row['errors']:raise ValueError('Formula errors or formulas without cached results: '+', '.join(row['errors']))
    if not serial or len(serial)>80 or not reference or len(reference)>192:
        raise ValueError('A valid original serial and old reference are required.')
    if v.get('Class')!='PD' or v.get('Fac / Claim') not in ('Fac','Claim'):
        raise ValueError('Only Facultative Property rows can be imported.')
    if str(v.get('Full-closed','')).strip().lower()!='v':
        raise ValueError('This phase imports only the confirmed fully-settled historical dataset.')
    currency=label(v.get('Currency')).upper()
    if currency not in ('TWD','USD','MYR','EUR','JPY','GBP','HKD'):raise ValueError('Unsupported currency.')
    party=label(v.get('Reinsurer'));cedant=label(v.get('Cedant'))
    if not party or not cedant:raise ValueError('Cedant and reinsurance settlement party are required.')
    if party not in rule_cache:rule_cache[party]=detect_rule(party)
    data=dict(reference=reference,currency=currency,party=party,cedant=cedant,
        insured=v.get('Description') or v.get('Insured (in English)',''),insuredCn=v.get('Insured (in Chinese)',''),
        effectiveDate=date_value(v.get('Effective Date')),expiryDate=date_value(v.get('Expiry Date')),
        revenueMonth=date_value(v.get('Revenue Month'))[:7],ae=v.get('AE',''),subAe=v.get('Sub AE',''),
        statementNo=str(v.get("Cedant's Policy No.",'') or ''),policyNo='',reinsurerRef=str(v.get("Reinsurer's Ref. No.",'') or ''),
        gross=money('100%Premium',False),share=None if v.get('Share') in (None,'') else money('Share')*100,
        brokerageNote=v.get('Note for Bkg.',''),claimNote=v.get('Note for Claim',''),remark=v.get('Remark',''),
        kind='claim' if v.get('Fac / Claim')=='Claim' else 'endorsement' if v.get('Endorsement No.') else 'premium',
        rule=rule_cache[party],cedantDays=90,reinsurerDays=90,newRenew=v.get('New / Renew',''),
        endorsementNo=str(v.get('Endorsement No.','') or ''),installmentNo=str(v.get('Installment No.','') or ''))
    data.update(issueDate=date_value(v.get('Issue Date')),claimIssueDate=date_value(v.get('Issue Date of Claim')),
        lossDate=date_value(v.get('DOL')),receiveReminder=date_value(v.get('Receive Date')),
        payReminder=date_value(v.get('Pay Date')),declaration=v.get('Declaration',''),
        accountingReferences={key:str(v.get(key) or '') for key in (
            'Cedant Receipt No','Cedant Payment No','Reinsurer Receipt No','Reinsurer Payment No.')})
    a=dict(premium=money('Our Share Premium'),commission=money('R/I Comm.'),tax=money('Tax'),
        claim=money('Claim',False) or 0,brokerage=money('Bkg. (Original Currency)'),
        cedantNet=money('Net Premium from Cedant'),reinsurerNet=money('Net Premium to Reinsurer'),
        brokeragePct=money('Bkg.(%)',False))
    if a['brokeragePct'] is not None:a['brokeragePct']*=100
    data['amounts']=a;data['brokerage']=a['brokerage'];data['claim']=a['claim']
    rate=money('Exchange Rate');total=money('Bkg. (in TWD)');ae=money('Re Dept. Bkg. (in TWD)')
    premium_twd=rounded(a['premium']*rate,'TWD')
    people=[dict(name=data['ae'],income=ae,premium=premium_twd,incomeOriginal=None,pct=None)]
    if data['subAe']:
        residual=Decimal(str(v['Bkg. (in TWD)']))-Decimal(str(v['Re Dept. Bkg. (in TWD)']))
        people.append(dict(name=data['subAe'],income=float(residual),premium=0,incomeOriginal=None,pct=None))
    snapshot=dict(rate=rate,incomeTwd=total,premiumTwd=premium_twd,awaitingFx=False,people=people,
        historicalPreserved=True,aeIncomeTwd=ae,subAeIncomeTwd=people[1]['income'] if data['subAe'] else 0)
    for key in ('gross','share'):
        if data.get(key) is None:notes.append('Missing '+key+'; stored historical amounts preserved.')
    if not data['rule']:notes.append('Payment rule awaiting confirmation for future entries.')
    return dict(original_serial=serial,number=serial,reference=reference,currency=currency,
        revenue_month=data['revenueMonth'],data=data,fx_snapshot=snapshot),notes


def preview(person, filename, content):
    if person.role_code!='admin':fail('Only System Administrators may import.',403)
    parsed=read_workbook(content);rules={};errors=[];warnings=[];seen=set();duplicates=[];count=0
    existing=set(LegacyTransaction.objects.filter(original_serial__isnull=False).values_list('original_serial',flat=True))
    totals={};excluded=[]
    for row in parsed['rows']:
        omission=excluded_row(row)
        if omission:
            excluded.append(omission);continue
        serial=label(row['values'].get('流水號'))
        if serial in seen or serial in existing:
            duplicates.append(dict(row=row['row'],serial=serial));continue
        seen.add(serial)
        try:item,notes=converted(row,rules)
        except ValueError as exc:
            errors.append(dict(row=row['row'],serial=serial,message=str(exc)));continue
        count+=1
        warnings.extend(dict(row=row['row'],serial=serial,message=n) for n in notes)
        bucket=totals.setdefault(item['currency'],dict(count=0,cedantNet=0,reinsurerNet=0,brokerage=0))
        bucket['count']+=1
        for key in ('cedantNet','reinsurerNet','brokerage'):bucket[key]+=item['data']['amounts'][key]
    manifest=dict(sourceRows=len(parsed['rows']),eligible=count,duplicates=duplicates,errors=errors,warnings=warnings,
        totals=totals,excluded=excluded,commentPolicy='not_imported',sourceSha256=parsed['sha256'])
    with serialized(PRODUCTION_SOURCES):
        bid=uuid.uuid4();key=f'legacy-imports/{bid}/original.xlsx'
        storage.put(key,content)
        batch=ImportBatch.objects.create(id=bid,filename=filename[:255],sha256=parsed['sha256'],storage_key=key,
            manifest=manifest,created_by=f'personnel:{person.pk}' if person.pk is not None else 'system:owner-authorized-deployment')
        audit(person,batch.pk,'import_preview',after={'sha256':batch.sha256,**manifest})
    return batch


def commit(person,batch_id,sha256):
    if person.role_code!='admin':fail('Only System Administrators may import.',403)
    with serialized(PRODUCTION_SOURCES):
        batch=ImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status!='preview':fail('This batch is not awaiting import.',409)
        if batch.sha256!=sha256:fail('Review the current preview before importing.',409)
        if batch.manifest.get('errors'):fail('Resolve the preview errors before importing.',409)
        with storage.open_read(batch.storage_key) as f:content=f.read()
        if hashlib.sha256(content).hexdigest()!=batch.sha256:fail('The stored source workbook changed.',409)
        parsed=read_workbook(content);rules={};seen=set()
        existing=set(LegacyTransaction.objects.filter(original_serial__isnull=False).values_list('original_serial',flat=True))
        records=[];skipped=[];stamp=timezone.now();excluded=[]
        for row in parsed['rows']:
            omission=excluded_row(row)
            if omission:
                excluded.append(omission);continue
            serial=label(row['values'].get('流水號'))
            if serial in seen or serial in existing:
                skipped.append(dict(row=row['row'],serial=serial));continue
            seen.add(serial)
            try:item,_=converted(row,rules)
            except ValueError as exc:fail(str(exc))
            records.append(LegacyTransaction(**item,status='confirmed',historical=True,batch=batch,
                original=row['values'],owner_id=person.pk,created_by_id=person.pk,first_confirmed_at=stamp))
        if excluded!=batch.manifest.get('excluded',[]):
            fail('Import exclusions changed. Create and review a new preview before importing.',409)
        LegacyTransaction.objects.bulk_create(records,batch_size=250)
        batch.status='imported';batch.imported_at=stamp
        batch.manifest.update(imported=len(records),duplicates=skipped,excluded=excluded)
        batch.save(update_fields=['status','imported_at','manifest'])
        # One permanent batch event plus original immutable workbook identifies
        # every imported row. No fake cash registrations or bank dates are made.
        audit(person,batch.pk,'batch_imported',after={'sha256':batch.sha256,'count':len(records),
            'skipped':skipped,'excluded':excluded,'transactions':[str(t.uid) for t in records]})
        return batch
