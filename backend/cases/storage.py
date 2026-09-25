"""
案件文件的檔案本體存放（對應 Alpha 的 Hatchable storage）。

放在 settings.CASE_DOCUMENT_ROOT（容器內 /data/documents，掛 Docker volume `case_documents`），
路徑就是 storage_key（例如 case-documents/<caseUid>/<fileId>.pdf）。

- 寫入：先寫暫存檔、fsync，再原子地 rename 成正式檔名；中途失敗不會留下只寫一半的正式檔案。
- 路徑一律檢查必須落在根目錄之下（storage_key 雖然由程式組出，這裡仍不信任它）。
- 備份：這個 volume 不在 MySQL 備份裡，要另外備份（見 MIGRATION-STATUS.md「維運」）。
"""
import os
import uuid
from pathlib import Path

from django.conf import settings


class StorageError(Exception):
    pass


def _root():
    return Path(settings.CASE_DOCUMENT_ROOT).resolve()


def path_for(storage_key):
    root = _root()
    path = (root / storage_key).resolve()
    if root not in path.parents:
        raise StorageError(f"storage key escapes the document root: {storage_key!r}")
    return path


def put(storage_key, data):
    path = path_for(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temp, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def open_read(storage_key):
    """回傳可讀的檔案物件；檔案不存在時丟出 FileNotFoundError。"""
    return open(path_for(storage_key), "rb")


def delete(storage_key):
    path_for(storage_key).unlink(missing_ok=True)


def exists(storage_key):
    return path_for(storage_key).is_file()
