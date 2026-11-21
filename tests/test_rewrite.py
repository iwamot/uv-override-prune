from collections.abc import Mapping
from pathlib import Path

import tomlkit
from hypothesis import example, given, settings
from hypothesis import strategies as st
from packaging.version import Version

from uv_override_prune.rewrite import (
    dynamic_build_fields,
    prepare_modified_text,
    rewrite_paths,
)


@settings(max_examples=200, derandomize=True, database=None, deadline=None)
@example(
    source_mode="paths",
    workspace_mode="members",
    directory="demo",
    name="local-pkg",
    sources=[0, 1, 2, 3, 4],
    members=[4, 3, 2, 1, 0, 0],
    readme=0,
    description="",
)
@given(
    source_mode=st.sampled_from(["absent", "empty", "git", "paths"]),
    workspace_mode=st.sampled_from(["absent", "exclude", "members"]),
    directory=st.text(alphabet="abcXYZ012-_", min_size=1, max_size=12),
    name=st.text(alphabet="abcXYZ012-_ 日本語", min_size=1, max_size=12),
    sources=st.lists(st.integers(0, 4), max_size=8),
    members=st.lists(st.integers(0, 4), max_size=8),
    readme=st.integers(0, 4),
    description=st.text(max_size=20),
)
def test_lock_input_preserves_path_targets_and_other_metadata(
    source_mode, workspace_mode, directory, name, sources, members, readme, description
):
    base = Path("/projects") / directory / "project"
    # Each spelling has a known target independent of the path rewriter.
    spellings = [
        (name, str(base / name)),
        (f"./{name}", str(base / name)),
        (f"nested/../{name}", str(base / name)),
        (f"../{name}", str(base.parent / name)),
        (f"/absolute/../{name}", f"/absolute/../{name}"),
    ]

    def document(source_paths, member_paths, readme_path, readme_form, entries):
        project: dict[str, object] = {"name": "demo", "description": description}
        if readme_form != "absent":
            project["readme"] = {
                "string": readme_path,
                "file": {"file": readme_path, "content-type": "text/markdown"},
                "inline": {"text": description, "content-type": "text/markdown"},
            }[readme_form]
        uv: dict[str, object] = {"override-dependencies": entries}
        if source_mode != "absent":
            source_table: dict[str, object] = {}
            if source_mode in ("git", "paths"):
                source_table["remote"] = {
                    "git": "https://example.com/repo.git",
                    "branch": "main",
                }
            if source_mode == "paths":
                source_table.update(
                    {
                        f"pkg{i}": {"path": path, "editable": True}
                        for i, path in enumerate(source_paths)
                    }
                )
            uv["sources"] = source_table
        if workspace_mode != "absent":
            workspace: dict[str, object] = {"exclude": ["excluded/*"]}
            if workspace_mode == "members":
                workspace["members"] = member_paths
            uv["workspace"] = workspace
        return {"project": project, "tool": {"uv": uv, "other": {"note": description}}}

    for readme_form in ("absent", "inline", "string", "file"):
        original = tomlkit.dumps(
            document(
                [spellings[i][0] for i in sources],
                [spellings[i][0] for i in members],
                spellings[readme][0],
                readme_form,
                ["foo>=1.0"],
            )
        )
        expected = document(
            [spellings[i][1] for i in sources],
            [spellings[i][1] for i in members],
            spellings[readme][1],
            readme_form,
            [],
        )
        result = prepare_modified_text(
            original, "override-dependencies", "foo>=1.0", base
        )
        assert tomlkit.parse(result) == expected
        assert (
            prepare_modified_text(result, "override-dependencies", "foo>=1.0", base)
            == result
        )


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
