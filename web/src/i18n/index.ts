export { tr } from "./tr";
import { tr } from "./tr";

const dateTime = new Intl.DateTimeFormat("tr-TR", {
  timeZone: "Europe/Istanbul", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit",
});
export function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? tr.unset : dateTime.format(date);
}
export const statusLabel = (value: string) => tr.statuses[value] ?? tr.statuses.unknown;
