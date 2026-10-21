import { useEffect, useState } from "react";
import { Button, Group } from "@mantine/core";
import { getSettings, type AskReadiness } from "./api";

/**
 * wiki/图谱空态的模型就绪提示（不门控）；缺少 LLM 凭证时给出设置入口，
 * 读取失败时静默省略。
 */
export function LlmReadinessHint({ onGoToSettings }: { onGoToSettings: () => void }) {
  const [readiness, setReadiness] = useState<AskReadiness | null>(null);

  useEffect(() => {
    let current = true;
    getSettings()
      .then((settings) => {
        if (!current) {
          return;
        }
        const candidate = settings.ask_readiness;
        setReadiness(
          typeof candidate?.ready === "boolean" && Array.isArray(candidate?.missing)
            ? candidate
            : null,
        );
      })
      .catch(() => {
        if (current) {
          setReadiness(null);
        }
      });
    return () => {
      current = false;
    };
  }, []);

  if (readiness === null) {
    return null;
  }

  const llmInvalid = (readiness.invalid ?? []).some((token) => token.startsWith("llm."));
  if (!readiness.missing.includes("llm.api_key") && !llmInvalid) {
    return (
      <p className="hint" role="note">
        模型通道已就绪：点击下方按钮即可开始，真实模型调用可能需要几分钟。
      </p>
    );
  }
  if (llmInvalid) {
    return (
      <Group className="llm-readiness-missing" gap="sm" wrap="wrap" role="note">
        <p className="hint">
          构建需要调用 LLM 通道，当前其配置无效（如接口协议取值越界，来自优先级更高的
          环境变量层）；建议先在「设置」查看无效警示，也可以直接尝试构建。
        </p>
        <Button variant="subtle" type="button" onClick={onGoToSettings}>
          去设置
        </Button>
      </Group>
    );
  }
  return (
    <Group className="llm-readiness-missing" gap="sm" wrap="wrap" role="note">
      <p className="hint">
        构建需要调用 LLM 通道，当前其 API key 未配置；建议先在「设置」完成模型配置，
        也可以直接尝试构建。
      </p>
      <Button variant="subtle" type="button" onClick={onGoToSettings}>
        去设置
      </Button>
    </Group>
  );
}
