# Bus Charging Scheduler

Electric-bus charging scheduler for the Bengaluru ↔ Kochi corridor. Built with **Python + Streamlit + OR-Tools CP-SAT**.

## Quick start (local)

```bash
git clone <your-repo-url>
cd exponent_energy
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501`. Pick a scenario from the dropdown to see input, per-bus timetables, and per-station charging order.

## Project layout

```
app.py                  # Streamlit UI
requirements.txt
data/
  route.yaml            # Route, stations, battery, default weights
  scenarios/            # 5 scenario files (the "scenario IS the data structure")
src/
  models.py             # Domain types
  loader.py             # YAML I/O
  planner.py            # Valid charging-plan generation (240 km rule)
  rules.py              # Soft objective rules (extensible)
  scheduler.py          # CP-SAT engine
```

## How to change a weight

Weights live in **one obvious place per scenario** — the `weights` block in the scenario YAML:

```yaml
# data/scenarios/scenario_04_operator_heavy.yaml
weights:
  individual: 1.0
  operator: 2.0   # ← change here
  overall: 1.0
```

Default weights for new scenarios come from `data/route.yaml`. No code change required.

The solver reads these at runtime and scales the CP-SAT objective:

```python
# src/scheduler.py (excerpt)
obj_terms = []
if w.individual:
    obj_terms.append(int(w.individual * scale) * total_wait)
if w.overall:
    obj_terms.append(int(w.overall * scale) * makespan)
if w.operator:
    obj_terms.append(int(w.operator * scale) * operator_spread)
model.Minimize(sum(obj_terms))
```

## How to add a new rule

1. Implement a class in `src/rules.py`:

```python
class PeakHourCostRule(SoftRule):
    name = "peak_hour_cost"

    def weight_key(self) -> str:
        return "peak_hour_cost"

    def evaluate(self, ctx: ObjectiveContext) -> int:
        # return penalty; lower is better
        return sum(1 for t in ctx.per_bus_wait.values() if t > 30)
```

2. Register it in `DEFAULT_RULES`.
3. Add the weight key to your YAML:

```yaml
weights:
  individual: 1.0
  operator: 1.0
  overall: 1.0
  peak_hour_cost: 0.5
```

4. Wire the same weight into the CP-SAT objective in `scheduler.py` (one line per rule).

Hard rules (e.g. "priority bus never waits") go in `scheduler.py` as additional `model.Add(...)` constraints — the engine structure stays the same.

## How to add a new scenario

Create `data/scenarios/scenario_06_my_test.yaml`:

```yaml
id: scenario_06
name: "My test scenario"
description: "..."
route_id: bengaluru_kochi
weights:
  individual: 1.0
  operator: 1.0
  overall: 1.0
buses:
  - { id: bus-BK-01, operator: kpn, direction: BK, departure: "19:00" }
  # ...
```

Restart the app — it auto-discovers all `scenario_*.yaml` files.

## Host on Streamlit Community Cloud

1. Push this repo to a **public** GitHub repository.
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click **New app** → select your repo, branch `main`, main file `app.py`.
4. Deploy. Copy the public URL for your submission form.

No secrets or extra config needed — `requirements.txt` is enough.

## Assumptions

| Topic | Assumption |
|-------|------------|
| Speed | 60 km/h → travel time in minutes equals distance in km |
| Time format | All times are same-day; schedules may cross midnight (displayed as 24h+) |
| Charging | Always to full, exactly 25 minutes, no partial charges |
| Endpoints | Bengaluru/Kochi pre-charge buses; only A–D are scheduled |
| Plan choice | Greedy load-balancing among minimum-stop valid plans; CP-SAT optimizes queue order |
| Direction | `BK` = Bengaluru→Kochi, `KB` = Kochi→Bengaluru |

See `ARCHITECTURE.md` for design rationale and anticipated future changes.
