import { useEffect } from 'react';
import { animate, motion, useMotionValue, useTransform } from 'framer-motion';

/** Shared motion tokens – every animation communicates a state change. */
export const spring = { type: 'spring', stiffness: 420, damping: 34, mass: 0.8 };
export const softSpring = { type: 'spring', stiffness: 260, damping: 30 };
export const ease = [0.2, 0.8, 0.2, 1];

export const fadeUp = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.22, ease } },
  exit: { opacity: 0, y: -6, transition: { duration: 0.14 } },
};
export const pop = {
  initial: { opacity: 0, scale: 0.96, y: -4 },
  animate: { opacity: 1, scale: 1, y: 0, transition: spring },
  exit: { opacity: 0, scale: 0.97, transition: { duration: 0.12 } },
};
export const slideRight = {
  initial: { opacity: 0, x: 24 },
  animate: { opacity: 1, x: 0, transition: softSpring },
  exit: { opacity: 0, x: 24, transition: { duration: 0.15 } },
};
export const listItem = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, height: 0, marginTop: 0, marginBottom: 0 },
};

/** Number that tweens to its new value (KPI changes are visible, not jumpy). */
export function AnimatedNumber({ value, format = (v) => Math.round(v).toLocaleString(), className }) {
  const mv = useMotionValue(typeof value === 'number' ? value : 0);
  const text = useTransform(mv, (v) => format(v));
  useEffect(() => {
    if (typeof value !== 'number' || Number.isNaN(value)) return undefined;
    const c = animate(mv, value, { duration: 0.6, ease });
    return () => c.stop();
  }, [value, mv]);
  if (typeof value !== 'number' || Number.isNaN(value)) return <span className={className}>–</span>;
  return <motion.span className={className}>{text}</motion.span>;
}
