"""Scripted capture for DummyJSON API — exercises products, carts, users endpoints."""

from __future__ import annotations


async def run(page, context) -> None:  # noqa: ARG001
    """Exercise DummyJSON API endpoints via browser fetch calls."""
    # Products - collection
    await page.evaluate("fetch('https://dummyjson.com/products?limit=5')")
    await page.wait_for_timeout(500)

    # Products - single
    await page.evaluate("fetch('https://dummyjson.com/products/1')")
    await page.wait_for_timeout(500)

    # Products - search
    await page.evaluate("fetch('https://dummyjson.com/products/search?q=phone')")
    await page.wait_for_timeout(500)

    # Products - categories
    await page.evaluate("fetch('https://dummyjson.com/products/categories')")
    await page.wait_for_timeout(500)

    # Users - collection
    await page.evaluate("fetch('https://dummyjson.com/users?limit=5')")
    await page.wait_for_timeout(500)

    # Users - single
    await page.evaluate("fetch('https://dummyjson.com/users/1')")
    await page.wait_for_timeout(500)

    # Carts - collection
    await page.evaluate("fetch('https://dummyjson.com/carts')")
    await page.wait_for_timeout(500)

    # Carts - single
    await page.evaluate("fetch('https://dummyjson.com/carts/1')")
    await page.wait_for_timeout(500)

    # Posts
    await page.evaluate("fetch('https://dummyjson.com/posts?limit=5')")
    await page.wait_for_timeout(500)

    # Posts - single
    await page.evaluate("fetch('https://dummyjson.com/posts/1')")
    await page.wait_for_timeout(500)

    # Comments for a post
    await page.evaluate("fetch('https://dummyjson.com/posts/1/comments')")
    await page.wait_for_timeout(500)

    # Recipes
    await page.evaluate("fetch('https://dummyjson.com/recipes?limit=5')")
    await page.wait_for_timeout(500)

    # Auth - login (POST)
    await page.evaluate("""
        fetch('https://dummyjson.com/auth/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username: 'emilys', password: 'emilyspass'})
        })
    """)
    await page.wait_for_timeout(500)

    # Add to cart (POST)
    await page.evaluate("""
        fetch('https://dummyjson.com/carts/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({userId: 1, products: [{id: 1, quantity: 1}]})
        })
    """)
    await page.wait_for_timeout(500)

    # Todos
    await page.evaluate("fetch('https://dummyjson.com/todos?limit=5')")
    await page.wait_for_timeout(500)

    # Quotes
    await page.evaluate("fetch('https://dummyjson.com/quotes?limit=5')")
    await page.wait_for_timeout(500)
