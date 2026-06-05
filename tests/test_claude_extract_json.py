"""Tests für extract_json_block in src/analysis/claude.py."""

from src.analysis.claude import extract_json_block


def test_single_json_block():
    text = "Hier die Analyse:\n```json\n{\"a\": 1}\n```\nFertig."
    assert extract_json_block(text) == {"a": 1}


def test_multiple_blocks_takes_last():
    """Bei mehreren ```json-Bloecken wird der LETZTE genommen (matches[-1])."""
    text = (
        "Erst:\n```json\n{\"v\": 1}\n```\n"
        "Dann final:\n```json\n{\"v\": 2}\n```\n"
    )
    assert extract_json_block(text) == {"v": 2}


def test_broken_json_returns_none():
    text = "```json\n{\"a\": 1,, broken}\n```"
    assert extract_json_block(text) is None


def test_no_block_returns_none():
    assert extract_json_block("Nur Fliesstext, kein Code-Block.") is None


def test_empty_string_returns_none():
    assert extract_json_block("") is None


def test_block_with_list_payload():
    text = "```json\n[{\"ticker\": \"AAPL\"}, {\"ticker\": \"META\"}]\n```"
    assert extract_json_block(text) == [{"ticker": "AAPL"}, {"ticker": "META"}]
