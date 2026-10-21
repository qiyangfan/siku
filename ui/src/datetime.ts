// 固定使用 zh-CN、公历和 24 小时制；非法输入原样返回。
const DATE_TIME_FORMAT = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export function formatDateTime(iso: string | number | Date): string {
  const moment = iso instanceof Date ? iso : new Date(iso);
  if (Number.isNaN(moment.getTime())) {
    return String(iso);
  }
  return DATE_TIME_FORMAT.format(moment);
}
