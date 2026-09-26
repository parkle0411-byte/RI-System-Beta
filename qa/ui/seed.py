# 畫面測試用的合成資料（只在用完即丟的測試環境執行）
from django.contrib.auth import get_user_model
from masterdata.models import MasterRecord
from personnel.models import Personnel

User = get_user_model()
PASSWORD = "Ui-Test-Pass-1"


def person(name, dept, role, username=None, must_change=False):
    p = Personnel.objects.create(name=name, department=dept, role_code=role, created_by="seed", updated_by="seed",
                                 is_split_eligible=dept not in ("finance", "admin"))
    if username:
        u = User.objects.create_user(username=username, password=PASSWORD)
        p.auth_user_id = str(u.pk)
        p.account_status = "active"
        p.must_change_password = must_change
        p.save()
    return p


person("UI Admin", "admin", "admin", "ui.admin")
sales = person("UI Sales", "reinsurance", "sales", "ui.sales")
person("UI Partner", "reinsurance", "sales")
person("UI Viewer", "business_1", "viewer", "ui.viewer")
person("UI Finance", "finance", "accounting")
person("UI Newcomer", "business_2", "viewer", "ui.newcomer", must_change=True)


def master(entity_type, name, code=None, **payload):
    return MasterRecord.objects.create(entity_type=entity_type, name=name, code=code, payload=payload,
                                       created_by="seed", updated_by="seed")


for code, title in (("LMA3333", "Reinsurers Liability Clause"), ("INTERMEDIARY", "Intermediary Clause (TW Insurance Brokers Ltd.)"),
                    ("LMA5390", "Test Clause Alpha"), ("NMA2918", "Test Clause Beta")):
    master("clause", title, code)
master("ae", "UI AE One")
master("reinsured", "UI Cedant Insurance", abbreviation="UIC", address="1 Test Road")
master("class", "Property", "PAR")
master("reinsurer", "UI Re Alpha", abbreviation="URA", fixedClauses=[{"code": "LMA5390", "title": "Test Clause Alpha"}], ratings=[])
master("reinsurer", "UI Re Beta (Facility)", abbreviation="URB", fixedClauses=[], ratings=[])
master("foreign_broker", "UI Broker")
print("seeded")
