# zrb-nudge

Scheduled reminders for [zrb](https://github.com/state-alchemists/zrb). A reminder is a
line in a JSON file; two tools write that file, and a trigger reads it and offers the
agent a turn when a reminder's moment comes. Nothing here needs a window or a face: it
works in any `zrb chat`.

## Install

```sh
pipx install zrb-nudge        # or: pip install zrb-nudge, next to zrb
zrb-nudge install             # append the export line to your shell profile, once
zrb chat
```

`zrb-nudge install` appends this line to the profile your shell reads (`~/.zshrc` for
zsh, `~/.bashrc` for bash, else `~/.profile`) and prints what it wrote:

```sh
export ZRB_INIT_SCRIPTS="$ZRB_INIT_SCRIPTS:/…/site-packages/zrb_nudge/zrb_init.py"
```

Open a new shell afterwards. `zrb-nudge uninstall` takes that line out again and
leaves the rest of the file alone.

## Using it

Ask the agent, in a normal turn:

> remind me at 15:30 that the deploy starts at 16:00

> stop reminding me to stretch

It answers with `AddSchedule` or `RemoveSchedule`. You can also write the file
yourself — the tools read exactly what they wrote:

```sh
zrb-nudge show     # the file, the schedules in it, and what has been said today
```

## The file

`~/.zrb/nudge.json`, or wherever `ZRB_NUDGE_FILE` points:

```json
{
  "schedules": [
    {
      "id": "lunch",
      "at": "12:00",
      "within": 120,
      "repeat": "daily",
      "message": "It is lunchtime and the user is still working."
    }
  ],
  "said": {"lunch": "2026-11-09T12:00"}
}
```

| Key | What it means |
| --- | --- |
| `id` | The name `RemoveSchedule` takes. Leave it off in a tool call and it is made from the first words of the message. |
| `at` | A time of day on the 24-hour clock, `12:30`. `24:00` is the end of the day. |
| `within` | Minutes after `at` during which the moment is still true, so a zrb started at 13:10 can still mention the 12:00 lunch. Past that, the moment is gone and the next one is tomorrow. |
| `repeat` | `daily`, `weekdays` (Monday to Friday) or `once`. A `once` reminder removes itself after it has been said, since it has nothing left to say. |
| `message` | The situation, not the words: the turn says it in the agent's own voice. |
| `said` | When each moment was last used. Written by the trigger, not by you. |

A window that runs past midnight is a window: `23:30` with `within: 60` is still due
at `00:15`, and it is still 23:30's reminder. Only these keys are kept; anything else
you add is dropped on the next write.

## Settings

The prefix follows zrb's own (`CFG.ENV_PREFIX`, `ZRB` by default), so a white-labeled
zrb reads its own names.

| Setting | Default | Read by | What it does |
| --- | --- | --- | --- |
| `ZRB_NUDGE` | `auto` | `zrb_init.py` | `auto` offers a turn when a moment is due and unsaid; `off` never does. |
| `ZRB_NUDGE_FILE` | `~/.zrb/nudge.json` | both | The schedule file. |
| `ZRB_NUDGE_SECONDS` | `60` | `zrb_init.py` | Seconds between looking at the file. Reading it costs nothing, so a due moment arrives within a minute. |
| `ZRB_NUDGE_PROMPT` | `Before saying anything, check whether the user is at the desk … otherwise reply exactly {nothing_to_say}. Otherwise say this to the user in your own words, briefly.` | `zrb_init.py` | What the turn asks for, after the reminder itself. `{nothing_to_say}` is the one placeholder it reads (`…`); an empty value asks for nothing, so the reminder is the whole turn. |
| `ZRB_NUDGE_PROFILE` | empty | `zrb-nudge install` | The profile to write, instead of the one this shell reads. |

## What a nudge turn is

A due moment becomes a user turn that says so:

```
[nudge 12:00, not typed by the user] It is lunchtime and the user is still working.
Before saying anything, check whether the user is at the desk — AvatarStatus answers it
where zrb-avatar is loaded — and if nobody is there reply exactly … , so nothing is said.
Otherwise say this to the user in your own words, briefly.
```

- It is a normal turn: the model answers it with its tools, its memory and its rules.
- **The presence check is the agent's, not this package's.** A reminder is worth saying
  to somebody; whether somebody is there is a fact only a face can supply. Where
  [zrb-avatar](https://github.com/state-alchemists/zrb-avatar) is loaded its `AvatarStatus`
  (and the `face —` line in every turn) answers it, and its speech backend shows `…`
  without speaking it. Where it is not, the model has nothing to check and simply says
  the reminder.
- A turn that starts while another is running is **queued behind it**, not dropped.
- One moment per look, earliest first: three reminders due at once arrive as three
  turns a minute apart, not one wall of text.
- The moment is written to `said` **before** the turn starts, so a turn that errors, a
  restart, or two zrb processes on the same file cannot say the same thing twice.

## Independence

Nothing here imports zrb-avatar, reads its files, or knows it exists; the two packages
share a convention (`…` for "nothing to say") and a question, not a call. zrb-avatar's
side of the bargain is presence: it knows whether someone is at the desk and answers
`AvatarStatus`. So a chat with no face still gets its reminders, and a chat with one gets
them only when someone is looking.

## The command line

| Command | What it does |
| --- | --- |
| `zrb-nudge init-path` | Prints the `zrb_init.py` to add to `ZRB_INIT_SCRIPTS`, for a profile this command does not write. |
| `zrb-nudge install [profile]` | Appends the export line to the profile, once, and says what it wrote. |
| `zrb-nudge uninstall [profile]` | Removes that line and its marker, and nothing else. |
| `zrb-nudge show` | The schedule file, the schedules in it, and what has been said today. |

## Develop

```sh
pip install -e ".[zrb]"
python test_nudge.py    # the file, the tools, the trigger and the command line
python test_ci.py       # the CI configuration is what keeps a secret out of a pull request
```

| File | Role |
| --- | --- |
| `zrb_nudge/schedule.py` | The file: schedules, windows, the ledger of what has been said, and which moment is due. No zrb, no clock of its own. |
| `zrb_nudge/zrb_init.py` | The zrb side, loaded through `ZRB_INIT_SCRIPTS`: `AddSchedule`, `RemoveSchedule`, and the trigger that reads the file. |
| `zrb_nudge/__main__.py` | The `zrb-nudge` command. |
| `test_nudge.py` | The checklist above, as assertions. |
