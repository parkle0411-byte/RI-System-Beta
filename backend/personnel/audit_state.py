def personnel_state(person):
    """Snapshot / Audit 內容，欄位與 Alpha 的 api/personnel.js 的 jsonb_build_object 相同。"""
    return {
        "id": person.id,
        "name": person.name,
        "email": person.email,
        "department": person.department,
        "roleCode": person.role_code,
        "isActive": person.is_active,
        "isSplitEligible": person.is_split_eligible,
        "accountStatus": person.account_status,
        "supervisorName": person.supervisor_name,
        "supervisorEmail": person.supervisor_email,
        "rowVersion": person.row_version,
    }
