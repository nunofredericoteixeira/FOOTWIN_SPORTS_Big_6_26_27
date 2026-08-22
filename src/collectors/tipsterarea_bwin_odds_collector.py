
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://tipsterarea.com"
REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 "
        "Chrome/151.0 Safari/537.36"
    )
}

CLUB_AFFIXES = {
    "fc",
    "sc",
    "sl",
    "cf",
    "ac",
    "as",
}


@dataclass(frozen=True)
class BwinOddsResult:
    tipsterarea_id: int
    canonical_url: str
    home_team: str
    away_team: str
    event_date: str
    odds: dict[str, float]
    footwin_prediction: str
    selected_odd: float | None


def normalize_team_name(value: str) -> str:
    text = unicodedata.normalize(
        "NFKD",
        value or "",
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    tokens = re.findall(
        r"[a-z0-9]+",
        text.lower(),
    )

    while (
        len(tokens) > 1
        and tokens[0] in CLUB_AFFIXES
    ):
        tokens.pop(0)

    while (
        len(tokens) > 1
        and tokens[-1] in CLUB_AFFIXES
    ):
        tokens.pop()

    return " ".join(tokens)


def extract_main_event(
    html: str,
) -> tuple[str, str, str] | None:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    event = soup.select_one(
        'div[itemscope][itemtype="http://schema.org/SportsEvent"]'
    )

    if event is None:
        return None

    teams = [
        " ".join(h2.stripped_strings)
        for h2 in event.select(
            'div[itemprop="performers"] h2[itemprop="name"]'
        )
    ]

    if len(teams) < 2:
        return None

    start = event.select_one(
        '[itemprop="startDate"]'
    )

    if start is None:
        return None

    content = str(
        start.get("content") or ""
    ).strip()

    if len(content) < 10:
        return None

    event_date = content[:10]

    return (
        teams[0],
        teams[1],
        event_date,
    )


def page_matches_exact_fixture(
    html: str,
    home_team: str,
    away_team: str,
    match_date: str,
) -> bool:
    extracted = extract_main_event(
        html,
    )

    if extracted is None:
        return False

    page_home, page_away, page_date = extracted

    return (
        normalize_team_name(page_home)
        == normalize_team_name(home_team)
        and normalize_team_name(page_away)
        == normalize_team_name(away_team)
        and page_date == match_date
    )


def parse_bwin_odds(
    html: str,
) -> dict[str, float]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    result: dict[str, float] = {}

    wanted_markets = {
        "Standard 1X2",
        "Double Chance",
    }

    for table in soup.select("table.odds"):
        header_cells = [
            " ".join(th.stripped_strings)
            for th in table.select("thead th")
        ]

        if not header_cells:
            continue

        market_name = header_cells[0].strip()

        if market_name not in wanted_markets:
            continue

        labels = [
            label.strip()
            for label in header_cells[1:]
        ]

        for row in table.select("tbody tr"):
            image = row.select_one(
                'td.bookmaker img[alt]'
            )

            if not image:
                continue

            bookmaker = (
                image.get("alt") or ""
            ).strip().lower()

            if bookmaker != "bwin":
                continue

            values = [
                float(td.get_text(strip=True))
                for td in row.select("td.odd")
            ]

            if len(labels) != len(values):
                raise RuntimeError(
                    "Estrutura de odds inesperada "
                    f"em {market_name}: "
                    f"labels={labels}, values={values}"
                )

            result.update(
                dict(zip(labels, values))
            )

    return result


def kickoff_iso_to_date(
    kickoff_utc_iso: str,
) -> str:
    value = str(
        kickoff_utc_iso or ""
    ).strip()

    if not value:
        raise ValueError(
            "kickoff_utc_iso vazio."
        )

    parsed = datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    )

    return parsed.date().isoformat()


def find_bwin_odds(
    *,
    home_team: str,
    away_team: str,
    footwin_prediction: str,
    kickoff_utc_iso: str,
    first_id: int,
    last_id: int,
) -> BwinOddsResult | None:
    match_date = kickoff_iso_to_date(
        kickoff_utc_iso
    )

    session = requests.Session()
    session.headers.update(HEADERS)

    for tipsterarea_id in range(
        first_id,
        last_id + 1,
    ):
        response = session.get(
            f"{BASE_URL}/match/{tipsterarea_id}",
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code != 200:
            continue

        if not page_matches_exact_fixture(
            response.text,
            home_team,
            away_team,
            match_date,
        ):
            continue

        odds = parse_bwin_odds(
            response.text,
        )

        prediction = str(
            footwin_prediction
        ).strip().upper()

        return BwinOddsResult(
            tipsterarea_id=tipsterarea_id,
            canonical_url=response.url,
            home_team=home_team,
            away_team=away_team,
            event_date=match_date,
            odds=odds,
            footwin_prediction=prediction,
            selected_odd=odds.get(prediction),
        )

    return None
