"""Tests for catalog-driven tool proposal compilation."""

from __future__ import annotations

from toolwright.core.normalize import EndpointAggregator
from toolwright.core.proposal.compiler import ProposalCompiler
from toolwright.models.capture import CaptureSession, HttpExchange, HTTPMethod


def _session_with_next_data_and_graphql() -> CaptureSession:
    return CaptureSession(
        id="cap_test_propose",
        name="proposal-test",
        allowed_hosts=["stockx.com"],
        exchanges=[
            HttpExchange(
                id="e1",
                url="https://stockx.com/_next/data/fz5n7pu8ao27rmx9abcde12345/en/buy/air-jordan-4-retro-rare-air-white-lettering.json",
                method=HTTPMethod.GET,
                host="stockx.com",
                path="/_next/data/fz5n7pu8ao27rmx9abcde12345/en/buy/air-jordan-4-retro-rare-air-white-lettering.json",
                response_status=200,
                response_headers={"Content-Type": "application/json"},
                response_body_json={"pageProps": {"slug": "air-jordan-4-retro-rare-air-white-lettering"}},
            ),
            HttpExchange(
                id="e2",
                url="https://stockx.com/_next/data/fz5n7pu8ao27rmx9abcde12345/en/buy/nike-dunk-low-panda.json",
                method=HTTPMethod.GET,
                host="stockx.com",
                path="/_next/data/fz5n7pu8ao27rmx9abcde12345/en/buy/nike-dunk-low-panda.json",
                response_status=200,
                response_headers={"Content-Type": "application/json"},
                response_body_json={"pageProps": {"slug": "nike-dunk-low-panda"}},
            ),
            HttpExchange(
                id="e3",
                url="https://stockx.com/api/graphql",
                method=HTTPMethod.POST,
                host="stockx.com",
                path="/api/graphql",
                request_headers={"Content-Type": "application/json"},
                request_body_json={
                    "operationName": "RecentlyViewedProducts",
                    "query": "query RecentlyViewedProducts { viewer { id } }",
                    "variables": {"slug": "air-jordan-4-retro-rare-air-white-lettering"},
                },
                response_status=200,
                response_headers={"Content-Type": "application/json"},
                response_body_json={"data": {"viewer": {"id": "user_1"}}},
            ),
            HttpExchange(
                id="e4",
                url="https://stockx.com/api/graphql",
                method=HTTPMethod.POST,
                host="stockx.com",
                path="/api/graphql",
                request_headers={"Content-Type": "application/json"},
                request_body_json={
                    "operationName": "UpdateBid",
                    "query": "mutation UpdateBid($id: ID!, $amount: Int!) { updateBid(id: $id, amount: $amount) { id } }",
                    "variables": {"id": "bid_1", "amount": 100},
                },
                response_status=200,
                response_headers={"Content-Type": "application/json"},
                response_body_json={"data": {"updateBid": {"id": "bid_1"}}},
            ),
        ],
    )


def test_build_endpoint_catalog_and_tool_proposals() -> None:
    session = _session_with_next_data_and_graphql()
    endpoints = EndpointAggregator(first_party_hosts=session.allowed_hosts).aggregate(session)

    compiler = ProposalCompiler()
    catalog = compiler.build_endpoint_catalog(
        capture_id=session.id,
        scope_name="first_party_only",
        endpoints=endpoints,
        session=session,
    )
    proposals = compiler.build_tool_proposals(catalog)
    questions = compiler.build_questions(catalog, proposals)

    next_family = next(
        family for family in catalog.families if family.path_template == "/_next/data/{token}/en/buy/{slug}.json"
    )
    param_names = {p.name for p in next_family.parameters}
    assert "token" in param_names
    assert "slug" in param_names
    token_param = next(p for p in next_family.parameters if p.name == "token")
    assert token_param.source.value == "derived"
    assert token_param.resolver is not None
    assert token_param.resolver.name == "nextjs_build_id"

    proposal_names = {proposal.name for proposal in proposals.proposals}
    assert "query_recently_viewed_products" in proposal_names
    assert "mutate_update_bid" in proposal_names

    query_proposal = next(p for p in proposals.proposals if p.name == "query_recently_viewed_products")
    assert query_proposal.kind.value == "graphql"
    assert query_proposal.fixed_body == {"operationName": "RecentlyViewedProducts"}
    assert query_proposal.operation_type == "query"

    mutate_proposal = next(p for p in proposals.proposals if p.name == "mutate_update_bid")
    assert mutate_proposal.operation_type == "mutation"
    assert mutate_proposal.risk_tier in {"high", "critical"}

    assert questions.questions
    assert any("capture" in q.prompt.lower() for q in questions.questions)


def test_graphql_operation_type_falls_back_to_name_when_query_missing() -> None:
    session = CaptureSession(
        id="cap_graphql_name_fallback",
        name="graphql-name-fallback",
        allowed_hosts=["stockx.com"],
        exchanges=[
            HttpExchange(
                id="e1",
                url="https://stockx.com/api/graphql",
                method=HTTPMethod.POST,
                host="stockx.com",
                path="/api/graphql",
                request_headers={"Content-Type": "application/json"},
                request_body_json={
                    "operationName": "RecentlyViewedProducts",
                    "variables": {"slug": "air-jordan-4-retro-rare-air-white-lettering"},
                },
                response_status=200,
                response_headers={"Content-Type": "application/json"},
                response_body_json={"data": {"viewer": {"id": "user_1"}}},
            ),
        ],
    )
    endpoints = EndpointAggregator(first_party_hosts=session.allowed_hosts).aggregate(session)

    compiler = ProposalCompiler()
    catalog = compiler.build_endpoint_catalog(
        capture_id=session.id,
        scope_name="first_party_only",
        endpoints=endpoints,
        session=session,
    )
    proposals = compiler.build_tool_proposals(catalog)

    query_proposal = next(p for p in proposals.proposals if p.name == "query_recently_viewed_products")
    assert query_proposal.operation_type == "query"
