import type { ReactElement } from "react";
import type { Confidence, SpecialistVerdict } from "../api";
import { CONFIDENCE, SPECIALIST } from "../labels";
import Tip from "./Tip";

/**
 * Мини-пометки записи (#80): уверенность в выводе и решение специалиста — значком того же
 * рисунка, что значки шапки (линия 1,4 на поле 20 × 20), а смысл и причины — в подсказке.
 * Отбора по ним нет: это сведения о записи, а не способ разложить список, и выпадающие
 * списки над протоколом только отнимали место у самих записей.
 */

/**
 * Уверенность — столбиками, как уровень сигнала: низкая — один из трёх, средняя — два.
 * Высокую строка списка не отмечает: пометка нужна там, где стоит проверить; в карточке
 * значок стоит всегда (`always`).
 */
export function ConfidenceMark({
  confidence,
  size = 14,
  always = false,
  hint = true,
}: {
  confidence: Confidence;
  size?: number;
  always?: boolean;
  /** Своя подсказка у значка. Карточка находки даёт подсказку всей строке уверенности — там false. */
  hint?: boolean;
}) {
  const filled = confidence.level === "LOW" ? 1 : confidence.level === "MEDIUM" ? 2 : 3;
  if (!always && filled === 3) return null;
  const word = CONFIDENCE[confidence.level]?.word ?? confidence.level;
  const text = `Уверенность ${word}` + (confidence.down.length ? `: ${confidence.down.join("; ")}` : "");
  const mark = (
    <svg
      className={`mark mark-conf conf-${confidence.level.toLowerCase()}`}
      width={size}
      height={size}
      viewBox="0 0 20 20"
      role="img"
      aria-label={`уверенность ${word}`}
    >
      {[0, 1, 2].map((i) => {
        const top = 13.5 - i * 4.5;
        return <rect key={i} x={2.5 + i * 5.5} y={top} width="3.5" height={17 - top} className={i < filled ? "on" : "off"} />;
      })}
    </svg>
  );
  return hint ? <Tip text={text}>{mark}</Tip> : mark;
}

/**
 * Знак решения специалиста рядом с человеком: нарушение, нужны данные, не нарушение,
 * гипотеза (волна — «может быть»), низкий приоритет (черта).
 */
const SPECIALIST_SIGN: Record<string, ReactElement> = {
  violation: <path d="M12.3 11.2l2.1 2.1 3.8-4.8" />,
  need_info: (
    <>
      <path d="M13.2 8.6a2.2 2.2 0 1 1 3.1 2c-.8.4-1.1.9-1.1 1.6v.4" />
      <path d="M15.2 15.1v.4" />
    </>
  ),
  no_violation: <path d="M13 9l4.6 4.6M17.6 9 13 13.6" />,
  hypothesis: <path d="M12.2 12.3c.9-1.6 2-1.6 2.9 0s2 1.6 2.9 0" />,
  drop: <path d="M12.6 12.2h5.4" />,
};

/**
 * Решение специалиста (#129, Р-86, Р-108): человек и знак. Решение — о виде записей, а не об
 * этой записи (Р-116); в подсказке — слово решения и пометка специалиста. Цвет — как у
 * решений на листе: решение принимал человек.
 */
export function SpecialistMark({ specialist, size = 14 }: { specialist: SpecialistVerdict; size?: number }) {
  const s = SPECIALIST[specialist.verdict];
  if (!s) return null;
  const text =
    `Специалист о таких записях${specialist.reviewed ? ` (${specialist.reviewed})` : ""}: ${s.word}.` +
    (specialist.note ? ` ${specialist.note}` : "");
  return (
    <Tip text={text}>
      <svg
        className={`mark mark-spec s-${s.tone}`}
        width={size}
        height={size}
        viewBox="0 0 20 20"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        role="img"
        aria-label={`специалист: ${s.word}`}
      >
        <circle cx="6.5" cy="6" r="2.8" />
        <path d="M1.8 17c0-3.1 2.1-5.3 4.7-5.3s4.7 2.2 4.7 5.3" />
        {SPECIALIST_SIGN[specialist.verdict]}
      </svg>
    </Tip>
  );
}
