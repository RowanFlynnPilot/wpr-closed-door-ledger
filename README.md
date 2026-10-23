# The Closed Door Ledger

*In development.* An archive of closed sessions held by local governmental bodies in central Wisconsin, being built by [Wausau Pilot & Review](https://wausaupilotandreview.com).

**Planned coverage:**
- the City of Wausau
- the Wausau and D.C. Everest school districts
- the villages of Weston and Kronenwetter
- Marathon County, once its agenda listing can be reached

For each closed session a body notices in its online agenda, the ledger will record:
- the exact wording of the notice
- the statutory exemption cited under Wis. Stat. § 19.85(1)
- what the minutes show happened afterward

## What the numbers will mean
Counts are of closed sessions **noticed in the online agenda**.
- A posted agenda isn't necessarily the legal notice. Under s. 19.84(1), bodies can also give notice by physical posting and by telling the media.
- A noticed session may never have been held.

The ledger reports what documents say. Any flag about a specific notice is an editor's decision, recorded with a note, and the body is asked for comment before it's published.

## How it works
1. **Fetching.** The ledger reads agendas and minutes from each body's publishing platform: CivicClerk, BoardBook, AgendaCenter or Municode.
2. **Archiving.** It keeps each document version.
3. **Parsing.** It reads the statutory citations with a deterministic, tested parser ([`citations.py`](citations.py)).

No generative AI reads or classifies notices. Scanned documents are read with open-source OCR (Tesseract), and anything read that way is checked by an editor.

[`bodies.yaml`](bodies.yaml) lists every included body; each committee, commission and board is its own governmental body under s. 19.82(1). Many Wisconsin bodies publish on the same four platforms, so another newsroom can add bodies by adding rows to this file.

## Development
```
python -m pip install -r requirements.txt
python -m pytest tests
```

## License
Code: MIT (see [LICENSE](LICENSE)). Published data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), credit Wausau Pilot & Review.
