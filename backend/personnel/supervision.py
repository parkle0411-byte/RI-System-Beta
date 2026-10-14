"""Resolve existing Supervisor assignments without granting role-wide personnel access."""
from .models import Personnel

SUBORDINATE_PERMISSIONS = ("personnel.read.team", "personnel.create.subordinate", "accounts.create.subordinate")


def subordinate_role(department):
    return {"reinsurance": "sales", "finance": "accounting"}.get(department, "viewer")


def supervisor_candidates(name, department, excluded_id=0):
    candidates = [p for p in Personnel.objects.filter(name__iexact=name, is_active=True)
                  if p.pk != excluded_id and
                  (p.department == department or p.role_code in ("general_manager", "president"))]
    return sorted(candidates, key=lambda p: (p.department != department, p.pk))


def is_supervisor(person):
    if person is None or not person.is_active:
        return False
    # Names may repeat across departments. Use the same resolution order as
    # personnel editing, excluding the subordinate themselves from candidates.
    candidates = list(Personnel.objects.filter(name__iexact=person.name, is_active=True))
    assignments = Personnel.objects.filter(supervisor_name__iexact=person.name).exclude(pk=person.pk)
    for subordinate_id, department in assignments.values_list("id", "department"):
        eligible = [p for p in candidates if p.pk != subordinate_id and
                    (p.department == department or p.role_code in ("general_manager", "president"))]
        eligible.sort(key=lambda p: (p.department != department, p.pk))
        if eligible and eligible[0].pk == person.pk:
            return True
    return False


def is_general_subordinate(supervisor, person):
    if (supervisor is None or not supervisor.is_active or person.pk == supervisor.pk
            or person.department != supervisor.department
            or person.role_code != subordinate_role(supervisor.department)
            or not person.supervisor_name):
        return False
    candidates = supervisor_candidates(person.supervisor_name, person.department, person.pk)
    return bool(candidates and candidates[0].pk == supervisor.pk)


def can_create_subordinate_account(supervisor, person):
    return (supervisor is not None and supervisor.role_code != "president"
            and is_general_subordinate(supervisor, person) and person.is_active
            and not person.auth_user_id and person.account_status == "not_configured")


def supervisor_permissions(person):
    """Supervisor grants respect role-specific restrictions as well as team scope."""
    if person is not None and person.role_code == "president":
        return ()
    return SUBORDINATE_PERMISSIONS
