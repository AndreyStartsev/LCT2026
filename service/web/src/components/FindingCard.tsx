import { useEffect, useRef, useState, type ReactElement } from "react";
import type { Confidence, Evidence, Finding, RevisionHistory, SideSource } from "../api";
import { REJECT_HINT } from "../keys";
import {
  APPROVAL,
  COMPARISON,
  CONFIDENCE,
  criticalityWeight,
  LABEL,
  LOCATION_TYPE,
  REASONS,
  SHEET_TOLERANCE_SIDES,
  STAGE,
  VERDICT,
  when,
  ruleCodeHint,
} from "../labels";
import { isCandidate, isHypothesis, isSheetTolerance, usesStage } from "../protocol";
import FindingContextView from "./FindingContextView";
import { ConfidenceMark, SpecialistMark } from "./Marks";
import Tip from "./Tip";

const NOT_COMPARED = new Set(["COMPARISON_IMPOSSIBLE", "MISSING_DOCUMENT"]);

interface Props {
  finding: Finding;
  editable: boolean;
  busy: boolean;
  rejectOpen: boolean;
  onRejectOpen: (open: boolean) => void;
  onDecide: (action: "CONFIRM" | "REJECT" | "CLARIFY" | "RESET" | "PROMOTE" | "DISPUTE", reason?: string, comment?: string) => void;
  onSplit: (locations: string[]) => void;
  /**
   * Черновик комментария живёт на экране проверки, по записи: клавиши 1 и 3 отправляют его
   * вместе с решением, а при листании ↑ ↓ он не пропадает (разбор интерфейса, п. 8).
   */
  comment: string;
  onComment: (text: string) => void;
  /** Показать эту страницу-доказательство справа: строка источника в карточке — кнопка (п. 13). */
  onPickSource?: (evidence: Evidence) => void;
  /** #82: связи документов этой записи; без процесса панели нет. */
  processId?: string;
  onOpenFinding?: (id: string) => void;
  onError?: (message: string) => void;
}

/** Источник значения: файл, страница и лист, а под ними — чем этот источник подтверждён. */
function Source({ e, onPick }: { e: Evidence; onPick?: (e: Evidence) => void }) {
  const where = (
    <>
      {e.file_id} · стр. {e.pdf_page_number}
      {e.page_count ? ` из ${e.page_count}` : ""}
      {e.document_sheet_number != null ? ` · лист ${e.document_sheet_number}` : ""}
    </>
  );
  return (
    <span className="src">
      {/* по щелчку эта страница показывается справа, в карточке страниц своей стороны */}
      {onPick ? (
        <button type="button" className="src-where src-pick" title="Показать эту страницу справа" onClick={() => onPick(e)}>
          {where}
        </button>
      ) : (
        <span className="src-where">{where}</span>
      )}
      <span className="src-what">
        {e.revision && <span title="Редакция документа по пометке в имени файла">ред. {e.revision}</span>}
        {e.approval_status && e.approval_status !== "UNKNOWN" && (
          <span title="Статус утверждения документа">{APPROVAL[e.approval_status] ?? e.approval_status}</span>
        )}
        {e.sha256 && (
          <span className="sha" title={`SHA-256 файла: ${e.sha256}`}>
            sha {e.sha256.slice(0, 12)}
          </span>
        )}
      </span>
    </span>
  );
}

/** Привязка значения по элементу (#41): всё, что не из указаний, инспектор должен видеть. */
const BINDING_NOTE: Record<string, string> = {
  SHEET: "значение с листа, не из указаний",
  PAGE: "значение со страницы, не из указаний",
  PATH: "значение по пути файла",
};
const STAGE_EMPTY: Record<string, string> = { PD: "проект", RD: "рабочая документация", ID: "исполнительная документация" };

function Side({
  stage,
  value,
  evidence,
  revisions,
  recognized,
  source,
  label,
  hint,
  onPick,
}: {
  stage: "PD" | "RD" | "ID";
  onPick?: (e: Evidence) => void;
  /** подпись стороны вместо стадии: у гипотезы сравнения редакций — «изм. 1», «изм. 3» (#81) */
  label?: string;
  /** подсказка к подписи стороны: откуда сторона, если это не просто стадия */
  hint?: string;
  value: string | null;
  evidence: Evidence[];
  revisions: RevisionHistory[];
  /** значение прочитано распознаванием, а не текстовым слоем (#52) */
  recognized?: boolean;
  /** привязка значения элемента (#41): всё, что не из указаний, инспектор должен видеть */
  source?: SideSource | null;
}) {
  const first = evidence[0];
  const binding = source?.binding ? BINDING_NOTE[source.binding] : null;
  const head = <span className={hint ? "stage with-tip" : "stage"}>{label ?? STAGE[stage]}</span>;
  return (
    <div className="side">
      <div className="side-head">
        {hint ? <Tip text={hint}>{head}</Tip> : head}
        <span className="side-doc" title={first?.document ?? undefined}>
          {first?.document_code ?? (first ? first.file_id : STAGE_EMPTY[stage])}
        </span>
      </div>
      <div className={`side-value${value ? "" : " absent"}`}>{value ?? "значение не найдено"}</div>
      {recognized && (
        <div className="side-read" title="Текст страницы распознан машиной: цифры она путает, сверьтесь с листом">
          прочитано распознаванием
        </div>
      )}
      {value && binding && (
        <div className="side-marks">
          <span className="tag">{binding}</span>
        </div>
      )}
      {first?.quote && <div className="side-quote">{first.quote}</div>}
      {revisions.map((r) => (
        <div key={r.used.file_id} className="side-revisions">
          Сравнение по редакции «{r.used.revision}». Устаревшие:{" "}
          {r.superseded.map((old, i) => (
            <span key={old.file_id}>
              {i > 0 ? "; " : ""}«{old.revision}» — {old.values.join(", ")}
            </span>
          ))}
        </div>
      ))}
      {evidence.length > 0 && (
        <div className="side-src">
          {evidence.map((e, i) => (
            <Source key={`${e.file_id}-${e.pdf_page_number}-${i}`} e={e} onPick={onPick} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Уверенность в выводе (#80): уровень и признаки, из которых он сложен. Процента нет — число
 * «72 %» нечем обосновать, а признаки инспектор может проверить на листе сам. В карточке —
 * значок и слово; что снижает уверенность и на что она опирается — подсказкой по наведению
 * (и с клавиатуры): строки обоснований отнимали высоту у значений и решения.
 */
function ConfidenceView({ confidence }: { confidence: Confidence }) {
  const word = CONFIDENCE[confidence.level]?.word ?? confidence.level;
  const why = [
    confidence.down.length > 0 ? `Что снижает уверенность: ${confidence.down.join("; ")}` : "",
    confidence.up.length > 0 ? `Опирается на: ${confidence.up.join("; ")}` : "",
  ]
    .filter(Boolean)
    .join("\n");
  const head = (
    <span className={why ? "conf-head has-why" : "conf-head"} tabIndex={why ? 0 : undefined}>
      <ConfidenceMark confidence={confidence} size={15} always hint={false} />
      <span className="conf-word">{word}</span>
    </span>
  );
  return <div className="confidence">{why ? <Tip text={why}>{head}</Tip> : head}</div>;
}

export function CardBody({ finding, onPickSource }: { finding: Finding; onPickSource?: (e: Evidence) => void }) {
  const pd = finding.evidence.filter((e) => e.stage === "PD");
  const rd = finding.evidence.filter((e) => e.stage === "RD");
  const idEvidence = finding.evidence.filter((e) => e.stage === "ID");
  // третья колонка (#42): исполнительная документация, если по ней есть значение или страница
  const withId = Boolean(finding.id_value) || idEvidence.length > 0;
  const weight = criticalityWeight(finding.criticality);
  const verdict = VERDICT[finding.verification_status];
  const hypothesis = isHypothesis(finding);
  // Гипотеза сравнения редакций (#81): стороны — прежняя и новая редакции одного листа, а не ПД и РД.
  // Первое доказательство — новая редакция, остальные той же редакции — тоже, прочие — прежняя.
  const revisionPair = finding.parameter_code === "FREE-REV-UNMARKED";
  const newest = revisionPair ? finding.evidence.filter((e) => e.revision === finding.evidence[0]?.revision) : [];
  const older = revisionPair ? finding.evidence.filter((e) => e.revision !== finding.evidence[0]?.revision) : [];
  // Сверка исполнительной схемы с допусками того же листа: стороны — допуск и отклонение с листа ИД.
  // Прежде допуск стоял под «ПД» с пустой страницей проекта, хотя проект в проверке не участвует.
  const sheetTolerance = isSheetTolerance(finding);
  // Стадии, которых проверка свободного поиска не касается, не показываются рамкой «не найдено»;
  // запись совсем без значений и страниц показывает обе, как раньше
  const bare = !usesStage(finding, "PD") && !usesStage(finding, "RD") && !withId;
  const showPd = bare || usesStage(finding, "PD");
  const showRd = bare || usesStage(finding, "RD");
  const count = [showPd, showRd, withId].filter(Boolean).length;
  const sidesClass = count === 3 ? "sides sides-three" : count === 1 ? "sides sides-one" : "sides";
  return (
    <>
      <div className="card-id">
        <Tip text={ruleCodeHint(finding.parameter_code)}>
          <span className="chip solid">{finding.parameter_code ?? "вне Матрицы"}</span>
        </Tip>
        {finding.violation_label && <span className="chip">{LABEL[finding.violation_label] ?? finding.violation_label}</span>}
        {/* у несравнённой записи конвейер ставит VALUE_MISMATCH по умолчанию: сравнения не было, и чип бы вводил в заблуждение */}
        {finding.comparison_result && !NOT_COMPARED.has(finding.violation_label ?? "") && (
          <span className="chip">{COMPARISON[finding.comparison_result] ?? finding.comparison_result}</span>
        )}
        {hypothesis && (
          <span className="chip">{finding.provisional ? "гипотеза черновика правила" : "гипотеза свободного поиска"}</span>
        )}
        {/* #41: распознанное значение, расхождение со слоем, нарушение по распознанному — решает инспектор, не система */}
        {finding.needs_expert && !hypothesis && (
          <span className="chip chip-expert" title="Система не решает сама: причина названа в поле «Расхождение»">
            требует подтверждения
          </span>
        )}
        {/* Решение специалиста по виду гипотезы (#129, Р-86): мини-пометка, слова специалиста — в подсказке */}
        {finding.specialist && <SpecialistMark specialist={finding.specialist} size={18} />}
        {finding.origin === "INSPECTOR_SPLIT" && <span className="chip">часть разделённой записи</span>}
        {/* #60: дозагруженные документы этой записи не касались — она и решение по ней из прошлой версии */}
        {finding.carried_from_version != null && (
          <span className="chip" title="Дозагруженные документы эту запись не касались: она перенесена из прошлой версии протокола вместе с решением">
            из версии {finding.carried_from_version}
          </span>
        )}
        <span className="mono small">{finding.finding_id}</span>
      </div>

      {/* после решения фокус встаёт сюда: следующая «1» — решение, а не цифра в поле комментария (п. 7) */}
      <h3 className="card-title" id="finding-card-title" tabIndex={-1}>
        {finding.title ?? finding.parameter_code ?? "Запись протокола"}
      </h3>

      {revisionPair ? (
        <div className="sides">
          <Side
            onPick={onPickSource}
            stage="RD"
            label={older[0]?.revision ?? "прежняя редакция"}
            value={older.length ? "прежний вид листа" : null}
            evidence={older}
            revisions={[]}
          />
          <Side
            onPick={onPickSource}
            stage="RD"
            label={newest[0]?.revision ?? "новая редакция"}
            value={finding.rd_value}
            evidence={newest}
            revisions={[]}
          />
        </div>
      ) : sheetTolerance ? (
        <div className="sides">
          <Side
            onPick={onPickSource}
            stage="ID"
            label={`${STAGE.ID} · допуск`}
            hint={SHEET_TOLERANCE_SIDES}
            value={finding.pd_value}
            // цитата доказательства — строка отклонений; у стороны допуска её не показываем
            evidence={idEvidence.map((e) => ({ ...e, quote: undefined }))}
            revisions={[]}
            recognized={finding.value_read_by?.id === "RECOGNIZED"}
          />
          <Side
            onPick={onPickSource}
            stage="ID"
            label={`${STAGE.ID} · отклонение`}
            value={finding.id_value ?? null}
            evidence={idEvidence}
            revisions={[]}
            recognized={finding.value_read_by?.id === "RECOGNIZED"}
            source={finding.sources?.id}
          />
        </div>
      ) : (
      <div className={sidesClass}>
        {showPd && (
          <Side
            onPick={onPickSource}
            stage="PD"
            value={finding.pd_value}
            evidence={pd}
            revisions={finding.revisions?.pd ?? []}
            recognized={finding.value_read_by?.pd === "RECOGNIZED"}
            source={finding.sources?.pd}
          />
        )}
        {showRd && (
          <Side
            onPick={onPickSource}
            stage="RD"
            value={finding.rd_value}
            evidence={rd}
            revisions={finding.revisions?.rd ?? []}
            recognized={finding.value_read_by?.rd === "RECOGNIZED"}
            source={finding.sources?.rd}
          />
        )}
        {withId && (
          <Side
            onPick={onPickSource}
            stage="ID"
            value={finding.id_value ?? null}
            evidence={idEvidence}
            revisions={[]}
            recognized={finding.value_read_by?.id === "RECOGNIZED"}
            source={finding.sources?.id}
          />
        )}
      </div>
      )}
      {finding.id_check && <div className="id-check small">{finding.id_check}</div>}

      <dl className="kv">
        <dt>Локация</dt>
        <dd>
          {finding.locations.length > 0
            ? finding.locations.map((l) => (
                <span key={l} className="room">
                  {l}
                </span>
              ))
            : finding.location ?? "—"}
          {finding.location_type && <span className="muted"> · {LOCATION_TYPE[finding.location_type] ?? finding.location_type}</span>}
        </dd>
        {finding.detail && (
          <>
            <dt>Расхождение</dt>
            <dd className="detail">{finding.detail}</dd>
          </>
        )}
        {/* Нормативная ссылка: параметр Матрицы и его триггер — то, чем нарушение обосновано */}
        <dt>По Матрице</dt>
        <dd>
          {finding.parameter_code ? (
            <span className="mono">{finding.parameter_code}</span>
          ) : (
            "вне Матрицы: свободный поиск"
          )}
        </dd>
        {finding.rule_basis && (
          <>
            <dt>Норма</dt>
            <dd>{finding.rule_basis}</dd>
          </>
        )}
        <dt>Критичность</dt>
        <dd>{finding.criticality ? <span className={`crit ${weight ?? ""}`}>{finding.criticality}</span> : "не назначается"}</dd>
        <dt>Уверенность</dt>
        <dd>
          {finding.confidence ? (
            <ConfidenceView confidence={finding.confidence} />
          ) : (
            <span className="muted">
              {NOT_COMPARED.has(finding.violation_label ?? "")
                ? "не оценивается: сравнения не было"
                : "не оценивается: уровень считается по тому, как правила прочитали значения, а у этой записи их нет"}
            </span>
          )}
        </dd>
        <dt>Статус</dt>
        <dd>
          {hypothesis
            ? "Гипотеза — вне итогов нарушений, пока не взята в кандидаты"
            : verdict
              ? verdict.word
              : finding.verification_status === "PENDING"
                ? "Кандидат — решение за инспектором"
                : "Решение не требуется"}
          {/* код легенды организатора — по нему запись ищут в протоколе и в файле сдачи */}
          {finding.finding_status && <span className="mono small muted"> · {finding.finding_status}</span>}
        </dd>
      </dl>

      {finding.comment && <p className="note">{finding.comment}</p>}
    </>
  );
}

export default function FindingCard({
  finding,
  editable,
  busy,
  rejectOpen,
  onRejectOpen,
  onDecide,
  onSplit,
  comment,
  onComment,
  onPickSource,
  processId,
  onOpenFinding,
  onError,
}: Props) {
  const [reason, setReason] = useState<string | null>(null);
  const [splitOpen, setSplitOpen] = useState(false);
  // Связи документов (#82) свёрнуты по умолчанию и грузятся, только когда их раскрыли;
  // раскрытая панель остаётся раскрытой при переходе к следующей записи.
  const [linksOpen, setLinksOpen] = useState(false);
  const reasonsRef = useRef<HTMLDivElement | null>(null);
  const commentRef = useRef<HTMLTextAreaElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);

  // Новая запись открывается с начала: прежде прокрутка переходила от предыдущей, и следующая
  // карточка открывалась с середины — с «Нормы», без заголовка и значений (п. 7).
  useEffect(() => {
    setReason(null);
    setSplitOpen(false);
    if (bodyRef.current) bodyRef.current.scrollTop = 0;
  }, [finding.id]);

  // Форма отклонения открывается с фокусом на причинах: 1–5 выбирают её с клавиатуры,
  // после выбора фокус уходит в комментарий, и отклонение укладывается в три действия.
  useEffect(() => {
    if (rejectOpen) reasonsRef.current?.focus();
  }, [rejectOpen]);

  function pickReason(code: string) {
    setReason(code);
    commentRef.current?.focus();
  }

  const rejectReady = !!reason && !!comment.trim();
  function submitReject() {
    if (rejectReady && !busy) onDecide("REJECT", reason ?? undefined, comment.trim());
  }

  const verdict = VERDICT[finding.verification_status];
  const hypothesis = isHypothesis(finding);
  let foot: ReactElement;

  if (!isCandidate(finding)) {
    foot = (
      <div className="foot-note">
        {finding.violation_label === "NO_VIOLATION"
          ? "Проверено автоматически: расхождения нет (NEGATIVE_VERIFIED), решение инспектора не требуется."
          : finding.completeness_status === "NOT_COMPARABLE"
            ? `Источники нельзя сопоставить (NOT_COMPARABLE)${finding.completeness_reason ? `: ${finding.completeness_reason}` : ""}. Это качество входных данных, а не нарушение.`
            : `Нет документа или фрагмента (MISSING_EVIDENCE)${finding.completeness_reason ? `: ${finding.completeness_reason}` : ""}. Это качество входных данных, а не нарушение.`}
        {/* Автоматика ошибается: не то значение прочитано, не та редакция сопоставлена (#74).
            Инспектор должен иметь возможность не согласиться и вернуть запись в работу. */}
        {finding.violation_label === "NO_VIOLATION" && editable && (
          <div className="foot-actions">
            <button type="button" className="btn" disabled={busy} onClick={() => onDecide("DISPUTE", undefined, comment.trim() || undefined)}>
              Вернуть в кандидаты
            </button>
            <span className="small muted">
              Запись вернётся в кандидаты и будет ждать вашего решения — подтвердить, отклонить или уточнить
            </span>
          </div>
        )}
      </div>
    );
  } else if (verdict) {
    foot = (
      <div className={`decided tone-${verdict.tone}`}>
        <span className="glyph">{verdict.glyph}</span>
        <span>
          <b>{verdict.word}</b>
          {finding.reason_code && ` · ${REASONS.find((r) => r.code === finding.reason_code)?.label ?? finding.reason_code}`}
          <br />
          <span className="mono small muted">
            {finding.decided_by ?? "—"} · {when(finding.decided_at)}
            {finding.reason_code ? ` · ${finding.reason_code}` : ""}
          </span>
          {finding.comment && <span className="decided-comment">{finding.comment}</span>}
          {finding.changed_after_decision && (
            <span className="stale">
              <br />
              После решения значения изменились: было ПД {finding.changed_after_decision.pd_value ?? "—"}, РД{" "}
              {finding.changed_after_decision.rd_value ?? "—"}. Пересмотрите решение.
            </span>
          )}
        </span>
        {editable && (
          <button className="undo" type="button" disabled={busy} onClick={() => onDecide("RESET")}>
            Вернуть в кандидаты
          </button>
        )}
      </div>
    );
  } else if (!editable) {
    foot = <div className="foot-note">Решение недоступно: протокол финализирован или идёт обработка.</div>;
  } else if (hypothesis) {
    // ТЗ 9.2: гипотеза вне итогов нарушений. Решение по ней сервер не примет,
    // пока инспектор не взял её в кандидаты, — об этом и говорит карточка.
    foot = (
      <div className="hypothesis">
        <p className="foot-note">
          Найдено вне Матрицы. В итоги нарушений запись не входит и финализацию не задерживает. Чтобы принять по ней
          решение, возьмите её в кандидаты.
        </p>
        <textarea
          id={`hypothesis-comment-${finding.id}`}
          className="comment"
          placeholder="Комментарий — необязателен"
          rows={2}
          value={comment}
          onChange={(e) => onComment(e.target.value)}
        />
        <div className="reason-actions">
          <button
            type="button"
            className="act act-clarify"
            disabled={busy}
            onClick={() => onDecide("PROMOTE", undefined, comment.trim() || undefined)}
          >
            <span className="glyph">→</span> Взять в кандидаты
          </button>
        </div>
      </div>
    );
  } else if (rejectOpen) {
    foot = (
      <div className="reasons">
        <div className="reasons-head">Причина отклонения — обязательна</div>
        <div
          className="reason-grid"
          role="radiogroup"
          aria-label="Причина отклонения"
          tabIndex={-1}
          ref={reasonsRef}
          onKeyDown={(e) => {
            // зажатая «2» открыла форму и повторяется: повтор не должен выбрать причину
            // и печатать цифры в комментарий — причину выбирают отдельным нажатием
            if (e.repeat) {
              e.preventDefault();
              return;
            }
            if (e.ctrlKey || e.metaKey) {
              if (e.key === "Enter") {
                e.preventDefault();
                submitReject();
              }
              return;
            }
            const n = Number(e.key);
            if (n >= 1 && n <= REASONS.length) {
              e.preventDefault();
              pickReason(REASONS[n - 1].code);
            }
          }}
        >
          {REASONS.map((r, i) => (
            <button
              key={r.code}
              type="button"
              className="reason"
              role="radio"
              aria-checked={reason === r.code}
              title={`Клавиша ${i + 1} · код ${r.code}`}
              onClick={() => pickReason(r.code)}
            >
              {r.label}
              <span className="code">{r.code}</span>
              {/* клавиша — цифрой в углу, как у кнопок решения: так пять причин встают в один ряд */}
              <span className="reason-key" aria-hidden="true">
                {i + 1}
              </span>
            </button>
          ))}
        </div>
        <textarea
          id={`reject-comment-${finding.id}`}
          className="comment"
          ref={commentRef}
          placeholder="Комментарий к отклонению — обязателен по ТЗ"
          rows={2}
          value={comment}
          onChange={(e) => onComment(e.target.value)}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
              e.preventDefault();
              submitReject();
            }
          }}
        />
        <div className="reason-actions">
          <button type="button" className="act act-reject" disabled={busy || !rejectReady} onClick={submitReject}>
            <span className="glyph">✗</span> Отклонить
          </button>
          <button type="button" className="btn" onClick={() => onRejectOpen(false)}>
            Отмена
          </button>
        </div>
        <div className="key-hint">{REJECT_HINT}</div>
      </div>
    );
  } else {
    foot = (
      <>
        {/* Решение принимает инспектор, не система: пересборка, после которой расхождения больше нет,
            не снимает его решение, а возвращает запись ему — с тем, что и по каким значениям было решено */}
        {finding.reopened && (
          <div className="reopened small">
            <b>Решить заново.</b> Прежнее решение — «{VERDICT[finding.reopened.decision]?.word ?? finding.reopened.decision}»
            {finding.reopened.by ? ` (${finding.reopened.by} · ${when(finding.reopened.at ?? null)})` : ""}
            {finding.reopened.before
              ? ` по значениям ПД ${finding.reopened.before.pd_value ?? "—"}, РД ${finding.reopened.before.rd_value ?? "—"}`
              : ""}
            . После дозагрузки автоматика расхождения больше не видит, поэтому запись вернулась к вам.
            {finding.reopened.comment && <span className="decided-comment">{finding.reopened.comment}</span>}
          </div>
        )}
        {/* ТЗ 9.3: решение содержит комментарий инспектора — не только у отклонения */}
        <textarea
          id={`decision-comment-${finding.id}`}
          className="comment"
          ref={commentRef}
          placeholder="Комментарий инспектора — необязателен при подтверждении и уточнении"
          rows={2}
          value={comment}
          onChange={(e) => onComment(e.target.value)}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !busy) {
              e.preventDefault();
              onDecide("CONFIRM", undefined, comment.trim() || undefined);
            }
          }}
        />
        {/* Запись вернул в кандидаты сам инспектор (#74): видно, кто и когда, и возврат
            можно отменить — иначе случайное нажатие исправить нечем. */}
        {finding.disputed_at && (
          <div className="foot-actions disputed-note">
            <span className="small">
              Автоматическая проверка оспорена: {finding.disputed_by ?? "—"} · {when(finding.disputed_at)}
            </span>
            <button type="button" className="undo" disabled={busy} onClick={() => onDecide("RESET")}>
              отменить возврат
            </button>
          </div>
        )}
        <div className="actions">
          <button
            className="act act-confirm"
            type="button"
            disabled={busy}
            onClick={() => onDecide("CONFIRM", undefined, comment.trim() || undefined)}
            title="Клавиша 1; из комментария — Ctrl+Enter"
          >
            <span className="glyph">✓</span> Подтвердить
            <span className="act-key" aria-hidden="true">
              1
            </span>
          </button>
          <button className="act act-reject" type="button" disabled={busy} onClick={() => onRejectOpen(true)} title="Клавиша 2">
            <span className="glyph">✗</span> Отклонить
            <span className="act-key" aria-hidden="true">
              2
            </span>
          </button>
          <button
            className="act act-clarify"
            type="button"
            disabled={busy}
            onClick={() => onDecide("CLARIFY", undefined, comment.trim() || undefined)}
            title="Клавиша 3"
          >
            <span className="glyph">?</span> Уточнить
            <span className="act-key" aria-hidden="true">
              3
            </span>
          </button>
        </div>
        {finding.verification_status === "PENDING" && finding.locations.length > 1 && (
          <div className="split">
            {!splitOpen ? (
              <button type="button" className="link" onClick={() => setSplitOpen(true)}>
                Разделить на {finding.locations.length} записи по локациям
              </button>
            ) : (
              <div className="split-confirm">
                <span>
                  Каждая локация станет отдельным кандидатом со своим решением:{" "}
                  {finding.locations.map((l) => (
                    <span key={l} className="room">
                      {l}
                    </span>
                  ))}
                </span>
                <button type="button" className="btn" disabled={busy} onClick={() => onSplit(finding.locations)}>
                  Разделить
                </button>
                <button type="button" className="btn" onClick={() => setSplitOpen(false)}>
                  Отмена
                </button>
              </div>
            )}
          </div>
        )}
      </>
    );
  }

  return (
    <>
      <div className="card-body" ref={bodyRef}>
        <CardBody finding={finding} onPickSource={onPickSource} />
        {processId && (
          <div className="lk-panel">
            <button type="button" className="lk-panel-head" aria-expanded={linksOpen} onClick={() => setLinksOpen(!linksOpen)}>
              <span className="lk-caret" aria-hidden="true">
                {linksOpen ? "▾" : "▸"}
              </span>
              Связи документов
              <span className="muted small">документы по стадиям, та же проверка на объекте, помещения</span>
            </button>
            {linksOpen && (
              <FindingContextView
                processId={processId}
                findingId={finding.id}
                compact
                onOpenFinding={onOpenFinding}
                onError={onError}
              />
            )}
          </div>
        )}
      </div>
      <div className="card-foot">{foot}</div>
    </>
  );
}
