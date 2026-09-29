// Стороны сравнения записи: ожидаемое и фактическое значения и стадии, откуда они взяты (ТЗ 9.3:
// инспектор видит оба, карточка доказательства называет источник каждого). Обычно ожидаемое —
// значение ПД, фактическое — РД, а исполнительная документация идёт третьим массивом (#42).
//
// Сверка исполнительной схемы с допусками, объявленными на том же листе (FREE-KR-002,
// `pipeline/tolerances.py`), сравнивает внутри одного листа ИД: допуск листа конвейер кладёт
// в pd_value, отклонение — в id_value, а ПД и РД в проверке не участвуют. Так же записан
// и эталон организатора по такому листу: ПД и РД пустые, допуски — на стороне ИД. Без этого
// карточка протокола называла допуск значением ПД без источника, фактического значения у неё
// не было вовсе, и в ИАИС подтверждённое нарушение ушло бы без него.
type Json = Record<string, any>;
type Stage = "PD" | "RD" | "ID";

/** Проверка внутри одного листа ИД: допуск и отклонение — с исполнительной схемы. */
export const SHEET_TOLERANCE = "FREE-KR-002";

export interface Sides {
  expected: unknown;
  actual: unknown;
  /** Значение ИД третьим массивом; у проверки внутри листа ИД оно и есть фактическое. */
  built: unknown;
  /** Стадия ожидаемого и фактического значений — подпись в карточке протокола. */
  expected_stage: Stage;
  actual_stage: Stage;
  /** Стадии страниц-источников каждой стороны. */
  expected_sources: Stage[];
  actual_sources: Stage[];
  /** Ключ в `extraction`, где конвейер записал, чем прочитано значение стороны. */
  read_by: { expected: "pd" | "id"; actual: "rd" | "id" };
  /** Значения по стадиям: стадии, которой проверка не касается, значения нет. */
  by_stage: Record<Stage, unknown>;
}

export function sidesOf(row: Json): Sides {
  const pd = row.pd_value ?? null;
  const rd = row.rd_value ?? null;
  const id = row.body?.id_value ?? null;
  if (row.parameter_code === SHEET_TOLERANCE) {
    return {
      expected: pd,
      actual: id,
      built: null,
      expected_stage: "ID",
      actual_stage: "ID",
      expected_sources: ["ID"],
      actual_sources: ["ID"],
      read_by: { expected: "id", actual: "id" },
      by_stage: { PD: null, RD: null, ID: id },
    };
  }
  return {
    expected: pd,
    actual: rd,
    built: id,
    expected_stage: "PD",
    actual_stage: "RD",
    expected_sources: ["PD"],
    actual_sources: ["RD", "ID"],
    read_by: { expected: "pd", actual: "rd" },
    by_stage: { PD: pd, RD: rd, ID: id },
  };
}
