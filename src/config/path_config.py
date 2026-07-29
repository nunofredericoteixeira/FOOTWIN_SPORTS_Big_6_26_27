# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class PathConfigurationError(RuntimeError):
    """Erro relacionado com a configuração dos caminhos do projeto."""


def load_paths_config(
    config_file: str | Path | None = None,
) -> dict[str, Any]:
    """
    Carrega o ficheiro config/paths.yaml.

    Os caminhos relativos são convertidos em objetos Path absolutos,
    usando project_root como diretório-base.
    """

    if config_file is None:
        current_file = Path(__file__).resolve()
        project_root = current_file.parents[2]
        config_path = project_root / "config" / "paths.yaml"
    else:
        config_path = Path(config_file).expanduser().resolve()

    if not config_path.exists():
        raise PathConfigurationError(
            f"Ficheiro de configuração inexistente: {config_path}"
        )

    try:
        with config_path.open("r", encoding="utf-8") as file:
            raw_config = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:
        raise PathConfigurationError(
            f"Erro ao interpretar o YAML: {config_path}"
        ) from exc

    configured_root = raw_config.get("project_root")

    if not configured_root:
        raise PathConfigurationError(
            "A propriedade 'project_root' não está definida em paths.yaml."
        )

    project_root = Path(configured_root).expanduser().resolve()

    if not project_root.exists():
        raise PathConfigurationError(
            f"O diretório principal não existe: {project_root}"
        )

    return _resolve_config_paths(
        config=raw_config,
        project_root=project_root,
    )


def _resolve_config_paths(
    config: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    """
    Percorre recursivamente a configuração e converte os caminhos
    relativos em objetos Path absolutos.
    """

    resolved: dict[str, Any] = {}

    for key, value in config.items():
        if key == "project_root":
            resolved[key] = project_root
            continue

        if isinstance(value, dict):
            resolved[key] = _resolve_config_paths(
                config=value,
                project_root=project_root,
            )
            continue

        if isinstance(value, str):
            path_value = Path(value).expanduser()

            if not path_value.is_absolute():
                path_value = project_root / path_value

            resolved[key] = path_value.resolve()
            continue

        resolved[key] = value

    return resolved


def ensure_project_directories(paths_config: dict[str, Any]) -> list[Path]:
    """
    Cria os diretórios configurados que ainda não existam.

    Não tenta criar caminhos que representem ficheiros, como a base SQLite.
    """

    created_directories: list[Path] = []

    file_suffixes = {
        ".db",
        ".sqlite",
        ".sqlite3",
        ".yaml",
        ".yml",
        ".csv",
        ".xlsx",
        ".json",
        ".log",
    }

    def process_value(value: Any) -> None:
        if isinstance(value, dict):
            for nested_value in value.values():
                process_value(nested_value)
            return

        if not isinstance(value, Path):
            return

        if value.suffix.lower() in file_suffixes:
            directory = value.parent
        else:
            directory = value

        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created_directories.append(directory)

    process_value(paths_config)

    return created_directories
