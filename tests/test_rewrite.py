from pathlib import Path

import tomlkit

from uv_override_prune.rewrite import (
    dynamic_build_fields,
    get_uv_array,
    pin_dynamic_version,
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


def test_prepare_modified_text_removes_entry():
    original = '[tool.uv]\noverride-dependencies = ["foo>=1.0", "bar>=2.0"]\n'
    result = prepare_modified_text(
        original,
        "override-dependencies",
        "bar>=2.0",
        Path("/"),
    )
    assert '"bar>=2.0"' not in result
    assert '"foo>=1.0"' in result


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


def test_prepare_modified_text_removes_every_equivalent_copy():
    original = (
        "[tool.uv]\n"
        'override-dependencies = ["click>=8.0", "foo>=1.0", "Click >= 8.0.0"]\n'
    )
    result = prepare_modified_text(
        original,
        "override-dependencies",
        "click>=8.0",
        Path("/projects/foo"),
    )
    assert 'override-dependencies = ["foo>=1.0"]' in result


def test_prepare_modified_text_keeps_same_name_with_other_specifier():
    original = '[tool.uv]\noverride-dependencies = ["click>=8.0", "click>=8.1"]\n'
    result = prepare_modified_text(
        original,
        "override-dependencies",
        "click>=8.0",
        Path("/projects/foo"),
    )
    assert 'override-dependencies = ["click>=8.1"]' in result


def test_prepare_modified_text_leaves_unparsable_siblings_alone():
    original = '[tool.uv]\noverride-dependencies = ["click>=8.0", "not a valid req"]\n'
    result = prepare_modified_text(
        original,
        "override-dependencies",
        "click>=8.0",
        Path("/projects/foo"),
    )
    assert 'override-dependencies = ["not a valid req"]' in result


def test_pin_dynamic_version_replaces_dynamic_version_with_placeholder():
    doc = tomlkit.parse('[project]\nname = "foo"\ndynamic = ["version"]\n')
    pin_dynamic_version(doc)
    assert tomlkit.dumps(doc) == '[project]\nname = "foo"\nversion = "0.0.0"\n'


def test_pin_dynamic_version_keeps_other_dynamic_fields():
    doc = tomlkit.parse(
        '[project]\nname = "foo"\ndynamic = ["version", "dependencies"]\n',
    )
    pin_dynamic_version(doc)
    assert tomlkit.dumps(doc) == (
        '[project]\nname = "foo"\ndynamic = ["dependencies"]\nversion = "0.0.0"\n'
    )


def test_pin_dynamic_version_leaves_static_version_alone():
    original = '[project]\nname = "foo"\nversion = "1.2.3"\n'
    doc = tomlkit.parse(original)
    pin_dynamic_version(doc)
    assert tomlkit.dumps(doc) == original


def test_pin_dynamic_version_leaves_dynamic_without_version_alone():
    original = '[project]\nname = "foo"\ndynamic = ["dependencies"]\n'
    doc = tomlkit.parse(original)
    pin_dynamic_version(doc)
    assert tomlkit.dumps(doc) == original


def test_pin_dynamic_version_ignores_missing_project_table():
    original = "[tool.uv]\noverride-dependencies = []\n"
    doc = tomlkit.parse(original)
    pin_dynamic_version(doc)
    assert tomlkit.dumps(doc) == original


def test_prepare_modified_text_pins_dynamic_version():
    text = (
        '[project]\nname = "foo"\ndynamic = ["version"]\n\n'
        '[tool.uv]\noverride-dependencies = ["bar>=1.0"]\n'
    )
    result = prepare_modified_text(text, "override-dependencies", "bar>=1.0", Path())
    assert 'version = "0.0.0"' in result
    assert "dynamic" not in result


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
