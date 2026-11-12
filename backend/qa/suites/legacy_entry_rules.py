"""Legacy endorsement/claim rules and Insured links (owner decisions 2026-11-12). Disposable MySQL only."""
import io, json, os, zipfile
from pathlib import Path
from xml.sax.saxutils import escape
exec(Path('/app/qa/suites/legacy_entries.py').read_text().replace("print(f'{len(checks)}/{len(checks)} passed')",'pass'))
from django.core.files.uploadedfile import SimpleUploadedFile
from masterdata.models import MasterRecord
from legacy.models import ImportBatch
from cases import storage
admin=clients['admin'];sales=clients['sales']
def detail(uid):return admin.get('/api/legacy?id='+uid).json()
def bad_save(t,data,name):
    code,r=send(sales,dict(id=t['uid'],version=t['version'],action='save',data=data))
    check(name,code==400,r);return r

# --- Sources ---
pol=make_source('RULE-REF',insured='Original insured',insuredCn='規則測試公司',effectiveDate='2025-01-01',expiryDate='2025-12-31',subAe='Entry admin',aePct=70)
e1=create(src=pol);check('endorsement draft carries the source split and Sub AE',e1['data']['subAe']=='Entry admin' and e1['data']['aePct']==70)
check('draft lists the locked fields',{'reference','party','cedant','currency','share','subAe','aePct','rule'}<=set(e1['lockedFields']),e1['lockedFields'])
bad_save(e1,{'subAe':'Entry sales'},'Sub AE follows the source')
bad_save(e1,{'aePct':40},'AE / Sub AE split follows the source')
e1=save(e1,dict(gross=1000,commissionRate=10,taxRate=1,brokerage=50,effectiveDate='2025-03-01',endorsementNo='R-E1',
                insured='Renamed insured',insuredCn='規則測試公司（更名）',expiryDate='2026-03-31'))
check('draft shows the projected automatic Revenue Month',e1.get('projectedRevenueMonth')==timezone.localdate().strftime('%Y-%m'),e1.get('projectedRevenueMonth'))
# A Sub AE carried over from the source is kept even after leaving (native rule); a new AE must be employed.
Personnel.objects.filter(name='Entry admin').update(is_active=False,deactivated_by='qa',deactivated_at=timezone.now())
bad=save(e1,{'ae':'Nobody Employed'});confirm(bad,400)
e1=save(bad,{'ae':'Entry sales'});e1=confirm(e1)
Personnel.objects.filter(name='Entry admin').update(is_active=True,deactivated_by=None,deactivated_at=None)
check('carried-over Sub AE and split kept on confirmation',e1['data']['subAe']=='Entry admin' and e1['data']['aePct']==70)
check('period change extends the policy (start fixed, 15 months)',e1['data']['expiryDate']=='2026-03-31')
claim_from_endorsement=send(sales,dict(referenceTransaction=e1['uid'],kind='claim'),method='POST')
check('claims are added only to an original premium row',claim_from_endorsement[0]==400,claim_from_endorsement)
e2=create(src=LegacyTransaction.objects.get(pk=e1['uid']))
check('an endorsement may follow another endorsement',e2['referenceTransaction']==e1['uid'])
e2=save(e2,dict(gross=-100,brokerage=-5,brokerageNote='Return of brokerage',effectiveDate='2025-02-01',endorsementNo='R-E2'));confirm(e2,400)   # before previous endorsement
e2=save(e2,dict(effectiveDate='2026-04-15'));confirm(e2,400)                                                  # outside the latest period
e2=save(e2,dict(effectiveDate='2026-03-01',expiryDate='2026-08-01'));confirm(e2,400)                          # over 18 months
e2=save(e2,dict(expiryDate='2026-03-31',endorsementNo='r-e1'));confirm(e2,400)                                # duplicate Endorsement No.
e2=save(e2,dict(endorsementNo='R-E2'));e2=confirm(e2)
check('endorsement inside the latest period after the previous one confirms',e2['status']=='confirmed')
cl=create('claim',src=pol)
check('claim takes the latest Insured from the newest endorsement',cl['data']['insured']=='Renamed insured' and cl['data']['insuredCn']=='規則測試公司（更名）',cl['data'])
check('claim DOL range follows the latest (extended) period',cl['data']['sourceExpiryDate']=='2026-03-31')
cl=save(cl,dict(lossNo='L-77',causeOfLoss='Fire',lossDate='2026-02-10',claim=1200));cl=confirm(cl)
check('claim DOL inside the extended period confirms',cl['status']=='confirmed')
cl2=create('claim',src=pol);cl2=save(cl2,dict(lossNo='l-77',lossDate='2026-02-10',claim=300));cl2=confirm(cl2)
group=detail(cl2['uid']).get('lossGroup') or {}
check('claim detail lists all claims with the same Loss No. and the total',len(group.get('rows',[]))==2 and group.get('total')==1500 and group.get('currency')=='TWD',group)
rows=admin.get('/api/accounting?view=list').json()['transactionRows']
check('Accounting shows the Loss No.',any(r.get('caseUid')==cl['uid'] and r.get('legacyLossNo')=='L-77' for r in rows))

# --- Facility days locked; ordinary days editable ---
fsrc=make_source('RULE-SW',party='Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)',rule='swiss',effectiveDate='2025-01-01',expiryDate='2025-12-31')
f=create(src=fsrc);bad_save(f,{'cedantDays':120},'Facility Cedant terms follow the rule')
o=create(src=pol);o=save(o,{'cedantDays':120,'reinsurerDays':45})
check('ordinary-rule terms are pre-filled and editable',o['data']['cedantDays']==120 and o['data']['reinsurerDays']==45)

# --- GL claim currency may change; Property may not ---
gl=make_source('RULE-GL',classOfBusiness='Commercial General Liability',classCode='GL',effectiveDate='2025-01-01',expiryDate='2025-12-31')
g=create('claim',src=gl);g=save(g,{'currency':'USD'})
check('a non-Property claim may use another currency',g['currency']=='USD')
g=save(g,dict(lossNo='GL-1',lossDate='2025-05-01',claim=10.5));g=confirm(g)
check('USD claim allows two decimals',g['data']['amounts']['claim']==10.5)

# --- Insured master links ---
existing=MasterRecord.objects.create(entity_type='insured',name='規則測試公司',payload={'aliases':[],'history':[]},created_by='qa',updated_by='qa')
link=create(src=pol);link=save(link,dict(gross=10,brokerage=1,commissionRate=0,taxRate=0,effectiveDate='2026-03-01',endorsementNo='R-LINK',insuredCn='規則測試公司'));link=confirm(link)
existing.refresh_from_db()
check('confirmation links the existing Insured master by Chinese name and marks it official',
      link['data'].get('insuredMasterId')==existing.pk and existing.payload.get('insuredAnnouncedAt'))
check('no duplicate Insured master created',MasterRecord.objects.filter(entity_type='insured',name='規則測試公司').count()==1)
renamed=MasterRecord.objects.filter(entity_type='insured',name='規則測試公司（更名）').first()
check('a new Chinese name creates an official Insured master',renamed and renamed.payload.get('insuredAnnouncedAt') and e1['data'].get('insuredMasterId')==renamed.pk)

# --- Import: Loss No., AE split, Share, Insured links ---
HEAD=['流水號','Insured (in English)','Insured (in Chinese)','Class','TW Ref. No.','Reinsurer','Cedant','Effective Date','Expiry Date','AE','Sub AE',
      'Currency','100%Premium','Share','Our Share Premium','R/I Comm.','Claim','Note for Claim','Tax','Bkg. (Original Currency)','Bkg. (in TWD)',
      'Re Dept. Bkg. (in TWD)','Net Premium from Cedant','Net Premium to Reinsurer','Revenue Month','Exchange Rate','New / Renew','Fac / Claim',
      'Receive Date','Pay Date','Endorsement No.','Issue Date of Claim','DOL','Full-closed']
FAC='Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)'
def xrow(serial,**kw):
    v={'流水號':serial,'Insured (in English)':'Imp '+serial,'Insured (in Chinese)':'匯入'+serial,'Class':'PD','TW Ref. No.':'TWIMP-'+serial,
       'Reinsurer':FAC,'Cedant':'QA Cedant','Effective Date':'46023','Expiry Date':'46388','AE':'Entry sales','Currency':'TWD',
       '100%Premium':'20000','Share':'0.5','Our Share Premium':'10000','R/I Comm.':'1500','Claim':'0','Tax':'100',
       'Bkg. (Original Currency)':'2000','Bkg. (in TWD)':'2000','Re Dept. Bkg. (in TWD)':'2000','Net Premium from Cedant':'8400',
       'Net Premium to Reinsurer':'6400','Revenue Month':'46081','Exchange Rate':'1','New / Renew':'New','Fac / Claim':'Fac',
       'Receive Date':'46100','Pay Date':'46110'}
    v.update(kw);return {k:x for k,x in v.items() if x is not None}
def workbook(rows):
    col=lambda i:(col(i//26-1) if i>=26 else '')+chr(65+i%26)
    cell=lambda ref,value:f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
    lines=[f'<row r="{n}">'+''.join(cell(col(i)+str(n),r[h]) for i,h in enumerate(HEAD) if h in r)+'</row>' for n,r in enumerate([dict(zip(HEAD,HEAD))]+rows,1)]
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main';out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('xl/workbook.xml',f'<?xml version="1.0"?><workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Facultative" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>'+''.join(lines)+'</sheetData></worksheet>')
    return out.getvalue()
keys=[]
def upload(rows):
    r=admin.post('/api/legacy/imports',{'file':SimpleUploadedFile('rules.xlsx',workbook(rows))});b=r.json()
    check('import preview accepted',r.status_code==201,b)
    keys.append(ImportBatch.objects.get(pk=b['id']).storage_key);return b
claim_cols=dict(**{'Fac / Claim':'Claim','Claim':'5000','Our Share Premium':'0','R/I Comm.':'0','Tax':'0','Bkg. (Original Currency)':'0',
    'Bkg. (in TWD)':'0','Re Dept. Bkg. (in TWD)':'0','Net Premium from Cedant':'-5000','Net Premium to Reinsurer':'-5000',
    'Issue Date of Claim':'46200','DOL':'46150','Share':None})
b=upload([xrow('IM1',**{'Sub AE':'Entry admin','Bkg. (in TWD)':'2000','Re Dept. Bkg. (in TWD)':'1399'}),
          xrow('IM2',**claim_cols,**{'Note for Claim':'Claim No: MCA0099'}),xrow('IM3',**claim_cols,**{'Note for Claim':'Recovery'}),
          xrow('IM4',**{'Endorsement No.':'E-IMP-1'})])
check('import preview passes (AE 69.95% -> 70, claims without Share)',not b['manifest']['errors'] and not b['manifest']['warnings'],b['manifest'])
check('import commits',admin.post('/api/legacy/imports',json.dumps(dict(action='commit',id=b['id'],sha256=b['sha256'])),content_type='application/json').status_code==200)
im={t.number:t for t in LegacyTransaction.objects.filter(batch_id=b['id'])}
check('import converts the AE / Sub AE amounts to the 70/30 split',im['IM1'].data['aePct']==70)
check('import splits Loss No. from Note for Claim and keeps the note',im['IM2'].data['lossNo']=='MCA0099' and im['IM2'].data['claimNote']=='Claim No: MCA0099' and im['IM3'].data['lossNo']=='')
check('import links official Insured masters',all(t.data.get('insuredMasterId') and MasterRecord.objects.get(pk=t.data['insuredMasterId']).payload.get('insuredAnnouncedAt') for t in im.values()))
dup=create(src=im['IM4']);dup=save(dup,dict(gross=10,brokerage=1,effectiveDate='2026-03-01',endorsementNo='e-imp-1'));confirm(dup,400)
check('Endorsement No. is unique including imported endorsements',True)
b=upload([xrow('IM5',**{'Sub AE':'Entry admin','Re Dept. Bkg. (in TWD)':'1000'})])
check('a split that is not 40/60 or 70/30 is a blocking warning',any('40/60 or 70/30' in w['message'] for w in b['manifest']['warnings']),b['manifest'])
b=upload([xrow('IM6',Share=None)])
check('a premium row without Share is an import error',any('Share is required' in e['message'] for e in b['manifest']['errors']),b['manifest'])
for key in keys:
    try:storage.delete(key)
    except Exception:pass
print(f'{len(checks)}/{len(checks)} passed legacy endorsement/claim rule checks')
