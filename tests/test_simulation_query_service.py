# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from src.models.simulation_query_service import (
    PositionProbability,
    SimulationQueryError,
    SimulationTeamSummary,
    clean_required_text,
    get_latest_simulation,
    get_position_probability,
    get_simulation_by_id,
    list_simulations,
    validate_position_probabilities,
    validate_positive_integer,
    validate_simulation_summary,
)


def build_team_summary(
    team_id: str,
    team_name: str,
    title_probability: float,
    position_probabilities: tuple[
        PositionProbability,
        ...
    ],
) -> SimulationTeamSummary:
    return SimulationTeamSummary(
        team_id=team_id,
        team_name=team_name,
        average_position=1.5,
        median_position=1.0,
        average_points=4.0,
        average_goals_for=3.0,
        average_goals_against=1.5,
        average_goal_difference=1.5,
        title_probability=title_probability,
        europe_probability=0.75,
        relegation_probability=0.25,
        playoff_probability=0.0,
        points_p10=1.0,
        points_p25=3.0,
        points_p50=4.0,
        points_p75=6.0,
        points_p90=6.0,
        position_probabilities=position_probabilities,
    )


class TestPositionProbabilityValidation(
    unittest.TestCase
):
    def test_valid_probabilities(self) -> None:
        probabilities = (
            PositionProbability(
                position=1,
                probability=0.60,
            ),
            PositionProbability(
                position=2,
                probability=0.40,
            ),
        )

        validate_position_probabilities(
            team_id="TEAM_A",
            probabilities=probabilities,
        )

    def test_probabilities_must_sum_to_one(
        self,
    ) -> None:
        probabilities = (
            PositionProbability(
                position=1,
                probability=0.50,
            ),
            PositionProbability(
                position=2,
                probability=0.30,
            ),
        )

        with self.assertRaises(
            SimulationQueryError
        ):
            validate_position_probabilities(
                team_id="TEAM_A",
                probabilities=probabilities,
            )

    def test_duplicate_position_is_rejected(
        self,
    ) -> None:
        probabilities = (
            PositionProbability(
                position=1,
                probability=0.50,
            ),
            PositionProbability(
                position=1,
                probability=0.50,
            ),
        )

        with self.assertRaises(
            SimulationQueryError
        ):
            validate_position_probabilities(
                team_id="TEAM_A",
                probabilities=probabilities,
            )

    def test_probability_outside_range_is_rejected(
        self,
    ) -> None:
        probabilities = (
            PositionProbability(
                position=1,
                probability=1.10,
            ),
            PositionProbability(
                position=2,
                probability=-0.10,
            ),
        )

        with self.assertRaises(
            SimulationQueryError
        ):
            validate_position_probabilities(
                team_id="TEAM_A",
                probabilities=probabilities,
            )

    def test_empty_probabilities_are_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            SimulationQueryError
        ):
            validate_position_probabilities(
                team_id="TEAM_A",
                probabilities=(),
            )


class TestSimulationSummaryValidation(
    unittest.TestCase
):
    def test_valid_two_team_summary(self) -> None:
        team_a = build_team_summary(
            team_id="TEAM_A",
            team_name="Team A",
            title_probability=0.60,
            position_probabilities=(
                PositionProbability(
                    position=1,
                    probability=0.60,
                ),
                PositionProbability(
                    position=2,
                    probability=0.40,
                ),
            ),
        )

        team_b = build_team_summary(
            team_id="TEAM_B",
            team_name="Team B",
            title_probability=0.40,
            position_probabilities=(
                PositionProbability(
                    position=1,
                    probability=0.40,
                ),
                PositionProbability(
                    position=2,
                    probability=0.60,
                ),
            ),
        )

        validate_simulation_summary(
            simulation_id="SIM_TEST",
            teams=[
                team_a,
                team_b,
            ],
        )

    def test_title_total_must_equal_one(
        self,
    ) -> None:
        team_a = build_team_summary(
            team_id="TEAM_A",
            team_name="Team A",
            title_probability=0.70,
            position_probabilities=(
                PositionProbability(
                    position=1,
                    probability=0.60,
                ),
                PositionProbability(
                    position=2,
                    probability=0.40,
                ),
            ),
        )

        team_b = build_team_summary(
            team_id="TEAM_B",
            team_name="Team B",
            title_probability=0.50,
            position_probabilities=(
                PositionProbability(
                    position=1,
                    probability=0.40,
                ),
                PositionProbability(
                    position=2,
                    probability=0.60,
                ),
            ),
        )

        with self.assertRaises(
            SimulationQueryError
        ):
            validate_simulation_summary(
                simulation_id="SIM_TEST",
                teams=[
                    team_a,
                    team_b,
                ],
            )

    def test_each_position_total_must_equal_one(
        self,
    ) -> None:
        team_a = build_team_summary(
            team_id="TEAM_A",
            team_name="Team A",
            title_probability=0.50,
            position_probabilities=(
                PositionProbability(
                    position=1,
                    probability=0.70,
                ),
                PositionProbability(
                    position=2,
                    probability=0.30,
                ),
            ),
        )

        team_b = build_team_summary(
            team_id="TEAM_B",
            team_name="Team B",
            title_probability=0.50,
            position_probabilities=(
                PositionProbability(
                    position=1,
                    probability=0.20,
                ),
                PositionProbability(
                    position=2,
                    probability=0.80,
                ),
            ),
        )

        with self.assertRaises(
            SimulationQueryError
        ):
            validate_simulation_summary(
                simulation_id="SIM_TEST",
                teams=[
                    team_a,
                    team_b,
                ],
            )

    def test_less_than_two_teams_is_rejected(
        self,
    ) -> None:
        team_a = build_team_summary(
            team_id="TEAM_A",
            team_name="Team A",
            title_probability=1.0,
            position_probabilities=(
                PositionProbability(
                    position=1,
                    probability=1.0,
                ),
            ),
        )

        with self.assertRaises(
            SimulationQueryError
        ):
            validate_simulation_summary(
                simulation_id="SIM_TEST",
                teams=[
                    team_a,
                ],
            )


class TestPositionLookup(unittest.TestCase):
    def setUp(self) -> None:
        self.team = build_team_summary(
            team_id="TEAM_A",
            team_name="Team A",
            title_probability=0.60,
            position_probabilities=(
                PositionProbability(
                    position=1,
                    probability=0.60,
                ),
                PositionProbability(
                    position=2,
                    probability=0.30,
                ),
                PositionProbability(
                    position=3,
                    probability=0.10,
                ),
            ),
        )

    def test_existing_position(self) -> None:
        probability = get_position_probability(
            team=self.team,
            position=2,
        )

        self.assertEqual(
            probability,
            0.30,
        )

    def test_missing_position_returns_zero(
        self,
    ) -> None:
        probability = get_position_probability(
            team=self.team,
            position=4,
        )

        self.assertEqual(
            probability,
            0.0,
        )

    def test_invalid_position_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            SimulationQueryError
        ):
            get_position_probability(
                team=self.team,
                position=0,
            )


class TestBasicValidation(unittest.TestCase):
    def test_clean_required_text(self) -> None:
        self.assertEqual(
            clean_required_text(
                " ENG1 ",
                "league_id",
            ),
            "ENG1",
        )

    def test_empty_text_is_rejected(self) -> None:
        with self.assertRaises(
            SimulationQueryError
        ):
            clean_required_text(
                "",
                "league_id",
            )

    def test_positive_integer(self) -> None:
        self.assertEqual(
            validate_positive_integer(
                20,
                "limit",
            ),
            20,
        )

    def test_zero_integer_is_rejected(self) -> None:
        with self.assertRaises(
            SimulationQueryError
        ):
            validate_positive_integer(
                0,
                "limit",
            )


class TestDatabaseQueries(unittest.TestCase):
    def test_get_latest_simulation(self) -> None:
        simulation = get_latest_simulation(
            league_id="ENG1",
            season_label="2026/27",
            model_version="MODEL_0_1",
        )

        self.assertEqual(
            simulation.league_id,
            "ENG1",
        )

        self.assertEqual(
            simulation.status,
            "SUCCESS",
        )

        self.assertEqual(
            simulation.simulation_count,
            10000,
        )

        self.assertEqual(
            len(simulation.teams),
            4,
        )

    def test_get_simulation_by_id(self) -> None:
        latest = get_latest_simulation(
            league_id="ENG1",
            season_label="2026/27",
            model_version="MODEL_0_1",
        )

        simulation = get_simulation_by_id(
            latest.simulation_id
        )

        self.assertEqual(
            simulation.simulation_id,
            latest.simulation_id,
        )

        self.assertEqual(
            simulation.teams,
            latest.teams,
        )

    def test_list_simulations(self) -> None:
        simulations = list_simulations(
            league_id="ENG1",
            season_label="2026/27",
            model_version="MODEL_0_1",
            limit=10,
        )

        self.assertGreaterEqual(
            len(simulations),
            1,
        )

        self.assertEqual(
            simulations[0]["league_id"],
            "ENG1",
        )

    def test_missing_simulation_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            SimulationQueryError
        ):
            get_simulation_by_id(
                "SIMULATION_DOES_NOT_EXIST"
            )


if __name__ == "__main__":
    unittest.main()
