import { EXEMPTIONS, LETTERS, el, fmtDate, fmtDateTime, fmtInt, isBargaining, loadJSON, showError, todayCentral } from "./common.js";

const PAGE = 50;
const main = document.querySelector("main");

function counts(items) {
  const byLetter = Object.fromEntries(LETTERS.map((l) => [l, 0]));
  for (const item of items) for (const l of item.exemptions) byLetter[l] += 1;
  return byLetter;
}

function figures(meta, meetings, items) {
  const noticing = new Set(items.map((i) => i.meeting_id)).size;
  const bargaining = items.filter(isBargaining).length;
  const figure = (n, label) =>
    el("div", { class: "lead-figure" }, el("span", { class: "lead-num" }, fmtInt(n)), el("span", { class: "lead-label" }, label));
  return [
    figure(meetings.length, "meetings with an online agenda"),
    figure(noticing, "noticed a closed session"),
    figure(items.length - bargaining, "closed-session items, bargaining not counted"),
    figure(bargaining, "s. 19.86 bargaining sessions, counted apart"),
  ];
}

function bodyRows(bodies, meetings, items) {
  const rows = [];
  let jurisdiction = null;
  const sorted = [...bodies].sort((a, b) =>
    a.jurisdiction_name.localeCompare(b.jurisdiction_name) || a.name.localeCompare(b.name));
  for (const body of sorted) {
    const ms = meetings.filter((m) => m.bodies.includes(body.key));
    if (!ms.length) continue;
    if (body.jurisdiction_name !== jurisdiction) {
      jurisdiction = body.jurisdiction_name;
      rows.push(el("tr", { class: "group" }, el("th", { scope: "rowgroup", colspan: "5" }, jurisdiction)));
    }
    const its = items.filter((i) => i.bodies.includes(body.key));
    const mix = Object.entries(counts(its)).filter(([, n]) => n).map(([l, n]) => `(${l}) ${fmtInt(n)}`);
    const bargaining = its.filter(isBargaining).length;
    if (bargaining) mix.push(`s. 19.86 ${fmtInt(bargaining)}`);
    rows.push(el("tr", {},
      el("th", { scope: "row", class: "body-name" }, body.name),
      el("td", { class: "num", "data-label": "Meetings with an online agenda" }, fmtInt(ms.length)),
      el("td", { class: "num", "data-label": "Noticing a closed session" }, fmtInt(ms.filter((m) => m.closed_item_count).length)),
      el("td", { class: "num", "data-label": "Closed-session items" }, fmtInt(its.length)),
      el("td", { class: "mix-cell", "data-label": "Exemptions cited" }, mix.join(" · ") || "—")));
  }
  return rows;
}

function mix(items) {
  const cited = items.filter((i) => i.exemptions.length);
  const byLetter = counts(cited);
  const max = Math.max(1, ...Object.values(byLetter));
  return LETTERS.filter((l) => byLetter[l]).map((l) =>
    el("div", { class: "mix-row" },
      el("span", { class: "mix-letter" }, `(${l})`),
      el("span", { class: "mix-label" }, EXEMPTIONS[l]),
      el("span", { class: "mix-bar", "aria-hidden": "true" },
        el("span", { class: "mix-fill", style: `width: ${(100 * byLetter[l]) / max}%` })),
      el("span", { class: "mix-n" }, fmtInt(byLetter[l]))));
}

function itemRow(item, names) {
  const links = [];
  if (item.notice_url) links.push(el("a", { href: item.notice_url, target: "_blank", rel: "noreferrer" }, "Agenda on the body's site"));
  if (item.archive_url) links.push(el("a", { href: item.archive_url }, "Archived copy"));
  const cited = isBargaining(item) ? "s. 19.86 (bargaining)"
    : item.exemptions.length ? item.exemptions.map((l) => `(${l})`).join(" ") : "No statute cited";
  // A noticed session that hasn't happened yet: the notice says it's planned, not that it was held.
  const today = todayCentral();
  const when = item.meeting_date > today ? "Upcoming" : item.meeting_date === today ? "Today" : null;
  return el("li", { class: "item" },
    el("div", { class: "item-head" },
      el("span", { class: "item-date" }, fmtDate(item.meeting_date)),
      when ? el("span", { class: "item-when" }, when) : null,
      el("span", { class: "item-body" }, item.bodies.map((b) => names[b]).join(" and ")),
      el("span", { class: "item-cites" }, cited)),
    el("p", { class: "item-subject" }, item.purpose_text ? item.purpose_text : el("em", {}, "The notice names no subject beyond the statute's wording.")),
    el("details", {}, el("summary", {}, "Exact wording"), el("p", { class: "item-text" }, item.item_text),
      item.citation_raw ? el("p", { class: "item-raw" }, `Citation as written: ${item.citation_raw}`) : null),
    item.review_note ? el("p", { class: "review-note" }, el("strong", {}, "Editor's note: "), item.review_note) : null,
    el("p", { class: "item-links" }, links));
}

function list(items, names) {
  const q = document.querySelector("#q");
  const bodyFilter = document.querySelector("#body-filter");
  const exFilter = document.querySelector("#ex-filter");
  const target = document.querySelector("#item-list");
  const shown = document.querySelector("#shown");
  const more = document.querySelector("#more");
  const sorted = [...items].sort((a, b) => b.meeting_date.localeCompare(a.meeting_date) || a.id.localeCompare(b.id));
  let limit = PAGE;
  function render() {
    const words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    const matches = sorted.filter((i) => {
      if (bodyFilter.value && !i.bodies.includes(bodyFilter.value)) return false;
      if (exFilter.value === "19.86" && !isBargaining(i)) return false;
      if (exFilter.value === "none" && (i.exemptions.length || isBargaining(i))) return false;
      if (exFilter.value && exFilter.value.length <= 2 && !i.exemptions.includes(exFilter.value)) return false;
      const hay = `${i.item_text} ${i.purpose_text || ""} ${i.bodies.map((b) => names[b]).join(" ")}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    });
    target.replaceChildren(...matches.slice(0, limit).map((i) => itemRow(i, names)));
    if (!matches.length) target.replaceChildren(el("li", { class: "empty" }, "No notices match."));
    shown.textContent = `${fmtInt(Math.min(limit, matches.length))} of ${fmtInt(matches.length)} shown`;
    more.hidden = matches.length <= limit;
  }
  for (const control of [q, bodyFilter, exFilter]) control.addEventListener("input", () => { limit = PAGE; render(); });
  more.addEventListener("click", () => { limit += PAGE; render(); });
  render();
}

async function start() {
  try {
    const [meta, bodies, allMeetings, items] = await Promise.all(
      ["meta", "bodies", "meetings", "closed_sessions"].map((n) => loadJSON(`data/${n}.json`)));
    // A meeting counts once the body has posted an agenda for it online.
    const meetings = allMeetings.filter((m) => m.notice_versions > 0);
    const names = Object.fromEntries(bodies.map((b) => [b.key, b.name]));
    document.querySelector("#updated").textContent =
      `Covers meetings from ${fmtDate(meta.window_start, { month: "long", day: "numeric", year: "numeric" })} on · rebuilt ${fmtDateTime(meta.built_at)}`;
    document.querySelector("#coverage").replaceChildren(
      `${meta.jurisdictions.join(", ")}, from ${fmtDate(meta.window_start, { month: "long", year: "numeric" })}; the bodies listed in `,
      el("a", { href: "bodies.yaml" }, "bodies.yaml"),
      meta.unpublished_bodies ? `. ${fmtInt(meta.unpublished_bodies)} more bodies are archived but not shown until an editor settles how to report them` : "",
      ". Nothing outside these bodies and dates is covered");
    document.querySelector("#figures").replaceChildren(...figures(meta, meetings, items));
    document.querySelector("#body-rows").replaceChildren(...bodyRows(bodies, meetings, items));
    const cited = items.filter((i) => i.exemptions.length);
    document.querySelector("#mix").replaceChildren(...mix(items));
    document.querySelector("#mix-note").textContent =
      `n = ${fmtInt(cited.length)} items citing a s. 19.85(1) letter. Items citing only s. 19.86 or no statute are not in this mix.`;
    const bodyFilter = document.querySelector("#body-filter");
    for (const b of [...bodies].sort((x, y) => x.name.localeCompare(y.name))) {
      if (items.some((i) => i.bodies.includes(b.key))) bodyFilter.append(el("option", { value: b.key }, `${b.name} (${b.jurisdiction_name})`));
    }
    const exFilter = document.querySelector("#ex-filter");
    for (const l of LETTERS) if (cited.some((i) => i.exemptions.includes(l))) exFilter.append(el("option", { value: l }, `(${l}) ${EXEMPTIONS[l]}`));
    exFilter.append(el("option", { value: "19.86" }, "s. 19.86 bargaining"), el("option", { value: "none" }, "No statute cited"));
    list(items, names);
  } catch (err) {
    showError(main, err);
  }
}

start();
