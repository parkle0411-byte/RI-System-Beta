"""結果快取（ri_system/result_cache.py）：Dashboard 與 Production Report 的 GET。
核心要求：任何變更之後，「有快取」的回應都必須等於「不用快取重新計算」的回應；快取沒有命中就不算數的測試，所以也驗證確實有命中。
只在拋棄式 QA 資料庫執行；所有變更在交易內回滾。"""
import copy, json, os, time as real_time
from datetime import datetime, timedelta, timezone as tz
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.utils import timezone
import dashboard.views as dashboard_views
from cases.models import Case
from fxrates.models import FxRate
from personnel.models import Personnel
from production.models import ProductionExclusion
from ri_system import result_cache
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
settings.RESULT_CACHE_ENABLED = True       # 其他測試組預設關閉快取（它們會用 update() 直接改資料）
settings.RESULT_CACHE_TTL_SECONDS = 60
checks = []
def check(name, condition):
    assert condition, name
    checks.append(name); print('PASS ' + name)
User = get_user_model()
def client(tag, role, dept):
    u = User.objects.create_user(username='zz.rc.' + tag, password='Rc-QA-Password-9!')
    p = Personnel.objects.create(name='ZZ RC ' + tag, department=dept, role_code=role, auth_user_id=str(u.pk), account_status='active', created_by='qa', updated_by='qa')
    c = Client(HTTP_HOST='localhost'); c.force_login(u); return c, p
def post(c, url, body): return c.post(url, data=json.dumps(body), content_type='application/json')
DASH, PRD, MONTH = '/api/dashboard', '/api/production-report?month=2031-05', '2031-05'
def fresh(c, url):
    settings.RESULT_CACHE_ENABLED = False
    try: return c.get(url).json()
    finally: settings.RESULT_CACHE_ENABLED = True
def cached(c, url): return c.get(url).json()
def same_as_fresh(c, url): return cached(c, url) == fresh(c, url)
def hits(): return result_cache.stats['hits']
def body(**over):
    b = dict(reinsuranceStructure='QS', ae='ZZ AE', currency='TWD', classOfBusiness='ZZ Class', classCode='PAR', newOrRenew='New', typePrefix='ZZ Type',
             reinsured='ZZ RC Cedant', originalInsured='ZZ RC Insured', policyFrom='2031-05-01', policyTo='2032-05-01', interest='Buildings',
             situations=[dict(address='1 ZZ Road', postcode='100')],
             reinsurers=[dict(name='ZZ Re A', sharePct=60, premium=600, riCommPct=5, taxPct=0), dict(name='ZZ Re B (Facility)', sharePct=40, premium=400, riCommPct=5, taxPct=0)],
             limitOfLiability=1000000, deductibles='10%', originalConditions='As original', occupation='Office', construction='Concrete',
             sumInsured=[dict(category='Building', amount=1000000)], lossAdvisedDate='2031-04-01', lossRecordYears=5,
             originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b
_ref = [0]
def make(admin, status='posted', **over):
    r = post(admin, '/api/cases', {'case': body(**over)}); assert r.status_code == 201, r.content
    case = Case.objects.get(case_uid=r.json()['case']['caseUid'])
    if status != 'draft':
        _ref[0] += 1
        Case.objects.filter(pk=case.pk).update(status=status, tw_ref=f'ZZ-RC-{_ref[0]:04d}', announced_at=timezone.now(), row_version=2)
    case.refresh_from_db(); return case
def app_write(case, **fields):
    """和系統一樣的寫入：改內容、版本號加一、save()（更新時間自動更新）。"""
    c = Case.objects.get(pk=case.pk); p = copy.deepcopy(c.payload); p.update(fields)
    c.payload = p; c.row_version += 1; c.save(); return c
class Rollback(Exception): pass
try:
    with transaction.atomic():
        result_cache.clear()
        admin, _ = client('admin', 'admin', 'admin')
        viewer, viewer_p = client('viewer', 'viewer', 'business_1')
        c1, c2 = make(admin, originalInsured='ZZ RC One'), make(admin, originalInsured='ZZ RC Two', currency='USD')
        FxRate.objects.create(year_month=MONTH, currency='USD', rate='30', created_by='qa', updated_by='qa')

        # ------------------------------------------------ Dashboard
        h = hits(); first = cached(admin, DASH); second = cached(admin, DASH)
        check('Dashboard: the second identical request is a cache hit with the same body', hits() == h + 1 and first == second)
        check('Dashboard: a cached body equals a fresh recomputation', same_as_fresh(admin, DASH))
        before = cached(admin, DASH)
        c3 = make(admin, originalInsured='ZZ RC Three')
        after = cached(admin, DASH)
        check('Dashboard: a new case changes the dashboard immediately', after != before and after == fresh(admin, DASH))
        before = after; c1 = app_write(c1, originalPremium=5000)
        after = cached(admin, DASH)
        check('Dashboard: editing a case (version bump) changes the dashboard immediately', after != before and after == fresh(admin, DASH))
        before = after; Case.objects.filter(pk=c3.pk).update(is_archived=True, archived_at=timezone.now(), archived_by='qa', row_version=3); after = cached(admin, DASH)
        check('Dashboard: archiving a case changes the dashboard immediately', after != before and after == fresh(admin, DASH))
        draft = make(admin, status='draft', originalInsured='ZZ RC Draft'); cached(admin, DASH)
        before = cached(admin, DASH); Case.objects.filter(pk=draft.pk).update(recycled_at=timezone.now(), recycled_by='qa', row_version=3); after = cached(admin, DASH)
        check('Dashboard: recycling a draft changes the dashboard immediately', after != before and after == fresh(admin, DASH))
        before = after
        r = post(admin, '/api/dashboard-targets', {'periodType': 'annual', 'periodKey': str(datetime.now(ZoneInfo('Asia/Taipei')).year), 'amount': 123456})
        after = cached(admin, DASH)
        check('Dashboard: a new target (through the API) shows immediately', r.status_code == 201 and after != before and after == fresh(admin, DASH))
        before = after
        fx = FxRate.objects.get(year_month=MONTH, currency='USD'); fx.rate = '31'; fx.row_version += 1; fx.save()
        check('Dashboard: an FX rate change is picked up (and equals a fresh recomputation)', cached(admin, DASH) == fresh(admin, DASH))

        # 草稿存檔不影響 Dashboard 數字，不該讓快取失效；草稿的新增與回收仍會改變「進行中報價」件數
        d1 = make(admin, status='draft', originalInsured='ZZ RC Draft Two'); cached(admin, DASH)
        h = hits(); d1 = app_write(d1, originalPremium=4321); same = cached(admin, DASH)
        check('Dashboard: saving a draft does not invalidate the cache (still a hit, still equal to a fresh recomputation)', hits() == h + 1 and same == fresh(admin, DASH))
        before = cached(admin, DASH); d2 = make(admin, status='draft', originalInsured='ZZ RC Draft Three'); after = cached(admin, DASH)
        check('Dashboard: a new draft changes the open-quotes count immediately', after['metrics']['openQuotes'] == before['metrics']['openQuotes'] + 1 and after == fresh(admin, DASH))
        Case.objects.filter(pk=d2.pk).update(status='posted', tw_ref='ZZ-RC-DRAFT2', announced_at=timezone.now(), row_version=3)
        after2 = cached(admin, DASH)
        check('Dashboard: announcing a draft (it leaves the draft group) changes the dashboard immediately', after2['metrics']['openQuotes'] == before['metrics']['openQuotes'] and after2 == fresh(admin, DASH))
        # 不同使用者的範圍不能互相污染
        admin_view, viewer_view = cached(admin, DASH), cached(viewer, DASH)
        check('Dashboard: a user without read-all gets their own scope, not the cached all-cases body',
              viewer_view == fresh(viewer, DASH) and viewer_view != admin_view and cached(admin, DASH) == admin_view)
        Case.objects.filter(pk=c1.pk).update(owner_personnel=viewer_p, row_version=9)
        check('Dashboard: ownership change is reflected for the restricted user', cached(viewer, DASH) == fresh(viewer, DASH) and cached(viewer, DASH) != viewer_view)

        # 跨日、中午 12:00 前後各自獨立
        tpe = ZoneInfo('Asia/Taipei')
        for label, when in (('next month', datetime(2031, 6, 3, 9, 0, tzinfo=tpe)), ('same day 11:00', datetime(2031, 5, 20, 11, 0, tzinfo=tpe)), ('same day 13:00', datetime(2031, 5, 20, 13, 0, tzinfo=tpe))):
            with mock.patch.object(dashboard_views, '_now', lambda w=when: w.astimezone(tz.utc)):
                a = cached(admin, DASH); b = cached(admin, DASH)
                check(f'Dashboard: {label} is computed for that date and then served from cache', a == b == fresh(admin, DASH))
        with mock.patch.object(dashboard_views, '_now', lambda: datetime(2031, 6, 3, 9, 0, tzinfo=tpe).astimezone(tz.utc)):
            june = cached(admin, DASH)
        check('Dashboard: a different month never reuses the previous month\'s cached body', june['period']['currentMonth'] == '2031-06' and cached(admin, DASH)['period']['currentMonth'] != '2031-06')

        # 繞過系統的直接資料庫修改：版本號沒變，靠保險上限在 60 秒內補上
        warm = cached(admin, DASH)
        p = copy.deepcopy(Case.objects.get(pk=c1.pk).payload); p['originalPremium'] = 99999
        Case.objects.filter(pk=c1.pk).update(payload=p)       # 沒有版本號、沒有更新時間
        stale = cached(admin, DASH)
        check('Dashboard: a write that bypasses the application is not seen immediately (documented limit)', stale == warm)
        late = SimpleNamespace(monotonic=lambda: real_time.monotonic() + 61)
        with mock.patch.object(result_cache, 'time', late):
            check('Dashboard: ...but is picked up after the safety limit (60 s)', cached(admin, DASH) != warm)

        # ------------------------------------------------ Production Report
        h = hits(); first = cached(admin, PRD); second = cached(admin, PRD)
        check('Production: the second identical request is a cache hit with the same body', hits() == h + 1 and first == second)
        check('Production: a cached body equals a fresh recomputation', same_as_fresh(admin, PRD))
        check('Production: the report really contains this test data', len([r for r in first['rows'] if r['reinsured'] == 'ZZ RC Cedant']) > 0)
        before = cached(admin, PRD)
        c4 = make(admin, originalInsured='ZZ RC Four')
        after = cached(admin, PRD)
        check('Production: a new case appears immediately', after != before and after == fresh(admin, PRD))
        before = after; c4 = app_write(c4, originalPremium=7777)
        after = cached(admin, PRD)
        check('Production: editing a case changes the preview immediately', after != before and after == fresh(admin, PRD))
        before = after; fx = FxRate.objects.get(year_month=MONTH, currency='USD'); fx.rate = '35'; fx.row_version += 1; fx.save()
        after = cached(admin, PRD)
        check('Production: an FX rate change for the month changes the preview immediately', after != before and after == fresh(admin, PRD))
        before = after; target_row = next(r for r in after['rows'] if r['caseUid'] == str(c4.case_uid))
        ProductionExclusion.objects.create(case_id=c4.pk, year_month=MONTH, scope='case', installment_key=target_row['key'], reinsurer_key=None,
                                           deferred_to='2031-06', reason='qa', created_by='qa')
        after = cached(admin, PRD)
        check('Production: an exclusion moves the rows immediately', after != before and after == fresh(admin, PRD))
        # 連結表：另一件（含已封存）案件的資料改變 First Policy No
        before = after; live = next(r for r in after['rows'] if r['caseUid'] == str(c1.case_uid))
        parent = Case.objects.create(tw_ref='ZZ-RC-PARENT', status='posted', is_archived=True, archived_at=timezone.now(), archived_by='qa', payload={'twRef': 'ZZ-RC-PARENT'}, created_by='qa', updated_by='qa')
        c1 = app_write(c1, renewedFromTwRef='ZZ-RC-PARENT')
        after = cached(admin, PRD); moved = next(r for r in after['rows'] if r['caseUid'] == str(c1.case_uid))
        check('Production: a renewal link to an archived case is followed immediately (First Policy No)', after == fresh(admin, PRD) and moved['firstPolicyNo'] == 'ZZ-RC-PARENT' and live['firstPolicyNo'] != 'ZZ-RC-PARENT')
        before = after; Case.objects.filter(pk=parent.pk).update(payload={'twRef': 'ZZ-RC-PARENT', 'renewedFromTwRef': 'ZZ-RC-ROOT'}, row_version=2)
        Case.objects.create(tw_ref='ZZ-RC-ROOT', status='posted', is_archived=True, archived_at=timezone.now(), archived_by='qa', payload={'twRef': 'ZZ-RC-ROOT'}, created_by='qa', updated_by='qa')
        after = cached(admin, PRD); moved = next(r for r in after['rows'] if r['caseUid'] == str(c1.case_uid))
        check('Production: a change in the archived chain is followed immediately', after == fresh(admin, PRD) and moved['firstPolicyNo'] == 'ZZ-RC-ROOT')
        # 寫入動作永遠讀最新資料；之後的 GET 立刻反映
        r = post(admin, '/api/production-report', {'action': 'generate', 'month': MONTH, 'sourceSignature': cached(admin, PRD)['sourceSignature']})   # 用快取預覽的簽章：若快取過期，伺服器會回 source_changed
        after = cached(admin, PRD)
        check('Production: Generate (never cached) works and the next GET shows the new version', r.status_code == 201 and len(after['versions']) == 1 and after == fresh(admin, PRD))
        r = post(admin, '/api/production-report', {'action': 'close', 'month': MONTH, 'reportUid': after['versions'][0]['reportUid'], 'rowVersion': after['versions'][0]['rowVersion'], 'sourceSignature': after['sourceSignature']})
        after = cached(admin, PRD)
        check('Production: Close works and the next GET shows the closed month', after['scope']['monthClosed'] is True and after == fresh(admin, PRD))
        # 權限判斷每次即時
        sales, _ = client('sales', 'sales', 'reinsurance')
        check('Production: the operate/close scope is decided per user, not taken from the cache',
              cached(sales, PRD)['scope']['canOperate'] is False and cached(admin, PRD)['scope']['canOperate'] is True)
        # 保險上限
        warm = cached(admin, PRD)
        p = copy.deepcopy(Case.objects.get(pk=c4.pk).payload); p['originalPremium'] = 1
        Case.objects.filter(pk=c4.pk).update(payload=p)
        stale = cached(admin, PRD)
        check('Production: a write that bypasses the application is not seen immediately (documented limit)', stale == warm)
        with mock.patch.object(result_cache, 'time', SimpleNamespace(monotonic=lambda: real_time.monotonic() + 61)):
            check('Production: ...but is picked up after the safety limit (60 s)', cached(admin, PRD) != warm)

        # 快取大小有上限；關閉開關時完全不使用快取
        for i in range(result_cache.MAX_ENTRIES + 5):
            result_cache.get_or_compute(('fill', i), ('fp',), lambda: i)
        check('Cache size is bounded', len(result_cache._store) <= result_cache.MAX_ENTRIES)
        h = hits(); settings.RESULT_CACHE_ENABLED = False; cached(admin, DASH); cached(admin, DASH); settings.RESULT_CACHE_ENABLED = True
        check('RI_RESULT_CACHE=false disables the cache completely', hits() == h)
        raise Rollback()
except Rollback:
    pass
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back')
