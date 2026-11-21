import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import { Button } from '../components/ui';

const ConfirmContext = createContext(null);

/** confirm({ title, body, confirmLabel, tone, extra }) -> Promise<false | {checked}>
 *  `extra` = optional checkbox ({ label, defaultChecked }) e.g. "also delete delivered history". */
export function ConfirmProvider({ children }) {
  const [state, setState] = useState(null);
  const resolver = useRef(null);
  const confirm = useCallback((opts) => new Promise((resolve) => {
    resolver.current = resolve;
    setState({ ...opts, checked: !!opts.extra?.defaultChecked });
  }), []);
  const close = (result) => { resolver.current?.(result); setState(null); };
  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <AnimatePresence>{state && <Dialog key="dlg" state={state} setState={setState} close={close} />}</AnimatePresence>
    </ConfirmContext.Provider>
  );
}

function Dialog({ state, setState, close }) {
  const cancelRef = useRef(null);
  useEffect(() => {
    cancelRef.current?.focus();
    const key = (e) => { if (e.key === 'Escape') close(false); };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const body = typeof state.body === 'function' ? state.body(state.checked) : state.body;
  return (
    <motion.div className="fixed inset-0 z-[3000] grid place-items-center bg-ink/30 p-4" onMouseDown={() => close(false)}
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <motion.div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title"
        initial={{ opacity: 0, scale: 0.94, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96 }}
        transition={{ type: 'spring', stiffness: 420, damping: 32 }}
        className="w-full max-w-md rounded-panel bg-surface p-6 shadow-panel" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex gap-3">
          {state.tone === 'danger' && (
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-bad-soft text-bad"><AlertTriangle className="h-5 w-5" /></span>
          )}
          <div className="min-w-0">
            <h2 id="confirm-title" className="text-lg font-bold">{state.title}</h2>
            <div className="mt-1.5 text-sm text-ink-soft">{body}</div>
          </div>
        </div>
        {state.extra && (
          <label className="mt-4 flex items-start gap-2 rounded-card bg-surface-subtle p-3 text-sm">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[theme(colors.bad.DEFAULT)]" checked={state.checked}
              onChange={(e) => setState({ ...state, checked: e.target.checked })} />
            <span>{state.extra.label}</span>
          </label>
        )}
        <div className="mt-6 flex justify-end gap-2">
          <Button ref={cancelRef} variant="ghost" onClick={() => close(false)}>{state.cancelLabel || 'Cancel'}</Button>
          <Button variant={state.tone === 'danger' ? 'dangerSolid' : 'dark'} disabled={state.disabled?.(state.checked)}
            onClick={() => close({ checked: state.checked })}>{state.confirmLabel || 'Confirm'}</Button>
        </div>
      </motion.div>
    </motion.div>
  );
}

export const useConfirm = () => useContext(ConfirmContext);
