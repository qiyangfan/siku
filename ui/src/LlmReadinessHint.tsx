import { useEffect, useState } from "react";
import { Button, Group } from "@mantine/core";
import { getSettings, type AskReadiness } from "./api";

/**
 * wiki/图谱空态的模型就绪提示（信息层，不做门控）：LLM 凭证缺失时说明缺项并给
 * 「去设置」入口；就绪时说明可直接构建。就绪判定复用 ask_readiness 的稳定
 * 机器 token（本组件只关心 llm.api_key）；读取失败或形状不可得时静默省略
 * （fail-open），不阻塞空态卡片的主行动按钮。
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

  if (!readiness.missing.includes("llm.api_key")) {
    return (
      <p className="hint" role="note">
        模型通道已就绪：点击下方按钮即可开始，真实模型调用可能需要几分钟。
      </p>
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
