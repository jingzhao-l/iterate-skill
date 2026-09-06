"""Unit tests for scripts/update_downloads_badge.py.

Covers normal path (all sources resolve), fallback to previous values, missing
data raising, boundary inputs, atomic file writing and the end-to-end main()
run with mocked upstream fetches.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

import update_downloads_badge as udb


def _clawhub_payload(downloads: int) -> dict:
    return {
        "skill": {"slug": "iterate-skill", "stats": {"downloads": downloads, "stars": 0}},
        "owner": {"handle": "jingzhao-l"},
    }


def _skillhub_payload(downloads: int) -> dict:
    return {
        "skill": {
            "slug": "iterate-skill",
            "stats": {"downloads": downloads, "installs": 0, "versions": 25},
        },
        "slug": "iterate-skill",
    }


def _npm_payload(downloads: int) -> dict:
    return {
        "start": "2000-01-01",
        "end": "2100-01-01",
        "package": "iterate-skill-installer",
        "downloads": downloads,
    }


class TestExtractCount:
    def test_extracts_clawhub_count(self) -> None:
        assert udb.extract_count("clawhub", _clawhub_payload(845)) == 845

    def test_extracts_skillhub_count(self) -> None:
        assert udb.extract_count("skillhub", _skillhub_payload(254)) == 254

    def test_extracts_npm_count(self) -> None:
        assert udb.extract_count("npm", _npm_payload(1464)) == 1464

    @pytest.mark.parametrize("payload", [None, [], "text", 42])
    def test_rejects_non_dict_payload(self, payload: object) -> None:
        assert udb.extract_count("npm", payload) is None

    def test_missing_path_returns_none(self) -> None:
        assert udb.extract_count("npm", {"downloads": None}) is None
        assert udb.extract_count("clawhub", {"skill": {}}) is None

    def test_rejects_bool_as_int(self) -> None:
        assert udb.extract_count("npm", _npm_payload(0)) == 0
        # bool is a subclass of int in Python and must not be treated as a count
        assert udb.extract_count("npm", {"downloads": True}) is None

    def test_rejects_negative_count(self) -> None:
        assert udb.extract_count("clawhub", _clawhub_payload(-5)) is None


class TestResolveCounts:
    def test_resolves_all_fresh_sources(self) -> None:
        fetched = {
            "clawhub": _clawhub_payload(845),
            "skillhub": _skillhub_payload(254),
            "npm": _npm_payload(1464),
        }
        resolved, warnings = udb.resolve_counts(fetched, None)
        assert resolved == {"clawhub": 845, "skillhub": 254, "npm": 1464}
        assert warnings == []

    def test_falls_back_to_previous_on_invalid_source(self) -> None:
        fetched = {
            "clawhub": _clawhub_payload(845),
            "skillhub": _skillhub_payload(254),
            "npm": _npm_payload(-1),  # invalid fresh value
        }
        previous = {"clawhub": 800, "skillhub": 200, "npm": 1000}
        resolved, warnings = udb.resolve_counts(fetched, previous)
        assert resolved["npm"] == 1000
        assert any("npm" in warning and "reused previous" in warning for warning in warnings)

    def test_raises_when_source_has_no_previous(self) -> None:
        fetched = {
            "clawhub": _clawhub_payload(845),
            "skillhub": _skillhub_payload(254),
            "npm": None,  # upstream down, no fallback data
        }
        with pytest.raises(ValueError, match="npm"):
            udb.resolve_counts(fetched, None)

    def test_raises_when_previous_value_is_bool(self) -> None:
        fetched = {"clawhub": _clawhub_payload(1), "skillhub": None, "npm": None}
        previous = {"clawhub": 1, "skillhub": True, "npm": 0}  # bool must be ignored
        with pytest.raises(ValueError):
            udb.resolve_counts(fetched, previous)

    def test_zero_counts_are_valid(self) -> None:
        fetched = {
            "clawhub": _clawhub_payload(0),
            "skillhub": _skillhub_payload(0),
            "npm": _npm_payload(0),
        }
        resolved, warnings = udb.resolve_counts(fetched, None)
        assert resolved == {"clawhub": 0, "skillhub": 0, "npm": 0}
        assert warnings == []


class TestBuildOutput:
    def test_sums_and_timestamps(self) -> None:
        output = udb.build_output({"clawhub": 845, "skillhub": 254, "npm": 1464}, [])
        assert output["total"] == 2563
        assert output["updatedAt"]
        assert "warnings" not in output

    def test_includes_warnings_when_present(self) -> None:
        output = udb.build_output(
            {"clawhub": 845, "skillhub": 254, "npm": 1464},
            ["npm: upstream down, reused previous value 1464"],
        )
        assert output["warnings"] == ["npm: upstream down, reused previous value 1464"]


class TestReadPrevious:
    def test_reads_valid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "downloads.json"
        path.write_text(json.dumps({"clawhub": 1, "total": 2}), encoding="utf-8")
        assert udb.read_previous(str(path)) == {"clawhub": 1, "total": 2}

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert udb.read_previous(str(tmp_path / "nope.json")) == {}

    def test_corrupt_file_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "downloads.json"
        path.write_text("{not json", encoding="utf-8")
        assert udb.read_previous(str(path)) == {}

    def test_non_dict_json_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "downloads.json"
        path.write_text("[1, 2]", encoding="utf-8")
        assert udb.read_previous(str(path)) == {}


class TestWriteOutput:
    def test_writes_round_trippable_json(self, tmp_path: Path) -> None:
        path = tmp_path / "downloads.json"
        udb.write_output(str(path), {"total": 2563, "clawhub": 845})
        with open(path, encoding="utf-8") as handle:
            assert json.load(handle) == {"total": 2563, "clawhub": 845}


class TestReadBounded:
    """Response bodies must be capped so an oversized JSON cannot exhaust memory."""

    class _FakeResp:
        def __init__(self, body: bytes) -> None:
            self._body = body
            self._pos = 0

        def read(self, amt: int) -> bytes:
            # Mimic urllib: read() advances a position and returns b"" at EOF
            # (a position-less stub would make a bounded read-loop spin until
            # the byte cap fires, so the fake must honor amt + EOF).
            if amt is None or amt < 0:
                chunk = self._body[self._pos :]
            else:
                chunk = self._body[self._pos : self._pos + amt]
            self._pos += len(chunk)
            return chunk

    def test_within_cap_returns_full_body(self) -> None:
        body = b"x" * (udb._MAX_RESPONSE_BYTES // 2)
        assert udb._read_bounded(self._FakeResp(body)) == body

    def test_exactly_at_cap_accepted(self) -> None:
        body = b"y" * udb._MAX_RESPONSE_BYTES
        assert udb._read_bounded(self._FakeResp(body)) == body

    def test_over_cap_raises(self) -> None:
        body = b"z" * (udb._MAX_RESPONSE_BYTES + 1)
        with pytest.raises(ValueError, match="safety cap"):
            udb._read_bounded(self._FakeResp(body))


class TestIsSkillhubUrl:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://api.skillhub.tencent.com/api/v1/foo", True),
            ("https://skillhub.cloud.tencent.com/x", True),
            ("https://sub.skillhub.cloud.tencent.com/x", True),
            ("https://evil-skillhub.cloud.tencent.com.evil.com/x", False),
            ("https://evilskillhub.tencent.com.evil.com/x", False),
            ("https://skillhub.tencent.com/x", True),
            ("not a url", False),
        ],
    )
    def test_is_skillhub_url(self, url: str, expected: bool) -> None:
        assert udb._is_skillhub_url(url) is expected

    def test_referer_only_added_for_skillhub(self, monkeypatch) -> None:
        captured: dict[str, object] = {}

        class FakeResp:
            _sent = False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, amt: int = -1) -> bytes:
                # Deliver the body once, then EOF (faithful to
                # http.client read semantics the bounded reader relies on).
                if self._sent:
                    return b""
                self._sent = True
                return b"{}"

        def fake_urlopen(request, timeout, context):
            captured["host"] = request.host
            captured["referer"] = request.get_header("Referer")
            return FakeResp()

        monkeypatch.setattr(udb.urllib.request, "urlopen", fake_urlopen)
        udb.fetch_json("https://skillhub.cloud.tencent.com/api")
        assert captured["referer"] == "https://skillhub.cloud.tencent.com/"

        captured.clear()
        udb.fetch_json("https://api.npmjs.org/downloads")
        assert captured["referer"] is None


class TestMain:
    @staticmethod
    def _fake_fetch(url: str) -> object:
        if "clawhub.ai" in url:
            return _clawhub_payload(845)
        if "skillhub" in url:
            return _skillhub_payload(254)
        if "npmjs" in url:
            return _npm_payload(1464)
        raise AssertionError(f"unexpected url: {url}")

    def test_main_writes_expected_sum(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(udb, "BADGES_FILE", str(tmp_path / "downloads.json"))
        monkeypatch.setattr(udb, "fetch_json", self._fake_fetch)
        assert udb.main() == 0
        with open(tmp_path / "downloads.json", encoding="utf-8") as handle:
            data = json.load(handle)
        assert data["total"] == 2563
        assert data["clawhub"] == 845
        assert data["skillhub"] == 254
        assert data["npm"] == 1464
        assert "updatedAt" in data

    def test_main_falls_back_to_previous_on_fetch_failure(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        target = tmp_path / "downloads.json"
        target.write_text(
            json.dumps({"clawhub": 845, "skillhub": 254, "npm": 1464, "total": 2563}),
            encoding="utf-8",
        )
        monkeypatch.setattr(udb, "BADGES_FILE", str(target))

        def failing_fetch(url: str) -> object:
            if "npmjs" in url:
                raise OSError("network down")
            if "clawhub.ai" in url:
                return _clawhub_payload(900)
            if "skillhub" in url:
                return _skillhub_payload(300)
            raise AssertionError(f"unexpected url: {url}")

        monkeypatch.setattr(udb, "fetch_json", failing_fetch)
        assert udb.main() == 0
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
        assert data["clawhub"] == 900
        assert data["skillhub"] == 300
        assert data["npm"] == 1464  # reused from previous
        assert data["total"] == 2664
        assert "warnings" in data

    def test_main_keeps_file_when_counts_unresolvable(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        target = tmp_path / "downloads.json"
        target.write_text(
            json.dumps({"clawhub": 845, "skillhub": 254, "npm": 1464, "total": 2563}),
            encoding="utf-8",
        )
        monkeypatch.setattr(udb, "BADGES_FILE", str(target))

        def all_down(url: str) -> object:
            raise OSError(f"network down: {url}")

        monkeypatch.setattr(udb, "fetch_json", all_down)
        # No previous value is available for reuse, so the sum cannot be resolved.
        monkeypatch.setattr(udb, "read_previous", lambda _path: {})
        assert udb.main() == 1
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
        assert data["total"] == 2563  # previous file untouched
