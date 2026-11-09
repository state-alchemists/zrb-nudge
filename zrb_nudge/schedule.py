"""The nudge file: the schedules, and what has already been said.

One JSON file holds both, because they answer one question — "is this moment due,
and unsaid?" — and a second file could only let the two answers disagree.

    {
      "schedules": [
        {"id": "lunch", "at": "12:00", "within": 120,
         "repeat": "daily", "message": "It is lunchtime and the user is working."}
      ],
      "said": {"lunch": "2026-11-09T12:00"}
    }

`at` is a time of day on the 24-hour clock. `within` is how many minutes after it
the moment is still true, so a zrb started at 13:10 can still mention the 12:00
lunch. `repeat` is `daily`, `weekdays` or `once`; a one-off schedule is removed once
it has been said, since it has nothing left to say. `said` holds the scheduled
moment last used, not the clock the turn happened to run at — comparing moments is
what makes a window fire exactly once.

The file belongs to the tools, and an entry written by hand is read exactly as one
they wrote. Only these keys are kept: anything else is dropped on the next write.
"""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPEATS = ("daily", "weekdays", "once")
# How long a scheduled moment stays true by default: long enough that a zrb started
# late still says the thing, short enough that "12:00" does not mean "sometime today".
DEFAULT_WITHIN = 120
# Saturday: `date.weekday()` counts from Monday, so this is where a weekend starts.
WEEKEND_START = 5
DEFAULT_FILE = "~/.zrb/nudge.json"
PREFIX_VAR = "_ZRB_ENV_PREFIX"
DEFAULT_PREFIX = "ZRB"


def prefix() -> str:
    """zrb's own settings prefix. Read from the bare variable zrb keeps it in, so a
    white-labeled zrb points this package at its own settings without a code change."""
    return os.getenv(PREFIX_VAR) or DEFAULT_PREFIX


def setting(name: str, default: str) -> str:
    """A nudge setting's value, spelled with the prefix zrb is running under."""
    return os.getenv(f"{prefix()}_NUDGE_{name}", default)


def nudge_file() -> Path:
    """The schedule file, from <PREFIX>_NUDGE_FILE; ~/.zrb/nudge.json by default."""
    return Path(os.path.expanduser(setting("FILE", DEFAULT_FILE)))


def parse_at(text: str) -> int:
    """Minutes into the day for a time like "12:30"; 24:00 is the end of the day, not an hour."""
    hour_text, _, minute_text = str(text).strip().partition(":")
    try:
        hour, minute = int(hour_text), int(minute_text)
    except ValueError:
        raise ValueError(
            f"at must read like 12:30 on the 24-hour clock; got {text!r}"
        ) from None
    if not 0 <= hour <= 24 or not 0 <= minute < 60 or (hour == 24 and minute):
        raise ValueError(f"at must read like 12:30 on the 24-hour clock; got {text!r}")
    return hour * 60 + minute


@dataclass(frozen=True)
class Schedule:
    """One when-and-what: a time of day, how long its moment lasts, and what to say."""

    id: str
    at: str
    message: str
    within: int = DEFAULT_WITHIN
    repeat: str = "daily"

    @property
    def minutes(self) -> int:
        return parse_at(self.at)

    def starts_on(self, day: datetime.date) -> bool:
        """Whether a window opens on `day`. A one-off starts every day and stops by being removed."""
        return self.repeat != "weekdays" or day.weekday() < WEEKEND_START


@dataclass
class Document:
    """The file: the schedules, and the moment each one last used."""

    schedules: list[Schedule] = field(default_factory=list)
    said: dict[str, str] = field(default_factory=dict)


def make(
    id: str,
    at: str,
    message: str,
    within: int = DEFAULT_WITHIN,
    repeat: str = "daily",
) -> Schedule:
    """One schedule, normalized, or a ValueError saying what is wrong with it."""
    name = str(id).strip()
    if not name:
        raise ValueError("id must be a name for the schedule")
    said = str(message).strip()
    if not said:
        raise ValueError("message must be what to tell the user")
    minutes = parse_at(at)
    if isinstance(within, bool) or not isinstance(within, int) or within <= 0:
        raise ValueError(
            f"within is how many minutes after {at} the moment is still true: "
            f"a whole number above zero; got {within!r}"
        )
    kind = str(repeat).strip().lower()
    if kind not in REPEATS:
        raise ValueError(f"repeat must be one of {', '.join(REPEATS)}; got {repeat!r}")
    return Schedule(
        id=name,
        at=f"{minutes // 60:02d}:{minutes % 60:02d}",
        message=said,
        within=within,
        repeat=kind,
    )


def document_from(data: object, source: str = "the nudge file") -> Document:
    """The schedules and ledger in a decoded file, or a ValueError naming what is wrong."""
    if not isinstance(data, dict):
        raise ValueError(f"{source} is not a JSON object; fix it or move it aside")
    entries = data.get("schedules", [])
    if not isinstance(entries, list):
        raise ValueError(f"{source}: schedules must be a list")
    schedules = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"{source}: schedule {index} is not an object")
        try:
            schedules.append(
                make(
                    entry["id"],
                    entry["at"],
                    entry["message"],
                    entry.get("within", DEFAULT_WITHIN),
                    entry.get("repeat", "daily"),
                )
            )
        except KeyError as missing:
            raise ValueError(
                f"{source}: schedule {index} has no {missing.args[0]}"
            ) from None
        except ValueError as error:
            raise ValueError(f"{source}: schedule {index}: {error}") from None
    names = [entry.id for entry in schedules]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ValueError(
            f"{source}: more than one schedule is called {', '.join(repeated)}"
        )
    said = data.get("said", {})
    if not isinstance(said, dict) or not all(
        isinstance(moment, str) for moment in said.values()
    ):
        raise ValueError(f"{source}: said must map a schedule id to the moment it used")
    return Document(schedules, dict(said))


def document_to(document: Document) -> dict:
    """The file's shape, for json.dumps."""
    return {
        "schedules": [
            {
                "id": entry.id,
                "at": entry.at,
                "within": entry.within,
                "repeat": entry.repeat,
                "message": entry.message,
            }
            for entry in document.schedules
        ],
        "said": dict(document.said),
    }


def load(path: Path) -> Document:
    """The file's schedules and ledger. A missing file is empty, not an error; one that
    is not ours is an error, because writing over it would lose what somebody meant."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Document()
    except OSError as error:
        raise ValueError(f"{path} could not be read: {error}") from None
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ValueError(f"{path} is not JSON ({error}); fix it or move it aside") from None
    return document_from(data, str(path))


def save(path: Path, document: Document) -> None:
    """Write the file whole and move it into place: a half-written one would read as a
    day with nothing said, and start over."""
    path.parent.mkdir(parents=True, exist_ok=True)
    half = path.with_name(path.name + ".new")
    half.write_text(json.dumps(document_to(document), indent=2) + "\n", encoding="utf-8")
    half.replace(path)


def moment(entry: Schedule, now: datetime.datetime) -> datetime.datetime | None:
    """The scheduled moment whose window holds `now`: today's, or yesterday's when the
    window runs past midnight."""
    for day in (now.date(), now.date() - datetime.timedelta(days=1)):
        if not entry.starts_on(day):
            continue
        start = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(
            minutes=entry.minutes
        )
        if start <= now < start + datetime.timedelta(minutes=entry.within):
            return start
    return None


def _said(document: Document, entry: Schedule, start: datetime.datetime) -> bool:
    """Whether this exact moment has already been used. A ledger nobody can read silences
    nothing: the day is said again rather than lost."""
    last = document.said.get(entry.id)
    if not last:
        return False
    try:
        return datetime.datetime.fromisoformat(last) >= start
    except ValueError:
        return False


def pending(
    document: Document, now: datetime.datetime
) -> tuple[Schedule, datetime.datetime] | None:
    """The earliest moment that is due and unsaid, with what to say for it."""
    due = [
        (start, order, entry)
        for order, entry in enumerate(document.schedules)
        if (start := moment(entry, now)) is not None
        and not _said(document, entry, start)
    ]
    if not due:
        return None
    start, _, entry = min(due, key=lambda item: (item[0], item[1]))
    return entry, start


def mark_said(
    document: Document, entry: Schedule, start: datetime.datetime
) -> Document:
    """A moment used: written down, and a one-off schedule dropped, since it is spent.

    The ledger keeps only what is still scheduled, so an entry deleted from the file by
    hand leaves nothing behind on the next write.
    """
    remaining = [
        other
        for other in document.schedules
        if entry.repeat != "once" or other.id != entry.id
    ]
    kept = {other.id for other in remaining}
    said = {
        name: used for name, used in document.said.items() if name in kept
    }
    if entry.repeat != "once":
        said[entry.id] = start.isoformat(timespec="minutes")
    return Document(remaining, said)


def free_id(document: Document, message: str) -> str:
    """A name for a schedule nobody named: its first words, counted up if that is taken."""
    words = "".join(c if c.isalnum() else " " for c in message.lower()).split()
    base = "-".join(words[:4])[:32] or "nudge"
    taken = {entry.id for entry in document.schedules}
    if base not in taken:
        return base
    count = 2
    while f"{base}-{count}" in taken:
        count += 1
    return f"{base}-{count}"


def add(document: Document, entry: Schedule) -> Document:
    """The file with one more schedule, or a ValueError naming the id already in it."""
    if any(other.id == entry.id for other in document.schedules):
        raise ValueError(
            f"there is already a schedule called {entry.id};"
            " remove it first, or give this one another id"
        )
    return Document([*document.schedules, entry], dict(document.said))


def remove(document: Document, id: str) -> tuple[Document, Schedule]:
    """The file without that schedule, and the schedule that went; a ValueError if unknown."""
    for entry in document.schedules:
        if entry.id == id:
            return (
                Document(
                    [other for other in document.schedules if other.id != id],
                    {name: used for name, used in document.said.items() if name != id},
                ),
                entry,
            )
    known = ", ".join(entry.id for entry in document.schedules) or "none"
    raise ValueError(f"there is no schedule called {id}; schedules: {known}")


def describe(document: Document) -> str:
    """The schedules, one per line, for whoever has to decide what to change."""
    if not document.schedules:
        return "No schedules."
    lines = ["Schedules:"]
    for entry in sorted(document.schedules, key=lambda item: (item.minutes, item.id)):
        lines.append(
            f"- {entry.id} at {entry.at}, {entry.repeat}, "
            f"within {entry.within} min: {entry.message}"
        )
    return "\n".join(lines)
