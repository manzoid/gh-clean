## Optimizations for wall-clock speed

### Concurrent compare API calls

The ancestry check for base-only branches is one REST call per branch and the dominant time cost. Run these concurrently — 20 in flight is safe given GitHub's 100 concurrent request limit and 900 REST points/minute budget.

### Early exclusion filtering

Check protected branches config, default branch, and protection rules before doing PR joins or deferred checks. Every branch eliminated early is an API call skipped.

### Conditional PR pagination

Fetch OPEN and MERGED PRs first. Only fetch CLOSED PRs if there are branches with no open/merged head PR match. This avoids paginating through potentially large volumes of closed PRs that don't affect the outcome.

### GitHub secondary rate limits for reference

- 100 concurrent requests (REST + GraphQL combined)
- 900 REST points/minute
- 2,000 GraphQL points/minute
- Throttled with 403 or 429, `retry-after` header
