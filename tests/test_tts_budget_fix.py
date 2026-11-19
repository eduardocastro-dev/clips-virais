"""Regressions for duration errors on real narrations; no network or paid inference."""
from backend.audio_timeline import fit_speech_tempo


def test_3424_second_case_does_not_trigger_redator():
    pace = fit_speech_tempo(34.24, 40)
    assert pace is not None
    assert 0.88 <= pace < 1
    assert 38.1 <= 34.24 / pace <= 40


def test_short_but_compliant_narration_unchanged():
    assert fit_speech_tempo(39.2, 40) == 1.0


def test_slightly_long_narration_speeds_up_safely():
    pace = fit_speech_tempo(41.2, 40)
    assert 1 < pace <= 1.1
    assert abs(41.2 / pace - 40) < 1e-6


def test_substantially_short_narration_needs_real_rewrite():
    assert fit_speech_tempo(29, 40) is None


def test_substantially_long_narration_needs_real_rewrite():
    assert fit_speech_tempo(45, 40) is None
