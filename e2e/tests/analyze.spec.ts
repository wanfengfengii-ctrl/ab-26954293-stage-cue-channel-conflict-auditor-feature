import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const fixturesDir = fileURLToPath(new URL("../fixtures", import.meta.url));

function fixture(name: string): string {
  return path.join(fixturesDir, name);
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "灯光 Cue 冲突检查" })).toBeVisible();
});

test("上传含冲突的 cue 文件：逐条展示通道、双方 cue 与确定区间，并可按通道筛选", async ({
  page,
}) => {
  await page.setInputFiles('[data-testid="file-input"]', fixture("conflict.json"));

  await expect(page.getByTestId("status-banner")).toContainText("2 处通道冲突");
  await expect(page.getByTestId("status-banner")).toContainText("共检查 2 个通道");
  await expect(page.getByTestId("conflict-row")).toHaveCount(2);

  // 结果按通道、重叠起点、重叠终点、cue 名排序：通道 1 在前
  const firstRow = page.getByTestId("conflict-row").first();
  await expect(firstRow).toContainText("开场");
  await expect(firstRow).toContainText("追光");
  await expect(firstRow).toContainText("[500, 1000)");

  // 按通道筛选后只剩通道 2 的冲突
  await page.getByTestId("channel-filter").selectOption("2");
  await expect(page.getByTestId("conflict-row")).toHaveCount(1);
  const filtered = page.getByTestId("conflict-row").first();
  await expect(filtered).toContainText("侧光");
  await expect(filtered).toContainText("顶光");
  await expect(filtered).toContainText("[600, 800)");

  // 回到全部通道
  await page.getByTestId("channel-filter").selectOption("all");
  await expect(page.getByTestId("conflict-row")).toHaveCount(2);
});

test("无冲突文件：显示可放行与检查通道数", async ({ page }) => {
  await page.setInputFiles('[data-testid="file-input"]', fixture("clean.json"));

  await expect(page.getByTestId("status-banner")).toContainText("可放行");
  await expect(page.getByTestId("status-banner")).toContainText("2 个通道");
  await expect(page.getByTestId("conflict-row")).toHaveCount(0);
});

test("非法文件：422 错误标明数组下标，且清除旧报告", async ({ page }) => {
  // 先上传一份有冲突的合法文件，确认报告出现
  await page.setInputFiles('[data-testid="file-input"]', fixture("conflict.json"));
  await expect(page.getByTestId("conflict-row")).toHaveCount(2);

  // 再上传非法文件：旧报告被清除，错误带下标
  await page.setInputFiles('[data-testid="file-input"]', fixture("invalid.json"));
  await expect(page.getByTestId("error-panel")).toBeVisible();
  await expect(page.getByTestId("error-item")).toHaveCount(2);
  await expect(page.getByTestId("error-item").nth(0)).toContainText("数组下标 1");
  await expect(page.getByTestId("error-item").nth(0)).toContainText("channel");
  await expect(page.getByTestId("error-item").nth(1)).toContainText("数组下标 2");
  await expect(page.getByTestId("conflict-row")).toHaveCount(0);
  await expect(page.getByTestId("status-banner")).toHaveCount(0);
});

test("JSON 语法损坏：整体报错且不展示任何分析结果", async ({ page }) => {
  await page.setInputFiles('[data-testid="file-input"]', fixture("malformed.json"));

  await expect(page.getByTestId("error-panel")).toBeVisible();
  await expect(page.getByTestId("error-item").first()).toContainText("整体");
  await expect(page.getByTestId("report-panel")).toHaveCount(0);
});

test("校验失败后重新上传合法文件可恢复", async ({ page }) => {
  await page.setInputFiles('[data-testid="file-input"]', fixture("invalid.json"));
  await expect(page.getByTestId("error-panel")).toBeVisible();

  await page.setInputFiles('[data-testid="file-input"]', fixture("clean.json"));
  await expect(page.getByTestId("status-banner")).toContainText("可放行");
  await expect(page.getByTestId("error-panel")).toHaveCount(0);
});

test("回归：cue 名称顺序与时间顺序不一致时，真实重叠不得被判为可放行", async ({
  page,
}) => {
  await page.setInputFiles('[data-testid="file-input"]', fixture("order-trap.json"));

  await expect(page.getByTestId("status-banner")).toContainText("1 处通道冲突");
  await expect(page.getByTestId("status-banner")).not.toContainText("可放行");
  await expect(page.getByTestId("conflict-row")).toHaveCount(1);
  const row = page.getByTestId("conflict-row").first();
  await expect(row).toContainText("A-长渐变");
  await expect(row).toContainText("C-叠加");
  await expect(row).toContainText("[400, 700)");
});

test("抢值时间窗：链式合并展示，点击下钻相交冲突，再次点击恢复", async ({ page }) => {
  await page.setInputFiles('[data-testid="file-input"]', fixture("windows.json"));

  await expect(page.getByTestId("status-banner")).toContainText("5 处通道冲突");
  await expect(page.getByTestId("conflict-row")).toHaveCount(5);

  // 时间窗按通道、起点排序：通道 1 的链式合并窗口在前
  const windows = page.getByTestId("contention-window");
  await expect(windows).toHaveCount(3);
  await expect(windows.nth(0)).toContainText("通道 1");
  await expect(windows.nth(0)).toContainText("[200, 1000)");
  await expect(windows.nth(0)).toContainText("3 处冲突");
  await expect(windows.nth(1)).toContainText("[1100, 1200)");
  await expect(windows.nth(2)).toContainText("通道 2");

  // 点击链式合并窗口：只显示与该窗相交的 3 条冲突
  await windows.nth(0).click();
  await expect(page.getByTestId("conflict-row")).toHaveCount(3);
  await expect(page.getByTestId("window-filter-note")).toBeVisible();
  await expect(page.getByTestId("conflict-row").nth(0)).toContainText("[200, 600)");
  await expect(page.getByTestId("conflict-row").nth(2)).toContainText("[500, 1000)");

  // 再次点击同一窗口：恢复当前通道的全部明细
  await page.getByTestId("contention-window").nth(0).click();
  await expect(page.getByTestId("conflict-row")).toHaveCount(5);
  await expect(page.getByTestId("window-filter-note")).toHaveCount(0);

  // 独立窗口只定位到自己的 1 条冲突
  await page.getByTestId("contention-window").nth(1).click();
  await expect(page.getByTestId("conflict-row")).toHaveCount(1);
  await expect(page.getByTestId("conflict-row").first()).toContainText("[1100, 1200)");
});

test("无冲突文件不出现时间窗；上传新文件清除时间窗选择", async ({ page }) => {
  // 先上传带冲突文件并选中一个时间窗
  await page.setInputFiles('[data-testid="file-input"]', fixture("windows.json"));
  await expect(page.getByTestId("contention-window")).toHaveCount(3);
  await page.getByTestId("contention-window").first().click();
  await expect(page.getByTestId("conflict-row")).toHaveCount(3);

  // 上传无冲突文件：时间窗与选择一并消失，只显示可放行
  await page.setInputFiles('[data-testid="file-input"]', fixture("clean.json"));
  await expect(page.getByTestId("status-banner")).toContainText("可放行");
  await expect(page.getByTestId("contention-window")).toHaveCount(0);
  await expect(page.getByTestId("conflict-row")).toHaveCount(0);
  await expect(page.getByTestId("window-filter-note")).toHaveCount(0);
});

test("校验失败不保留报告与时间窗，重传合法文件后可正常下钻", async ({ page }) => {
  await page.setInputFiles('[data-testid="file-input"]', fixture("windows.json"));
  await expect(page.getByTestId("contention-window")).toHaveCount(3);

  // 校验失败：只展示错误，不保留上份报告与时间窗
  await page.setInputFiles('[data-testid="file-input"]', fixture("invalid.json"));
  await expect(page.getByTestId("error-panel")).toBeVisible();
  await expect(page.getByTestId("contention-window")).toHaveCount(0);
  await expect(page.getByTestId("report-panel")).toHaveCount(0);

  // 重传合法文件：报告与时间窗恢复，可正常下钻
  await page.setInputFiles('[data-testid="file-input"]', fixture("windows.json"));
  await expect(page.getByTestId("contention-window")).toHaveCount(3);
  await page.getByTestId("contention-window").first().click();
  await expect(page.getByTestId("conflict-row")).toHaveCount(3);
});
