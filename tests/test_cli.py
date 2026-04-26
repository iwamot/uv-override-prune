from uv_override_prune.cli import _LABELS


def test_labels_cover_all_statuses():
    assert set(_LABELS) == {"prune", "keep", "skip", "error"}


def test_labels_have_uniform_width():
    widths = {len(v) for v in _LABELS.values()}
    assert widths == {len("[PRUNE]")}
