# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


REMOTE_ICS_URL = (
    "https://www.ligaportugal.pt/"
    "calendars-ics/ligaportugalbetclic.ics"
)

USER_AGENT = "FOOTWIN-SPORTS/1.0"


@dataclass
class Por1CalendarRefreshResult:
    checked_matches: int = 0
    updated_matches: int = 0
    unchanged_matches: int = 0
    missing_remote_matches: int = 0


def _download_remote_calendar() -> str:
    request = Request(
        REMOTE_ICS_URL,
        headers={"User-Agent": USER_AGENT},
    )

    with urlopen(request, timeout=60) as response:
        return response.read().decode(
            "utf-8",
            errors="replace",
        )


def _unfold_ics(text: str) -> str:
    return re.sub(
        r"\r?\n[ \t]",
        "",
        text,
    )


def _load_remote_dates(
    text: str,
) -> dict[str, str]:
    text = _unfold_ics(text)

    remote_dates: dict[str, str] = {}

    for block in re.findall(
        r"BEGIN:VEVENT\n(.*?)\nEND:VEVENT",
        text,
        flags=re.DOTALL,
    ):
        fields: dict[str, str] = {}

        for line in block.splitlines():
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.split(";", 1)[0]
            fields[key] = value.strip()

        source_url = fields.get("URL", "")
        date_raw = fields.get("DTSTART", "")

        if (
            "/match/20262027/"
            "ligaportugalbetclic/"
            not in source_url
        ):
            continue

        if not date_raw:
            continue

        try:
            parsed = datetime.strptime(
                date_raw,
                "%Y%m%dT%H%M%SZ",
            )
        except ValueError:
            continue

        remote_dates[source_url] = (
            parsed.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

    return remote_dates


def refresh_por1_calendar(
    database_path: str | Path,
    season_label: str = "2026/27",
) -> Por1CalendarRefreshResult:
    result = Por1CalendarRefreshResult()

    remote_text = _download_remote_calendar()
    remote_dates = _load_remote_dates(
        remote_text
    )

    connection = sqlite3.connect(
        str(database_path)
    )
    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            """
            SELECT
                match_id,
                match_date,
                source_url,
                status
            FROM matches
            WHERE league_id = 'POR1'
              AND season_label = ?
            ORDER BY match_id
            """,
            (season_label,),
        ).fetchall()

        result.checked_matches = len(rows)

        connection.execute(
            "BEGIN IMMEDIATE"
        )

        for row in rows:
            source_url = str(
                row["source_url"] or ""
            ).strip()

            new_date = remote_dates.get(
                source_url
            )

            if not new_date:
                result.missing_remote_matches += 1
                continue

            old_date = str(
                row["match_date"] or ""
            ).strip()

            if old_date == new_date:
                result.unchanged_matches += 1
                continue

            connection.execute(
                """
                UPDATE matches
                SET
                    match_date = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE match_id = ?
                """,
                (
                    new_date,
                    row["match_id"],
                ),
            )

            result.updated_matches += 1

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return result
