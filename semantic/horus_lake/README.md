# `horus_lake`: the Horus semantic model

The Helios (Ossie) semantic model of the Horus lake: datasets, fields, joins and
metrics over the typed views in `horus_<instance>_views` (`provision/lake.py`,
`VIEWS`). It is Horus product content, like the NiFi flows: built once from the
lake, reviewed by a person, committed here, and published on each instance at
install (burndown O0d). Customers don't harvest it; they extend it with their own
tables.

## Files

| File | What |
|---|---|
| `RUN` | The Helios run the current proposal came from |
| `PROPOSAL.md` | Every proposed element with its confidence and the LLM's rationale, for review |
| `proposal.json` | The same, as JSON (`helios proposal show --format json`) |
| `review.json` | The decisions: accept, edit or reject per element (Helios's review format) |
| `model.yaml` | The published Ossie document (`helios model export`); what O0d publishes on a new instance |

## Building it (O0b)

In a Workbench session of the Horus project, with Helios installed (the command
prints the pinned `pip install` if it isn't) and the LLM key set as on the
feeds-gateway (`LLM_API_KEY`, `LLM_MODEL`):

```bash
python provision/horus.py create --yes          # creates the typed views (and anything else missing)
python provision/horus.py model-propose         # helios harvest, profile, propose, proposal show
# review PROPOSAL.md; record decisions in review.json; commit and pull
python provision/horus.py model-publish         # helios publish --review review.json, then helios model export
```

Both commands only write the instance's `helios.toml` and call the `helios`
commands, the same ones any Helios user runs. The run's working files stay in `~/helios-data/<instance>/` in the session; what
matters is committed here. The harvest sends column profiles, including sample
values, to the LLM.

Tested locally (`ssb/test/run_views_local.sh`, Trino 460): the views over every
feed's sample envelopes, and Helios's harvest and profile of them, set up by
`provision/semantic.py`.
