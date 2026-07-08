# go-example — the five bugs in Go

A secondary-language mirror of `agent-loop-target`. Same five bugs, same
"failing test = done" contract, idiomatic Go.

| # | File | Category | Test |
|---|------|----------|------|
| 1 | `pagination.go` | off-by-one in a list operation | `pagination_test.go` |
| 2 | `grades.go` | wrong comparison operator | `grades_test.go` |
| 3 | `normalize.go` | missing edge case | `normalize_test.go` |
| 4 | `weather.go` | incorrect API response parsing | `weather_test.go` |
| 5 | `async_counter.go` | race condition (goroutines) | `async_counter_test.go` |

## Run the tests

```bash
cd go-example
go test ./...          # bugs 1-4 fail here
go test -race ./...    # also flags bug 5's data race deterministically
```

Always use `-race` so the concurrency bug is caught reliably — a data race may
"pass" by luck under a plain `go test`, but the race detector flags it every run.
"Done" = `go test -race ./...` is green.
