"""Property QS/XOL construction choices. Historical text is retained until confirmed."""
OPTIONS = ('A2 Class', 'A1 Class', 'B Class', 'C Class', 'D Class')
VERSION = 'property-construction-20261028-v1'
FIELDS = ('constructionSelections','constructionLegacyText','constructionLegacyConfirmed','constructionSelectionVersion')

def scope(p):
    return isinstance(p,dict) and str(p.get('classOfBusiness') or '').strip().casefold()=='property' and str(p.get('reinsuranceStructure') or '').upper() in ('QS','XOL','FACULTATIVE')

def legacy_text(p):
    if 'constructionLegacyText' in p:return str(p.get('constructionLegacyText') or '')
    raw=p.get('draftInput')
    original=raw if isinstance(raw,dict) and 'construction' in raw else p
    return str(original.get('construction') or '') if not isinstance(original.get('constructionSelections'),list) else ''

def adopt(p,source=None):
    if not scope(p):return p
    if not isinstance(p.get('constructionSelections'),list):
        p['constructionLegacyText']=legacy_text(source or p)
        p['constructionSelections']=[]
        p['constructionLegacyConfirmed']=not bool(p['constructionLegacyText'].strip())
    p['constructionSelectionVersion']=VERSION
    return p

def normalize(inp,value,errors,existing=None):
    if not scope(value):return
    raw=inp.get('constructionSelections',[])
    if not isinstance(raw,list):
        errors.append('Construction must be a list of available classes.');raw=[]
    if any(x not in OPTIONS for x in raw):errors.append('Construction must use A2 Class, A1 Class, B Class, C Class or D Class.')
    selected=[x for x in OPTIONS if x in raw]
    # The stored historical text cannot be discarded by an unrelated form save.
    old=legacy_text(existing) if scope(existing) else legacy_text(inp)
    if not scope(existing):old=old[:3000]
    confirmed=not old.strip() or inp.get('constructionLegacyConfirmed') is True
    value.update(constructionSelections=selected,constructionLegacyText=old,constructionLegacyConfirmed=confirmed,constructionSelectionVersion=VERSION)
    value['construction']='\n'.join(selected) if confirmed else old

def issues(p):
    if not scope(p):return []
    out=[];selected=p.get('constructionSelections')
    if not isinstance(selected,list) or not selected or any(x not in OPTIONS for x in selected):
        out.append({'field':'constructionSelections','label':'Construction — select at least one available class.'})
    if legacy_text(p).strip() and p.get('constructionLegacyConfirmed') is not True:
        out.append({'field':'constructionLegacyConfirmed','label':'Confirm the new Construction selections before replacing the historical text.'})
    return out
