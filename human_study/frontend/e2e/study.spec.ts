import { test, expect } from '@playwright/test';

test('mobile keyboard flow, refresh and internal receipt', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/study');
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Begin study' }).click();
  for (let i = 0; i < 37; i++) {
    const question = page.getByRole('heading', { level: 2 });
    await expect(page.getByRole('radio').first()).toBeVisible();
    if (i === 17) {
      const wording = await question.textContent();
      await page.reload();
      await expect(question).toHaveText(wording!);
    }
    await page.getByRole('radio').first().focus();
    await page.keyboard.press('Space');
    await expect(page.getByRole('radio').first()).toBeChecked();
    await page.getByRole('button', { name: 'Save and continue' }).click();
    await expect(page.getByText(`${i + 1} of 37 questions saved`, { exact: false })).toBeVisible();
  }
  await page.getByRole('button', { name: 'Finish study' }).click();
  await expect(page.getByTestId('receipt')).toHaveText(/^[A-F0-9]{12}$/);
  const receipt = await page.getByTestId('receipt').textContent();
  await page.reload();
  await expect(page.getByTestId('receipt')).toHaveText(receipt!);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/mobile-receipt.png', fullPage: true });
});

test('network failure offers retry without changing the question', async ({ page }) => {
  await page.goto('/study');
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Begin study' }).click();
  await expect(page.getByRole('radio').first()).toBeVisible();
  const wording = await page.getByRole('heading', { level: 2 }).textContent();
  let fail = true;
  await page.route('**/api/human/answer', route => fail ? (fail = false, route.abort()) : route.continue());
  await page.getByRole('radio').first().check();
  await page.getByRole('button', { name: 'Save and continue' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('heading', { level: 2 })).toHaveText(wording!);
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByText('1 of 37 questions saved', { exact: false })).toBeVisible();
});
