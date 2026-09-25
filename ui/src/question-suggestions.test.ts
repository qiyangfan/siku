import { describe, expect, it } from "vitest";
import type { NoteDetail, NoteSummary, WikiEntryDetail } from "./api";
import { buildQuestionSuggestions } from "./question-suggestions";

const note: NoteSummary = {
  source_id: "doc-1",
  source_name: "notes-from-interviews.md",
  note_path: "notes/doc-1.md",
  source_hash: "a".repeat(64),
  extractor: "MarkdownExtractor",
};

const detail: NoteDetail = {
  ...note,
  anchors: ["用户研究与访谈结论"],
  content: "# 访谈洞察\n\n## 用户研究与访谈结论\n访谈记录。",
};

const wikiEntry: WikiEntryDetail = {
  community_id: 4,
  title: "社区 0004",
  content: "# 社区 0004\n\n## 成员实体\n\n- 本地检索（能力）\n- 向量索引（组件）\n\n## 关键关系\n",
  generated_at: "2026-09-24T00:00:00Z",
};

describe("根据本地知识构造提问建议", () => {
  it("从笔记标题、章节和 wiki 实体生成建议", () => {
    expect(buildQuestionSuggestions([note], [detail], wikiEntry)).toEqual([
      {
        question: "《访谈洞察》中「用户研究与访谈结论」的核心内容是什么？",
        label: "《访谈洞察》中「用户研究与访谈结论」的核心内容是什么？",
      },
      {
        question: "知识图谱中「本地检索」和「向量索引」有哪些关联？",
        label: "知识图谱中「本地检索」和「向量索引」有哪些关联？",
      },
    ]);
  });

  it("跳过 content 这类抽取占位章节名", () => {
    const thermodynamics = {
      ...note,
      source_id: "thermodynamics-1",
      source_name: "热力学基础.md",
    };
    const thermodynamicsDetail = {
      ...detail,
      source_id: "thermodynamics-1",
      source_name: "热力学基础.md",
      anchors: ["content"],
      content: "# content\n\n## content\n\n热力学的基本概念。",
    };

    expect(buildQuestionSuggestions([thermodynamics], [thermodynamicsDetail], undefined)).toEqual([
      {
        question: "《热力学基础》的核心内容是什么？",
        label: "《热力学基础》的核心内容是什么？",
      },
    ]);
  });

  it("跳过通用文件名，并继续查找后续可读标题", () => {
    const genericNotes = [
      { ...note, source_id: "generic-1", source_name: "content.md" },
      { ...note, source_id: "generic-2", source_name: "body.md" },
      { ...note, source_id: "thermodynamics-2", source_name: "热力学基础.md" },
    ];

    expect(buildQuestionSuggestions(genericNotes, [], undefined)).toEqual([
      {
        question: "《热力学基础》的核心内容是什么？",
        label: "《热力学基础》的核心内容是什么？",
      },
    ]);
    expect(buildQuestionSuggestions([genericNotes[0]], [], undefined)).toEqual([]);
  });

  it("把已导入的 SKILL.md 当作笔记处理", () => {
    const skill = { ...note, source_id: "skill-1", source_name: "SKILL.md" };
    const skillDetail = {
      ...detail,
      source_id: "skill-1",
      source_name: "SKILL.md",
      anchors: ["验证流程"],
      content: "# 前端质量闸门\n\n## 验证流程\n按步骤执行。",
    };
    expect(buildQuestionSuggestions([skill], [skillDetail], undefined)[0]?.question).toBe(
      "已导入技能「前端质量闸门」中「验证流程」规定了什么？",
    );
  });

  it("没有可用标题或实体时返回空列表，不伪造问题", () => {
    const emptyWiki = { ...wikiEntry, content: "# 社区 0004\n\n## 成员实体\n" };
    expect(buildQuestionSuggestions([], [], emptyWiki)).toEqual([]);
  });

  it("限制建议数量，长标题可读且完整问题仍保留原文", () => {
    const longTitle = "跨团队本地优先知识治理、自动化研发协作与长期服务恢复完整实践指南";
    const longSection = "导入资料版本变更与冲突处理、旧内容清理以及索引重建的完整操作流程";
    const longNote = {
      ...note,
      source_id: "long-1",
      source_name: `${longTitle}.md`,
    };
    const longDetail = {
      ...detail,
      source_id: "long-1",
      content: `# ${longTitle}`,
      anchors: [longSection],
    };
    const suggestions = buildQuestionSuggestions(
      [longNote, { ...note, source_id: "doc-2" }, { ...note, source_id: "doc-3" }],
      [longDetail],
      wikiEntry,
    );
    expect(suggestions).toHaveLength(3);
    expect(suggestions[0].question).toContain(longTitle);
    expect(suggestions[0].question).toContain(longSection);
    expect([...suggestions[0].label].length).toBeLessThan([...suggestions[0].question].length);
  });
});
