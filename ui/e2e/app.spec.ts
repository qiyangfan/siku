import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const VIEWS = ["浏览", "图谱", "wiki", "资料库", "设置"] as const;

async function expectNoWcagViolations(
  page: Page,
  context: string,
): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations, `${context} 存在 WCAG A/AA 违规`).toEqual([]);
}

test("问答页加载且无 WCAG A/AA 违规", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "问问你的知识库" }),
  ).toBeVisible();
  await expectNoWcagViolations(page, "问答页");
});

for (const label of VIEWS) {
  test(`${label} 视图可切换且无 WCAG A/AA 违规`, async ({ page }) => {
    await page.goto("/");
    await page.getByRole("tab", { name: label }).click();
    await expect(page.getByRole("tab", { name: label })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expectNoWcagViolations(page, `${label} 视图`);
  });
}
