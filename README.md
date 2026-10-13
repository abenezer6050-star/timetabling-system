# University Timetabling System

A desktop application that automatically generates conflict-free academic timetables
for departments with complex scheduling constraints. My final year project for a
BSc in Computer Science (University of Reading), built as the sole developer.

Non-technical users enter rooms, lecturers, groups and modules through a graphical
interface. The app models the scheduling problem and uses a constraint solver to
find a valid timetable, so nobody needs to understand the solver underneath.

<!-- Add a screenshot here: ![Timetable view](screenshot.png) -->

## Features

- **Tkinter GUI** with tabs for Rooms, Timeslots, Lecturers, Groups and Modules
- **Auto mode:** the solver places modules. **Manual mode:** you choose the slot, with clash detection
- **Interactive timetable grid** where you can pick up a module and move it
- **Constraint solving with Google OR-Tools CP-SAT**
  - Hard constraints: room capacity and room type, lecturer availability, break slots,
    no student group, lecturer or room double-booked, consecutive (multi-slot) sessions,
    alternate-week patterns
  - Soft constraints with adjustable weights: avoid first/last slots, spread sessions
    evenly across days, slots and rooms, avoid lecturer back-to-back sessions
- **Pre-flight check** that flags modules with no suitable room before solving
- **Conflict report** (Analysis tab) with the final penalty score
- **Bulk generate by group:** re-solve selected groups while keeping other placements fixed
- **Save/load** all data as JSON and **export the timetable to PDF** (ReportLab; falls back to HTML if it is not installed)

## Tech

Python, Tkinter, Google OR-Tools (CP-SAT), ReportLab, JSON, threading (the solver runs
off the main thread so the interface stays responsive).

## Run it

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python timetable_system.py
```

Tkinter ships with most Python installs. On some Linux systems install it with
`sudo apt install python3-tk`.

### Try it with sample data

1. Click the load button and choose `sample_data.json`
2. Generate the timetable with the solver (Auto mode)
3. Open the Analysis tab for the conflict report, then export to PDF

`sample_data.json` is invented example data (no real staff or students).

## How it works

Each module gets a day, a timeslot and a room as decision variables. Hard constraints
rule out invalid combinations, and the solver minimises a weighted sum of soft-constraint
penalties (0 would be a perfectly even spread; lower is better).

## Limitations and ideas

- All code is in a single file; splitting it into modules (data, solver, UI) would make it easier to test.
- No automated tests yet; the solver logic is the first thing I would cover.
- Ideas: more constraint types, importing data from CSV, a web front end.
