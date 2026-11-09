"""zrb-nudge's zrb side: a file of reminders, two tools that write it, and a trigger
that reads it.

    export ZRB_INIT_SCRIPTS="$ZRB_INIT_SCRIPTS:$(zrb-nudge init-path)"

Loading this gives zrb two tools of its own -- AddSchedule and RemoveSchedule -- and
offers the agent a turn when a moment in the file is due and unsaid. The file is the
whole trigger: it is read every <PREFIX>_NUDGE_SECONDS and never held in memory, so a
schedule added a second ago is live and one removed a second ago is gone. A turn that
starts while another is running is queued behind it, not dropped.

Settings (the prefix follows zrb's CFG.ENV_PREFIX, ZRB by default):
  ZRB_NUDGE            "auto" (default) offers a turn when a moment is due and
                       unsaid; "off" never does
  ZRB_NUDGE_FILE       the schedule file (~/.zrb/nudge.json): the schedules, and
                       what has already been said, in one file people can read
  ZRB_NUDGE_SECONDS    seconds between looking at it (60); reading a file costs
                       nothing, and the moment is due to the minute
  ZRB_NUDGE_PROMPT     what the turn asks for, after the reminder itself ("Say this
                       to the user in your own words, briefly."). Empty asks for
                       nothing, so the reminder is the whole turn
"""

import asyncio
import datetime
import os
import sys

from zrb import CFG
from zrb.builtin import llm_chat
from zrb.llm.tool_call import auto_approve
from zrb.llm.ui.trigger import TriggerInput

# zrb moved its shared layer-0 leaves into `zrb.llm.shared`, and this plugin declares no
# minimum zrb: read the layout that is here. The class is the same code in both spots.
try:
    from zrb.llm.shared.input_source import InputProvenance
except ImportError:  # a zrb that predates the move keeps it at the top of zrb.llm
    from zrb.llm.input_source import InputProvenance

# zrb loads this file by path; from a source checkout the package isn't installed.
# Appended, not prepended: installed, this folder is another venv's site-packages,
# whose compiled modules would shadow the running zrb's own.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# zrb's prefix is authoritative here -- a white-labeled zrb sets its own -- and the
# file module reads it from the bare variable zrb keeps it in, so it works with or
# without zrb around it.
os.environ.setdefault("_ZRB_ENV_PREFIX", CFG.ENV_PREFIX)
from zrb_nudge import schedule  # noqa: E402

NUDGE = os.getenv(f"{schedule.prefix()}_NUDGE", "auto").strip().lower()  # auto | off
FILE = schedule.nudge_file()
SECONDS = float(schedule.setting("SECONDS", "60"))
PROMPT = schedule.setting("PROMPT", "Say this to the user in your own words, briefly.")
_warned = ""


def AddSchedule(
    at: str,
    message: str,
    id: str = "",
    repeat: str = "daily",
    within: int = schedule.DEFAULT_WITHIN,
) -> str:
    """Schedule a reminder: what to say, and when.

    `at` is a time of day on the 24-hour clock, like "12:30". `message` is the situation
    itself, written the way you would want to be reminded of it ("It is lunchtime and the
    user is still working"), not the words to say: the turn says it in its own voice.

    `within` is how many minutes after `at` the reminder is still worth saying, so a zrb
    started late still says it; past that, the moment is gone and the next one is
    tomorrow. `repeat` is `daily`, `weekdays` (Monday to Friday) or `once`; a `once`
    reminder removes itself after it has been said, so use it for today's one thing.
    Leave `id` empty to name it after its first words; a name makes RemoveSchedule and
    the file readable.
    """
    try:
        document = schedule.load(FILE)
        entry = schedule.make(
            id or schedule.free_id(document, message), at, message, within, repeat
        )
        document = schedule.add(document, entry)
        schedule.save(FILE, document)
    except (OSError, ValueError) as error:
        return f"Not added: {error}"
    return f"Added {entry.id}.\n\n{schedule.describe(document)}"


def RemoveSchedule(id: str) -> str:
    """Remove a scheduled reminder by its id, as AddSchedule or this tool's own answer
    named it. The reminder stops at once: the trigger reads the file, so nothing waits
    for a restart. Say what you removed in your own words when the user asked for it;
    when you are only tidying up, nothing needs saying."""
    try:
        document = schedule.load(FILE)
        document, removed = schedule.remove(document, str(id).strip())
        schedule.save(FILE, document)
    except (OSError, ValueError) as error:
        return f"Not removed: {error}"
    return f"Removed {removed.id} ({removed.at}, {removed.repeat}).\n\n{schedule.describe(document)}"


def _nudge_input(entry: schedule.Schedule, start: datetime.datetime) -> TriggerInput:
    """The turn a due moment starts: the reminder, then what to do with it."""
    text = f"[nudge {start:%H:%M}, not typed by the user] {entry.message}"
    if PROMPT.strip():
        text += f" {PROMPT.strip()}"
    return TriggerInput(
        text=text,
        source=InputProvenance("nudge", modality="text"),
    )


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _warn(error: BaseException) -> None:
    """Say what is wrong once per distinct problem: a bad file must not print every minute."""
    global _warned
    message = f"zrb-nudge: not nudging: {error}"
    if message != _warned:
        print(message)
        _warned = message


async def nudge_watch():
    """A turn offered when a moment in the file is due and unsaid, one moment per look.

    The rules cost nothing -- a file read -- so they run every NUDGE_SECONDS; the turn they
    start is where the model decides how to say it in its own words. The moment is written
    down before the turn starts, so an error, a restart, or two zrb processes reading the
    same file cannot say the same thing twice. Earliest first, and one per look: three
    reminders due at once arrive as three turns rather than one wall of text.
    """
    if NUDGE == "off":
        return
    while True:
        await asyncio.sleep(SECONDS)
        now = _now()
        try:
            document = schedule.load(FILE)
            due = schedule.pending(document, now)
            if due is None:
                continue
            entry, start = due
            schedule.save(FILE, schedule.mark_said(document, entry, start))
        except (OSError, ValueError) as error:
            _warn(error)
            continue
        yield _nudge_input(entry, start)


# Both tools write a file the trigger re-reads, so neither needs approval; a wrong
# reminder is undone by the next call, not by a gate in front of this one.
for _tool in (AddSchedule, RemoveSchedule):
    llm_chat.append_tool(_tool)
    llm_chat.prepend_tool_policy(auto_approve(_tool.__name__, kwargs_patterns=None))
llm_chat.append_trigger(nudge_watch)
