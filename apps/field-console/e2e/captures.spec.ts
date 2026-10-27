import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Capture Inspector (SCR2.02 / TC2.158, TC2.159)", () => {
  test("renders capture details, evidence crop, rank breakdown, and timings waterfall", async ({ page }) => {
    await page.goto("/captures/cap-0192a-sample");

    // Header checks
    await expect(page.getByRole("heading", { name: "Capture Inspector" })).toBeVisible();
    await expect(page.getByText("SCR2.02 · FR2.068")).toBeVisible();
    await expect(page.getByText("On-Task Match")).toBeVisible();
    await expect(page.getByText("Blur Applied (PR2.13)")).toBeVisible();

    // Evidence Crop Preview with 16px bystander blur label
    await expect(page.getByText("Evidence Crop (Signed S3 URL · 60 s TTL)")).toBeVisible();
    await expect(page.getByText("16px Bystander Block Blur Applied")).toBeVisible();

    // 6-Factor Rank Breakdown
    await expect(page.getByText("6-Factor Rank Breakdown")).toBeVisible();
    await expect(page.getByText("Center Proximity (w=0.3)")).toBeVisible();
    await expect(page.getByText("Task Line Match (w=0.25)")).toBeVisible();
    await expect(page.getByText("Readability (Motion Adj) (w=0.2)")).toBeVisible();

    // AI Verification section
    await expect(page.getByText("AI Verification (P13b Registry)")).toBeVisible();
    await expect(page.getByText("muse-spark-1.3")).toBeVisible();
    await expect(page.getByText("Non-contributor data guarantee enforced (FR2.059)")).toBeVisible();

    // Timings waterfall
    await expect(page.getByText("Timings Waterfall")).toBeVisible();
    await expect(page.getByText("shutter (t0)")).toBeVisible();
    await expect(page.getByText("lens_drawn")).toBeVisible();

    // Voice turns
    await expect(page.getByText("Confirmed Voice Turns")).toBeVisible();
    await expect(page.getByText('"count twelve"')).toBeVisible();
    await expect(page.getByText('"confirm"')).toBeVisible();

    // Accessibility test (TC2.159)
    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(accessibilityScanResults.violations).toEqual([]);
  });
});
