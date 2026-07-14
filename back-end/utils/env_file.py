"""The ``back-end/.env`` this repository tells a developer to write, actually read.

``docs/STARTUP.md`` has always said to copy ``.env.example`` to ``.env``, and nothing in this
repository ever loaded that file: no module called ``load_dotenv``, and ``python-dotenv`` was in
neither requirements file, so Flask's CLI - which auto-loads a ``.env`` only when python-dotenv is
installed - did not either. The instruction was harmless while the app booted regardless (the signing
key had a fallback, CORS was permissive, the session backend was derived), and it stops being
harmless now that those defaults are gone: a developer who follows the guide sets
``ALLOW_INSECURE_LOCAL_DEV`` in a file the process never opens, and meets a boot refusal telling them
to set the variable they just set. So the file is loaded here, which is what makes
``back-end/.env.example`` a template that boots as it stands.

The real environment wins (``override=False``). A deployment's variables are set on the host, and a
``.env`` that found its way into an image - the Docker stack bind-mounts ``back-end/`` straight into
the container - must never be able to quietly replace them. The path is anchored to this file rather
than searched from the working directory, so ``flask run`` from ``back-end/`` and ``python app.py``
from anywhere read the same file.
"""

from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load ``path`` into the environment, leaving anything already set alone.

    A missing file is not an error: the Docker stack and every deployment pass their configuration
    in directly, and a process with a fully configured environment has nothing to read.
    """
    load_dotenv(path, override=False)
