import tomlkit
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


@settings(max_examples=200, derandomize=True, database=None, deadline=None)
@example(
    spellings=("foo", "Foo", "FOO"),
    rows=[(True, (2, 0), 0), (False, (3, 0), 0), (True, (1, 5), 1), (True, (1, 5), 2)],
)
@example(
    spellings=("flask-login", "Flask_Login", "flask.login"), rows=[(True, (0, 6), 0)]
)
@example(
    spellings=("ruamel-yaml", "ruamel.yaml", "RUAMEL_YAML"), rows=[(True, (0, 18), 0)]
)
@given(
    spellings=st.sampled_from(
        [
            ("foo", "Foo", "FOO"),
            ("flask-login", "Flask_Login", "flask.login"),
            ("ruamel-yaml", "ruamel.yaml", "RUAMEL_YAML"),
        ]
    ),
    rows=st.lists(st.tuples(st.booleans(), RELEASES, st.integers(0, 2)), max_size=30),
)
def test_lock_lookup_returns_matching_forks_in_their_original_order(spellings, rows):
    # Matching rows are identified before names are spelled, so the oracle
    # does not share the lookup's package-name normalization.
    packages = [
        {
            "name": spellings[spelling] if matches else "other-" + spellings[0],
            "version": f"{major}.{minor}",
        }
        for matches, (major, minor), spelling in rows
    ]
    expected = [
        Version(f"{major}.{minor}") for matches, (major, minor), _ in rows if matches
    ]
    plain = {"package": packages}
    parsed = tomlkit.parse(tomlkit.dumps(plain))
    for document in (plain, parsed):
        for name in spellings:
            assert find_resolved_versions(document, name) == expected
        assert find_resolved_versions(document, "missing-" + spellings[0]) == []


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
