"""Import an owner's reinsurer Register (XLSX) as standalone Legacy transactions.

2026-11-11 (owner decisions): System Administrators import through the web in two steps
(preview, then commit with the reviewed SHA256). Any error or warning blocks the commit.
PD and GL rows are accepted. Settled and unsettled rows are both imported:
- a cash leg is settled when its Register receipt/payment number is filled
  (Cedant Receipt No / Cedant Payment No for the Cedant leg; Reinsurer Receipt No /
  Reinsurer Payment No. for the reinsurer leg); its number becomes the Accounting Dept. Ref.
  of a receipt/payment registration dated Receive Date (receipts) or Pay Date (payments);
- rows whose cash legs are all settled stay read-only historical rows;
- rows with an unsettled leg become trackable Accounting balances with the native payment
  rules; their settled legs are marked as reconciled before import.
Imported rows never create Cases or Production rows. No row is ever changed after import.
"""
import copy
import hashlib
import json
import re
import uuid
from pathlib import Path
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from cases import storage
from coordination.services import serialized, PRODUCTION_SOURCES
from .excel import read_workbook, date_value, label
from .money import number, rounded
from .models import ImportBatch, LegacyTransaction, LegacyAudit
from .services import fail, audit
from .ledger import detect_rule

APPROVED_EXCLUSIONS=json.loads(Path(__file__).with_name('import_exclusions.json').read_text(encoding='utf-8'))
APPROVED_CORRECTIONS=json.loads(Path(__file__).with_name('import_corrections.json').read_text(encoding='utf-8'))
CLASSES={'PD':'Property','GL':'Commercial General Liability'}
CURRENCIES=('TWD','USD','MYR','EUR','JPY','GBP','HKD')
SETTLEMENT_COLUMNS={'cedant':('Cedant Receipt No','Cedant Payment No'),
                    'reinsurer':('Reinsurer Receipt No','Reinsurer Payment No.')}
IMPORT_NOTE='Settled before import (Register receipt/payment number).'


def excluded_row(row):
    serial=label(row['values'].get('流水號'))
    if serial in APPROVED_EXCLUSIONS or serial in getattr(settings,'LEGACY_IMPORT_EXCLUDED_SERIALS',()):
        return dict(row=row['row'],serial=serial,reason=APPROVED_EXCLUSIONS.get(serial,'Excluded by owner instruction; do not import.'))
    return None


def corrected_values(row):
    """Owner-approved corrections fill named cells; the stored original keeps the Register values."""
    serial=label(row['values'].get('流水號'))
    fix=APPROVED_CORRECTIONS.get(serial)
    if not fix:return row['values'],None
    values=dict(row['values'])
    changed={k:dict(before=values.get(k,''),after=v) for k,v in fix['values'].items() if label(values.get(k))!=label(v)}
    values.update(fix['values'])
    return values,(dict(row=row['row'],serial=serial,changes=changed,reason=fix.get('reason','')) if changed else None)


def _month_end(iso):
    import calendar
    y,m=int(iso[:4]),int(iso[5:7])
    return f'{y:04d}-{m:02d}-{calendar.monthrange(y,m)[1]:02d}'


RATE_FORMULA=re.compile(r'^=?\s*(?:ROUND\(\s*)?\$?[A-Z]{1,3}\$?\d+\s*\*\s*([0-9]*\.?[0-9]+)\s*(?:,\s*-?\d+\s*\))?\s*$',re.I)


def _rate(row,column,amount,premium,currency):
    """R/I Comm. % / Tax % (owner 2026-11-11): the constant of a simple Register formula
    (Our Share Premium x rate, never evaluated), else amount / premium. Returns (rate, source, ok)."""
    text=(row.get('formulas') or {}).get(column)
    if text:
        m=RATE_FORMULA.match(text.strip())
        if not m:return None,'formula',False
        rate=round(float(m.group(1))*100,6);source='formula'
    elif premium:
        rate=round(amount/premium*100,6);source='amount'
    else:
        return (0.0,'amount',True) if not amount else (None,'amount',False)
    tolerance=0.5 if currency=='TWD' else 0.005
    return rate,source,abs(premium*rate/100-amount)<=tolerance+1e-9


LOSS_NOTE=re.compile(r'^\s*(?:claim|loss)\s*no\.?\s*[:：]?\s*(\S.*)$',re.I)


def _refs(v,side):
    return ' / '.join(x for x in (label(v.get(c)) for c in SETTLEMENT_COLUMNS[side]) if x and x.upper()!='N/A')


def _date(v,key):
    value=date_value(v.get(key))
    return value if len(value)==10 and value[4]=='-' else ''


def converted(row, rule_cache):
    values,_=corrected_values(row)
    v=values; notes=[]
    def money(key, required=True):
        value=v.get(key)
        if value in (None,'') and not required:
            return None
        return number(value,key)
    serial=label(v.get('流水號')); reference=label(v.get('TW Ref. No.'))
    if row['errors']:raise ValueError('Formula errors or formulas without cached results: '+', '.join(row['errors']))
    if not serial or len(serial)>80 or not reference or len(reference)>192:
        raise ValueError('A valid original serial and old reference are required.')
    code=label(v.get('Class')).upper()
    if code not in CLASSES:raise ValueError('Class must be PD or GL.')
    if v.get('Fac / Claim') not in ('Fac','Claim'):raise ValueError('Fac / Claim must be Fac or Claim.')
    currency=label(v.get('Currency')).upper()
    if currency not in CURRENCIES:raise ValueError('Unsupported currency.')
    party=label(v.get('Reinsurer'));cedant=label(v.get('Cedant'))
    if not party or not cedant:raise ValueError('Cedant and reinsurance settlement party are required.')
    insured=v.get('Description') or v.get('Insured (in English)','')
    if not label(insured):raise ValueError('Insured (in English) is required.')
    effective=_date(v,'Effective Date');expiry=_date(v,'Expiry Date')
    if not effective or not expiry:raise ValueError('Effective Date and Expiry Date must be dates.')
    if party not in rule_cache:rule_cache[party]=detect_rule(party)
    claim=v.get('Fac / Claim')=='Claim'
    data=dict(reference=reference,currency=currency,party=party,cedant=cedant,
        classOfBusiness=CLASSES[code],classCode=code,
        insured=insured,insuredCn=v.get('Insured (in Chinese)',''),
        effectiveDate=effective,expiryDate=expiry,
        revenueMonth=date_value(v.get('Revenue Month'))[:7] if _date(v,'Revenue Month') else '',
        ae=v.get('AE',''),subAe=v.get('Sub AE',''),
        statementNo=str(v.get("Cedant's Policy No.",'') or ''),policyNo='',reinsurerRef=str(v.get("Reinsurer's Ref. No.",'') or ''),
        gross=money('100%Premium',False),share=None if v.get('Share') in (None,'') else money('Share')*100,
        brokerageNote=v.get('Note for Bkg.',''),claimNote=v.get('Note for Claim',''),remark=v.get('Remark',''),
        kind='claim' if claim else 'endorsement' if v.get('Endorsement No.') else 'premium',
        rule=rule_cache[party],cedantDays=90,reinsurerDays=90,newRenew=v.get('New / Renew',''),
        endorsementNo=str(v.get('Endorsement No.','') or ''),installmentNo=str(v.get('Installment No.','') or ''))
    data.update(claimIssueDate=_date(v,'Issue Date of Claim'),lossDate=_date(v,'DOL'),
        receiveReminder=_date(v,'Receive Date'),payReminder=_date(v,'Pay Date'),declaration=v.get('Declaration',''),
        accountingReferences={key:str(v.get(key) or '') for key in (
            'Cedant Receipt No','Cedant Payment No','Reinsurer Receipt No','Reinsurer Payment No.')},
        importSettlement={side:_refs(v,side) for side in SETTLEMENT_COLUMNS})
    if claim and not data['lossDate']:notes.append('Claim without DOL.')
    a=dict(premium=money('Our Share Premium'),commission=money('R/I Comm.'),tax=money('Tax'),
        claim=money('Claim',False) or 0,brokerage=money('Bkg. (Original Currency)'),
        cedantNet=money('Net Premium from Cedant'),reinsurerNet=money('Net Premium to Reinsurer'),
        brokeragePct=money('Bkg.(%)',False))
    if a['brokeragePct'] is not None:a['brokeragePct']*=100
    data['amounts']=a;data['brokerage']=a['brokerage'];data['claim']=a['claim']
    if not claim:
        sources={}
        for key,column,amount in (('commissionRate','R/I Comm.',a['commission']),('taxRate','Tax',a['tax'])):
            rate,source,ok=_rate(row,column,amount,a['premium'],currency)
            if not ok:notes.append(f'{column} does not equal Our Share Premium x a fixed rate; check the Register formula.')
            data[key]=rate;sources[key]=source
        data['rateSource']=sources
    rate=money('Exchange Rate');total=money('Bkg. (in TWD)');ae=money('Re Dept. Bkg. (in TWD)')
    premium_twd=rounded(a['premium']*rate,'TWD')
    people=[dict(name=data['ae'],income=ae,premium=premium_twd,incomeOriginal=None,pct=None)]
    if data['subAe']:
        residual=Decimal(str(v['Bkg. (in TWD)']))-Decimal(str(v['Re Dept. Bkg. (in TWD)']))
        people.append(dict(name=data['subAe'],income=float(residual),premium=0,incomeOriginal=None,pct=None))
    snapshot=dict(rate=rate,incomeTwd=total,premiumTwd=premium_twd,awaitingFx=False,people=people,
        historicalPreserved=True,aeIncomeTwd=ae,subAeIncomeTwd=people[1]['income'] if data['subAe'] else 0)
    # Owner 2026-11-12: Share is required on premium/endorsement rows (endorsements lock the source Share).
    if not claim and data.get('share') is None:raise ValueError('Share is required for premium and endorsement rows.')
    if data.get('gross') is None:notes.append('Missing gross; stored historical amounts preserved.')
    # AE / Sub AE split: imported amounts are converted to the 40/60 or 70/30 split (within 1%).
    data['aePct']=100
    if data['subAe']:
        pct=float(Decimal(str(v['Re Dept. Bkg. (in TWD)']))/Decimal(str(v['Bkg. (in TWD)']))*100) if float(v.get('Bkg. (in TWD)') or 0) else None
        match=next((p for p in (40,70) if pct is not None and abs(pct-p)<=1),None)
        if match is None:notes.append('AE / Sub AE brokerage split is not 40/60 or 70/30.')
        data['aePct']=match
    # Loss No. from Note for Claim ("Claim No: x" / "Loss No: x"); the note itself is kept.
    m=LOSS_NOTE.match(str(data.get('claimNote') or ''))
    data['lossNo']=m.group(1).strip()[:160] if (claim and m) else ''
    if not data['rule']:notes.append('Payment rule awaiting confirmation for future entries.')
    # Cash legs (claims reverse the parties): settled when the Register number is filled.
    # Settlement dates: premium rows use Receive Date / Pay Date; claim rows (whose Register
    # dates read "Claim") use the last day of Closed Month (owner 2026-11-11).
    legs=[('reinsurer',-a['reinsurerNet']),('cedant',-a['cedantNet'])] if claim else [('cedant',a['cedantNet']),('reinsurer',a['reinsurerNet'])]
    closed=_date(v,'Closed Month')
    data['closedMonthEnd']=_month_end(closed) if closed else ''
    for side,value in legs:
        if not value or not data['importSettlement'][side]:continue
        if claim:
            if not data['closedMonthEnd']:raise ValueError('Closed Month is required for a settled claim account.')
            continue
        receipt=value>0
        if not data['receiveReminder' if receipt else 'payReminder']:
            raise ValueError(('Receive Date' if receipt else 'Pay Date')+' is required for a settled '+side+' account.')
    historical=all(not value or data['importSettlement'][side] for side,value in legs)
    if claim and not historical and not data['claimIssueDate']:
        notes.append('Issue Date of Claim is required for an unsettled claim (its due date is Issue Date of Claim + 15 days).')
    return dict(original_serial=serial,number=serial,reference=reference,currency=currency,
        revenue_month=data['revenueMonth'],data=data,fx_snapshot=snapshot,historical=historical),notes


def _manifest_row(item):
    d=item['data'];a=d['amounts']
    return dict(serial=item['number'],classCode=d['classCode'],kind=d['kind'],currency=item['currency'],
        settled=item['historical'],cedantSettled=bool(d['importSettlement']['cedant']),
        reinsurerSettled=bool(d['importSettlement']['reinsurer']))


def scan(content):
    """Read and convert every row without writing anything (used by preview and commit)."""
    parsed=read_workbook(content);rules={};errors=[];warnings=[];seen=set();duplicates=[];items=[]
    existing=set(LegacyTransaction.objects.filter(original_serial__isnull=False).values_list('original_serial',flat=True))
    totals={};excluded=[];corrections=[];classes={};settled=dict(fully=0,open=0)
    for row in parsed['rows']:
        omission=excluded_row(row)
        if omission:
            excluded.append(omission);continue
        serial=label(row['values'].get('流水號'))
        if serial in seen or serial in existing:
            duplicates.append(dict(row=row['row'],serial=serial));continue
        seen.add(serial)
        _,fix=corrected_values(row)
        if fix:corrections.append(fix)
        try:item,notes=converted(row,rules)
        except ValueError as exc:
            errors.append(dict(row=row['row'],serial=serial,message=str(exc)));continue
        items.append((row,item))
        warnings.extend(dict(row=row['row'],serial=serial,message=n) for n in notes)
        bucket=totals.setdefault(item['currency'],dict(count=0,cedantNet=0,reinsurerNet=0,brokerage=0))
        bucket['count']+=1
        for key in ('cedantNet','reinsurerNet','brokerage'):bucket[key]+=item['data']['amounts'][key]
        code=item['data']['classCode'];classes[code]=classes.get(code,0)+1
        settled['fully' if item['historical'] else 'open']+=1
    manifest=dict(sourceRows=len(parsed['rows']),eligible=len(items),duplicates=duplicates,errors=errors,warnings=warnings,
        totals=totals,excluded=excluded,corrections=corrections,classes=classes,settlement=settled,
        openRows=[_manifest_row(item) for _,item in items if not item['historical']],
        commentPolicy='not_imported',sourceSha256=parsed['sha256'])
    return parsed,items,manifest


def _admin(person):
    if person.role_code!='admin':fail('Only System Administrators may import.',403)


def preview(person, filename, content):
    _admin(person)
    try:parsed,_,manifest=scan(content)
    except ValueError as exc:fail(str(exc))
    with serialized(PRODUCTION_SOURCES):
        bid=uuid.uuid4();key=f'legacy-imports/{bid}/original.xlsx'
        storage.put(key,content)
        batch=ImportBatch.objects.create(id=bid,filename=str(filename or 'register.xlsx')[:255],sha256=parsed['sha256'],storage_key=key,
            manifest=manifest,created_by=f'personnel:{person.pk}' if person.pk is not None else 'system:owner-authorized-deployment')
        audit(person,batch.pk,'import_preview',after={'sha256':batch.sha256,**{k:v for k,v in manifest.items() if k!='openRows'}})
    return batch


def _settle_imported(t,stamp,actor,batch_id):
    """Zero legs settle like new entries; Register-settled legs get one receipt/payment each."""
    from .ledger import payload_for,details
    from cases.property_original import persist_settlements
    payload=payload_for(t)
    if not t.historical:
        persist_settlements(payload,stamp,actor)
    d=t.data;claim=d.get('kind')=='claim'
    current=details(payload)
    for no,item in current.items():
        if item['cashTracking']!='cash' or not item['amount']:continue
        side='cedant' if item['partyType']=='cedant' else 'reinsurer'
        ref=d['importSettlement'].get(side)
        if not ref:continue
        receipt=item['paymentDirection']=='receivable'
        payload.setdefault('paymentEntries',[]).append({
            'id':str(uuid.uuid4()),'entryType':'payment','transactionNo':no,
            'scheduleKey':(item['cashParts'][0]['scheduleKey'] if item['cashParts'] else 'single:'+('cedant' if side=='cedant' else 'r1')),
            'partyType':item['partyType'],'partyName':item['partyName'],'paymentDirection':item['paymentDirection'],
            'currency':t.currency,'amount':item['amount'],'nonCash':False,'entryKind':'legacy-import',
            'batchId':f'legacy-import:{t.uid}:{no}','importBatchId':str(batch_id),
            'paymentDate':d['closedMonthEnd'] if claim else d['receiveReminder' if receipt else 'payReminder'],'reference':ref[:200],'note':IMPORT_NOTE,
            'createdAt':stamp,'createdBy':actor['id'],'createdByName':actor['name']})
    keys=('paymentEntries','financeClaimTracking','swissAccounting','transactions')
    t.financial={key:copy.deepcopy(payload.get(key,{} if key=='swissAccounting' else [])) for key in keys}
    if t.historical:  # historical rows are always shown settled; keep only the display receipts
        t.financial={'paymentEntries':t.financial['paymentEntries']}


def commit(person,batch_id,sha256):
    _admin(person)
    with serialized(PRODUCTION_SOURCES):
        try:batch=ImportBatch.objects.select_for_update().get(pk=batch_id)
        except (ImportBatch.DoesNotExist,ValueError,ValidationError):fail('Import batch not found.',404)
        if batch.status!='preview':fail('This batch is not awaiting import.',409)
        if batch.sha256!=sha256:fail('Review the current preview before importing.',409)
        if batch.manifest.get('errors'):fail('Resolve the preview errors before importing.',409)
        if batch.manifest.get('warnings'):fail('Resolve the preview warnings before importing.',409)
        if not batch.manifest.get('eligible'):fail('This preview has no new transactions to import.',409)
        with storage.open_read(batch.storage_key) as f:content=f.read()
        if hashlib.sha256(content).hexdigest()!=batch.sha256:fail('The stored source workbook changed.',409)
        try:parsed,items,manifest=scan(content)
        except ValueError as exc:fail(str(exc))
        if manifest['errors'] or manifest['warnings']:fail('The workbook no longer passes the preview checks. Create a new preview.',409)
        if manifest['excluded']!=batch.manifest.get('excluded',[]) or manifest['corrections']!=batch.manifest.get('corrections',[]):
            fail('Import exclusions or corrections changed. Create and review a new preview before importing.',409)
        if manifest['eligible']!=batch.manifest.get('eligible'):
            fail('Other transactions were imported since this preview. Create and review a new preview.',409)
        now=timezone.now();stamp=now.isoformat()
        actor={'id':f'personnel:{person.pk}' if person.pk is not None else 'system','name':person.name}
        records=[]
        for row,item in items:
            item=copy.deepcopy(item);item['data']['confirmedAt']=stamp
            t=LegacyTransaction(uid=uuid.uuid4(),**item,status='confirmed',batch=batch,
                original=row['values'],owner_id=person.pk,created_by_id=person.pk,first_confirmed_at=now)
            try:_settle_imported(t,stamp,actor,batch.pk)
            except (ValueError,OverflowError) as exc:fail(f'Row {row["row"]} ({t.number}): {exc}')
            # Owner 2026-11-12: link the Chinese-name Insured master (same matching as Case); official.
            from .policy import link_insured
            master=link_insured(t.data.get('insuredCn'),actor,str(t.uid))
            if master:t.data['insuredMasterId']=master
            records.append(t)
        LegacyTransaction.objects.bulk_create(records,batch_size=250)
        batch.status='imported';batch.imported_at=now
        batch.manifest.update(imported=len(records),historical=sum(t.historical for t in records),
            open=sum(not t.historical for t in records))
        batch.save(update_fields=['status','imported_at','manifest'])
        # One permanent batch event plus the original immutable workbook identifies every row.
        audit(person,batch.pk,'batch_imported',after={'sha256':batch.sha256,'count':len(records),
            'excluded':manifest['excluded'],'corrections':manifest['corrections'],
            'transactions':[str(t.uid) for t in records]})
        return batch
