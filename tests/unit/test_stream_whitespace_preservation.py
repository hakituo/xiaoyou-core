from core.utils.text_processor import enforce_dialogue_style


def test_preserve_edge_whitespace_keeps_trailing_space_for_stream_join():
    left = enforce_dialogue_style(
        "Hello ",
        max_chars=None,
        at_start=True,
        skip_breathing=True,
        preserve_edge_whitespace=True,
    )
    right = enforce_dialogue_style(
        "world",
        max_chars=None,
        at_start=False,
        skip_breathing=True,
        preserve_edge_whitespace=True,
    )
    assert left + right == "Hello world"


def test_preserve_edge_whitespace_keeps_leading_space_for_mid_segment():
    mid = enforce_dialogue_style(
        " world",
        max_chars=None,
        at_start=False,
        skip_breathing=True,
        preserve_edge_whitespace=True,
    )
    assert mid.startswith(" ")

