"""zrb-nudge: scheduled reminders for zrb, from a file the agent writes too.

zrb-nudge init-path            the file to add to ZRB_INIT_SCRIPTS
zrb-nudge install [profile]    append that export line to your shell profile, and say what it wrote
zrb-nudge uninstall [profile]  take the line out again
zrb-nudge show                 the schedule file, the schedules in it, and what has been said
"""

import os
import sys
from pathlib import Path

from zrb_nudge import schedule

INIT_SCRIPT = Path(__file__).with_name("zrb_init.py").resolve()
MARKER = "# zrb-nudge: the nudge trigger and its tools, in every zrb chat"


def export_line() -> str:
    """The shell line that loads this package into zrb."""
    return f'export ZRB_INIT_SCRIPTS="$ZRB_INIT_SCRIPTS:{INIT_SCRIPT}"'


def profile_path() -> Path:
    """The file `install` writes to: <PREFIX>_NUDGE_PROFILE, else the one this shell reads."""
    override = schedule.setting("PROFILE", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    shell = os.path.basename(os.environ.get("SHELL", ""))
    if "zsh" in shell:
        return Path.home() / ".zshrc"
    if "bash" in shell:
        return Path.home() / ".bashrc"
    return Path.home() / ".profile"


def _loads_it(text: str) -> bool:
    """Whether some line that is not a comment already names this package's init script."""
    return any(
        str(INIT_SCRIPT) in line and not line.lstrip().startswith("#")
        for line in text.splitlines()
    )


def install(profile: Path) -> None:
    """Append the export line to the profile, once: a second run says so and writes nothing."""
    if os.name == "nt":
        sys.exit(
            "this writes a POSIX shell line; on Windows set ZRB_INIT_SCRIPTS to "
            f"{INIT_SCRIPT} by hand"
        )
    text = profile.read_text(encoding="utf-8") if profile.exists() else ""
    if _loads_it(text):
        print(f"{profile} already loads this package; nothing changed.")
        return
    ending = "" if not text or text.endswith("\n") else "\n"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(f"{text}{ending}{MARKER}\n{export_line()}\n", encoding="utf-8")
    print(
        f"Wrote to {profile}:\n  {export_line()}\n"
        f"Open a new shell, or run: source {profile}"
    )
    print(f"Schedules live in {schedule.nudge_file()}; `zrb-nudge show` reads it.")


def uninstall(profile: Path) -> None:
    """Remove the marker and the line that names this package, leaving every other line."""
    if not profile.exists():
        print(f"{profile} is not there; nothing to remove.")
        return
    text = profile.read_text(encoding="utf-8")
    lines = text.splitlines()
    kept = [
        line
        for line in lines
        if line != MARKER
        and not (str(INIT_SCRIPT) in line and not line.lstrip().startswith("#"))
    ]
    if kept == lines:
        print(f"{profile} does not load this package; nothing changed.")
        return
    profile.write_text(
        "\n".join(kept) + ("\n" if text.endswith("\n") else ""), encoding="utf-8"
    )
    print(f"Removed this package's line from {profile}. Open a new shell to be rid of it.")


def show() -> None:
    """The schedule file, what is scheduled, and what has already been said."""
    path = schedule.nudge_file()
    print(path)
    try:
        document = schedule.load(path)
    except ValueError as error:
        sys.exit(str(error))
    print(schedule.describe(document))
    if document.said:
        print(
            "Said: "
            + ", ".join(f"{name} ({used})" for name, used in sorted(document.said.items()))
        )
    else:
        print("Nothing said yet.")


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else ""
    if command in ("-h", "--help", "help"):
        print(__doc__)
    elif command == "init-path" and len(args) == 1:
        print(INIT_SCRIPT)
    elif command == "install" and len(args) <= 2:
        install(Path(args[1]).expanduser() if len(args) == 2 else profile_path())
    elif command == "uninstall" and len(args) <= 2:
        uninstall(Path(args[1]).expanduser() if len(args) == 2 else profile_path())
    elif command == "show" and len(args) == 1:
        show()
    elif command in ("init-path", "install", "uninstall", "show"):
        sys.exit(__doc__)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
