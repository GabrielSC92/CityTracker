"""ISO 3166-1 alpha-2 country code -> continent, plus flag emoji helpers.

Kept as a small local table so the app has no dependency on pycountry or any
other lookup package. Transcontinental countries are assigned to a single
continent (Russia -> Europe, Turkey -> Asia, Cyprus -> Europe) so that the
per-continent counters stay stable.
"""

from __future__ import annotations

_BY_CONTINENT: dict[str, str] = {
    "Africa": (
        "DZ AO BJ BW BF BI CM CV CF TD KM CD CG CI DJ EG GQ ER SZ ET GA GM GH "
        "GN GW KE LS LR LY MG MW ML MR MU YT MA MZ NA NE NG RE RW SH ST SN SC "
        "SL SO ZA SS SD TZ TG TN UG EH ZM ZW"
    ),
    "Europe": (
        "AL AD AT AX BY BE BA BG HR CY CZ DK EE FO FI FR DE GI GR GG HU IS IE "
        "IM IT JE XK LV LI LT LU MT MD MC ME NL MK NO PL PT RO RS RU SM SK SI "
        "ES SJ SE CH UA GB VA"
    ),
    "Asia": (
        "AF AM AZ BH BD BT BN KH CN GE HK ID IN IL IQ IR JO JP KG KH KP KR KW "
        "KZ LA LB LK MM MN MO MV MY NP OM PH PK PS QA SA SG SY TH TJ TL TM TR "
        "TW UZ VN YE AE"
    ),
    "North America": (
        "AG AI AW BB BL BM BQ BS BZ CA CR CU CW DM DO GD GL GP GT HN HT JM KN "
        "KY LC MF MQ MS MX NI PA PM PR SV SX TC TT US VC VG VI"
    ),
    "South America": "AR BO BR CL CO EC FK GF GY PE PY SR UY VE",
    "Oceania": (
        "AS AU CK FJ FM GU KI MH MP NC NF NR NU NZ PF PG PN PW SB TK TO TV UM "
        "VU WF WS"
    ),
    "Antarctica": "AQ BV GS HM TF",
}

CONTINENTS: tuple[str, ...] = (
    "Africa",
    "Asia",
    "Europe",
    "North America",
    "South America",
    "Oceania",
    "Antarctica",
)

_CODE_TO_CONTINENT: dict[str, str] = {
    code: continent
    for continent, codes in _BY_CONTINENT.items()
    for code in codes.split()
}


def continent_for(country_code: str | None) -> str:
    """Return the continent for an ISO alpha-2 code, or "Unknown"."""
    if not country_code:
        return "Unknown"
    return _CODE_TO_CONTINENT.get(country_code.strip().upper(), "Unknown")


def flag(country_code: str | None) -> str:
    """Return the regional-indicator flag emoji for an ISO alpha-2 code."""
    if not country_code:
        return ""
    code = country_code.strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(char) - ord("A")) for char in code)
