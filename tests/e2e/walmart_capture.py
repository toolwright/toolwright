"""Scripted capture for Walmart — navigates URLs to generate API traffic."""

from __future__ import annotations


async def run(page, context) -> None:  # noqa: ARG001
    """Navigate Walmart pages to generate API traffic for capture."""
    # Home page
    await page.goto("https://www.walmart.com", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Search results
    await page.goto(
        "https://www.walmart.com/search?q=bluetooth+speaker", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(3000)

    # Product page
    await page.goto(
        "https://www.walmart.com/browse/electronics/3944", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(3000)

    # Grocery
    await page.goto(
        "https://www.walmart.com/browse/food/976759", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(2000)

    # Deals
    await page.goto(
        "https://www.walmart.com/shop/deals", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(2000)
