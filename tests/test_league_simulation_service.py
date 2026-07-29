# -*- coding: utf-8 -*-

from __future__ import annotations

import random
import unittest

from src.models.league_simulation_service import (
    LeagueSimulationError,
    SimulationMatch,
    TeamSimulationState,
    apply_match_result,
    is_playoff_position,
    percentile,
    rank_team_states,
    sample_poisson,
    simulate_league,
    validate_position_rules,
    validate_simulation_count,
)


class TestApplyMatchResult(unittest.TestCase):
    def test_home_win(self) -> None:
        home = TeamSimulationState(
            team_id="HOME"
        )

        away = TeamSimulationState(
            team_id="AWAY"
        )

        apply_match_result(
            home_state=home,
            away_state=away,
            home_goals=2,
            away_goals=1,
        )

        self.assertEqual(
            home.points,
            3,
        )

        self.assertEqual(
            away.points,
            0,
        )

        self.assertEqual(
            home.goals_for,
            2,
        )

        self.assertEqual(
            home.goals_against,
            1,
        )

        self.assertEqual(
            away.goals_for,
            1,
        )

        self.assertEqual(
            away.goals_against,
            2,
        )

    def test_draw(self) -> None:
        home = TeamSimulationState(
            team_id="HOME"
        )

        away = TeamSimulationState(
            team_id="AWAY"
        )

        apply_match_result(
            home_state=home,
            away_state=away,
            home_goals=1,
            away_goals=1,
        )

        self.assertEqual(
            home.points,
            1,
        )

        self.assertEqual(
            away.points,
            1,
        )

    def test_away_win(self) -> None:
        home = TeamSimulationState(
            team_id="HOME"
        )

        away = TeamSimulationState(
            team_id="AWAY"
        )

        apply_match_result(
            home_state=home,
            away_state=away,
            home_goals=0,
            away_goals=3,
        )

        self.assertEqual(
            home.points,
            0,
        )

        self.assertEqual(
            away.points,
            3,
        )

        self.assertEqual(
            home.goal_difference,
            -3,
        )

        self.assertEqual(
            away.goal_difference,
            3,
        )


class TestStandings(unittest.TestCase):
    def test_ranking_by_points(self) -> None:
        states = [
            TeamSimulationState(
                team_id="TEAM_B",
                points=3,
                goals_for=2,
                goals_against=1,
            ),
            TeamSimulationState(
                team_id="TEAM_A",
                points=6,
                goals_for=3,
                goals_against=1,
            ),
        ]

        standings = rank_team_states(
            states
        )

        self.assertEqual(
            standings[0].team_id,
            "TEAM_A",
        )

    def test_ranking_by_goal_difference(self) -> None:
        states = [
            TeamSimulationState(
                team_id="TEAM_A",
                points=3,
                goals_for=2,
                goals_against=1,
            ),
            TeamSimulationState(
                team_id="TEAM_B",
                points=3,
                goals_for=4,
                goals_against=1,
            ),
        ]

        standings = rank_team_states(
            states
        )

        self.assertEqual(
            standings[0].team_id,
            "TEAM_B",
        )

    def test_ranking_by_goals_for(self) -> None:
        states = [
            TeamSimulationState(
                team_id="TEAM_A",
                points=3,
                goals_for=2,
                goals_against=1,
            ),
            TeamSimulationState(
                team_id="TEAM_B",
                points=3,
                goals_for=3,
                goals_against=2,
            ),
        ]

        standings = rank_team_states(
            states
        )

        self.assertEqual(
            standings[0].team_id,
            "TEAM_B",
        )

    def test_team_id_is_final_tiebreaker(self) -> None:
        states = [
            TeamSimulationState(
                team_id="TEAM_B",
                points=3,
                goals_for=2,
                goals_against=1,
            ),
            TeamSimulationState(
                team_id="TEAM_A",
                points=3,
                goals_for=2,
                goals_against=1,
            ),
        ]

        standings = rank_team_states(
            states
        )

        self.assertEqual(
            standings[0].team_id,
            "TEAM_A",
        )


class TestPoissonSampling(unittest.TestCase):
    def test_same_seed_is_reproducible(self) -> None:
        first_generator = random.Random(
            12345
        )

        second_generator = random.Random(
            12345
        )

        first_values = [
            sample_poisson(
                lambda_value=1.5,
                random_generator=(
                    first_generator
                ),
            )
            for _ in range(100)
        ]

        second_values = [
            sample_poisson(
                lambda_value=1.5,
                random_generator=(
                    second_generator
                ),
            )
            for _ in range(100)
        ]

        self.assertEqual(
            first_values,
            second_values,
        )

    def test_poisson_never_returns_negative(self) -> None:
        generator = random.Random(
            202627
        )

        values = [
            sample_poisson(
                lambda_value=2.0,
                random_generator=generator,
            )
            for _ in range(1000)
        ]

        self.assertTrue(
            all(
                value >= 0
                for value in values
            )
        )


class TestPercentile(unittest.TestCase):
    def test_median_percentile(self) -> None:
        result = percentile(
            [1, 2, 3, 4, 5],
            50,
        )

        self.assertEqual(
            result,
            3.0,
        )

    def test_interpolated_percentile(self) -> None:
        result = percentile(
            [0, 10],
            25,
        )

        self.assertEqual(
            result,
            2.5,
        )

    def test_empty_values_are_rejected(self) -> None:
        with self.assertRaises(
            LeagueSimulationError
        ):
            percentile(
                [],
                50,
            )

    def test_invalid_percentile_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            LeagueSimulationError
        ):
            percentile(
                [1, 2, 3],
                110,
            )


class TestPlayoffPositions(unittest.TestCase):
    def test_playoff_position_above_relegation(
        self,
    ) -> None:
        self.assertTrue(
            is_playoff_position(
                position=16,
                team_count=18,
                relegation_places=2,
                playoff_places=1,
            )
        )

    def test_direct_relegation_is_not_playoff(
        self,
    ) -> None:
        self.assertFalse(
            is_playoff_position(
                position=17,
                team_count=18,
                relegation_places=2,
                playoff_places=1,
            )
        )

    def test_no_playoff_places(self) -> None:
        self.assertFalse(
            is_playoff_position(
                position=16,
                team_count=18,
                relegation_places=2,
                playoff_places=0,
            )
        )


class TestPositionRules(unittest.TestCase):
    def test_valid_rules(self) -> None:
        validate_position_rules(
            team_count=20,
            europe_places=6,
            relegation_places=3,
            playoff_places=0,
        )

    def test_too_many_europe_places(self) -> None:
        with self.assertRaises(
            LeagueSimulationError
        ):
            validate_position_rules(
                team_count=4,
                europe_places=5,
                relegation_places=1,
                playoff_places=0,
            )

    def test_relegation_and_playoff_exceed_teams(
        self,
    ) -> None:
        with self.assertRaises(
            LeagueSimulationError
        ):
            validate_position_rules(
                team_count=4,
                europe_places=2,
                relegation_places=3,
                playoff_places=2,
            )


class TestSimulationCount(unittest.TestCase):
    def test_valid_simulation_count(self) -> None:
        self.assertEqual(
            validate_simulation_count(
                10000
            ),
            10000,
        )

    def test_zero_is_rejected(self) -> None:
        with self.assertRaises(
            LeagueSimulationError
        ):
            validate_simulation_count(
                0
            )


class TestSimulationReproducibility(unittest.TestCase):
    def setUp(self) -> None:
        self.matches = [
            SimulationMatch(
                match_id="M1",
                league_id="ENG1",
                season_label="2026/27",
                home_team_id="TEAM_A",
                away_team_id="TEAM_B",
                lambda_home=2.0,
                lambda_away=0.8,
            ),
            SimulationMatch(
                match_id="M2",
                league_id="ENG1",
                season_label="2026/27",
                home_team_id="TEAM_B",
                away_team_id="TEAM_A",
                lambda_home=1.0,
                lambda_away=1.5,
            ),
        ]

    def test_same_seed_same_results(self) -> None:
        first = simulate_league(
            simulation_id="SIM_1",
            league_id="ENG1",
            season_label="2026/27",
            model_version="MODEL_TEST",
            run_id=None,
            matches=self.matches,
            simulation_count=1000,
            random_seed=123,
            europe_places=1,
            relegation_places=1,
            playoff_places=0,
        )

        second = simulate_league(
            simulation_id="SIM_2",
            league_id="ENG1",
            season_label="2026/27",
            model_version="MODEL_TEST",
            run_id=None,
            matches=self.matches,
            simulation_count=1000,
            random_seed=123,
            europe_places=1,
            relegation_places=1,
            playoff_places=0,
        )

        self.assertEqual(
            first.team_results,
            second.team_results,
        )

    def test_stronger_team_has_more_title_probability(
        self,
    ) -> None:
        result = simulate_league(
            simulation_id="SIM_3",
            league_id="ENG1",
            season_label="2026/27",
            model_version="MODEL_TEST",
            run_id=None,
            matches=self.matches,
            simulation_count=5000,
            random_seed=202627,
            europe_places=1,
            relegation_places=1,
            playoff_places=0,
        )

        results_by_team = {
            item.team_id: item
            for item in result.team_results
        }

        self.assertGreater(
            results_by_team[
                "TEAM_A"
            ].title_probability,
            results_by_team[
                "TEAM_B"
            ].title_probability,
        )

    def test_position_probabilities_sum_to_one(
        self,
    ) -> None:
        result = simulate_league(
            simulation_id="SIM_4",
            league_id="ENG1",
            season_label="2026/27",
            model_version="MODEL_TEST",
            run_id=None,
            matches=self.matches,
            simulation_count=1000,
            random_seed=321,
            europe_places=1,
            relegation_places=1,
            playoff_places=0,
        )

        for team in result.team_results:
            total = sum(
                probability
                for _, probability
                in team.position_probabilities
            )

            self.assertAlmostEqual(
                total,
                1.0,
                places=9,
            )


if __name__ == "__main__":
    unittest.main()
