import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

interface Props {
  /** Текст подсказки: что делает кнопка или что значит код, словами инспектора. */
  text: string;
  children: ReactNode;
  /** Снизу, сверху или справа: у рельсы экрана место только справа. */
  place?: "below" | "above" | "right";
  /** Обёртка занимает всю ширину: для строк навигации по протоколу. */
  block?: boolean;
}

const EDGE = 8;
const GAP = 6;

/**
 * Подсказка по наведению с задержкой (#74, по итогам репетиции #53). Человеку со стороны
 * непонятно назначение служебных кнопок, вкладок и технических кодов, а читать руководство
 * во время проверки он не станет. Задержка в 450 мс не даёт подсказкам мелькать, когда
 * курсор просто проходит мимо; с клавиатуры подсказка появляется сразу.
 *
 * Подсказка считается от места на экране и рисуется поверх страницы (position: fixed):
 * при прежнем способе её обрезала любая прокручиваемая колонка — левая колонка протокола
 * уже 300 px подсказки. У края экрана подсказка сдвигается внутрь, у низа — переворачивается
 * наверх. Прокрутка и смена размера окна её убирают: место под курсором уже другое.
 */
export default function Tip({ text, children, place = "below", block }: Props) {
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState<{ left: number; top: number } | null>(null);
  const wrap = useRef<HTMLSpanElement>(null);
  const bubble = useRef<HTMLSpanElement>(null);
  const timer = useRef<number | null>(null);
  const clear = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };
  useEffect(() => clear, []);

  useLayoutEffect(() => {
    if (!open || !bubble.current || !wrap.current) return;
    const anchor = wrap.current.getBoundingClientRect();
    const box = bubble.current.getBoundingClientRect();
    let left: number;
    let top: number;
    if (place === "right") {
      left = anchor.right + GAP + 2;
      top = anchor.top + anchor.height / 2 - box.height / 2;
    } else {
      left = anchor.left + anchor.width / 2 - box.width / 2;
      top = place === "above" ? anchor.top - box.height - GAP : anchor.bottom + GAP;
      // не помещается снизу — переворачиваем наверх, и наоборот
      if (place === "below" && top + box.height > window.innerHeight - EDGE) top = anchor.top - box.height - GAP;
      if (place === "above" && top < EDGE) top = anchor.bottom + GAP;
    }
    left = Math.min(Math.max(left, EDGE), Math.max(EDGE, window.innerWidth - EDGE - box.width));
    top = Math.min(Math.max(top, EDGE), Math.max(EDGE, window.innerHeight - EDGE - box.height));
    setAt((was) => (was && Math.abs(was.left - left) < 0.5 && Math.abs(was.top - top) < 0.5 ? was : { left, top }));
  }, [open, place, text]);

  const hide = () => {
    clear();
    setOpen(false);
    setAt(null);
  };

  useEffect(() => {
    if (!open) return;
    const away = () => hide();
    // прокрутка внутри любой колонки уводит кнопку из-под подсказки: проще убрать
    window.addEventListener("scroll", away, true);
    window.addEventListener("resize", away);
    return () => {
      window.removeEventListener("scroll", away, true);
      window.removeEventListener("resize", away);
    };
  }, [open]);

  return (
    <span
      ref={wrap}
      className={`tip-wrap${block ? " tip-block" : ""}`}
      onMouseEnter={() => {
        clear();
        timer.current = window.setTimeout(() => setOpen(true), 450);
      }}
      onMouseLeave={hide}
      onFocusCapture={() => setOpen(true)}
      onBlurCapture={hide}
    >
      {children}
      {open && (
        <span
          ref={bubble}
          className="tip"
          role="tooltip"
          // первая отрисовка — только чтобы измерить пузырь; видимым он становится на месте
          style={at ? { left: at.left, top: at.top } : { left: 0, top: 0, visibility: "hidden" }}
        >
          {text}
        </span>
      )}
    </span>
  );
}
