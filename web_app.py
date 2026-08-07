from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template_string

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "footwin_sports.db"

app = Flask(__name__)

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
            grid-template-columns: repeat(3, 1fr);
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

        .summary-card span {
            display: block;
            color: var(--muted);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.9px;
        }

        .summary-card strong {
            display: block;
            margin-top: 8px;
            font-size: 27px;
        }

        .matches {
            display: grid;
            gap: 16px;
        }

        .match-card {
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
            margin-top: 6px;
            font-size: 21px;
        }

        .prediction {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 14px;
            margin-top: 17px;
            padding-top: 17px;
            border-top: 1px solid var(--border);
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

            .probabilities {
                gap: 8px;
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
        <div>
            <div class="subtitle">FOOTWIN SPORTS</div>
            <h1>Prognósticos POR1</h1>
        </div>
        <div class="updated">Atualizado: {{ updated_at }}</div>
    </header>

    {% if matches %}
        <section class="summary">
            <article class="summary-card">
                <span>Próxima jornada</span>
                <strong>{{ round_number }}</strong>
            </article>
            <article class="summary-card">
                <span>Jogos</span>
                <strong>{{ matches|length }}</strong>
            </article>
            <article class="summary-card">
                <span>Chave final</span>
                <strong>{{ key }}</strong>
            </article>
        </section>

        <main class="matches">
            {% for match in matches %}
                <article class="match-card">
                    <div class="match-top">
                        <div class="teams">{{ match.home_team }} — {{ match.away_team }}</div>
                        <div class="date">{{ match.display_date }}</div>
                    </div>

                    <div class="probabilities">
                        <div class="probability">
                            <span>Vitória casa</span>
                            <strong>{{ "%.2f"|format(match.home_probability * 100) }}%</strong>
                        </div>
                        <div class="probability">
                            <span>Empate</span>
                            <strong>{{ "%.2f"|format(match.draw_probability * 100) }}%</strong>
                        </div>
                        <div class="probability">
                            <span>Vitória fora</span>
                            <strong>{{ "%.2f"|format(match.away_probability * 100) }}%</strong>
                        </div>
                    </div>

                    <div class="prediction">
                        <div>
                            <div class="subtitle">Prognóstico prudente</div>
                            <span class="badge">{{ match.prudent }}</span>
                        </div>
                        <div class="score">
                            Resultado mais provável:
                            <strong>{{ match.most_likely_score or "—" }}</strong>
                        </div>
                    </div>
                </article>
            {% endfor %}
        </main>
    {% else %}
        <div class="empty">Não existem prognósticos disponíveis para a próxima jornada.</div>
    {% endif %}
</div>
</body>
</html>
"""


def prudent_prediction(home: float, draw: float, away: float) -> str:
    probabilities = [
        ("1", home),
        ("X", draw),
        ("2", away),
    ]
    probabilities.sort(key=lambda item: item[1], reverse=True)

    first_label, first_value = probabilities[0]
    second_label, second_value = probabilities[1]

    if (first_value - second_value) <= 0.10:
        order = {"1": 0, "X": 1, "2": 2}
        return "".join(
            sorted(
                [first_label, second_label],
                key=lambda label: order[label],
            )
        )

    return first_label


def get_next_round_matches() -> tuple[int | None, list[dict]]:
    now_utc = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        next_round_row = connection.execute(
            """
            SELECT round_number
            FROM matches
            WHERE league_id = 'POR1'
              AND season_label = '2026/27'
              AND status IN ('SCHEDULED', 'POSTPONED')
              AND match_date >= ?
              AND round_number IS NOT NULL
            ORDER BY match_date, round_number, match_id
            LIMIT 1
            """,
            (now_utc,),
        ).fetchone()

        if next_round_row is None:
            return None, []

        round_number = int(next_round_row["round_number"])

        rows = connection.execute(
            """
            SELECT
                m.match_id,
                m.round_number,
                m.match_date,
                home.team_name AS home_team,
                away.team_name AS away_team,
                p.home_win_probability,
                p.draw_probability,
                p.away_win_probability,
                p.most_likely_score,
                p.prediction_timestamp
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
                  ORDER BY p2.prediction_timestamp DESC, p2.created_at DESC
                  LIMIT 1
              )
            WHERE m.league_id = 'POR1'
              AND m.season_label = '2026/27'
              AND m.round_number = ?
              AND m.status IN ('SCHEDULED', 'POSTPONED')
            ORDER BY m.match_date, m.match_id
            """,
            (round_number,),
        ).fetchall()

    matches = []

    for row in rows:
        match_date = row["match_date"]
        try:
            parsed_date = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            display_date = parsed_date.astimezone().strftime("%d/%m/%Y · %H:%M")
        except (TypeError, ValueError):
            display_date = match_date or "Data por definir"

        home_probability = float(row["home_win_probability"])
        draw_probability = float(row["draw_probability"])
        away_probability = float(row["away_win_probability"])

        matches.append(
            {
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "display_date": display_date,
                "home_probability": home_probability,
                "draw_probability": draw_probability,
                "away_probability": away_probability,
                "most_likely_score": row["most_likely_score"],
                "prudent": prudent_prediction(
                    home_probability,
                    draw_probability,
                    away_probability,
                ),
                "prediction_timestamp": row["prediction_timestamp"],
            }
        )

    return round_number, matches


@app.route("/")
def predictions():
    round_number, matches = get_next_round_matches()
    key = ", ".join(match["prudent"] for match in matches)

    timestamps = [
        match["prediction_timestamp"]
        for match in matches
        if match["prediction_timestamp"]
    ]
    updated_at = max(timestamps) if timestamps else "Sem registo"

    return render_template_string(
        HTML_TEMPLATE,
        matches=matches,
        round_number=round_number,
        key=key,
        updated_at=updated_at,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
