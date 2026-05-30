"""Streamlit UI for the Bus Charging Scheduler."""

from __future__ import annotations

import streamlit as st
import pandas as pd

from src.loader import load_all_scenarios, minutes_to_time
from src.scheduler import schedule_scenario


st.set_page_config(
    page_title="Bus Charging Scheduler",
    page_icon="🚌",
    layout="wide",
)

st.title("Bus Charging Scheduler")
st.caption("Bengaluru ↔ Kochi · 4 charging stations · OR-Tools CP-SAT")


@st.cache_data(show_spinner="Running scheduler…")
def run_scheduler(scenario_id: str):
    scenarios = {s.id: s for s in load_all_scenarios()}
    scenario = scenarios[scenario_id]
    return schedule_scenario(scenario)


scenarios = load_all_scenarios()
scenario_options = {s.name: s.id for s in scenarios}

selected_name = st.selectbox(
    "Scenario",
    options=list(scenario_options.keys()),
    index=0,
)

scenario_id = scenario_options[selected_name]
scenario = next(s for s in scenarios if s.id == scenario_id)

try:
    result = run_scheduler(scenario_id)
except Exception as exc:
    st.error(f"Scheduler failed: {exc}")
    st.stop()

# --- Scenario input ---
st.subheader("Scenario input")
col1, col2 = st.columns([2, 1])
with col1:
    st.markdown(f"**{scenario.name}**")
    st.write(scenario.description)
with col2:
    st.markdown("**Weights**")
    st.json(
        {
            "individual": scenario.weights.individual,
            "operator": scenario.weights.operator,
            "overall": scenario.weights.overall,
        }
    )

bus_rows = [
    {
        "Bus ID": b.id,
        "Operator": b.operator,
        "Direction": "Bengaluru→Kochi" if b.direction.value == "BK" else "Kochi→Bengaluru",
        "Departure": minutes_to_time(b.departure_min),
    }
    for b in scenario.buses
]
st.dataframe(pd.DataFrame(bus_rows), use_container_width=True, hide_index=True)

st.divider()

# --- Summary metrics ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("Solver status", result.solver_status)
m2.metric("Total wait (all buses)", f"{result.total_wait_min} min")
m3.metric("Network makespan", minutes_to_time(result.makespan_min))
m4.metric("Operator spread", f"{result.operator_spread_min} min")

# --- Per-bus timetable ---
st.subheader("Per-bus timetable")

for timeline in result.bus_timelines:
    direction_label = "BK" if timeline.direction.value == "BK" else "KB"
    with st.expander(
        f"{timeline.bus_id} · {timeline.operator} · {direction_label} · "
        f"departs {minutes_to_time(timeline.departure_min)} · "
        f"arrives {minutes_to_time(timeline.arrival_min)} · "
        f"wait {timeline.total_wait_min} min",
        expanded=False,
    ):
        st.write(f"**Charging plan:** {' → '.join(timeline.stations_used)}")

        rows = []
        for i, leg in enumerate(timeline.legs):
            if "charge_start" in leg:
                rows.append(
                    {
                        "Step": f"Travel + charge @ {leg['to']}",
                        "From": leg["from"],
                        "To": leg["to"],
                        "Travel (min)": leg["travel_min"],
                        "Arrival": minutes_to_time(leg["arrival"]),
                        "Charge start": minutes_to_time(leg["charge_start"]),
                        "Charge end": minutes_to_time(leg["charge_end"]),
                        "Wait (min)": leg["wait_min"],
                    }
                )
            else:
                rows.append(
                    {
                        "Step": "Final leg to destination",
                        "From": leg["from"],
                        "To": leg["to"],
                        "Travel (min)": leg["travel_min"],
                        "Arrival": minutes_to_time(leg["arrival"]),
                        "Charge start": "—",
                        "Charge end": "—",
                        "Wait (min)": "—",
                    }
                )

        rows.insert(
            0,
            {
                "Step": "Depart origin (full charge)",
                "From": "Bengaluru" if timeline.direction.value == "BK" else "Kochi",
                "To": timeline.stations_used[0],
                "Travel (min)": timeline.legs[0]["travel_min"] if timeline.legs else "—",
                "Arrival": minutes_to_time(
                    timeline.legs[0]["arrival"] if timeline.legs else timeline.departure_min
                ),
                "Charge start": "—",
                "Charge end": "—",
                "Wait (min)": 0,
            },
        )

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.divider()

# --- Per-station view ---
st.subheader("Per-station charging order")

station_tabs = st.tabs(["A", "B", "C", "D"])
for tab, station_id in zip(station_tabs, ["A", "B", "C", "D"]):
    with tab:
        queue = result.station_queues.get(station_id, [])
        if not queue:
            st.info("No buses charged at this station in this scenario.")
            continue
        rows = [
            {
                "#": i + 1,
                "Bus ID": e.bus_id,
                "Operator": e.operator,
                "Arrival": minutes_to_time(e.arrival_min),
                "Charge start": minutes_to_time(e.charge_start_min),
                "Charge end": minutes_to_time(e.charge_end_min),
                "Wait (min)": e.wait_min,
            }
            for i, e in enumerate(queue)
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
