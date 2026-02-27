"""Scripted capture for StockX — navigates URLs to generate API traffic."""

from __future__ import annotations


async def run(page, context) -> None:  # noqa: ARG001
    """Navigate StockX pages to generate API traffic for capture."""
    # Home page
    await page.goto("https://stockx.com", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Search results
    await page.goto(
        "https://stockx.com/search?s=jordan+1+retro", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(3000)

    # Product page (known slug)
    await page.goto(
        "https://stockx.com/air-jordan-1-retro-high-og-chicago-lost-and-found",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(3000)

    # Sneakers category
    await page.goto("https://stockx.com/sneakers", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Electronics category
    await page.goto("https://stockx.com/electronics", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    # Apparel
    await page.goto("https://stockx.com/apparel", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
