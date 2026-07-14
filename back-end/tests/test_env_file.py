"""The local-development template has to be a file the process actually reads.

``docs/STARTUP.md`` tells a developer to copy ``.env.example`` to ``.env``, and until this was wired
up nothing loaded it - so every variable in it was set in a file the back end never opened. That was
invisible while the app booted anyway; with the five boot requirements in place it means the
documented onboarding path ends in a refusal naming the variable the developer has already set.
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.env_file import ENV_FILE, load_env_file

VAR = "A_VARIABLE_FOR_THIS_TEST"


def test_the_file_the_back_end_reads_is_the_one_startup_md_names():
    """`back-end/.env` - the path `cp .env.example .env` writes, from the directory it is run in."""
    assert ENV_FILE.name == ".env"
    assert (ENV_FILE.parent / ".env.example").is_file()


def test_a_variable_in_the_file_reaches_the_process(monkeypatch, tmp_path):
    monkeypatch.delenv(VAR, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"{VAR}=from-the-file\n")

    load_env_file(env_file)

    assert os.environ[VAR] == "from-the-file"


def test_the_real_environment_wins(monkeypatch, tmp_path):
    """The Docker stack bind-mounts `back-end/` into the container, so a developer's `.env` rides
    along - and a deployment sets its variables on the host. A file that could override them would be
    a way to hand a deployment a signing key, a session backend or an escape hatch it never chose."""
    monkeypatch.setenv(VAR, "from-the-environment")
    env_file = tmp_path / ".env"
    env_file.write_text(f"{VAR}=from-the-file\n")

    load_env_file(env_file)

    assert os.environ[VAR] == "from-the-environment"


def test_a_missing_file_is_not_an_error(tmp_path):
    """Every deployment, and the Docker stack: configuration comes in directly, and there is nothing
    to read."""
    load_env_file(tmp_path / "nothing-here")
