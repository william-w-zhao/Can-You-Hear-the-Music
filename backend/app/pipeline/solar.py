"""Sun position (NOAA solar calculator equations, vectorized). Accurate to well under a degree."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np


def sun_position(lat, lon, when_utc):
    """when_utc: numpy datetime64 array (UTC). Returns (elevation_deg, azimuth_deg clockwise from north)."""
    t = np.asarray(when_utc, dtype="datetime64[s]")
    jd = t.astype("int64") / 86400.0 + 2440587.5
    jc = (jd - 2451545.0) / 36525.0
    l0 = np.mod(280.46646 + jc * (36000.76983 + jc * 0.0003032), 360)
    m = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    mr = np.radians(m)
    c = np.sin(mr) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) + np.sin(2 * mr) * (0.019993 - 0.000101 * jc) \
        + np.sin(3 * mr) * 0.000289
    true_long = l0 + c
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * np.sin(np.radians(omega))
    eps0 = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * np.cos(np.radians(omega))
    decl = np.degrees(np.arcsin(np.sin(np.radians(eps)) * np.sin(np.radians(app_long))))
    y = np.tan(np.radians(eps / 2)) ** 2
    l0r = np.radians(l0)
    eq_time = 4 * np.degrees(y * np.sin(2 * l0r) - 2 * e * np.sin(mr) + 4 * e * y * np.sin(mr) * np.cos(2 * l0r)
                             - 0.5 * y * y * np.sin(4 * l0r) - 1.25 * e * e * np.sin(2 * mr))
    minutes = (t - t.astype("datetime64[D]")).astype("int64") / 60.0
    tst = np.mod(minutes + eq_time + 4 * lon, 1440)
    ha = np.where(tst / 4 < 0, tst / 4 + 180, tst / 4 - 180)
    latr, declr, har = np.radians(lat), np.radians(decl), np.radians(ha)
    cos_zen = np.clip(np.sin(latr) * np.sin(declr) + np.cos(latr) * np.cos(declr) * np.cos(har), -1, 1)
    zen = np.degrees(np.arccos(cos_zen))
    az = np.degrees(np.arctan2(np.sin(har), np.cos(har) * np.sin(latr) - np.tan(declr) * np.cos(latr))) + 180
    return 90 - zen, np.mod(az, 360)


def matching_times(lat, lon, azimuth, elevation, tz="America/Los_Angeles", year=2025, step_min=5, top=6):
    """Dates and local times in `year` when the sun stood at (azimuth, elevation). Mirror dates either side of
    a solstice give near-identical positions, so results come in pairs."""
    start = np.datetime64(f"{year}-01-01T00:00")
    times = start + np.arange(0, 366 * 24 * 60, step_min).astype("timedelta64[m]")
    el, az = sun_position(lat, lon, times)
    daz = (az - azimuth + 180) % 360 - 180
    err = np.hypot(daz * np.cos(np.radians(elevation)), el - elevation)
    order = np.argsort(err)
    picked, days = [], []
    zone = ZoneInfo(tz)
    for i in order:
        if err[i] > 3 or len(picked) >= top:
            break
        utc = datetime.fromtimestamp(times[i].astype("datetime64[s]").astype(int), timezone.utc)
        day = utc.timetuple().tm_yday
        if any(abs(day - d) < 12 for d in days):
            continue
        days.append(day)
        local = utc.astimezone(zone)
        picked.append({"local": local.strftime("%b %d, %H:%M %Z"), "date": local.strftime("%m-%d"),
                       "error_deg": round(float(err[i]), 2)})
    return picked


def elevation_range(lat, lon, tz="America/Los_Angeles", year=2025):
    """Noon sun elevation at the solstices: the plausible range for midday aerial capture."""
    out = {}
    for name, md in (("dec_solstice", "12-21"), ("jun_solstice", "06-21")):
        day = np.datetime64(f"{year}-{md}T00:00") + np.arange(0, 1440, 2).astype("timedelta64[m]")
        el, _ = sun_position(lat, lon, day)
        out[name] = round(float(el.max()), 1)
    return out
