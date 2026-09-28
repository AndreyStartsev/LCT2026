// Протокол в DOCX (ТЗ, модуль 7: «экспорт протоколов в PDF, DOCX, XML»). Содержание то же,
// что у PDF: оба формата собираются из блоков report-blocks.ts. Вёрстка — средствами Word:
// шапка таблицы повторяется на каждой странице, строка не рвётся между страницами,
// в колонтитуле — номер протокола и «Лист N из M».
import {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  Packer,
  PageNumber,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableLayoutType,
  TableRow,
  TextRun,
  WidthType,
} from "docx";
import type { ProtocolReport } from "./report.js";
import { dash, footerText, protocolBlocks, type Column } from "./report-blocks.js";

const INK = "17181A";
const PENCIL = "46484B";
const RULE = "9A9C9F";
const TINT = "ECECEA";
const FONT = "Arial";
// A4 в твипах (1/20 пункта) и поля, как у PDF: 36 пт
const PAGE_WIDTH = 11906;
const PAGE_HEIGHT = 16838;
const MARGIN = 720;
const CONTENT = PAGE_WIDTH - 2 * MARGIN;

const half = (pt: number) => Math.round(pt * 2); // размер шрифта в docx — в полупунктах

/** Текст ячейки: переводы строк — отдельными строками, как в PDF. */
function runs(text: string, size: number, bold = false, color = INK): TextRun[] {
  return text.split("\n").map((line, i) => new TextRun({ text: line, size: half(size), bold, color, font: FONT, break: i ? 1 : 0 }));
}

const border = { style: BorderStyle.SINGLE, size: 4, color: RULE };
const borders = { top: border, bottom: border, left: border, right: border };

function cell(text: string, width: number, size: number, header: boolean, align?: Column["align"]): TableCell {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders,
    shading: header ? { type: ShadingType.CLEAR, fill: TINT, color: "auto" } : undefined,
    margins: { top: 50, bottom: 50, left: 70, right: 70 },
    children: [
      new Paragraph({
        alignment: align === "right" ? AlignmentType.RIGHT : align === "center" ? AlignmentType.CENTER : AlignmentType.LEFT,
        children: runs(text, size, header),
      }),
    ],
  });
}

function table(columns: Column[], rows: string[][], size = 8): Table {
  const widths = columns.map((c) => Math.round(c.width * CONTENT));
  const body = rows.length ? rows : [columns.map((_, i) => (i === 0 ? "Записей нет" : ""))];
  return new Table({
    width: { size: CONTENT, type: WidthType.DXA },
    columnWidths: widths,
    layout: TableLayoutType.FIXED,
    rows: [
      new TableRow({
        tableHeader: true,
        cantSplit: true,
        children: columns.map((c, i) => cell(c.title, widths[i], size, true, c.align)),
      }),
      ...body.map(
        (row) =>
          new TableRow({
            cantSplit: true,
            children: row.map((value, i) => cell(value, widths[i], size, false, columns[i].align)),
          }),
      ),
    ],
  });
}

const gap = () => new Paragraph({ spacing: { after: 80 }, children: [] });

export function renderReportDocx(report: ProtocolReport): Promise<Buffer> {
  const children: (Paragraph | Table)[] = [
    new Paragraph({
      spacing: { after: 60 },
      children: [new TextRun({ text: report.title.toUpperCase(), bold: true, size: half(15), color: INK, font: FONT, characterSpacing: 10 })],
    }),
    new Paragraph({
      spacing: { after: 160 },
      children: [new TextRun({ text: `№ ${dash(report.number)}`, size: half(10), color: PENCIL, font: FONT })],
    }),
  ];
  for (const block of protocolBlocks(report)) {
    switch (block.kind) {
      case "heading":
        children.push(
          new Paragraph({
            keepNext: true,
            spacing: { before: 240, after: 100 },
            border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: INK, space: 2 } },
            children: [new TextRun({ text: block.text.toUpperCase(), bold: true, size: half(11), color: INK, font: FONT, characterSpacing: 8 })],
          }),
        );
        break;
      case "note":
        children.push(new Paragraph({ spacing: { after: 100 }, children: runs(block.text, 8.5, false, PENCIL) }));
        break;
      case "table":
        children.push(table(block.columns, block.rows, block.size), gap());
        break;
      case "kv":
        children.push(
          table([{ title: "Поле", width: 0.28 }, { title: "Значение", width: 0.72 }], block.pairs, block.size ?? 8.5),
          gap(),
        );
        break;
      case "card":
        children.push(
          new Paragraph({
            keepNext: true,
            spacing: { before: 160, after: 60 },
            children: [new TextRun({ text: block.text, bold: true, size: half(9), color: INK, font: FONT })],
          }),
        );
        break;
    }
  }

  const doc = new Document({
    creator: "Инспектор ИИ",
    title: `${report.title} ${report.number ?? ""}`.trim(),
    subject: report.object.name,
    styles: { default: { document: { run: { font: FONT, size: half(9), color: INK } } } },
    sections: [
      {
        properties: {
          page: {
            size: { width: PAGE_WIDTH, height: PAGE_HEIGHT },
            margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN, footer: 360 },
          },
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                children: [
                  new TextRun({ text: `${footerText(report)} · Лист `, size: half(7.5), color: PENCIL, font: FONT }),
                  new TextRun({ children: [PageNumber.CURRENT], size: half(7.5), color: PENCIL, font: FONT }),
                  new TextRun({ text: " из ", size: half(7.5), color: PENCIL, font: FONT }),
                  new TextRun({ children: [PageNumber.TOTAL_PAGES], size: half(7.5), color: PENCIL, font: FONT }),
                ],
              }),
            ],
          }),
        },
        children,
      },
    ],
  });
  return Packer.toBuffer(doc);
}
