def is_active_claimer(report, user):
    """US-SEC1 · is `user` the account with the currently-active claim on `report`?
    An expired claim doesn't count — that claimer is no longer the one who needs the
    precise spot; a fresh claimer (or no one) does."""
    if not getattr(user, "is_authenticated", False):
        return False
    return report.cases.filter(claimed_by_account=user, expired_at__isnull=True).exists()
