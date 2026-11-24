"""
Mobile app accounts.

Two kinds of accounts can use the mobile app:
  - committee accounts (``GovernmentWorker``): the secretary's account of a CCGP (village),
    a CLGP (commune) or the national committee. They receive and process issues.
  - facilitator accounts (``Facilitator``): field staff who create and follow issues
    but never process them.

Any other account (GRM managers, citizens, ...) is refused by the mobile app.
"""

ACCOUNT_TYPE_COMMITTEE = "committee"
ACCOUNT_TYPE_FACILITATOR = "facilitator"

# How the mobile "location" step lets the user pick where the issue happened
LOCATION_MODE_FIXED = "fixed"  # single region, preselected and locked (e.g. CCGP village)
LOCATION_MODE_LIST = "list"  # pick one region from ``regions``
LOCATION_MODE_FREE = "free"  # any region of the tree (e.g. national committee)


def get_mobile_account_type(user):
    """Return the mobile account type of ``user`` or ``None`` if not allowed on the mobile app."""
    if hasattr(user, "governmentworker"):
        return ACCOUNT_TYPE_COMMITTEE
    if hasattr(user, "facilitator"):
        return ACCOUNT_TYPE_FACILITATOR
    return None


def _leaf_regions_under(region):
    """Regions without children under ``region`` (villages in Benin), ``region`` included if it is a leaf."""
    from issues.models import AdministrativeRegion

    return (
        AdministrativeRegion.objects.filter(id__in=region.get_descendant_ids(), children__isnull=True)
        .select_related("administrative_level")
        .order_by("hierarchical_name", "name")
    )


def get_location_scope(user):
    """
    Return ``(mode, regions)`` describing the locations ``user`` can choose on the mobile app.

    - CCGP (committee on a leaf region): fixed to its village.
    - National committee (committee on the root region): free choice.
    - Other committees (CLGP): the commune itself and the villages under it.
    - Facilitator: its covered villages; if none are set, the villages under its region.
    """
    account_type = get_mobile_account_type(user)

    if account_type == ACCOUNT_TYPE_COMMITTEE:
        region = user.governmentworker.administrative_region
        if region.parent_id is None:
            return LOCATION_MODE_FREE, []
        if not region.children.exists():
            return LOCATION_MODE_FIXED, [region]
        return LOCATION_MODE_LIST, [region, *_leaf_regions_under(region)]

    if account_type == ACCOUNT_TYPE_FACILITATOR:
        facilitator = user.facilitator
        villages = list(
            facilitator.villages.select_related("administrative_level").order_by("hierarchical_name", "name")
        )
        if not villages:
            villages = list(_leaf_regions_under(facilitator.administrative_region))
        if len(villages) == 1:
            return LOCATION_MODE_FIXED, villages
        return LOCATION_MODE_LIST, villages

    return None, []


def _region_data(region):
    from issues.serializers import AdministrativeRegionSerializer

    return AdministrativeRegionSerializer(region).data if region else None


def build_mobile_profile(user):
    """Profile returned to the mobile app after login (see ``MobileProfileAPIView``)."""
    account_type = get_mobile_account_type(user)
    committee = None

    if account_type == ACCOUNT_TYPE_COMMITTEE:
        worker = user.governmentworker
        region = worker.administrative_region
        committee = {
            "department": {"id": worker.department_id, "name": worker.department.name},
            "administrative_level": {
                "id": region.administrative_level_id,
                "name": region.administrative_level.name,
            },
        }
    else:
        region = user.facilitator.administrative_region

    mode, regions = get_location_scope(user)
    return {
        "account_type": account_type,
        "can_process_issues": account_type == ACCOUNT_TYPE_COMMITTEE,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone": user.phone_number,
            "photo": user.photo.url if getattr(user, "photo", None) else None,
        },
        "administrative_region": _region_data(region),
        "committee": committee,
        # Field staff role ("FC" community facilitator, "SC" communal supervisor), "" for committees
        "field_role": user.facilitator.role if account_type == ACCOUNT_TYPE_FACILITATOR else "",
        "location": {"mode": mode, "regions": [_region_data(r) for r in regions]},
    }
