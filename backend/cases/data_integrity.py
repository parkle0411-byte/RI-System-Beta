"""Recognize unreadable financial inputs without changing the stored payload.

Missing fields and blank draft values are incomplete, not corrupted. Formal
underwriting requirements remain in draft.py. This boundary never repairs data.
"""
import math
import re
from .calc.jsnum import js_trim

NUMBER=re.compile(r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$')
# Calendar/underwriting requirements retain their existing, field-specific gates.
NUMBERS=('originalPremium','riCommPct','taxPct')
ROWS={'reinsurers':('sharePct','premium','riCommPct','taxPct'),
      'performanceInstallments':('premium','ratio')}

def numeric(value):
    if value is None or isinstance(value,str) and not js_trim(value):return True
    if isinstance(value,bool) or not isinstance(value,(int,float,str)):return False
    if isinstance(value,str):
        value=js_trim(value).replace(',','')
        if not NUMBER.fullmatch(value):return False
    try:return math.isfinite(float(value))
    except (TypeError,ValueError,OverflowError):return False

def financial_issues(payload):
    if payload is None:return []
    if not isinstance(payload,dict):return [{'field':'case','label':'Case data has an invalid format.'}]
    issues=[]
    def add(field):issues.append({'field':field,'label':field+': invalid financial data. Correct the saved data before continuing.'})
    def numbers(row,keys,prefix=''):
        for key in keys:
            value=row.get(key)
            if not numeric(value):add(prefix+key)
            elif key in ('sharePct','riCommPct','taxPct','ratio') and value is not None and not (isinstance(value,str) and not js_trim(value)):
                if not 0<=float(js_trim(str(value)).replace(',',''))<=100:add(prefix+key)
    numbers(payload,NUMBERS)
    for key,keys in ROWS.items():
        value=payload.get(key)
        if value is None:continue
        if not isinstance(value,list):add(key);continue
        for i,row in enumerate(value):
            field=f'{key}.{i}'
            if not isinstance(row,dict):add(field);continue
            numbers(row,keys,field+'.')
            if key=='reinsurers' and row.get('name') is not None and not isinstance(row['name'],str):add(field+'.name')
    return issues

def require_readable(payload):
    issues=financial_issues(payload)
    if issues:raise ValueError('Case financial data is invalid; amounts are pending confirmation.')

def response_error(payload,status=409):
    issues=financial_issues(payload)
    if not issues:return None
    from rest_framework.response import Response
    return Response({'error':'case_data_invalid','message':'Case data is invalid. Amounts are pending confirmation. Correct the saved data before continuing.','issues':issues},status=status)
