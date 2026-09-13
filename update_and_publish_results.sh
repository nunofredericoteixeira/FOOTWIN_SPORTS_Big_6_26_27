#!/bin/zsh

set -euo pipefail

PROJECT_DIR="/Users/admin/PycharmProjects/pythonProject/FOOTWIN_SPORTS_Big_6_26_27"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_PREFIX="[FOOTWIN $(date '+%Y-%m-%d %H:%M:%S')]"

cd "$PROJECT_DIR"

echo "$LOG_PREFIX Início da atualização."

"$PYTHON" -c "
from src.services.final_result_service import run_final_result_update
from src.services.prediction_evaluation_service import run_prediction_evaluation
from src.services.supabase_prediction_runtime_service import sync_league_evaluation_runtime
from src.database.init_database import get_database_path

database_path = get_database_path()

summary = run_final_result_update(
    league_id=None,
    season_label='2026/27',
    minutes_after_kickoff=120,
    database_path=database_path,
)

print(summary)

for league_id in ('POR1', 'ESP1', 'ENG1', 'FRA1', 'ITA1', 'GER1'):
    evaluation_summary = run_prediction_evaluation(
        league_id=league_id,
        season_label='2026/27',
        model_version=None,
        database_path=database_path,
    )

    print(league_id, evaluation_summary)

    if evaluation_summary.inserted_evaluations > 0:
        synced = sync_league_evaluation_runtime(
            league_id=league_id,
            database_path=database_path,
        )
        print(
            'EVALUATION RUNTIME SYNC | '
            f'league={league_id} | evaluations={synced}'
        )
"

"$PYTHON" generate_public_site.py

if git diff --quiet -- docs/index.html; then
    echo "$LOG_PREFIX Sem alterações no site público."
    exit 0
fi

git add docs/index.html
git commit docs/index.html -m "Atualizar resultados finais e validação dos prognósticos"
git push origin master

echo "$LOG_PREFIX Site público atualizado e publicado."
