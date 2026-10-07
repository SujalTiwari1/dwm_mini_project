/**
 * Priority / status badge.
 * level: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
 */
const MAP = {
  CRITICAL: 'badge-critical',
  HIGH:     'badge-high',
  MEDIUM:   'badge-medium',
  LOW:      'badge-low',
};

const DOT = {
  CRITICAL: '●',
  HIGH:     '●',
  MEDIUM:   '●',
  LOW:      '●',
};

export default function PriorityBadge({ level }) {
  if (!level) return null;
  const cls = MAP[level?.toUpperCase()] ?? 'badge-low';
  return (
    <span className={`badge ${cls}`}>
      <span style={{ fontSize: '0.5rem' }}>{DOT[level?.toUpperCase()] ?? '●'}</span>
      {level}
    </span>
  );
}
