// 日期时间展示单源:固定 zh-CN + 公历 24 小时制(走查发现 2026-09 ④核销)。
// 禁裸 `toLocaleString()`——其随宿主系统 locale 漂移,英文系统呈现美式 12 小时制,
// 与全中文产品口径相悖;非法输入按原样回退,由调用方保证可读性。
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
