#!/bin/zsh

set -euo pipefail

PROJECT_DIR="/Users/admin/PycharmProjects/pythonProject/FOOTWIN_SPORTS_Big_6_26_27"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_PREFIX="[FOOTWIN $(date '+%Y-%m-%d %H:%M:%S')]"

cd "$PROJECT_DIR"

echo "$LOG_PREFIX Início da atualização."

"$PYTHON" -c "
from src.services.final_result_service import run_final_result_update

summary = run_final_result_update(
    league_id='POR1',
    season_label='2026/27',
    minutes_after_kickoff=120,
)

print(summary)
"

"$PYTHON" generate_public_site.py

if git diff --quiet -- docs/index.html; then
    echo "$LOG_PREFIX Sem alterações no site público."
    exit 0
fi

git add docs/index.html
git commit -m "Atualizar resultados finais e validação dos prognósticos"
git push origin master

echo "$LOG_PREFIX Site público atualizado e publicado."
