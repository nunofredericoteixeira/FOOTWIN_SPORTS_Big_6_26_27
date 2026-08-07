# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamCatalogEntry:
    team_id: str
    team_name: str
    short_name: str
    league_id: str
    country: str
    promoted: int
    promotion_method: str | None
    previous_division: str


def team(
    team_id: str,
    team_name: str,
    short_name: str,
    league_id: str,
    country: str,
    promoted: int = 0,
    promotion_method: str | None = None,
    previous_division: str | None = None,
) -> TeamCatalogEntry:
    return TeamCatalogEntry(
        team_id=team_id,
        team_name=team_name,
        short_name=short_name,
        league_id=league_id,
        country=country,
        promoted=promoted,
        promotion_method=promotion_method,
        previous_division=(
            previous_division
            if previous_division is not None
            else league_id
        ),
    )


TEAM_CATALOG: dict[
    str,
    tuple[TeamCatalogEntry, ...],
] = {
    # ==========================================================
    # PREMIER LEAGUE — 20 EQUIPAS
    # ==========================================================
    "ENG1": (
        team(
            "ENG1_ARSENAL",
            "Arsenal",
            "Arsenal",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_ASTON_VILLA",
            "Aston Villa",
            "Aston Villa",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_BOURNEMOUTH",
            "AFC Bournemouth",
            "Bournemouth",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_BRENTFORD",
            "Brentford",
            "Brentford",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_BRIGHTON",
            "Brighton & Hove Albion",
            "Brighton",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_CHELSEA",
            "Chelsea",
            "Chelsea",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_COVENTRY",
            "Coventry City",
            "Coventry",
            "ENG1",
            "England",
            1,
            "CHAMPION",
            "ENG2",
        ),
        team(
            "ENG1_CRYSTAL_PALACE",
            "Crystal Palace",
            "Crystal Palace",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_EV​ERTON".replace(
                "\u200b",
                "",
            ),
            "Everton",
            "Everton",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_FULHAM",
            "Fulham",
            "Fulham",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_HULL_CITY",
            "Hull City",
            "Hull City",
            "ENG1",
            "England",
            1,
            "PLAYOFF",
            "ENG2",
        ),
        team(
            "ENG1_IPSWICH",
            "Ipswich Town",
            "Ipswich",
            "ENG1",
            "England",
            1,
            "DIRECT",
            "ENG2",
        ),
        team(
            "ENG1_LEEDS",
            "Leeds United",
            "Leeds",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_LIVERPOOL",
            "Liverpool",
            "Liverpool",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_MANCHESTER_CITY",
            "Manchester City",
            "Man City",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_MANCHESTER_UNITED",
            "Manchester United",
            "Man United",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_NEWCASTLE",
            "Newcastle United",
            "Newcastle",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_NOTTINGHAM_FOREST",
            "Nottingham Forest",
            "Nott'm Forest",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_SUNDERLAND",
            "Sunderland",
            "Sunderland",
            "ENG1",
            "England",
        ),
        team(
            "ENG1_TOTTENHAM",
            "Tottenham Hotspur",
            "Tottenham",
            "ENG1",
            "England",
        ),
    ),

    # ==========================================================
    # LALIGA — 20 EQUIPAS
    # ==========================================================
    "ESP1": (
        team(
            "ESP1_ATHLETIC_CLUB",
            "Athletic Club",
            "Athletic",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_ATLETICO_MADRID",
            "Atlético de Madrid",
            "Atlético",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_OSASUNA",
            "CA Osasuna",
            "Osasuna",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_CELTA",
            "Celta",
            "Celta",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_ALAVES",
            "Deportivo Alavés",
            "Alavés",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_ELCHE",
            "Elche CF",
            "Elche",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_BARCELONA",
            "FC Barcelona",
            "Barcelona",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_GETAFE",
            "Getafe CF",
            "Getafe",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_LEVANTE",
            "Levante UD",
            "Levante",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_MALAGA",
            "Málaga CF",
            "Málaga",
            "ESP1",
            "Spain",
            1,
            "PLAYOFF",
            "ESP2",
        ),
        team(
            "ESP1_RACING",
            "R. Racing Club",
            "Racing",
            "ESP1",
            "Spain",
            1,
            "CHAMPION",
            "ESP2",
        ),
        team(
            "ESP1_RAYO_VALLECANO",
            "Rayo Vallecano",
            "Rayo",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_DEPORTIVO",
            "RC Deportivo",
            "Deportivo",
            "ESP1",
            "Spain",
            1,
            "DIRECT",
            "ESP2",
        ),
        team(
            "ESP1_ESPANYOL",
            "RCD Espanyol de Barcelona",
            "Espanyol",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_REAL_BETIS",
            "Real Betis",
            "Betis",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_REAL_MADRID",
            "Real Madrid",
            "Real Madrid",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_REAL_SOCIEDAD",
            "Real Sociedad",
            "Real Sociedad",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_SEVILLA",
            "Sevilla FC",
            "Sevilla",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_VALENCIA",
            "Valencia CF",
            "Valencia",
            "ESP1",
            "Spain",
        ),
        team(
            "ESP1_VILLARREAL",
            "Villarreal CF",
            "Villarreal",
            "ESP1",
            "Spain",
        ),
    ),

    # ==========================================================
    # SERIE A — 20 EQUIPAS
    # ==========================================================
    "ITA1": (
        team(
            "ITA1_ATALANTA",
            "Atalanta",
            "Atalanta",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_BOLOGNA",
            "Bologna",
            "Bologna",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_CAGLIARI",
            "Cagliari",
            "Cagliari",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_COMO",
            "Como",
            "Como",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_FIORENTINA",
            "Fiorentina",
            "Fiorentina",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_FROSINONE",
            "Frosinone",
            "Frosinone",
            "ITA1",
            "Italy",
            1,
            "DIRECT",
            "ITA2",
        ),
        team(
            "ITA1_GENOA",
            "Genoa",
            "Genoa",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_INTER",
            "Inter",
            "Inter",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_JUVENTUS",
            "Juventus",
            "Juventus",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_LAZIO",
            "Lazio",
            "Lazio",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_LECCE",
            "Lecce",
            "Lecce",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_MILAN",
            "AC Milan",
            "Milan",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_MONZA",
            "Monza",
            "Monza",
            "ITA1",
            "Italy",
            1,
            "PLAYOFF",
            "ITA2",
        ),
        team(
            "ITA1_NAPOLI",
            "Napoli",
            "Napoli",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_PARMA",
            "Parma",
            "Parma",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_ROMA",
            "Roma",
            "Roma",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_SASSUOLO",
            "Sassuolo",
            "Sassuolo",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_TORINO",
            "Torino",
            "Torino",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_UDINESE",
            "Udinese",
            "Udinese",
            "ITA1",
            "Italy",
        ),
        team(
            "ITA1_VENEZIA",
            "Venezia",
            "Venezia",
            "ITA1",
            "Italy",
            1,
            "CHAMPION",
            "ITA2",
        ),
    ),

    # ==========================================================
    # BUNDESLIGA — 18 EQUIPAS
    # ==========================================================
    "GER1": (
        team(
            "GER1_BAYERN",
            "FC Bayern München",
            "Bayern",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_DORTMUND",
            "Borussia Dortmund",
            "Dortmund",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_RB_LEIPZIG",
            "RB Leipzig",
            "RB Leipzig",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_STUTTGART",
            "VfB Stuttgart",
            "Stuttgart",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_HOFFENHEIM",
            "TSG Hoffenheim",
            "Hoffenheim",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_LEVERKUSEN",
            "Bayer 04 Leverkusen",
            "Leverkusen",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_FREIBURG",
            "SC Freiburg",
            "Freiburg",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_FRANKFURT",
            "Eintracht Frankfurt",
            "Frankfurt",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_AUGSBURG",
            "FC Augsburg",
            "Augsburg",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_MAINZ",
            "1. FSV Mainz 05",
            "Mainz",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_UNION_BERLIN",
            "1. FC Union Berlin",
            "Union Berlin",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_MONCHENGLADBACH",
            "Borussia Mönchengladbach",
            "M'gladbach",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_HAMBURG",
            "Hamburger SV",
            "Hamburg",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_COLOGNE",
            "1. FC Köln",
            "Köln",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_WERDER_BREMEN",
            "SV Werder Bremen",
            "Werder",
            "GER1",
            "Germany",
        ),
        team(
            "GER1_SCHALKE",
            "FC Schalke 04",
            "Schalke",
            "GER1",
            "Germany",
            1,
            "CHAMPION",
            "GER2",
        ),
        team(
            "GER1_ELVERSBERG",
            "SV Elversberg",
            "Elversberg",
            "GER1",
            "Germany",
            1,
            "DIRECT",
            "GER2",
        ),
        team(
            "GER1_PADERBORN",
            "SC Paderborn 07",
            "Paderborn",
            "GER1",
            "Germany",
            1,
            "PLAYOFF",
            "GER2",
        ),
    ),

    # ==========================================================
    # LIGUE 1 — 18 EQUIPAS
    # ==========================================================
    "FRA1": (
        team(
            "FRA1_ANGERS",
            "Angers SCO",
            "Angers",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_AUXERRE",
            "AJ Auxerre",
            "Auxerre",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_BREST",
            "Stade Brestois 29",
            "Brest",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_LE_HAVRE",
            "Le Havre AC",
            "Le Havre",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_LE_MANS",
            "Le Mans FC",
            "Le Mans",
            "FRA1",
            "France",
            1,
            "DIRECT",
            "FRA2",
        ),
        team(
            "FRA1_LENS",
            "RC Lens",
            "Lens",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_LILLE",
            "LOSC Lille",
            "Lille",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_LORIENT",
            "FC Lorient",
            "Lorient",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_LYON",
            "Olympique Lyonnais",
            "Lyon",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_MARSEILLE",
            "Olympique de Marseille",
            "Marseille",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_MONACO",
            "AS Monaco",
            "Monaco",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_NICE",
            "OGC Nice",
            "Nice",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_PSG",
            "Paris Saint-Germain",
            "Paris SG",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_PARIS_FC",
            "Paris FC",
            "Paris FC",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_RENNES",
            "Stade Rennais FC",
            "Rennes",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_STRASBOURG",
            "RC Strasbourg Alsace",
            "Strasbourg",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_TOULOUSE",
            "Toulouse FC",
            "Toulouse",
            "FRA1",
            "France",
        ),
        team(
            "FRA1_TROYES",
            "ESTAC Troyes",
            "Troyes",
            "FRA1",
            "France",
            1,
            "CHAMPION",
            "FRA2",
        ),
    ),

    # ==========================================================
    # LIGA PORTUGAL — 18 EQUIPAS
    # ==========================================================
    "POR1": (
        team(
            "POR1_ACADEMICO",
            "Académico de Viseu FC",
            "Académico",
            "POR1",
            "Portugal",
            1,
            "CHAMPION",
            "POR2",
        ),
        team(
            "POR1_AROUCA",
            "FC Arouca",
            "Arouca",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_BENFICA",
            "SL Benfica",
            "Benfica",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_BRAGA",
            "SC Braga",
            "Braga",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_CASA_PIA",
            "Casa Pia AC",
            "Casa Pia",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_ESTORIL",
            "Estoril Praia",
            "Estoril",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_ESTRELA_AMADORA",
            "Estrela Amadora",
            "Estrela",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_FAMALICAO",
            "FC Famalicão",
            "Famalicão",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_ALVERCA",
            "FC Alverca",
            "Alverca",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_GIL_VICENTE",
            "Gil Vicente FC",
            "Gil Vicente",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_MARITIMO",
            "Marítimo M.",
            "Marítimo",
            "POR1",
            "Portugal",
            1,
            "DIRECT",
            "POR2",
        ),
        team(
            "POR1_MOREIRENSE",
            "Moreirense FC",
            "Moreirense",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_NACIONAL",
            "CD Nacional",
            "Nacional",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_PORTO",
            "FC Porto",
            "FC Porto",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_RIO_AVE",
            "Rio Ave FC",
            "Rio Ave",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_SANTA_CLARA",
            "CD Santa Clara",
            "Santa Clara",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_SPORTING",
            "Sporting CP",
            "Sporting",
            "POR1",
            "Portugal",
        ),
        team(
            "POR1_VITORIA_SC",
            "Vitória SC",
            "Vitória SC",
            "POR1",
            "Portugal",
        ),
    ),
}


EXPECTED_COUNTS = {
    "ENG1": 20,
    "ESP1": 20,
    "ITA1": 20,
    "GER1": 18,
    "FRA1": 18,
    "POR1": 18,
}


EXPECTED_COUNTRIES = {
    "ENG1": "England",
    "ESP1": "Spain",
    "ITA1": "Italy",
    "GER1": "Germany",
    "FRA1": "France",
    "POR1": "Portugal",
}


VALID_PROMOTION_METHODS = {
    "CHAMPION",
    "DIRECT",
    "PLAYOFF",
}


def get_team_catalog(
    league_id: str | None = None,
) -> tuple[TeamCatalogEntry, ...]:
    if league_id is None:
        return tuple(
            entry
            for current_league_id
            in EXPECTED_COUNTS
            for entry
            in TEAM_CATALOG[current_league_id]
        )

    final_league_id = (
        str(league_id)
        .strip()
        .upper()
    )

    if final_league_id not in TEAM_CATALOG:
        raise KeyError(
            f"Liga inexistente no catálogo: "
            f"{final_league_id}"
        )

    return TEAM_CATALOG[
        final_league_id
    ]


def validate_team_catalog() -> None:
    actual_leagues = set(
        TEAM_CATALOG
    )

    expected_leagues = set(
        EXPECTED_COUNTS
    )

    if actual_leagues != expected_leagues:
        missing = (
            expected_leagues
            - actual_leagues
        )

        extra = (
            actual_leagues
            - expected_leagues
        )

        raise RuntimeError(
            "Ligas inválidas no catálogo. "
            f"Em falta: {sorted(missing)}; "
            f"adicionais: {sorted(extra)}."
        )

    all_team_ids: list[str] = []
    all_team_names: list[
        tuple[str, str]
    ] = []

    for league_id, expected_count in (
        EXPECTED_COUNTS.items()
    ):
        entries = TEAM_CATALOG[
            league_id
        ]

        if len(entries) != expected_count:
            raise RuntimeError(
                f"{league_id}: encontradas "
                f"{len(entries)} equipas; "
                f"esperadas {expected_count}."
            )

        expected_country = (
            EXPECTED_COUNTRIES[
                league_id
            ]
        )

        for entry in entries:
            if not entry.team_id.strip():
                raise RuntimeError(
                    f"{league_id}: team_id vazio."
                )

            if not entry.team_name.strip():
                raise RuntimeError(
                    f"{entry.team_id}: "
                    "team_name vazio."
                )

            if not entry.short_name.strip():
                raise RuntimeError(
                    f"{entry.team_id}: "
                    "short_name vazio."
                )

            if (
                entry.league_id
                != league_id
            ):
                raise RuntimeError(
                    f"{entry.team_id}: "
                    "league_id incorreto."
                )

            if (
                entry.country
                != expected_country
            ):
                raise RuntimeError(
                    f"{entry.team_id}: "
                    "country incorreto."
                )

            if entry.promoted not in {
                0,
                1,
            }:
                raise RuntimeError(
                    f"{entry.team_id}: "
                    "promoted deve ser 0 ou 1."
                )

            if entry.promoted == 1:
                if (
                    entry.promotion_method
                    not in
                    VALID_PROMOTION_METHODS
                ):
                    raise RuntimeError(
                        f"{entry.team_id}: "
                        "método de promoção "
                        "inválido."
                    )

                if (
                    entry.previous_division
                    == league_id
                ):
                    raise RuntimeError(
                        f"{entry.team_id}: "
                        "equipa promovida não pode "
                        "ter a mesma divisão anterior."
                    )

            else:
                if (
                    entry.promotion_method
                    is not None
                ):
                    raise RuntimeError(
                        f"{entry.team_id}: "
                        "equipa não promovida não "
                        "deve ter método de promoção."
                    )

                if (
                    entry.previous_division
                    != league_id
                ):
                    raise RuntimeError(
                        f"{entry.team_id}: "
                        "divisão anterior incorreta."
                    )

            all_team_ids.append(
                entry.team_id
            )

            all_team_names.append(
                (
                    league_id,
                    entry.team_name.casefold(),
                )
            )

    if len(all_team_ids) != 114:
        raise RuntimeError(
            "Total global incorreto: "
            f"{len(all_team_ids)} equipas. "
            "Esperadas: 114."
        )

    if (
        len(all_team_ids)
        != len(set(all_team_ids))
    ):
        raise RuntimeError(
            "Existem team_id duplicados "
            "no catálogo."
        )

    if (
        len(all_team_names)
        != len(set(all_team_names))
    ):
        raise RuntimeError(
            "Existem nomes de equipas "
            "duplicados dentro da mesma liga."
        )


validate_team_catalog()
