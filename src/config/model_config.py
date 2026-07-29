# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.config.path_config import load_paths_config


class ModelConfigurationError(RuntimeError):
    """Erro relacionado com a configuração do modelo FOOTWIN SPORTS."""


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Carrega um ficheiro YAML e garante que o conteúdo é um dicionário."""

    if not path.exists():
        raise ModelConfigurationError(
            f"Ficheiro de configuração inexistente: {path}"
        )

    try:
        with path.open("r", encoding="utf-8") as file:
            content = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:
        raise ModelConfigurationError(
            f"Erro ao interpretar o ficheiro YAML: {path}"
        ) from exc

    if not isinstance(content, dict):
        raise ModelConfigurationError(
            f"O conteúdo de {path.name} deve ser um dicionário YAML."
        )

    return content


def load_model_version() -> dict[str, Any]:
    """Carrega e valida config/model_version.yaml."""

    paths = load_paths_config()
    config_path = paths["project_root"] / "config" / "model_version.yaml"

    config = _load_yaml_file(config_path)
    validate_model_version(config)

    return config


def load_model_weights() -> dict[str, Any]:
    """Carrega e valida config/model_weights.yaml."""

    paths = load_paths_config()
    config_path = paths["project_root"] / "config" / "model_weights.yaml"

    config = _load_yaml_file(config_path)
    validate_model_weights(config)

    return config


def load_full_model_config() -> dict[str, Any]:
    """Devolve a configuração consolidada do modelo."""

    return {
        "version": load_model_version(),
        "weights": load_model_weights(),
    }


def validate_model_version(config: dict[str, Any]) -> None:
    """Valida os campos essenciais da versão do modelo."""

    required_fields = {
        "model_version",
        "model_name",
        "status",
        "season_label",
        "enabled_components",
        "goal_model",
        "simulation_model",
        "dataset",
    }

    missing = required_fields - set(config)

    if missing:
        raise ModelConfigurationError(
            "Faltam campos em model_version.yaml: "
            + ", ".join(sorted(missing))
        )

    if config["model_version"] != "MODEL_0_1":
        raise ModelConfigurationError(
            "Nesta primeira fase, model_version deve ser MODEL_0_1."
        )

    if config["season_label"] != "2026/27":
        raise ModelConfigurationError(
            "A época configurada deve ser 2026/27."
        )

    enabled_components = config["enabled_components"]

    if not isinstance(enabled_components, dict):
        raise ModelConfigurationError(
            "enabled_components deve ser um dicionário."
        )

    if enabled_components.get("collective_performance") is not True:
        raise ModelConfigurationError(
            "collective_performance deve estar ativo no Modelo 0.1."
        )


def validate_model_weights(config: dict[str, Any]) -> None:
    """Valida pesos, limites e parâmetros do Modelo 0.1."""

    required_sections = {
        "performance",
        "rating_conversion",
        "promotion",
        "poisson",
        "home_advantage",
        "simulation",
        "validation",
        "alerts",
    }

    missing_sections = required_sections - set(config)

    if missing_sections:
        raise ModelConfigurationError(
            "Faltam secções em model_weights.yaml: "
            + ", ".join(sorted(missing_sections))
        )

    _validate_performance_weights(config["performance"])
    _validate_rating_conversion(config["rating_conversion"])
    _validate_promotion_config(config["promotion"])
    _validate_poisson_config(config["poisson"])
    _validate_home_advantage(config["home_advantage"])
    _validate_simulation_config(config["simulation"])
    _validate_expected_totals(config["validation"])


def _validate_performance_weights(config: dict[str, Any]) -> None:
    required = {
        "ppg_weight",
        "attack_weight",
        "defence_weight",
        "goal_difference_weight",
    }

    missing = required - set(config)

    if missing:
        raise ModelConfigurationError(
            "Faltam pesos de desempenho: "
            + ", ".join(sorted(missing))
        )

    total = sum(float(config[field]) for field in required)

    if abs(total - 1.0) > 0.000001:
        raise ModelConfigurationError(
            f"Os pesos de desempenho devem somar 1,00. Soma atual: {total:.6f}"
        )

    for field in required:
        value = float(config[field])

        if value < 0 or value > 1:
            raise ModelConfigurationError(
                f"{field} deve estar entre 0 e 1."
            )


def _validate_rating_conversion(config: dict[str, Any]) -> None:
    minimum = float(config["minimum_rating"])
    maximum = float(config["maximum_rating"])
    center = float(config["center"])
    multiplier = float(config["zscore_multiplier"])
    minimum_std = float(config["minimum_standard_deviation"])

    if minimum >= maximum:
        raise ModelConfigurationError(
            "minimum_rating deve ser inferior a maximum_rating."
        )

    if not minimum <= center <= maximum:
        raise ModelConfigurationError(
            "O centro do rating deve ficar dentro dos limites."
        )

    if multiplier <= 0:
        raise ModelConfigurationError(
            "zscore_multiplier deve ser positivo."
        )

    if minimum_std <= 0:
        raise ModelConfigurationError(
            "minimum_standard_deviation deve ser positivo."
        )


def _validate_promotion_config(config: dict[str, Any]) -> None:
    required_groups = {"general", "attack", "defence"}

    missing = required_groups - set(config)

    if missing:
        raise ModelConfigurationError(
            "Faltam grupos na configuração das promovidas: "
            + ", ".join(sorted(missing))
        )

    required_factors = {
        "champion_factor",
        "direct_factor",
        "playoff_factor",
    }

    for group_name in required_groups:
        group = config[group_name]
        missing_factors = required_factors - set(group)

        if missing_factors:
            raise ModelConfigurationError(
                f"Faltam fatores em promotion.{group_name}: "
                + ", ".join(sorted(missing_factors))
            )

        for factor_name in required_factors:
            value = float(group[factor_name])

            if value <= 0 or value > 1:
                raise ModelConfigurationError(
                    f"promotion.{group_name}.{factor_name} "
                    "deve estar entre 0 e 1."
                )

        if not (
            float(group["champion_factor"])
            >= float(group["direct_factor"])
            >= float(group["playoff_factor"])
        ):
            raise ModelConfigurationError(
                f"Os fatores de promotion.{group_name} devem respeitar: "
                "champion >= direct >= playoff."
            )

    regression_weight = float(
        config["first_division_regression_weight"]
    )

    if regression_weight < 0 or regression_weight > 1:
        raise ModelConfigurationError(
            "first_division_regression_weight deve estar entre 0 e 1."
        )


def _validate_poisson_config(config: dict[str, Any]) -> None:
    attack_scale = float(config["attack_scale"])
    defence_scale = float(config["defence_scale"])
    minimum_lambda = float(config["minimum_lambda"])
    maximum_lambda = float(config["maximum_lambda"])
    maximum_goals = int(config["maximum_goals"])

    if attack_scale <= 0 or defence_scale <= 0:
        raise ModelConfigurationError(
            "As escalas de ataque e defesa devem ser positivas."
        )

    if minimum_lambda <= 0:
        raise ModelConfigurationError(
            "minimum_lambda deve ser superior a zero."
        )

    if maximum_lambda <= minimum_lambda:
        raise ModelConfigurationError(
            "maximum_lambda deve ser superior a minimum_lambda."
        )

    if maximum_goals < 5:
        raise ModelConfigurationError(
            "maximum_goals deve ser pelo menos 5."
        )


def _validate_home_advantage(config: dict[str, Any]) -> None:
    home_share = float(config["home_goal_share"])
    away_share = float(config["away_goal_share"])

    if home_share <= 0 or away_share <= 0:
        raise ModelConfigurationError(
            "As percentagens de golos de casa e fora devem ser positivas."
        )

    if abs((home_share + away_share) - 1.0) > 0.000001:
        raise ModelConfigurationError(
            "home_goal_share e away_goal_share devem somar 1,00."
        )


def _validate_simulation_config(config: dict[str, Any]) -> None:
    quick_runs = int(config["quick_runs"])
    default_runs = int(config["default_runs"])
    official_runs = int(config["official_runs"])
    random_seed = int(config["random_seed"])

    if quick_runs <= 0 or default_runs <= 0 or official_runs <= 0:
        raise ModelConfigurationError(
            "O número de simulações deve ser positivo."
        )

    if not quick_runs <= default_runs <= official_runs:
        raise ModelConfigurationError(
            "Deve respeitar quick_runs <= default_runs <= official_runs."
        )

    if random_seed < 0:
        raise ModelConfigurationError(
            "random_seed não pode ser negativa."
        )


def _validate_expected_totals(config: dict[str, Any]) -> None:
    if int(config["expected_leagues"]) != 6:
        raise ModelConfigurationError(
            "expected_leagues deve ser 6."
        )

    if int(config["expected_teams"]) != 114:
        raise ModelConfigurationError(
            "expected_teams deve ser 114."
        )

    if int(config["expected_matches"]) != 2058:
        raise ModelConfigurationError(
            "expected_matches deve ser 2058."
        )
