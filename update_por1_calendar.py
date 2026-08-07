# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from urllib.request import Request, urlopen

from src.config.model_config import load_model_version
from src.importers.fixtures_importer import import_fixtures
from src.collectors.write_por1_calendar_to_dataset import (
    DATASET_PATH,
    ICS_PATH,
    read_calendar,
    validate_matches,
    write_dataset,
)


REMOTE_ICS_URL = (
    "https://www.ligaportugal.pt/"
    "calendars-ics/ligaportugalbetclic.ics"
)

REMOTE_TEMP_PATH = ICS_PATH.with_suffix(".remote.ics")
LOCAL_BACKUP_PATH = ICS_PATH.with_suffix(".backup.ics")

MEANINGFUL_FIELDS = {
    "URL",
    "SUMMARY",
    "DTSTART",
    "DTEND",
    "LOCATION",
    "SEQUENCE",
    "DESCRIPTION",
}


def download_remote_calendar() -> bytes:
    request = Request(
        REMOTE_ICS_URL,
        headers={"User-Agent": "FOOTWIN-SPORTS/1.0"},
    )

    with urlopen(request, timeout=60) as response:
        return response.read()


def unfold_lines(text: str) -> list[str]:
    unfolded: list[str] = []

    for line in text.splitlines():
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)

    return unfolded


def parse_events(text: str) -> dict[str, dict[str, str]]:
    events: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None

    for line in unfold_lines(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue

        if line == "END:VEVENT":
            if current:
                key = current.get("URL") or current.get("DESCRIPTION")

                if key:
                    events[key] = {
                        field: current.get(field, "")
                        for field in MEANINGFUL_FIELDS
                    }

            current = None
            continue

        if current is None or ":" not in line:
            continue

        raw_key, value = line.split(":", 1)
        key = raw_key.split(";", 1)[0]

        if key in MEANINGFUL_FIELDS:
            current[key] = value

    return events


def detect_changes(
    local_text: str,
    remote_text: str,
) -> tuple[list[str], list[str], list[str]]:
    local_events = parse_events(local_text)
    remote_events = parse_events(remote_text)

    local_keys = set(local_events)
    remote_keys = set(remote_events)

    added = sorted(remote_keys - local_keys)
    removed = sorted(local_keys - remote_keys)
    changed = sorted(
        key
        for key in local_keys & remote_keys
        if local_events[key] != remote_events[key]
    )

    return added, removed, changed


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    print("=" * 100)
    print("POR1 — ATUALIZAÇÃO DIÁRIA DO CALENDÁRIO OFICIAL")
    print("=" * 100)

    remote_data = download_remote_calendar()
    remote_text = remote_data.decode(
        "utf-8",
        errors="replace",
    )

    if ICS_PATH.exists():
        local_data = ICS_PATH.read_bytes()
        local_text = local_data.decode(
            "utf-8",
            errors="replace",
        )
    else:
        local_data = b""
        local_text = ""

    added, removed, changed = detect_changes(
        local_text=local_text,
        remote_text=remote_text,
    )

    print(f"URL oficial: {REMOTE_ICS_URL}")
    print(f"Jogos novos: {len(added)}")
    print(f"Jogos removidos: {len(removed)}")
    print(f"Jogos alterados: {len(changed)}")
    print(f"SHA256 local:  {sha256(local_data) if local_data else 'INEXISTENTE'}")
    print(f"SHA256 remoto: {sha256(remote_data)}")

    if not added and not removed and not changed:
        print("Sem alterações reais no calendário.")
        print("RESULTADO: UNCHANGED")
        return

    ICS_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REMOTE_TEMP_PATH.write_bytes(remote_data)

    if ICS_PATH.exists():
        shutil.copy2(
            ICS_PATH,
            LOCAL_BACKUP_PATH,
        )

    shutil.move(
        str(REMOTE_TEMP_PATH),
        str(ICS_PATH),
    )

    try:
        matches = read_calendar()
        validate_matches(matches)
        write_dataset(matches)

        model_config = load_model_version()
        dataset_version = str(
            model_config["dataset"]["expected_version"]
        )

        result = import_fixtures(
            dataset_path=DATASET_PATH,
            dataset_version=dataset_version,
            require_approved_dataset=False,
        )

    except Exception:
        if LOCAL_BACKUP_PATH.exists():
            shutil.copy2(
                LOCAL_BACKUP_PATH,
                ICS_PATH,
            )

        raise

    print(f"Jogos gravados no Excel: {len(matches)}")
    print(f"SQLite inseridos: {result.inserted}")
    print(f"SQLite atualizados: {result.updated}")
    print(f"SQLite inalterados: {result.unchanged}")
    print(f"SQLite ignorados: {result.skipped}")
    print(f"SQLite erros: {result.errors}")
    print("RESULTADO: SUCCESS")


if __name__ == "__main__":
    main()
