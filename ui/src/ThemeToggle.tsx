import { ActionIcon, useComputedColorScheme, useMantineColorScheme } from "@mantine/core";
import { IconMoon, IconSun } from "@tabler/icons-react";

/** header 操作区的主题切换入口：两态图标切换，跟随系统为初值（无第三态控件）。 */
export function ThemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const colorScheme = useComputedColorScheme("light", { getInitialValueInEffect: false });
  const nextScheme = colorScheme === "light" ? "dark" : "light";

  return (
    <ActionIcon
      type="button"
      variant="subtle"
      className="theme-toggle"
      aria-label={nextScheme === "dark" ? "切换为暗色" : "切换为亮色"}
      onClick={() => setColorScheme(nextScheme)}
    >
      {nextScheme === "dark" ? (
        <IconMoon size={20} stroke={1.8} aria-hidden="true" />
      ) : (
        <IconSun size={20} stroke={1.8} aria-hidden="true" />
      )}
    </ActionIcon>
  );
}
