"""Scripted capture for Amazon — navigates URLs to generate API traffic."""

from __future__ import annotations


async def run(page, context) -> None:  # noqa: ARG001
    """Navigate Amazon pages to generate API traffic for capture."""
    # Home page
    await page.goto("https://www.amazon.com", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Search results page (URL-based, no selector needed)
    await page.goto(
        "https://www.amazon.com/s?k=wireless+headphones", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(3000)

    # Product detail page (a known ASIN)
    await page.goto(
        "https://www.amazon.com/dp/B09WX4GJ6T", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(3000)

    # Category browse — electronics
    await page.goto(
        "https://www.amazon.com/s?i=electronics&rh=n%3A172282", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(3000)

    # Best sellers
    await page.goto(
        "https://www.amazon.com/gp/bestsellers/", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(3000)

    # Today's deals
    await page.goto(
        "https://www.amazon.com/gp/goldbox", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(2000)
