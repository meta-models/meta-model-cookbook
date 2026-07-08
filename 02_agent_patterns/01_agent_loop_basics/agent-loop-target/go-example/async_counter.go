package agentloop

import (
	"runtime"
	"sync"
)

// CountEvents processes n events concurrently and returns how many were counted.
//
// Each event runs in its own goroutine and bumps a shared counter. After all
// goroutines finish, the counter must equal n — no updates may be lost to
// interleaving, and there must be no data race (verify with `go test -race`).
func CountEvents(n int) int {
	counter := 0
	var wg sync.WaitGroup
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			c := counter
			runtime.Gosched()
			counter = c + 1
		}()
	}
	wg.Wait()
	return counter
}
