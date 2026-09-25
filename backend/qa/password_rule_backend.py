"""把 password_vectors.json 每一組密碼丟給後端驗證，印出 RESULT {密碼: 是否通過}（供與前端檢查函數比對）。"""
import json
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

vectors = json.load(open(os.environ.get("VECTORS", "/app/qa/password_vectors.json"), encoding="utf-8"))
out = {}
for v in vectors:
    try:
        validate_password(v)
        out[v] = True
    except ValidationError:
        out[v] = False
print("RESULT " + json.dumps(out, ensure_ascii=False))
