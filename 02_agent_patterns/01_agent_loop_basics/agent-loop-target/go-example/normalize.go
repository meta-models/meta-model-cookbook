package agentloop

// Normalize scales values into the range [0, 1] by dividing by the maximum.
//
// Edge cases the caller relies on:
//   - An empty slice returns an empty slice.
//   - If the maximum is 0 (e.g. all values are 0), every result is 0.0 rather
//     than producing NaN.
func Normalize(values []float64) []float64 {
	largest := values[0]
	for _, v := range values {
		if v > largest {
			largest = v
		}
	}
	out := make([]float64, len(values))
	for i, v := range values {
		out[i] = v / largest
	}
	return out
}
