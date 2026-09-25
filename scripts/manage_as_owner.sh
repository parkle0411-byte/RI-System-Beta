#!/usr/bin/env bash
# 以「維護者」ri_app 身分執行 manage.py（可改資料表結構、可 DELETE）。
# 網站平常用的 ri_runtime 沒有這些權限；只有 migrate 或明確的維護作業才用這支。
#   例：scripts/manage_as_owner.sh shell
set -euo pipefail
docker exec -i -e MYSQL_USER=ri_app -e MYSQL_PASSWORD_FILE=/run/secrets/mysql_app_password ri-backend python manage.py "$@"
