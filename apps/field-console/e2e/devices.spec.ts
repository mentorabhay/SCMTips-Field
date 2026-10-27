import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Device Registry & Revoke (SCR2.01 / TC2.157, TC2.159)", () => {
  test("renders registry with devices, filters, and stale status", async ({ page }) => {
    await page.goto("/devices");

    // Header & Badge check
    await expect(page.getByRole("heading", { name: "Device Registry" })).toBeVisible();
    await expect(page.getByText("SCR2.01 · FR2.067")).toBeVisible();

    // Table rows
    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    await expect(page.getByText("Google Pixel 8 Pro")).toBeVisible();
    await expect(page.getByText("Ray-Ban Meta Gen 2")).toBeVisible();

    // Stale device flag
    await expect(page.getByText("Stale (> 15m)")).toBeVisible();

    // Filter by kind: glasses
    await page.getByLabel("Filter by Device Kind").selectOption("glasses");
    await expect(page.getByText("Ray-Ban Meta Gen 2")).toBeVisible();
    await expect(page.getByText("Google Pixel 8 Pro")).not.toBeVisible();

    // Reset filter
    await page.getByLabel("Filter by Device Kind").selectOption("all");

    // Search filter
    const searchInput = page.getByPlaceholder("Search by serial, model, or site...");
    await searchInput.fill("PH-8P-440192");
    await expect(page.getByText("Google Pixel 8 Pro")).toBeVisible();
    await expect(page.getByText("Samsung Galaxy XCover 6 Pro")).not.toBeVisible();

    // WCAG 2.1 AA Accessibility audit (TC2.159)
    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(accessibilityScanResults.violations).toEqual([]);
  });

  test("device detail page supports revocation with confirmation", async ({ page }) => {
    await page.goto("/devices/dev-phone-001");

    // Header and details
    await expect(page.getByRole("heading", { name: "Google Pixel 8 Pro" })).toBeVisible();
    await expect(page.getByText("Single active pairing enforced (TC2.103)")).toBeVisible();
    await expect(page.getByText("SCR2.09")).toBeVisible();

    // Heartbeat history table
    await expect(page.getByText("24-Hour Heartbeat History")).toBeVisible();

    // Revocation flow
    const revokeBtn = page.getByRole("button", { name: "Revoke Device Access" });
    await expect(revokeBtn).toBeVisible();
    await revokeBtn.click();

    // Modal dialog
    const modal = page.getByRole("dialog");
    await expect(modal).toBeVisible();
    await expect(modal.getByText("Revoke Device Access")).toBeVisible();

    // Type serial number confirmation
    const confirmInput = modal.getByPlaceholder("PH-8P-440192");
    await confirmInput.fill("PH-8P-440192");

    const confirmBtn = modal.getByRole("button", { name: "Confirm Revoke" });
    await expect(confirmBtn).toBeEnabled();
    await confirmBtn.click();

    // Verify MSG2.19 banner displayed and status updated to Revoked
    await expect(page.getByText("Device Revocation Enforced")).toBeVisible();
    await expect(
      page.getByText("Access terminated and remote session cleared.")
    ).toBeVisible();
    await expect(page.getByText("Revoked")).toBeVisible();
  });
});
