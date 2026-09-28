import { useEffect, useMemo, useState, type ReactNode, type Ref } from "react";
import { openInTab, sourceUrl, type Evidence } from "../api";
import { cloudPath, fragmentOf, zonesFor, type Box } from "../cloud";
import { highlightNote, STAGE, STAGE_NAME } from "../labels";
import { usePageImage, type PageImage } from "../pages";
import Tip from "./Tip";

interface Props {
  processId: string;
  stage: "PD" | "RD";
  items: Evidence[];
  value: string | null;
  /**
   * Значение исполнительной документации: в карточке РД листаются и страницы ИД (#42),
   * и под страницей ИД должно стоять значение ИД, а не РД.
   */
  idValue?: string | null;
  onOpen: (evidence: Evidence) => void;
  /** Куда сказать, что файл не отдался: у карточки своего места для ошибки нет. */
  onError?: (message: string) => void;
  /**
   * Какая страница показана — задаёт экран проверки (п. 13): тогда «во весь экран»,
   * сопоставление и строки источников в карточке находки открывают одну и ту же страницу.
   * Без него карточка листает сама.
   */
  index?: number;
  onIndex?: (index: number) => void;
}

/** Знак «исходный файл»: лист с загнутым углом, тонкой линией, как остальная графика экрана. */
function FileIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
      <path
        d="M9.2 1.8H4.3a.8.8 0 0 0-.8.8v10.8a.8.8 0 0 0 .8.8h7.4a.8.8 0 0 0 .8-.8V5.3L9.2 1.8Zm0 0V5a.4.4 0 0 0 .4.4h3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export interface Plan {
  image: PageImage;
  clouds: string[];
  /** Фрагмент вокруг облаков в пикселях картинки; null — показывать лист целиком. */
  fragment: Box | null;
}

/** Картинка страницы-доказательства, облака изменений и фрагмент вокруг них. */
export function usePlan(processId: string, evidence: Evidence): Plan {
  const image = usePageImage(processId, evidence.file_id, evidence.pdf_page_number);
  const highlights = evidence.highlights;
  return useMemo(() => {
    if (image.state !== "ready") return { image, clouds: [], fragment: null };
    const zones = zonesFor(highlights ?? [], image.w, image.h);
    return {
      image,
      clouds: zones.map((zone) => cloudPath(zone, image.w, image.h)),
      fragment: fragmentOf(zones, image.w, image.h),
    };
  }, [image, highlights]);
}

/** Страница с облаками. Картинка и облака в одной SVG-системе, поэтому совпадают при любом масштабе. */
export function PlanView({
  plan,
  view,
  label,
  svgRef,
  missing,
}: {
  plan: Plan;
  view: Box | null;
  label: string;
  svgRef?: Ref<SVGSVGElement>;
  /** Что показать вместо картинки, которой нет; по умолчанию — «сверяйте по цитате». */
  missing?: ReactNode;
}) {
  const { image } = plan;
  if (image.state === "loading") {
    return <div className="plan plan-wait">Страница загружается…</div>;
  }
  if (image.state === "missing") {
    return (
      <div className="plan plan-absent hatched">
        {missing ?? <span>Страница не отрисована: сверяйте по цитате</span>}
      </div>
    );
  }
  const box = view ?? { x: 0, y: 0, w: image.w, h: image.h };
  return (
    <svg
      ref={svgRef}
      className="plan"
      viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={label}
    >
      <image href={image.src} x="0" y="0" width={image.w} height={image.h} />
      {plan.clouds.map((d, i) => (
        <g key={i}>
          <path d={d} className="cloud-halo" vectorEffect="non-scaling-stroke" />
          <path d={d} className="cloud" vectorEffect="non-scaling-stroke" />
        </g>
      ))}
    </svg>
  );
}

function Figure({ processId, evidence, onOpen }: { processId: string; evidence: Evidence; onOpen: () => void }) {
  const plan = usePlan(processId, evidence);
  const label = `${STAGE_NAME[evidence.stage] ?? evidence.stage}, страница ${evidence.pdf_page_number}${plan.fragment ? ", фрагмент у облака" : ""}`;
  return (
    <button type="button" className="plan-button" onClick={onOpen} title="Открыть страницу крупно">
      <PlanView plan={plan} view={plan.fragment} label={label} />
    </button>
  );
}

export default function PageCard({ processId, stage, items, value, idValue, onOpen, onError, index: shown, onIndex }: Props) {
  // Том может весить десятки мегабайт: пока он грузится, кнопка занята и показывает проценты
  const [opening, setOpening] = useState<number | null>(null);
  // Открываемся на странице, где место обведено: у сравнения по помещениям первыми идут
  // доказательства уровня страницы, и инспектор видел лист без рамки (задача #50).
  const marked = Math.max(items.findIndex((e) => e.highlights?.length), 0);
  const [own, setOwn] = useState(marked);
  // Список пересобирается при каждой отрисовке экрана; листать заново — только когда сменились сами страницы
  const pagesKey = items.map((e) => `${e.file_id}:${e.pdf_page_number}`).join("|");
  useEffect(() => setOwn(marked), [pagesKey]);
  const index = shown ?? own;
  const setIndex = (i: number) => (onIndex ? onIndex(i) : setOwn(i));
  const evidence = items[Math.min(index, items.length - 1)];

  // у записи есть значение ИД — карточка РД говорит о двух стадиях, а не только о рабочей
  const withId = stage === "RD" && idValue != null;
  if (!evidence) {
    return (
      <article className="page-card">
        <div className="page-head">
          <span className="stage">{withId ? `${STAGE.RD} · ${STAGE.ID}` : STAGE[stage]}</span>
          <span>{withId ? `${STAGE_NAME.RD} и ${STAGE_NAME.ID.toLowerCase()}` : STAGE_NAME[stage]}</span>
        </div>
        <div className="plan plan-absent hatched">
          <span>
            {stage === "PD"
              ? "Страница проекта не найдена"
              : withId
                ? "Страницы рабочей и исполнительной документации не найдены"
                : "Страница рабочей документации не найдена"}
          </span>
        </div>
        <div className="page-foot">
          {withId ? (
            <span className={value ? "" : "absent-inline"}>
              {STAGE.RD}: {value ?? "не найдено"} · {STAGE.ID}: {idValue}
            </span>
          ) : (
            <span className="absent-inline">{value ?? "значение не найдено"}</span>
          )}
        </div>
      </article>
    );
  }
  // значение — той стадии, чья страница сейчас показана
  const sideValue = evidence.stage === "ID" ? (idValue ?? null) : value;

  const where = highlightNote(evidence);
  return (
    <article className="page-card">
      <div className="page-head">
        <span className="stage">{STAGE[evidence.stage] ?? evidence.stage}</span>
        <span>
          {evidence.file_id} · стр. {evidence.pdf_page_number}
          {evidence.page_count ? `/${evidence.page_count}` : ""}
        </span>
        {evidence.document_sheet_number != null && (
          <span className="sheet-no" title={evidence.document_code ?? undefined}>
            лист {evidence.document_sheet_number}
          </span>
        )}
        {/* Исходный файл целиком (#74): рядом со страницей-доказательством инспектору нужен
            весь том — посмотреть соседние листы, штамп, ведомость. Файл хранится как
            загружен, поэтому открывается просмотрщиком браузера на нужной странице. */}
        <Tip text="Открыть исходный файл целиком в новой вкладке — на этой же странице" place="below">
          <button
            type="button"
            className="icon-btn"
            aria-label="Открыть исходный файл"
            disabled={opening !== null}
            onClick={() => {
              setOpening(0);
              openInTab(sourceUrl(processId, evidence.file_id), `#page=${evidence.pdf_page_number}`, (done, total) =>
                setOpening(Math.round((done / total) * 100)),
              )
                .catch((e) => onError?.(`Исходный файл не открылся: ${(e as Error).message}`))
                .finally(() => setOpening(null));
            }}
          >
            {opening === null ? <FileIcon /> : <span className="mono small">{opening}%</span>}
          </button>
        </Tip>
        {items.length > 1 && (
          <span className="pager">
            <button type="button" aria-label="Предыдущая страница" disabled={index === 0} onClick={() => setIndex(index - 1)}>
              ‹
            </button>
            {index + 1} из {items.length}
            <button
              type="button"
              aria-label="Следующая страница"
              disabled={index >= items.length - 1}
              onClick={() => setIndex(index + 1)}
            >
              ›
            </button>
          </span>
        )}
      </div>
      <Figure
        key={`${evidence.file_id}:${evidence.pdf_page_number}`}
        processId={processId}
        evidence={evidence}
        onOpen={() => onOpen(evidence)}
      />
      <div className="page-foot">
        <span className={sideValue ? "" : "absent-inline"}>{sideValue ?? "значение не найдено"}</span>
        <span className="legend">{where}</span>
      </div>
    </article>
  );
}
