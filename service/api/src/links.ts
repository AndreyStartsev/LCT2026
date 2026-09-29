// Связи документов объекта (#82, дизайн — docs/design/82-document-links.html).
//
// Две вещи, обе считаются на лету из того, что уже есть в базе: карта объекта «стадии ×
// разделы» с находками дугами между клетками и контекст одной находки — её документы по
// стадиям, та же проверка на других участках, помещения. Графа объекта не храним и не
// строим: на крупном объекте он превращается в клубок (Речников — 427 помещений, 76
// документов, 3 949 связей). Конвейер не трогаем: индекс помещений кладёт в отчёт
// протокола воркер, фильтр ложных связей — здесь.
import { findingStatus } from "./report.js";
import { sidesOf } from "./sides.js";

type Json = Record<string, any>;
export type Stage = "PD" | "RD" | "ID";
export const STAGES: Stage[] = ["PD", "RD", "ID"];

/** Помещение, которое встречается в большем числе документов, связей не даёт: это поэтажный план или ведомость. */
export const ROOM_MAX_DOCS = 8;
/** Номер из одной-двух цифр чаще всего — номер строки таблицы («1» у «Коммерческого помещения 742»). */
const SHORT_ROOM = /^\d{1,2}$/;

/** Состояние записи на карте и в контексте — то же деление, что на карте Матрицы дашборда. */
export type LinkState = "VIOLATION" | "CANDIDATE" | "CLEAN" | "NOT_COMPARABLE" | "MISSING_EVIDENCE" | "SUSPICION";

export function linkState(row: Json): LinkState {
  switch (findingStatus(row)) {
    case "CONFIRMED_VIOLATION":
      return "VIOLATION";
    case "CANDIDATE":
    case "CLARIFICATION_REQUIRED":
      return "CANDIDATE";
    case "NEGATIVE_VERIFIED":
      return "CLEAN";
    case "NOT_COMPARABLE":
      return "NOT_COMPARABLE";
    case "SUSPICION":
      return "SUSPICION";
    default:
      return "MISSING_EVIDENCE";
  }
}
const STATE_ORDER: LinkState[] = ["VIOLATION", "CANDIDATE", "SUSPICION", "NOT_COMPARABLE", "CLEAN", "MISSING_EVIDENCE"];

/** Стадия файла: ручная правка инспектора важнее разбора; смешанный комплект РД и ИД — рабочая. */
export function fileStage(file: Json): Stage | null {
  const raw = String(file.stage_manual ?? file.doc_stage ?? "");
  const stage = raw === "RD_ID_MIXED" ? "RD" : raw;
  return (STAGES as string[]).includes(stage) ? (stage as Stage) : null;
}

/** Стадия доказательства: какую стадию читало правило; смешанный комплект — рабочая. */
function evidenceStage(e: Json, file: Json | undefined): Stage | null {
  const raw = String(e.stage ?? "");
  const stage = raw === "RD_ID_MIXED" ? "RD" : raw;
  if ((STAGES as string[]).includes(stage)) return stage as Stage;
  return file ? fileStage(file) : null;
}

export function fileSection(file: Json): string {
  const s = file.section_manual ?? file.discipline;
  return s ? String(s) : "OTHER";
}

const basename = (path: string | null | undefined) => String(path ?? "").split("/").pop() ?? "";
const evidenceOf = (row: Json): Json[] => (Array.isArray(row.body?.evidence) ? row.body.evidence : []);
const locationOf = (row: Json): string | null => {
  const list = Array.isArray(row.body?.locations) ? row.body.locations.map(String) : [];
  return list.join(", ") || (row.location ? String(row.location) : null);
};

/**
 * Карта объекта: документы по стадиям и разделам, находки — связями между клетками, если их
 * доказательства лежат в двух стадиях. Там же — список таких находок: из него в дашборде
 * выбирают, чей контекст смотреть.
 */
export function objectMap(files: Json[], findings: Json[]) {
  const accepted = files.filter((f) => f.status === "ACCEPTED" && f.file_id);
  const byId = new Map(accepted.map((f) => [String(f.file_id), f]));
  const grid = new Map<string, number>();
  const stages: Record<Stage, number> = { PD: 0, RD: 0, ID: 0 };
  // смешанный комплект РД и ИД стоит в колонке РД — карта говорит, сколько таких
  let mixed = 0;
  for (const f of accepted) {
    const stage = fileStage(f);
    if (!stage) continue;
    stages[stage] += 1;
    if (stage === "RD" && !f.stage_manual && f.doc_stage === "RD_ID_MIXED") mixed += 1;
    const key = `${stage}|${fileSection(f)}`;
    grid.set(key, (grid.get(key) ?? 0) + 1);
  }

  const links = new Map<string, number>();
  const multi: Json[] = [];
  for (const row of findings) {
    if (row.verification_status === "SPLIT") continue;
    const cells = new Map<string, [Stage, string]>();
    for (const e of evidenceOf(row)) {
      const file = byId.get(String(e.file_id));
      const stage = evidenceStage(e, file);
      if (!file || !stage) continue;
      cells.set(`${stage}|${fileSection(file)}`, [stage, fileSection(file)]);
    }
    const list = [...cells.values()].sort((a, b) => STAGES.indexOf(a[0]) - STAGES.indexOf(b[0]) || a[1].localeCompare(b[1]));
    const state = linkState(row);
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        if (list[i][0] === list[j][0]) continue;
        const key = `${list[i][0]}|${list[i][1]}>${list[j][0]}|${list[j][1]}>${state}`;
        links.set(key, (links.get(key) ?? 0) + 1);
      }
    }
    const inStages = STAGES.filter((s) => list.some((c) => c[0] === s));
    if (inStages.length >= 2) {
      multi.push({
        id: row.id,
        code: row.parameter_code,
        title: row.body?.title ?? null,
        location: locationOf(row),
        state,
        stages: inStages,
        cells: list.map(([stage, section]) => ({ stage, section })),
      });
    }
  }
  multi.sort((a, b) => STATE_ORDER.indexOf(a.state) - STATE_ORDER.indexOf(b.state) || String(a.code).localeCompare(String(b.code)));

  return {
    stages,
    mixed,
    grid: [...grid.entries()].map(([key, documents]) => {
      const [stage, section] = key.split("|");
      return { stage, section, documents };
    }),
    links: [...links.entries()]
      .map(([key, count]) => {
        const [from, to, state] = key.split(">");
        const [fromStage, fromSection] = from.split("|");
        const [toStage, toSection] = to.split("|");
        return { from: { stage: fromStage, section: fromSection }, to: { stage: toStage, section: toSection }, state, findings: count };
      })
      .sort((a, b) => b.findings - a.findings),
    findings: multi,
  };
}

/**
 * Контекст находки: её документы по стадиям (со страницами, цитатой и редакцией), та же
 * проверка на других участках объекта и помещения — где ещё они встречаются. Помещение
 * с коротким номером или из «клубка» связи не даёт; заменённая редакция не связывается.
 */
export function findingContext(row: Json, files: Json[], findings: Json[], rooms: Record<string, string[]> | null) {
  const byId = new Map(files.filter((f) => f.file_id).map((f) => [String(f.file_id), f]));
  // актуальная редакция каждой цепочки: её выбирает инспектор или разбор
  const current = new Map<string, Json>();
  for (const f of files) {
    if (!f.chain_id) continue;
    if (f.revision_manual === true || (f.revision_status === "CURRENT" && !current.has(String(f.chain_id)))) {
      current.set(String(f.chain_id), f);
    }
  }
  const superseded = (f: Json | undefined) => !!f && f.revision_status === "SUPERSEDED" && f.revision_manual !== true;
  const docView = (f: Json) => ({
    file_id: String(f.file_id),
    name: basename(f.relative_path),
    code: f.document_code ?? null,
    page_count: f.pdf_pages ?? null,
    revision: f.revision ?? null,
    revision_status: f.revision_status ?? null,
    current: superseded(f) && current.get(String(f.chain_id))
      ? { file_id: String(current.get(String(f.chain_id))!.file_id), name: basename(current.get(String(f.chain_id))!.relative_path) }
      : null,
  });

  // документы доказательства по стадиям
  const perFile = new Map<string, { stage: Stage; pages: Set<number>; quote: string | null }>();
  for (const e of evidenceOf(row)) {
    const file = byId.get(String(e.file_id));
    const stage = evidenceStage(e, file);
    if (!file || !stage) continue;
    const key = `${stage}|${file.file_id}`;
    const slot = perFile.get(key) ?? { stage, pages: new Set<number>(), quote: null };
    if (Number.isFinite(Number(e.pdf_page_number))) slot.pages.add(Number(e.pdf_page_number));
    if (!slot.quote && e.quote) slot.quote = String(e.quote).slice(0, 240);
    perFile.set(key, slot);
  }
  // у проверки внутри листа ИД допуск и отклонение оба с него: у ПД и РД значения нет
  const values: Record<Stage, unknown> = sidesOf(row).by_stage;
  const stages = STAGES.map((stage) => ({
    stage,
    value: values[stage] === undefined || values[stage] === null ? null : String(values[stage]),
    documents: [...perFile.entries()]
      .filter(([, slot]) => slot.stage === stage)
      .map(([key, slot]) => ({
        ...docView(byId.get(key.split("|")[1])!),
        pages: [...slot.pages].sort((a, b) => a - b),
        quote: slot.quote,
      })),
  }));
  const evidenceFiles = new Set([...perFile.keys()].map((k) => k.split("|")[1]));

  // та же проверка на других участках
  const same = findings
    .filter((f) => f.id !== row.id && f.parameter_code === row.parameter_code && f.verification_status !== "SPLIT")
    .map((f) => ({ id: f.id, location: locationOf(f), state: linkState(f) }))
    .sort((a, b) => STATE_ORDER.indexOf(a.state) - STATE_ORDER.indexOf(b.state) || String(a.location).localeCompare(String(b.location)));

  // помещения: где ещё встречаются, с фильтром ложных связей
  const roomNumbers = row.body?.location_type === "ROOM" && Array.isArray(row.body?.locations)
    ? row.body.locations.map(String).slice(0, 5)
    : [];
  const roomsView = rooms === null
    ? null
    : roomNumbers.map((room: string) => {
        const all = (rooms[room] ?? []).filter((id) => byId.has(id));
        const other = all.filter((id) => !evidenceFiles.has(id));
        const actual = other.filter((id) => !superseded(byId.get(id)));
        const cut = SHORT_ROOM.test(room) ? "SHORT" : all.length > ROOM_MAX_DOCS ? "TANGLED" : null;
        return {
          room,
          total: all.length,
          cut,
          superseded_skipped: other.length - actual.length,
          documents: actual.slice(0, 12).map((id) => {
            const f = byId.get(id)!;
            return { file_id: id, stage: fileStage(f), name: basename(f.relative_path), code: f.document_code ?? null };
          }),
        };
      });

  return {
    finding: {
      id: row.id,
      finding_id: row.finding_id,
      code: row.parameter_code,
      title: row.body?.title ?? null,
      state: linkState(row),
      location: locationOf(row),
      location_type: row.body?.location_type ?? null,
    },
    stages,
    same_parameter: { total: same.length, items: same.slice(0, 12) },
    rooms: roomsView,
    rooms_indexed: rooms !== null,
  };
}
