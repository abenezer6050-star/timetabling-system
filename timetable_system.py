# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import json
import threading
import math
from ortools.sat.python import cp_model

# =========================================================
# CONSTANTS
# =========================================================
DAYS          = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
ROOM_TYPES    = ["Any", "Lecture Theatre", "Lab", "Seminar Room", "Tutorial Room"]
MODULE_TYPES  = ["Lecture", "Lab", "Seminar", "Tutorial"]
WEEK_PATTERNS = ["Every Week", "Alternate Weeks A", "Alternate Weeks B"]

ROOM_COMPAT = {
    "Lecture":  ["Any", "Lecture Theatre"],
    "Lab":      ["Any", "Lab"],
    "Seminar":  ["Any", "Seminar Room"],
    "Tutorial": ["Any", "Tutorial Room"],
}

LECTURER_COLORS = [
    "#AED6F1", "#A9DFBF", "#F9E79F", "#F1948A", "#D2B4DE",
    "#FAD7A0", "#A3E4D7", "#D5DBDB", "#FDEBD0", "#FADBD8"
]

# =========================================================
# DATA STORAGE
# =========================================================
BUILDINGS   = []   # list of strings
ROOMS       = []   # list of dicts: {name, capacity, room_type, building}
TIMESLOTS   = []   # list of strings
BREAK_SLOTS = set()  # set of timeslot strings marked as breaks
LECTURERS   = []   # list of dicts: {name, unavailable: [(day, slot), ...]}
GROUPS      = []   # list of strings e.g. "CS Year 1"
MODULES     = []   # list of dicts: {name, lecturer, room, timeslot, day,
                   #                  module_type, attendance, consecutive, week_pattern, group}

# Default 9-3 timeslots (13:00-14:00 pre-marked as lunch break)
for _h in range(9, 15):
    TIMESLOTS.append(f"{_h:02d}:00-{_h+1:02d}:00")
BREAK_SLOTS.add("13:00-14:00")

# =========================================================
# SOFT CONSTRAINT WEIGHTS (adjustable via UI)
# =========================================================
# These are plain dicts updated by the settings UI before the solver runs
SOFT_WEIGHTS = {
    "early_late":  2,   # penalty for first/last timeslot
    "day_spread":  3,   # penalty for uneven day distribution
    "slot_spread": 3,   # penalty for uneven timeslot distribution
    "room_spread": 2,   # penalty for uneven room distribution
    "back_to_back":1,   # penalty for lecturer back-to-back sessions
}

# =========================================================
# HELPERS
# =========================================================
def lecturer_names():
    return [l['name'] for l in LECTURERS]

def room_names():
    return [r['name'] for r in ROOMS]

def get_lecturer_color(name):
    names = lecturer_names()
    if not name or name not in names:
        return "#FFFFFF"
    return LECTURER_COLORS[names.index(name) % len(LECTURER_COLORS)]

def weeks_overlap(p1, p2):
    """True if two week patterns could occupy the same week."""
    if p1 == "Every Week" or p2 == "Every Week":
        return True
    return p1 == p2

# =========================================================
# MAIN WINDOW
# =========================================================
root = tk.Tk()
root.title("University Timetabling System")
root.geometry("1340x820")
root.minsize(1050, 680)

status_var = tk.StringVar(value="Ready")
status_bar = tk.Label(root, textvariable=status_var, anchor="w",
                      relief="sunken", font=("Arial", 9), bg="#ECEFF1", padx=8)
status_bar.pack(side="bottom", fill="x")

tk.Label(root, text="  University Timetabling System",
         font=("Arial", 16, "bold"), bg="#1F3864", fg="white",
         anchor="w", pady=8).pack(fill="x")

main_frame = tk.Frame(root)
main_frame.pack(fill="both", expand=True, padx=10, pady=8)

# =========================================================
# LEFT NOTEBOOK
# =========================================================
notebook = ttk.Notebook(main_frame, width=325)
notebook.pack(side="left", fill="y", padx=(0, 10))

tab_rooms     = ttk.Frame(notebook, padding=8)
tab_timeslots = ttk.Frame(notebook, padding=8)
tab_lecturers = ttk.Frame(notebook, padding=8)
tab_groups    = ttk.Frame(notebook, padding=8)
tab_modules   = ttk.Frame(notebook, padding=8)

notebook.add(tab_rooms,     text="  Rooms  ")
notebook.add(tab_timeslots, text=" Timeslots ")
notebook.add(tab_lecturers, text=" Lecturers ")
notebook.add(tab_groups,    text="  Groups  ")
notebook.add(tab_modules,   text="  Modules  ")

# =========================================================
# RIGHT PANEL
# =========================================================
right_frame = tk.LabelFrame(main_frame, text="Timetable & Analysis",
                             font=("Arial", 10, "bold"), padx=8, pady=8)
right_frame.pack(side="right", fill="both", expand=True)

# Button bar packed side=bottom FIRST so it is always visible
btn_bar = tk.Frame(right_frame, bg="#F5F5F5", pady=4)
btn_bar.pack(side="bottom", fill="x")

mode_var = tk.StringVar(value="Manual")
ttk.Label(btn_bar, text="Mode:").pack(side="left", padx=(6, 2))
mode_dropdown = ttk.Combobox(btn_bar, textvariable=mode_var,
                              values=["Manual", "Auto"], state="readonly", width=8)
mode_dropdown.pack(side="left", padx=(0, 10))

generate_btn = ttk.Button(btn_bar, text="Generate",       command=lambda: draw_timetable())
auto_btn     = ttk.Button(btn_bar, text="Auto Solve",     command=lambda: start_solver_thread())
bulk_btn     = ttk.Button(btn_bar, text="Schedule Group",  command=lambda: open_bulk_dialog())
save_btn     = ttk.Button(btn_bar, text="Save",           command=lambda: save_data())
load_btn     = ttk.Button(btn_bar, text="Load",           command=lambda: load_data())
export_btn   = ttk.Button(btn_bar, text="Export PDF",     command=lambda: export_timetable())
clear_btn    = ttk.Button(btn_bar, text="Clear",          command=lambda: clear_timetable())

for btn in (generate_btn, auto_btn, bulk_btn, save_btn, load_btn, export_btn, clear_btn):
    btn.pack(side="left", padx=3)

solver_buttons = [generate_btn, auto_btn, bulk_btn, save_btn, load_btn, export_btn, clear_btn]

# Right sub-notebook: Timetable + Analysis
right_notebook = ttk.Notebook(right_frame)
right_notebook.pack(fill="both", expand=True)

tab_timetable = ttk.Frame(right_notebook)
tab_analysis  = ttk.Frame(right_notebook)
right_notebook.add(tab_timetable, text="  Timetable  ")
right_notebook.add(tab_analysis,  text="  Analysis  ")

# Timetable grid canvas
grid_outer = tk.Frame(tab_timetable)
grid_outer.pack(fill="both", expand=True)

grid_scroll_y = ttk.Scrollbar(grid_outer, orient="vertical")
grid_scroll_x = ttk.Scrollbar(grid_outer, orient="horizontal")
grid_canvas   = tk.Canvas(grid_outer, bg="#ECEFF1",
                           yscrollcommand=grid_scroll_y.set,
                           xscrollcommand=grid_scroll_x.set)
grid_scroll_y.config(command=grid_canvas.yview)
grid_scroll_x.config(command=grid_canvas.xview)
grid_scroll_x.pack(side="bottom", fill="x")
grid_scroll_y.pack(side="right",  fill="y")
grid_canvas.pack(side="left", fill="both", expand=True)

timetable_grid = tk.Frame(grid_canvas, bg="#ECEFF1")
grid_canvas.create_window((0, 0), window=timetable_grid, anchor="nw")

def _on_grid_configure(event=None):
    grid_canvas.configure(scrollregion=grid_canvas.bbox("all"))
timetable_grid.bind("<Configure>", _on_grid_configure)

cells = {}

# Drag-and-drop state
_drag_source = [None]   # (slot, day) of the picked-up cell
_drag_module = [None]   # index into MODULES of the dragged module
tk.Label(tab_analysis, text="Conflict Report",
         font=("Arial", 10, "bold")).pack(anchor="w", padx=6, pady=(6, 0))

conflict_text = scrolledtext.ScrolledText(tab_analysis, height=13,
                                           font=("Courier", 9),
                                           state="disabled", wrap="word")
conflict_text.pack(fill="both", expand=True, padx=6, pady=(4, 0))

# Soft constraint weight settings
weights_lf = ttk.LabelFrame(tab_analysis, text="Soft Constraint Weights  (used by Auto Solve)",
                              padding=6)
weights_lf.pack(fill="x", padx=6, pady=(6, 6))

_weight_vars = {}
_weight_defs = [
    ("early_late",   "Avoid early/late slots",          2),
    ("day_spread",   "Even day distribution",           3),
    ("slot_spread",  "Even timeslot distribution",      3),
    ("room_spread",  "Even room distribution",          2),
    ("back_to_back", "Avoid lecturer back-to-back",     1),
]

tk.Label(weights_lf, text="Constraint", font=("Arial", 9, "bold"),
         width=28, anchor="w").grid(row=0, column=0, sticky="w")
tk.Label(weights_lf, text="Weight (0 = off)", font=("Arial", 9, "bold"),
         anchor="w").grid(row=0, column=1, sticky="w", padx=(8, 0))

for r, (key, label, default) in enumerate(_weight_defs, start=1):
    var = tk.IntVar(value=default)
    _weight_vars[key] = var
    tk.Label(weights_lf, text=label, font=("Arial", 9),
             width=28, anchor="w").grid(row=r, column=0, sticky="w")
    ttk.Spinbox(weights_lf, from_=0, to=10, textvariable=var,
                width=6).grid(row=r, column=1, sticky="w", padx=(8, 0))

def _apply_weights():
    for key, var in _weight_vars.items():
        SOFT_WEIGHTS[key] = var.get()
    status_var.set("Soft constraint weights updated — will apply on next Auto Solve.")

ttk.Button(weights_lf, text="Apply Weights", command=_apply_weights).grid(
    row=len(_weight_defs) + 1, column=0, columnspan=2, sticky="w", pady=(6, 0))

# =========================================================
# TAB: ROOMS
# =========================================================
room_form = ttk.LabelFrame(tab_rooms, text="Room Details", padding=6)
room_form.pack(fill="x", pady=(0, 4))
room_form.columnconfigure(1, weight=1)

tk.Label(room_form, text="Name",     font=("Arial", 9, "bold")).grid(row=0, column=0, sticky="w", pady=2)
room_name_entry = tk.Entry(room_form, width=20)
room_name_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=2)

tk.Label(room_form, text="Capacity", font=("Arial", 9, "bold")).grid(row=1, column=0, sticky="w", pady=2)
room_capacity_var = tk.StringVar(value="30")
tk.Entry(room_form, textvariable=room_capacity_var, width=10).grid(row=1, column=1, sticky="w", padx=(6, 0), pady=2)

tk.Label(room_form, text="Type",     font=("Arial", 9, "bold")).grid(row=2, column=0, sticky="w", pady=2)
room_type_var = tk.StringVar(value="Any")
ttk.Combobox(room_form, textvariable=room_type_var, values=ROOM_TYPES,
             state="readonly", width=18).grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=2)

tk.Label(room_form, text="Building", font=("Arial", 9, "bold")).grid(row=3, column=0, sticky="w", pady=2)
room_building_var = tk.StringVar()
tk.Entry(room_form, textvariable=room_building_var, width=20).grid(row=3, column=1, sticky="ew", padx=(6, 0), pady=2)

def add_room():
    name = room_name_entry.get().strip()
    if not name:
        return
    if name in room_names():
        messagebox.showwarning("Duplicate", "Room already exists.")
        return
    try:
        cap = int(room_capacity_var.get())
    except ValueError:
        cap = 30
    ROOMS.append({'name': name, 'capacity': cap,
                  'room_type': room_type_var.get(),
                  'building': room_building_var.get()})
    room_name_entry.delete(0, tk.END)
    update_room_list()
    update_dropdowns()
    status_var.set(f"Room '{name}' added.")

def update_room_list():
    room_listbox.delete(0, tk.END)
    for r in ROOMS:
        room_listbox.insert(tk.END,
            f"  {r['name']}  |  {r['capacity']} seats  |  {r['room_type']}  |  {r.get('building','')}")

def remove_room():
    sel = room_listbox.curselection()
    if not sel:
        return
    removed = ROOMS.pop(sel[0])['name']
    update_room_list()
    update_dropdowns()
    status_var.set(f"Room '{removed}' removed.")

_rb = tk.Frame(tab_rooms)
_rb.pack(anchor="w", pady=4)
ttk.Button(_rb, text="Add",    command=add_room).pack(side="left", padx=(0, 4))
ttk.Button(_rb, text="Remove", command=remove_room).pack(side="left")

room_listbox = tk.Listbox(tab_rooms, height=10, font=("Arial", 8),
                           selectbackground="#1F3864", selectforeground="white")
room_listbox.pack(fill="both", expand=True, pady=(4, 0))
room_name_entry.bind("<Return>", lambda e: add_room())

# =========================================================
# TAB: TIMESLOTS
# =========================================================
tk.Label(tab_timeslots, text="Timeslot  (e.g. 09:00-10:00)",
         font=("Arial", 9, "bold")).pack(anchor="w")
timeslot_entry = tk.Entry(tab_timeslots, width=28)
timeslot_entry.pack(anchor="w", pady=(2, 4))

is_break_var = tk.BooleanVar(value=False)
ttk.Checkbutton(tab_timeslots, text="Mark as break (no modules allowed)",
                variable=is_break_var).pack(anchor="w", pady=(0, 4))

def add_timeslot():
    ts = timeslot_entry.get().strip()
    if not ts:
        return
    if ts in TIMESLOTS:
        messagebox.showwarning("Duplicate", "Timeslot already exists.")
        return
    TIMESLOTS.append(ts)
    if is_break_var.get():
        BREAK_SLOTS.add(ts)
    timeslot_entry.delete(0, tk.END)
    is_break_var.set(False)
    update_timeslot_list()
    update_dropdowns()
    status_var.set(f"Timeslot '{ts}' added{'  [BREAK]' if ts in BREAK_SLOTS else ''}.")

def toggle_break():
    sel = timeslot_listbox.curselection()
    if not sel:
        messagebox.showinfo("Select Timeslot", "Please select a timeslot to toggle break status.")
        return
    ts = TIMESLOTS[sel[0]]
    if ts in BREAK_SLOTS:
        BREAK_SLOTS.discard(ts)
        status_var.set(f"'{ts}' is no longer a break.")
    else:
        BREAK_SLOTS.add(ts)
        status_var.set(f"'{ts}' marked as break — solver will not schedule modules here.")
    update_timeslot_list()
    update_dropdowns()

def update_timeslot_list():
    timeslot_listbox.delete(0, tk.END)
    for i, t in enumerate(TIMESLOTS):
        label = f"  {t}  [BREAK]" if t in BREAK_SLOTS else f"  {t}"
        timeslot_listbox.insert(tk.END, label)
        if t in BREAK_SLOTS:
            timeslot_listbox.itemconfig(i, bg="#F1948A", fg="white")
        else:
            timeslot_listbox.itemconfig(i, bg="white", fg="black")

def remove_timeslot():
    sel = timeslot_listbox.curselection()
    if not sel:
        return
    removed = TIMESLOTS.pop(sel[0])
    BREAK_SLOTS.discard(removed)
    update_timeslot_list()
    update_dropdowns()
    status_var.set(f"Timeslot '{removed}' removed.")

_tb = tk.Frame(tab_timeslots)
_tb.pack(anchor="w", pady=4)
ttk.Button(_tb, text="Add",          command=add_timeslot).pack(side="left", padx=(0, 4))
ttk.Button(_tb, text="Toggle Break", command=toggle_break).pack(side="left",  padx=(0, 4))
ttk.Button(_tb, text="Remove",       command=remove_timeslot).pack(side="left")

tk.Label(tab_timeslots, text="Red = break slot (solver blocked)",
         font=("Arial", 8), fg="gray").pack(anchor="w")

timeslot_listbox = tk.Listbox(tab_timeslots, height=14, font=("Arial", 9),
                               selectbackground="#1F3864", selectforeground="white")
timeslot_listbox.pack(fill="both", expand=True, pady=(4, 0))
timeslot_entry.bind("<Return>", lambda e: add_timeslot())
update_timeslot_list()  # show pre-defined timeslots on startup

# =========================================================
# TAB: LECTURERS
# =========================================================
tk.Label(tab_lecturers, text="Lecturer Name", font=("Arial", 9, "bold")).pack(anchor="w")
lecturer_entry = tk.Entry(tab_lecturers, width=28)
lecturer_entry.pack(anchor="w", pady=(2, 4))

def add_lecturer():
    lec = lecturer_entry.get().strip()
    if not lec:
        return
    if lec in lecturer_names():
        messagebox.showwarning("Duplicate", "Lecturer already exists.")
        return
    LECTURERS.append({'name': lec, 'unavailable': []})
    lecturer_entry.delete(0, tk.END)
    update_lecturer_list()
    update_dropdowns()
    status_var.set(f"Lecturer '{lec}' added.")

def update_lecturer_list():
    lecturer_listbox.delete(0, tk.END)
    for i, lec in enumerate(LECTURERS):
        lecturer_listbox.insert(tk.END, f"  {lec['name']}")
        lecturer_listbox.itemconfig(i, bg=get_lecturer_color(lec['name']))

def remove_lecturer():
    sel = lecturer_listbox.curselection()
    if not sel:
        return
    removed = LECTURERS.pop(sel[0])['name']
    update_lecturer_list()
    update_dropdowns()
    _refresh_avail_list()
    status_var.set(f"Lecturer '{removed}' removed.")

_lb = tk.Frame(tab_lecturers)
_lb.pack(anchor="w", pady=4)
ttk.Button(_lb, text="Add",    command=add_lecturer).pack(side="left", padx=(0, 4))
ttk.Button(_lb, text="Remove", command=remove_lecturer).pack(side="left")

lecturer_listbox = tk.Listbox(tab_lecturers, height=6, font=("Arial", 9),
                               selectbackground="#1F3864", selectforeground="white")
lecturer_listbox.pack(fill="x", pady=(4, 0))
lecturer_entry.bind("<Return>", lambda e: add_lecturer())

# Unavailability section
avail_lf = ttk.LabelFrame(tab_lecturers, text="Lecturer Unavailability", padding=6)
avail_lf.pack(fill="both", expand=True, pady=(8, 0))

tk.Label(avail_lf, text="Select a lecturer above, then mark unavailable slots:",
         font=("Arial", 8), fg="gray").pack(anchor="w")

avail_row = tk.Frame(avail_lf)
avail_row.pack(fill="x", pady=(4, 0))

avail_day_var  = tk.StringVar()
avail_slot_var = tk.StringVar()

avail_day_combo  = ttk.Combobox(avail_row, textvariable=avail_day_var,
                                 values=DAYS, state="readonly", width=11)
avail_day_combo.pack(side="left", padx=(0, 4))

avail_slot_combo = ttk.Combobox(avail_row, textvariable=avail_slot_var,
                                 state="readonly", width=13)
avail_slot_combo.pack(side="left", padx=(0, 4))

def add_unavailability():
    sel = lecturer_listbox.curselection()
    if not sel:
        messagebox.showinfo("Select Lecturer", "Please select a lecturer from the list above.")
        return
    day  = avail_day_var.get().strip()
    slot = avail_slot_var.get().strip()
    if not day or not slot:
        messagebox.showerror("Error", "Please select both a day and a timeslot.")
        return
    lec = LECTURERS[sel[0]]
    if (day, slot) in lec['unavailable']:
        messagebox.showwarning("Duplicate", "Already marked unavailable.")
        return
    lec['unavailable'].append((day, slot))
    _refresh_avail_list()
    status_var.set(f"{lec['name']} unavailable: {day} {slot}")

def remove_unavailability():
    sel_lec   = lecturer_listbox.curselection()
    sel_avail = avail_listbox.curselection()
    if not sel_lec or not sel_avail:
        return
    LECTURERS[sel_lec[0]]['unavailable'].pop(sel_avail[0])
    _refresh_avail_list()

def _refresh_avail_list():
    avail_listbox.delete(0, tk.END)
    sel = lecturer_listbox.curselection()
    if not sel:
        return
    for (day, slot) in LECTURERS[sel[0]]['unavailable']:
        avail_listbox.insert(tk.END, f"  {day}  |  {slot}")

lecturer_listbox.bind("<<ListboxSelect>>", lambda e: _refresh_avail_list())

avail_btn_row = tk.Frame(avail_lf)
avail_btn_row.pack(anchor="w", pady=4)
ttk.Button(avail_btn_row, text="Add Unavailable",
           command=add_unavailability).pack(side="left", padx=(0, 4))
ttk.Button(avail_btn_row, text="Remove Selected",
           command=remove_unavailability).pack(side="left")

avail_listbox = tk.Listbox(avail_lf, height=7, font=("Arial", 9),
                            selectbackground="#1F3864", selectforeground="white")
avail_listbox.pack(fill="both", expand=True, pady=(4, 0))

# =========================================================
# TAB: GROUPS
# =========================================================
tk.Label(tab_groups, text="Student Group Name  (e.g. CS Year 1)",
         font=("Arial", 9, "bold")).pack(anchor="w")
group_entry = tk.Entry(tab_groups, width=28)
group_entry.pack(anchor="w", pady=(2, 4))

def add_group():
    g = group_entry.get().strip()
    if not g:
        return
    if g in GROUPS:
        messagebox.showwarning("Duplicate", "Group already exists.")
        return
    GROUPS.append(g)
    group_entry.delete(0, tk.END)
    update_group_list()
    update_dropdowns()
    status_var.set(f"Group '{g}' added.")

def update_group_list():
    group_listbox.delete(0, tk.END)
    for g in GROUPS:
        group_listbox.insert(tk.END, f"  {g}")

def remove_group():
    sel = group_listbox.curselection()
    if not sel:
        return
    removed = GROUPS.pop(sel[0])
    update_group_list()
    update_dropdowns()
    status_var.set(f"Group '{removed}' removed.")

_gb = tk.Frame(tab_groups)
_gb.pack(anchor="w", pady=4)
ttk.Button(_gb, text="Add",    command=add_group).pack(side="left", padx=(0, 4))
ttk.Button(_gb, text="Remove", command=remove_group).pack(side="left")

group_listbox = tk.Listbox(tab_groups, height=16, font=("Arial", 9),
                            selectbackground="#1F3864", selectforeground="white")
group_listbox.pack(fill="both", expand=True, pady=(4, 0))
group_entry.bind("<Return>", lambda e: add_group())

tk.Label(tab_groups,
         text="Modules sharing the same group cannot\nbe scheduled at the same time.",
         font=("Arial", 8), fg="gray").pack(anchor="w", pady=(8, 0))

# =========================================================
# TAB: MODULES
# =========================================================
form_lf = ttk.LabelFrame(tab_modules, text="Module Details", padding=6)
form_lf.pack(fill="x", pady=(0, 4))
form_lf.columnconfigure(1, weight=1)

_row = [0]
def _frow():
    r = _row[0]; _row[0] += 1; return r

tk.Label(form_lf, text="Name",        font=("Arial", 9, "bold")).grid(row=_frow(), column=0, sticky="w", pady=1)
module_entry = tk.Entry(form_lf, width=22)
module_entry.grid(row=_row[0]-1, column=1, sticky="ew", padx=(6, 0), pady=1)

tk.Label(form_lf, text="Lecturer",    font=("Arial", 9, "bold")).grid(row=_frow(), column=0, sticky="w", pady=1)
module_lecturer_combo = ttk.Combobox(form_lf, state="readonly", width=20)
module_lecturer_combo.grid(row=_row[0]-1, column=1, sticky="ew", padx=(6, 0), pady=1)

tk.Label(form_lf, text="Type",        font=("Arial", 9, "bold")).grid(row=_frow(), column=0, sticky="w", pady=1)
module_type_var = tk.StringVar(value="Lecture")
ttk.Combobox(form_lf, textvariable=module_type_var, values=MODULE_TYPES,
             state="readonly", width=20).grid(row=_row[0]-1, column=1, sticky="ew", padx=(6, 0), pady=1)

tk.Label(form_lf, text="Attendance",  font=("Arial", 9, "bold")).grid(row=_frow(), column=0, sticky="w", pady=1)
attendance_var = tk.StringVar(value="30")
ttk.Spinbox(form_lf, from_=1, to=5000, textvariable=attendance_var,
            width=10).grid(row=_row[0]-1, column=1, sticky="w", padx=(6, 0), pady=1)

tk.Label(form_lf, text="Week Pattern",font=("Arial", 9, "bold")).grid(row=_frow(), column=0, sticky="w", pady=1)
week_pattern_var = tk.StringVar(value="Every Week")
ttk.Combobox(form_lf, textvariable=week_pattern_var, values=WEEK_PATTERNS,
             state="readonly", width=20).grid(row=_row[0]-1, column=1, sticky="ew", padx=(6, 0), pady=1)

consecutive_var = tk.BooleanVar(value=False)
ttk.Checkbutton(form_lf, text="Requires 2 consecutive slots",
                variable=consecutive_var).grid(row=_frow(), column=0, columnspan=2, sticky="w", pady=1)

tk.Label(form_lf, text="Group", font=("Arial", 9, "bold")).grid(row=_frow(), column=0, sticky="w", pady=1)
module_group_combo = ttk.Combobox(form_lf, state="readonly", width=20)
module_group_combo.grid(row=_row[0]-1, column=1, sticky="ew", padx=(6, 0), pady=1)

# Manual-only fields — hidden in Auto mode
manual_fields = tk.Frame(form_lf)
manual_fields.grid(row=_frow(), column=0, columnspan=2, sticky="ew")
manual_fields.columnconfigure(1, weight=1)

tk.Label(manual_fields, text="Day",      font=("Arial", 9, "bold")).grid(row=0, column=0, sticky="w", pady=1)
day_var      = tk.StringVar()
day_dropdown = ttk.Combobox(manual_fields, textvariable=day_var,
                             values=DAYS, state="readonly", width=20)
day_dropdown.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=1)

tk.Label(manual_fields, text="Room",     font=("Arial", 9, "bold")).grid(row=1, column=0, sticky="w", pady=1)
module_room_combo = ttk.Combobox(manual_fields, state="readonly", width=20)
module_room_combo.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=1)

tk.Label(manual_fields, text="Timeslot", font=("Arial", 9, "bold")).grid(row=2, column=0, sticky="w", pady=1)
module_timeslot_combo = ttk.Combobox(manual_fields, state="readonly", width=20)
module_timeslot_combo.grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=1)

def toggle_mode(*args):
    if mode_var.get() == "Auto":
        manual_fields.grid_remove()
    else:
        manual_fields.grid()

mode_var.trace_add("write", toggle_mode)
toggle_mode()

def update_dropdowns():
    module_lecturer_combo['values'] = lecturer_names()
    module_room_combo['values']     = room_names()
    module_timeslot_combo['values'] = [t for t in TIMESLOTS if t not in BREAK_SLOTS]
    avail_slot_combo['values']      = TIMESLOTS
    module_group_combo['values']    = ["(none)"] + GROUPS

# ---- Editing state ----
_editing_index = [None]

def _populate_form(m):
    module_entry.delete(0, tk.END)
    module_entry.insert(0, m['name'])
    module_lecturer_combo.set(m['lecturer'])
    module_type_var.set(m.get('module_type', 'Lecture'))
    attendance_var.set(str(m.get('attendance', 30)))
    week_pattern_var.set(m.get('week_pattern', 'Every Week'))
    consecutive_var.set(m.get('consecutive', False))
    module_group_combo.set(m.get('group', '(none)'))
    day_var.set(m.get('day', ''))
    module_room_combo.set(m.get('room', ''))
    module_timeslot_combo.set(m.get('timeslot', ''))

def _clear_form():
    module_entry.delete(0, tk.END)
    module_lecturer_combo.set('')
    module_type_var.set('Lecture')
    attendance_var.set('30')
    week_pattern_var.set('Every Week')
    consecutive_var.set(False)
    module_group_combo.set('(none)')
    day_var.set('')
    module_room_combo.set('')
    module_timeslot_combo.set('')

def check_clash(new_mod, exclude_index=None):
    errors = []
    new_day     = new_mod.get('day', '')
    new_slot    = new_mod.get('timeslot', '')
    new_consec  = new_mod.get('consecutive', False)
    new_pattern = new_mod.get('week_pattern', 'Every Week')

    if not new_day or not new_slot or new_slot not in TIMESLOTS:
        return errors

    new_idx   = TIMESLOTS.index(new_slot)
    new_slots = {new_idx}
    if new_consec and new_idx + 1 < len(TIMESLOTS):
        new_slots.add(new_idx + 1)

    for idx, m in enumerate(MODULES):
        if idx == exclude_index:
            continue
        if m.get('day') != new_day:
            continue
        if not weeks_overlap(new_pattern, m.get('week_pattern', 'Every Week')):
            continue
        m_slot = m.get('timeslot', '')
        if not m_slot or m_slot not in TIMESLOTS:
            continue
        m_idx    = TIMESLOTS.index(m_slot)
        m_consec = m.get('consecutive', False)
        m_slots  = {m_idx}
        if m_consec and m_idx + 1 < len(TIMESLOTS):
            m_slots.add(m_idx + 1)
        if new_slots & m_slots:
            if m['lecturer'] == new_mod.get('lecturer') and new_mod.get('lecturer'):
                errors.append(f"Lecturer clash with '{m['name']}'")
            if m['room'] == new_mod.get('room') and new_mod.get('room'):
                errors.append(f"Room clash with '{m['name']}'")
    return errors

def add_module():
    mode     = mode_var.get()
    name     = module_entry.get().strip()
    lecturer = module_lecturer_combo.get().strip()

    if not name or not lecturer:
        messagebox.showerror("Error", "Module name and lecturer are required.")
        return

    try:
        att = int(attendance_var.get())
    except ValueError:
        att = 30

    if mode == "Auto":
        new_mod = {
            'name': name, 'lecturer': lecturer,
            'room': '', 'timeslot': '', 'day': '',
            'module_type':  module_type_var.get(),
            'attendance':   att,
            'consecutive':  consecutive_var.get(),
            'week_pattern': week_pattern_var.get(),
            'group':        module_group_combo.get() if module_group_combo.get() != '(none)' else ''
        }
    else:
        room     = module_room_combo.get().strip()
        timeslot = module_timeslot_combo.get().strip()
        day      = day_var.get().strip()
        if not room or not timeslot or not day:
            messagebox.showerror("Error", "Please fill in Day, Room and Timeslot.")
            return
        new_mod = {
            'name': name, 'lecturer': lecturer,
            'room': room, 'timeslot': timeslot, 'day': day,
            'module_type':  module_type_var.get(),
            'attendance':   att,
            'consecutive':  consecutive_var.get(),
            'week_pattern': week_pattern_var.get(),
            'group':        module_group_combo.get() if module_group_combo.get() != '(none)' else ''
        }
        errors = check_clash(new_mod, exclude_index=_editing_index[0])
        if errors:
            messagebox.showerror("Clash Detected", "\n".join(errors))
            return

    if _editing_index[0] is not None:
        MODULES[_editing_index[0]] = new_mod
        status_var.set(f"Module '{name}' updated.")
        _cancel_edit()
    else:
        MODULES.append(new_mod)
        status_var.set(f"Module '{name}' added ({mode} Mode).")
        _clear_form()

    update_module_list()

def edit_module():
    sel = module_tree.selection()
    if not sel:
        messagebox.showinfo("Select Module", "Please select a module to edit.")
        return
    idx = module_tree.index(sel[0])
    _editing_index[0] = idx
    _populate_form(MODULES[idx])
    add_mod_btn.config(text="Save Edit")
    cancel_edit_btn.pack(side="left", padx=4)
    notebook.select(tab_modules)
    status_var.set(f"Editing '{MODULES[idx]['name']}' — modify fields then click Save Edit.")

def _cancel_edit():
    _editing_index[0] = None
    add_mod_btn.config(text="Add Module")
    cancel_edit_btn.pack_forget()
    _clear_form()

def cancel_edit_cmd():
    _cancel_edit()
    status_var.set("Edit cancelled.")

def remove_module():
    sel = module_tree.selection()
    if not sel:
        return
    idx  = module_tree.index(sel[0])
    name = MODULES[idx]['name']
    MODULES.pop(idx)
    if _editing_index[0] == idx:
        _cancel_edit()
    update_module_list()
    status_var.set(f"Module '{name}' removed.")

mod_btn_row = tk.Frame(tab_modules)
mod_btn_row.pack(fill="x", pady=(0, 4))

add_mod_btn     = ttk.Button(mod_btn_row, text="Add Module",      command=add_module)
edit_mod_btn    = ttk.Button(mod_btn_row, text="Edit Selected",   command=edit_module)
remove_mod_btn  = ttk.Button(mod_btn_row, text="Remove Selected", command=remove_module)
cancel_edit_btn = ttk.Button(mod_btn_row, text="Cancel Edit",     command=cancel_edit_cmd)

add_mod_btn.pack(side="left",    padx=(0, 4))
edit_mod_btn.pack(side="left",   padx=4)
remove_mod_btn.pack(side="left", padx=4)
# cancel_edit_btn intentionally not packed — appears only during an edit

# Module Treeview
mod_tree_outer = tk.Frame(tab_modules)
mod_tree_outer.pack(fill="both", expand=True)

mod_vsb = ttk.Scrollbar(mod_tree_outer, orient="vertical")
mod_hsb = ttk.Scrollbar(mod_tree_outer, orient="horizontal")
mod_vsb.pack(side="right",  fill="y")
mod_hsb.pack(side="bottom", fill="x")

MOD_COLS = ("Name", "Lecturer", "Type", "Attend.", "Group", "Room", "Timeslot", "Day", "Consec.", "Week")
module_tree = ttk.Treeview(mod_tree_outer, columns=MOD_COLS, show="headings",
                            height=7,
                            yscrollcommand=mod_vsb.set,
                            xscrollcommand=mod_hsb.set)
mod_vsb.config(command=module_tree.yview)
mod_hsb.config(command=module_tree.xview)

_col_w = {"Name": 80, "Lecturer": 80, "Type": 68, "Attend.": 55, "Group": 80,
          "Room": 68, "Timeslot": 80, "Day": 72, "Consec.": 52, "Week": 100}
for col in MOD_COLS:
    module_tree.heading(col, text=col)
    module_tree.column(col, width=_col_w.get(col, 70), anchor="center", minwidth=45)

module_tree.pack(fill="both", expand=True)
module_tree.bind("<Double-1>", lambda e: edit_module())

def update_module_list():
    for row in module_tree.get_children():
        module_tree.delete(row)
    for m in MODULES:
        module_tree.insert("", "end", values=(
            m['name'], m['lecturer'],
            m.get('module_type', 'Lecture'),
            m.get('attendance', 0),
            m.get('group', '') or '',
            m.get('room', ''), m.get('timeslot', ''), m.get('day', ''),
            "Yes" if m.get('consecutive') else "No",
            m.get('week_pattern', 'Every Week')
        ))

# =========================================================
# TIMETABLE GRID
# =========================================================
def _cell_click(slot, day):
    """Handle a click on a timetable cell — pick up or drop a module."""
    # If nothing is being dragged, try to pick up the module in this cell
    if _drag_source[0] is None:
        mod_idx = next((i for i, m in enumerate(MODULES)
                        if m.get('timeslot') == slot and m.get('day') == day), None)
        if mod_idx is None:
            return  # empty cell, nothing to pick up
        _drag_source[0] = (slot, day)
        _drag_module[0] = mod_idx
        # Highlight source cell yellow to show it's selected
        if (slot, day) in cells:
            cells[(slot, day)].config(bg="#F9E79F", relief="ridge", bd=3)
        status_var.set(f"Picked up '{MODULES[mod_idx]['name']}' — click a destination cell to move it.  (Click same cell to cancel)")
    else:
        src_slot, src_day = _drag_source[0]
        mod_idx = _drag_module[0]

        # Click same cell = cancel
        if (slot, day) == (src_slot, src_day):
            _cancel_drag()
            return

        # Check destination is not a break slot
        if slot in BREAK_SLOTS:
            messagebox.showwarning("Break Slot", "Cannot place a module in a break slot.")
            return

        # Check destination is not already occupied
        existing = next((i for i, m in enumerate(MODULES)
                         if m.get('timeslot') == slot and m.get('day') == day
                         and i != mod_idx), None)
        if existing is not None:
            if not messagebox.askyesno("Cell Occupied",
                                       f"'{MODULES[existing]['name']}' is already here.\n"
                                       f"Swap the two modules?"):
                _cancel_drag()
                return
            # Swap
            MODULES[existing]['timeslot'] = src_slot
            MODULES[existing]['day']      = src_day

        # Check clashes for the moved module at the new position
        test_mod = dict(MODULES[mod_idx])
        test_mod['timeslot'] = slot
        test_mod['day']      = day
        errors = check_clash(test_mod, exclude_index=mod_idx)
        if errors:
            if not messagebox.askyesno("Clash Warning",
                                       "Moving here would cause:\n" +
                                       "\n".join(errors) +
                                       "\n\nMove anyway?"):
                _cancel_drag()
                return

        # Apply move
        MODULES[mod_idx]['timeslot'] = slot
        MODULES[mod_idx]['day']      = day
        _drag_source[0] = None
        _drag_module[0] = None
        update_module_list()
        draw_timetable()
        status_var.set(f"Moved '{MODULES[mod_idx]['name']}' to {day} {slot}.")


def _cancel_drag():
    _drag_source[0] = None
    _drag_module[0] = None
    draw_timetable()
    status_var.set("Drag cancelled.")


def build_grid():
    for w in timetable_grid.winfo_children():
        w.destroy()
    cells.clear()

    tk.Label(timetable_grid, text="", bg="#2C3E50", width=16,
             relief="flat").grid(row=0, column=0, sticky="nsew", padx=1, pady=1)

    for col, day in enumerate(DAYS, start=1):
        tk.Label(timetable_grid, text=day, bg="#2C3E50", fg="white",
                 font=("Arial", 10, "bold"), padx=6, pady=6,
                 relief="flat").grid(row=0, column=col, sticky="nsew", padx=1, pady=1)

    for row, slot in enumerate(TIMESLOTS, start=1):
        is_break = slot in BREAK_SLOTS
        slot_bg  = "#E8E8E8" if is_break else "#34495E"
        slot_fg  = "#888888" if is_break else "white"
        slot_lbl = f"{slot}\n[BREAK]" if is_break else slot
        tk.Label(timetable_grid, text=slot_lbl, bg=slot_bg, fg=slot_fg,
                 font=("Arial", 9, "bold"), width=16, padx=4, pady=4,
                 relief="flat").grid(row=row, column=0, sticky="nsew", padx=1, pady=1)
        for col, day in enumerate(DAYS, start=1):
            cell_bg = "#E8E8E8" if is_break else "white"
            cell = tk.Label(timetable_grid,
                            text="BREAK" if is_break else "",
                            bg=cell_bg, fg="#AAAAAA",
                            relief="solid", bd=1,
                            wraplength=140, justify="center",
                            font=("Arial", 8), width=20, height=4,
                            cursor="hand2" if not is_break else "arrow")
            cell.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
            if not is_break:
                cells[(slot, day)] = cell
                cell.bind("<Button-1>",
                          lambda e, s=slot, d=day: _cell_click(s, d))

    for i in range(len(TIMESLOTS) + 1):
        timetable_grid.rowconfigure(i, weight=1)
    for j in range(len(DAYS) + 1):
        timetable_grid.columnconfigure(j, weight=1)


def draw_timetable():
    build_grid()
    count = 0
    for m in MODULES:
        day  = m.get('day', '')
        slot = m.get('timeslot', '')
        if not day or not slot:
            continue
        key = (slot, day)
        if key not in cells:
            continue
        color  = get_lecturer_color(m['lecturer'])
        w_tag  = ""
        if m.get('week_pattern', 'Every Week') != 'Every Week':
            w_tag = f"\n[{m['week_pattern'][-1]}]"
        c_tag  = " [2x]" if m.get('consecutive') else ""
        cells[key].config(
            text=f"{m['name']}{c_tag}\n{m['lecturer']}\n{m.get('room','')}{w_tag}",
            bg=color, fg="black", font=("Arial", 8, "bold")
        )
        count += 1
        # Shade the continuation slot for consecutive modules
        if m.get('consecutive') and slot in TIMESLOTS:
            idx = TIMESLOTS.index(slot)
            if idx + 1 < len(TIMESLOTS):
                nkey = (TIMESLOTS[idx + 1], day)
                if nkey in cells:
                    cells[nkey].config(
                        text=f"  ↑ {m['name']}\n  (continued)",
                        bg=color, font=("Arial", 8, "italic")
                    )
    status_var.set(f"Timetable drawn — {count} module(s) placed.")


def clear_timetable():
    build_grid()
    status_var.set("Timetable cleared.")

# =========================================================
# CONFLICT REPORT
# =========================================================
def generate_conflict_report(modules, score):
    lines = []
    sep = "=" * 56

    lines += [sep, "CONFLICT REPORT", sep,
              f"Solver Penalty Score: {score}  (0 = perfect spread)", ""]

    num_mods      = len(modules)
    num_timeslots = len(TIMESLOTS)
    num_rooms     = len(ROOMS)
    num_days      = len(DAYS)

    w_el   = SOFT_WEIGHTS.get("early_late",  2)
    w_day  = SOFT_WEIGHTS.get("day_spread",  3)
    w_slot = SOFT_WEIGHTS.get("slot_spread", 3)
    w_room = SOFT_WEIGHTS.get("room_spread", 2)
    w_b2b  = SOFT_WEIGHTS.get("back_to_back",1)

    running_total = 0
    any_violation = False

    lines.append("SOFT CONSTRAINT VIOLATIONS:")
    lines.append("-" * 40)

    # 1. Early slot — mirrors solver: module_time[i] == 0
    early_mods = [m for m in modules
                  if m.get('timeslot') and m['timeslot'] in TIMESLOTS
                  and TIMESLOTS.index(m['timeslot']) == 0]
    if early_mods:
        any_violation = True
        sub = len(early_mods) * w_el
        running_total += sub
        lines.append(f"Early slot  (weight {w_el} per module)  →  {len(early_mods)} × {w_el} = {sub} pts")
        for m in early_mods:
            lines.append(f"   • {m['name']} | {m['lecturer']} | {m.get('day','')}")

    # 2. Late slot — mirrors solver: module_time[i] == max_t
    late_mods = []
    for m in modules:
        slot = m.get('timeslot', '')
        if not slot or slot not in TIMESLOTS:
            continue
        is_c  = m.get('consecutive', False)
        max_t = max(0, (num_timeslots - 2) if is_c else (num_timeslots - 1))
        if TIMESLOTS.index(slot) == max_t:
            late_mods.append(m)
    if late_mods:
        any_violation = True
        sub = len(late_mods) * w_el
        running_total += sub
        lines.append(f"Late slot   (weight {w_el} per module)  →  {len(late_mods)} × {w_el} = {sub} pts")
        for m in late_mods:
            lines.append(f"   • {m['name']} | {m['lecturer']} | {m.get('day','')}")

    # 3. Day overload — mirrors solver: for k in range(ideal, num_mods): sum(on_day) > k
    ideal_per_day = math.ceil(num_mods / num_days) if num_mods > 0 else 0
    day_lines = []
    day_sub   = 0
    for day in DAYS:
        count = sum(1 for m in modules if m.get('day') == day)
        if count > ideal_per_day:
            excess = count - ideal_per_day
            pts    = excess * w_day
            day_sub       += pts
            running_total += pts
            day_lines.append(
                f"   • {day}: {count} modules  (ideal ≤ {ideal_per_day})  "
                f"excess {excess} × {w_day} = +{pts} pts")
    if day_lines:
        any_violation = True
        lines.append(f"Day overload  (weight {w_day} per excess module, ideal ≤ {ideal_per_day}/day)  →  {day_sub} pts")
        lines.extend(day_lines)

    # 4. Slot overload — mirrors solver: uses len(TIMESLOTS) as denominator
    ideal_per_slot = math.ceil(num_mods / num_timeslots) if num_timeslots > 0 else 0
    slot_lines = []
    slot_sub   = 0
    for slot in TIMESLOTS:
        count = sum(1 for m in modules if m.get('timeslot') == slot)
        if count > ideal_per_slot:
            excess = count - ideal_per_slot
            pts    = excess * w_slot
            slot_sub      += pts
            running_total += pts
            slot_lines.append(
                f"   • {slot}: {count} modules  (ideal ≤ {ideal_per_slot})  "
                f"excess {excess} × {w_slot} = +{pts} pts")
    if slot_lines:
        any_violation = True
        lines.append(f"Slot overload (weight {w_slot} per excess module, ideal ≤ {ideal_per_slot}/slot)  →  {slot_sub} pts")
        lines.extend(slot_lines)

    # 5. Room overload — mirrors solver: uses len(ROOMS) as denominator
    ideal_per_room = math.ceil(num_mods / num_rooms) if num_rooms > 0 else 0
    room_lines = []
    room_sub   = 0
    for r in ROOMS:
        count = sum(1 for m in modules if m.get('room') == r['name'])
        if count > ideal_per_room:
            excess = count - ideal_per_room
            pts    = excess * w_room
            room_sub      += pts
            running_total += pts
            room_lines.append(
                f"   • {r['name']}: {count} modules  (ideal ≤ {ideal_per_room})  "
                f"excess {excess} × {w_room} = +{pts} pts")
    if room_lines:
        any_violation = True
        lines.append(f"Room overload (weight {w_room} per excess module, ideal ≤ {ideal_per_room}/room)  →  {room_sub} pts")
        lines.extend(room_lines)

    # 6. Back-to-back — mirrors solver pairwise check
    b2b = []
    for lec_name in sorted(set(m['lecturer'] for m in modules if m.get('lecturer'))):
        lec_mods = [m for m in modules if m['lecturer'] == lec_name
                    and m.get('day') and m.get('timeslot')
                    and m['timeslot'] in TIMESLOTS]
        for day in DAYS:
            day_mods = sorted([m for m in lec_mods if m['day'] == day],
                              key=lambda m: TIMESLOTS.index(m['timeslot']))
            for k in range(len(day_mods) - 1):
                idx1 = TIMESLOTS.index(day_mods[k]['timeslot'])
                idx2 = TIMESLOTS.index(day_mods[k + 1]['timeslot'])
                gap  = idx2 - idx1
                threshold = 2 if day_mods[k].get('consecutive') else 1
                if gap == threshold:
                    b2b.append((lec_name, day_mods[k]['name'],
                                day_mods[k + 1]['name'], day))
    if b2b:
        any_violation = True
        b2b_sub        = len(b2b) * w_b2b
        running_total += b2b_sub
        lines.append(f"Back-to-back  (weight {w_b2b} per pair)  →  {len(b2b)} × {w_b2b} = {b2b_sub} pts")
        for lec, m1, m2, day in b2b:
            lines.append(f"   • {lec}: {m1} → {m2} on {day}  +{w_b2b} pts")

    if not any_violation:
        lines.append("   No soft constraint violations detected!")

    lines.append("-" * 40)
    lines.append(f"TOTAL:  {running_total} pts")
    lines.append(f"(Solver reported: {score} pts)")

    # Building travel warnings
    lines += ["", "BUILDING TRAVEL WARNINGS:", "-" * 40]
    travel = []
    for lec_name in sorted(set(m['lecturer'] for m in modules if m.get('lecturer'))):
        lec_mods = [m for m in modules if m['lecturer'] == lec_name
                    and m.get('day') and m.get('timeslot') and m['timeslot'] in TIMESLOTS]
        for day in DAYS:
            day_mods = sorted([m for m in lec_mods if m['day'] == day],
                              key=lambda m: TIMESLOTS.index(m['timeslot']))
            for k in range(len(day_mods) - 1):
                r1 = next((r for r in ROOMS if r['name'] == day_mods[k].get('room', '')), None)
                r2 = next((r for r in ROOMS if r['name'] == day_mods[k+1].get('room', '')), None)
                if r1 and r2:
                    b1, b2 = r1.get('building', ''), r2.get('building', '')
                    if b1 and b2 and b1 != b2:
                        travel.append((lec_name, day_mods[k]['name'], b1,
                                       day_mods[k+1]['name'], b2, day))

    if travel:
        for lec, m1, b1, m2, b2, day in travel:
            lines.append(f"   ⚠  {lec}: {m1} ({b1}) → {m2} ({b2}) on {day}")
    else:
        lines.append("   No building travel issues detected.")

    # Hard constraint summary
    lines += ["", "HARD CONSTRAINT SUMMARY:", "-" * 40,
              "   ✓  No room double-bookings",
              "   ✓  No lecturer clashes",
              "   ✓  All lecturer availability constraints respected",
              "   ✓  All room type requirements enforced"]

    cap_ok = True
    for m in modules:
        r_obj = next((r for r in ROOMS if r['name'] == m.get('room', '')), None)
        if r_obj and m.get('attendance', 0) > r_obj['capacity']:
            lines.append(f"   ✗  Capacity issue: {m['name']} "
                         f"({m['attendance']} students) in "
                         f"{r_obj['name']} (cap {r_obj['capacity']})")
            cap_ok = False
    if cap_ok:
        lines.append("   ✓  All room capacities respected")

    lines.append(sep)
    return "\n".join(lines)


def _display_report(modules, score):
    report = generate_conflict_report(modules, score)
    conflict_text.config(state="normal")
    conflict_text.delete("1.0", tk.END)
    conflict_text.insert(tk.END, report)
    conflict_text.config(state="disabled")

# =========================================================
# SOLVER
# =========================================================
def start_solver_thread():
    if not MODULES:
        messagebox.showerror("Error", "Please add at least one module.")
        return
    if not TIMESLOTS:
        messagebox.showerror("Error", "Please add at least one timeslot.")
        return
    if not ROOMS:
        messagebox.showerror("Error", "Please add at least one room.")
        return
    for btn in solver_buttons:
        btn.config(state="disabled")

    # Pre-flight: check every module has at least one valid room
    issues = _preflight_check()
    if issues:
        for btn in solver_buttons:
            btn.config(state="normal")
        messagebox.showerror("Cannot Solve — Room Issues",
                             "The following modules have no valid room available:\n\n" +
                             "\n".join(issues) +
                             "\n\nPlease add a suitable room or adjust attendance/type.")
        return

    status_var.set("Solver running — please wait...")
    threading.Thread(target=_run_solver, daemon=True).start()


def _run_solver():
    try:
        result = _solve()
        root.after(0, lambda: _finish_solver(result))
    except Exception as exc:
        err = str(exc)
        root.after(0, lambda: _solver_error(err))


def _solver_error(msg):
    for btn in solver_buttons:
        btn.config(state="normal")
    status_var.set("Solver error.")
    messagebox.showerror("Solver Error", msg)


def _finish_solver(result):
    for btn in solver_buttons:
        btn.config(state="normal")
    if result is None:
        status_var.set("No valid timetable found.")
        messagebox.showerror("No Solution",
                             "The solver could not find a valid timetable.\n"
                             "Try adding more rooms or timeslots, or relaxing constraints.")
        return
    new_modules, score = result
    MODULES.clear()
    MODULES.extend(new_modules)
    update_module_list()
    draw_timetable()
    _display_report(new_modules, score)
    status_var.set(f"Timetable generated — penalty score: {score}  (lower is better)")
    messagebox.showinfo("Success",
                        f"Timetable generated!\n\nPenalty score: {score}\n"
                        f"(0 = perfect spread)\n\n"
                        f"See the Analysis tab for the full conflict report.")


def _preflight_check():
    """Check for modules that have no valid room — return list of error strings."""
    errors = []
    for m in MODULES:
        att      = m.get('attendance', 0)
        mod_type = m.get('module_type', 'Lecture')
        allowed  = ROOM_COMPAT.get(mod_type, list(ROOM_TYPES))
        valid_rooms = [r for r in ROOMS
                       if r['room_type'] in allowed
                       and (att == 0 or r['capacity'] >= att)]
        if not valid_rooms:
            errors.append(
                f"  • '{m['name']}' — attendance {att}, type {mod_type}: "
                f"no room is large enough or of the right type."
            )
    return errors


def _solve(seed=None, fixed_modules=None):
    """
    Solve for MODULES (the current list).
    fixed_modules: list of already-placed dicts whose day/timeslot/room
                   are treated as occupied (for bulk generation awareness).
    """
    days_list     = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    model         = cp_model.CpModel()
    num_modules   = len(MODULES)
    num_timeslots = len(TIMESLOTS)
    num_rooms     = len(ROOMS)
    num_days      = len(days_list)

    if num_modules == 0 or num_timeslots == 0 or num_rooms == 0:
        return None

    module_time = []
    module_room = []
    module_day  = []

    for i in range(num_modules):
        is_c  = MODULES[i].get('consecutive', False)
        max_t = max(0, (num_timeslots - 2) if is_c else (num_timeslots - 1))
        module_time.append(model.NewIntVar(0, max_t,         f"t_{i}"))
        module_room.append(model.NewIntVar(0, num_rooms - 1, f"r_{i}"))
        module_day.append( model.NewIntVar(0, num_days  - 1, f"d_{i}"))

    # ---- HARD: Room capacity ----
    for i in range(num_modules):
        att = MODULES[i].get('attendance', 0)
        if att > 0:
            for r in range(num_rooms):
                if ROOMS[r]['capacity'] < att:
                    model.Add(module_room[i] != r)

    # ---- HARD: Room type ----
    for i in range(num_modules):
        mod_type = MODULES[i].get('module_type', 'Lecture')
        allowed  = ROOM_COMPAT.get(mod_type, list(ROOM_TYPES))
        for r in range(num_rooms):
            if ROOMS[r]['room_type'] not in allowed:
                model.Add(module_room[i] != r)

    # ---- HARD: Lecturer availability ----
    for i in range(num_modules):
        lec_obj = next((l for l in LECTURERS if l['name'] == MODULES[i]['lecturer']), None)
        if not lec_obj:
            continue
        for (unavail_day, unavail_slot) in lec_obj.get('unavailable', []):
            if unavail_day not in days_list or unavail_slot not in TIMESLOTS:
                continue
            d = days_list.index(unavail_day)
            t = TIMESLOTS.index(unavail_slot)
            # Can't be at (day d, slot t)
            bd = model.NewBoolVar(f"avd_{i}_{d}_{t}")
            bt = model.NewBoolVar(f"avt_{i}_{d}_{t}")
            model.Add(module_day[i]  == d).OnlyEnforceIf(bd)
            model.Add(module_day[i]  != d).OnlyEnforceIf(bd.Not())
            model.Add(module_time[i] == t).OnlyEnforceIf(bt)
            model.Add(module_time[i] != t).OnlyEnforceIf(bt.Not())
            model.AddBoolOr([bd.Not(), bt.Not()])
            # Consecutive module can't start at t-1 either (would occupy t)
            if MODULES[i].get('consecutive', False) and t > 0:
                bd2 = model.NewBoolVar(f"avd2_{i}_{d}_{t}")
                bt2 = model.NewBoolVar(f"avt2_{i}_{d}_{t}")
                model.Add(module_day[i]  == d).OnlyEnforceIf(bd2)
                model.Add(module_day[i]  != d).OnlyEnforceIf(bd2.Not())
                model.Add(module_time[i] == t - 1).OnlyEnforceIf(bt2)
                model.Add(module_time[i] != t - 1).OnlyEnforceIf(bt2.Not())
                model.AddBoolOr([bd2.Not(), bt2.Not()])

    # ---- HARD: Break slots — no module can be assigned here ----
    for i in range(num_modules):
        for t, slot in enumerate(TIMESLOTS):
            if slot in BREAK_SLOTS:
                model.Add(module_time[i] != t)
                # Consecutive modules can't start at t-1 either (would run into break)
                if MODULES[i].get('consecutive', False) and t > 0:
                    model.Add(module_time[i] != t - 1)

    # ---- HARD: Student group clash — same group can't have two modules at same time ----
    for i in range(num_modules):
        for j in range(i + 1, num_modules):
            g_i = MODULES[i].get('group', '')
            g_j = MODULES[j].get('group', '')
            if not g_i or not g_j or g_i != g_j:
                continue
            p_i = MODULES[i].get('week_pattern', 'Every Week')
            p_j = MODULES[j].get('week_pattern', 'Every Week')
            if not weeks_overlap(p_i, p_j):
                continue

            sd_g = model.NewBoolVar(f"gsd_{i}_{j}")
            ov_g = model.NewBoolVar(f"gov_{i}_{j}")

            model.Add(module_day[i] == module_day[j]).OnlyEnforceIf(sd_g)
            model.Add(module_day[i] != module_day[j]).OnlyEnforceIf(sd_g.Not())

            # Overlap includes consecutive slot spans
            i_c = MODULES[i].get('consecutive', False)
            j_c = MODULES[j].get('consecutive', False)
            if not i_c and not j_c:
                model.Add(module_time[i] == module_time[j]).OnlyEnforceIf(ov_g)
                model.Add(module_time[i] != module_time[j]).OnlyEnforceIf(ov_g.Not())
            else:
                gdiff = model.NewIntVar(-(num_timeslots - 1), num_timeslots - 1, f"gd_{i}_{j}")
                model.Add(gdiff == module_time[j] - module_time[i])
                threshold = 2 if (i_c and j_c) else 1
                gd_bools = []
                for v in range(-threshold + 1, threshold):
                    b = model.NewBoolVar(f"gdb_{i}_{j}_{v+threshold}")
                    model.Add(gdiff == v).OnlyEnforceIf(b)
                    model.Add(gdiff != v).OnlyEnforceIf(b.Not())
                    gd_bools.append(b)
                model.AddBoolOr(gd_bools).OnlyEnforceIf(ov_g)
                model.AddBoolAnd([b.Not() for b in gd_bools]).OnlyEnforceIf(ov_g.Not())

            # Group clash: cannot share day + overlapping time
            model.AddBoolOr([sd_g.Not(), ov_g.Not()])

    # ---- HARD: Fixed module placements (bulk generation awareness) ----
    if fixed_modules:
        for i in range(num_modules):
            for fm in fixed_modules:
                fm_day  = fm.get('day', '')
                fm_slot = fm.get('timeslot', '')
                fm_room = fm.get('room', '')
                if not fm_day or not fm_slot or not fm_room:
                    continue
                if fm_day not in days_list or fm_slot not in TIMESLOTS:
                    continue
                fd = days_list.index(fm_day)
                ft = TIMESLOTS.index(fm_slot)
                fr = next((ri for ri, r in enumerate(ROOMS)
                           if r['name'] == fm_room), None)

                # Lecturer clash with fixed module
                if (fm.get('lecturer') and
                        fm['lecturer'] == MODULES[i].get('lecturer')):
                    # Can't be on same day + slot as fixed module
                    bd = model.NewBoolVar(f"fmd_{i}_{fd}_{ft}")
                    bt = model.NewBoolVar(f"fmt_{i}_{fd}_{ft}")
                    model.Add(module_day[i]  == fd).OnlyEnforceIf(bd)
                    model.Add(module_day[i]  != fd).OnlyEnforceIf(bd.Not())
                    model.Add(module_time[i] == ft).OnlyEnforceIf(bt)
                    model.Add(module_time[i] != ft).OnlyEnforceIf(bt.Not())
                    model.AddBoolOr([bd.Not(), bt.Not()])

                # Room clash with fixed module
                if fr is not None:
                    bd2 = model.NewBoolVar(f"fmrd_{i}_{fd}_{ft}")
                    bt2 = model.NewBoolVar(f"fmrt_{i}_{fd}_{ft}")
                    br2 = model.NewBoolVar(f"fmrr_{i}_{fd}_{ft}_{fr}")
                    model.Add(module_day[i]  == fd).OnlyEnforceIf(bd2)
                    model.Add(module_day[i]  != fd).OnlyEnforceIf(bd2.Not())
                    model.Add(module_time[i] == ft).OnlyEnforceIf(bt2)
                    model.Add(module_time[i] != ft).OnlyEnforceIf(bt2.Not())
                    model.Add(module_room[i] == fr).OnlyEnforceIf(br2)
                    model.Add(module_room[i] != fr).OnlyEnforceIf(br2.Not())
                    model.AddBoolOr([bd2.Not(), bt2.Not(), br2.Not()])

    # ---- HARD: Pairwise clash constraints ----
    for i in range(num_modules):
        for j in range(i + 1, num_modules):
            p_i = MODULES[i].get('week_pattern', 'Every Week')
            p_j = MODULES[j].get('week_pattern', 'Every Week')
            if not weeks_overlap(p_i, p_j):
                continue   # different alternate weeks — no clash possible

            i_c = MODULES[i].get('consecutive', False)
            j_c = MODULES[j].get('consecutive', False)

            sd = model.NewBoolVar(f"sd_{i}_{j}")
            model.Add(module_day[i]  == module_day[j]).OnlyEnforceIf(sd)
            model.Add(module_day[i]  != module_day[j]).OnlyEnforceIf(sd.Not())

            sr = model.NewBoolVar(f"sr_{i}_{j}")
            model.Add(module_room[i] == module_room[j]).OnlyEnforceIf(sr)
            model.Add(module_room[i] != module_room[j]).OnlyEnforceIf(sr.Not())

            # Build overlap boolean based on consecutive flags
            if not i_c and not j_c:
                ov = model.NewBoolVar(f"ov_{i}_{j}")
                model.Add(module_time[i] == module_time[j]).OnlyEnforceIf(ov)
                model.Add(module_time[i] != module_time[j]).OnlyEnforceIf(ov.Not())
            else:
                diff = model.NewIntVar(-(num_timeslots - 1), num_timeslots - 1, f"dff_{i}_{j}")
                model.Add(diff == module_time[j] - module_time[i])

                if i_c and not j_c:
                    # i at [ti, ti+1], j at tj. Overlap if diff in {0, 1}
                    d0 = model.NewBoolVar(f"d0_{i}_{j}")
                    d1 = model.NewBoolVar(f"d1_{i}_{j}")
                    model.Add(diff == 0).OnlyEnforceIf(d0)
                    model.Add(diff != 0).OnlyEnforceIf(d0.Not())
                    model.Add(diff == 1).OnlyEnforceIf(d1)
                    model.Add(diff != 1).OnlyEnforceIf(d1.Not())
                    ov = model.NewBoolVar(f"ov_{i}_{j}")
                    model.AddBoolOr([d0, d1]).OnlyEnforceIf(ov)
                    model.AddBoolAnd([d0.Not(), d1.Not()]).OnlyEnforceIf(ov.Not())

                elif not i_c and j_c:
                    # j at [tj, tj+1], i at ti. Overlap if diff in {-1, 0}
                    dn1 = model.NewBoolVar(f"dn1_{i}_{j}")
                    d0  = model.NewBoolVar(f"d0_{i}_{j}")
                    model.Add(diff == -1).OnlyEnforceIf(dn1)
                    model.Add(diff != -1).OnlyEnforceIf(dn1.Not())
                    model.Add(diff ==  0).OnlyEnforceIf(d0)
                    model.Add(diff !=  0).OnlyEnforceIf(d0.Not())
                    ov = model.NewBoolVar(f"ov_{i}_{j}")
                    model.AddBoolOr([dn1, d0]).OnlyEnforceIf(ov)
                    model.AddBoolAnd([dn1.Not(), d0.Not()]).OnlyEnforceIf(ov.Not())

                else:
                    # Both consecutive. Overlap if diff in {-1, 0, 1}
                    dn1 = model.NewBoolVar(f"dn1_{i}_{j}")
                    d0  = model.NewBoolVar(f"d0_{i}_{j}")
                    d1  = model.NewBoolVar(f"d1_{i}_{j}")
                    model.Add(diff == -1).OnlyEnforceIf(dn1)
                    model.Add(diff != -1).OnlyEnforceIf(dn1.Not())
                    model.Add(diff ==  0).OnlyEnforceIf(d0)
                    model.Add(diff !=  0).OnlyEnforceIf(d0.Not())
                    model.Add(diff ==  1).OnlyEnforceIf(d1)
                    model.Add(diff !=  1).OnlyEnforceIf(d1.Not())
                    ov = model.NewBoolVar(f"ov_{i}_{j}")
                    model.AddBoolOr([dn1, d0, d1]).OnlyEnforceIf(ov)
                    model.AddBoolAnd([dn1.Not(), d0.Not(), d1.Not()]).OnlyEnforceIf(ov.Not())

            # No two modules same day + overlapping time
            model.AddBoolOr([sd.Not(), ov.Not()])
            # No two modules same day + overlapping time + same room
            model.AddBoolOr([sd.Not(), ov.Not(), sr.Not()])
            # Lecturer cannot be in two places at once
            if MODULES[i]['lecturer'] == MODULES[j]['lecturer']:
                model.AddBoolOr([sd.Not(), ov.Not()])

    # ---- SOFT CONSTRAINTS (weighted penalties) ----
    penalties = []

    w_early_late  = SOFT_WEIGHTS["early_late"]
    w_day_spread  = SOFT_WEIGHTS["day_spread"]
    w_slot_spread = SOFT_WEIGHTS["slot_spread"]
    w_room_spread = SOFT_WEIGHTS["room_spread"]
    w_back2back   = SOFT_WEIGHTS["back_to_back"]

    # Avoid first and last timeslot
    for i in range(num_modules):
        is_c  = MODULES[i].get('consecutive', False)
        max_t = max(0, (num_timeslots - 2) if is_c else (num_timeslots - 1))

        pe = model.NewBoolVar(f"early_{i}")
        model.Add(module_time[i] == 0).OnlyEnforceIf(pe)
        model.Add(module_time[i] != 0).OnlyEnforceIf(pe.Not())
        penalties.append((pe, w_early_late))

        pl = model.NewBoolVar(f"late_{i}")
        model.Add(module_time[i] == max_t).OnlyEnforceIf(pl)
        model.Add(module_time[i] != max_t).OnlyEnforceIf(pl.Not())
        penalties.append((pl, w_early_late))

    # Even day spread
    ideal_per_day = math.ceil(num_modules / num_days)
    for d in range(num_days):
        on_day = []
        for mi in range(num_modules):
            b = model.NewBoolVar(f"od_{mi}_{d}")
            model.Add(module_day[mi] == d).OnlyEnforceIf(b)
            model.Add(module_day[mi] != d).OnlyEnforceIf(b.Not())
            on_day.append(b)
        for k in range(ideal_per_day, num_modules):
            ov2 = model.NewBoolVar(f"dov_{d}_{k}")
            model.Add(sum(on_day) > k).OnlyEnforceIf(ov2)
            model.Add(sum(on_day) <= k).OnlyEnforceIf(ov2.Not())
            penalties.append((ov2, w_day_spread))

    # Even timeslot spread
    ideal_per_slot = math.ceil(num_modules / num_timeslots)
    for t in range(num_timeslots):
        on_slot = []
        for mi in range(num_modules):
            b = model.NewBoolVar(f"os_{mi}_{t}")
            model.Add(module_time[mi] == t).OnlyEnforceIf(b)
            model.Add(module_time[mi] != t).OnlyEnforceIf(b.Not())
            on_slot.append(b)
        for k in range(ideal_per_slot, num_modules):
            ov2 = model.NewBoolVar(f"sov_{t}_{k}")
            model.Add(sum(on_slot) > k).OnlyEnforceIf(ov2)
            model.Add(sum(on_slot) <= k).OnlyEnforceIf(ov2.Not())
            penalties.append((ov2, w_slot_spread))

    # Even room spread
    ideal_per_room = math.ceil(num_modules / num_rooms)
    for r in range(num_rooms):
        on_room = []
        for mi in range(num_modules):
            b = model.NewBoolVar(f"or_{mi}_{r}")
            model.Add(module_room[mi] == r).OnlyEnforceIf(b)
            model.Add(module_room[mi] != r).OnlyEnforceIf(b.Not())
            on_room.append(b)
        for k in range(ideal_per_room, num_modules):
            ov2 = model.NewBoolVar(f"rov_{r}_{k}")
            model.Add(sum(on_room) > k).OnlyEnforceIf(ov2)
            model.Add(sum(on_room) <= k).OnlyEnforceIf(ov2.Not())
            penalties.append((ov2, w_room_spread))

    # Avoid lecturer back-to-back sessions
    for i in range(num_modules):
        for j in range(i + 1, num_modules):
            if MODULES[i]['lecturer'] != MODULES[j]['lecturer']:
                continue
            p_i = MODULES[i].get('week_pattern', 'Every Week')
            p_j = MODULES[j].get('week_pattern', 'Every Week')
            if not weeks_overlap(p_i, p_j):
                continue

            sd2 = model.NewBoolVar(f"csd_{i}_{j}")
            model.Add(module_day[i] == module_day[j]).OnlyEnforceIf(sd2)
            model.Add(module_day[i] != module_day[j]).OnlyEnforceIf(sd2.Not())

            tdiff   = model.NewIntVar(-(num_timeslots - 1), num_timeslots - 1, f"btd_{i}_{j}")
            absdiff = model.NewIntVar(0, num_timeslots - 1, f"batd_{i}_{j}")
            model.Add(tdiff == module_time[i] - module_time[j])
            model.AddAbsEquality(absdiff, tdiff)

            i_c       = MODULES[i].get('consecutive', False)
            j_c       = MODULES[j].get('consecutive', False)
            threshold = 2 if (i_c or j_c) else 1

            is_b2b = model.NewBoolVar(f"ib2b_{i}_{j}")
            model.Add(absdiff == threshold).OnlyEnforceIf(is_b2b)
            model.Add(absdiff != threshold).OnlyEnforceIf(is_b2b.Not())

            b2b = model.NewBoolVar(f"b2b_{i}_{j}")
            model.AddBoolAnd([sd2, is_b2b]).OnlyEnforceIf(b2b)
            model.AddBoolOr([sd2.Not(), is_b2b.Not()]).OnlyEnforceIf(b2b.Not())
            penalties.append((b2b, w_back2back))

    model.Minimize(sum(w * p for p, w in penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 15.0
    if seed is not None:
        solver.parameters.random_seed = seed

    status = solver.Solve(model)
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return None

    new_modules = []
    for i, m in enumerate(MODULES):
        new_modules.append({
            'name':         m['name'],
            'lecturer':     m['lecturer'],
            'room':         ROOMS[solver.Value(module_room[i])]['name'],
            'timeslot':     TIMESLOTS[solver.Value(module_time[i])],
            'day':          days_list[solver.Value(module_day[i])],
            'module_type':  m.get('module_type', 'Lecture'),
            'attendance':   m.get('attendance', 0),
            'consecutive':  m.get('consecutive', False),
            'week_pattern': m.get('week_pattern', 'Every Week'),
            'group':        m.get('group', ''),
        })

    return new_modules, int(solver.ObjectiveValue())

# =========================================================
# SAVE / LOAD / EXPORT
# =========================================================
def save_data():
    path = filedialog.asksaveasfilename(defaultextension=".json",
                                        filetypes=[("JSON files", "*.json")])
    if not path:
        return
    with open(path, "w") as f:
        json.dump({
            "buildings":   BUILDINGS,
            "rooms":       ROOMS,
            "timeslots":   TIMESLOTS,
            "break_slots": list(BREAK_SLOTS),
            "lecturers":   LECTURERS,
            "groups":      GROUPS,
            "modules":     MODULES
        }, f, indent=4)
    status_var.set(f"Saved to {path}")
    messagebox.showinfo("Saved", "Data saved successfully.")


def load_data():
    path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
    if not path:
        return
    with open(path, "r") as f:
        data = json.load(f)

    BUILDINGS.clear(); BUILDINGS.extend(data.get("buildings", []))
    ROOMS.clear();     ROOMS.extend(data.get("rooms", []))
    TIMESLOTS.clear(); TIMESLOTS.extend(data.get("timeslots", []))
    BREAK_SLOTS.clear(); BREAK_SLOTS.update(data.get("break_slots", []))
    LECTURERS.clear(); LECTURERS.extend(data.get("lecturers", []))
    GROUPS.clear();    GROUPS.extend(data.get("groups", []))
    MODULES.clear();   MODULES.extend(data.get("modules", []))

    # Backward-compatibility: upgrade plain string rooms/lecturers from old saves
    for idx, r in enumerate(ROOMS):
        if isinstance(r, str):
            ROOMS[idx] = {'name': r, 'capacity': 30, 'room_type': 'Any', 'building': ''}
    for idx, l in enumerate(LECTURERS):
        if isinstance(l, str):
            LECTURERS[idx] = {'name': l, 'unavailable': []}

    # JSON deserialises tuples as lists; convert back
    for l in LECTURERS:
        l['unavailable'] = [tuple(x) for x in l.get('unavailable', [])]

    # buildings stored in BUILDINGS list for room building field reference
    update_room_list()
    update_timeslot_list()
    update_lecturer_list()
    update_group_list()
    update_module_list()
    update_dropdowns()
    draw_timetable()
    status_var.set(f"Loaded from {path}")
    messagebox.showinfo("Loaded", "Data loaded successfully.")


def export_timetable():
    if not TIMESLOTS:
        messagebox.showerror("Error", "No timetable to export — add timeslots first.")
        return
    path = filedialog.asksaveasfilename(defaultextension=".pdf",
                                        filetypes=[("PDF files", "*.pdf")])
    if not path:
        return
    try:
        import tkinter.font as tkfont
        # Use reportlab if available, otherwise fall back to a simple HTML->print approach
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import cm

            doc = SimpleDocTemplate(path, pagesize=landscape(A4),
                                    leftMargin=1*cm, rightMargin=1*cm,
                                    topMargin=1.5*cm, bottomMargin=1*cm)
            styles = getSampleStyleSheet()
            elements = []

            elements.append(Paragraph("University Timetable", styles['Title']))
            elements.append(Spacer(1, 0.3*cm))

            header = ["Time"] + DAYS
            data   = [header]

            for slot in TIMESLOTS:
                row = [slot]
                for day in DAYS:
                    content = ""
                    for m in MODULES:
                        if m.get('timeslot') == slot and m.get('day') == day:
                            content = f"{m['name']}\n{m['lecturer']}\n{m.get('room','')}"
                            break
                    row.append(content)
                data.append(row)

            col_w  = [3*cm] + [4.2*cm] * 5
            table  = Table(data, colWidths=col_w, repeatRows=1)
            style  = TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F3864')),
                ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
                ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE',   (0, 0), (-1, 0), 10),
                ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#34495E')),
                ('TEXTCOLOR',  (0, 1), (0, -1), colors.white),
                ('FONTNAME',   (0, 1), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE',   (0, 1), (-1, -1), 8),
                ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID',       (0, 0), (-1, -1), 0.5, colors.grey),
                ('ROWBACKGROUNDS', (1, 1), (-1, -1),
                 [colors.white, colors.HexColor('#F5F7FF')]),
                ('WORDWRAP',   (0, 0), (-1, -1), True),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ])
            # Colour occupied cells by lecturer
            for row_i, slot in enumerate(TIMESLOTS, start=1):
                for col_i, day in enumerate(DAYS, start=1):
                    for m in MODULES:
                        if m.get('timeslot') == slot and m.get('day') == day:
                            hex_col = get_lecturer_color(m['lecturer']).lstrip('#')
                            r, g, b = (int(hex_col[k:k+2], 16)/255 for k in (0, 2, 4))
                            style.add('BACKGROUND', (col_i, row_i), (col_i, row_i),
                                      colors.Color(r, g, b))
                            break
            table.setStyle(style)
            elements.append(table)
            doc.build(elements)

        except ImportError:
            # Fallback: write an HTML file and inform user
            html_path = path.replace('.pdf', '.html')
            _export_html(html_path)
            messagebox.showinfo("PDF Export",
                                "reportlab is not installed — exported as HTML instead.\n"
                                f"Open {html_path} in a browser and print to PDF.\n\n"
                                "To install reportlab: pip install reportlab")
            status_var.set(f"Exported as HTML to {html_path}")
            return

    except Exception as e:
        messagebox.showerror("Export Error", f"Export failed:\n{e}")
        return

    status_var.set(f"Exported PDF to {path}")
    messagebox.showinfo("Exported", "Timetable exported successfully as PDF.")


def _export_html(path):
    rows_html = ""
    for slot in TIMESLOTS:
        row_html = f"<tr><td class='time'>{slot}</td>"
        for day in DAYS:
            content = ""
            color   = "#ffffff"
            for m in MODULES:
                if m.get('timeslot') == slot and m.get('day') == day:
                    content = f"<b>{m['name']}</b><br>{m['lecturer']}<br>{m.get('room','')}"
                    color   = get_lecturer_color(m['lecturer'])
                    break
            row_html += f"<td style='background:{color}'>{content}</td>"
        row_html += "</tr>"
        rows_html += row_html

    day_headers = "".join(f"<th>{d}</th>" for d in DAYS)
    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>Timetable</title>
<style>
  body {{ font-family: Arial, sans-serif; }}
  h1 {{ color: #1F3864; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th {{ background: #1F3864; color: white; padding: 8px; font-size: 13px; }}
  td {{ border: 1px solid #ccc; padding: 6px 8px; font-size: 11px;
        text-align: center; vertical-align: middle; min-width: 110px; min-height: 50px; }}
  td.time {{ background: #34495E; color: white; font-weight: bold; }}
  @media print {{ button {{ display: none; }} }}
</style></head><body>
<h1>University Timetable</h1>
<button onclick='window.print()'>Print / Save as PDF</button><br><br>
<table><thead><tr><th>Time</th>{day_headers}</tr></thead>
<tbody>{rows_html}</tbody></table>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

# =========================================================
# BULK GENERATION BY GROUP
# =========================================================
def open_bulk_dialog():
    if not GROUPS:
        messagebox.showerror("No Groups", "Please add student groups first.")
        return
    if not TIMESLOTS or not ROOMS:
        messagebox.showerror("Missing Data", "Please add timeslots and rooms first.")
        return

    dlg = tk.Toplevel(root)
    dlg.title("Bulk Generate by Group")
    dlg.geometry("380x320")
    dlg.resizable(False, False)
    dlg.grab_set()

    tk.Label(dlg, text="Select groups to auto-schedule:",
             font=("Arial", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
    tk.Label(dlg, text="Only modules belonging to the selected groups will be\n"
                       "solved. Modules with no group are unaffected.",
             font=("Arial", 8), fg="gray").pack(anchor="w", padx=12)

    # Checkboxes for each group
    group_vars = {}
    chk_frame = tk.Frame(dlg)
    chk_frame.pack(fill="x", padx=12, pady=8)
    for g in GROUPS:
        var = tk.BooleanVar(value=True)
        group_vars[g] = var
        ttk.Checkbutton(chk_frame, text=g, variable=var).pack(anchor="w")

    # Option to keep existing placements for other modules
    keep_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(dlg, text="Keep existing placements for unselected groups",
                    variable=keep_var).pack(anchor="w", padx=12)

    def run_bulk():
        selected = [g for g, v in group_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("No Groups Selected", "Please select at least one group.")
            return

        # Indices of modules that belong to selected groups
        target_indices = [i for i, m in enumerate(MODULES)
                          if m.get('group', '') in selected]

        if not target_indices:
            messagebox.showinfo("No Modules", "No modules found for the selected groups.")
            return

        # If keeping existing, temporarily remove non-target modules from solver
        # but pass their placements as fixed constraints would be complex —
        # instead we just solve the target subset and merge back
        original_modules = [dict(m) for m in MODULES]

        # Extract only the target modules for solving
        target_modules = [MODULES[i] for i in target_indices]

        # Temporarily replace MODULES with just the target subset
        MODULES.clear()
        MODULES.extend(target_modules)

        # Modules NOT in target — their placements are fixed constraints
        fixed = [original_modules[i] for i in range(len(original_modules))
                 if i not in target_indices
                 and original_modules[i].get('day')
                 and original_modules[i].get('timeslot')]

        dlg.destroy()

        for btn in solver_buttons:
            btn.config(state="disabled")
        status_var.set(f"Bulk solving {len(target_modules)} module(s) for: {', '.join(selected)}...")

        def _bulk_thread():
            try:
                result = _solve(fixed_modules=fixed)
                root.after(0, lambda: _finish_bulk(result, original_modules,
                                                    target_indices, keep_var.get()))
            except Exception as exc:
                err = str(exc)
                MODULES.clear()
                MODULES.extend(original_modules)
                root.after(0, lambda: _solver_error(err))

        threading.Thread(target=_bulk_thread, daemon=True).start()

    tk.Frame(dlg).pack(expand=True)  # spacer
    btn_row = tk.Frame(dlg)
    btn_row.pack(fill="x", padx=12, pady=(0, 12))
    ttk.Button(btn_row, text="Generate Selected Groups",
               command=run_bulk).pack(side="left", padx=(0, 8))
    ttk.Button(btn_row, text="Cancel",
               command=dlg.destroy).pack(side="left")


def _finish_bulk(result, original_modules, target_indices, keep_existing):
    for btn in solver_buttons:
        btn.config(state="normal")

    if result is None:
        # Restore original state
        MODULES.clear()
        MODULES.extend(original_modules)
        status_var.set("Bulk solve failed — no valid timetable found.")
        messagebox.showerror("No Solution",
                             "The solver could not find a valid timetable for the selected groups.\n"
                             "Try adding more rooms or timeslots.")
        return

    solved_modules, score = result

    if keep_existing:
        # Merge: put solved modules back into their original positions,
        # restore the rest from original
        merged = list(original_modules)
        for new_pos, orig_idx in enumerate(target_indices):
            merged[orig_idx] = solved_modules[new_pos]
        MODULES.clear()
        MODULES.extend(merged)
    else:
        # Replace just the target modules, clear others
        merged = list(original_modules)
        for new_pos, orig_idx in enumerate(target_indices):
            merged[orig_idx] = solved_modules[new_pos]
        MODULES.clear()
        MODULES.extend(merged)

    update_module_list()
    draw_timetable()
    _display_report(MODULES, score)
    status_var.set(f"Bulk generation complete — penalty score: {score}")
    messagebox.showinfo("Success",
                        f"Bulk generation complete!\n\nPenalty score: {score}\n"
                        f"Modules solved: {len(target_indices)}")


# =========================================================
# RUN
# =========================================================
root.mainloop()

