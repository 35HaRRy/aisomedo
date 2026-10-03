const paths = {
  edit: "m15 5 4 4M4 16l-1 5 5-1L20 8a2.8 2.8 0 0 0-4-4Z",
  close: "m6 6 12 12M6 18 18 6",
  remove: "M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7",
  restore: "M8 4 3 9l5 5M3 9h11a6 6 0 0 1 0 12h-3",
  left: "m10 6-6 6 6 6M4 12h16",
  right: "m14 6 6 6-6 6M4 12h16",
  drag: "M12 2v20M2 12h20m-13-7 3-3 3 3m-6 14 3 3 3-3M5 9l-3 3 3 3m14-6 3 3-3 3",
};

export function MediaActionIcon({ action }: { action: keyof typeof paths }) {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={paths[action]} /></svg>;
}
