"""Scripted capture for TCGplayer — navigates URLs to generate API traffic."""

from __future__ import annotations


async def run(page, context) -> None:  # noqa: ARG001
    """Navigate TCGplayer pages to generate API traffic for capture."""
    # Home page
    await page.goto("https://www.tcgplayer.com", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Search results
    await page.goto(
        "https://www.tcgplayer.com/search/all/product?q=charizard",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(3000)

    # Magic: The Gathering category
    await page.goto(
        "https://www.tcgplayer.com/categories/trading-card-games/magic-the-gathering",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(3000)

    # Pokemon category
    await page.goto(
        "https://www.tcgplayer.com/categories/trading-card-games/pokemon",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(2000)

    # Yu-Gi-Oh
    await page.goto(
        "https://www.tcgplayer.com/categories/trading-card-games/yugioh",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(2000)
