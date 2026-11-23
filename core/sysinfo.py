"""Battery health and Windows license (read-only)."""
from .system import ps_json

WIN_APP_ID = "55c92734-d682-4d71-983e-d6ec3f16059f"     # Windows SKUs in SoftwareLicensingProduct
STATUS = {0: "Unlicensed", 1: "Activated", 2: "Grace period", 3: "Grace period",
          4: "Not genuine", 5: "Notification", 6: "Extended grace"}


def _battery_powercfg():
    """Main source: Windows' own battery report (powercfg /batteryreport /xml)."""
    import os
    import subprocess
    import tempfile
    import xml.etree.ElementTree as ET
    from .system import NOWIN
    out = os.path.join(tempfile.gettempdir(), "disktool_battery.xml")
    try:
        os.remove(out)
    except OSError:
        pass
    try:
        subprocess.run(["powercfg", "/batteryreport", "/xml", "/output", out],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       stdin=subprocess.DEVNULL, creationflags=NOWIN, timeout=60)
        root = ET.parse(out).getroot()
    except Exception:
        return []

    def txt(node, name):
        for ch in node:
            if ch.tag.split("}")[-1] == name:
                return (ch.text or "").strip()
        return ""
    rows = []
    for b in root.iter():
        if b.tag.split("}")[-1] != "Battery":
            continue
        def num(n):
            try:
                return int(float(txt(b, n)))
            except ValueError:
                return None
        rows.append({"Name": txt(b, "Id"), "Maker": txt(b, "Manufacturer"),
                     "Serial": txt(b, "SerialNumber"), "Chem": txt(b, "Chemistry"),
                     "Design": num("DesignCapacity"), "Full": num("FullChargeCapacity"),
                     "Cycles": num("CycleCount"), "Charge": None})
    return rows


def battery():
    """Health % = full charge capacity / design capacity (mWh).

    1st: powercfg battery report (works on most laptops)
    2nd: root\\wmi classes (fallback)
    """
    rows = _battery_powercfg()
    if rows:
        chg = ps_json("Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | "
                      "Select-Object EstimatedChargeRemaining")
        for i, r in enumerate(rows):
            if i < len(chg):
                r["Charge"] = chg[i].get("EstimatedChargeRemaining")
        return _grade(rows)
    return _grade(_battery_wmi())


def battery_report_html():
    """Make the full HTML battery report and open it."""
    import os
    import subprocess
    import tempfile
    from .system import NOWIN
    out = os.path.join(tempfile.gettempdir(), "battery-report.html")
    subprocess.run(["powercfg", "/batteryreport", "/output", out], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=NOWIN, timeout=60)
    if os.path.isfile(out):
        os.startfile(out)
        return True
    return False


def _battery_wmi():
    rows = ps_json(
        "$d=@(Get-CimInstance -Namespace root\\wmi -ClassName BatteryStaticData -ErrorAction SilentlyContinue);"
        "$f=@(Get-CimInstance -Namespace root\\wmi -ClassName BatteryFullChargedCapacity -ErrorAction SilentlyContinue);"
        "$c=@(Get-CimInstance -Namespace root\\wmi -ClassName BatteryCycleCount -ErrorAction SilentlyContinue);"
        "$b=@(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue);"
        "for($i=0;$i -lt $d.Count;$i++){[pscustomobject]@{"
        "Name=$d[$i].DeviceName; Maker=$d[$i].ManufactureName; Serial=$d[$i].SerialNumber;"
        "Design=$d[$i].DesignedCapacity; Full=($f[$i]).FullChargedCapacity;"
        "Cycles=($c[$i]).CycleCount; Charge=($b[$i]).EstimatedChargeRemaining}}")
    return rows


def _grade(rows):
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
