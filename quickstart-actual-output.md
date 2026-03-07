# Quickstart Actual Output
# Captured: Sun Mar  1 22:04:12 EST 2026

## toolwright --version
toolwright, version 1.0.0a2

## Step 1: Install (already done)

## Step 2: Mint
```
$ toolwright mint https://github.com -a api.github.com --duration 120
```

(Interactive step — capture output manually, paste below)

## Step 3: Auth check
```
No toolpack found. Create one with:
  toolwright mint <url> -a <api-host>
  toolwright capture import <spec> -a <api-host>
```

## Step 4: Gate status (before approval)
```
No lockfile found at: /Users/thomasallicino/oss/toolwright/toolwright.lock.yaml
Run 'toolwright gate sync' first to create one.
```

## Step 4b: Gate allow
```
No lockfile found at: /Users/thomasallicino/oss/toolwright/toolwright.lock.yaml
```

## Step 4c: Gate status (after approval)
```
No lockfile found at: /Users/thomasallicino/oss/toolwright/toolwright.lock.yaml
Run 'toolwright gate sync' first to create one.
```

## Step 5: Serve (startup output only)
```
$ toolwright serve --scope repos
```
(Copy the startup card output, then Ctrl-C)

## Step 6: Config
```
Usage: toolwright config [OPTIONS]
Try 'toolwright config --help' for help.

Error: No toolpack found. Create one with:
  toolwright mint <url> -a <api-host>
  toolwright capture import <spec> -a <api-host>
```

## Other useful outputs

## groups list
```
No tool groups found. Run 'toolwright compile' to generate groups.
```

## status
```
No toolpack found. Create one with:
  toolwright mint <url> -a <api-host>
  toolwright capture import <spec> -a <api-host>
```

## rules template list
```
  crud-safety          Require reading a resource before destructive operations (3 rules)
  rate-control         Rate limits on write operations and session budgets (2 rules)
  retry-safety         Prevent agents from retrying failed calls unproductively (1 rules)
```

## recipes list
```
  github          GitHub REST API                          [api.github.com]
  notion          Notion API                               [api.notion.com]
  shopify         Shopify Admin REST API                   [*.myshopify.com]
  slack           Slack Web API                            [slack.com]
  stripe          Stripe API                               [api.stripe.com]
```
