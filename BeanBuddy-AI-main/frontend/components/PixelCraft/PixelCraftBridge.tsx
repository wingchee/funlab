import { IconArrowBackUp, IconExternalLink } from '@tabler/icons-react';
import { useEffect, useMemo, useState } from 'react';

type PixelCraftCell = {
  row: number;
  col: number;
  symbol: string;
  color_hex: string;
  empty?: boolean;
};

type PixelCraftLegendEntry = {
  symbol: string;
  name?: string;
  color_hex: string;
  count?: number;
};

type PixelCraftResult = {
  rows: number;
  cols: number;
  cells: PixelCraftCell[];
  legend?: PixelCraftLegendEntry[];
};

type PixelCraftPayload = {
  source?: string;
  updated_at?: number;
  result?: PixelCraftResult;
};

const PAYLOAD_KEY = 'pixelcraft_editor_payload';
const RESULT_KEY = 'pixelcraft_editor_result';

function readPayload(): PixelCraftPayload | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(PAYLOAD_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (error) {
    console.error('Unable to read PixelCraft payload:', error);
    return null;
  }
}

function PatternPreview({ result }: { result: PixelCraftResult }) {
  const cellsByKey = useMemo(() => {
    const index = new Map<string, PixelCraftCell>();
    result.cells?.forEach((cell) => index.set(`${cell.row}:${cell.col}`, cell));
    return index;
  }, [result.cells]);

  const visibleRows = Math.min(result.rows || 0, 52);
  const visibleCols = Math.min(result.cols || 0, 52);

  return (
    <div
      className="grid overflow-hidden rounded-lg border border-[#E8E6E1] bg-white shadow-sm"
      style={{
        gridTemplateColumns: `repeat(${visibleCols}, minmax(0, 1fr))`,
        aspectRatio: '1 / 1',
      }}
    >
      {Array.from({ length: visibleRows * visibleCols }, (_, index) => {
        const row = Math.floor(index / visibleCols) + 1;
        const col = (index % visibleCols) + 1;
        const cell = cellsByKey.get(`${row}:${col}`);
        return (
          <span
            key={`${row}:${col}`}
            style={{ background: cell?.empty ? '#F8F7F4' : cell?.color_hex || '#F8F7F4' }}
          />
        );
      })}
    </div>
  );
}

export function PixelCraftBridge() {
  const [payload, setPayload] = useState<PixelCraftPayload | null>(null);

  useEffect(() => {
    setPayload(readPayload());
  }, []);

  const result = payload?.result;
  const legend = result?.legend || [];

  const returnToPixelCraft = () => {
    if (!result || typeof window === 'undefined') return;
    const message = {
      type: 'pixelcraft-editor-result',
      result,
      updated_at: Date.now(),
    };
    window.localStorage.setItem(RESULT_KEY, JSON.stringify(message));
    window.opener?.postMessage(message, window.location.origin);
    window.close();
  };

  if (!result) {
    return (
      <aside className="hidden w-[320px] shrink-0 border-l border-[#E8E6E1] bg-[#FEF4F5] p-5 text-[#1A1A18] lg:block">
        <div className="rounded-xl border border-[#E8E6E1] bg-white p-5 shadow-sm">
          <div className="mb-2 text-xs font-bold uppercase tracking-[0.14em] text-[#F47A8A]">
            PixelCraft
          </div>
          <h2 className="mb-2 text-lg font-bold">No pattern loaded</h2>
          <p className="text-sm leading-6 text-[#777]">
            Open BeanBuddy from the PixelCraft admin edit button to load the selected bead map.
          </p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="hidden w-[340px] shrink-0 overflow-y-auto border-l border-[#E8E6E1] bg-[#FEF4F5] p-5 text-[#1A1A18] lg:block">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="text-xs font-bold uppercase tracking-[0.14em] text-[#F47A8A]">
            PixelCraft Edit
          </div>
          <h2 className="text-xl font-bold">BeanBuddy AI</h2>
        </div>
        <button
          onClick={returnToPixelCraft}
          className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-[#F47A8A] to-[#6BB5E8] px-3 py-2 text-xs font-bold text-white shadow-sm transition hover:opacity-90"
        >
          <IconArrowBackUp size={15} />
          Return
        </button>
      </div>

      <div className="mb-4 rounded-xl border border-[#E8E6E1] bg-white p-4 shadow-sm">
        <PatternPreview result={result} />
        <div className="mt-3 flex items-center justify-between text-sm">
          <span className="font-mono font-bold">{result.cols}x{result.rows}</span>
          <span className="text-[#777]">{legend.length} colors</span>
        </div>
      </div>

      <div className="mb-4 rounded-xl border border-[#E8E6E1] bg-white p-4 shadow-sm">
        <div className="mb-3 text-xs font-bold uppercase tracking-[0.12em] text-[#999]">
          Prompt starter
        </div>
        <p className="text-sm leading-6 text-[#555]">
          Ask BeanBuddy to simplify colors, improve outlines, remove noisy isolated beads, or suggest a cleaner Q-style version before you publish.
        </p>
      </div>

      <div className="rounded-xl border border-[#E8E6E1] bg-white p-4 shadow-sm">
        <div className="mb-3 text-xs font-bold uppercase tracking-[0.12em] text-[#999]">
          Bead colors
        </div>
        <div className="space-y-2">
          {legend.slice(0, 12).map((entry) => (
            <div key={entry.symbol} className="flex items-center gap-3 text-sm">
              <span
                className="h-4 w-4 shrink-0 rounded border border-black/10"
                style={{ background: entry.color_hex }}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate font-semibold">{entry.name || entry.symbol}</div>
                <div className="font-mono text-xs text-[#999]">{entry.count || 0} beads</div>
              </div>
            </div>
          ))}
        </div>
        {legend.length > 12 && (
          <div className="mt-3 flex items-center gap-1 text-xs text-[#999]">
            <IconExternalLink size={13} />
            {legend.length - 12} more colors in PixelCraft
          </div>
        )}
      </div>
    </aside>
  );
}
