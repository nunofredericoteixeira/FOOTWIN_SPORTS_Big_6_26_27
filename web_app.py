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
from src.services.supabase_auth_service import (
    SupabaseAuthError,
    login_user,
    logout_user,
    register_user,
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

        .summary {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .summary-card,
        .match-card {
            background: rgba(16, 29, 47, 0.92);
            border: 1px solid var(--border);
            border-radius: 18px;
            box-shadow: 0 18px 48px rgba(0, 0, 0, 0.22);
        }

        .summary-card {
            padding: 20px;
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
        <section class="summary">
            <article class="summary-card">
                <span>Próxima jornada</span>

                <div class="summary-list">
                    {% for item in league_rounds %}
                        <div class="summary-row">
                            <div class="summary-league">
                                {% if item.league_id == "ENG1" %}
                                    <img class="summary-flag-image" src="/assets/england-flag.svg" alt="Inglaterra">
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

            <article class="summary-card">
                <span>Versões por campeonato</span>

                <div class="summary-list">
                    {% for item in league_versions %}
                        <div class="summary-row">
                            <div class="summary-league">
                                {% if item.league_id == "ENG1" %}
                                    <img class="summary-flag-image" src="/assets/england-flag.svg" alt="Inglaterra">
                                {% elif item.league_id == "ESP1" %}
                                    <img class="summary-flag-image" src="/assets/spain-flag.svg" alt="Espanha">
                                {% else %}
                                    {{ item.flag }}
                                {% endif %}
                                {{ item.league_id }}
                            </div>

                            <strong>
                                {{ item.version_label }}
                            </strong>

                            {% if item.changed_count %}
                                <small class="changed">
                                    Houve alteração
                                </small>
                            {% else %}
                                <small class="unchanged">
                                    Sem alteração
                                </small>
                            {% endif %}
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
                    <option value="fixed">
                        Valor fixo (€)
                    </option>
                    <option value="percentage">
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
                    {% if match.match_id == next_match_id %}
                    id="next-match"
                    {% endif %}
                >
                    <aside class="league-rail">
                        <div class="league-flag">
                            {% if match.league_id == "ENG1" %}
                                <img class="league-flag-image" src="/assets/england-flag.svg" alt="Inglaterra">
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
                            <div class="date">{{ match.display_date }}</div>
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

            now_local = datetime.now(
                local_timezone
            ).replace(
                tzinfo=None
            ).strftime("%Y-%m-%d %H:%M:%S")

            next_round_row = connection.execute(
                """
                SELECT round_number
                FROM matches
                WHERE league_id = ?
                  AND season_label = ?
                  AND status IN ('SCHEDULED', 'POSTPONED')
                  AND match_date >= ?
                  AND round_number IS NOT NULL
                ORDER BY match_date, round_number, match_id
                LIMIT 1
                """,
                (
                    league_id,
                    SEASON_LABEL,
                    now_local,
                ),
            ).fetchone()

            if next_round_row is None:
                continue

            round_number = int(
                next_round_row["round_number"]
            )

            league_rounds.append(
                {
                    "league_id": league_id,
                    "round_number": round_number,
                    "flag": metadata["flag"],
                    "country_name": metadata["name"],
                }
            )

            rows = connection.execute(
                """
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
                      OR (
                          m.round_number = ?
                          AND m.status IN ('SCHEDULED', 'POSTPONED')
                      )
                  )
                ORDER BY m.match_date, m.match_id
                """,
                (
                    league_id,
                    SEASON_LABEL,
                    round_number,
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
                    parsed_date = datetime.fromisoformat(
                        str(match_date).replace("Z", "+00:00")
                    )

                    if parsed_date.tzinfo is None:
                        local_date = parsed_date.replace(
                            tzinfo=timezone.utc
                        ).astimezone(
                            local_timezone
                        )
                    else:
                        local_date = parsed_date.astimezone(
                            local_timezone
                        )

                    display_date = local_date.strftime(
                        "%d/%m/%Y · %H:%M"
                    )

                    sort_timestamp = local_date.astimezone(
                        timezone.utc
                    )

                except (TypeError, ValueError):
                    display_date = (
                        match_date or "Data por definir"
                    )
                    sort_timestamp = datetime.max.replace(
                        tzinfo=timezone.utc
                    )

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




def get_algorithm_accuracy() -> float | None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        row = connection.execute(
            """
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
            WHERE m.season_label = ?
              AND pe.prudent_outcome_hit IS NOT NULL
            """,
            (SEASON_LABEL,),
        ).fetchone()

    if row is None or row["accuracy"] is None:
        return None

    return float(row["accuracy"])


def get_user_betting_state(
    user_id: str,
    matches: list[dict],
) -> dict:
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        bankroll_row = connection.execute(
            """
            SELECT initial_bankroll
            FROM user_bankrolls
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        initial_bankroll = (
            float(bankroll_row["initial_bankroll"])
            if bankroll_row is not None
            else 0.0
        )

        bet_rows = connection.execute(
            """
            SELECT match_id, odd, stake, prudent_prediction
            FROM user_bets
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()

    bets_by_match = {
        str(row["match_id"]): {
            "odd": (
                float(row["odd"])
                if row["odd"] is not None
                else None
            ),
            "stake": (
                float(row["stake"])
                if row["stake"] is not None
                else None
            ),
            "prudent_prediction": row["prudent_prediction"],
        }
        for row in bet_rows
    }

    current_bankroll = initial_bankroll

    for match in matches:
        bet = bets_by_match.get(match["match_id"], {})
        odd = bet.get("odd")
        stake = bet.get("stake")
        bet_prudent = (
            bet.get("prudent_prediction")
            or match["prudent"]
        )

        match["bet_odd"] = odd
        match["bet_stake"] = stake
        match["bet_prudent"] = bet_prudent
        match["bet_status"] = "pending"

        if (
            odd is None
            or stake is None
            or odd <= 0
            or stake <= 0
            or not match["actual_score"]
        ):
            continue

        home_text, away_text = match["actual_score"].split("-", 1)
        home_goals = int(home_text)
        away_goals = int(away_text)

        if home_goals > away_goals:
            final_result = "1"
        elif home_goals < away_goals:
            final_result = "2"
        else:
            final_result = "X"

        if final_result in bet_prudent:
            match["bet_status"] = "won"
            current_bankroll += (odd - 1.0) * stake
        else:
            match["bet_status"] = "lost"
            current_bankroll -= stake

    return {
        "initial_bankroll": initial_bankroll,
        "current_bankroll": current_bankroll,
    }


def login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not session.get("access_token"):
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

    if not user_id:
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
        match["match_id"]: match
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

        if odd_raw in (None, "") and stake_raw in (None, ""):
            validated_bets.append(
                {
                    "match_id": match_id,
                    "odd": None,
                    "stake": None,
                    "prudent_prediction": match["prudent"],
                }
            )
            continue

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

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            INSERT INTO user_bankrolls (
                user_id,
                initial_bankroll,
                updated_at
            )
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                initial_bankroll = excluded.initial_bankroll,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                initial_bankroll,
            ),
        )

        for bet in validated_bets:
            connection.execute(
                """
                INSERT INTO user_bets (
                    user_id,
                    match_id,
                    odd,
                    stake,
                    prudent_prediction,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, match_id) DO UPDATE SET
                    odd = excluded.odd,
                    stake = excluded.stake,
                    prudent_prediction = (
                        CASE
                            WHEN user_bets.prudent_prediction
                                IS NOT NULL
                            THEN user_bets.prudent_prediction
                            ELSE excluded.prudent_prediction
                        END
                    ),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    bet["match_id"],
                    bet["odd"],
                    bet["stake"],
                    bet["prudent_prediction"],
                ),
            )

        connection.commit()

    _, refreshed_matches = get_next_round_matches()
    betting_state = get_user_betting_state(
        user_id=user_id,
        matches=refreshed_matches,
    )

    return jsonify(
        {
            "ok": True,
            "initial_bankroll": (
                betting_state["initial_bankroll"]
            ),
            "current_bankroll": (
                betting_state["current_bankroll"]
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
    try:
        run_final_result_update(
            league_id="POR1",
            season_label=SEASON_LABEL,
            minutes_after_kickoff=120,
            database_path=DATABASE_PATH,
        )
    except Exception as exc:
        print(
            "AVISO: não foi possível atualizar "
            f"os resultados finais: {exc}"
        )

    round_number, matches = get_next_round_matches()

    user_id = session.get("user_id")

    betting_state = get_user_betting_state(
        user_id=user_id,
        matches=matches,
    )

    league_rounds = []
    league_versions = []

    league_order = [
        "POR1",
        "ENG1",
        "ESP1",
        "FRA1",
        "ITA1",
        "GER1",
    ]

    for league_id in league_order:
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

        max_version = max(
            match["prediction_version"]
            for match in league_matches
        )

        changed_count = sum(
            1
            for match in league_matches
            if match["prediction_changed"]
        )

        league_versions.append(
            {
                "league_id": league_id,
                "country_name": metadata["name"],
                "flag": metadata["flag"],
                "version_label": f"V{max_version:03d}",
                "changed_count": changed_count,
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
        league_rounds=league_rounds,
        league_versions=league_versions,
        algorithm_accuracy_label=algorithm_accuracy_label,
        next_match_id=next_match_id,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)

