"""Fill the owner-provided Standard Slip/Addendum packages without external tools."""
import copy
from datetime import date
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as E
from django.utils import timezone
from . import placing_rules as rules

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
def tag(k): return '{' + W + '}' + k
def text(n): return ''.join(x.text or '' for x in n.iter(tag('t')))

def put(node, value):
    """Keep cell/paragraph formatting; Word XML escapes all user-supplied text."""
    paragraphs = node.findall('w:p', NS)
    proto = copy.deepcopy(paragraphs[0]) if paragraphs else E.Element(tag('p'))
    rpr = next(iter(proto.findall('.//w:rPr', NS)), None)
    for child in list(node):
        if child.tag not in (tag('tcPr'), tag('pPr')): node.remove(child)
    lines = str(value if value is not None else '').split('\n')
    for line in lines:
        p = E.SubElement(node, tag('p')) if node.tag != tag('p') else node
        if node.tag != tag('p'):
            pp = proto.find('w:pPr', NS)
            if pp is not None: p.append(copy.deepcopy(pp))
        r = E.SubElement(p, tag('r'))
        if rpr is not None: r.append(copy.deepcopy(rpr))
        t = E.SubElement(r, tag('t')); t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve'); t.text = line

def money(value, currency):
    if value is None or value == '': return ''
    return f'{currency} {float(value):,.0f}' if currency == 'TWD' else f'{currency} {float(value):,.2f}'

def period(p):
    return f'From {p.get("policyFrom", "")} at {p.get("policyFromTime") or "12:00"} to {p.get("policyTo", "")} at {p.get("policyToTime") or "12:00"} Local Standard Time at the location of the Reinsured.'

def replace_rows(table, values, rename=None, remove=()):
    rename = rename or {}
    for row in list(table.findall('w:tr', NS)):
        cells = row.findall('w:tc', NS)
        label = text(cells[0]).strip() if cells else ''
        label = re.sub(r'\s+', ' ', label)
        if label in remove or (label in values and values[label] is None):
            table.remove(row); continue
        if label in rename: put(cells[0], rename[label])
        if label in values and len(cells) > 1: put(cells[-1], values[label])

def clause_lines(p):
    from masterdata.models import MasterRecord
    from .draft import UNIVERSAL_CLAUSES
    clauses = {x['code']: x for x in UNIVERSAL_CLAUSES}
    cls = MasterRecord.objects.filter(entity_type='class',name=p.get('classOfBusiness'),is_active=True).first()
    records = [cls] if cls else []
    names = [x.get('name') for x in rules.named(p) if not rules.is_facility(x.get('name'))]
    if names:
        records += list(MasterRecord.objects.filter(entity_type='reinsurer',name__in=names,is_active=True))
    for master in records:
        for row in (master.payload or {}).get('fixedClauses') or []:
            ids = row.get('classIds')
            if master.entity_type == 'reinsurer' and isinstance(ids,list) and (not cls or cls.pk not in [int(x) for x in ids if str(x).isdigit()]): continue
            clauses.setdefault(row.get('code'), row)
    if names:
        for row in p.get('manualClauses') or []:
            if isinstance(row,dict): clauses.setdefault(row.get('code'),row)
    intro = 'This Reinsurance is subject to the same terms and conditions as the Original Policy except as otherwise provided herein and Reinsurers will follow the Wordings, Clauses and Settlements of the Original Policy.'
    from .resolve import resolve_clause_titles
    resolved = resolve_clause_titles({**p, 'clauseDetails': copy.deepcopy(list(clauses.values()))})
    def clause_text(row):
        code=str(row.get('code') or '').strip()
        title=str(row.get('title') or '').strip()
        # MDM titles may already include the code; preserve the title verbatim once.
        if not code or title.casefold()==code.casefold() or title.casefold().startswith(code.casefold()+' '):return title
        return f'{code} {title}'.strip()
    return intro + '\n' + '\n'.join(clause_text(x) for x in resolved['clauseDetails'])

def original_conditions(value):
    tail = 'All other terms and conditions are subject to original policy wordings.'
    lines = [x.strip() for x in str(value or '').replace(tail,'').splitlines() if x.strip()]
    return '\n'.join(f'{i+1}. {x}' for i,x in enumerate(lines)) + '\n' + tail

def loss_text(p):
    rows=p.get('lossRecord') or []
    try:years=int(p.get('lossRecordYears'))
    except (TypeError,ValueError):years=5
    period_years=years if years>0 else 5
    count='Loss Clean' if not rows else f"{len(rows)} {'loss' if len(rows)==1 else 'losses'}"
    summary='Loss Clean since operation.' if years==0 and not rows and p.get('newOrRenew')=='New' and not p.get('renewedFromTwRef') else f"{count} in the past {period_years} {'year' if period_years==1 else 'years'}"
    def long_date(value):
        try:return date.fromisoformat(str(value)).strftime('%d %B %Y')
        except ValueError:return str(value or '')
    if p.get('lossAdvisedDate'):summary+=f" (as advised by TW Insurance Brokers Ltd. on {long_date(p['lossAdvisedDate'])})"
    details=[f"{long_date(r.get('date'))} | {r.get('cause', '')} | {money(r.get('lossPaid'),p.get('currency'))}" for r in rows]
    return '\n'.join([summary]+details+([p['lossRecordText']] if p.get('lossRecordText') else []))

def document_values(p, annual):
    is_cgl=rules.cgl(p); currency=p.get('currency') or ''
    address='\n'.join(' '.join(str(x.get(k) or '').strip() for k in ('address','postcode')).strip() for x in p.get('situations') or [] if str(x.get('address') or '').strip())
    opt=lambda key: str(p.get(key) or '').strip() or None
    values={
        'TYPE':p.get('type'), 'REINSURED':p.get('reinsured'), 'INSURED':p.get('originalInsured'),
        'ORIGINAL INSURED':p.get('originalInsured'),'PERIOD':period(p), 'LOCATION':address or None,
        'INTEREST':opt('interest') or (rules.INTEREST if is_cgl else ''),
        'LIMIT OF LIABILITY':money(p.get('limitOfLiability'),currency)+(' each occurrence' if is_cgl else ''),
        'AGGREGATE LIMIT':money(p.get('aggregateLimit'),currency) if p.get('aggregateLimit') else None,
        'SUB-LIMITS':opt('subLimits'),'DEDUCTIBLES':opt('deductibles'),
        'SELF-INSURED RETENTION':opt('selfInsuredRetention'),
        'REINSURED’S RETENTION':opt('reinsuredRetention') or rules.RETENTION,
        'REINSTATEMENT PROVISIONS':opt('reinstatementProvisions'),
        'INDEMNITY PERIOD':None if is_cgl else opt('indemnityPeriod'),
        'BASIS OF VALUATION':None if is_cgl else (p.get('basisOfValuationOther') if p.get('basisOfValuation')=='Other' else p.get('basisOfValuation')),
        'REINSURANCE CONDITIONS':clause_lines(p),'ORIGINAL CONDITIONS':original_conditions(p.get('originalConditions')),
        'LOSS PAYEE':None if is_cgl else opt('lossPayee'),'CO-REINSURANCE WARRANTY':opt('coReinsuranceWarranty'),
        'NOTICES':opt('notices'), 'EXPRESS WARRANTIES':opt('expressWarranties') or rules.NONE,
        'CONDITIONS PRECEDENT':opt('conditionsPrecedent') or rules.NONE, 'SUBJECTIVITIES':opt('subjectivities') or rules.NONE,
        '100% PREMIUM':'(Annual)' if annual else '', 'CEDING COMMISSION':'', 'TAX PAYABLE BY REINSURER':'',
        'ORDER HEREON':'', 'TOTAL DEDUCTIONS':'',
        'PREMIUM PAYMENT TERMS':'90 Days Payment Conditions - LSW3001 Premium Payment Clause',
    }
    return values

def insert_row(table, reference, label, value, after=None):
    row=copy.deepcopy(reference); cells=row.findall('w:tc',NS)
    put(cells[0],label);put(cells[-1],value)
    if after is None:table.append(row)
    else:table.insert(list(table).index(after)+1,row)
    return row

def render(p, ae_email, *, annual=True, previous=None, references=None):
    # Draft input can retain unfinished finance and surrounding whitespace. Render the
    # canonical risk fields after the risk-only gate; no Case values are written back.
    if not p.get('parentTwRef'):
        from .draft import normalize_draft
        p = normalize_draft(p, existing_premiums=p)['value']
    endorsement=bool(p.get('parentTwRef')); filename='placing-addendum.docx' if endorsement else 'placing-standard.docx'
    package=zipfile.ZipFile(Path(__file__).parent/'templates'/filename)
    xml=package.read('word/document.xml')
    namespace_defs = list(dict(re.findall(r'xmlns:([\w]+)="([^"]+)"',xml.decode())).items())
    for prefix,uri in namespace_defs:
        if not re.fullmatch(r'ns\d+',prefix):E.register_namespace(prefix,uri)
    root=E.fromstring(xml); body=root.find('w:body',NS)
    tables=body.findall('w:tbl',NS)
    now=timezone.localtime(); contact=f'{now:%d %B %Y}\nIn case of query please contact {p.get("ae", "")}\nEmail: {ae_email}'
    if endorsement:
        table=tables[0]; rows=table.findall('w:tr',NS)
        prototype=next(r for r in rows if len(r.findall('w:tc',NS))==2 and text(r.findall('w:tc',NS)[0])=='TYPE')
        for r in list(rows): table.remove(r)
        header=copy.deepcopy(rows[0]); cells=header.findall('w:tc',NS);put(cells[0],'');put(cells[-1],contact);table.append(header)
        ref=references or {}; heading=copy.deepcopy(rows[2]);put(heading.findall('w:tc',NS)[0],f'ADDENDUM NO. {ref.get("sequence", "")} TO COVER NOTE NO. {ref.get("root", "")}');table.append(heading)
        original=previous or p
        values={'TYPE':original.get('type'),'REINSURED':original.get('reinsured'),'ORIGINAL INSURED':original.get('originalInsured'),'PERIOD':period(original),'REFERENCE':ref.get('full',''),'EFFECTIVE DATE':p.get('endoEffectiveDate'),'ENDORSEMENT TYPE':', '.join(p.get('endoTypes') or []),'': 'It is hereby noted and agreed that\n'+str(p.get('endoText') or '')}
        for k,v in values.items():insert_row(table,prototype,k,v)
        if 'Period' in (p.get('endoTypes') or []):insert_row(table,prototype,'AMENDED PERIOD',period(p))
        if original.get('originalInsured')!=p.get('originalInsured'):insert_row(table,prototype,'AMENDED ORIGINAL INSURED',p.get('originalInsured'))
        for r in p.get('reinsurers') or []:insert_row(table,prototype,str(r.get('name') or 'Reinsurer')+' PREMIUM','')
        insert_row(table,prototype,'','All other terms and conditions remain unchanged.')
        for n in list(body):
            if n is not table and n.tag!=tag('sectPr'):body.remove(n)
    else:
        values=document_values(p,annual)
        risk=tables[0]
        first=risk.find('w:tr/w:tc',NS);put(first,'PLACING SLIP\n'+contact)
        remove=('RETROCEDENT','CONVEYANCE','VESSELS','ADDITIONAL COVERAGES','UNDERLYING LIMITS','SITUATION')
        rename={'INSURED':'ORIGINAL INSURED','LOCATION':'PRINCIPAL ADDRESS' if rules.cgl(p) else 'SITUATION'}
        if rules.cgl(p):rename['LIMIT OF LIABILITY']='LIMIT OF INDEMNITY'
        replace_rows(risk,values,rename,remove)
        proto=next(r for r in risk.findall('w:tr',NS) if text(r.findall('w:tc',NS)[0])=='INTEREST')
        if rules.cgl(p):
            coverage='\n'.join(str(p.get('coveragesOther') or '') if x=='Other' else x for x in p.get('coverages') or [])
            insert_row(risk,proto,'COVERAGES',coverage,after=proto)
        if p.get('originalExclusions'):insert_row(risk,proto,'ORIGINAL EXCLUSIONS',p['originalExclusions'])
        info=tables[1]; children=list(info); start=next(i for i,r in enumerate(children) if 'FOR Property Placement'==text(r)); split=next(i for i,r in enumerate(children) if text(r)=='FOR Commercial General Liability & Products Liability Placement')
        remove_rows=children[start:split] if rules.cgl(p) else children[split:]
        for r in remove_rows:info.remove(r)
        for r in list(info.findall('w:tr',NS)):
            if text(r).startswith('FOR '):info.remove(r)
        ci=p.get('cglInformation') or {}
        turnover='\n'.join(f'{r.get("regionOther") if r.get("region")=="Other" else r.get("region")} | {money(r.get("amount"),r.get("currency"))}' for r in ci.get('estimatedTurnover') or [])
        sums=[]
        for index,situation in enumerate(p.get('situations') or []):
            for r in p.get('sumInsured') or []:
                if r.get('locationIndex')==index:sums.append(f'Location {index+1} | {r.get("category", "")} | {money(r.get("amount"),p.get("currency"))}')
        sums += [f'{r.get("category", "")} | {money(r.get("amount"),p.get("currency"))}' for r in p.get('sumInsured') or [] if r.get('locationIndex') is None]
        sums.append('Total | '+money(sum(float(r.get('amount') or 0) for r in p.get('sumInsured') or []),p.get('currency')))
        iv={'OCCUPATION':p.get('occupation'),'CONSTRUCTION':p.get('construction'),'BREAKFOWN OF SUM INSURED':'\n'.join(sums),
            'LOSS RECORD':loss_text(p),'SPECIAL AGREEMENT':p.get('specialAgreement') or None,
            'POLICY FORM':ci.get('policyForm'),'RETROACTIVE DATE':ci.get('retroactiveDate') if ci.get('policyForm')=='Claims-Made Form' else None,
            'EXTENDED REPORTINGPERIOD':(ci.get('extendedReportingPeriod') if ci.get('extendedReportingApplies')=='applicable' else 'Not Applicable') if ci.get('policyForm')=='Claims-Made Form' else None,
            'TERRITORIAL/ JURISDICTION LIMITS':ci.get('territorialOther') if ci.get('territorialLimits')=='Other' else ci.get('territorialLimits'),
            'INSURED’S BUSINESS':rules.business_text(ci),'INSURED’S PRODUCTS':ci.get('insuredProducts'),'ESTIMATED TURNOVER':turnover,'INSURED’S WEBSITE':ci.get('insuredWebsite') or None}
        if rules.cgl(p) and ci.get('specialAgreementApplies')!='applicable':iv['SPECIAL AGREEMENT']=None
        replace_rows(info,iv,{'BREAKFOWN OF SUM INSURED':'BREAKDOWN OF SUM INSURED'})
        for table in tables[2:]:replace_rows(table,values)
        # Signing page always has empty Written/Signed Lines and current year.
        for n in tables[-2].iter(tag('t')):
            if n.text == '2021': n.text = str(now.year)
        for cell in tables[-1].findall('.//w:tc',NS):
            value=text(cell)
            if 'xx.xx%' in value:put(cell,value.replace('xx.xx%',''))
        # Template signing-page data table is filled separately.
        replace_rows(tables[-3],values)
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as dest:
        for name in package.namelist():
            data=E.tostring(root,encoding='utf-8',xml_declaration=True) if name=='word/document.xml' else package.read(name)
            if name == 'word/document.xml':
                extras = ''.join(f' xmlns:{prefix}="{uri}"' for prefix,uri in namespace_defs if ('xmlns:'+prefix+'=').encode() not in data)
                if extras: data = data.replace(b'<w:document', b'<w:document'+extras.encode(), 1)
            dest.writestr(name,data)
    return output.getvalue()
