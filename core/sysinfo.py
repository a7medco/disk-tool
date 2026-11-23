"""Battery health and Windows license (read-only)."""
from .system import ps_json

WIN_APP_ID = "55c92734-d682-4d71-983e-d6ec3f16059f"     # Windows SKUs in SoftwareLicensingProduct
STATUS = {0: "Unlicensed", 1: "Activated", 2: "Grace period", 3: "Grace period",
          4: "Not genuine", 5: "Notification", 6: "Extended grace"}


def battery():
    """Health % = FullChargedCapacity / DesignedCapacity (root\\wmi, in mWh)."""
    rows = ps_json(
        "$d=@(Get-CimInstance -Namespace root\\wmi -ClassName BatteryStaticData -ErrorAction SilentlyContinue);"
        "$f=@(Get-CimInstance -Namespace root\\wmi -ClassName BatteryFullChargedCapacity -ErrorAction SilentlyContinue);"
        "$c=@(Get-CimInstance -Namespace root\\wmi -ClassName BatteryCycleCount -ErrorAction SilentlyContinue);"
        "$b=@(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue);"
        "for($i=0;$i -lt $d.Count;$i++){[pscustomobject]@{"
        "Name=$d[$i].DeviceName; Maker=$d[$i].ManufactureName; Serial=$d[$i].SerialNumber;"
        "Design=$d[$i].DesignedCapacity; Full=($f[$i]).FullChargedCapacity;"
        "Cycles=($c[$i]).CycleCount; Charge=($b[$i]).EstimatedChargeRemaining}}")
    for r in rows:
        try:
            r["Health"] = round(100.0 * r["Full"] / r["Design"]) if r.get("Design") else None
        except (TypeError, ZeroDivisionError):
            r["Health"] = None
        h = r["Health"]
        r["Verdict"] = "?" if h is None else ("ok" if h >= 80 else "warn" if h >= 60 else "bad")
    return rows


def license_info():
    svc = ps_json("Get-CimInstance SoftwareLicensingService | "
                  "Select-Object OA3xOriginalProductKey,OA3xOriginalProductKeyDescription")
    prod = ps_json("Get-CimInstance SoftwareLicensingProduct -Filter \"ApplicationID='%s' "
                   "AND PartialProductKey IS NOT NULL\" | Select-Object Name,Description,"
                   "PartialProductKey,LicenseStatus,ProductKeyChannel" % WIN_APP_ID)
    os_ = ps_json("Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber")
    s = svc[0] if svc else {}
    p = prod[0] if prod else {}
    o = os_[0] if os_ else {}
    return {
        "bios_key": (s.get("OA3xOriginalProductKey") or "").strip(),
        "bios_desc": (s.get("OA3xOriginalProductKeyDescription") or "").strip(),
        "edition": o.get("Caption", ""), "build": "%s (%s)" % (o.get("Version", ""), o.get("BuildNumber", "")),
        "partial": p.get("PartialProductKey") or "",
        "channel": p.get("ProductKeyChannel") or (p.get("Description") or ""),
        "status": STATUS.get(int(p.get("LicenseStatus") or 0), "Unknown") if p else "No key installed",
    }
