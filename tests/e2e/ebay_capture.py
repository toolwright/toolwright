"""Scripted capture for eBay — navigates URLs to generate API traffic."""

from __future__ import annotations


async def run(page, context) -> None:  # noqa: ARG001
    """Navigate eBay pages to generate API traffic for capture."""
    # Home page
    await page.goto("https://www.ebay.com", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Search results
    await page.goto(
        "https://www.ebay.com/sch/i.html?_nkw=vintage+watch", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(3000)

    # Electronics category
    await page.goto(
        "https://www.ebay.com/b/Electronics/bn_7000259124", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(3000)

    # Daily deals
    await page.goto("https://www.ebay.com/deals", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    # Collectibles
    await page.goto(
        "https://www.ebay.com/b/Collectibles/1", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(2000)

    # Motors
    await page.goto(
        "https://www.ebay.com/b/Auto-Parts-and-Vehicles/6000", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(2000)
