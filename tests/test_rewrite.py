from collections.abc import Mapping
from pathlib import Path

import tomlkit
from hypothesis import example, given, settings
from hypothesis import strategies as st
from packaging.version import Version

from uv_override_prune.rewrite import (
    dynamic_build_fields,
    get_uv_array,
    prepare_modified_text,
    remove_entries,
    rewrite_paths,
)


def test_get_uv_array_returns_entries():
    doc = tomlkit.parse(
        '[tool.uv]\noverride-dependencies = ["foo>=1.0", "bar>=2.0"]\n',
    )
    arr = get_uv_array(doc, "override-dependencies")
    assert [str(x) for x in arr] == ["foo>=1.0", "bar>=2.0"]


def test_rewrite_paths_makes_sources_path_absolute():
    doc = tomlkit.parse(
        '[tool.uv.sources]\nmypkg = { path = "./local-pkg" }\n',
    )
    rewrite_paths(doc, Path("/projects/foo"))
    assert '"/projects/foo/local-pkg"' in tomlkit.dumps(doc)


def test_rewrite_paths_leaves_absolute_sources_path_alone():
    original = '[tool.uv.sources]\nmypkg = { path = "/abs/path" }\n'
    doc = tomlkit.parse(original)
    rewrite_paths(doc, Path("/projects/foo"))
    assert tomlkit.dumps(doc) == original


def test_rewrite_paths_makes_workspace_members_absolute():
    doc = tomlkit.parse(
        '[tool.uv.workspace]\nmembers = ["./pkg-a", "/abs/pkg-b"]\n',
    )
    rewrite_paths(doc, Path("/projects/foo"))
    output = tomlkit.dumps(doc)
    assert '"/projects/foo/pkg-a"' in output
    assert '"/abs/pkg-b"' in output


def test_rewrite_paths_makes_readme_string_absolute():
    doc = tomlkit.parse('[project]\nreadme = "README.md"\n')
    rewrite_paths(doc, Path("/projects/foo"))
    assert 'readme = "/projects/foo/README.md"' in tomlkit.dumps(doc)


def test_rewrite_paths_handles_readme_table_with_file():
    doc = tomlkit.parse(
        '[project.readme]\nfile = "docs/README.md"\ncontent-type = "text/markdown"\n',
    )
    rewrite_paths(doc, Path("/projects/foo"))
    assert 'file = "/projects/foo/docs/README.md"' in tomlkit.dumps(doc)


def test_rewrite_paths_no_change_when_no_paths():
    original = '[project]\nname = "test"\n'
    doc = tomlkit.parse(original)
    rewrite_paths(doc, Path("/projects/foo"))
    assert tomlkit.dumps(doc) == original


def test_rewrite_paths_empty_sources_table():
    original = "[tool.uv.sources]\n"
    doc = tomlkit.parse(original)
    rewrite_paths(doc, Path("/projects/foo"))
    assert tomlkit.dumps(doc) == original


def test_rewrite_paths_workspace_without_members_key():
    original = "[tool.uv.workspace]\nexclude = []\n"
    doc = tomlkit.parse(original)
    rewrite_paths(doc, Path("/projects/foo"))
    assert tomlkit.dumps(doc) == original


def test_rewrite_paths_readme_table_without_file_key():
    original = (
        '[project.readme]\ntext = "inline content"\ncontent-type = "text/markdown"\n'
    )
    doc = tomlkit.parse(original)
    rewrite_paths(doc, Path("/projects/foo"))
    assert tomlkit.dumps(doc) == original


def test_rewrite_paths_sources_without_path_key_left_alone():
    original = (
        "[tool.uv.sources]\n"
        'mypkg = { git = "https://example.com/repo.git", branch = "main" }\n'
    )
    doc = tomlkit.parse(original)
    rewrite_paths(doc, Path("/projects/foo"))
    assert tomlkit.dumps(doc) == original


def test_rewrite_paths_leaves_absolute_readme_string_alone():
    original = '[project]\nreadme = "/abs/README.md"\n'
    doc = tomlkit.parse(original)
    rewrite_paths(doc, Path("/projects/foo"))
    assert tomlkit.dumps(doc) == original


def test_rewrite_paths_leaves_absolute_readme_file_alone():
    original = (
        "[project.readme]\n"
        'file = "/abs/docs/README.md"\n'
        'content-type = "text/markdown"\n'
    )
    doc = tomlkit.parse(original)
    rewrite_paths(doc, Path("/projects/foo"))
    assert tomlkit.dumps(doc) == original


def test_rewrite_paths_handles_non_table_tool_uv():
    original = '[tool]\nuv = "not a table"\n'
    doc = tomlkit.parse(original)
    rewrite_paths(doc, Path("/projects/foo"))
    assert tomlkit.dumps(doc) == original


def test_rewrite_paths_handles_non_string_source_path():
    original = "[tool.uv.sources.mypkg]\npath = 42\n"
    doc = tomlkit.parse(original)
    rewrite_paths(doc, Path("/projects/foo"))
    assert tomlkit.dumps(doc) == original


def test_remove_entries_drops_one_from_array():
    doc = tomlkit.parse(
        '[tool.uv]\noverride-dependencies = ["foo>=1.0", "bar>=2.0", "baz>=3.0"]\n',
    )
    remove_entries(doc, {"override-dependencies": ["bar>=2.0"]})
    arr = [str(x) for x in get_uv_array(doc, "override-dependencies")]
    assert arr == ["foo>=1.0", "baz>=3.0"]


def test_remove_entries_handles_multiple_sections():
    doc = tomlkit.parse(
        "[tool.uv]\n"
        'override-dependencies = ["foo>=1.0", "bar>=2.0"]\n'
        'constraint-dependencies = ["x>=1.0", "y>=2.0"]\n',
    )
    remove_entries(
        doc,
        {
            "override-dependencies": ["bar>=2.0"],
            "constraint-dependencies": ["x>=1.0"],
        },
    )
    overrides = [str(x) for x in get_uv_array(doc, "override-dependencies")]
    constraints = [str(x) for x in get_uv_array(doc, "constraint-dependencies")]
    assert overrides == ["foo>=1.0"]
    assert constraints == ["y>=2.0"]


def test_remove_entries_preserves_surrounding_comments():
    original = (
        "[tool.uv]\n"
        "# Security overrides\n"
        "override-dependencies = [\n"
        '    "foo>=1.0",  # CVE-1\n'
        '    "bar>=2.0",  # to be removed\n'
        '    "baz>=3.0",  # CVE-3\n'
        "]\n"
    )
    doc = tomlkit.parse(original)
    remove_entries(doc, {"override-dependencies": ["bar>=2.0"]})
    output = tomlkit.dumps(doc)
    assert "# Security overrides" in output
    assert "# CVE-1" in output
    assert "# CVE-3" in output
    assert "bar>=2.0" not in output


@settings(max_examples=200, derandomize=True, database=None, deadline=None)
@example(
    section="override-dependencies",
    name="click",
    version=8,
    entries=[(True, "click>=8.0"), (False, "foo>=1.0"), (True, "Click >= 8.0.0")],
    description="",
)
@example(
    section="override-dependencies",
    name="bar",
    version=2,
    entries=[(False, "foo>=1.0"), (True, "bar>=2.0"), (False, "baz>=3.0")],
    description="",
)
@given(
    section=st.sampled_from(["override-dependencies", "constraint-dependencies"]),
    name=st.sampled_from(["click", "bar", "some-package"]),
    version=st.integers(1, 20),
    entries=st.lists(
        st.sampled_from(
            [
                (True, "{name}>={version}.0"),
                (True, "{alias} >= {version}.0.0"),
                (False, "foo>=1.0"),
                (False, "{name}>={version}.1"),
                (False, "{name}>{version}.0"),
                (False, "{name}[feature]>={version}.0"),
                (False, '{name}>={version}.0; python_version >= "3.10"'),
                (False, "not a valid req"),
            ]
        ),
        max_size=20,
    ),
    description=st.text(max_size=30),
)
def test_preparing_lock_input_removes_only_equivalent_requirements(
    section, name, version, entries, description
):
    target = f"{name}>={version}.0"
    entries = [
        (
            removed,
            text.format(
                name=name, alias=name.upper().replace("-", "_"), version=version
            ),
        )
        for removed, text in entries
    ]
    other = (
        "constraint-dependencies"
        if section == "override-dependencies"
        else "override-dependencies"
    )
    project = {"name": "demo", "version": "1.2.3", "description": description}
    retained = {
        section: [text for removed, text in entries if not removed],
        other: [target],
    }
    expected = {"project": project, "tool": {"uv": retained}}
    before = {
        "project": project,
        "tool": {"uv": {**retained, section: [text for _, text in entries]}},
    }
    result = prepare_modified_text(tomlkit.dumps(before), section, target, Path("/"))
    assert tomlkit.parse(result) == expected
    assert prepare_modified_text(result, section, target, Path("/")) == result


def test_prepare_modified_text_rewrites_readme_path():
    original = (
        '[project]\nreadme = "README.md"\n'
        '[tool.uv]\noverride-dependencies = ["foo>=1.0"]\n'
    )
    result = prepare_modified_text(
        original,
        "override-dependencies",
        "foo>=1.0",
        Path("/projects/foo"),
    )
    assert 'readme = "/projects/foo/README.md"' in result


@settings(max_examples=200, derandomize=True, database=None, deadline=None)
@example(mode="dynamic_version", fields=[], position=0, static_version="1.2.3", note="")
@example(
    mode="dynamic_version",
    fields=["dependencies"],
    position=0,
    static_version="1.2.3",
    note="",
)
@example(
    mode="dynamic_version",
    fields=["classifiers", "requires-python"],
    position=1,
    static_version="1.2.3",
    note="",
)
@given(
    mode=st.sampled_from(["absent", "static", "other_dynamic", "dynamic_version"]),
    fields=st.lists(
        st.sampled_from(
            [
                "dependencies",
                "optional-dependencies",
                "requires-python",
                "classifiers",
                "readme",
                "license",
            ]
        ),
        unique=True,
    ),
    position=st.integers(0, 6),
    static_version=st.sampled_from(["1.2.3", "2.0rc1", "0.1.dev1"]),
    note=st.text(max_size=20),
)
def test_lock_input_has_static_version_without_changing_other_metadata(
    mode, fields, position, static_version, note
):
    original: dict[str, object] = {
        "tool": {
            "uv": {"override-dependencies": ["remove>=1.0"]},
            "other": {"note": note},
        }
    }
    expected: dict[str, object] = {
        "tool": {"uv": {"override-dependencies": []}, "other": {"note": note}}
    }
    project: dict[str, object] = {"name": "demo"}
    expected_project = project.copy()
    if mode == "static":
        project["version"] = expected_project["version"] = static_version
    elif mode == "other_dynamic":
        project["dynamic"] = expected_project["dynamic"] = fields
    elif mode == "dynamic_version":
        dynamic = fields.copy()
        dynamic.insert(position % (len(fields) + 1), "version")
        project["dynamic"] = dynamic
        if fields:
            expected_project["dynamic"] = fields
    if mode != "absent":
        original["project"] = project
        expected["project"] = expected_project

    result = prepare_modified_text(
        tomlkit.dumps(original), "override-dependencies", "remove>=1.0", Path("/")
    )
    parsed = tomlkit.parse(result)
    if mode == "dynamic_version":
        metadata = parsed.get("project")
        assert isinstance(metadata, Mapping)
        version = metadata.get("version")
        assert isinstance(version, str)
        Version(version)
        expected_project["version"] = version
    assert parsed == expected
    assert (
        prepare_modified_text(result, "override-dependencies", "remove>=1.0", Path("/"))
        == result
    )


def test_dynamic_build_fields_lists_resolution_fields_only():
    doc = tomlkit.parse(
        '[project]\nname = "foo"\n'
        'dynamic = ["classifiers", "optional-dependencies", "version", "dependencies"]\n',
    )
    assert dynamic_build_fields(doc) == ["dependencies", "optional-dependencies"]


def test_dynamic_build_fields_empty_for_version_only():
    doc = tomlkit.parse('[project]\nname = "foo"\ndynamic = ["version"]\n')
    assert dynamic_build_fields(doc) == []


def test_dynamic_build_fields_empty_without_dynamic():
    assert dynamic_build_fields(tomlkit.parse('[project]\nname = "foo"\n')) == []
    assert dynamic_build_fields(tomlkit.parse("[tool.uv]\n")) == []
