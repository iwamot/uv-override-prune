from hypothesis import example, given, settings
from hypothesis import strategies as st
from packaging.requirements import Requirement
from packaging.version import Version

from uv_override_prune.analyze import (
    classify,
    duplicate_indexes,
    find_resolved_versions,
    is_pure_lower_bound,
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


RELEASES = st.tuples(st.integers(0, 50), st.integers(0, 50))


@settings(max_examples=200, derandomize=True, database=None, deadline=None)
@example(bound=(1, 0), strict=False, releases=[])
@example(bound=(2, 0), strict=False, releases=[(2, 1), (2, 0), (2, 1)])
@example(bound=(2, 0), strict=True, releases=[(2, 0)])
@example(bound=(2, 0), strict=False, releases=[(2, 1), (1, 9), (1, 8), (1, 9)])
@given(bound=RELEASES, strict=st.booleans(), releases=st.lists(RELEASES, max_size=20))
def test_classification_agrees_with_numeric_bounds(bound, strict, releases):
    # Plain major.minor releases compare as integer pairs, independently of
    # packaging's specifier implementation. Other PEP 440 forms are outside
    # this generated domain.
    major, minor = bound
    op = ">" if strict else ">="
    req = Requirement(f"foo{op}{major}.{minor}")
    resolved = [Version(f"{major}.{minor}") for major, minor in releases]
    below = [r for r in releases if r < bound or (strict and r == bound)]
    expected = ", ".join(
        f"{major}.{minor}" for major, minor in sorted(set(below or releases))
    )
    result = classify(req, resolved)
    assert result.status == ("keep" if below else "prune")
    assert result.value == (expected if releases else "(unused)")
    assert classify(req, resolved[::-1]) == result
    assert classify(req, resolved + resolved) == result


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


@settings(max_examples=200, derandomize=True, database=None, deadline=None)
@example(name="foo", version=1, entries=[])
@example(
    name="foo",
    version=1,
    entries=[
        ("base", "foo>=1.0"),
        ("other", "bar>=1.0"),
        ("base", "foo>=1.0"),
        ("base", "foo>=1.0"),
    ],
)
@example(
    name="click",
    version=8,
    entries=[("base", "click>=8.0"), ("base", "Click >= 8.0.0")],
)
@given(
    name=st.sampled_from(["foo", "click", "some-package"]),
    version=st.integers(0, 20),
    entries=st.lists(
        st.sampled_from(
            [
                ("base", "{name}>={version}.0"),
                ("base", "{alias} >= {version}.0.0"),
                ("higher", "{name}>={version}.1"),
                ("strict", "{name}>{version}.0"),
                ("other", "other-{name}>={version}.0"),
                ("marked", '{name}>={version}.0; python_version >= "3.10"'),
                ("marked", "{alias} >= {version}.0.0; python_version >= '3.10'"),
                ("extras", "{name}[a,b]>={version}.0"),
                ("extras", "{alias}[b,a]>={version}.0.0"),
                (None, "not a valid req"),
            ]
        ),
        max_size=30,
    ),
)
def test_duplicate_removal_keeps_the_first_of_each_requirement(name, version, entries):
    # Identities describe equivalent input spellings. The oracle uses their
    # first positions without parsing requirements or reproducing a seen set.
    identities = [identity for identity, _ in entries]
    expected = frozenset(
        i
        for i, identity in enumerate(identities)
        if identity is not None and i != identities.index(identity)
    )
    original = [
        text.format(name=name, alias=name.upper().replace("-", "_"), version=version)
        for _, text in entries
    ]
    values = original.copy()
    duplicates = duplicate_indexes(values)
    assert duplicates == expected
    assert values == original
    survivors = [value for i, value in enumerate(values) if i not in duplicates]
    assert duplicate_indexes(survivors) == frozenset()
