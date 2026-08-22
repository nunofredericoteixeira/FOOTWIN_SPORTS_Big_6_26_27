from __future__ import annotations

import math
import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo


LEAGUE_METADATA = {
    "POR1": {"name": "Portugal", "timezone": "Europe/Lisbon", "flag": "🇵🇹"},
    "ENG1": {"name": "Inglaterra", "timezone": "Europe/London", "flag": "🏴"},
    "ESP1": {"name": "Espanha", "timezone": "Europe/Madrid", "flag": "🇪🇸"},
    "FRA1": {"name": "França", "timezone": "Europe/Paris", "flag": "🇫🇷"},
    "ITA1": {"name": "Itália", "timezone": "Europe/Rome", "flag": "🇮🇹"},
    "GER1": {"name": "Alemanha", "timezone": "Europe/Berlin", "flag": "🇩🇪"},
}

SEASON_LABEL = "2026/27"


UTC_NAIVE_LEAGUES = {
    "ENG1",
    "ESP1",
    "FRA1",
    "ITA1",
    "GER1",
}


def match_datetime_utc(
    league_id: str,
    value: str,
) -> datetime:
    parsed = datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )

    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)

    league = str(league_id).upper()

    if league in UTC_NAIVE_LEAGUES:
        return parsed.replace(
            tzinfo=timezone.utc
        )

    metadata = LEAGUE_METADATA.get(
        league,
        {
            "timezone": "Europe/Lisbon",
        },
    )

    return parsed.replace(
        tzinfo=ZoneInfo(metadata["timezone"])
    ).astimezone(timezone.utc)



from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    send_from_directory,
    session,
    url_for,
)

from src.services.final_result_service import run_final_result_update
from src.services.prediction_evaluation_service import run_prediction_evaluation
from src.services.supabase_auth_service import (
    SupabaseAuthError,
    login_user,
    logout_user,
    refresh_session,
    register_user,
)
from src.services.supabase_betting_service import (
    SupabaseBettingError,
    load_bankroll,
    load_user_bets,
    save_bankroll,
    save_pending_bet,
    settle_bet,
)
from src.services.supabase_bwin_odds_service import (
    SupabaseBwinOddsError,
    load_bwin_odds_for_matches,
)

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "footwin_sports.db"

load_dotenv(dotenv_path=BASE_DIR / ".env")

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


def initialize_betting_tables() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_bankrolls (
                user_id TEXT PRIMARY KEY,
                initial_bankroll REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                match_id TEXT NOT NULL,
                odd REAL,
                stake REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                prudent_prediction TEXT,
                UNIQUE (user_id, match_id),
                FOREIGN KEY (match_id) REFERENCES matches(match_id)
            );

            CREATE INDEX IF NOT EXISTS idx_user_bets_user_id
            ON user_bets(user_id);
            """
        )

        prediction_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(match_predictions)"
            ).fetchall()
        }

        required_prediction_columns = {
            "prediction_stage": "TEXT NOT NULL DEFAULT 'PRE_MATCH'",
            "prediction_version": "INTEGER NOT NULL DEFAULT 1",
            "parent_prediction_id": "TEXT",
            "lineup_id": "TEXT",
            "lineup_hash": "TEXT",
            "lineup_confirmed": "INTEGER NOT NULL DEFAULT 0",
            "lineup_data_quality": "TEXT NOT NULL DEFAULT 'NOT_APPLICABLE'",
            "is_current": "INTEGER NOT NULL DEFAULT 1",
            "input_snapshot_json": "TEXT",
            "superseded_at": "TEXT",
        }

        for column_name, column_definition in required_prediction_columns.items():
            if column_name not in prediction_columns:
                connection.execute(
                    f"ALTER TABLE match_predictions "
                    f"ADD COLUMN {column_name} {column_definition}"
                )


initialize_betting_tables()

HTML_TEMPLATE = """
<!doctype html>
<html lang="pt">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>FOOTWIN SPORTS — Prognósticos</title>
    <style>
        :root {
            color-scheme: dark;
            --bg: #07111f;
            --panel: #101d2f;
            --panel-2: #16263c;
            --text: #f4f7fb;
            --muted: #9fb0c6;
            --accent: #36c98f;
            --border: #263b57;
        }

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            min-height: 100vh;
            background:
                linear-gradient(rgba(2, 8, 16, 0.78), rgba(2, 8, 16, 0.88)),
                url("assets/footwin-background.jpg") center center / cover fixed no-repeat,
                var(--bg);
            color: var(--text);
            font-family: Inter, Arial, sans-serif;
        }

        .container {
            width: min(1180px, calc(100% - 32px));
            margin: 0 auto;
            padding: 38px 0 60px;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: end;
            gap: 24px;
            margin-bottom: 28px;
        }

        h1 {
            margin: 0;
            font-size: clamp(28px, 5vw, 48px);
            letter-spacing: -1.5px;
        }

        .subtitle,
        .updated {
            color: var(--muted);
        }

        .top-controls {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 10px;
            margin-bottom: 16px;
        }

        .top-control-button,
        .league-filter-button,
        .summary-close-button {
            border: 1px solid rgba(255, 255, 255, 0.14);
            background: rgba(16, 29, 47, 0.92);
            color: var(--text);
            cursor: pointer;
            font: inherit;
            font-weight: 850;
            transition:
                border-color 0.18s ease,
                background 0.18s ease,
                transform 0.18s ease;
        }

        .top-control-button {
            min-height: 42px;
            padding: 9px 15px;
            border-radius: 12px;
        }

        .top-control-button:hover,
        .league-filter-button:hover,
        .summary-close-button:hover {
            border-color: var(--accent);
        }

        .league-filter-group {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 7px;
            margin-left: auto;
        }

        .league-filter-button {
            display: inline-flex;
            min-width: 44px;
            min-height: 42px;
            align-items: center;
            justify-content: center;
            padding: 7px 10px;
            border-radius: 12px;
            font-size: 19px;
        }

        .league-filter-button.all-leagues {
            min-width: auto;
            padding-inline: 14px;
            font-size: 13px;
        }

        .league-filter-button.active {
            color: #042116;
            background: var(--accent);
            border-color: var(--accent);
        }

        .league-filter-england {
            width: 27px;
            height: 17px;
            border-radius: 2px;
        }

        .league-dashboard {
            margin-bottom: 24px;
        }

        .league-dashboard[hidden] {
            display: none;
        }

        .league-dashboard-card {
            padding: 20px;
            background: rgba(16, 29, 47, 0.92);
            border: 1px solid var(--border);
            border-radius: 18px;
            box-shadow: 0 18px 48px rgba(0, 0, 0, 0.22);
        }

        .league-dashboard-card[hidden] {
            display: none;
        }

        .league-dashboard-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 14px;
            margin-bottom: 18px;
        }

        .league-dashboard-title {
            display: flex;
            align-items: center;
            gap: 9px;
        }

        .league-dashboard-title strong {
            font-size: 18px;
        }

        .league-dashboard-title > span:last-child {
            color: var(--muted);
            font-size: 13px;
            font-weight: 800;
        }

        .league-dashboard-stats {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 10px;
            margin-bottom: 16px;
        }

        .league-stat {
            padding: 12px;
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.03);
        }

        .league-stat span {
            display: block;
            margin-bottom: 5px;
            color: var(--muted);
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
        }

        .league-stat strong {
            font-size: 18px;
        }

        .league-model-current {
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            gap: 8px;
            margin-bottom: 14px;
            padding: 12px;
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 12px;
        }

        .league-model-current > span {
            color: var(--muted);
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
        }

        .league-model-current small {
            color: var(--muted);
        }

        .league-model-history {
            display: grid;
            gap: 8px;
        }

        .league-model-history-title {
            color: var(--muted);
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
        }

        .league-model-row {
            display: grid;
            grid-template-columns:
                minmax(180px, 1fr)
                minmax(160px, auto);
            gap: 12px;
            align-items: center;
            padding: 10px 12px;
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 11px;
            background: rgba(255, 255, 255, 0.025);
        }

        .league-model-row > div:last-child {
            text-align: right;
        }

        .league-model-row small,
        .league-model-row span {
            display: block;
            color: var(--muted);
            font-size: 11px;
        }

        .league-model-empty {
            color: var(--muted);
            font-size: 13px;
        }

        .summary {
            display: none;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .summary.open {
            display: grid;
        }

        .summary-card,
        .match-card {
            background: rgba(16, 29, 47, 0.92);
            border: 1px solid var(--border);
            border-radius: 18px;
            box-shadow: 0 18px 48px rgba(0, 0, 0, 0.22);
        }

        .summary-card {
            position: relative;
            padding: 20px;
        }

        .summary-card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 12px;
        }

        .summary-card-title {
            color: var(--muted);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.9px;
        }

        .summary-close-button {
            width: 34px;
            height: 34px;
            padding: 0;
            border-radius: 10px;
            font-size: 20px;
            line-height: 1;
        }

        .summary-card > span {
            display: block;
            margin-bottom: 12px;
            color: var(--muted);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.9px;
        }

        .summary-list {
            display: grid;
            gap: 8px;
        }

        .summary-row {
            display: grid;
            grid-template-columns: 110px minmax(120px, 1fr) auto;
            gap: 10px;
            align-items: center;
            min-height: 42px;
            padding: 8px 10px;
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 11px;
            background: rgba(255, 255, 255, 0.03);
        }

        .summary-league {
            font-size: 14px;
            font-weight: 900;
        }

        .summary-row strong {
            display: block;
            margin: 0;
            font-size: 15px;
        }

        .summary-row small {
            display: block;
            margin: 0;
            color: var(--muted);
            font-size: 11px;
            font-weight: 800;
            text-align: right;
        }

        .summary-row small.changed {
            color: #ffd166;
        }

        .summary-row small.unchanged {
            color: var(--accent);
        }

        .matches {
            display: grid;
            gap: 16px;
        }

        .match-card {
            display: grid;
            grid-template-columns: minmax(92px, 10%) 1fr;
            padding: 0;
            overflow: hidden;
        }

        .league-rail {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 8px;
            padding: 18px 8px;
            border-right: 1px solid rgba(255, 255, 255, 0.08);
            background:
                linear-gradient(
                    180deg,
                    rgba(27, 47, 73, 0.96),
                    rgba(11, 23, 38, 0.98)
                );
            text-align: center;
        }

        .league-flag {
            font-size: 40px;
            line-height: 1;
        }

        .league-flag-image {
            width: 48px;
            height: 29px;
            object-fit: cover;
            border-radius: 3px;
            box-shadow: 0 0 8px rgba(255, 255, 255, 0.18);
        }

        .summary-flag-image {
            width: 25px;
            height: 15px;
            object-fit: cover;
            border-radius: 2px;
            vertical-align: middle;
            margin-right: 5px;
        }

        .england-flag {
            position: relative;
            display: inline-block;
            background: #ffffff;
            overflow: hidden;
            flex: 0 0 auto;
        }

        .england-flag::before,
        .england-flag::after {
            content: "";
            position: absolute;
            background: #ce1124;
        }

        .england-flag::before {
            left: 41.6667%;
            top: 0;
            width: 16.6667%;
            height: 100%;
        }

        .england-flag::after {
            left: 0;
            top: 36.1111%;
            width: 100%;
            height: 27.7778%;
        }

        .england-flag-summary {
            width: 25px;
            height: 15px;
            border-radius: 2px;
            vertical-align: middle;
            margin-right: 5px;
        }

        .england-flag-large {
            width: 48px;
            height: 29px;
            border-radius: 3px;
            box-shadow: 0 0 8px rgba(255, 255, 255, 0.18);
        }

        .league-code {
            font-size: 14px;
            font-weight: 950;
            letter-spacing: 0.07em;
        }

        .league-country {
            color: var(--muted);
            font-size: 10px;
            font-weight: 800;
            text-transform: uppercase;
        }

        .match-content {
            padding: 22px;
        }

        .match-top {
            display: flex;
            justify-content: space-between;
            gap: 18px;
            align-items: center;
            margin-bottom: 18px;
        }

        .teams {
            font-size: 21px;
            font-weight: 750;
        }

        .date {
            color: var(--muted);
            font-size: 14px;
            white-space: nowrap;
        }

        .probabilities {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
        }

        .probability {
            padding: 14px;
            background: var(--panel-2);
            border-radius: 13px;
            text-align: center;
        }

        .probability span {
            display: block;
            color: var(--muted);
            font-size: 13px;
        }

        .probability strong {
            display: block;
            font-size: 21px;
        }

        .probability-value {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            min-height: 48px;
            margin-top: 6px;
        }

        .team-logo {
            width: 42px;
            height: 42px;
            flex: 0 0 42px;
            object-fit: contain;
            object-position: center;
            background: transparent;
        }

        .probability-value.home {
            justify-content: center;
        }

        .probability-value.away {
            justify-content: center;
        }

        .prediction {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 14px;
            margin-top: 17px;
            padding: 17px 14px 14px;
            border-top: 1px solid var(--border);
            border-radius: 14px;
            transition:
                background 0.25s ease,
                border-color 0.25s ease,
                box-shadow 0.25s ease;
        }

        .prediction.result-pending {
            margin-left: -14px;
            margin-right: -14px;
        }

        .prediction.result-green {
            margin-left: -14px;
            margin-right: -14px;
            color: #d9ffe9;
            background: rgba(0, 255, 136, 0.10);
            border: 1px solid rgba(0, 255, 136, 0.72);
            box-shadow:
                0 0 8px rgba(0, 255, 136, 0.72),
                0 0 22px rgba(0, 255, 136, 0.40),
                inset 0 0 18px rgba(0, 255, 136, 0.08);
        }

        .prediction.result-red {
            margin-left: -14px;
            margin-right: -14px;
            color: #ffe0e0;
            background: rgba(255, 37, 37, 0.11);
            border: 1px solid rgba(255, 55, 55, 0.80);
            box-shadow:
                0 0 8px rgba(255, 45, 45, 0.78),
                0 0 22px rgba(255, 35, 35, 0.44),
                inset 0 0 18px rgba(255, 35, 35, 0.09);
        }

        .prediction.result-gold {
            margin-left: -14px;
            margin-right: -14px;
            color: #fff7cf;
            background: rgba(255, 204, 0, 0.12);
            border: 1px solid rgba(255, 215, 0, 0.88);
            box-shadow:
                0 0 8px rgba(255, 215, 0, 0.92),
                0 0 24px rgba(255, 184, 0, 0.52),
                inset 0 0 20px rgba(255, 215, 0, 0.10);
        }

        .prediction.result-green .badge {
            background: #00ff88;
            box-shadow: 0 0 14px rgba(0, 255, 136, 0.85);
        }

        .prediction.result-red .badge {
            background: #ff3535;
            color: #ffffff;
            box-shadow: 0 0 14px rgba(255, 53, 53, 0.88);
        }

        .prediction.result-gold .badge {
            background: #ffd700;
            color: #382b00;
            box-shadow: 0 0 15px rgba(255, 215, 0, 0.95);
        }

        .prediction.result-green .subtitle,
        .prediction.result-green .score,
        .prediction.result-red .subtitle,
        .prediction.result-red .score,
        .prediction.result-gold .subtitle,
        .prediction.result-gold .score {
            color: inherit;
        }

        .actual-result {
            display: block;
            margin-top: 5px;
            font-size: 13px;
            font-weight: 700;
        }

        .badge {
            display: inline-flex;
            min-width: 48px;
            min-height: 42px;
            align-items: center;
            justify-content: center;
            padding: 8px 14px;
            border-radius: 12px;
            background: var(--accent);
            color: #042116;
            font-size: 21px;
            font-weight: 900;
        }

        .score {
            color: var(--muted);
        }

        .betting-fields {
        display: grid;
        grid-template-columns:
            minmax(120px, 0.7fr)
            minmax(140px, 0.9fr)
            minmax(150px, 1fr);
        gap: 12px;
        align-items: end;
        margin: 16px 0;
        padding: 14px;
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 14px;
        background: rgba(0, 0, 0, 0.22);
    }

    .betting-field {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .betting-field label {
        color: var(--muted);
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    .betting-field > input,
    .bet-money-input {
        min-height: 44px;
        border: 1px solid rgba(255, 255, 255, 0.16);
        border-radius: 11px;
        background: rgba(0, 0, 0, 0.28);
    }

    .betting-field > input {
        width: 100%;
        padding: 10px 12px;
        outline: 0;
        color: #ffffff;
        font: inherit;
        font-weight: 800;
    }

    .betting-field > input:focus,
    .bet-money-input:focus-within {
        border-color: var(--accent);
        box-shadow: 0 0 10px rgba(0, 255, 136, 0.20);
    }

    .bet-money-input {
        display: flex;
        align-items: center;
        overflow: hidden;
    }

    .bet-money-input span {
        padding-left: 12px;
        color: var(--accent);
        font-weight: 900;
    }

    .bet-money-input input {
        width: 100%;
        min-width: 0;
        padding: 10px 12px 10px 7px;
        border: 0;
        outline: 0;
        background: transparent;
        color: #ffffff;
        font: inherit;
        font-weight: 800;
    }

    .betting-field input:disabled {
        cursor: not-allowed;
        opacity: 0.58;
    }

    .bet-status {
        display: flex;
        min-height: 44px;
        align-items: center;
        justify-content: center;
        padding: 10px 13px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 11px;
        color: var(--muted);
        font-size: 13px;
        font-weight: 900;
        text-align: center;
    }

    .bet-status.won {
        color: #00ff88;
        border-color: rgba(0, 255, 136, 0.48);
        background: rgba(0, 255, 136, 0.08);
        box-shadow: 0 0 12px rgba(0, 255, 136, 0.16);
    }

    .bet-status.lost {
        color: #ff6b6b;
        border-color: rgba(255, 65, 65, 0.48);
        background: rgba(255, 55, 55, 0.08);
        box-shadow: 0 0 12px rgba(255, 55, 55, 0.14);
    }

    .bankroll-panel {
        position: sticky;
        top: 10px;
        z-index: 50;
        display: grid;
        grid-template-columns:
            minmax(190px, 1fr)
            minmax(135px, 0.58fr)
            minmax(220px, 1.15fr)
            minmax(170px, 0.82fr)
            auto;
        gap: 14px;
        align-items: end;
        margin: 0 0 24px;
        padding: 18px;
        border: 1px solid rgba(0, 255, 136, 0.32);
        border-radius: 18px;
        background: rgba(4, 20, 15, 0.96);
        box-shadow:
            0 10px 30px rgba(0, 0, 0, 0.42),
            0 0 20px rgba(0, 255, 136, 0.10),
            inset 0 0 20px rgba(0, 255, 136, 0.04);
        backdrop-filter: blur(10px);
    }

    .bankroll-field,
    .bankroll-balance,
    .bankroll-accuracy {
        display: flex;
        flex-direction: column;
        gap: 7px;
    }

    .bankroll-field label,
    .bankroll-balance span,
    .bankroll-accuracy span {
        color: var(--muted);
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    .bankroll-mode select {
        min-height: 42px;
        padding: 8px 10px;
        border: 1px solid rgba(255, 255, 255, 0.13);
        border-radius: 10px;
        background: rgba(0, 0, 0, 0.22);
        color: #dbe5ef;
        font: inherit;
        font-size: 13px;
        font-weight: 700;
    }

    .bankroll-accuracy {
        padding: 10px 13px;
        border: 1px solid rgba(255, 209, 102, 0.22);
        border-radius: 12px;
        background: rgba(255, 209, 102, 0.04);
    }

    .bankroll-accuracy strong {
        color: #ffd166;
        font-size: 27px;
        font-weight: 950;
    }

    .money-input {
        display: flex;
        min-height: 48px;
        align-items: center;
        overflow: hidden;
        border: 1px solid rgba(255, 255, 255, 0.18);
        border-radius: 12px;
        background: rgba(0, 0, 0, 0.30);
    }

    .money-input:focus-within {
        border-color: var(--accent);
        box-shadow: 0 0 12px rgba(0, 255, 136, 0.22);
    }

    .money-input span {
        padding-left: 15px;
        color: var(--accent);
        font-size: 18px;
        font-weight: 900;
    }

    .money-input input {
        width: 100%;
        min-width: 0;
        padding: 12px 14px 12px 8px;
        border: 0;
        outline: 0;
        background: transparent;
        color: #ffffff;
        font: inherit;
        font-size: 18px;
        font-weight: 800;
    }

    .bankroll-balance {
        padding: 10px 14px;
        border: 1px solid rgba(0, 255, 136, 0.22);
        border-radius: 12px;
        background: rgba(0, 255, 136, 0.05);
    }

    .bankroll-balance strong {
        display: flex;
        min-height: 48px;
        align-items: center;
        color: #00ffae;
        font-size: 34px;
        font-weight: 950;
        text-shadow:
            0 0 10px rgba(0, 255, 174, 0.50),
            0 0 22px rgba(0, 255, 174, 0.18);
    }

    #save-betting-state {
        min-height: 48px;
        padding: 11px 20px;
        border: 0;
        border-radius: 12px;
        background: var(--accent);
        color: #042116;
        cursor: pointer;
        font: inherit;
        font-weight: 900;
        transition:
            transform 0.15s ease,
            box-shadow 0.15s ease,
            opacity 0.15s ease;
    }

    #save-betting-state:hover {
        transform: translateY(-1px);
        box-shadow: 0 0 16px rgba(0, 255, 136, 0.42);
    }

    #save-betting-state:disabled {
        cursor: wait;
        opacity: 0.65;
        transform: none;
    }

    #bankroll-message {
        grid-column: 1 / -1;
        min-height: 18px;
        color: var(--muted);
        font-size: 13px;
        font-weight: 700;
    }

    #bankroll-message.success {
        color: var(--accent);
    }

    #bankroll-message.error {
        color: #ff6b6b;
    }

    .empty {
            padding: 40px;
            text-align: center;
            background: var(--panel);
            border-radius: 18px;
            color: var(--muted);
        }

        @media (max-width: 720px) {
            header,
            .match-top,
            .prediction {
                align-items: flex-start;
                flex-direction: column;
            }

            .summary {
                grid-template-columns: 1fr;
            }

            .league-dashboard-stats {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .league-model-row {
                grid-template-columns: 1fr;
            }

            .league-model-row > div:last-child {
                text-align: left;
            }

            .bankroll-panel {
                grid-template-columns: 1fr;
                align-items: stretch;
            }

            .betting-fields {
                grid-template-columns: 1fr;
                align-items: stretch;
            }

            #bankroll-message {
                grid-column: auto;
            }

            .probabilities {
                gap: 8px;
            }

            .probability {
                padding: 11px 7px;
            }

            .probability-value {
                gap: 5px;
                min-height: 38px;
            }

            .team-logo {
                width: 32px;
                height: 32px;
                flex-basis: 32px;
            }

            .probability strong {
                font-size: 17px;
            }

            .match-card {
                padding: 17px;
            }
        }
    </style>
</head>
<body>
<div class="container">
    <header>
        <div class="subtitle">FOOTWIN SPORTS</div>
        <div class="updated">Atualizado: {{ updated_at }}</div>
    </header>

    {% if matches %}
        <section class="top-controls">
            <button
                class="top-control-button"
                type="button"
                data-summary-target="next-round-summary"
            >
                Próxima Jornada
            </button>

            <button
                class="top-control-button"
                type="button"
                data-summary-target="versions-summary"
            >
                Versões por campeonato
            </button>

            <div
                class="league-filter-group"
                aria-label="Filtrar por campeonato"
            >
                <button
                    class="league-filter-button all-leagues active"
                    type="button"
                    data-league-filter="ALL"
                >
                    Todos
                </button>

                <button
                    class="league-filter-button"
                    type="button"
                    data-league-filter="POR1"
                    title="Portugal"
                    aria-label="Portugal"
                >
                    🇵🇹
                </button>

                <button
                    class="league-filter-button"
                    type="button"
                    data-league-filter="ENG1"
                    title="Inglaterra"
                    aria-label="Inglaterra"
                >
                    <span
                        class="england-flag league-filter-england"
                        role="img"
                        aria-label="Inglaterra"
                    ></span>
                </button>

                <button
                    class="league-filter-button"
                    type="button"
                    data-league-filter="ESP1"
                    title="Espanha"
                    aria-label="Espanha"
                >
                    🇪🇸
                </button>

                <button
                    class="league-filter-button"
                    type="button"
                    data-league-filter="FRA1"
                    title="França"
                    aria-label="França"
                >
                    🇫🇷
                </button>

                <button
                    class="league-filter-button"
                    type="button"
                    data-league-filter="ITA1"
                    title="Itália"
                    aria-label="Itália"
                >
                    🇮🇹
                </button>

                <button
                    class="league-filter-button"
                    type="button"
                    data-league-filter="GER1"
                    title="Alemanha"
                    aria-label="Alemanha"
                >
                    🇩🇪
                </button>
            </div>
        </section>

        <section
            class="league-dashboard"
            id="league-dashboard"
            hidden
        >
            {% for item in league_summaries %}
                <article
                    class="league-dashboard-card"
                    data-league-dashboard="{{ item.league_id }}"
                    hidden
                >
                    <div class="league-dashboard-header">
                        <div>
                            <div class="league-dashboard-title">
                                {% if item.league_id == "ENG1" %}
                                    <span
                                        class="england-flag england-flag-summary"
                                        role="img"
                                        aria-label="Inglaterra"
                                    ></span>
                                {% elif item.league_id == "ESP1" %}
                                    <img
                                        class="summary-flag-image"
                                        src="/assets/spain-flag.svg"
                                        alt="Espanha"
                                    >
                                {% else %}
                                    {{ item.flag }}
                                {% endif %}

                                <strong>
                                    {{ item.league_id }}
                                </strong>

                                <span>
                                    {{ item.country_name }}
                                </span>
                            </div>
                        </div>

                        <button
                            class="summary-close-button"
                            type="button"
                            id="close-league-dashboard"
                            aria-label="Fechar resumo do campeonato"
                        >
                            ×
                        </button>
                    </div>

                    <div class="league-dashboard-stats">
                        <div class="league-stat">
                            <span>Jornada atual</span>
                            <strong>
                                {% if item.current_round is not none %}
                                    {{ item.current_round }}
                                {% else %}
                                    —
                                {% endif %}
                            </strong>
                        </div>

                        <div class="league-stat">
                            <span>Disputados</span>
                            <strong>
                                {{ item.played_matches }}
                            </strong>
                        </div>

                        <div class="league-stat">
                            <span>Por disputar</span>
                            <strong>
                                {{ item.remaining_matches }}
                            </strong>
                        </div>

                        <div class="league-stat">
                            <span>Total</span>
                            <strong>
                                {{ item.total_matches }}
                            </strong>
                        </div>

                        <div class="league-stat">
                            <span>Eficácia</span>
                            <strong>
                                {{ item.accuracy_label }}
                            </strong>
                        </div>
                    </div>

                    <div class="league-model-current">
                        <span>Modelo ativo</span>

                        {% if item.active_model %}
                            <strong>
                                {{ item.active_model.display_version }}
                            </strong>

                            <small>
                                {{ item.active_model.model_version }}
                            </small>
                        {% else %}
                            <strong>
                                Sem modelo registado
                            </strong>
                        {% endif %}
                    </div>

                    <div class="league-model-history">
                        <span class="league-model-history-title">
                            Histórico de versões
                        </span>

                        {% if item.model_history %}
                            {% for version in item.model_history %}
                                <div class="league-model-row">
                                    <div>
                                        <strong>
                                            {{ version.display_version }}
                                        </strong>

                                        <small>
                                            {{ version.model_version }}
                                        </small>
                                    </div>

                                    <div>
                                        <span>
                                            {{ version.evaluated_matches }}
                                            jogos avaliados
                                        </span>

                                        <strong>
                                            {{ version.accuracy_label }}
                                        </strong>
                                    </div>
                                </div>
                            {% endfor %}
                        {% else %}
                            <div class="league-model-empty">
                                Sem versões registadas.
                            </div>
                        {% endif %}
                    </div>
                </article>
            {% endfor %}
        </section>

        <section
            class="summary"
            id="next-round-summary"
        >
            <article class="summary-card">
                <div class="summary-card-header">
                    <span class="summary-card-title">
                        Próxima jornada
                    </span>

                    <button
                        class="summary-close-button"
                        type="button"
                        data-summary-close="next-round-summary"
                        aria-label="Fechar Próxima Jornada"
                    >
                        ×
                    </button>
                </div>

                <div class="summary-list">
                    {% for item in league_rounds %}
                        <div
                            class="summary-row"
                            data-summary-league="{{ item.league_id }}"
                        >
                            <div class="summary-league">
                                {% if item.league_id == "ENG1" %}
                                    <span class="england-flag england-flag-summary" role="img" aria-label="Inglaterra"></span>
                                {% elif item.league_id == "ESP1" %}
                                    <img class="summary-flag-image" src="/assets/spain-flag.svg" alt="Espanha">
                                {% else %}
                                    {{ item.flag }}
                                {% endif %}
                                {{ item.league_id }}
                            </div>

                            <strong>
                                Jornada {{ item.round_number }}
                            </strong>

                            <small>
                                {{ item.country_name }}
                            </small>
                        </div>
                    {% endfor %}
                </div>
            </article>
        </section>

        <section
            class="summary"
            id="versions-summary"
        >
            <article class="summary-card">
                <div class="summary-card-header">
                    <span class="summary-card-title">
                        Versões por campeonato
                    </span>

                    <button
                        class="summary-close-button"
                        type="button"
                        data-summary-close="versions-summary"
                        aria-label="Fechar Versões por campeonato"
                    >
                        ×
                    </button>
                </div>

                <div class="summary-list">
                    {% for item in league_versions %}
                        <div
                            class="summary-row"
                            data-summary-league="{{ item.league_id }}"
                        >
                            <div class="summary-league">
                                {% if item.league_id == "ENG1" %}
                                    <span class="england-flag england-flag-summary" role="img" aria-label="Inglaterra"></span>
                                {% elif item.league_id == "ESP1" %}
                                    <img class="summary-flag-image" src="/assets/spain-flag.svg" alt="Espanha">
                                {% else %}
                                    {{ item.flag }}
                                {% endif %}
                                {{ item.league_id }}
                            </div>

                            <div class="summary-version-history">
                                {% if item.model_history %}
                                    {% for version in item.model_history %}
                                        <div class="summary-version-row">
                                            <div>
                                                <strong>
                                                    {{ version.display_version }}
                                                </strong>

                                                <small>
                                                    {{ version.model_version }}
                                                </small>
                                            </div>

                                            <div>
                                                <small>
                                                    {{ version.evaluated_matches }}
                                                    jogos avaliados
                                                </small>

                                                <strong>
                                                    {{ version.accuracy_label }}
                                                </strong>
                                            </div>
                                        </div>
                                    {% endfor %}
                                {% else %}
                                    <small class="unchanged">
                                        Sem versões registadas
                                    </small>
                                {% endif %}
                            </div>
                        </div>
                    {% endfor %}
                </div>
            </article>
        </section>

        <section class="bankroll-panel">
            <div class="bankroll-field bankroll-initial">
                <label for="initial-bankroll">
                    Carteira inicial
                </label>
                <div class="money-input">
                    <span>€</span>
                    <input
                        id="initial-bankroll"
                        type="number"
                        min="0"
                        step="0.01"
                        value="{{ '%.2f'|format(initial_bankroll) }}"
                        inputmode="decimal"
                    >
                </div>
            </div>

            <div class="bankroll-field bankroll-mode">
                <label for="stake-mode">
                    Modo da aposta
                </label>
                <select id="stake-mode">
                    <option
                        value="fixed"
                        {% if stake_mode|upper == "FIXED" %}
                        selected
                        {% endif %}
                    >
                        Valor fixo (€)
                    </option>
                    <option
                        value="percentage"
                        {% if stake_mode|upper == "PERCENTAGE" %}
                        selected
                        {% endif %}
                    >
                        Percentagem (%)
                    </option>
                </select>
            </div>

            <div class="bankroll-balance">
                <span>Saldo atual</span>
                <strong id="current-bankroll">
                    {{ "%.2f"|format(current_bankroll) }} €
                </strong>
            </div>

            <div class="bankroll-accuracy">
                <span>Eficácia dos algoritmos</span>
                <strong>
                    {{ algorithm_accuracy_label }}
                </strong>
            </div>

            <button
                id="save-betting-state"
                type="button"
            >
                Guardar carteira
            </button>

            <div
                id="bankroll-message"
                role="status"
                aria-live="polite"
            ></div>
        </section>

        <main class="matches">
            {% for match in matches %}
                <article
                    class="match-card"
                    data-league="{{ match.league_id }}"
                    {% if match.match_id == next_match_id %}
                    id="next-match"
                    {% endif %}
                >
                    <aside class="league-rail">
                        <div class="league-flag">
                            {% if match.league_id == "ENG1" %}
                                <span class="england-flag england-flag-large" role="img" aria-label="Inglaterra"></span>
                            {% elif match.league_id == "ESP1" %}
                                <img class="league-flag-image" src="/assets/spain-flag.svg" alt="Espanha">
                            {% else %}
                                {{ match.country_flag }}
                            {% endif %}
                        </div>
                        <div class="league-code">
                            {{ match.league_id }}
                        </div>
                        <div class="league-country">
                            {{ match.country_name }}
                        </div>
                    </aside>

                    <div class="match-content">
                        <div class="match-top">
                            <div class="teams">{{ match.home_team }} — {{ match.away_team }}</div>
                            <div
                                class="date match-local-date"
                                data-kickoff-utc="{{ match.kickoff_utc_iso }}"
                            >{{ match.display_date }}</div>
                        </div>

                    <div class="probabilities">
                        <div class="probability">
                            <span>Vitória casa</span>
                            <div class="probability-value home">
                                <img
                                    class="team-logo"
                                    src="{{ match.home_logo }}"
                                    alt="Símbolo {{ match.home_team }}"
                                    title="{{ match.home_team }}"
                                    loading="lazy"
                                >
                                <strong>{{ "%.2f"|format(match.home_probability * 100) }}%</strong>
                            </div>
                        </div>
                        <div class="probability">
                            <span>Empate</span>
                            <div class="probability-value">
                                <strong>{{ "%.2f"|format(match.draw_probability * 100) }}%</strong>
                            </div>
                        </div>
                        <div class="probability">
                            <span>Vitória fora</span>
                            <div class="probability-value away">
                                <strong>{{ "%.2f"|format(match.away_probability * 100) }}%</strong>
                                <img
                                    class="team-logo"
                                    src="{{ match.away_logo }}"
                                    alt="Símbolo {{ match.away_team }}"
                                    title="{{ match.away_team }}"
                                    loading="lazy"
                                >
                            </div>
                        </div>
                    </div>

                    <div
                        class="betting-fields"
                        data-match-id="{{ match.match_id }}"
                    >
                        <div class="betting-field">
                            <label for="odd-{{ match.match_id }}">
                                Odd
                            </label>
                            <input
                                id="odd-{{ match.match_id }}"
                                class="bet-odd"
                                type="number"
                                min="1.01"
                                step="0.01"
                                inputmode="decimal"
                                value="{% if match.bet_odd is not none %}{{ '%.2f'|format(match.bet_odd) }}{% endif %}"
                            >
                        </div>

                        <div class="betting-field">
                            <label for="stake-{{ match.match_id }}">
                                Aposta
                            </label>
                            <div class="bet-money-input">
                                <span class="bet-stake-symbol">€</span>
                                <input
                                    id="stake-{{ match.match_id }}"
                                    class="bet-stake"
                                    type="number"
                                    min="0.01"
                                    step="0.01"
                                    inputmode="decimal"
                                    value="{% if match.bet_stake is not none %}{{ '%.2f'|format(match.bet_stake) }}{% endif %}"
                                    >
                            </div>
                        </div>

                        <div class="bet-status {{ match.bet_status }}">
                            {% if match.bet_status == "won" %}
                                Aposta ganha
                            {% elif match.bet_status == "lost" %}
                                Aposta perdida
                            {% elif match.bet_odd and match.bet_stake %}
                                Aguardar resultado
                            {% else %}
                                Sem aposta
                            {% endif %}
                        </div>
                    </div>

                    <div class="prediction {{ match.result_class }}">
                        <div>
                            <div class="subtitle">Prognóstico prudente</div>
                            <span class="badge">{{ match.prudent }}</span>
                        </div>
                        <div class="score">
                            Resultado mais provável:
                            <strong>{{ match.most_likely_score or "—" }}</strong>

                            {% if match.actual_score %}
                                <span class="actual-result">
                                    Resultado final:
                                    {{ match.actual_score }}
                                </span>
                            {% endif %}
                        </div>
                    </div>
                    </div>
                </article>
            {% endfor %}
        </main>
    {% else %}
        <div class="empty">Não existem prognósticos disponíveis para a próxima jornada.</div>
    {% endif %}
</div>
<script>
    (() => {
        const summaryButtons = document.querySelectorAll(
            "[data-summary-target]"
        );
        const summaryCloseButtons = document.querySelectorAll(
            "[data-summary-close]"
        );
        const leagueButtons = document.querySelectorAll(
            "[data-league-filter]"
        );
        const matchCards = document.querySelectorAll(
            ".match-card[data-league]"
        );
        const summaryRows = document.querySelectorAll(
            "[data-summary-league]"
        );
        const leagueDashboard = document.getElementById(
            "league-dashboard"
        );
        const leagueDashboardCards = document.querySelectorAll(
            "[data-league-dashboard]"
        );
        const closeLeagueDashboard = document.getElementById(
            "close-league-dashboard"
        );

        let activeLeague = "ALL";

        const applyLeagueFilter = () => {
            for (const card of matchCards) {
                const visible = (
                    activeLeague === "ALL"
                    || card.dataset.league === activeLeague
                );

                card.hidden = !visible;
            }

            for (const row of summaryRows) {
                const visible = (
                    activeLeague === "ALL"
                    || row.dataset.summaryLeague === activeLeague
                );

                row.hidden = !visible;
            }

            for (const button of leagueButtons) {
                button.classList.toggle(
                    "active",
                    button.dataset.leagueFilter === activeLeague,
                );
            }

            if (leagueDashboard) {
                if (activeLeague === "ALL") {
                    leagueDashboard.hidden = true;

                    for (const dashboardCard of leagueDashboardCards) {
                        dashboardCard.hidden = true;
                    }
                } else {
                    leagueDashboard.hidden = false;

                    for (const dashboardCard of leagueDashboardCards) {
                        dashboardCard.hidden = (
                            dashboardCard.dataset.leagueDashboard
                            !== activeLeague
                        );
                    }
                }
            }
        };

        for (const button of summaryButtons) {
            button.addEventListener("click", () => {
                const targetId = button.dataset.summaryTarget;
                const target = document.getElementById(targetId);

                if (!target) {
                    return;
                }

                const isOpen = target.classList.contains("open");

                document
                    .querySelectorAll(".summary.open")
                    .forEach((panel) => {
                        panel.classList.remove("open");
                    });

                if (!isOpen) {
                    target.classList.add("open");
                }
            });
        }

        for (const button of summaryCloseButtons) {
            button.addEventListener("click", () => {
                const target = document.getElementById(
                    button.dataset.summaryClose
                );

                if (target) {
                    target.classList.remove("open");
                }
            });
        }

        for (const button of leagueButtons) {
            button.addEventListener("click", () => {
                activeLeague = button.dataset.leagueFilter || "ALL";
                applyLeagueFilter();
            });
        }

        if (closeLeagueDashboard) {
            closeLeagueDashboard.addEventListener("click", () => {
                activeLeague = "ALL";
                applyLeagueFilter();
            });
        }

        applyLeagueFilter();
    })();

    (() => {
        const dateElements = document.querySelectorAll(
            ".match-local-date[data-kickoff-utc]"
        );

        const userTimeZone = (
            Intl.DateTimeFormat()
            .resolvedOptions()
            .timeZone
        );

        for (const element of dateElements) {
            const raw = element.dataset.kickoffUtc;

            if (!raw) {
                continue;
            }

            const kickoff = new Date(raw);

            if (Number.isNaN(kickoff.getTime())) {
                continue;
            }

            const parts = new Intl.DateTimeFormat(
                "pt-PT",
                {
                    timeZone: userTimeZone,
                    day: "2-digit",
                    month: "2-digit",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: false,
                },
            ).formatToParts(kickoff);

            const values = {};

            for (const part of parts) {
                if (part.type !== "literal") {
                    values[part.type] = part.value;
                }
            }

            element.textContent = (
                `${values.day}/${values.month}/${values.year}`
                + ` · ${values.hour}:${values.minute}`
            );

            element.title = userTimeZone;
        }
    })();

    (() => {
        const saveButton = document.getElementById(
            "save-betting-state"
        );
        const bankrollInput = document.getElementById(
            "initial-bankroll"
        );
        const currentBankroll = document.getElementById(
            "current-bankroll"
        );
        const message = document.getElementById(
            "bankroll-message"
        );
        const stakeMode = document.getElementById(
            "stake-mode"
        );

        if (
            !saveButton
            || !bankrollInput
            || !currentBankroll
            || !message
            || !stakeMode
        ) {
            return;
        }

        const setMessage = (text, type = "") => {
            message.textContent = text;
            message.className = type;
        };

        const parseOptionalNumber = (value) => {
            const normalized = value.trim();

            if (!normalized) {
                return null;
            }

            const number = Number(normalized);

            return Number.isFinite(number)
                ? number
                : null;
        };

        const updateStakeMode = () => {
            const percentageMode =
                stakeMode.value === "percentage";

            document.querySelectorAll(
                ".bet-stake-symbol"
            ).forEach((symbol) => {
                symbol.textContent =
                    percentageMode ? "%" : "€";
            });

            document.querySelectorAll(
                ".bet-stake"
            ).forEach((input) => {
                if (percentageMode) {
                    input.max = "100";
                    input.placeholder = "Percentagem";
                } else {
                    input.removeAttribute("max");
                    input.placeholder = "Valor";
                }
            });
        };

        stakeMode.addEventListener(
            "change",
            updateStakeMode
        );

        updateStakeMode();

        saveButton.addEventListener("click", async () => {
            const initialBankroll = Number(
                bankrollInput.value
            );

            const bets = Array.from(
                document.querySelectorAll(
                    ".betting-fields"
                )
            ).map((container) => {
                const oddInput = container.querySelector(
                    ".bet-odd"
                );
                const stakeInput = container.querySelector(
                    ".bet-stake"
                );

                return {
                    match_id:
                        container.dataset.matchId,
                    odd: parseOptionalNumber(
                        oddInput?.value || ""
                    ),
                    stake: (() => {
                        const enteredStake =
                            parseOptionalNumber(
                                stakeInput?.value || ""
                            );

                        if (enteredStake === null) {
                            return null;
                        }

                        if (
                            stakeMode.value
                            === "percentage"
                        ) {
                            return Number(
                                (
                                    initialBankroll
                                    * enteredStake
                                    / 100
                                ).toFixed(2)
                            );
                        }

                        return enteredStake;
                    })(),
                };
            });

            saveButton.disabled = true;
            setMessage("A guardar...");

            try {
                const response = await fetch(
                    "/api/betting-state",
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json",
                        },
                        body: JSON.stringify({
                            initial_bankroll:
                                initialBankroll,
                            stake_mode:
                                stakeMode.value,
                            bets,
                        }),
                    }
                );

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(
                        data.error
                        || "Não foi possível guardar."
                    );
                }

                bankrollInput.value = Number(
                    data.initial_bankroll
                ).toFixed(2);

                currentBankroll.textContent = `${
                    Number(
                        data.current_bankroll
                    ).toFixed(2)
                } €`;

                setMessage(
                    "Carteira e apostas guardadas.",
                    "success"
                );
            } catch (error) {
                setMessage(
                    error.message
                    || "Erro ao guardar a carteira.",
                    "error"
                );
            } finally {
                saveButton.disabled = false;
            }
        });
    })();

    window.addEventListener("load", () => {
        const nextMatch = document.getElementById(
            "next-match"
        );

        if (!nextMatch) {
            return;
        }

        requestAnimationFrame(() => {
            nextMatch.scrollIntoView({
                behavior: "auto",
                block: "center",
                inline: "nearest",
            });
        });
    });
</script>
</body>
</html>
"""


def prudent_prediction(
    home: float,
    draw: float,
    away: float,
    most_likely_score: str | None = None,
) -> str:
    probabilities = [
        ("1", home),
        ("X", draw),
        ("2", away),
    ]
    probabilities.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    first_label, first_value = probabilities[0]
    second_label, second_value = probabilities[1]

    order = {
        "1": 0,
        "X": 1,
        "2": 2,
    }

    if (first_value - second_value) <= 0.10:
        prudent_sign = "".join(
            sorted(
                [first_label, second_label],
                key=lambda label: order[label],
            )
        )
    else:
        prudent_sign = first_label

    score_sign: str | None = None

    if most_likely_score:
        try:
            home_goals_text, away_goals_text = (
                most_likely_score.split("-", 1)
            )
            home_goals = int(home_goals_text)
            away_goals = int(away_goals_text)

            if home_goals > away_goals:
                score_sign = "1"
            elif home_goals < away_goals:
                score_sign = "2"
            else:
                score_sign = "X"

        except (TypeError, ValueError):
            score_sign = None

    if score_sign and score_sign not in prudent_sign:
        prudent_sign = "".join(
            sorted(
                {first_label, score_sign},
                key=lambda label: order[label],
            )
        )

    return prudent_sign


def get_result_sign(
    home_goals: int,
    away_goals: int,
) -> str:
    """Converte o marcador real no sinal 1, X ou 2."""

    if home_goals > away_goals:
        return "1"

    if home_goals < away_goals:
        return "2"

    return "X"


def parse_score(
    score: str | None,
) -> tuple[int, int] | None:
    """Interpreta um marcador no formato casa-fora."""

    if not score:
        return None

    try:
        home_text, away_text = score.split("-", 1)

        return (
            int(home_text.strip()),
            int(away_text.strip()),
        )

    except (AttributeError, TypeError, ValueError):
        return None


def evaluate_prediction_result(
    prudent: str,
    most_likely_score: str | None,
    home_goals: int | None,
    away_goals: int | None,
) -> str:
    """
    Devolve a classe visual da validação.

    Dourado: prudente e marcador exato corretos.
    Verde: apenas um dos dois correto.
    Vermelho: ambos errados.
    Pendente: jogo ainda sem resultado final.
    """

    if home_goals is None or away_goals is None:
        return "result-pending"

    actual_sign = get_result_sign(
        home_goals,
        away_goals,
    )

    prudent_correct = actual_sign in prudent

    predicted_score = parse_score(
        most_likely_score
    )

    exact_score_correct = (
        predicted_score
        == (home_goals, away_goals)
    )

    if prudent_correct and exact_score_correct:
        return "result-gold"

    if prudent_correct or exact_score_correct:
        return "result-green"

    return "result-red"


def get_next_round_matches() -> tuple[int | None, list[dict]]:
    league_rounds = []
    matches = []

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        league_rows = connection.execute(
            """
            SELECT DISTINCT league_id
            FROM matches
            WHERE season_label = ?
            ORDER BY
                CASE league_id
                    WHEN 'POR1' THEN 1
                    WHEN 'ENG1' THEN 2
                    WHEN 'ESP1' THEN 3
                    WHEN 'FRA1' THEN 4
                    WHEN 'ITA1' THEN 5
                    WHEN 'GER1' THEN 6
                    ELSE 99
                END,
                league_id
            """,
            (SEASON_LABEL,),
        ).fetchall()

        for league_row in league_rows:
            league_id = str(league_row["league_id"])

            metadata = LEAGUE_METADATA.get(
                league_id,
                {
                    "name": league_id,
                    "timezone": "Europe/Lisbon",
                    "flag": "🏳️",
                },
            )

            local_timezone = ZoneInfo(
                metadata["timezone"]
            )

            candidate_rows = connection.execute(
                """
                SELECT
                    round_number,
                    match_date,
                    match_id
                FROM matches
                WHERE league_id = ?
                  AND season_label = ?
                  AND status IN ('SCHEDULED', 'POSTPONED')
                  AND match_date IS NOT NULL
                  AND TRIM(match_date) <> ''
                  AND round_number IS NOT NULL
                ORDER BY match_date, round_number, match_id
                """,
                (
                    league_id,
                    SEASON_LABEL,
                ),
            ).fetchall()

            now_utc = datetime.now(
                timezone.utc
            )

            future_candidates = []

            for candidate in candidate_rows:
                try:
                    kickoff_utc = match_datetime_utc(
                        league_id,
                        candidate["match_date"],
                    )
                except (TypeError, ValueError):
                    continue

                if kickoff_utc >= now_utc:
                    future_candidates.append(
                        (
                            kickoff_utc,
                            candidate,
                        )
                    )

            if future_candidates:
                future_candidates.sort(
                    key=lambda item: (
                        item[0],
                        int(item[1]["round_number"]),
                        str(item[1]["match_id"]),
                    )
                )
                next_round_row = future_candidates[0][1]
            else:
                next_round_row = None

            if next_round_row is None:
                continue

            round_number = int(
                next_round_row["round_number"]
            )

            future_round_numbers = []

            for _kickoff_utc, candidate in future_candidates:
                candidate_round = int(
                    candidate["round_number"]
                )

                if candidate_round not in future_round_numbers:
                    future_round_numbers.append(
                        candidate_round
                    )

                if len(future_round_numbers) >= 2:
                    break

            league_rounds.append(
                {
                    "league_id": league_id,
                    "round_number": round_number,
                    "flag": metadata["flag"],
                    "country_name": metadata["name"],
                }
            )

            placeholders = ",".join(
                "?"
                for _ in future_round_numbers
            )

            rows = connection.execute(
                f"""
                SELECT
                    m.match_id,
                    m.league_id,
                    m.round_number,
                    m.match_date,
                    m.status,
                    m.home_goals,
                    m.away_goals,
                    m.updated_at AS result_updated_at,
                    home.team_id AS home_team_id,
                    home.team_name AS home_team,
                    away.team_id AS away_team_id,
                    away.team_name AS away_team,
                    p.prediction_id,
                    p.home_win_probability,
                    p.draw_probability,
                    p.away_win_probability,
                    p.most_likely_score,
                    p.prediction_timestamp,
                    p.prediction_stage,
                    p.prediction_version,
                    p.model_version,
                    p.lineup_confirmed,
                    p.lineup_data_quality
                FROM matches AS m
                JOIN teams AS home
                  ON home.team_id = m.home_team_id
                JOIN teams AS away
                  ON away.team_id = m.away_team_id
                JOIN match_predictions AS p
                  ON p.prediction_id = (
                      SELECT p2.prediction_id
                      FROM match_predictions AS p2
                      WHERE p2.match_id = m.match_id
                        AND p2.is_current = 1
                      ORDER BY
                          CASE p2.prediction_stage
                              WHEN 'CONFIRMED_LINEUP' THEN 1
                              WHEN 'MANUAL_OVERRIDE' THEN 2
                              WHEN 'PRE_MATCH' THEN 3
                              ELSE 4
                          END,
                          p2.prediction_version DESC,
                          p2.prediction_timestamp DESC,
                          p2.created_at DESC
                      LIMIT 1
                  )
                WHERE m.league_id = ?
                  AND m.season_label = ?
                  AND (
                      m.status = 'PLAYED'
                      OR m.status IN ('SCHEDULED', 'POSTPONED')
                  )
                ORDER BY m.match_date, m.match_id
                """,
                (
                    league_id,
                    SEASON_LABEL,
                ),
            ).fetchall()

            for row in rows:
                baseline = connection.execute(
                    """
                    SELECT
                        home_win_probability,
                        draw_probability,
                        away_win_probability,
                        most_likely_score
                    FROM match_predictions
                    WHERE match_id = ?
                      AND prediction_id <> ?
                    ORDER BY
                        CASE
                            WHEN prediction_stage = 'PRE_MATCH' THEN 1
                            ELSE 2
                        END,
                        prediction_version DESC,
                        prediction_timestamp DESC,
                        created_at DESC
                    LIMIT 1
                    """,
                    (
                        row["match_id"],
                        row["prediction_id"],
                    ),
                ).fetchone()

                match_date = row["match_date"]

                try:
                    sort_timestamp = match_datetime_utc(
                        league_id,
                        match_date,
                    )

                    display_date = sort_timestamp.strftime(
                        "%d/%m/%Y · %H:%M UTC"
                    )

                    kickoff_utc_iso = (
                        sort_timestamp
                        .astimezone(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z")
                    )

                except (TypeError, ValueError):
                    display_date = (
                        match_date or "Data por definir"
                    )
                    sort_timestamp = datetime.max.replace(
                        tzinfo=timezone.utc
                    )
                    kickoff_utc_iso = ""

                if row["status"] in ("SCHEDULED", "POSTPONED"):
                    now_utc = datetime.now(timezone.utc)

                    if sort_timestamp >= now_utc:
                        if int(row["round_number"]) not in future_round_numbers:
                            continue
                    else:
                        seconds_since_kickoff = (
                            now_utc - sort_timestamp
                        ).total_seconds()

                        if seconds_since_kickoff > 6 * 60 * 60:
                            continue

                home_probability = float(
                    row["home_win_probability"]
                )
                draw_probability = float(
                    row["draw_probability"]
                )
                away_probability = float(
                    row["away_win_probability"]
                )

                prudent = prudent_prediction(
                    home_probability,
                    draw_probability,
                    away_probability,
                    row["most_likely_score"],
                )

                home_goals = row["home_goals"]
                away_goals = row["away_goals"]

                actual_score = None

                if (
                    home_goals is not None
                    and away_goals is not None
                ):
                    actual_score = (
                        f"{home_goals}-{away_goals}"
                    )

                result_class = evaluate_prediction_result(
                    prudent=prudent,
                    most_likely_score=row["most_likely_score"],
                    home_goals=home_goals,
                    away_goals=away_goals,
                )

                prediction_changed = False

                if baseline is not None:
                    current_values = (
                        round(home_probability, 10),
                        round(draw_probability, 10),
                        round(away_probability, 10),
                        row["most_likely_score"],
                    )

                    baseline_values = (
                        round(
                            float(
                                baseline["home_win_probability"]
                            ),
                            10,
                        ),
                        round(
                            float(
                                baseline["draw_probability"]
                            ),
                            10,
                        ),
                        round(
                            float(
                                baseline["away_win_probability"]
                            ),
                            10,
                        ),
                        baseline["most_likely_score"],
                    )

                    prediction_changed = (
                        current_values != baseline_values
                    )

                matches.append(
                    {
                        "match_id": str(row["match_id"]),
                        "league_id": league_id,
                        "round_number": int(row["round_number"]),
                        "country_name": metadata["name"],
                        "country_flag": metadata["flag"],
                        "home_team": row["home_team"],
                        "away_team": row["away_team"],
                        "home_team_id": row["home_team_id"],
                        "away_team_id": row["away_team_id"],
                        "home_logo": (
                            f"/assets/team_logos/{row['home_team_id']}.png"
                        ),
                        "away_logo": (
                            f"/assets/team_logos/{row['away_team_id']}.png"
                        ),
                        "display_date": display_date,
                        "kickoff_utc_iso": kickoff_utc_iso,
                        "sort_timestamp": sort_timestamp,
                        "home_probability": home_probability,
                        "draw_probability": draw_probability,
                        "away_probability": away_probability,
                        "most_likely_score": row["most_likely_score"],
                        "prudent": prudent,
                        "status": row["status"],
                        "actual_score": actual_score,
                        "result_class": result_class,
                        "prediction_timestamp": row["prediction_timestamp"],
                        "prediction_stage": row["prediction_stage"],
                        "prediction_version": int(
                            row["prediction_version"]
                        ),
                        "model_version": row["model_version"],
                        "prediction_changed": prediction_changed,
                        "lineup_confirmed": bool(
                            row["lineup_confirmed"]
                        ),
                        "lineup_data_quality": (
                            row["lineup_data_quality"]
                        ),
                        "result_updated_at": (
                            row["result_updated_at"]
                        ),
                    }
                )

    now_utc = datetime.now(
        timezone.utc
    )

    matches.sort(
        key=lambda match: (
            match["sort_timestamp"],
            match["league_id"],
            match["match_id"],
        ),
        reverse=True,
    )

    return (
        league_rounds[0]["round_number"]
        if league_rounds
        else None,
        matches,
    )




def get_algorithm_accuracy(
    *,
    league_id: str | None = None,
    model_version: str | None = None,
) -> float | None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        conditions = [
            "m.season_label = ?",
            "pe.prudent_outcome_hit IS NOT NULL",
        ]
        parameters = [SEASON_LABEL]

        if league_id:
            conditions.append("m.league_id = ?")
            parameters.append(league_id.strip().upper())

        if model_version:
            conditions.append("pe.model_version = ?")
            parameters.append(model_version.strip())

        if model_version:
            row = connection.execute(
                f"""
                SELECT
                    AVG(
                        CAST(
                            pe.prudent_outcome_hit
                            AS REAL
                        )
                    ) * 100 AS accuracy
                FROM prediction_evaluations AS pe
                JOIN matches AS m
                  ON m.match_id = pe.match_id
                WHERE {" AND ".join(conditions)}
                """,
                parameters,
            ).fetchone()
        else:
            row = connection.execute(
                f"""
                WITH ranked AS (
                    SELECT
                        pe.match_id,
                        pe.prudent_outcome_hit,
                        ROW_NUMBER() OVER (
                            PARTITION BY pe.match_id
                            ORDER BY
                                CASE pe.prediction_stage
                                    WHEN 'CONFIRMED_LINEUP' THEN 1
                                    WHEN 'MANUAL_OVERRIDE' THEN 2
                                    WHEN 'PRE_MATCH' THEN 3
                                    ELSE 4
                                END,
                                mp.prediction_version DESC,
                                mp.prediction_timestamp DESC,
                                mp.created_at DESC,
                                pe.prediction_id DESC
                        ) AS selection_rank
                    FROM prediction_evaluations AS pe
                    JOIN matches AS m
                      ON m.match_id = pe.match_id
                    JOIN match_predictions AS mp
                      ON mp.prediction_id = pe.prediction_id
                    WHERE {" AND ".join(conditions)}
                )
                SELECT
                    AVG(
                        CAST(
                            prudent_outcome_hit
                            AS REAL
                        )
                    ) * 100 AS accuracy
                FROM ranked
                WHERE selection_rank = 1
                """,
                parameters,
            ).fetchone()

    if row is None or row["accuracy"] is None:
        return None

    return float(row["accuracy"])



def get_league_dashboard_summary(
    league_id: str,
) -> dict:
    league_id = league_id.strip().upper()

    metadata = LEAGUE_METADATA.get(
        league_id,
        {
            "name": league_id,
            "flag": "🏳️",
        },
    )

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        totals = connection.execute(
            """
            SELECT
                COUNT(*) AS total_matches,
                SUM(
                    CASE
                        WHEN status IN ('PLAYED', 'AWARDED')
                        THEN 1
                        ELSE 0
                    END
                ) AS played_matches,
                SUM(
                    CASE
                        WHEN status NOT IN ('PLAYED', 'AWARDED')
                        THEN 1
                        ELSE 0
                    END
                ) AS remaining_matches
            FROM matches
            WHERE league_id = ?
              AND season_label = ?
            """,
            (
                league_id,
                SEASON_LABEL,
            ),
        ).fetchone()

        current_round_row = connection.execute(
            """
            SELECT
                MIN(round_number) AS current_round
            FROM matches
            WHERE league_id = ?
              AND season_label = ?
              AND status NOT IN ('PLAYED', 'AWARDED')
            """,
            (
                league_id,
                SEASON_LABEL,
            ),
        ).fetchone()

        if (
            current_round_row is None
            or current_round_row["current_round"] is None
        ):
            current_round_row = connection.execute(
                """
                SELECT
                    MAX(round_number) AS current_round
                FROM matches
                WHERE league_id = ?
                  AND season_label = ?
                """,
                (
                    league_id,
                    SEASON_LABEL,
                ),
            ).fetchone()

        model_rows = connection.execute(
            """
            SELECT
                mv.model_version,
                mv.parent_model_version,
                mv.version_status,
                mv.created_at,
                mv.activated_at,
                mv.retired_at
            FROM model_versions AS mv
            WHERE mv.season_label = ?
              AND (
                    mv.league_id = ?
                    OR (
                        mv.league_id IS NULL
                        AND EXISTS (
                            SELECT 1
                            FROM match_predictions AS mp
                            JOIN matches AS m
                              ON m.match_id = mp.match_id
                            WHERE m.league_id = ?
                              AND m.season_label = ?
                              AND mp.model_version = mv.model_version
                        )
                    )
              )
            ORDER BY
                COALESCE(
                    mv.activated_at,
                    mv.created_at
                ),
                mv.model_version
            """,
            (
                SEASON_LABEL,
                league_id,
                league_id,
                SEASON_LABEL,
            ),
        ).fetchall()

        prediction_usage_rows = connection.execute(
            """
            SELECT
                mp.model_version,
                COUNT(DISTINCT mp.match_id) AS predicted_matches
            FROM match_predictions AS mp
            JOIN matches AS m
              ON m.match_id = mp.match_id
            WHERE m.league_id = ?
              AND m.season_label = ?
            GROUP BY mp.model_version
            """,
            (
                league_id,
                SEASON_LABEL,
            ),
        ).fetchall()

        evaluation_rows = connection.execute(
            """
            SELECT
                pe.model_version,
                COUNT(*) AS evaluated_matches,
                SUM(
                    CASE
                        WHEN pe.prudent_outcome_hit = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS hits,
                AVG(
                    CAST(
                        pe.prudent_outcome_hit
                        AS REAL
                    )
                ) * 100 AS accuracy
            FROM prediction_evaluations AS pe
            JOIN matches AS m
              ON m.match_id = pe.match_id
            WHERE m.league_id = ?
              AND m.season_label = ?
              AND pe.prudent_outcome_hit IS NOT NULL
            GROUP BY pe.model_version
            """,
            (
                league_id,
                SEASON_LABEL,
            ),
        ).fetchall()

    usage_by_model = {
        row["model_version"]: int(
            row["predicted_matches"] or 0
        )
        for row in prediction_usage_rows
    }

    evaluation_by_model = {
        row["model_version"]: {
            "evaluated_matches": int(
                row["evaluated_matches"] or 0
            ),
            "hits": int(
                row["hits"] or 0
            ),
            "accuracy": (
                float(row["accuracy"])
                if row["accuracy"] is not None
                else None
            ),
        }
        for row in evaluation_rows
    }

    model_history = []

    for index, row in enumerate(
        model_rows,
        start=1,
    ):
        model_version = row["model_version"]
        evaluation = evaluation_by_model.get(
            model_version,
            {
                "evaluated_matches": 0,
                "hits": 0,
                "accuracy": None,
            },
        )

        model_history.append(
            {
                "display_version": f"V{index:03d}",
                "model_version": model_version,
                "status": row["version_status"],
                "parent_model_version": (
                    row["parent_model_version"]
                ),
                "predicted_matches": usage_by_model.get(
                    model_version,
                    0,
                ),
                "evaluated_matches": (
                    evaluation["evaluated_matches"]
                ),
                "hits": evaluation["hits"],
                "accuracy": evaluation["accuracy"],
                "accuracy_label": (
                    f'{evaluation["accuracy"]:.2f}%'
                    if evaluation["accuracy"] is not None
                    else "Sem jogos avaliados"
                ),
                "activated_at": row["activated_at"],
                "retired_at": row["retired_at"],
            }
        )

    active_models = [
        item
        for item in model_history
        if item["status"] == "ACTIVE"
    ]

    active_model = (
        active_models[-1]
        if active_models
        else (
            model_history[-1]
            if model_history
            else None
        )
    )

    league_accuracy = get_algorithm_accuracy(
        league_id=league_id,
    )

    return {
        "league_id": league_id,
        "country_name": metadata["name"],
        "flag": metadata["flag"],
        "current_round": (
            int(current_round_row["current_round"])
            if (
                current_round_row is not None
                and current_round_row["current_round"]
                is not None
            )
            else None
        ),
        "total_matches": int(
            totals["total_matches"] or 0
        ),
        "played_matches": int(
            totals["played_matches"] or 0
        ),
        "remaining_matches": int(
            totals["remaining_matches"] or 0
        ),
        "accuracy": league_accuracy,
        "accuracy_label": (
            f"{league_accuracy:.2f}%"
            if league_accuracy is not None
            else "Sem jogos avaliados"
        ),
        "active_model": active_model,
        "model_history": model_history,
    }


def get_user_betting_state(
    user_id: str,
    access_token: str,
    matches: list[dict],
) -> dict:
    bankroll_row = load_bankroll(
        user_id=user_id,
        access_token=access_token,
    )

    initial_bankroll = (
        float(bankroll_row["initial_balance"])
        if bankroll_row is not None
        else 0.0
    )

    stored_current_balance = (
        float(bankroll_row["current_balance"])
        if bankroll_row is not None
        else initial_bankroll
    )

    stake_mode = (
        str(bankroll_row.get("stake_mode") or "FIXED")
        if bankroll_row is not None
        else "FIXED"
    )

    default_stake_value = (
        float(bankroll_row.get("default_stake_value") or 0)
        if bankroll_row is not None
        else 0.0
    )

    bet_rows = load_user_bets(
        user_id=user_id,
        access_token=access_token,
    )

    try:
        bwin_odds_by_match = load_bwin_odds_for_matches(
            match_ids=[
                str(match["match_id"])
                for match in matches
            ],
            access_token=access_token,
        )
    except SupabaseBwinOddsError as exc:
        print(
            "AVISO: não foi possível carregar odds Bwin: "
            f"{exc}"
        )
        bwin_odds_by_match = {}

    bets_by_match = {
        str(row["match_id"]): {
            "id": int(row["id"]),
            "odd": (
                float(row["odd"])
                if row.get("odd") is not None
                else None
            ),
            "stake": (
                float(row["stake_amount"])
                if row.get("stake_amount") is not None
                else None
            ),
            "prudent_prediction": row.get("selection"),
            "status": str(
                row.get("status") or "PENDING"
            ).upper(),
        }
        for row in bet_rows
    }

    current_bankroll = stored_current_balance
    bankroll_changed = False

    for match in matches:
        bet = bets_by_match.get(
            str(match["match_id"]),
            {},
        )

        odd = bet.get("odd")
        stake = bet.get("stake")
        bet_prudent = (
            bet.get("prudent_prediction")
            or match["prudent"]
        )

        if odd is None:
            bwin_row = bwin_odds_by_match.get(
                str(match["match_id"])
            )

            if bwin_row is not None:
                odd_field_by_prediction = {
                    "1": "odd_1",
                    "X": "odd_x",
                    "2": "odd_2",
                    "1X": "odd_1x",
                    "12": "odd_12",
                    "X2": "odd_x2",
                }

                odd_field = odd_field_by_prediction.get(
                    str(bet_prudent).strip().upper()
                )

                if (
                    odd_field is not None
                    and bwin_row.get(odd_field) is not None
                ):
                    odd = float(
                        bwin_row[odd_field]
                    )

        match["bet_odd"] = odd
        match["bet_stake"] = stake
        match["bet_prudent"] = bet_prudent

        status = str(
            bet.get("status") or "PENDING"
        ).upper()

        if (
            status == "PENDING"
            and bet.get("id") is not None
            and odd is not None
            and stake is not None
            and odd > 0
            and stake > 0
            and match.get("actual_score")
        ):
            home_text, away_text = (
                match["actual_score"].split("-", 1)
            )
            home_goals = int(home_text)
            away_goals = int(away_text)

            if home_goals > away_goals:
                final_result = "1"
            elif home_goals < away_goals:
                final_result = "2"
            else:
                final_result = "X"

            if final_result in bet_prudent:
                new_status = "WON"
                actual_return = odd * stake
                profit_loss = (odd - 1.0) * stake
            else:
                new_status = "LOST"
                actual_return = 0.0
                profit_loss = -stake

            new_balance = (
                current_bankroll + profit_loss
            )

            settled = settle_bet(
                user_id=user_id,
                access_token=access_token,
                bet_id=bet["id"],
                status=new_status,
                actual_return=actual_return,
                profit_loss=profit_loss,
                balance_after_settlement=new_balance,
                home_goals=home_goals,
                away_goals=away_goals,
            )

            if settled:
                status = new_status
                current_bankroll = new_balance
                bankroll_changed = True

        if status == "WON":
            match["bet_status"] = "won"
        elif status == "LOST":
            match["bet_status"] = "lost"
        else:
            match["bet_status"] = "pending"

    if bankroll_changed:
        save_bankroll(
            user_id=user_id,
            access_token=access_token,
            initial_balance=initial_bankroll,
            current_balance=current_bankroll,
            stake_mode=stake_mode,
            default_stake_value=default_stake_value,
        )

    return {
        "initial_bankroll": initial_bankroll,
        "current_bankroll": current_bankroll,
        "stake_mode": stake_mode,
        "default_stake_value": default_stake_value,
    }


def login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        access_token = session.get("access_token")
        refresh_token = session.get("refresh_token")

        if not access_token:
            return redirect(url_for("login"))

        if refresh_token:
            try:
                auth_data = refresh_session(
                    refresh_token=refresh_token,
                )

                renewed_access_token = auth_data.get(
                    "access_token"
                )
                renewed_refresh_token = auth_data.get(
                    "refresh_token"
                )
                user = auth_data.get("user") or {}

                if renewed_access_token:
                    session["access_token"] = (
                        renewed_access_token
                    )

                if renewed_refresh_token:
                    session["refresh_token"] = (
                        renewed_refresh_token
                    )

                if user.get("id"):
                    session["user_id"] = user["id"]

                if user.get("email"):
                    session["user_email"] = user["email"]

            except SupabaseAuthError:
                session.clear()
                return redirect(url_for("login"))

        return view_function(*args, **kwargs)

    return wrapped_view


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("access_token"):
        return redirect(url_for("predictions"))

    error = None
    success = None
    email = ""

    if request.args.get("registered") == "1":
        success = (
            "Conta criada com sucesso. "
            "Já podes iniciar sessão."
        )

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            error = "Preenche o email e a palavra-passe."
        else:
            try:
                auth_data = login_user(
                    email=email,
                    password=password,
                )

                access_token = auth_data.get("access_token")
                refresh_token = auth_data.get("refresh_token")
                user = auth_data.get("user") or {}

                if not access_token:
                    raise SupabaseAuthError(
                        "O Supabase não devolveu uma sessão válida."
                    )

                session.clear()
                session["access_token"] = access_token
                session["refresh_token"] = refresh_token
                session["user_id"] = user.get("id")
                session["user_email"] = user.get("email", email)

                return redirect(url_for("predictions"))

            except SupabaseAuthError as exc:
                message = str(exc).lower()

                if "invalid login credentials" in message:
                    error = "Email ou palavra-passe incorretos."
                elif "email not confirmed" in message:
                    error = (
                        "Confirma primeiro o teu email "
                        "antes de iniciares sessão."
                    )
                else:
                    error = f"Não foi possível iniciar sessão: {exc}"

            except Exception as exc:
                error = (
                    "Ocorreu um erro ao contactar "
                    f"o serviço de autenticação: {exc}"
                )

    return render_template(
        "login.html",
        error=error,
        success=success,
        email=email,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("access_token"):
        return redirect(url_for("predictions"))

    error = None
    name = ""
    email = ""

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirmation = request.form.get(
            "password_confirmation",
            "",
        )

        if len(name) < 2:
            error = "Indica um nome válido."
        elif not email:
            error = "Indica um endereço de email válido."
        elif len(password) < 8:
            error = (
                "A palavra-passe deve ter "
                "pelo menos 8 caracteres."
            )
        elif password != password_confirmation:
            error = "As palavras-passe não coincidem."
        else:
            try:
                register_user(
                    name=name,
                    email=email,
                    password=password,
                )

                return redirect(
                    url_for(
                        "login",
                        registered="1",
                    )
                )

            except SupabaseAuthError as exc:
                message = str(exc).lower()

                if (
                    "already registered" in message
                    or "user already registered" in message
                ):
                    error = "Já existe uma conta com este email."
                else:
                    error = f"Não foi possível criar a conta: {exc}"

            except Exception as exc:
                error = (
                    "Ocorreu um erro ao contactar "
                    f"o serviço de autenticação: {exc}"
                )

    return render_template(
        "register.html",
        error=error,
        name=name,
        email=email,
    )


@app.route("/logout")
def logout():
    access_token = session.get("access_token")

    if access_token:
        try:
            logout_user(access_token)
        except Exception as exc:
            print(
                "AVISO: não foi possível terminar "
                f"a sessão no Supabase: {exc}"
            )

    session.clear()

    return redirect(url_for("login"))


@app.route("/api/betting-state", methods=["POST"])
@login_required
def save_betting_state():
    user_id = session.get("user_id")
    access_token = session.get("access_token")

    if not user_id or not access_token:
        return jsonify(
            {
                "ok": False,
                "error": "Sessão sem utilizador válido.",
            }
        ), 401

    payload = request.get_json(silent=True) or {}

    try:
        initial_bankroll = float(
            payload.get("initial_bankroll", 0)
        )
    except (TypeError, ValueError):
        return jsonify(
            {
                "ok": False,
                "error": "A carteira inicial é inválida.",
            }
        ), 400

    if (
        not math.isfinite(initial_bankroll)
        or initial_bankroll < 0
    ):
        return jsonify(
            {
                "ok": False,
                "error": (
                    "A carteira inicial deve ser "
                    "um valor igual ou superior a zero."
                ),
            }
        ), 400

    stake_mode = str(
        payload.get("stake_mode") or "fixed"
    ).strip().lower()

    if stake_mode not in {
        "fixed",
        "percentage",
    }:
        return jsonify(
            {
                "ok": False,
                "error": "O modo da aposta é inválido.",
            }
        ), 400

    bets_payload = payload.get("bets", [])

    if not isinstance(bets_payload, list):
        return jsonify(
            {
                "ok": False,
                "error": "A lista de apostas é inválida.",
            }
        ), 400

    _, current_matches = get_next_round_matches()

    matches_by_id = {
        str(match["match_id"]): match
        for match in current_matches
    }

    validated_bets = []

    for item in bets_payload:
        if not isinstance(item, dict):
            continue

        match_id = str(
            item.get("match_id") or ""
        ).strip()

        if not match_id:
            continue

        match = matches_by_id.get(match_id)

        if match is None:
            continue

        odd_raw = item.get("odd")
        stake_raw = item.get("stake")

        if stake_raw in (None, ""):
            continue

        if odd_raw in (None, ""):
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "Não existe odd disponível "
                        "para esta aposta."
                    ),
                }
            ), 400

        try:
            odd = float(odd_raw)
            stake = float(stake_raw)
        except (TypeError, ValueError):
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "Existe uma odd ou aposta inválida."
                    ),
                }
            ), 400

        if (
            not math.isfinite(odd)
            or not math.isfinite(stake)
            or odd <= 1
            or stake <= 0
        ):
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "A odd deve ser superior a 1 "
                        "e a aposta superior a zero."
                    ),
                }
            ), 400

        validated_bets.append(
            {
                "match_id": match_id,
                "odd": odd,
                "stake": stake,
                "prudent_prediction": match["prudent"],
            }
        )

    try:
        existing_bankroll = load_bankroll(
            user_id=user_id,
            access_token=access_token,
        )

        if existing_bankroll is None:
            current_balance = initial_bankroll
        else:
            stored_initial = float(
                existing_bankroll.get(
                    "initial_balance",
                    initial_bankroll,
                )
            )
            stored_current = float(
                existing_bankroll.get(
                    "current_balance",
                    initial_bankroll,
                )
            )

            if abs(
                stored_initial - initial_bankroll
            ) > 0.000001:
                current_balance = initial_bankroll
            else:
                current_balance = stored_current

        save_bankroll(
            user_id=user_id,
            access_token=access_token,
            initial_balance=initial_bankroll,
            current_balance=current_balance,
            stake_mode=stake_mode,
            default_stake_value=0.0,
        )

        running_balance = current_balance

        for bet in validated_bets:
            save_pending_bet(
                user_id=user_id,
                access_token=access_token,
                match_id=bet["match_id"],
                selection=bet[
                    "prudent_prediction"
                ],
                odd=bet["odd"],
                stake_amount=bet["stake"],
                balance_before=running_balance,
                balance_after_stake=running_balance,
            )

        betting_state = get_user_betting_state(
            user_id=user_id,
            access_token=access_token,
            matches=current_matches,
        )

    except SupabaseBettingError as exc:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "Não foi possível guardar a carteira "
                    f"no Supabase: {exc}"
                ),
            }
        ), 502

    return jsonify(
        {
            "ok": True,
            "initial_bankroll": (
                betting_state["initial_bankroll"]
            ),
            "current_bankroll": (
                betting_state["current_bankroll"]
            ),
            "stake_mode": (
                betting_state["stake_mode"]
            ),
        }
    )


@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(
        BASE_DIR / "docs" / "assets",
        filename,
    )


@app.route("/")
@login_required
def predictions():
    for league_id in ("POR1", "ESP1", "ENG1", "FRA1", "ITA1", "GER1"):
        try:
            run_final_result_update(
                league_id=league_id,
                season_label=SEASON_LABEL,
                minutes_after_kickoff=120,
                database_path=DATABASE_PATH,
            )
            evaluation_summary = run_prediction_evaluation(
                league_id=league_id,
                season_label=SEASON_LABEL,
                database_path=DATABASE_PATH,
            )

            if evaluation_summary.inserted_evaluations > 0:
                print(
                    "APRENDIZAGEM AUTOMATICA PENDENTE | "
                    f"liga={league_id} | "
                    "não executada dentro da rota web"
                )
        except Exception as exc:
            print(
                "AVISO: não foi possível atualizar "
                f"resultados/avaliações de {league_id}: {exc}"
            )

    round_number, matches = get_next_round_matches()

    user_id = session.get("user_id")

    betting_state = get_user_betting_state(
        user_id=user_id,
        access_token=session.get("access_token"),
        matches=matches,
    )

    league_rounds = []
    league_versions = []
    league_summaries = []

    league_order = [
        "POR1",
        "ENG1",
        "ESP1",
        "FRA1",
        "ITA1",
        "GER1",
    ]

    for league_id in league_order:
        league_summary = (
            get_league_dashboard_summary(
                league_id
            )
        )

        league_summaries.append(
            league_summary
        )

        league_matches = [
            match
            for match in matches
            if match["league_id"] == league_id
        ]

        if not league_matches:
            continue

        metadata = LEAGUE_METADATA.get(
            league_id,
            {
                "name": league_id,
                "flag": "🏳️",
            },
        )

        future_matches = [
            match
            for match in league_matches
            if match["status"] in (
                "SCHEDULED",
                "POSTPONED",
            )
        ]

        next_round_number = (
            future_matches[0]["round_number"]
            if future_matches
            else league_matches[-1]["round_number"]
        )

        league_rounds.append(
            {
                "league_id": league_id,
                "country_name": metadata["name"],
                "flag": metadata["flag"],
                "round_number": next_round_number,
            }
        )

        league_versions.append(
            {
                "league_id": league_id,
                "country_name": metadata["name"],
                "flag": metadata["flag"],
                "model_history": league_summary.get(
                    "model_history",
                    [],
                ),
            }
        )

    future_matches_for_scroll = [
        match
        for match in matches
        if match["status"] in (
            "SCHEDULED",
            "POSTPONED",
        )
    ]

    next_match_id = None

    if future_matches_for_scroll:
        next_match = min(
            future_matches_for_scroll,
            key=lambda match: match["sort_timestamp"],
        )
        next_match_id = next_match["match_id"]

    accuracy = get_algorithm_accuracy()

    if accuracy is None:
        algorithm_accuracy_label = "Sem dados"
    else:
        algorithm_accuracy_label = f"{accuracy:.2f}%"

    timestamps = [
        match["prediction_timestamp"]
        for match in matches
        if match["prediction_timestamp"]
    ]

    updated_at = (
        max(timestamps)
        if timestamps
        else "Sem registo"
    )

    return render_template_string(
        HTML_TEMPLATE,
        matches=matches,
        round_number=round_number,
        updated_at=updated_at,
        initial_bankroll=betting_state["initial_bankroll"],
        current_bankroll=betting_state["current_bankroll"],
        stake_mode=betting_state["stake_mode"],
        default_stake_value=betting_state[
            "default_stake_value"
        ],
        league_rounds=league_rounds,
        league_versions=league_versions,
        league_summaries=league_summaries,
        algorithm_accuracy_label=algorithm_accuracy_label,
        next_match_id=next_match_id,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)

