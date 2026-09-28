// Протокол в PDF. Задача #30, ТЗ 9.2: «создаётся структурированный документ (JSON/PDF)».
//
// Вёрстка повторяет разделы образца из Приложения 2: шапка с объектом и статусом,
// трассируемость, статус загрузки, сводка, таблицы, резолютивная часть, карточки
// доказательств и правила подсчёта. Шрифт с кириллицей берётся из системы: в образе API
// это DejaVu, путь можно задать переменными PDF_FONT_REGULAR и PDF_FONT_BOLD.

import { existsSync } from "node:fs";
import PDFDocument from "pdfkit";
import type { ProtocolReport } from "./report.js";
import { dash, footerText, protocolBlocks, type Column } from "./report-blocks.js";

const FONT_CANDIDATES = {
  regular: [
    process.env.PDF_FONT_REGULAR,
    "/usr/share/fonts/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Narrow.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
  ],
  bold: [
    process.env.PDF_FONT_BOLD,
    "/usr/share/fonts/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
  ],
};

function font(kind: keyof typeof FONT_CANDIDATES): string {
  const found = FONT_CANDIDATES[kind].find((path) => path && existsSync(path));
  if (!found) {
    throw new Error("не найден шрифт с кириллицей для PDF: задайте PDF_FONT_REGULAR и PDF_FONT_BOLD");
  }
  return found;
}

const INK = "#17181a";
const PENCIL = "#46484b";
const RULE = "#9a9c9f";
const TINT = "#ececea";
const MARGIN = 36;

type Doc = PDFKit.PDFDocument;

function bottom(doc: Doc): number {
  return doc.page.height - MARGIN - 22;
}

function ensure(doc: Doc, height: number): void {
  if (doc.y + height > bottom(doc)) {
    doc.addPage();
  }
}

function heading(doc: Doc, text: string): void {
  ensure(doc, 60);
  doc.moveDown(0.6);
  doc.font("bold").fontSize(11).fillColor(INK).text(text.toUpperCase(), MARGIN, doc.y, { characterSpacing: 0.4 });
  const y = doc.y + 2;
  doc.moveTo(MARGIN, y).lineTo(doc.page.width - MARGIN, y).lineWidth(1).strokeColor(INK).stroke();
  doc.y = y + 6;
}

function note(doc: Doc, text: string): void {
  ensure(doc, 30);
  doc.font("regular").fontSize(8.5).fillColor(PENCIL).text(text, MARGIN, doc.y, { width: doc.page.width - 2 * MARGIN });
  doc.moveDown(0.4);
}

/** Таблица с переносом строк и повтором шапки на новой странице. Ширины — доли ширины листа. */
function table(doc: Doc, columns: Column[], rows: string[][], size = 8): void {
  const full = doc.page.width - 2 * MARGIN;
  const widths = columns.map((c) => c.width * full);
  const pad = 3;
  const drawRow = (cells: string[], header: boolean) => {
    doc.font(header ? "bold" : "regular").fontSize(size);
    const heights = cells.map((cell, i) => doc.heightOfString(cell, { width: widths[i] - 2 * pad }));
    const height = Math.max(...heights) + 2 * pad;
    if (doc.y + height > bottom(doc)) {
      doc.addPage();
      if (!header) drawRow(columns.map((c) => c.title), true);
      doc.font("regular").fontSize(size);
    }
    let x = MARGIN;
    const y = doc.y;
    cells.forEach((cell, i) => {
      if (header) doc.rect(x, y, widths[i], height).fillColor(TINT).fill();
      doc.rect(x, y, widths[i], height).lineWidth(0.5).strokeColor(RULE).stroke();
      doc.fillColor(INK).font(header ? "bold" : "regular").fontSize(size)
        .text(cell, x + pad, y + pad, { width: widths[i] - 2 * pad, align: columns[i].align ?? "left" });
      x += widths[i];
    });
    doc.y = y + height;
  };
  ensure(doc, 40);
  drawRow(columns.map((c) => c.title), true);
  if (rows.length === 0) {
    drawRow(columns.map((_, i) => (i === 0 ? "Записей нет" : "")), false);
  }
  for (const row of rows) drawRow(row, false);
  doc.x = MARGIN;
  doc.moveDown(0.5);
}

function keyValues(doc: Doc, pairs: [string, string][], size = 8.5): void {
  table(doc, [{ title: "Поле", width: 0.28 }, { title: "Значение", width: 0.72 }], pairs.map(([k, v]) => [k, v]), size);
}

export function renderReportPdf(report: ProtocolReport): Promise<Buffer> {
  const doc = new PDFDocument({ size: "A4", margin: MARGIN, bufferPages: true, info: {
    Title: `${report.title} ${report.number ?? ""}`.trim(),
    Subject: report.object.name,
    Creator: "Инспектор ИИ",
  } });
  doc.registerFont("regular", font("regular"));
  doc.registerFont("bold", font("bold"));
  const chunks: Buffer[] = [];
  doc.on("data", (chunk: Buffer) => chunks.push(chunk));
  const done = new Promise<Buffer>((resolve, reject) => {
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);
  });

  // ---- название и номер; дальше содержание — общими блоками с DOCX ----
  doc.font("bold").fontSize(15).fillColor(INK).text(`${report.title.toUpperCase()}`, { characterSpacing: 0.5 });
  doc.font("regular").fontSize(10).fillColor(PENCIL).text(`№ ${dash(report.number)}`);
  doc.moveDown(0.4);
  for (const block of protocolBlocks(report)) {
    switch (block.kind) {
      case "heading":
        heading(doc, block.text);
        break;
      case "note":
        note(doc, block.text);
        break;
      case "table":
        table(doc, block.columns, block.rows, block.size);
        break;
      case "kv":
        keyValues(doc, block.pairs, block.size);
        break;
      case "card":
        ensure(doc, 120);
        doc.font("bold").fontSize(9).fillColor(INK).text(block.text, MARGIN, doc.y);
        doc.moveDown(0.2);
        break;
    }
  }

  // ---- колонтитул ----
  const range = doc.bufferedPageRange();
  for (let i = range.start; i < range.start + range.count; i++) {
    doc.switchToPage(i);
    // колонтитул ниже нижнего поля: без обнуления поля pdfkit на каждую строку добавляет пустой лист
    const bottomMargin = doc.page.margins.bottom;
    doc.page.margins.bottom = 0;
    const y = doc.page.height - MARGIN + 4;
    doc.font("regular").fontSize(7.5).fillColor(PENCIL)
      .text(footerText(report), MARGIN, y, { width: doc.page.width - 2 * MARGIN - 80, lineBreak: false })
      .text(`Лист ${i + 1} из ${range.count}`, doc.page.width - MARGIN - 80, y, { width: 80, align: "right", lineBreak: false });
    doc.page.margins.bottom = bottomMargin;
  }
  doc.end();
  return done;
}
