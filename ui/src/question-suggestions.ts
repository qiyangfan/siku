import type { NoteDetail, NoteSummary, WikiEntryDetail } from "./api";

const MAX_NOTE_SUGGESTIONS = 2;
const MAX_SUGGESTIONS = 3;
const MAX_TITLE_LENGTH = 24;
const MAX_HEADING_LENGTH = 20;
const GENERIC_SECTION_TITLES = new Set([
  "body",
  "content",
  "contents",
  "doc",
  "document",
  "text",
  "unknown",
  "untitled",
  "正文",
  "正文内容",
  "内容",
  "文档内容",
  "全文",
  "章节内容",
]);

export type QuestionSuggestion = {
  question: string;
  label: string;
};

function shorten(value: string, maxLength: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  const characters = [...normalized];
  if (characters.length <= maxLength) {
    return normalized;
  }
  return `${characters.slice(0, maxLength - 1).join("")}…`;
}

function firstMarkdownTitle(content: string): string | null {
  const heading = content
    .split(/\r?\n/)
    .find((line) => /^#\s+\S/.test(line));
  return heading?.replace(/^#\s+/, "").trim() || null;
}

function displaySectionTitle(value: string): string | null {
  const title = value.replace(/\s+/g, " ").trim();
  const key = title
    .replace(/^[#\s]+|[\s\p{P}\p{S}]+$/gu, "")
    .toLocaleLowerCase("en-US");
  if (!title || GENERIC_SECTION_TITLES.has(key)) {
    return null;
  }
  return title;
}

function displayTitle(note: NoteSummary, detail: NoteDetail | undefined): string | null {
  const sectionTitle = displaySectionTitle(firstMarkdownTitle(detail?.content ?? "") ?? "");
  const sourceTitle = note.source_name
    .replace(/\.(md|markdown|pdf|docx?|pptx?|xlsx?|epub|html?)$/i, "")
    .split(/[\\/]/)
    .at(-1)
    ?.trim() ?? "";
  const basename = sectionTitle ?? displaySectionTitle(sourceTitle);
  if (!basename) {
    return null;
  }
  if (/^skill$/i.test(basename) && isSkillNote(note)) {
    return "使用说明";
  }
  return basename.replace(/[_-]+/g, " ");
}

function isSkillNote(note: NoteSummary): boolean {
  return /(^|[/\\])skill(?:\.md|\.markdown)?$/i.test(note.source_name.trim()) ||
    /\bskills?\b/i.test(note.source_name);
}

function noteSuggestion(note: NoteSummary, detail: NoteDetail | undefined): QuestionSuggestion | null {
  const title = displayTitle(note, detail);
  if (!title) {
    return null;
  }
  const section = detail?.anchors
    .map(displaySectionTitle)
    .find((anchor): anchor is string => anchor !== null);
  const fullLocation = section ? `中「${section}」` : "";
  const shortLocation = section ? `中「${shorten(section, MAX_HEADING_LENGTH)}」` : "";
  if (isSkillNote(note)) {
    return {
      question: `已导入技能「${title}」${fullLocation}规定了什么？`,
      label: `已导入技能「${shorten(title, MAX_TITLE_LENGTH)}」${shortLocation}规定了什么？`,
    };
  }
  return {
    question: `《${title}》${fullLocation}的核心内容是什么？`,
    label: `《${shorten(title, MAX_TITLE_LENGTH)}》${shortLocation}的核心内容是什么？`,
  };
}

function wikiMemberNames(content: string): string[] {
  const lines = content.split(/\r?\n/);
  const sectionStart = lines.findIndex((line) => /^##\s+成员实体\s*$/.test(line.trim()));
  if (sectionStart < 0) {
    return [];
  }

  const names: string[] = [];
  for (const line of lines.slice(sectionStart + 1)) {
    if (/^##\s+/.test(line.trim())) {
      break;
    }
    const match = line.match(/^\s*-\s+(.+?)\s*$/);
    if (!match) {
      continue;
    }
    const name = match[1].split("（", 1)[0].split(" — ", 1)[0].trim();
    if (name && !names.includes(name)) {
      names.push(name);
    }
  }
  return names;
}

function wikiSuggestion(entry: WikiEntryDetail | undefined): QuestionSuggestion | null {
  if (!entry) {
    return null;
  }
  const members = wikiMemberNames(entry.content);
  if (members.length >= 2) {
    return {
      question: `知识图谱中「${members[0]}」和「${members[1]}」有哪些关联？`,
      label: `知识图谱中「${shorten(members[0], MAX_TITLE_LENGTH)}」和「${shorten(members[1], MAX_TITLE_LENGTH)}」有哪些关联？`,
    };
  }
  if (members.length === 1) {
    return {
      question: `知识图谱中「${members[0]}」与哪些内容有关联？`,
      label: `知识图谱中「${shorten(members[0], MAX_TITLE_LENGTH)}」与哪些内容有关联？`,
    };
  }
  return null;
}

export function buildQuestionSuggestions(
  notes: NoteSummary[],
  noteDetails: NoteDetail[],
  wikiEntry: WikiEntryDetail | undefined,
): QuestionSuggestion[] {
  const detailBySource = new Map(noteDetails.map((detail) => [detail.source_id, detail]));
  const seen = new Set<string>();
  const candidates: QuestionSuggestion[] = [];
  const addUnique = (suggestion: QuestionSuggestion | null) => {
    if (!suggestion) {
      return;
    }
    const key = suggestion.question.toLocaleLowerCase("zh-CN");
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    candidates.push(suggestion);
  };

  for (const note of notes) {
    if (candidates.length >= MAX_NOTE_SUGGESTIONS) {
      break;
    }
    addUnique(noteSuggestion(note, detailBySource.get(note.source_id)));
  }
  addUnique(wikiSuggestion(wikiEntry));
  return candidates.slice(0, MAX_SUGGESTIONS);
}
