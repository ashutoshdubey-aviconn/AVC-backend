"""Which site an alarm belongs to when sites are merged with virtual aisle groups.

An aisle has a physical site (``AisleGroup.site``: where its meter and gateway
are, and where its readings are stored) and a display site
(``AisleGroup.virtual_siteID``: the site the customer sees it under). A
customer may want two physical sites shown as one: e.g. site 185 FM
FarukhNagar-2 is not live, its aisles show under the live site 183 FM MCF-1
Farrukhnagar (one site for the customer, two gateways).

Rules (since 2026-11-17):
* A site is MONITORED when it is live, or when one of its active aisles shows
  under a live display site. Gateway (15 / 16), meter (14) and spike (17)
  checks cover monitored sites; they used to skip every site not live.
* Aisle alarms (7, 8, 10, 11, 12, 17) are stored and e-mailed under the
  aisle's display site, so they show where the customer sees the aisle.
* Gateway alarms go to the live display sites of the aisles the gateway feeds
  (AisleSyncRecoveryStatus; all active aisles of its site when unknown), or to
  its own site when that is live and none of them is.
* Thresholds, baselines and NL hours are still taken from the physical site;
  an alarm is Off (AlarmSetting) when it is Off on the physical OR the display
  site.
"""

from django.db.models import F

from wareApp.models import AisleGroup, AisleSyncRecoveryStatus, Site


def display_site_id(aisle_group, site_id):
    """Site id an aisle's alarms are stored under (its display site).

    Origin: Ashu
    """
    if aisle_group is None:
        return site_id
    return getattr(aisle_group, "virtual_siteID_id", None) or getattr(aisle_group, "site_id", None) or site_id


def display_site(aisle_group, site):
    """Site object an aisle's alarms are stored under.

    Origin: Ashu
    """
    target = display_site_id(aisle_group, site.id)
    if target == site.id:
        return site
    return Site.objects.filter(pk=target).first() or site


def live_site_ids():
    """Ids of the sites marked live.

    Origin: Ashu
    """
    return set(Site.objects.filter(is_live=True).values_list("id", flat=True))


def monitored_site_ids(live=None):
    """Live sites plus sites whose active aisles show under a live display site.

    Origin: Ashu
    """
    live = live_site_ids() if live is None else live
    merged = set(
        AisleGroup.objects.filter(is_active=True, virtual_siteID_id__in=live)
        .exclude(site_id=F("virtual_siteID_id"))
        .values_list("site_id", flat=True)
    )
    return live | merged


def site_targets(site_id, aisles, live):
    """Live sites that get an alarm about ``aisles`` of physical site ``site_id``.

    Origin: Ashu
    """
    targets = sorted({display_site_id(aisle, site_id) for aisle in aisles} & live)
    if not targets and site_id in live:
        targets = [site_id]
    return targets


def gateway_aisles(hgw):
    """Active aisles a gateway feeds (all active aisles of its site when unknown).

    Origin: Ashu
    """
    site_aisles = AisleGroup.objects.filter(site_id=hgw.connected_to_id, is_active=True)
    fed = set(
        AisleSyncRecoveryStatus.objects.filter(home_gateway_id=hgw.hgw_id, aisle_group__isnull=False)
        .values_list("aisle_group_id", flat=True)
    )
    if fed:
        mapped = [aisle for aisle in site_aisles if aisle.id in fed]
        if mapped:
            return mapped
    return list(site_aisles)


def candidate_sites(site_id, aisles):
    """Every site an alarm about these aisles could have been stored under (for clearing).

    Origin: Ashu
    """
    return {site_id} | {display_site_id(aisle, site_id) for aisle in aisles}
