"""Re-onboarding must not silently reset a tuned project.

The basic-config branch of the wizard rebuilds ``OnboardingData`` from prompts.
It used to regenerate the scan-derived values unconditionally, so a returning
user who accepted the defaults lost:

* curated ``dimension_sets`` (custom names / per-dimension focus),
* project-specific ``validation.commands``,
* whitelist entries such as ``make`` that the scanner never suggests,
* ``git.target_branch`` / ``review.scope`` / ``git.push_per_round``.

These are behavioural settings (they decide what ``guard post-check`` runs and
where pushes go), not cosmetics, and pressing Enter is the documented way to
keep the current value.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iterate_cli.fingerprint import capture_fingerprints
from iterate_cli.generator import OnboardingData, write_onboarding_outputs
from iterate_cli.refresh import load_onboarding_config
from iterate_cli.scan import scan_project, suggest_dimensions
from iterate_cli.wizard import run_wizard


def _seed_tuned_project(project: Path) -> None:
    (project / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n', encoding="utf-8"
    )
    (project / "tests").mkdir()
    (project / "src").mkdir()
    scan = scan_project(project)
    data = OnboardingData(
        project_root=project,
        channel="cli",
        scan=scan,
        dimensions=suggest_dimensions(scan),
        dimension_sets={
            "api": {
                "dimensions": ["security", "correctness"],
                "focus": {"security": "authz boundaries only"},
            }
        },
        validation_commands={"python": ["pytest -q tests/unit -p no:cacheprovider"]},
        command_whitelist=["make"],
        target_branch="develop",
        review_scope="changed-only",
        push_per_round=True,
        fingerprints=capture_fingerprints(project),
    )
    write_onboarding_outputs(data, project)


def _update_basic_responses() -> iter:
    return iter([
        "y",   # update basic config
        "y",   # tech stack correct
        "",    # keep the currently configured validation commands
        "",    # dimensions: suggested defaults
        "",    # dimension sets: keep/enable all
        "",    # target branch: keep current
        "",    # review scope: keep current
        "",    # push after each round: keep current
        "",    # description: keep current
        "",    # conventions: keep current
        "n",   # advanced config: no
        "y",   # confirm summary
        "n",   # personalization: no
    ])


class TestBasicUpdatePreservesTunedValues:
    def test_dimension_sets_and_focus_survive(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        _seed_tuned_project(project)

        responses = _update_basic_responses()
        result = run_wizard(project, input_func=lambda _: next(responses))

        assert result is not None
        assert result.dimension_sets["api"]["dimensions"] == [
            "security",
            "correctness",
        ]
        assert result.dimension_sets["api"]["focus"] == {
            "security": "authz boundaries only"
        }
        # A scan suggestion the user never enabled must not be resurrected.
        assert "performance" not in result.dimension_sets

    def test_validation_commands_survive_enter(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        _seed_tuned_project(project)

        responses = _update_basic_responses()
        result = run_wizard(project, input_func=lambda _: next(responses))

        assert result is not None
        assert result.validation_commands == {
            "python": ["pytest -q tests/unit -p no:cacheprovider"]
        }

    def test_command_whitelist_is_union_not_replace(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        _seed_tuned_project(project)

        responses = _update_basic_responses()
        result = run_wizard(project, input_func=lambda _: next(responses))

        assert result is not None
        assert "make" in result.command_whitelist
        assert "pytest" in result.command_whitelist

    def test_git_settings_survive_enter(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        _seed_tuned_project(project)

        responses = _update_basic_responses()
        result = run_wizard(project, input_func=lambda _: next(responses))

        assert result is not None
        assert result.target_branch == "develop"
        assert result.review_scope == "changed-only"
        assert result.push_per_round is True

    def test_persisted_config_keeps_the_values(self, tmp_path: Path) -> None:
        """End-to-end: wizard result written by onboard keeps the tuning."""
        project = tmp_path / "proj"
        project.mkdir()
        _seed_tuned_project(project)

        responses = _update_basic_responses()
        result = run_wizard(project, input_func=lambda _: next(responses))
        assert result is not None
        write_onboarding_outputs(result, project)

        config = load_onboarding_config(project)
        assert config is not None
        assert config["git"]["target_branch"] == "develop"
        assert config["git"]["push_per_round"] is True
        assert config["review"]["scope"] == "changed-only"
        assert config["validation"]["commands"] == {
            "python": ["pytest -q tests/unit -p no:cacheprovider"]
        }
        assert "make" in config["validation"]["command_whitelist"]
        assert config["dimension_sets"]["api"]["focus"]["security"] == (
            "authz boundaries only"
        )
