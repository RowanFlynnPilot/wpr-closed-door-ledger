# CLAUDE.md — The Closed Door Ledger (`wpr-closed-door-ledger`)

## What this is
An accountability archive of closed sessions in central Wisconsin, for Wausau Pilot & Review.
- It records every closed session a governmental body **notices in its online agenda**, the exemption the body cites, and the notice's exact wording.
- From the minutes it then records what happened: whether the session was held, how the vote to close was recorded, whether the minutes cite the exemption, and whether the body reconvened in open session.

It is pitched to funders together with the Records Ledger (`wpr-records-ledger`) as one transparency project. The two are tied together by a quarterly records audit (see "Quarterly audit").

**What the numbers mean.** Every count is labeled "noticed in the online agenda". A posted agenda is not necessarily the legal notice: s. 19.84(1) is also satisfied by physical posting and by notifying the media. And a session that was noticed may never have been held.

## Standing rules (set Oct 23, 2026)
- **The archive repo is always checked out at `archive/` in this folder**, locally and in Actions. `archive/` is in `.gitignore`.
- **One request at a time per host, at least 1 second apart.** Different hosts may run in parallel. The Jan 2024 backfill runs once, locally. The nightly run re-checks only the last 90 days and upcoming meetings.
- **Before every archive push:** no file over 50 MB and the repo under 1 GB, or stop. `archive_check.py` enforces this.
- Never put a private person's name from minutes into data. Nothing from `archive/` or `data/` ever lands in this repo.
- Wherever this file and the live sites disagree, the sites win: fix this file.

## Repos and licensing
- **`wpr-closed-door-ledger` (public).** Holds the code, tests, workflow and site.
  - Code is MIT-licensed. Published data is CC BY 4.0.
  - The site deploys to GitHub Pages as an Actions artifact. No data, archived documents, reviews or unvetted findings are ever committed here.
- **`wpr-closed-door-archive` (private).** Holds:
  - the archived notices and minutes
  - `reviews.json`
  - the internal data files
  - `NOTES.md`, the editorial leads and internal decisions

  The workflow checks it out with the `ARCHIVE_TOKEN` secret and pushes updates back.

## Files
**Built and tested (`python -m pytest tests`):**
- `citations.py`: the statute citations in an item
- `purpose.py`: the notice's own subject
- `bodies.py` with `bodies.yaml`: which governmental body held a meeting
- `triage_terms.json`: subject words per exemption, used to order the review queue
- `tests/`:
  - `fixtures/citations.json`: 27 cases, 24 of them real
  - `fixtures/titles.json`: 1,278 real meeting titles
  - `fixtures/sample_items.jsonl`: 110 real closed-session items
- `audit/request_template.md`: the quarterly request wording, pending Shereen's review

**To build, in phase order:**
- `adapters/` (`civicclerk.py`, `boardbook.py`, `agendacenter.py`, `municode.py`, later `marathon_county.py`)
  - Each exposes `list_meetings(since) -> list[Meeting]` and `fetch_documents(meeting) -> Documents`.
  - `Documents` carries the notice and minutes files, each with its text, `text_source` and sha256.
- `ocr.py`
- `extract.py`: sections, items, `citations` + `purpose`, triage
- `build.py`: writes the internal files to the archive repo and the public projection into the site artifact
- `audit.py`
- `web/`
- `.github/workflows/ledger.yml`

## Bodies, platforms and coverage (all probed Oct 23, 2026)
**Comparison window: Jan 1, 2024 to the present, for every jurisdiction.** Kronenwetter's listing only reaches back to May 2023.

**Report per governmental body.** Each committee, commission and board is its own body under s. 19.82(1). `bodies.yaml` lists all 72 and states the matching rules; `bodies.py` implements them.
- **Validated** Oct 23 on every 2024–26 meeting title: 1,278 across Wausau, both school districts and Kronenwetter. Each one maps to exactly one body, is a genuine joint meeting, or is excluded on purpose (quorum notices, test events, supplemental-packet rows). Weston matches on AgendaCenter category ids.
- **Unmatched or ambiguous titles fail the build.** A title matching several bodies counts for each only if it contains "joint". Otherwise it needs an `overrides` entry naming the bodies.
- **Generic titles are mapped one by one.** Wausau SD posts many different things as "Public Meeting".
  - Its 32 such entries since 2024 are mapped in `overrides` by first agenda item: 15 event quorum notices (graduations, celebrations, forums) are excluded; 11 Elementary Task Force meetings, 3 election canvasses and 3 board–union bargaining sessions are kept.
  - A blanket exclusion would have hidden those bargaining sessions, which are closed under s. 19.86.
  - New "Public Meeting" entries fail the build until classified.
- **`custodian:`** names who keeps a body's records when that isn't the jurisdiction whose portal posts the notice: the intergovernmental police and fire bodies, and a county commission posted on the city's portal.
- **`confirm:` marks open editor decisions:** Wausau SD's Elementary Task Force and election canvass, intergovernmental bodies, the county park commission, a regional housing task force, and Kronenwetter's generic "Ad Hoc Committee". **Bodies with `confirm:` are archived but not published until it's removed.**
- **For other newsrooms:** they add rows to `bodies.yaml`, not code.

| jurisdiction key | How to get notices | Minutes | Reaches back to |
|---|---|---|---|
| `wausau` | CivicClerk API `wausauwi.api.civicclerk.com/v1` (see below) | `publishedFiles` with `type: "Minutes"` (has text) | 2008; ~200 agendas a year since 2020 |
| `wausau_sd` | BoardBook `/Public/Organization/1360`, then `/Public/Agenda/1360?meeting=N` | PDF (has text); see "Minutes" | 2013 (852 meetings) |
| `dc_everest` | BoardBook org 1315, same paths | scanned PDF (needs OCR) | 2013 (219 meetings) |
| `weston` | AgendaCenter: `POST /AgendaCenter/UpdateCategoryList` with `year` and `catID` (360 agendas, 2024–26) | `/AgendaCenter/ViewFile/Minutes/_MMDDYYYY-ID` | 2013 |
| `kronenwetter` | Municode hub `?page=N` (pages 0–14), then the ADA HTML agenda | `MEET-Minutes-<guid>.pdf` on the hub row (has text) | May 2023 |
| `marathon` | marathoncounty.gov returns 403 to server IPs (confirmed Oct 23) | — | unknown |

**CivicClerk (Wausau):**
- Page through `/Events` by following `@odata.nextLink`; pages hold 15 events.
- Send a browser User-Agent. Python's default gets a 403.
- Download the PDF with `/Meetings/GetMeetingFileStream(fileId=N,plainText=false)` and extract the text yourself.
- **Do not use `plainText=true` for the ledger.** It returned empty text for every 2024 file tried (47 of 47), even though those PDFs have a text layer.

**Weston "agendas" are full packets.** The file AgendaCenter serves as the Agenda is the whole meeting packet: a median of 30 pages, up to 559 pages and 67 MB in the sample. `?html=true` returns the same PDF.
- Read only the first 5 pages. In the sample, every closed-session item was on pages 1–3.
- Archive only those pages (split with `pypdf`), plus the full file's sha256, page count and URL. Never commit a whole packet: GitHub rejects files over 100 MB.
- Use a HEAD request (`Content-Length`, `Last-Modified`) before re-downloading.

**Text.**
- **Sources:** pdfplumber for PDFs; `beautifulsoup4` for BoardBook pages and Municode ADA HTML. Unescape HTML entities.
- **Which version:** items come from the **latest notice version seen before the meeting started**. Later versions are archived but don't change the items.

**Scanned documents (OCR).** Image-only PDFs are routine: 14 of 63 sampled Weston agendas (the intergovernmental police bodies' signed notices), and D.C. Everest's minutes.
- Render each page at 300 dpi with `pypdfium2` and read it with Tesseract (`tesseract page.png - --psm 4`). In Actions, install it with `sudo apt-get install -y tesseract-ocr`.
- Tested Oct 23 on Weston's scanned agendas: the text read cleanly and `citations.parse` found every citation.
- Items from OCR'd text carry `text_source: "ocr"` and always go to review.
- If OCR yields under 200 characters, raise an error naming the file. A document must never count as "no closed items" because it couldn't be read.

**Politeness.** One request at a time per host, with a browser User-Agent and at least 1 second between them (`polite.py`). Different hosts may run in parallel.

## The law (verified Oct 23, 2026)
- **Notice, s. 19.84(2):** A notice must give the time, date, place and subject matter, including the subject matter of any contemplated closed session. It must be in a form reasonably likely to apprise the public and news media. It is due 24 hours ahead, or no less than 2 hours ahead for good cause (s. 19.84(3)). Citing the specific exemption in the notice is recommended practice (WASB); the statute requires it in the presiding officer's *announcement*.
- **How specific a notice must be:** *State ex rel. Buswell v. Tomah Area School District*, 2007 WI 71, sets a case-by-case reasonableness test. It weighs three things, judged by what the person writing the notice knew or should have known:
  - the burden of giving more detail
  - how much public interest the subject draws
  - whether the subject is routine or novel
- **Convening, s. 19.85(1):**
  - The body starts in open session.
  - The motion to close passes by majority, and each member's vote is recorded.
  - Before the vote, the presiding officer announces the nature of the business and the specific exemption.
  - The closed session is limited to that business.
- **Records, s. 19.88(3):** Motions and roll call votes are recorded, preserved and open to inspection. The minutes are not required to record the announcement.
- **Reconvening, s. 19.85(2):** To reopen in open session within 12 hours, the body must state that intent in the original notice.
- **Bargaining, s. 19.85(3):** A body may not use a closed session to ratify a collective bargaining agreement it negotiated.
- **Negotiations, s. 19.86:** The open meetings law does not apply to collective bargaining negotiations.

**Exemptions in s. 19.85(1)** (the only letters in the statute):
| Letter | Covers |
|---|---|
| (a) | Deliberating a case heard in a judicial or quasi-judicial trial or hearing before the body |
| (b) | Dismissal, demotion, licensing or discipline of an employee or licensee |
| (c) | Employment, promotion, compensation or performance evaluation data |
| (d) | Probation, extended supervision or parole applications; crime detection or prevention strategy |
| (e) | Buying public property, investing public funds, or other business where competitive or bargaining reasons require secrecy |
| (ee) | Unemployment insurance council deliberations |
| (eg) | Worker's compensation council deliberations |
| (em) | Burial site locations (s. 157.70) |
| (f) | Personal, financial, medical, social or disciplinary histories, or preliminary personnel problems, where discussion would likely harm a reputation |
| (g) | Conferring with legal counsel on litigation strategy |
| (h) | Requests for confidential advice from elections or ethics bodies |

Sources: [Wis. Stat. 19.85](https://docs.legis.wisconsin.gov/statutes/statutes/19/v/85); [WASB Open Meetings Law brochure, rev. March 2026](https://wasb.org/wp-content/uploads/2026/03/Open-Meetings-Law-Brochure.pdf); [Axley summary of *Buswell*](https://www.axley.com/publication_article/new-reasonableness-standard-applies-to-public-notices-of-governmental-meetings/); [DOJ open meetings training, March 2026](https://www.wisdoj.gov/Open%20Government/DOJ%20Human%20Trafficking%20Council%20-%20OML%20Basics.pdf).

## What real notices look like
**Samples pulled Oct 23, 2026, 2024–26:**
- Wausau: 160 random agendas plus all 130 Board of Public Works agendas
- Wausau SD and D.C. Everest: 45 BoardBook agendas each
- Kronenwetter: 60 Municode agendas
- Weston: 63 AgendaCenter packets

**Layouts:**
- Wausau and D.C. Everest write the citation into each closed-session item. D.C. Everest often chains several exemptions in one item: "19.85(1)(c) for … (Administrator Retirement Agreements) and (e) for … (Teacher Negotiations) and (f) for …".
- The Wausau School District puts a header, "REQUEST FOR CLOSED SESSION PURSUANT TO STATE STATUTES", over sub-items such as "Administrator Contract Review s. 19.85 (1)(c)". The subject comes before the citation.
- Kronenwetter and Weston use bare headers ("ANNOUNCEMENT OF CLOSED SESSION", "CLOSED SESSION", "CONTINUE IN CLOSED SESSION", "ACTION AFTER CLOSED SESSION") around a motion line that carries the citation.

**Citation forms seen:**
- `§ 19.85(1)(e)`, `Section 19.85(1)(g), Wis. Stats.`, `s. 19.85 (1)(c)`, `W.S.S. 19.85(1)(c)`
- spacing variants: `19.85(1) (e)` and `19.85 (1)( c )`
- Weston's comma form: `19.85(1), (c) and (f)`
- Kronenwetter's dotless form: `1985(1)(f)`
- a missing closing parenthesis: `19.85(1)(g for`
- no "(1)": `19.85(d)` and `19.85 (g)`

**Other patterns:**
- `19.85(2)` lines ("motion to reconvene … pursuant to 19.85(2)") are not closed sessions. They set `notices_reconvene` on the meeting.
- Other statutes appear: 19.86 with 111.70(4)(cm) (bargaining) and 118.125 (student records). Municipal code numbers like `12.56.130` are not statutes.
- Wausau's CivicClerk files were bulk re-published Jan 26, 2026, so `publishOn` can't date a historical notice.

## Extraction
- **Segment by agenda item, never by line.** PDF text wraps mid-citation.
  - BoardBook: table rows.
  - PDFs and Municode ADA HTML: split on the item numbering.
- **Sections.** A closed-session section is a header containing "closed session" plus the items under it. Each item in it that cites 19.85(1) or 19.86 is a closed-session item. Header-only lines are not items.
- **`no_citation`** is set on a section with no citation anywhere in it.
- **19.86-only items** (bargaining negotiations) are kept and counted separately as "s. 19.86 bargaining sessions", never in the exemption mix.
- **`citations.parse(text)`** returns `exemptions`, `cites_subsection_1`, `other_citations` and `citation_raw`.
  - It found letters in every one of 127 unique citation paragraphs from Wausau, both school districts and Kronenwetter, and every one of Weston's 14.
  - A review caught that D.C. Everest's chained letters were being dropped. That's fixed, and the 6 affected items are now fixtures.
  - The parser passes all 27 fixtures.
- **`purpose.purpose_text(text)`** returns the notice's own subject.
  - It looks for text after a marker ("for the purpose of", "regarding", "in regard to", "to wit", "specifically", "to discuss", a bullet), text in parentheses, or text before the citation.
  - It returns `""` when the notice only restates the statute and `None` when the item cites nothing.
  - It passes every fixture. On the 110 sample items it found a subject in 109.
  - The sample items were split by paragraph, so some include a neighboring item. Use them to see wording, not as test truth.
- **Item id:** `<meeting id>:<first 12 hex chars of sha256(normalized item_text)>`. That is stable when an amended agenda renumbers its items.
- **No LLM.**

## Review
**`triage` is `check` when any of these is true:**
- the section has no citation
- `cites_subsection_1` is false
- `purpose_text` is empty or under 4 words
- `text_source` is `ocr`
- the `purpose_text` contains none of the terms listed in `triage_terms.json` for any of the cited letters (a case-insensitive substring match). Letters with no terms (ee, eg, em) always check.

Otherwise `triage` is `ok`. Nearly every notice names some subject, so the real *Buswell* question is generic subjects such as "Potential Litigation" or "deliberating on claims". That's why the word-count rule exists.

**`reviews.json`** lives in the archive repo, keyed by item id:
```json
{ "wausau:130:3f9a1c2b7d4e": { "decision": "flagged", "note": "…", "editor": "SS", "date": "2026-11-02" } }
```
- `decision` is `confirmed`, `flagged` or `withhold`. Editors judge against the *Buswell* factors and whether the exemption fits the subject.
- The build **fails** on any review whose key matches no item.
- `withhold` drops the item from the site and blanks its meeting's `notice_url` and archived-copy link. Use it, for example, for an agenda that named a student.

## Archive rules
- **Append-only, every version.** Archive each distinct file version (by sha256) with `seen_at`.
- **`changed_after_meeting`** is set only when a meeting already had an archived version, and a *new* version is first seen after the meeting date. Backfilled history never sets it.
- **Removals are shown neutrally** ("no longer on the body's site").
- **Fail fast:**
  - Any HTTP error raises.
  - A jurisdiction whose listing returns zero meetings for the last 60 days raises.
  - GitHub emails on a failed run; no issue automation is needed.
- **Marathon County staleness** (from phase 3 on): the build fails if the newest county notice is more than 10 days old.

## Minutes (probed Oct 23, 2026)
**Where they are:**
- **Wausau:** a `Minutes` entry in `publishedFiles`. Download it with `GetMeetingFileStream(plainText=false)`.
- **BoardBook:** `/Public/Minutes/{org}?meeting=N` is a viewer page. The PDF's id is in the hidden input `NewDocumentViewerDocumentID`; download it from `/Documents/DownloadPDF/{id}?org={org}`.
- **Kronenwetter:** `https://mccmeetings.blob.core.usgovcloudapi.net/krnwtrwi-pubu/MEET-Minutes-<guid>.pdf`
- **Weston:** `/AgendaCenter/ViewFile/Minutes/_MMDDYYYY-ID`

**`vote_record`** records how the minutes show the vote to close:

| `vote_record` | What the minutes show | Seen in |
|---|---|---|
| `per_member` | each member's vote ("Sarah Brock – Yes …") | Wausau SD |
| `tally` | a count ("Motion Passed 3-0", "roll call vote 6:0") | Wausau since late 2025, Kronenwetter |
| `unanimous` | "Motion passed unanimously", with attendance listed | Wausau 2025 |
| `result_only` | "Motion passed." | Wausau early 2025 |
| `unreadable` | a scan not yet OCR'd | D.C. Everest |

DOJ's training (March 2026) says the vote of each member must be recorded. Whether `unanimous` or `tally` with attendance satisfies that is a legal judgment for editors. It is never an automated label.

**`exemption_in_minutes`** records whether the minutes cite the exemption. Minutes aren't required to record the announcement, so a false here is not a violation.

**Minutes get revised.** Kronenwetter amended its Jan 12, 2026 minutes to change a voice vote to a roll call on the motion to close. Archive every minutes version.

**Names.** Minutes name private people, such as claimants and complainants. Never copy those names into data or onto the site; link to the source.

## Data contracts
**Internal files** (in the archive repo) hold every field.

`meetings.json`:
```json
{ "id": "wausau:2195", "bodies": ["wausau-water-works"], "jurisdiction": "wausau",
  "meeting_date": "2026-09-01", "canceled": false, "notice_url": "https://…",
  "notice_versions": 1, "changed_after_meeting": false, "source_status": "live",
  "notices_reconvene": false, "closed_item_count": 0, "minutes_url": "https://…" }
```

`closed_sessions.json`:
```json
{ "id": "wausau:130:3f9a1c2b7d4e", "meeting_id": "wausau:130", "bodies": ["wausau-economic-development"],
  "meeting_date": "2026-01-06", "item_text": "exact notice wording",
  "citation_raw": "19.85(1)(e)", "exemptions": ["e"], "cites_subsection_1": true,
  "other_citations": [], "no_citation": false, "text_source": "text_layer",
  "purpose_text": "the sale of 424 Burns Street, Wausau", "triage": "ok",
  "minutes": null }
```
- `text_source` is `text_layer`, `html` or `ocr`.
- From phase 2, `minutes` becomes `{ "held": true, "motion_recorded": true, "vote_record": "tally", "exemption_in_minutes": true, "reconvened": true, "minutes_version": 1 }`.

**Public projection** (site JSON and CSV):
- **Whitelisted fields only:** `id`, `meeting_id`, `bodies`, `meeting_date`, `item_text`, `citation_raw`, `exemptions`, `other_citations`, `purpose_text`, `notice_url`, `archive_url`, `minutes`, plus `review_note` for `confirmed` or `flagged` items.
- **Never published:**
  - `triage`, `cites_subsection_1`, `no_citation`, `text_source`, `notices_reconvene`
  - withheld items
  - bodies with `confirm:`

## Quarterly audit (links the two ledgers)
Each quarter, file the same simple request with each **custodian**: the open-session minutes or s. 19.88(3) records showing the motion and vote for each closed session noticed in the quarter.
- `audit.py` groups `closed_sessions.json` by `custodian` (from `bodies.yaml`, defaulting to the jurisdiction) and fills `audit/request_template.md`. The template is pending Shereen's review.
- The requests are logged in the Records Ledger.
- **The first round covers Q3 2026.** Its responses feed the phase 2 hand-check.

## Marathon County
- **Residential machine.** Run the county adapter on the residential machine as a scheduled task, at a few requests per day, and commit to the archive repo. This is the same flow marathon-meetings uses for transcripts.
- **Find the listing first.** From a normal browser, find out how the county lists agendas. Search engines index the documents but not the listing pages, and WebFetch is blocked too.
- **What's known about the document links.** They look like `/home/showpublisheddocument/<id>/<stamp>`. The ids look sequential (around 18,500 by May 2026). The stamp appears to be .NET ticks of the upload time: `639149618233330000` decodes to 2026-05-21 12:03. Confirm that in the browser.
- **Ask the clerk.** Ask whether the 403 block can exempt this archive, or whether agendas come as a feed. A yes moves the county into CI.

## Phases
1. **Five reachable jurisdictions, Jan 2024 onward.** Build the adapters, `ocr.py`, `extract.py` and `build.py`. Write internal files only; nothing is published yet.
   - Done when the build passes and a spot-check of 10 random notices per jurisdiction matches.
2. **First audit and minutes hand-check.**
   - Write `audit.py` and file the Q3 2026 audit round.
   - Hand-check Q3 2026 minutes for every noticed closed session: held? motion recorded? which `vote_record` level? exemption in the minutes? reconvened?
   - Separately, list closed sessions in the minutes that were never noticed.

   Automate the minutes rules afterward.
3. **Marathon County** on the residential machine.
4. **Site:** a per-body table and the exemption mix (with n), a searchable item list linking the source and archived copy, and CSV downloads. No trend chart, because quarterly counts per body are too small.

## Editorial policy
- The ledger states what a notice says, what it cites, and what the minutes show. Nothing more.
- No automated characterizations. Every published flag is an editor's decision with a note.
- Before publishing a flag about a body, the reporter contacts that body for comment.
- **Unvetted leads live in the private archive repo's `NOTES.md`**, never in this public repo.
- The page states its coverage window and links `bodies.yaml`, and never implies completeness outside them.

## Design system and conventions
- **Design system:** Same as the other Ledgers. Teal `#3A867C`, cream `#F6F2E9`; Fraunces for display, Public Sans for body, JetBrains Mono for data.
- **Code:** Python 3.12. Scripts use `argparse` and support `--dry-run`.
- **Locally:** Windows, PowerShell 5.1, `python -m pip`, commands chained with semicolons. Tesseract for Windows comes from the UB Mannheim build, added to PATH.
- **Principles:** One correct path, no fallbacks, fail fast. Single-responsibility functions.
- **Workflow:** `.github/workflows/ledger.yml` runs daily on `cron: "17 11 * * *"` (11:17 UTC, early morning Central).
