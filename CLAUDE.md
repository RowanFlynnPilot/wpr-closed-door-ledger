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
All built and tested (`python -m pytest tests`). Code targets Python 3.12 (Actions); the local venv runs 3.14.
- **Reading notices:** `citations.py` (statute citations), `purpose.py` (the notice's own subject), `extract.py` (items, sections, triage, item ids), `minutes.py` (what the minutes show)
- **Bodies:** `bodies.py` with `bodies.yaml`; `triage_terms.json` orders the review queue
- **Fetching:** `adapters/` (`base.py` is the interface; `civicclerk.py`, `boardbook.py`, `agendacenter.py`, `municode.py`), `polite.py` (all HTTP), `documents.py` (PDF text, page splits), `ocr.py`, `store.py` (archive layout), `fetch.py` (the runner)
- **Building:** `build.py` (archive → internal files and the site), `archive_check.py` (pre-push limits)
- **Quarterly:** `quarters.py`, `audit.py` with `audit/request_template.md` (pending Shereen's review), `handcheck.py`
- **Site:** `web/` (static HTML, CSS and ES modules; no build step). `build.py` copies it into `site/` with the data.
- **Workflow:** `.github/workflows/ledger.yml`, on the `workflow` branch until it's merged.
- **Fixtures** (`tests/fixtures/`): `citations.json`, `titles.json`, `sample_items.jsonl`, `notices.json` (short excerpts of real posted agendas with the items a reader finds), and `adapters/<platform>/` (trimmed listing pages and agendas). Fixtures hold public agenda wording only, **never minutes text**, and nothing is copied out of `archive/`.

**Pipeline.** `fetch.py` is the only step that makes requests; it writes the archive. `build.py` reads only the archive.
```
python fetch.py --since 2024-01-01     # the one-time local backfill
python fetch.py --recent               # nightly: the last 90 days and upcoming meetings
python build.py                        # archive/data/ and site/
python archive_check.py --push         # after committing in archive/
python audit.py --quarter 2026Q3       # archive/audit/2026-Q3/
python handcheck.py --quarter 2026Q3   # archive/handcheck/2026-Q3/
```
- **When documents are fetched:** a meeting whose start is in the last 90 days or later, or that has never been fetched. So an interrupted backfill resumes, and older meetings are fetched once.
- Jurisdictions run in parallel threads; `polite.py` serializes each host. An error in one jurisdiction lets the others finish, then the run fails.
- Titles a jurisdiction excludes (quorum notices) are listed but their documents aren't fetched. Unmatched titles are fetched; the build then fails until `bodies.yaml` classifies them.

**Adapter interface** (`adapters/base.py`; this replaces the earlier one-argument sketch):
- `list_meetings(jurisdiction, config, since) -> list[Meeting]`: every listed meeting starting on or after `since`, including upcoming ones. `config` is the jurisdiction's `bodies.yaml` block.
- `fetch_documents(meeting, known) -> Documents`: the current notice and minutes. `known` holds the latest archived version of each; an adapter may answer `Unchanged` after a HEAD request instead of downloading.
- HTML text puts each agenda item on one line, starting with its label. PDF pages are joined with `\f`.

**Archive layout** (`store.py`): `archive/meetings/<jurisdiction>/<meeting_id>/meeting.json` (latest listing, first and last listed, every file version with `seen_at`), `<kind>-<sha12>.<pdf|html>` and `<kind>-<sha12>.txt`. Internal files go to `archive/data/`; the hand-check and audit to `archive/handcheck/` and `archive/audit/`.

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

| jurisdiction key | How to get notices | Minutes | Listed since Jan 1, 2024 (Oct 23, 2026) |
|---|---|---|---|
| `wausau` | CivicClerk API `wausauwi.api.civicclerk.com/v1` (see below) | `publishedFiles` with `type: "Minutes"` (has text) | 913 events (753 past, 160 upcoming into 2028); 716 with an agenda; 501 with minutes |
| `wausau_sd` | BoardBook `/Public/Organization/1360`, then `/Public/Agenda/1360?meeting=N` | PDF (has text) or an item table; see "Minutes" | 186; 107 with minutes |
| `dc_everest` | BoardBook org 1315, same paths | scanned PDF (OCR'd) | 49; 46 with minutes |
| `weston` | AgendaCenter: `POST /AgendaCenter/UpdateCategoryList` with `year` and `catID` | `/AgendaCenter/ViewFile/Minutes/_MMDDYYYY-ID` | 406 rows (360 without Election Notices); 282 with minutes |
| `kronenwetter` | Municode `/meetings3` listing, then the ADA HTML agenda | `MEET-Minutes-<guid>.pdf` on the row (has text) | 296 rows, 281 with files; 238 with minutes |
| `marathon` | marathoncounty.gov returns 403 to plain requests, even from this machine with a browser User-Agent (Oct 23); see "Marathon County" | — | unknown |

**CivicClerk (Wausau):**
- List `/Events?$filter=startDateTime ge <since>T00:00:00Z&$orderby=startDateTime` and follow `@odata.nextLink` (15 per page; the link carries the filter).
- `startDateTime` ends in "Z" but is **Central wall-clock time** ("10:30:00Z" is a 10:30 a.m. meeting).
- Send a browser User-Agent. Python's default gets a 403.
- The notice is the `Agenda` file. Three 2024 events (1463, 1640, 1424) post only an `Agenda Packet`; for those the notice is the packet's first 5 pages, as with Weston. `Notice` files are another body's quorum notices and are ignored.
- Download with `/Meetings/GetMeetingFileStream(fileId=N,plainText=false)` and extract the text yourself. **Never `plainText=true`:** it returned empty text for 47 of 47 2024 files.
- HEAD returns 405 and there's no Last-Modified, so files are always downloaded. Public links are portal pages: `wausauwi.portal.civicclerk.com/event/{eventId}/files/agenda/{fileId}` (the portal uses `agenda` for every file type).
- Cancellation shows only in the title.

**BoardBook (both school districts):**
- One listing page holds every meeting since 2013 (`tr.row-for-board`). A heading with no clock time ("Immediately following the Annual Meeting") gives a date-only start; the titles fixture missed three such D.C. Everest meetings.
- **Each page carries a per-request `__RequestVerificationToken`.** The adapter blanks it before archiving and hashing, or every fetch would look like a new version.
- Item descriptions ("Show Everything") are part of the posted agenda and are kept in the item's line.
- An agenda page is usually an item table, but some special meetings redirect to a PDF viewer (`CustomAgendaForMeeting`). Minutes are usually a PDF viewer, but some are an item table. The adapter handles both shapes for both.
- No Last-Modified, so no HEAD shortcut.

**Weston "agendas" are full packets.** The file AgendaCenter serves as the Agenda is the whole meeting packet: a median of 30 pages, up to 559 pages and 56 MB (Dec 16, 2024 Village Board). `?html=true` returns the same PDF.
- Read only the first 5 pages, and archive only those (split with `pypdf`), plus the full file's sha256, page count and URL. Never commit a whole packet.
- **AgendaCenter sends no Last-Modified.** Before re-downloading, the adapter compares the HEAD `Content-Length` and the listing's own "Posted/Amended" stamp with the archived version.
- Every category on `/AgendaCenter` is listed, so a new category fails `bodies.match` instead of being missed. Five old categories (none used since 2023) aren't in `bodies.yaml`.
- No start time is listed: starts are date-only.
- 19 quorum notices sit in body categories; `exclude: possible quorum` drops them.
- Packets carry the previous meeting's minutes after the agenda, so extraction stops after the agenda's Adjourn page (see "Extraction").
- Earlier agenda versions are listed at `/AgendaCenter/PreviousVersions/_MMDDYYYY-ID` (225 of 406 rows). Not used yet; they could backfill "latest version before the meeting".

**Municode (Kronenwetter):**
- List `/meetings3` with an explicit date filter from `since` to today + 366 days (the default "To" is today + 30, which hides later meetings), following the pager link.
- The meeting id is the 32-hex guid in the row's file names. **Rows with no files (12 cancellations and 3 others since 2024) have no id and are skipped**; a row appears once its agenda is posted.
- The ADA HTML agenda (`meetings.municode.com/adaHtmlDocument/index?cc=KRNWTRWI&me=<guid>`) sends no Last-Modified. Minutes are overwritten in place at the same URL; a HEAD (size and Last-Modified) catches a revision.
- Cancellation shows only in the title, sometimes as a suffix ("Meeting--CANCELLED").

**Text.**
- **Sources:** pdfplumber for PDFs; `beautifulsoup4` for BoardBook pages and Municode ADA HTML. Unescape HTML entities.
- **Which version:** items come from the **latest notice version seen before the meeting started**. Later versions are archived but don't change the items. A date-only start (Weston, some BoardBook meetings) counts versions seen through the meeting day. When no version was seen before the meeting (the backfill), the earliest archived version is used.
- **Unreadable documents:** a PDF that yields under 200 readable characters raises, naming the file. An HTML agenda raises only when empty (under 10 characters): real ones can hold a single item ("I. VERIFY SCHOOL BOARD ELECTION RESULTS").

**Scanned documents (OCR).** Image-only PDFs are routine: 14 of 63 sampled Weston agendas (the intergovernmental police bodies' signed notices), and D.C. Everest's minutes.
- OCR is decided **per page**: a page whose text layer has under 25 non-space characters and that carries an image is a scan. Render it at 300 dpi with `pypdfium2` and read it with Tesseract (`tesseract stdin stdout --psm 4`). In Actions, install it with `sudo apt-get install -y tesseract-ocr`.
- An item's `text_source` is `ocr` when the page it starts on was OCR'd, so a scanned attachment behind a text agenda doesn't send the agenda's items to review.
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
- a slash for the dot: `19/85 (1)(f)` (Wausau HR, Nov 11, 2024)
- capital letters: `19.85 (1)(C)` (Mountain Bay police)
- the wrong statute: SAFER cites `19.81(1)(c)` (Aug 2025). The parser reads no exemption, so the item is `no_citation` and goes to review. That is correct: the notice cites no s. 19.85 exemption.

**Other patterns:**
- `19.85(2)` lines ("motion to reconvene … pursuant to 19.85(2)") are not closed sessions. They set `notices_reconvene` on the meeting.
- Other statutes appear: 19.86 with 111.70(4)(cm) (bargaining) and 118.125 (student records). Municipal code numbers like `12.56.130` are not statutes.
- Wausau's CivicClerk files were bulk re-published Jan 26, 2026, so `publishOn` can't date a historical notice.

## Extraction
- **Segment by agenda item, never by line.** PDF text wraps mid-citation.
  - BoardBook and Municode: the adapter puts one item per line (table rows, list items).
  - PDFs: a new item starts at a numbering label (`IV.`, `V.A.`, `7.`, `a)`, `(1)`, Wausau's bare `5 Closed Session.`, OCR's `8,`), at an unnumbered line in capitals (a header), or at an unnumbered line that *starts* with a closed-session keyword in capitals (`CLOSED SESSION pursuant to…`, `MOTION TO MOVE TO CLOSED SESSION`, `CONTINUE IN CLOSED SESSION`, `RECONVENE…`, `POSSIBLE ACTION…`). Everything else continues the item before it.
  - Each item's depth comes from its label style, in the order styles first appear (I. → A. → 1. → a.); BoardBook's combined labels give depth directly. Headers sit above numbered items.
  - Lines repeated at the top or bottom of two or more pages (page headers and footers) are dropped.
  - **Notices stop at the page holding the closing "Adjourn" line** (not "Adjourn to closed session"). Weston's packets and CivicClerk packet-only notices carry the previous meeting's minutes after the agenda, with their own closed-session motions.
- **Sections.** A closed-session section is an item that speaks of convening in closed session, plus everything under it. Mentions that aren't about convening don't start one: reconvening, action after or on closed-session items, approving closed-session minutes, "prior to any potential closed session".
- **Closed-session items:** each item that cites s. 19.85(1) or s. 19.86 and either itself speaks of convening or sits under a section that does. Header-only lines are not items.
- **`no_citation`:** when a notice has closed-session sections but no cited item anywhere, it yields **one** item with `no_citation: true` whose text is the sections' wording, " / "-joined. A notice with any cited item yields only those: its uncited mentions ("ANNOUNCEMENT OF CLOSED SESSION", "Closed Session Information (Board Only)") belong to the same session.
- **`notices_reconvene`** is set by a `19.85(2)` citation or wording that states the intent to reconvene in open session ("reconvene [meeting] into open session", "return to open session", even the misspelled "RECONVEVE"), read from the agenda's own pages only (not a packet's bound-in earlier agendas).
- Labels may have no space after them in some PDFs ("III.The Board"); a label BoardBook doubles ("II.A. II.A.") is read once.
- **A wrong statute** (SAFER's "19.81(1)(c)") makes the item `no_citation`, but `citation_raw` shows the statute as written and `purpose_text` still reads the named subject. `citation_raw` falls back to any other statute's text only when there is no s. 19.85 citation, so s. 19.86 items show "ss. 19.86 and 111.70 (4)(cm)".
- **s. 19.86 footnotes:** a heading row carrying an asterisked footnote ("ADJOURNMENT* * The Parties may continue negotiations in closed session pursuant to ss. 19.86 …") yields the footnote as the item, and its subject comes from the earlier item that cites s. 19.86 and names the talks.
- **19.86-only items** (bargaining negotiations) are kept and counted separately as "s. 19.86 bargaining sessions", never in the exemption mix.
- **`citations.parse(text)`** returns `exemptions`, `cites_subsection_1`, `other_citations` and `citation_raw`.
  - It found letters in every one of 127 unique citation paragraphs from Wausau, both school districts and Kronenwetter, and every one of Weston's 14.
  - A review caught that D.C. Everest's chained letters were being dropped. That's fixed, and the 6 affected items are now fixtures.
  - The parser passes all 27 fixtures.
- **`purpose.purpose_text(text)`** returns the notice's own subject.
  - It looks for, in order: text before the citation, kept whole when it names something beyond procedural words ("Meet with Attorney to Discuss Sale of Property"; not "MOTION TO MOVE TO" or "The Board will adjourn to"); text after a marker ("for the purpose of", "regarding", "in regard to", "to wit", "specifically", "to discuss", "including", "discussing", "related to", "relating to", "to hold", a bullet), running to the next citation, bullet, motion or sentence end, so a second "regarding" inside one subject doesn't split it; text in parentheses; and, when none of those names anything, the words right after the last citation.
  - Every candidate is cut where the statute's own wording begins ("employment, promotion, compensation", "substantial adverse effect", …), so restated statute text never passes as a subject.
  - It returns `""` when the notice only restates the statute and `None` when the item cites nothing.
  - It passes every fixture. On the 110 sample items it found a subject in 109.
  - The sample items were split by paragraph, so some include a neighboring item. Use them to see wording, not as test truth.
- **Item id:** `<meeting id>:<first 12 hex chars of sha256(normalized item_text)>`. `item_text` excludes the numbering label, and normalizing collapses whitespace and case-folds. That is stable when an amended agenda renumbers its items.
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
- **Append-only, every version.** Archive each distinct file version (by sha256) with `seen_at` (UTC).
- **`changed_after_meeting`** is set only when a meeting already had an archived notice version, and a *new* version whose **text differs** from the one before it is first seen on a later Central date than the meeting date. Backfilled history never sets it. The text test keeps a re-published file with identical wording (Wausau re-published everything Jan 26, 2026) from looking like a change.
- **Removals are shown neutrally** ("no longer on the body's site"). A meeting inside the listed window that the platform no longer lists gets `source_status: "removed"`; a file no longer served gets `file_status[kind]: "removed"` in `meeting.json`.
- **Fail fast:**
  - Any HTTP error raises. No retries: a failed run is re-run, and the archive skips what it holds.
  - A jurisdiction whose listing returns zero meetings for the last 60 days raises.
  - GitHub emails on a failed run; no issue automation is needed.
- **Marathon County staleness** (from phase 3 on): the build fails if the newest county notice is more than 10 days old.

## Minutes (probed Oct 23, 2026)
**Where they are:**
- **Wausau:** a `Minutes` entry in `publishedFiles`. Download it with `GetMeetingFileStream(plainText=false)`.
- **BoardBook:** `/Public/Minutes/{org}?meeting=N` is usually a viewer page (it redirects to `CustomMinutesForMeeting`). The PDF's id is in the hidden input `NewDocumentViewerDocumentID`; download it from `/Documents/DownloadPDF/{id}?org={org}`. Some Wausau SD minutes are an item table instead, archived as HTML.
- **Kronenwetter:** `https://mccmeetings.blob.core.usgovcloudapi.net/krnwtrwi-pubu/MEET-Minutes-<guid>.pdf`
- **Weston:** `/AgendaCenter/ViewFile/Minutes/_MMDDYYYY-ID`. Usually a PDF; a few are Word files (June 8, 2026), archived as `.docx` and read with the standard library (`documents.docx_text`).

**`vote_record`** records how the minutes show the vote to close:

| `vote_record` | What the minutes show | Seen in |
|---|---|---|
| `per_member` | each member's vote ("Pat Doe – Yes …", "Yes: Doe, Roe, …", "roll call vote, Doe, Roe, … all yes") | Wausau SD, D.C. Everest (OCR'd), Mountain Bay police, some Wausau committees |
| `tally` | a count ("Motion Passed 3-0", "roll call vote 6:0", "Yes 11, No 0") | Wausau since late 2025, Kronenwetter, Weston |
| `unanimous` | "Motion passed unanimously" | Wausau 2025 |
| `result_only` | "Motion passed." | Wausau Board of Public Works 2024–25 |
| `not_shown` | a motion with no vote result ("took rollcall of members present") | Wausau HR 2024 |

`vote_record` is `null` when no motion is recorded. `unreadable` is gone: every scan is OCR'd, and OCR'd minutes are classified like any other.

DOJ's training (March 2026) says the vote of each member must be recorded. Whether `unanimous` or `tally` with attendance satisfies that is a legal judgment for editors. It is never an automated label.

**The rules** (`minutes.py`; the minutes are segmented like an agenda, without stopping at Adjourn):
- `motion_recorded`: a motion to convene in closed session ("Motion by … to convene into closed session", "moved to enter into Closed Session", "Motioned by … to Adjourn to Closed Session", "Motion by … to Closed Session").
- `held`: the minutes say the body convened ("convened into Closed Session", "TIME INTO CLOSED SESSION", "entered closed session", "adjourned from Closed Session"), or a convene motion passed.
- `vote_record`: read from the text after the first convene motion whose vote is shown, up to the next motion (2,500 characters at most: motions restate the statute first).
- `exemption_in_minutes`: the item holding the motion, or its parent heading, cites an s. 19.85(1) letter.
- `reconvened`: a motion to reconvene in open session, "reconvened", "TIME INTO OPEN SESSION" or "back in open session", unless the minutes say the body did not reconvene.
- Facts come from the latest minutes version. They are per meeting and attached to each of its items.
- **Not published yet.** `build.PUBLISH_MINUTES` is `False` until the Q3 2026 hand-check validates the rules; until then the public `minutes` field is `null`.
- **Never-noticed closed sessions:** a meeting whose minutes record a convene motion but whose notice has no closed-session item goes in `archive/data/unnoticed_closed_sessions.json` (ids, links and minutes page numbers only). These are unvetted leads: the agenda online may not be the only notice, or the minutes may belong to an amended agenda the site no longer shows.

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
- `minutes` is `{ "held": true, "motion_recorded": true, "vote_record": "tally", "exemption_in_minutes": true, "reconvened": true, "minutes_version": 1 }`, or `null` when no minutes are archived.
- `meetings.json` also holds `title`, `start`, `minutes_versions`, `notice_file` (the archived version the items came from), `minutes` and `minutes_convene_pages`.

**Public projection** (`site/data/`, JSON and CSV):
- **Items, whitelisted fields only:** `id`, `meeting_id`, `bodies`, `meeting_date`, `item_text`, `citation_raw`, `exemptions`, `other_citations`, `purpose_text`, `notice_url`, `archive_url`, `minutes` (`null` until `PUBLISH_MINUTES`), plus `review_note` for `confirmed` or `flagged` items.
- **Meetings, whitelisted:** `id`, `bodies`, `jurisdiction`, `meeting_date`, `canceled`, `notice_url`, `notice_versions`, `source_status`, `closed_item_count`, `minutes_url`. Also `bodies.json` (key, name, jurisdiction), `meta.json` (build time, window, jurisdictions, how many bodies are held back) and a copy of `bodies.yaml`.
- **`archive_url`** is a site-relative path (`archive/<jurisdiction>/<meeting_id>/notice-<sha12>.<ext>`). `build.py` copies those archived notices, and only those, into the site artifact. The archive repo stays private.
- **Never published:**
  - `triage`, `cites_subsection_1`, `no_citation`, `text_source`, `notices_reconvene`, `changed_after_meeting`
  - withheld items
  - bodies with `confirm:`. A joint meeting is published under its other bodies; an item whose only bodies are held back is dropped.

## Quarterly audit (links the two ledgers)
Each quarter, file the same simple request with each **custodian**: the open-session minutes or s. 19.88(3) records showing the motion and vote for each closed session noticed in the quarter.
- `audit.py` groups `closed_sessions.json` by `custodian` (from `bodies.yaml`, defaulting to the jurisdiction's name) and fills `audit/request_template.md`, one file per custodian in `archive/audit/<year>-Q<n>/`. The template is pending Shereen's review.
  - A joint meeting's item goes to each of its bodies' custodians.
  - s. 19.86-only items are left out: the open meetings law doesn't apply to bargaining negotiations, so there are no s. 19.88(3) records to ask for.
  - The requester's fields (`[RECORDS CUSTODIAN]`, `[EMAIL]`, `[AMOUNT]`, `[NAME]`, `[PHONE]`) are left for the editor. Custodian `unknown` (the regional housing task force) can't be sent until its `confirm:` is settled.
- The requests are filed by an editor and logged in the Records Ledger. Nothing files automatically.
- **The first round covers Q3 2026.** Its responses feed the phase 2 hand-check.
- **The hand-check** (`handcheck.py`) writes `archive/handcheck/<year>-Q<n>/`: `sheet_noticed.csv` (every meeting that noticed a closed session, with blank columns for the five minutes facts), `sheet_unnoticed.csv` (every other meeting with minutes, with a blank "closed session in minutes?" column), `automated.json` (`minutes.py`'s answers, opened only after both sheets are filled) and a README. The sheets carry links, never minutes text.

## Marathon County
- **Residential machine.** Run the county adapter on the residential machine as a scheduled task, at a few requests per day, and commit to the archive repo. This is the same flow marathon-meetings uses for transcripts.
- **Plain requests are blocked from this machine too** (Oct 23, 2026): `https://www.marathoncounty.gov/` and `/robots.txt` return 403 "Access Denied" from Akamai (`Server: AkamaiGHost`) even with a browser User-Agent. **No adapter was built**, and none should work around the block.
- **The listing, seen in a normal browser (Oct 23):**
  - `/about-us/minutes-agendas` lists the current year's meetings: Event, Date/Time, Agenda, Minutes, Packet. Toggles: `/-toggle-today`, `-next7days`, `-next30days`, `-allupcoming`, `-allpast`, `-all`; pages via `/-npage-N` (40 rows a page; "All Past" had 31 pages). A category filter (`eventcats_46_638_623`) lists 36 bodies, from Airport Board to Veterans Service Commission.
  - "All available Minutes & Agendas" is at `/about-us/minutes-agendas/meeting-document-archive`. The page notes that sub-committee materials are not posted to the archive.
  - Each event links `/Home/Components/Calendar/Event/<id>/309`. Files are named like `TRAN_20261021_Agenda`, `COBD_20261020_Packet`, and link `/home/showpublisheddocument/<id>/<stamp>` (ids near 19,500 by Oct 2026).
  - The stamp is .NET ticks of the upload time, and the decoded times fit the meetings: `639281039839870000` is 2026-10-20 14:39, for an Oct 21 agenda.
- **Ask the clerk.** Ask whether the 403 block can exempt this archive, or whether agendas come as a feed. A yes moves the county into CI, with an adapter for the listing above.

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
- **Workflow:** `.github/workflows/ledger.yml` runs daily on `cron: "17 11 * * *"` (11:17 UTC, early morning Central): test, `fetch.py --recent`, `build.py`, commit the archive, `archive_check.py --push`, then upload `site/` and deploy it to Pages. It lives on the `workflow` branch until merged; schedules only run from the default branch.
- **Site:** `web/` reuses the Records Ledger's tokens, masthead and footer. Values from the data are always set as text, never HTML. Preview with `.claude/launch.json` ("site": `http.server` on port 8790 over `site/`).
