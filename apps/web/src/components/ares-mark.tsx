/** The two cut planes of the ARES monogram: observation meeting action. */
export function AresMark({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
    >
      <path d="M4 33 17 6h8L12 33H4Z" fill="currentColor" />
      <path d="m25 12 11 21H21l4-8h-5l5-13Z" fill="currentColor" />
      <path d="M16 33h3l4-8h-3l-4 8Z" fill="currentColor" opacity=".4" />
    </svg>
  );
}
