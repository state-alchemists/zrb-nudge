"""The nudge file, the two tools that write it, and the trigger that reads it.

Read as a checklist, the way zrb-avatar's tests are: what a schedule means, what has
been said, what happens when the file is hand-edited or broken, and that the CLI
writes its one line to a profile and takes it away again.
"""

import asyncio
import datetime
import json
import tempfile
from pathlib import Path

from zrb_nudge import __main__ as cli
from zrb_nudge import schedule

# A time of day is minutes into the day, and a time that is not one is refused by name.
assert schedule.parse_at("12:30") == 12 * 60 + 30
assert schedule.parse_at(" 7:05 ") == 7 * 60 + 5
assert schedule.parse_at("24:00") == 24 * 60  # the end of the day, not an hour in it
for unreadable in ("noon", "12", "25:00", "12:60", "12:30:45", "", "12:-1"):
    try:
        schedule.parse_at(unreadable)
    except ValueError as error:
        assert "12:30" in str(error), error
    else:
        raise AssertionError(f"{unreadable!r} was accepted as a time")

# A schedule is normalized where it is made, so the file says one thing per entry:
# 9:05 is written the way a clock reads, and anything the trigger could not act on
# is refused rather than stored and discovered later.
entry = schedule.make("lunch", "9:5", "  It is lunchtime.  ", 90, " DAILY ")
assert (entry.at, entry.message, entry.within, entry.repeat) == (
    "09:05",
    "It is lunchtime.",
    90,
    "daily",
)
assert entry.minutes == 9 * 60 + 5
assert schedule.make("x", "23:59", "m").minutes == 23 * 60 + 59
for refused in (
    ("", "12:00", "m", 120, "daily"),  # no name
    ("x", "12:00", "  ", 120, "daily"),  # nothing to say
    ("x", "12:00", "m", 120, "hourly"),  # a repeat the trigger cannot act on
    ("x", "12:00", "m", 0, "daily"),  # a window that never opens
    ("x", "12:00", "m", -5, "daily"),
    ("x", "12:00", "m", True, "daily"),  # a bool is not a number of minutes
    ("x", "12:00", "m", 1.5, "daily"),
):
    try:
        schedule.make(*refused)  # type: ignore[arg-type] -- the shapes it must refuse
    except ValueError as error:
        assert any(
            word in str(error) for word in ("id", "message", "within", "repeat", "at")
        ), error
    else:
        raise AssertionError(f"{refused!r} was accepted")

# Which days a window opens on: daily and once every day (a one-off stops by being
# removed), weekdays Monday to Friday.
monday, saturday = datetime.date(2026, 11, 9), datetime.date(2026, 11, 14)
assert monday.weekday() == 0 and saturday.weekday() == schedule.WEEKEND_START
daily = schedule.make("daily", "12:00", "m")
weekdays = schedule.make("weekdays", "12:00", "m", repeat="weekdays")
once = schedule.make("once", "12:00", "m", repeat="once")
assert daily.starts_on(saturday) and weekdays.starts_on(monday) and once.starts_on(saturday)
assert not weekdays.starts_on(saturday)


def clock(hour, minute=0, day=9):
    return datetime.datetime(2026, 11, day, hour, minute)


# The moment a schedule is about is the time it names, and it stays true for its window:
# a zrb started at 12:40 still says the 12:00 lunch, and at 14:05 it does not.
assert schedule.moment(daily, clock(11, 59)) is None
assert schedule.moment(daily, clock(12)) == clock(12)
assert schedule.moment(daily, clock(13, 59)) == clock(12)
assert schedule.moment(daily, clock(14)) is None
# A window that runs past midnight is yesterday's moment, not a new one: 23:30 with
# 60 minutes is still open at 00:15, and it is still 23:30.
bed = schedule.make("bed", "23:30", "Go to bed.", within=60)
assert schedule.moment(bed, clock(0, 15, day=10)) == clock(23, 30, day=9)
assert schedule.moment(bed, clock(0, 30, day=10)) is None  # the window closes at 00:30
# A weekday window does not open on a weekend, so Saturday's 12:00 is nothing.
assert schedule.moment(weekdays, clock(12, 30, day=14)) is None
assert schedule.moment(weekdays, clock(12, 30, day=13)) == clock(12, day=13)

# What is pending is the earliest due and unsaid moment. The ledger holds the moment
# that was used, so the same window cannot fire twice, while the next day's can.
document = schedule.Document([daily, bed])
assert schedule.pending(document, clock(11)) is None
assert schedule.pending(document, clock(12, 30)) == (daily, clock(12))
used = schedule.mark_said(document, daily, clock(12))
assert used.said == {"daily": "2026-11-09T12:00"}
assert schedule.pending(used, clock(12, 31)) is None
assert schedule.pending(used, clock(12, 30, day=10)) == (daily, clock(12, day=10))
# Two due at once arrive in time order, whichever order the file holds them in.
both = schedule.Document([bed, daily])
assert schedule.pending(both, clock(23, 45)) == (bed, clock(23, 30, day=9))
# A ledger nobody can read silences nothing: the day is said again rather than lost.
broken = schedule.Document([daily], {"daily": "yesterday-ish"})
assert schedule.pending(broken, clock(12, 30)) == (daily, clock(12))

# A one-off is spent once it is said: it leaves the file with its ledger entry, since
# there is nothing left to keep. A repeating one keeps both.
spent = schedule.mark_said(schedule.Document([once]), once, clock(12))
assert spent.schedules == [] and spent.said == {}
kept = schedule.mark_said(schedule.Document([daily], {"gone": "2026-11-08T12:00"}), daily, clock(12))
assert [entry.id for entry in kept.schedules] == ["daily"]
assert kept.said == {"daily": "2026-11-09T12:00"}  # and the id that left is gone

# A schedule nobody named is named after its first words, counted up if that is taken.
assert schedule.free_id(schedule.Document(), "It is lunchtime and the user works") == (
    "it-is-lunchtime-and"
)
named = schedule.Document([schedule.make("it-is-lunchtime-and", "12:00", "m")])
assert schedule.free_id(named, "It is lunchtime and the user works") == (
    "it-is-lunchtime-and-2"
)
assert schedule.free_id(schedule.Document(), "!!!") == "nudge"

# Adding refuses an id that is taken; removing an unknown one says what there is.
added = schedule.add(schedule.Document(), daily)
assert [entry.id for entry in added.schedules] == ["daily"]
try:
    schedule.add(added, schedule.make("daily", "13:00", "m"))
except ValueError as error:
    assert "already a schedule called daily" in str(error), error
else:
    raise AssertionError("a duplicate id was accepted")
removed, was = schedule.remove(schedule.Document([daily, bed], {"daily": "x", "bed": "y"}), "daily")
assert was.id == "daily" and [entry.id for entry in removed.schedules] == ["bed"]
assert removed.said == {"bed": "y"}
try:
    schedule.remove(removed, "nope")
except ValueError as error:
    assert "no schedule called nope" in str(error) and "bed" in str(error), error
else:
    raise AssertionError("removing an unknown id was accepted")


# The file: a missing one is empty, one that is not ours is an error rather than
# something to write over, and a write leaves no half file behind.
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / "nudge.json"
    assert schedule.load(path) == schedule.Document()
    schedule.save(path, schedule.Document([daily], {"daily": "2026-11-09T12:00"}))
    assert schedule.load(path) == schedule.Document(
        [daily], {"daily": "2026-11-09T12:00"}
    )
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schedules": [
            {
                "id": "daily",
                "at": "12:00",
                "within": 120,
                "repeat": "daily",
                "message": "m",
            }
        ],
        "said": {"daily": "2026-11-09T12:00"},
    }
    assert not (Path(folder) / "nudge.json.new").exists()
    # A key nobody knows is dropped, and what the file does say is read.
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "schedules": [{"id": "lunch", "at": "12:00", "message": "m"}],
            }
        ),
        encoding="utf-8",
    )
    reloaded = schedule.load(path)
    assert [(entry.id, entry.at, entry.within, entry.repeat) for entry in reloaded.schedules] == [
        ("lunch", "12:00", schedule.DEFAULT_WITHIN, "daily")
    ]
    assert reloaded.said == {}
    for broken in (
        "{not json",
        "[]",
        '{"schedules": {}}',
        '{"schedules": [1]}',
        '{"schedules": [{"id": "a", "message": "m"}]}',
        '{"schedules": [{"id": "a", "at": "noon", "message": "m"}]}',
        '{"schedules": [{"id": "a", "at": "12:00", "message": "m"},'
        ' {"id": "a", "at": "13:00", "message": "m"}]}',
        '{"schedules": [], "said": {"a": 1}}',
    ):
        path.write_text(broken, encoding="utf-8")
        try:
            schedule.load(path)
        except ValueError as error:
            assert str(path) in str(error), error
        else:
            raise AssertionError(f"{broken!r} was accepted")

# The listing names every schedule, its time and how often; an empty file says so.
assert schedule.describe(schedule.Document()) == "No schedules."
listing = schedule.describe(schedule.Document([bed, daily]))
assert listing.startswith("Schedules:\n- daily at 12:00, daily"), listing
assert "- bed at 23:30, daily, within 60 min: Go to bed." in listing
assert listing.index("daily") < listing.index("bed")  # in time order, whatever the file says


# Her tools write that file and answer with what is in it now, so the model never has
# to guess what it changed. This needs zrb, which everything above does without.
import zrb_nudge.zrb_init as nudge  # noqa: E402

with tempfile.TemporaryDirectory() as folder:
    saved_file, saved_prompt = nudge.FILE, nudge.PROMPT
    nudge.FILE = Path(folder) / "nudge.json"
    try:
        answer = nudge.AddSchedule("12:00", "It is lunchtime and the user is still working.")
        assert answer.startswith("Added it-is-lunchtime-and.\n\nSchedules:\n- "), answer
        assert "at 12:00, daily, within 120 min" in answer
        listed = schedule.load(nudge.FILE)
        assert [(entry.id, entry.repeat) for entry in listed.schedules] == [
            ("it-is-lunchtime-and", "daily")
        ]
        # A name makes it addressable, and a second call with the same name is refused
        # without touching the file.
        assert "Added lunch." in nudge.AddSchedule(
            "22:30", "It is late and the user is still working.", id="lunch", repeat="weekdays"
        )
        refused = nudge.AddSchedule("23:00", "x", id="lunch")
        assert refused.startswith("Not added: there is already a schedule called lunch"), refused
        assert len(schedule.load(nudge.FILE).schedules) == 2
        # A time it cannot read is refused by name, and nothing is written.
        assert nudge.AddSchedule("noon", "x", id="noon").startswith("Not added: at must read like")
        assert len(schedule.load(nudge.FILE).schedules) == 2
        assert nudge.RemoveSchedule("  lunch  ") == (
            "Removed lunch (22:30, weekdays).\n\nSchedules:\n- "
            "it-is-lunchtime-and at 12:00, daily, within 120 min:"
            " It is lunchtime and the user is still working."
        )
        assert nudge.RemoveSchedule("lunch").startswith("Not removed: there is no schedule called lunch")
        # A file that is not ours is reported, not overwritten: it may hold somebody's work.
        nudge.FILE.write_text("{oops", encoding="utf-8")
        assert nudge.AddSchedule("12:00", "x").startswith("Not added: ")
        assert nudge.RemoveSchedule("x").startswith("Not removed: ")
        assert nudge.FILE.read_text(encoding="utf-8") == "{oops"
    finally:
        nudge.FILE, nudge.PROMPT = saved_file, saved_prompt

# What a due moment turns into: the reminder, then what to do with it. A prompt set to
# nothing leaves the reminder alone, with no trailing space to trip over.
with tempfile.TemporaryDirectory() as folder:
    saved_file = nudge.FILE
    nudge.FILE = Path(folder) / "nudge.json"
    try:
        nudge.PROMPT = "Say this in your own words."
        text = nudge._nudge_input(daily, clock(12)).text
        assert text == (
            "[nudge 12:00, not typed by the user] m Say this in your own words."
        ), text
        nudge.PROMPT = "   "
        assert nudge._nudge_input(daily, clock(12)).text == (
            "[nudge 12:00, not typed by the user] m"
        )
        assert nudge._nudge_input(daily, clock(12)).source.modality == "text"
    finally:
        nudge.FILE, nudge.PROMPT = saved_file, nudge.PROMPT if False else saved_prompt


async def _a_due_moment_is_offered():
    """The trigger, end to end: one look, one turn, and the moment written down first."""
    with tempfile.TemporaryDirectory() as folder:
        saved = (nudge.FILE, nudge.SECONDS, nudge.NUDGE, nudge._now)
        nudge.FILE = Path(folder) / "nudge.json"
        nudge.SECONDS, nudge.NUDGE = 0.001, "auto"
        nudge._now = lambda: clock(12, 30)
        try:
            nudge.PROMPT = "Say this in your own words."
            schedule.save(nudge.FILE, schedule.Document([daily, bed]))
            generator = nudge.nudge_watch()
            try:
                turn = await asyncio.wait_for(anext(generator), timeout=10)
            finally:
                await generator.aclose()
            # Written before the turn: an error, a restart or a second zrb cannot repeat it.
            assert schedule.load(nudge.FILE).said == {"daily": "2026-11-09T12:00"}
            assert schedule.pending(schedule.load(nudge.FILE), clock(12, 31)) is None
            # Off is off: the same file, the same moment, no turn at all.
            nudge.NUDGE = "off"
            silent = nudge.nudge_watch()
            try:
                await asyncio.wait_for(anext(silent), timeout=1)
            except StopAsyncIteration:
                pass
            else:
                raise AssertionError("a trigger switched off still offered a turn")
            finally:
                await silent.aclose()
            return turn
        finally:
            nudge.FILE, nudge.SECONDS, nudge.NUDGE, nudge._now = saved
            nudge.PROMPT = saved_prompt


turn = asyncio.run(_a_due_moment_is_offered())
assert turn.text == (
    "[nudge 12:00, not typed by the user] m Say this in your own words."
), turn.text
# The trigger is registered whatever the switch says, the way the avatar's sources are:
# the switch is read when it runs, not when zrb starts.
assert nudge.nudge_watch in nudge.llm_chat.triggers


# The command line's one job that writes: the export line is appended once, it says
# what it wrote, and uninstall takes exactly that line away and nothing else.
with tempfile.TemporaryDirectory() as folder:
    profile = Path(folder) / "shellrc"
    profile.write_text("# the user's own lines\nalias ll='ls -l'\n", encoding="utf-8")
    cli.install(profile)
    text = profile.read_text(encoding="utf-8")
    assert text.startswith("# the user's own lines\nalias ll='ls -l'\n")
    assert text.count(str(cli.INIT_SCRIPT)) == 1
    assert cli.MARKER in text
    assert text.endswith("\n")
    # Running it again is not a second line.
    cli.install(profile)
    assert profile.read_text(encoding="utf-8").count(str(cli.INIT_SCRIPT)) == 1
    # A line that only mentions the path in a comment is not a line that loads it.
    commented = Path(folder) / "commented"
    commented.write_text(f"# {cli.INIT_SCRIPT}\n", encoding="utf-8")
    cli.install(commented)
    assert commented.read_text(encoding="utf-8").count(str(cli.INIT_SCRIPT)) == 2
    cli.uninstall(commented)
    assert commented.read_text(encoding="utf-8") == f"# {cli.INIT_SCRIPT}\n"
    cli.uninstall(profile)
    assert profile.read_text(encoding="utf-8") == "# the user's own lines\nalias ll='ls -l'\n"
    cli.uninstall(Path(folder) / "missing")
    cli.uninstall(profile)  # nothing left to remove says so rather than failing

print("ok")
