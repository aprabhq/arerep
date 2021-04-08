"""Development tasks."""

import os
import re
from pathlib import Path
from shutil import which
from typing import List, Optional, Pattern
from urllib.request import urlopen

from duty import duty

PY_SRC_PATHS = (Path(_) for _ in ("src", "tests", "duties.py", "docs/macros.py"))
PY_SRC_LIST = tuple(str(_) for _ in PY_SRC_PATHS)
PY_SRC = " ".join(PY_SRC_LIST)
TESTING = os.environ.get("TESTING", "0") in {"1", "true"}
CI = os.environ.get("CI", "0") in {"1", "true", "yes", ""}
WINDOWS = os.name == "nt"
PTY = not WINDOWS and not CI


def _latest(lines: List[str], regex: Pattern) -> Optional[str]:
    for line in lines:
        match = regex.search(line)
        if match:
            return match.groupdict()["version"]
    return None


def _unreleased(versions, last_release):
    for index, version in enumerate(versions):
        if version.tag == last_release:
            return versions[:index]
    return versions


def update_changelog(
    inplace_file: str,
    marker: str,
    version_regex: str,
    template_url: str,
    commit_style: str,
) -> None:
    """
    Update the given changelog file in place.

    Arguments:
        inplace_file: The file to update in-place.
        marker: The line after which to insert new contents.
        version_regex: A regular expression to find currently documented versions in the file.
        template_url: The URL to the Jinja template used to render contents.
        commit_style: The style of commit messages to parse.
    """
    from git_changelog.build import Changelog
    from jinja2.sandbox import SandboxedEnvironment

    env = SandboxedEnvironment(autoescape=False)
    template_text = urlopen(template_url).read().decode("utf8")  # noqa: S310
    template = env.from_string(template_text)
    changelog = Changelog(".", style=commit_style)

    if len(changelog.versions_list) == 1:
        last_version = changelog.versions_list[0]
        if last_version.planned_tag is None:
            planned_tag = "0.1.0"
            last_version.tag = planned_tag
            last_version.url += planned_tag
            last_version.compare_url = last_version.compare_url.replace("HEAD", planned_tag)

    with open(inplace_file, "r") as changelog_file:
        lines = changelog_file.read().splitlines()

    last_released = _latest(lines, re.compile(version_regex))
    if last_released:
        changelog.versions_list = _unreleased(changelog.versions_list, last_released)
    rendered = template.render(changelog=changelog, inplace=True)
    lines[lines.index(marker)] = rendered

    with open(inplace_file, "w") as changelog_file:  # noqa: WPS440
        changelog_file.write("\n".join(lines).rstrip("\n") + "\n")


@duty
def bundle(ctx):
    """
    Build a standalone executable.

    Arguments:
        ctx: The [context][duty.logic.Context] instance (passed automatically).
    """
    ctx.run(
        "pyinstaller -F -n aria2p -p __pypackages__/3.8/lib src/aria2p/__main__.py",
        title="Bundling standalone executable",
        pty=PTY,
    )


@duty
def changelog(ctx):
    """
    Update the changelog in-place with latest commits.

    Arguments:
        ctx: The context instance (passed automatically).
    """
    commit = "166758a98d5e544aaa94fda698128e00733497f4"
    template_url = f"https://raw.githubusercontent.com/pawamoy/jinja-templates/{commit}/keepachangelog.md"
    ctx.run(
        update_changelog,
        kwargs={
            "inplace_file": "CHANGELOG.md",
            "marker": "<!-- insertion marker -->",
            "version_regex": r"^## \[v?(?P<version>[^\]]+)",
            "template_url": template_url,
            "commit_style": "angular",
        },
        title="Updating changelog",
        pty=PTY,
    )


@duty(pre=["check_code_quality", "check_types", "check_docs", "check_dependencies"])
def check(ctx):
    """
    Check it all!

    Arguments:
        ctx: The context instance (passed automatically).
    """


@duty
def check_code_quality(ctx, files=PY_SRC):
    """
    Check the code quality.

    Arguments:
        ctx: The context instance (passed automatically).
        files: The files to check.
    """
    ctx.run(f"flake8 --config=config/flake8.ini {files}", title="Checking code quality", pty=PTY)


@duty
def check_dependencies(ctx):
    """
    Check for vulnerabilities in dependencies.

    Arguments:
        ctx: The context instance (passed automatically).
    """
    nofail = False
    safety = which("safety")
    if not safety:
        pipx = which("pipx")
        if pipx:
            safety = f"{pipx} run safety"
        else:
            safety = "safety"
            nofail = True
    ctx.run(
        f"pdm export -f requirements --without-hashes | {safety} check --stdin --full-report",
        title="Checking dependencies",
        pty=PTY,
        nofail=nofail,
    )


@duty
def check_docs(ctx):
    """
    Check if the documentation builds correctly.

    Arguments:
        ctx: The context instance (passed automatically).
    """
    Path("build/coverage").mkdir(parents=True, exist_ok=True)
    Path("build/coverage/index.html").touch(exist_ok=True)
    ctx.run("mkdocs build -s", title="Building documentation", pty=PTY)


@duty
def check_types(ctx):
    """
    Check that the code is correctly typed.

    Arguments:
        ctx: The context instance (passed automatically).
    """
    ctx.run(f"mypy --config-file config/mypy.ini {PY_SRC}", title="Type-checking", pty=PTY, nofail=True, quiet=True)


@duty(silent=True, post=["clean_tests"])
def clean(ctx):
    """
    Delete temporary files.

    Arguments:
        ctx: The context instance (passed automatically).
    """
    ctx.run("rm -rf .mypy_cache")
    ctx.run("rm -rf build")
    ctx.run("rm -rf dist")
    ctx.run("rm -rf pip-wheel-metadata")
    ctx.run("rm -rf site")
    ctx.run("rm -rf .coverage*")
    ctx.run("find . -type d -name __pycache__ | xargs rm -rf")
    ctx.run("find . -name '*.rej' -delete")


@duty(silent=True)
def clean_tests(ctx):
    """
    Delete temporary tests files.

    Arguments:
        ctx: The context instance (passed automatically).
    """
    ctx.run("rm -rf .ports.json")
    ctx.run("rm -rf .lockdir")
    ctx.run("rm -rf .pytest_cache")
    ctx.run("rm -rf tests/.pytest_cache")
    ctx.run("find tests -type d -name __pycache__ | xargs rm -rf")


@duty
def docs(ctx):
    """
    Build the documentation locally.

    Arguments:
        ctx: The context instance (passed automatically).
    """
    ctx.run("mkdocs build", title="Building documentation")


@duty
def docs_serve(ctx, host="127.0.0.1", port=8000):
    """
    Serve the documentation (localhost:8000).

    Arguments:
        ctx: The context instance (passed automatically).
        host: The host to serve the docs from.
        port: The port to serve the docs on.
    """
    ctx.run(f"mkdocs serve -a {host}:{port}", title="Serving documentation", capture=False)


@duty
def docs_deploy(ctx):
    """
    Deploy the documentation on GitHub pages.

    Arguments:
        ctx: The context instance (passed automatically).
    """
    ctx.run("mkdocs gh-deploy", title="Deploying documentation")


@duty
def format(ctx):  # noqa: W0622 (we don't mind shadowing the format builtin)
    """
    Run formatting tools on the code.

    Arguments:
        ctx: The context instance (passed automatically).
    """
    ctx.run(
        f"autoflake -ir --exclude tests/fixtures --remove-all-unused-imports {PY_SRC}",
        title="Removing unused imports",
        pty=PTY,
    )
    ctx.run(f"isort {PY_SRC}", title="Ordering imports", pty=PTY)
    ctx.run(f"black {PY_SRC}", title="Formatting code", pty=PTY)


@duty
def release(ctx, version):
    """
    Release a new Python package.

    Arguments:
        ctx: The context instance (passed automatically).
        version: The new version number to use.
    """
    ctx.run("git add pyproject.toml CHANGELOG.md", title="Staging files", pty=PTY)
    ctx.run(["git", "commit", "-m", f"chore: Prepare release {version}"], title="Committing changes", pty=PTY)
    ctx.run(f"git tag {version}", title="Tagging commit", pty=PTY)
    if not TESTING:
        ctx.run("git push", title="Pushing commits", pty=False)
        ctx.run("git push --tags", title="Pushing tags", pty=False)
        ctx.run("pdm build", title="Building dist/wheel", pty=PTY)
        ctx.run("twine upload --skip-existing dist/*", title="Publishing version", pty=PTY)
        docs_deploy.run()  # type: ignore


@duty(silent=True)
def coverage(ctx):
    """
    Report coverage as text and HTML.

    Arguments:
        ctx: The context instance (passed automatically).
    """
    ctx.run("coverage combine .coverage*", nofail=True)
    ctx.run("coverage report --rcfile=config/coverage.ini", capture=False)
    ctx.run("coverage html --rcfile=config/coverage.ini")


@duty(pre=[lambda ctx: clean_tests.run()])
def test(ctx, match="", markers="", cpus="auto", sugar=True, verbose=False, cov=True):
    """
    Run the test suite.

    Arguments:
        ctx: The context instance (passed automatically).
        match: A pytest expression to filter selected tests.
        markers: A pytest expression to filter selected tests based on markers.
        cpus: Number of CPUs to use, or "no", default "auto".
        sugar: Use the sugar plugin, default True.
        verbose: Be verbose, default False.
        cov: Compute coverage, default True.
    """
    if WINDOWS and CI:
        cpus = ["--dist", "no"]
        verbose = ["-vv"]
        sugar = ["-p", "no:sugar"]
        cov = ["--no-cov"]
    else:
        cpus = ["--dist", "no"] if cpus == "no" else ["-n", cpus]
        sugar = [] if sugar is True else ["-p", "no:sugar"]
        verbose = [] if verbose is False else ["-vv"]
        cov = [] if cov is True else ["--no-cov"]

    match = ["-k", match] if match else []
    markers = ["-m", markers] if markers else []
    options = [*cov, *verbose, *sugar, *cpus, *match, *markers]  # noqa: WPS221

    ctx.run(
        ["pytest", "-c", "config/pytest.ini", *options, "tests"],
        title="Running tests",
        capture=False,
        pty=PTY,
    )