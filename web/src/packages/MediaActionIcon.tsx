const paths = {
  dashboard: "M3 3h7v7H3ZM14 3h7v7h-7ZM3 14h7v7H3ZM14 14h7v7h-7Z",
  package: "M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm5 4 6 3-6 3Z",
  completed: "m12 2 9 5v10l-9 5-9-5V7Zm0 10 9-5M12 12 3 7m9 5v10",
  activity: "M2 12h4l3-9 6 18 3-9h4",
  settings: "m9 3 1-1h4l1 3 3 1 3-1 2 4-2 2v3l2 2-2 4-3-1-3 1-1 3h-4l-1-3-3-1-3 1-2-4 2-2v-3L1 9l2-4 3 1 3-1Zm3 6a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
  sun: "M12 3V1m0 22v-2M3 12H1m22 0h-2M5.6 5.6 4.2 4.2m15.6 15.6-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4M17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0",
  moon: "M20.9 13a9 9 0 1 1-9.9-9.9A7 7 0 0 0 20.9 13Z",
  collapse: "m6 15 6-6 6 6",
  expand: "m6 9 6 6 6-6",
  refresh: "M20 7v5h-5M4 17v-5h5M6.1 6.1A8 8 0 0 1 20 12M4 12a8 8 0 0 0 13.9 5.9",
  approve: "m5 12 4 4L19 6",
  skip: "m5 5 10 7-10 7ZM19 5v14",
  schedule: "M7 3v4M17 3v4M3 10h18M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2M8 14h3v3H8Z",
  edit: "m15 5 4 4M4 16l-1 5 5-1L20 8a2.8 2.8 0 0 0-4-4Z",
  close: "m6 6 12 12M6 18 18 6",
  save: "M5 3h12l4 4v14H3V3ZM7 3v6h10V3M7 21v-8h10v8",
  discard: "M8 4 3 9l5 5M3 9h11a6 6 0 0 1 0 12h-3",
  render: "m9 5 11 7-11 7ZM3 5v14",
  remove: "M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7",
  restore: "M8 4 3 9l5 5M3 9h11a6 6 0 0 1 0 12h-3",
  drag: "M12 2v20M2 12h20m-13-7 3-3 3 3m-6 14 3 3 3-3M5 9l-3 3 3 3m14-6 3 3-3 3",
  add: "M12 5v14M5 12h14",
  download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
};

export function MediaActionIcon({ action }: { action: keyof typeof paths }) {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={paths[action]} /></svg>;
}
