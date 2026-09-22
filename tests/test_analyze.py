from packaging.requirements import Requirement
from packaging.version import Version

from uv_override_prune.analyze import (
    classify,
    duplicate_indexes,
    find_resolved_versions,
    is_pure_lower_bound,
    is_same_requirement,
)


def test_is_pure_lower_bound_accepts_ge():
    assert is_pure_lower_bound(Requirement("foo>=1.0"))


def test_is_pure_lower_bound_accepts_gt():
    assert is_pure_lower_bound(Requirement("foo>1.0"))


def test_is_pure_lower_bound_rejects_eq():
    assert not is_pure_lower_bound(Requirement("foo==1.0"))


def test_is_pure_lower_bound_rejects_tilde_eq():
    assert not is_pure_lower_bound(Requirement("foo~=1.0"))


def test_is_pure_lower_bound_rejects_mixed_with_ne():
    assert not is_pure_lower_bound(Requirement("foo>=1.0,!=2.0"))


def test_is_pure_lower_bound_rejects_no_specifier():
    assert not is_pure_lower_bound(Requirement("foo"))


def test_classify_prune_when_resolution_missing():
    result = classify(Requirement("foo>=1.0"), [])
    assert result.status == "prune"
    assert result.value == "(unused)"


def test_classify_prune_when_satisfied():
    result = classify(Requirement("foo>=1.0"), [Version("2.0")])
    assert result.status == "prune"
    assert result.value == "2.0"


def test_classify_prune_at_exact_lower_bound():
    result = classify(Requirement("foo>=2.0"), [Version("2.0")])
    assert result.status == "prune"
    assert result.value == "2.0"


def test_classify_keep_when_below_bound():
    result = classify(Requirement("foo>=2.0"), [Version("1.0")])
    assert result.status == "keep"
    assert result.value == "1.0"


def test_classify_keep_at_exact_strict_lower_bound():
    result = classify(Requirement("foo>2.0"), [Version("2.0")])
    assert result.status == "keep"
    assert result.value == "2.0"


def test_classify_keep_lists_only_the_forks_below_bound():
    result = classify(
        Requirement("foo>=2.0"),
        [Version("2.1"), Version("1.9"), Version("1.8")],
    )
    assert result.status == "keep"
    assert result.value == "1.8, 1.9"


def test_classify_prune_lists_every_fork_when_all_satisfy():
    result = classify(Requirement("foo>=2.0"), [Version("2.1"), Version("2.0")])
    assert result.status == "prune"
    assert result.value == "2.0, 2.1"


def test_classify_collapses_repeated_versions():
    result = classify(Requirement("foo>=2.0"), [Version("2.1"), Version("2.1")])
    assert result.status == "prune"
    assert result.value == "2.1"


def test_find_resolved_versions_finds_match():
    lock_doc = {
        "package": [
            {"name": "foo", "version": "1.0.0"},
            {"name": "bar", "version": "2.0.0"},
        ],
    }
    assert find_resolved_versions(lock_doc, "foo") == [Version("1.0.0")]


def test_find_resolved_versions_returns_every_fork_in_lock_order():
    lock_doc = {
        "package": [
            {"name": "foo", "version": "2.0.0"},
            {"name": "bar", "version": "1.0.0"},
            {"name": "foo", "version": "1.5.0"},
        ],
    }
    assert find_resolved_versions(lock_doc, "foo") == [
        Version("2.0.0"),
        Version("1.5.0"),
    ]


def test_find_resolved_versions_normalises_pep503():
    lock_doc = {"package": [{"name": "flask-login", "version": "0.6.0"}]}
    assert find_resolved_versions(lock_doc, "Flask_Login") == [Version("0.6.0")]


def test_find_resolved_versions_handles_dotted_separators():
    lock_doc = {"package": [{"name": "ruamel-yaml", "version": "0.18.0"}]}
    assert find_resolved_versions(lock_doc, "ruamel.yaml") == [Version("0.18.0")]


def test_find_resolved_versions_returns_empty_when_absent():
    lock_doc = {"package": [{"name": "foo", "version": "1.0.0"}]}
    assert find_resolved_versions(lock_doc, "missing") == []


def test_find_resolved_versions_handles_empty_lock():
    assert find_resolved_versions({}, "foo") == []
    assert find_resolved_versions({"package": []}, "foo") == []


def test_find_resolved_versions_skips_non_mapping_package_entries():
    lock_doc = {
        "package": [
            "not-a-mapping",
            {"name": "foo", "version": "1.0.0"},
        ],
    }
    assert find_resolved_versions(lock_doc, "foo") == [Version("1.0.0")]


def test_find_resolved_versions_returns_empty_when_package_field_not_list():
    lock_doc = {"package": "wrong-shape"}
    assert find_resolved_versions(lock_doc, "foo") == []


def test_duplicate_indexes_empty_when_all_distinct():
    assert duplicate_indexes(["foo>=1.0", "bar>=1.0", "foo>=2.0"]) == frozenset()


def test_duplicate_indexes_flags_later_copies_only():
    entries = ["foo>=1.0", "bar>=1.0", "foo>=1.0", "foo>=1.0"]
    assert duplicate_indexes(entries) == frozenset({2, 3})


def test_duplicate_indexes_matches_equivalent_spellings():
    entries = ["click>=8.0", "Click >= 8.0.0"]
    assert duplicate_indexes(entries) == frozenset({1})


def test_duplicate_indexes_distinguishes_markers():
    entries = ["foo>=1.0", 'foo>=1.0; python_version >= "3.10"']
    assert duplicate_indexes(entries) == frozenset()


def test_duplicate_indexes_ignores_unparsable_entries():
    entries = ["not a valid req", "not a valid req", "foo>=1.0"]
    assert duplicate_indexes(entries) == frozenset()


def test_is_same_requirement_matches_equivalent_spelling():
    assert is_same_requirement("Click >= 8.0.0", Requirement("click>=8.0"))


def test_is_same_requirement_rejects_different_specifier():
    assert not is_same_requirement("click>=8.1", Requirement("click>=8.0"))


def test_is_same_requirement_rejects_unparsable_text():
    assert not is_same_requirement("not a valid req", Requirement("click>=8.0"))
