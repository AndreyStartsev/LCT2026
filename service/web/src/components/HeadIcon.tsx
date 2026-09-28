import type { ReactElement } from "react";

/**
 * Значки действий шапки экрана проверки. Подписи «Выгрузить», «Печать», «Дозагрузить»,
 * «Журнал», «Финализировать протокол» занимали строку шапки целиком; значок того же рисунка,
 * что у рельсы (20 × 20, линия 1,4), а название и смысл — во всплывающей подсказке.
 */
export type HeadAction = "export" | "print" | "reupload" | "journal" | "finalize" | "resync" | "unfinalize" | "compare";

const PATHS: Record<HeadAction, ReactElement> = {
  // выгрузка: стрелка вниз в лоток
  export: (
    <>
      <path d="M10 2.5v10" />
      <path d="M6.5 9 10 12.5 13.5 9" />
      <path d="M3.5 13.5v4h13v-4" />
    </>
  ),
  print: (
    <>
      <path d="M6 7.5v-5h8v5" />
      <path d="M5.5 14.5h-2.5v-7h14v7h-2.5" />
      <path d="M6 11.5h8v6H6z" />
    </>
  ),
  // дозагрузка: стопка листов с плюсом — добавить документы. Стрелка вверх из лотка была
  // зеркалом «Выгрузить» и читалась как выгрузка; одиночный лист с плюсом спорил бы с «Финализировать»
  reupload: (
    <>
      <path d="M7 5.5v-3h9v12h-2.5" />
      <path d="M3.5 5.5h10v12h-10z" />
      <path d="M8.5 9v6M5.5 12h6" />
    </>
  ),
  // журнал аудита: листы с записями и корешок
  journal: (
    <>
      <path d="M5 2.5h11v15H5z" />
      <path d="M7.5 2.5v15" />
      <path d="M10 6.5h4M10 9.5h4M10 12.5h2.5" />
    </>
  ),
  // финализация: лист с отметкой
  finalize: (
    <>
      <path d="M5 2.5h7l3 3v12H5z" />
      <path d="M7.5 11.5l2 2 3.5-4.5" />
    </>
  ),
  resync: (
    <>
      <path d="M15.5 8.5A6 6 0 0 0 5 6" />
      <path d="M4.5 2.5V6.5H8.5" />
      <path d="M4.5 11.5A6 6 0 0 0 15 14" />
      <path d="M15.5 17.5v-4h-4" />
    </>
  ),
  // отмена финализации: открытый замок
  unfinalize: (
    <>
      <path d="M4 9.5h12v8H4z" />
      <path d="M7 9.5V6.5a3 3 0 0 1 5.8-1.1" />
      <path d="M10 12.5v2" />
    </>
  ),
  // сопоставление листов во весь экран: четыре угла
  compare: <path d="M8 3H3v5M12 17h5v-5M17 8V3h-5M3 12v5h5" strokeLinecap="round" strokeLinejoin="round" />,
};

export default function HeadIcon({ name }: { name: HeadAction }) {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}
