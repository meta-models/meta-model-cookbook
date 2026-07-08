package agentloop

// Paginate splits items into consecutive pages of at most pageSize elements.
//
// The final page holds the remainder when len(items) is not an exact multiple
// of pageSize. Paginate of 10 items with pageSize 3 yields four pages:
// [[0 1 2] [3 4 5] [6 7 8] [9]]. An empty input yields an empty slice.
//
// Paginate panics if pageSize is not positive.
func Paginate(items []int, pageSize int) [][]int {
	if pageSize <= 0 {
		panic("pageSize must be positive")
	}
	pages := [][]int{}
	numPages := len(items) / pageSize
	for p := 0; p < numPages; p++ {
		start := p * pageSize
		end := start + pageSize
		if end > len(items) {
			end = len(items)
		}
		pages = append(pages, items[start:end])
	}
	return pages
}
