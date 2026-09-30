"""Markets as data: ISO 3166-1 country codes and BCP 47 locale tags (ADR-0007 §1).

A market is not an enum member. A source context names its country, currency and time zone
explicitly, and a locale is a BCP 47 tag such as ``en-AE``, ``ar-SA`` or ``fr-FR``.

Only the subset of BCP 47 that storefronts use is accepted, in canonical case:
``language[-Script][-REGION]`` (``ar``, ``ar-AE``, ``az-Arab``, ``zh-Hant-TW``, ``es-419``).
"""

import re

#: ISO 3166-1 alpha-2 codes officially assigned (from the IANA tz database ``iso3166.tab``).
COUNTRY_CODES: frozenset[str] = frozenset(
    """
    AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ
    BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM
    DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS
    GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN
    KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ
    MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM
    PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV
    SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI
    VN VU WF WS YE YT ZA ZM ZW
    """.split()  # noqa: SIM905 - one compact, reviewable block
)

#: Languages written right to left in their default script.
RTL_LANGUAGES: frozenset[str] = frozenset(
    {"ar", "arc", "ckb", "dv", "fa", "he", "ks", "ku", "ps", "sd", "syr", "ug", "ur", "yi"}
)
#: Scripts written right to left; an explicit script subtag overrides the language default.
RTL_SCRIPTS: frozenset[str] = frozenset({"Adlm", "Arab", "Hebr", "Nkoo", "Rohg", "Syrc", "Thaa"})

_LOCALE_RE = re.compile(
    r"^(?P<language>[a-z]{2,3})(?:-(?P<script>[A-Z][a-z]{3}))?(?:-(?P<region>[A-Z]{2}|[0-9]{3}))?$"
)


def check_country(value: str) -> str:
    """Return ``value`` if it is an assigned ISO 3166-1 alpha-2 code, else raise."""
    if value not in COUNTRY_CODES:
        msg = f"unknown ISO 3166-1 alpha-2 country {value!r}"
        raise ValueError(msg)
    return value


def _parse(value: str) -> re.Match[str]:
    found = _LOCALE_RE.fullmatch(value)
    if found is None:
        msg = f"locale {value!r} is not a canonical BCP 47 language[-Script][-REGION] tag"
        raise ValueError(msg)
    region = found.group("region")
    if region is not None and region.isalpha():
        check_country(region)
    return found


def check_locale(value: str) -> str:
    """Return ``value`` if it is a canonical ``language[-Script][-REGION]`` tag, else raise."""
    _parse(value)
    return value


def language_of(locale: str) -> str:
    """The primary language subtag: ``ar`` for ``ar-AE``."""
    return _parse(locale).group("language")


def region_of(locale: str) -> str | None:
    """The region subtag, or None: ``AE`` for ``ar-AE``, None for ``ar``."""
    return _parse(locale).group("region")


def is_rtl(locale: str) -> bool:
    """True when the tag's script (explicit, else the language default) is right to left."""
    found = _parse(locale)
    script = found.group("script")
    if script is not None:
        return script in RTL_SCRIPTS
    return found.group("language") in RTL_LANGUAGES
