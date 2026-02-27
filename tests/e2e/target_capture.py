"""Scripted capture for Target — navigates URLs to generate API traffic."""

from __future__ import annotations


async def run(page, context) -> None:  # noqa: ARG001
    """Navigate Target pages to generate API traffic for capture."""
    # Home page
    await page.goto("https://www.target.com", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Search results
    await page.goto(
        "https://www.target.com/s?searchTerm=coffee+maker", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(3000)

    # Electronics category
    await page.goto(
        "https://www.target.com/c/electronics/-/N-5xtg6", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(3000)

    # Top deals
    await page.goto(
        "https://www.target.com/c/top-deals/-/N-2bfcq", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(2000)

    # Grocery
    await page.goto(
        "https://www.target.com/c/grocery/-/N-5xt1a", wait_until="domcontentloaded"
    )
    await page.wait_for_timeout(2000)
