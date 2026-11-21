import { motion } from 'framer-motion';
import { MapPinOff, RotateCw } from 'lucide-react';
import { Button } from '../ui';

export default function MapMissing({ error, onRetry }) {
  return (
    <div className="grid h-full place-items-center bg-surface-subtle p-6">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="panel max-w-lg p-8 text-center">
        <span className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-warn-soft text-warn"><MapPinOff className="h-7 w-7" /></span>
        <h1 className="mt-4 text-xl font-bold">The city map is not downloaded yet</h1>
        <p className="mt-2 text-sm text-ink-soft">{error}</p>
        <pre className="mt-4 rounded-card bg-ink px-4 py-3 text-left font-mono text-sm text-white">./set-up.sh</pre>
        <p className="mt-2 text-xs text-ink-muted">Needs an internet connection once; the road network is then stored in backend/data/osm/. Restart with ./run.sh afterwards.</p>
        <Button className="mt-5" icon={RotateCw} onClick={onRetry}>Check again</Button>
      </motion.div>
    </div>
  );
}
