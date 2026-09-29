// Клиент REST API. Типы повторяют схемы из service/openapi.json.
//
// Демонстрационных данных здесь нет намеренно: если сервис недоступен, интерфейс
// говорит об этом, а не показывает правдоподобные, но выдуманные находки.

export type ProcessStatusName = "PENDING" | "PARSING" | "READY" | "VERIFYING" | "COMPLETED" | "FINALIZED";

export interface Limits {
  max_file_mb: number;
  max_package_mb: number;
  formats: string[];
  /** Модели для способа чтения «модель» (#54): пусто — выбор не предлагается */
  reading_models?: { id: string; label: string }[];
  model_default?: string | null;
}

export interface Processing {
  state?: "IDLE" | "QUEUED" | "RUNNING" | "DONE" | "FAILED";
  step?: string | null;
  attempt?: number | null;
  message?: string | null;
  error?: string | null;
  last_step_seconds?: number;
  /** когда задание встало в очередь и когда воркер его взял: по ним видна очередь */
  queued_at?: string | null;
  started_at?: string | null;
}

export interface FindingCounts {
  total: number;
  candidates: number;
  pending: number;
  /** записи свободного поиска, не переведённые в кандидаты: в candidates и pending не входят */
  hypotheses: number;
  confirmed: number;
  rejected: number;
  clarification: number;
  split: number;
  no_violation: number;
  not_comparable: number;
  /** решения, принятые по прежним значениям: после дозагрузки значения изменились — пересмотреть */
  revisit?: number;
  /** по разделам Матрицы (ключ — начало кода: PZ, KR, IOS4…): ждут решения и подтверждено */
  by_section?: Record<string, { candidates: number; confirmed: number }>;
}

export interface ProtocolMeta {
  version: number;
  status: string;
  matrix_version: string | null;
  dataset_version: string | null;
  model_version: string | null;
  created_at: string;
}

/**
 * Способ чтения объекта (#54): чем читать сканы и чертежи. Выбирается при загрузке —
 * текстового слоя хватает не всякому объекту, а модель нужна не всякому.
 */
export type ReadingMode = "layer" | "tesseract" | "model";
export const READING_MODES: ReadingMode[] = ["layer", "tesseract", "model"];

export interface ProcessStatus {
  process_id: string;
  object_id: string;
  object_name?: string;
  status: ProcessStatusName;
  scenario: string | null;
  upload_status: string[];
  /** способ чтения, выбранный при загрузке; null — способ сервиса */
  reading_mode?: ReadingMode | null;
  /** модель, выбранная при загрузке для режима «модель»; null — модель сервиса */
  model_name?: string | null;
  processing: Processing;
  progress?: { step: string; message: string; done?: number; total?: number; updated_at?: string } | null;
  files: { accepted: number; rejected: number; bytes: number };
  protocol_version: number | null;
  protocol?: ProtocolMeta;
  findings?: FindingCounts;
  /**
   * охват Матрицы последней версией протокола: сопоставлено параметров из всех; без сравнения —
   * параметры с правилом, по которым значения не сопоставлены: нет доказательств и несопоставимые
   */
  coverage?: { compared: number; total: number; missing_evidence?: number; not_comparable?: number } | null;
  /** готовность объекта (#39): на что опирается вывод — считается при разборе */
  readiness?: Readiness | null;
  /** что пересчитано при последней обработке, а что перенесено из прошлой версии (#60) */
  recompute?: Recompute | null;
  sync?: SyncState | null;
  created_at: string;
  updated_at: string;
  finalized_at: string | null;
}

export interface ObjectItem {
  object_id: string;
  name: string;
  processes: number;
  last_process?: ProcessStatus;
}

/** Прочитанный текст файла постранично: ответ GET /api/v1/process/{id}/text/{fileId} (#52). */
export interface FileText {
  file_id: string;
  relative_path?: string;
  total_pages: number;
  from: number;
  sources: Record<string, number>;
  pages: {
    page: number;
    text_source: string | null;
    kind: string | null;
    quality: string | null;
    chars: number;
    text: string;
  }[];
}

export interface FileItem {
  relative_path: string;
  status: "ACCEPTED" | "REJECTED";
  reject_code: string | null;
  reject_message: string | null;
  size_bytes: number | null;
  file_id: string | null;
  doc_stage: string | null;
  discipline?: string | null;
  pdf_pages: number | null;
  /** стадия и раздел, заданные инспектором руками (#39): разбор их не перезаписывает */
  stage_manual?: string | null;
  section_manual?: string | null;
  manual_by?: string | null;
  manual_at?: string | null;
  /** когда файл принят последний раз: принятый после сборки протокола в протокол не вошёл */
  uploaded_at?: string | null;
  /** редакции (#10): шифр, отметка редакции, цепочка и место в ней */
  document_code?: string | null;
  revision?: string | null;
  chain_id?: string | null;
  revision_status?: "CURRENT" | "SUPERSEDED" | "DUPLICATE" | "CLARIFICATION_REQUIRED" | string | null;
  /** инспектор назвал файл актуальной редакцией своей цепочки */
  revision_manual?: boolean | null;
  revision_manual_by?: string | null;
  revision_manual_at?: string | null;
}

/**
 * Что изменилось между редакциями одного документа (#19, #81). Указатель — пары и их
 * страницы без подробностей: реестр файлов показывает по нему «что изменилось», карточка
 * находки — менялся ли лист доказательства. Подробности пары — `api.fileChanges`.
 */
export interface RevisionPairHead {
  pair_id: string;
  chain_id: string | null;
  stage_group: string | null;
  mark: string | null;
  old_file_id: string;
  new_file_id: string;
  old_revision: string | null;
  new_revision: string | null;
  old_document: string | null;
  new_document: string | null;
  counts: Record<string, number>;
  looks_like_revision: boolean | null;
  /** страниц, где изменилось содержание; где содержание то же — служебные поля, перенос строк, текст сдвинулся между страницами */
  content_changed: number;
  service_only: number;
  /** отметка изменения проверялась (только рабочая документация) */
  checked: boolean;
  /** номера изменений, появившиеся в новой редакции */
  introduced: number[];
  /** листов, изменённых без отметки */
  unmarked: number;
}

export interface RevisionPageRef {
  old_page: number | null;
  new_page: number | null;
  sheet: number | null;
  status: "CHANGED" | "ADDED" | "REMOVED" | "UNREADABLE" | string;
  content_changed: boolean | null;
  /** REGISTERED, UNREGISTERED, NOT_NEEDED, UNKNOWN; null — отметка не проверялась */
  registration: string | null;
}

export interface RevisionPair extends RevisionPairHead {
  pages: RevisionPageRef[];
}

export interface RevisionPlace {
  /** SAME_PLACE, SHIFTED, RESIZED, RELAID — лист перекомпонован, мест изменений нет */
  layout: string;
  numbers?: string[];
  service?: string[];
  moved?: number;
  /** слов, ушедших на соседние страницы новой редакции и пришедших с соседних страниц прежней:
   * текст записки перетёк, это не изменение */
  flowed_out?: number;
  flowed_in?: number;
  content_removed?: number;
  content_added?: number;
  removed_sample?: string[];
  added_sample?: string[];
  /** рамки мест изменений в долях видимой страницы, Y сверху — как highlights доказательств */
  zones_old: number[][];
  zones_new: number[][];
}

export interface RevisionPage {
  old_page: number | null;
  new_page: number | null;
  sheet: number | null;
  /** номер листа прежней редакции: в записке страницы сдвигаются, лист 30 становится листом 32 */
  old_sheet?: number | null;
  status: string;
  what: string | null;
  content_changed: boolean | null;
  numbers: string[];
  changes: { was: string | null; now: string | null }[];
  place: RevisionPlace | null;
  registration: { status: string; why?: string; sheet?: number | null; numbers?: number[] } | null;
  /** есть ли картинки страниц для сравнения */
  rendered_old: boolean;
  rendered_new: boolean;
}

export interface FileChanges extends RevisionPairHead {
  pages: RevisionPage[];
}

export interface SideSource {
  text_source: "RECOGNIZED" | null;
  binding: string | null;
}

export type ConfidenceLevel = "HIGH" | "MEDIUM" | "LOW";

/** Уверенность в выводе записи (#80): процента нет — уровень выводится из признаков и показывается с ними. */
export interface Confidence {
  level: ConfidenceLevel;
  /** что снижает уверенность, начиная с того, что делает её низкой */
  down: string[];
  /** на что вывод опирается */
  up: string[];
}

export interface SpecialistVerdict {
  verdict: "violation" | "need_info" | "no_violation" | "hypothesis" | "drop";
  /** к чему решение (Р-108): kind — к виду гипотезы, record — к этой записи */
  scope?: "kind" | "record";
  reviewed: string | null;
  note: string | null;
  cases: string[];
}

export interface Evidence {
  stage: "PD" | "RD" | "ID" | string;
  file_id: string;
  pdf_page_number: number;
  quote?: string;
  /** имя файла, его SHA-256 и пометка редакции: инспектор проверяет, что сравнение шло по актуальной */
  document?: string | null;
  sha256?: string | null;
  revision?: string | null;
  /** статус утверждения документа; пока всегда UNKNOWN, это #10 */
  approval_status?: string | null;
  document_code?: string | null;
  document_sheet_number?: number | null;
  sheet_source?: string | null;
  page_count?: number | null;
  preview?: { aspect: number };
  highlights?: number[][];
  highlight_source?: "VALUE" | "ROWS" | "LOCATION" | "FINDING" | "REVISION" | null;
  /** «BBOX» — место на листе указано находкой, «PAGE_LEVEL» и «DOCUMENT_LEVEL» — рамки нет по существу */
  localization?: "BBOX" | "PAGE_LEVEL" | "DOCUMENT_LEVEL" | string | null;
}

export interface Finding {
  id: string;
  finding_id: string;
  protocol_version?: number;
  parameter_code: string | null;
  parameter_id?: number | null;
  location: string | null;
  violation_label: string | null;
  protocol_status: string | null;
  criticality: string | null;
  pd_value: string | null;
  rd_value: string | null;
  verification_status: string;
  reason_code: string | null;
  comment: string | null;
  decided_by: string | null;
  decided_at: string | null;
  title: string | null;
  locations: string[];
  location_type: string | null;
  comparison_result: string | null;
  matrix_scope: string | null;
  // находка черновика правила (#95): гипотеза до решения инспектора
  provisional?: boolean;
  detail: string | null;
  rule_basis: string | null;
  /** «RECOGNIZED», если значение стороны прочитано распознаванием, а не текстовым слоем (#52) */
  value_read_by?: { pd: string | null; rd: string | null; id?: string | null };
  origin: string | null;
  /** Запись перенесена из этой версии протокола: дозагрузка её не касалась (#60) */
  carried_from_version?: number | null;
  parent_finding_id: string | null;
  completeness_status?: string | null;
  completeness_reason?: string | null;
  revisions?: { pd: RevisionHistory[]; rd: RevisionHistory[] };
  /** третий массив (#42): значение исполнительной документации и итог сверки с ней */
  id_value?: string | null;
  id_check?: string | null;
  /** чем прочитано значение и к чему привязано (#41): RECOGNIZED — распознано машиной; binding SHEET/PAGE — с листа */
  sources?: { pd: SideSource | null; rd: SideSource | null; id: SideSource | null };
  needs_expert?: boolean;
  /** статус по легенде организатора к Матрице с учётом решения инспектора (#80): CANDIDATE, SUSPICION… */
  finding_status?: string | null;
  /** решение специалиста (#129, Р-86, Р-108): по виду гипотезы или по этой записи — поле scope */
  specialist?: SpecialistVerdict | null;
  /** уверенность в выводе (#80): уровень для отбора и признаки, из которых он сложен; null — сравнения не было */
  confidence?: Confidence | null;
  changed_after_decision?: { pd_value: string | null; rd_value: string | null; violation_label: string | null } | null;
  /**
   * Решение инспектора, которое пересборка не сняла, а вернула ему в кандидаты: после дозагрузки
   * автоматика расхождения больше не видит. Новое решение отметку снимает.
   */
  reopened?: {
    decision: string;
    by: string | null;
    at: string | null;
    reason_code?: string | null;
    comment?: string | null;
    version?: number;
    before?: { pd_value: string | null; rd_value: string | null; violation_label: string | null };
  } | null;
  /** когда и кто взял гипотезу свободного поиска в кандидаты (ТЗ 9.2) */
  promoted_at?: string | null;
  promoted_by?: string | null;
  /** инспектор вернул в кандидаты запись, проверенную автоматически без нарушения (#74) */
  disputed_at?: string | null;
  disputed_by?: string | null;
  evidence: Evidence[];
}

export interface RevisionEntry {
  file_id: string;
  document: string;
  revision: string;
  values: string[];
}

export interface RevisionHistory {
  used: RevisionEntry;
  superseded: RevisionEntry[];
}

export interface SyncState {
  status: "PENDING_SYNC" | "SYNCED" | "REJECTED" | "CANCELLED" | string;
  protocol_version: number;
  attempts: number;
  max_retries: number;
  next_attempt_at: string | null;
  last_error: string | null;
  last_status_code: number | null;
  external_id: string | null;
  synced_at: string | null;
}

export interface Notification {
  id: number;
  role: string;
  level: string;
  /** ACTION — требует действия человека, QUALITY — наблюдение о разборе (живёт в журнале), INFO */
  category?: string;
  message: string;
  process_id: string | null;
  created_at: string;
}

/** Состояние параметра Матрицы на карте дашборда (#83). */
export type CellState =
  | "VIOLATION"
  | "CANDIDATE"
  | "CLEAN"
  | "NOT_COMPARABLE"
  | "MISSING_EVIDENCE"
  | "NOT_APPLICABLE"
  | "NOT_CHECKED"
  | "OUT_OF_SCOPE"
  | "HYPOTHESIS";

/** Дашборд объекта (#83): сводка протокола и карта 132 параметров. */
export interface Dashboard {
  process_id: string;
  object_id: string;
  object_name: string;
  protocol: {
    version: number | null;
    status: string;
    status_text: string;
    preliminary: boolean;
    created_at: string | null;
    finalized_at: string | null;
  };
  scenario_text: string | null;
  stages: {
    stage: string;
    name: string;
    status: string;
    status_text: string;
    files_accepted: number;
    files_expected: number;
    files_rejected: number;
  }[];
  matrix: {
    total: number;
    compared: number;
    with_violation: number;
    with_candidate: number;
    missing_evidence: number;
    not_comparable: number;
    not_checked: number;
    out_of_scope?: number;
    hypothesis?: number;
    not_applicable: number;
  };
  records: Record<string, number>;
  sections: {
    section: string;
    parameters: number;
    implemented: number;
    compared: number;
    missing_evidence: number;
    not_comparable: number;
    not_checked: number;
    not_applicable?: number;
    out_of_scope?: number;
    hypothesis?: number;
    records: number;
    negatives: number;
    candidates: number;
    confirmed: number;
  }[];
  changes: { added: number; changed: number; removed: number; decided_changed: string[] } | null;
  sync: { status: string | null } | null;
  /** ход автоматики по версиям протокола: записей, кандидатов до решений, сопоставлено параметров */
  history: { version: number; created_at: string | null; records: number; candidates: number; compared: number }[];
  cells: {
    code: string;
    id: number | null;
    name: string | null;
    section: string | null;
    queue: number | null;
    critical: boolean | null;
    state: CellState;
    group: string;
    records: number;
    reason: string | null;
    /** у «не проверено» — пометка для инспектора: что нужно правилу и чего нет в пакете */
    note?: string | null;
    finding: string | null;
  }[];
}

/** Состояние записи на карте связей и в контексте находки (#82). */
export type LinkState = "VIOLATION" | "CANDIDATE" | "CLEAN" | "NOT_COMPARABLE" | "MISSING_EVIDENCE" | "SUSPICION";

/** Карта объекта «стадии × разделы» и находки, связывающие стадии (#82). */
export interface ObjectLinks {
  stages: Record<string, number>;
  /** смешанных комплектов РД и ИД: на карте они в колонке РД */
  mixed: number;
  grid: { stage: string; section: string; documents: number }[];
  links: { from: { stage: string; section: string }; to: { stage: string; section: string }; state: LinkState; findings: number }[];
  findings: {
    id: string;
    code: string | null;
    title: string | null;
    location: string | null;
    state: LinkState;
    stages: string[];
    cells: { stage: string; section: string }[];
  }[];
}

export interface LinkDocument {
  file_id: string;
  name: string;
  code: string | null;
  stage?: string | null;
  page_count?: number | null;
  revision?: string | null;
  revision_status?: string | null;
  current?: { file_id: string; name: string } | null;
  pages?: number[];
  quote?: string | null;
}

/** Контекст находки (#82): документы по стадиям, та же проверка, помещения. */
export interface FindingContext {
  finding: { id: string; finding_id: string; code: string | null; title: string | null; state: LinkState; location: string | null; location_type: string | null };
  stages: { stage: string; value: string | null; documents: LinkDocument[] }[];
  same_parameter: { total: number; items: { id: string; location: string | null; state: LinkState }[] };
  rooms: { room: string; total: number; cut: "SHORT" | "TANGLED" | null; superseded_skipped: number; documents: LinkDocument[] }[] | null;
  rooms_indexed: boolean;
}

/** Журнал обработки объекта (#83): как читали, что вышло и что сервис об этом сказал. */
export interface ProcessLog {
  process_id: string;
  object_id: string;
  status: string;
  processing: Processing;
  runs: {
    version: number;
    created_at: string | null;
    status: string;
    reading_mode: string | null;
    model_name: string | null;
    matrix_version: string | null;
    model_version: string | null;
    ocr: boolean | null;
    model: boolean | null;
    pages: number | null;
    findings: number | null;
    checks: number | null;
    labels: Record<string, number> | null;
    recompute: Recompute | null;
    changes: Record<string, number> | null;
    readiness: (Partial<Readiness> & { pages_low_quality?: number; by_text_source?: Record<string, number> }) | null;
  }[];
  notifications: Notification[];
  rejected_files: { code: string; count: number; message: string | null }[];
}

/**
 * Что пересчитано при последней обработке (#60). Дозагрузка не запускает объект заново:
 * пересчитываются только параметры, которых коснулись новые документы, остальные записи
 * переносятся из прошлой версии протокола вместе с решениями инспектора.
 */
export interface Recompute {
  full: boolean;
  reason: string | null;
  documents_read: number;
  documents_total: number | null;
  recomputed: number;
  carried_over: number;
}

/** Полнота обработки документации (#39, название по #74): на что опирается вывод по объекту. */
export interface Readiness {
  files: number;
  unsupported: number;
  stage_unknown: number;
  section_other: number;
  pages: number;
  pages_without_text: number;
  share_without_text: number;
  pages_low_quality: number;
  by_text_source?: Record<string, number>;
  ocr_enabled: boolean | null;
  model_enabled: boolean | null;
  /** чем объект прочитан на самом деле (#54): layer, tesseract, model */
  reading_mode?: ReadingMode | null;
  model_name?: string | null;
  /** во что обошлось чтение (#54): наблюдение, ограничителя расхода нет */
  read_seconds?: number;
  model_calls?: number;
  model_answered?: number;
  model_looped?: number;
  model_seconds?: number;
  model_cost_usd?: number;
  ocr_pages?: number;
  model_pages?: number;
}

export interface AuditEntry {
  id: number;
  user_id: string | null;
  action: string;
  details: Record<string, unknown>;
  timestamp: string;
}

export interface UploadResult {
  process_id: string;
  object_id: string;
  status: string;
  processing_queued: boolean;
  accepted: { relative_path: string; size_bytes: number }[];
  rejected: { relative_path: string; code: string; message: string }[];
  limits: Limits;
}

export class ApiFailure extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> | null = null,
  ) {
    super(message);
  }
}

const TOKEN_KEY = "inspector-token";

/** Роли стенда. Эксперт (Р-134) — права инспектора и страница правил, скрытая от остальных. */
export type Role = "inspector" | "admin" | "expert";

export interface Session {
  token: string;
  login: string;
  role: Role;
}

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(TOKEN_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function saveSession(value: Session | null): void {
  try {
    if (value) localStorage.setItem(TOKEN_KEY, JSON.stringify(value));
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // хранилище браузера недоступно: сессия живёт до перезагрузки страницы
  }
}

let session: Session | null = loadSession();
let onUnauthorized: () => void = () => {};

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

/** Кто вошёл: его пробные прогоны страница правил показывает снова, когда к правилу возвращаются. */
export function currentLogin(): string | null {
  return session?.login ?? null;
}

export function authHeader(): Record<string, string> {
  return session ? { authorization: `Bearer ${session.token}` } : {};
}

async function failure(response: Response): Promise<ApiFailure> {
  try {
    const body = await response.json();
    const error = body?.error ?? {};
    return new ApiFailure(response.status, error.code ?? "HTTP_ERROR", error.message ?? response.statusText, error.details ?? null);
  } catch {
    return new ApiFailure(response.status, "HTTP_ERROR", response.statusText);
  }
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: {
        ...(body !== undefined ? { "content-type": "application/json" } : {}),
        ...authHeader(),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiFailure(0, "NETWORK_ERROR", "Сервис недоступен. Проверьте, что он запущен, и повторите");
  }
  if (response.status === 401 && session) {
    logout();
    onUnauthorized();
  }
  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as T;
}

export async function login(loginName: string, password: string): Promise<Session> {
  const result = await request<{ access_token: string; role: Role }>("POST", "/api/v1/auth/token", {
    login: loginName,
    password,
  });
  session = { token: result.access_token, login: loginName, role: result.role };
  saveSession(session);
  return session;
}

export function logout(): void {
  session = null;
  saveSession(null);
}

export const api = {
  health: () => request<{ status: string; limits: Limits }>("GET", "/api/v1/health"),
  objects: () => request<{ objects: ObjectItem[] }>("GET", "/api/v1/objects"),
  status: (id: string) => request<ProcessStatus>("GET", `/api/v1/process/${id}/status`),
  files: (id: string) => request<{ files: FileItem[] }>("GET", `/api/v1/process/${id}/files`),
  findings: (id: string) =>
    request<{ findings: Finding[]; counts: FindingCounts; protocol_version: number | null }>(
      "GET",
      `/api/v1/process/${id}/findings`,
    ),
  protocol: (id: string) => request<Record<string, unknown>>("GET", `/api/v1/process/${id}/protocol`),
  audit: (id: string) => request<{ entries: AuditEntry[] }>("GET", `/api/v1/audit?process_id=${id}`),
  log: (id: string) => request<ProcessLog>("GET", `/api/v1/process/${id}/log`),
  summary: (id: string) => request<Dashboard>("GET", `/api/v1/process/${id}/summary`),
  links: (id: string) => request<ObjectLinks>("GET", `/api/v1/process/${id}/links`),
  context: (id: string, findingId: string) => request<FindingContext>("GET", `/api/v1/process/${id}/findings/${findingId}/context`),
  decide: (
    findingId: string,
    action: "CONFIRM" | "REJECT" | "CLARIFY" | "RESET" | "PROMOTE" | "DISPUTE",
    reasonCode?: string,
    comment?: string,
  ) =>
    request<{ finding: Finding; process_status: string; counts: FindingCounts }>(
      "POST",
      `/api/v1/findings/${findingId}/decision`,
      { action, ...(reasonCode ? { reason_code: reasonCode } : {}), ...(comment ? { comment } : {}) },
    ),
  split: (findingId: string, locations: string[], comment?: string) =>
    request<{ original_finding_id: string; created_findings: Finding[]; counts: FindingCounts; process_status: string }>(
      "POST",
      `/api/v1/findings/${findingId}/split`,
      { locations, ...(comment ? { comment } : {}) },
    ),
  notifications: () => request<{ notifications: Notification[] }>("GET", "/api/v1/notifications"),
  /** Что система прочитала в файле: текст страниц и чем каждая прочитана (#52). */
  fileText: (processId: string, fileId: string, from = 1, limit = 25) =>
    request<FileText>(
      "GET",
      `/api/v1/process/${processId}/text/${encodeURIComponent(fileId)}?from=${from}&limit=${limit}`,
    ),
  /** Что изменилось между редакциями: пары цепочек и их страницы, без подробностей (#81). */
  revisions: (processId: string) =>
    request<{ process_id: string; pairs: RevisionPair[] }>("GET", `/api/v1/process/${processId}/revisions`),
  /** Что изменилось в этой редакции относительно предыдущей: страницы, рамки, отметки (#81). */
  fileChanges: (processId: string, fileId: string) =>
    request<FileChanges>("GET", `/api/v1/process/${processId}/files/${encodeURIComponent(fileId)}/changes`),
  /** Стадия и раздел файла руками: пустая строка снимает правку (#39). */
  setFileStage: (processId: string, fileId: string, body: { doc_stage?: string; section?: string; comment?: string }) =>
    request<FileItem & { rebuild_required: boolean }>(
      "POST",
      `/api/v1/process/${processId}/files/${encodeURIComponent(fileId)}/stage`,
      body,
    ),
  /** Актуальная редакция цепочки по выбору инспектора (#10); false снимает выбор. */
  setFileRevision: (processId: string, fileId: string, body: { authoritative: boolean; comment?: string }) =>
    request<FileItem & { released: string[]; note: string }>(
      "POST",
      `/api/v1/process/${processId}/files/${encodeURIComponent(fileId)}/revision`,
      body,
    ),
  finalize: (id: string) => request<ProcessStatus>("POST", `/api/v1/process/${id}/finalize`),
  unfinalize: (id: string, reason: string) => request<ProcessStatus>("POST", `/api/v1/process/${id}/unfinalize`, { reason }),
  start: (id: string) => request<ProcessStatus>("POST", `/api/v1/process/${id}/start`),
  retrySync: (id: string) => request<ProcessStatus>("POST", `/api/v1/process/${id}/sync`),
  /** Без версии — черновик с разницей к последней версии; с версией — её состав. */
  dataset: (version?: string) =>
    request<DatasetView>("GET", `/api/v1/dataset${version ? `?dataset_version=${encodeURIComponent(version)}` : ""}`),
  datasetVersions: () => request<{ versions: DatasetVersion[] }>("GET", "/api/v1/dataset/versions"),
  /** Все правила сверки — только эксперту (Р-134). */
  rules: () => request<RulesView>("GET", "/api/v1/rules"),
  /** Пробный прогон правила: без variant — трасса рабочего правила, с variant — песочница (#222, #223). */
  ruleTestStart: (body: { code: string; variant?: Record<string, unknown> | null; process_ids?: string[]; trace?: boolean }) =>
    request<RuleTest>("POST", "/api/v1/rules/tests", body),
  ruleTest: (id: string) => request<RuleTest>("GET", `/api/v1/rules/tests/${id}`),
  /** Последние прогоны правила — чтобы вернуться к своему, уйдя со страницы. */
  ruleTests: (code: string) => request<{ tests: RuleTest[] }>("GET", `/api/v1/rules/tests?code=${encodeURIComponent(code)}`),
  /** Предложения правки правил из песочницы (#224): эксперт пишет, разработчик переносит и отмечает статус. */
  ruleProposals: (code?: string) =>
    request<{ proposals: RuleProposal[] }>("GET", `/api/v1/rules/proposals${code ? `?code=${encodeURIComponent(code)}` : ""}`),
  ruleProposal: (id: string) => request<RuleProposal>("GET", `/api/v1/rules/proposals/${id}`),
  ruleProposalCreate: (body: { test_id: string; comment?: string }) => request<RuleProposal>("POST", "/api/v1/rules/proposals", body),
  /** Прогоны по правилам: какие идут и когда был последний — для пометки в перечне правил. */
  ruleActivity: () => request<{ rules: RuleActivity[] }>("GET", "/api/v1/rules/tests/activity"),
  /** Примерное время прогона по объектам: по числу страниц и скорости последних прогонов стенда. */
  ruleTestEstimate: () =>
    request<{ speed: number; recent: number; processes: RuleEstimate[] }>("GET", "/api/v1/rules/tests/estimate"),
  datasetRelease: (comment?: string) =>
    request<DatasetVersion>("POST", "/api/v1/dataset/release", comment ? { comment } : {}),
  /** Отзыв версии (#74): версия остаётся в истории, но в дообучение не берётся. */
  datasetWithdraw: (version: string, reason: string) =>
    request<DatasetVersion>("POST", `/api/v1/dataset/versions/${encodeURIComponent(version)}/withdraw`, { reason }),
  /** Удаление чернового объекта (#74): только без финализированных протоколов, администратором. */
  deleteObject: (objectId: string) =>
    request<{ object_id: string; processes: number; files: number; blobs_removed: number }>(
      "DELETE",
      `/api/v1/objects/${encodeURIComponent(objectId)}`,
    ),
};

export type DatasetChange = "ADDED" | "CHANGED" | "UNCHANGED" | "REMOVED";

export interface DatasetItem {
  finding_row_id: string;
  object_id: string;
  process_id: string;
  protocol_version: number;
  finding_id: string;
  parameter_code: string | null;
  location: string | null;
  gold_label: "CONFIRMED_VIOLATION" | "NEGATIVE_VERIFIED";
  reason_code: string | null;
  comment: string | null;
  expert_id: string | null;
  decided_at: string | null;
  /** Только в черновике: чем запись отличается от последней выпущенной версии. */
  change?: DatasetChange;
}

export interface DatasetView {
  /** DRAFT или идентификатор версии */
  source: string;
  base_version: string | null;
  counts: { items: number; positives: number; negatives: number; added: number; changed: number; removed: number };
  items: DatasetItem[];
  removed: DatasetItem[];
}

/** Как правило находит значение (#222): шаблоны из файла правила, свой разбор в коде или модель по чертежам. */
export type Engine = "pattern" | "code" | "llm";
export type NumericKey = "threshold" | "trigger" | "tolerance" | "tolerance_pct";

/** Правило или черновик правила параметра Матрицы (GET /rules, Р-134). */
export interface RuleLogic {
  /** тип правила; null — снимок правил старый, типа в нём нет */
  engine: Engine | null;
  /** поля, которые песочница может поменять: compare, labels, exclude, features */
  editable: string[];
  /** текущие числа сравнения */
  values: Partial<Record<NumericKey, number>>;
  features: { name: string; pattern: string }[];
  /** что считается нарушением при этом виде сравнения */
  compare: string | null;
  /** порог и допуск словами: «порог Матрицы 1200 мм», «порог 1 %» */
  threshold: string | null;
  unit: string | null;
  /** подписи, по которым ищется значение, — регулярные выражения правила */
  labels: string[];
  exclude: string[];
  /** документы стадии: названия или выражение, если названий из него не выделить */
  documents: { stage: "PD" | "RD" | "ID"; names: string[]; pattern: string | null }[];
  /** значение с чертежей читает модель */
  model: { what: string | null; stages: string[]; sections: string[]; prompt: string | null } | null;
  /** расхождение по чертежу — только гипотеза */
  hypothesis_only: boolean;
  note: string | null;
}

export type RuleState = "ACTIVE" | "DRAFT" | "NOT_CHECKED" | "OUT_OF_SCOPE";

export interface RuleItem {
  code: string;
  id: number | null;
  name: string | null;
  section: string | null;
  queue: number | null;
  criticality: string | null;
  unit: string | null;
  sources: { pd: string | null; rd: string | null; id: string | null };
  trigger: string | null;
  state: RuleState;
  state_note: string | null;
  rule: RuleLogic | null;
  draft: RuleLogic | null;
}

export interface RulesView {
  fingerprint: string;
  published_at: string;
  counts: { parameters: number; active: number; draft: number; not_checked: number; out_of_scope: number };
  parameters: RuleItem[];
  /** решения специалиста по видам свободного поиска */
  guidance: {
    code: string;
    aspect: string | null;
    verdict: SpecialistVerdict["verdict"] | null;
    /** вид признан нарушением и идёт в сдачу без перевода инспектором */
    submit: boolean;
    note: string | null;
  }[];
}

/** Запись в итоге пробного прогона: без тяжёлых полей (#222, #223). */
export interface TestFinding {
  finding_id: string;
  locations: string[];
  violation_label: string | null;
  finding_status: string | null;
  pd_value: string | null;
  rd_value: string | null;
  id_value: string | null;
  detail: string | null;
  evidence: { stage: string; file_id: string; page: number }[];
  /** решение инспектора по этой записи в проверке объекта */
  decision?: string | null;
}

export interface TestCandidate {
  document: string | null;
  file_id: string | null;
  page: number | null;
  value: string | null;
  raw: string | null;
  label: string | null;
  snippet: string;
  chosen: boolean;
  recognized: boolean;
  stage?: string;
}

export interface TestTrace {
  stages: Record<"PD" | "RD" | "ID", { total: number; documents: number; chosen: string[]; candidates: TestCandidate[] }>;
  excluded: TestCandidate[];
  excluded_total: number;
}

export interface TestChange {
  finding_id: string;
  change: "added" | "removed" | "changed";
  before: TestFinding | null;
  after: TestFinding | null;
  decision?: string | null;
}

export interface TestResult {
  object_id: string;
  code: string;
  engine: Engine;
  pages_read: number;
  elapsed_s: number;
  base: { findings: TestFinding[] };
  trace?: TestTrace;
  variant?: { findings: TestFinding[]; changes: TestChange[]; same: number; trace?: TestTrace };
}

/** Прогоны правила: сколько их, сколько идёт, как и когда кончился последний и кто его поставил. */
export interface RuleActivity {
  code: string;
  runs: number;
  active: number;
  last_status: RuleTest["status"];
  last_variant: boolean;
  last_by: string | null;
  last_at: string;
}

export type ProposalStatus = "NEW" | "APPLIED" | "REJECTED";

/** Разница варианта по объектам — итогами. */
export interface ProposalTotals {
  objects: number;
  done: number;
  failed: number;
  changed_objects: number;
  changes: number;
  added: number;
  removed: number;
  changed: number;
  /** перемены записей, по которым инспектор уже решил */
  disputed: number;
}

/** Предложение правки правила из песочницы: вариант, разница по объектам снимком и статус. */
export interface RuleProposal {
  id: string;
  code: string;
  queue: number;
  draft: boolean;
  file: string;
  variant: Record<string, unknown>;
  comment: string | null;
  status: ProposalStatus;
  status_reason: string | null;
  status_by: string | null;
  status_at: string | null;
  created_by: string;
  created_at: string;
  test_id: string | null;
  fingerprint: string;
  totals: ProposalTotals;
  /** в карточке предложения: правило на момент предложения и перемены по объектам */
  rule?: Record<string, unknown>;
  objects?: {
    process_id: string;
    object_id: string | null;
    object_name: string | null;
    status: string;
    error: string | null;
    same: number;
    changes: TestChange[];
  }[];
}

/** Примерное время прогона на последней проверке объекта, секунд. */
export interface RuleEstimate {
  process_id: string;
  object_id: string;
  pages: number;
  trace_s: number;
  variant_s: number;
}

/** Пробный прогон правила: трасса или песочница. Ничего на стенде не меняет. */
export interface RuleTest {
  id: string;
  code: string;
  variant: Record<string, unknown> | null;
  trace: boolean;
  status: "QUEUED" | "RUNNING" | "DONE" | "FAILED";
  total: number;
  done: number;
  error: string | null;
  created_by?: string | null;
  /** сколько прогонов в очереди перед этим (в ответе на ход прогона) */
  ahead?: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  results?: {
    process_id: string;
    object_id: string | null;
    object_name: string | null;
    status: "QUEUED" | "DONE" | "FAILED";
    error: string | null;
    elapsed_s: number | null;
    result: TestResult | null;
  }[];
}

export interface DatasetVersion {
  dataset_version: string;
  items: number;
  positives: number;
  negatives: number;
  added: number;
  changed: number;
  removed: number;
  objects: string[];
  manifest_sha256: string;
  comment?: string | null;
  released_by?: string | null;
  released_at?: string | null;
  /** отозвана: в дообучение не берётся, но остаётся в истории (#74) */
  withdrawn_at?: string | null;
  withdrawn_by?: string | null;
  withdrawn_reason?: string | null;
}

/** Скачать файл из API с токеном: ссылка без заголовка авторизации не пройдёт. */
export async function download(path: string, fallbackName: string): Promise<Headers | null> {
  let response: Response;
  try {
    response = await fetch(path, { headers: authHeader() });
  } catch {
    throw new ApiFailure(0, "NETWORK_ERROR", "Сервис недоступен: проверьте соединение");
  }
  if (response.status === 401) {
    onUnauthorized();
  }
  if (!response.ok) {
    throw await failure(response);
  }
  const disposition = response.headers.get("content-disposition") ?? "";
  const name = disposition.match(/filename="([^"]+)"/)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return response.headers;
}

export function pageUrl(processId: string, fileId: string, page: number): string {
  return `/api/v1/process/${processId}/pages/${encodeURIComponent(fileId)}/${page}`;
}

/** Адрес исходного файла документа: том или чертёж, как его загрузили. */
export function sourceUrl(processId: string, fileId: string): string {
  return `/api/v1/process/${processId}/files/${encodeURIComponent(fileId)}/source`;
}

/**
 * Открыть файл сервиса в отдельной вкладке. Ссылкой это не сделать: запрос идёт с токеном,
 * поэтому файл забирается fetch и отдаётся вкладке object URL. `hash` — закладка внутри
 * документа, например «#page=84»: просмотрщик браузера открывает PDF сразу на ней.
 *
 * Вкладка открывается сразу по нажатию и показывает, сколько уже загружено: том проектной
 * документации весит десятки мегабайт, и через домен это полминуты. Открывать вкладку после
 * загрузки нельзя вдвойне: браузер считает её всплывающим окном не по нажатию и блокирует.
 */
export async function openInTab(url: string, hash = "", onProgress?: (done: number, total: number) => void): Promise<void> {
  const tab = window.open("", "_blank");
  if (!tab) throw new Error("Браузер не дал открыть вкладку: разрешите всплывающие окна");
  const say = (text: string) => {
    try {
      tab.document.body.innerHTML = `<p style="font:14px system-ui;color:#3c3d40;padding:24px">${text}</p>`;
    } catch {
      // вкладку закрыли или увели на другой адрес: ход загрузки показывать уже некому
    }
  };
  try {
    tab.document.write("<!doctype html><title>Файл открывается…</title><body>");
    // Документ закрывается сразу: у незакрытого разбор остаётся открытым, и переход
    // на object URL в конце загрузки браузер откладывает до бесконечности.
    tab.document.close();
    say("Файл загружается…");
    const response = await fetch(url, { headers: authHeader() });
    if (!response.ok) throw new Error((await failure(response)).message);
    const total = Number(response.headers.get("content-length") ?? 0);
    const type = response.headers.get("content-type") ?? "application/octet-stream";
    let blob: Blob;
    if (response.body && total > 0) {
      const reader = response.body.getReader();
      const parts: BlobPart[] = [];
      let done = 0;
      for (;;) {
        const chunk = await reader.read();
        if (chunk.done) break;
        parts.push(chunk.value as BlobPart);
        done += chunk.value.length;
        onProgress?.(done, total);
        say(`Файл загружается: ${Math.round((done / total) * 100)} % из ${Math.round(total / 1024 / 1024)} МБ`);
      }
      blob = new Blob(parts, { type });
    } else {
      blob = await response.blob();
    }
    const object = URL.createObjectURL(blob);
    tab.location.replace(object + hash);
    // Формат, который браузер не показывает сам (DOCX, XML), уходит в загрузки, и вкладка
    // остаётся нашей: тогда говорим, что файл уже скачан. Если лист открылся, заголовок
    // у вкладки уже не наш, и мы её не трогаем — иначе затрём показанный документ.
    setTimeout(() => {
      try {
        if (tab.document.title === "Файл открывается…") say("Файл ушёл в загрузки браузера: этот лист можно закрыть.");
      } catch {
        // вкладка показывает документ и больше нам не принадлежит
      }
    }, 2000);
    // вкладка уже держит содержимое; адрес освобождается, когда он ей точно не нужен
    setTimeout(() => URL.revokeObjectURL(object), 120000);
  } catch (e) {
    say(`Файл не открылся: ${(e as Error).message}`);
    throw e;
  }
}

/** Загрузка пакета через XMLHttpRequest: у fetch нет событий хода отправки. */
export function uploadBatch(form: FormData, onProgress: (sent: number, total: number) => void): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/v1/documents/upload");
    if (session) xhr.setRequestHeader("authorization", `Bearer ${session.token}`);
    xhr.upload.onprogress = (event) => onProgress(event.loaded, event.total);
    xhr.onerror = () => reject(new ApiFailure(0, "NETWORK_ERROR", "Соединение прервано при загрузке"));
    xhr.onload = () => {
      let body: any = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // тело не JSON: ответ прокси или обрыв
      }
      if (xhr.status === 202) {
        resolve(body as UploadResult);
      } else {
        const error = body?.error ?? {};
        reject(new ApiFailure(xhr.status, error.code ?? "HTTP_ERROR", error.message ?? `Ошибка ${xhr.status}`, error.details ?? null));
      }
    };
    xhr.send(form);
  });
}
